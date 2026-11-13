"""AYON pickers on ComfyUI nodes: the AYON side.

The paired ComfyUI tab shows folder / product / version / representation
pickers on the `AYON Load ...` nodes (`js/ayon_pickers.js`). It asks this
AYON session for the lists to show and to load a picked representation
into a node, over the bridge (see `bridge_client.py`).

These are the only picker methods a tab can call; they are registered as
bridge handlers, which is the allow-list. Any JavaScript running on the
ComfyUI page can reach them through the paired tab, so:

- Queries are read-only, scoped to the session's current project (the tab
  can't choose another project) and return ids, names and version numbers,
  never file paths or people. (A loaded container may hold rootless
  `{root[...]}` paths when its node reads files by path; those are what
  ComfyUI resolves on its own server, not paths of this machine.)
- Every id is validated and checked to belong to its parent entity.
- Loading resolves the representation, the loader and the container here;
  nothing the tab sends ends up in a container except the container id of
  the node to load into. Loads are rate limited.
- Loading (the uploads) runs on one dedicated worker thread, so it never
  freezes the AYON tools, and the handler answers right away. The result
  is sent to the tab with `pickerApplied` from the Qt main thread: the tab
  then records the container in the AYON Context node, and the host's own
  read-modify-writes of that node (Loader, Scene Inventory, Creator) run
  on the main thread too, so the two can't interleave and lose an entry.
  `pickerApplied` is addressed by a token the tab chose, so the tab
  updates exactly the node that asked, also when the artist switched
  workflows in the meantime.
- `pickerApplied` is sent also while the bridge is busy, i.e. while a
  publish waits for its ComfyUI render, so artists can keep picking: the
  publish took the workflow it renders and saved the workfile it
  publishes before it started waiting, and the render runs the prompt
  queued then, so changing a node doesn't affect it (it is like the artist
  editing the graph meanwhile; it ends up in the next workfile version).
  The wait shows an application-modal window, so no Loader, Scene
  Inventory or Creator action runs meanwhile, and their read-modify-writes
  don't process Qt events, so they can't be interleaved either. Opening
  the AYON Loader for a node (`picker.browse`) does wait: that window
  couldn't be used before the render is done anyway.

Queries run on the bridge's worker threads and are cached for a minute
(`refresh` bypasses the cache; changing the AYON context clears it).
"""

from __future__ import annotations

import logging
import re
import threading
import time
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from functools import partial
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable

    from ayon_comfyui.api.bridge import ComfyUIBridge

log = logging.getLogger(__name__)

LOAD_NODE_TYPES = frozenset({
    "AYON Load Image",
    "AYON Load Video",
    "AYON Load 3D Model",
})
VERSION_MODES = frozenset({"latest", "pinned"})

CACHE_TTL = 60.0
# Entries a query cache keeps at most; its keys come from the tab.
MAX_CACHE_ITEMS = 2000
MAX_STATUS_ITEMS = 500
MAX_NAME_LENGTH = 255
# Queries a tab may make per minute, and how often it may bypass the cache.
MAX_QUERIES_PER_MINUTE = 600
MIN_REFRESH_INTERVAL = 5.0
# Loads (uploads) a tab may start per minute, how many may be queued or
# running at once (they run on the Qt main thread), one per node.
MAX_APPLIES_PER_MINUTE = 30
MAX_APPLIES_IN_FLIGHT = 2

_ENTITY_ID = re.compile(r"^[0-9a-f]{32}$")
_CONTAINER_UUID = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
)
_TOKEN = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


class PickerError(ValueError):
    """A picker request that can't be answered; the message is for artists."""


def _entity_id(params: dict, key: str, *, required: bool = True) -> str | None:
    value = params.get(key)
    if value in {None, ""} and not required:
        return None
    if not isinstance(value, str) or not _ENTITY_ID.match(value):
        msg = f"Invalid {key}."
        raise PickerError(msg)
    return value


def _node_type(params: dict) -> str:
    node_type = params.get("node_type")
    if node_type not in LOAD_NODE_TYPES:
        msg = f"AYON pickers don't support node type {node_type!r}."
        raise PickerError(msg)
    return node_type


def version_label(version: int) -> str:
    """Return how a version number is shown, e.g. `v003`."""
    return f"v{version:03d}"


class _Cache:
    """Thread-safe cache of query results with a time to live."""

    def __init__(self, ttl: float = CACHE_TTL) -> None:
        self._ttl = ttl
        self._lock = threading.Lock()
        self._items: dict[Any, tuple[float, Any]] = {}

    def get(
        self, key: Any, compute: Callable[[], Any], *, refresh: bool = False  # noqa: ANN401
    ) -> Any:  # noqa: ANN401
        now = time.monotonic()
        if not refresh:
            with self._lock:
                item = self._items.get(key)
            if item is not None and now - item[0] < self._ttl:
                return item[1]
        value = compute()
        with self._lock:
            self._items.pop(key, None)
            self._items[key] = (now, value)
            self._evict(now)
        return value

    def _evict(self, now: float) -> None:
        """Drop expired entries, then the oldest beyond MAX_CACHE_ITEMS."""
        items = self._items
        expired = [
            key for key, (at, _) in items.items() if now - at >= self._ttl
        ]
        for key in expired:
            del items[key]
        while len(items) > MAX_CACHE_ITEMS:
            # Dicts keep insertion order and entries are re-inserted when
            # updated, so the first one is the oldest.
            del items[next(iter(items))]

    def clear(self) -> None:
        with self._lock:
            self._items.clear()


def _default_project_name() -> str:
    from ayon_core.pipeline import get_current_project_name  # noqa: PLC0415

    return get_current_project_name()


def _default_representation_context(project_name: str, repre: dict) -> dict:
    from ayon_core.pipeline.load import (  # noqa: PLC0415
        get_representation_context,
    )

    return get_representation_context(project_name, repre)


def pick_node_loaders(loaders: Any) -> dict[str, type]:  # noqa: ANN401
    """Return the loader plugin of each load node type among `loaders`.

    Discovery also returns base classes imported into plugin modules (they
    are subclasses of LoaderPlugin too), so skip anything that isn't a
    concrete loader for a node type.
    """
    result = {}
    for loader in loaders:
        if loader.__dict__.get("skip_discovery") is True:
            continue
        node_type = getattr(getattr(loader, "load_type", None), "value", None)
        if node_type not in LOAD_NODE_TYPES or not hasattr(
            loader, "build_container"
        ):
            continue
        product_filter = (
            getattr(loader, "product_base_types", None)
            or getattr(loader, "product_types", None)
        )
        if not product_filter or not getattr(loader, "representations", None):
            continue
        result.setdefault(node_type, loader)
    return result


def _default_loaders() -> dict[str, type]:
    """Return the ComfyUI loader plugin for each load node type."""
    from ayon_core.pipeline.load import (  # noqa: PLC0415
        discover_loader_plugins,
    )

    return pick_node_loaders(discover_loader_plugins())


# Loader plugins don't change during a session: discover them once (the
# pickers warm this on the Qt main thread when they start).
_loaders_lock = threading.Lock()
_loaders: dict[str, type] | None = None


def loaders_by_node_type() -> dict[str, type]:
    """Return the ComfyUI loader plugin for each load node type.

    Discovered once and shared by the pickers and the Loader action; the
    Loader asks for every representation it lists.
    """
    global _loaders  # noqa: PLW0603
    with _loaders_lock:
        if _loaders is None:
            _loaders = _default_loaders()
        return _loaders


# --- "Open AYON Loader" for one node -----------------------------------------
#
# A node's "Open AYON Loader..." button makes it the load target of this
# session and opens the AYON Loader; its "Load into waiting ComfyUI node"
# action (`plugins/load/load_into_node.py`) loads the chosen representation
# into that node. One target at a time; it ends when it is used, when the
# Loader closes, or after LOAD_TARGET_TTL.

LOAD_TARGET_TTL = 30 * 60.0
MIN_BROWSE_INTERVAL = 1.0

_load_target_lock = threading.Lock()
_load_target: dict | None = None


def get_load_target() -> dict | None:
    """Return the node waiting for a representation from the Loader."""
    with _load_target_lock:
        target = _load_target
        if target and time.monotonic() - target["at"] > LOAD_TARGET_TTL:
            return None
        return dict(target) if target else None


def set_load_target(target: dict | None) -> dict | None:
    """Replace the load target; return the previous one."""
    global _load_target  # noqa: PLW0603
    with _load_target_lock:
        previous = _load_target
        _load_target = dict(target, at=time.monotonic()) if target else None
    return previous


def take_load_target(token: str | None = None) -> dict | None:
    """Return and end the load target (only `token`'s, when given)."""
    global _load_target  # noqa: PLW0603
    with _load_target_lock:
        target = _load_target
        if target is None or (token and target["token"] != token):
            return None
        _load_target = None
    if time.monotonic() - target["at"] > LOAD_TARGET_TTL:
        return None
    return target


class PickerService:
    """Answers the pickers' queries and loads picked representations.

    Args:
        api: The `ayon_api` module (or a stand-in for tests).
        project_name: Returns the session's current project.
        loaders: Returns the loader plugin class per load node type.
        representation_context: Returns the full context of a
            representation entity.
    """

    def __init__(
        self,
        api: Any = None,  # noqa: ANN401
        *,
        project_name: Callable[[], str] = _default_project_name,
        loaders: Callable[[], dict[str, type]] = loaders_by_node_type,
        representation_context: Callable[
            [str, dict], dict
        ] = _default_representation_context,
    ) -> None:
        if api is None:
            import ayon_api  # noqa: PLC0415

            api = ayon_api
        self._api = api
        self._project_name = project_name
        self._loaders = loaders
        self._representation_context = representation_context
        self._cache = _Cache()
        self._apply_lock = threading.Lock()
        self._apply_times: deque[float] = deque()
        self._applying: set[str] = set()
        self._last_browse = 0.0
        self._query_lock = threading.Lock()
        self._query_times: deque[float] = deque()
        self._last_refresh: dict[str, float] = {}

    def clear_cache(self) -> None:
        """Forget cached query results, e.g. after a context change."""
        self._cache.clear()

    # --- helpers ----------------------------------------------------------

    def _admit_query(self, method: str, params: dict) -> bool:
        """Rate limit queries; return whether to bypass the cache.

        Raises:
            PickerError: Too many queries in the last minute.
        """
        now = time.monotonic()
        with self._query_lock:
            times = self._query_times
            while times and now - times[0] > 60:
                times.popleft()
            if len(times) >= MAX_QUERIES_PER_MINUTE:
                msg = "Too many AYON queries in a short time, try again soon."
                raise PickerError(msg)
            times.append(now)
            if not params.get("refresh"):
                return False
            if now - self._last_refresh.get(method, -1e9) < (
                MIN_REFRESH_INTERVAL
            ):
                return False
            self._last_refresh[method] = now
            return True

    def _project(self) -> str:
        project_name = self._project_name()
        if not project_name:
            msg = "The AYON session has no current project."
            raise PickerError(msg)
        return project_name

    def _loader(self, node_type: str) -> type:
        loader = self._loaders().get(node_type)
        if loader is None:
            msg = f"No AYON loader is available for '{node_type}' nodes."
            raise PickerError(msg)
        return loader

    def _products(self, project_name: str, folder_id: str) -> list[dict]:
        return list(self._api.get_products(
            project_name,
            folder_ids=[folder_id],
            fields={"id", "name", "productType", "folderId"},
        ))

    def _versions(self, project_name: str, product_id: str) -> list[dict]:
        versions = list(self._api.get_versions(
            project_name,
            product_ids=[product_id],
            hero=False,
            fields={"id", "version", "productId"},
        ))
        versions.sort(key=lambda version: version["version"], reverse=True)
        return versions

    def _representations(
        self, project_name: str, version_id: str
    ) -> list[dict]:
        return list(self._api.get_representations(
            project_name,
            version_ids=[version_id],
            fields={"id", "name", "versionId", "context"},
        ))

    # --- queries (bridge worker threads) ----------------------------------

    def folders(self, params: dict) -> dict:
        """Folders that have products, by path."""
        refresh = self._admit_query("folders", params)
        project_name = self._project()

        def _query() -> list[dict]:
            folders = [
                {"id": folder["id"], "path": folder["path"]}
                for folder in self._api.get_folders(
                    project_name,
                    has_products=True,
                    fields={"id", "path"},
                )
            ]
            folders.sort(key=lambda folder: folder["path"].lower())
            return folders

        folders = self._cache.get(
            ("folders", project_name), _query, refresh=refresh
        )
        return {"project_name": project_name, "folders": folders}

    def options(self, params: dict) -> dict:
        """The products of a folder, versions of a product, and the
        representations of a version that the node type can load.

        Params: `node_type`, `folder_id`, optional `product_id` and
        `version_id` (the latest version when not given), `refresh`.
        """
        refresh = self._admit_query("options", params)
        project_name = self._project()
        node_type = _node_type(params)
        folder_id = _entity_id(params, "folder_id")
        product_id = _entity_id(params, "product_id", required=False)
        version_id = _entity_id(params, "version_id", required=False)
        loader = self._loader(node_type)

        products = self._cache.get(
            ("products", project_name, folder_id),
            partial(self._products, project_name, folder_id),
            refresh=refresh,
        )
        product_filter = set(
            getattr(loader, "product_base_types", None)
            or getattr(loader, "product_types", None)
            or ()
        )
        if "*" not in product_filter:
            products = [
                product for product in products
                if product.get("productType") in product_filter
            ]
        result = {
            "products": sorted(
                (
                    {
                        "id": product["id"],
                        "name": product["name"],
                        "product_type": product.get("productType"),
                    }
                    for product in products
                ),
                key=lambda product: product["name"].lower(),
            ),
            "versions": [],
            "version_id": None,
            "representations": [],
        }
        if product_id is None:
            return result

        product = next(
            (item for item in products if item["id"] == product_id), None
        )
        if product is None:
            msg = "The product isn't in this folder, or can't be loaded here."
            raise PickerError(msg)

        versions = self._cache.get(
            ("versions", project_name, product_id),
            partial(self._versions, project_name, product_id),
            refresh=refresh,
        )
        result["versions"] = [
            {
                "id": version["id"],
                "version": version["version"],
                "label": version_label(version["version"]),
            }
            for version in versions
        ]
        if not versions:
            return result
        if version_id is None:
            version_id = versions[0]["id"]
        elif not any(version["id"] == version_id for version in versions):
            # E.g. the product's hero version, which isn't listed.
            version = self._api.get_version_by_id(project_name, version_id)
            if not version or version.get("productId") != product_id:
                msg = "The version doesn't belong to the product."
                raise PickerError(msg)
        result["version_id"] = version_id

        representations = self._cache.get(
            ("representations", project_name, version_id),
            partial(self._representations, project_name, version_id),
            refresh=refresh,
        )
        result["representations"] = sorted(
            (
                {"id": repre["id"], "name": repre["name"]}
                for repre in representations
                if loader.is_compatible_loader(
                    {"product": product, "representation": repre}
                )
            ),
            key=lambda repre: repre["name"].lower(),
        )
        return result

    def status(self, params: dict) -> dict:
        """Describe what load nodes load, by representation id.

        Params: `representation_ids` (list). Returns, per id, the folder,
        product, version and representation (ids and labels) plus the
        product's latest version, or `missing` naming the first entity
        that no longer exists.
        """
        self._admit_query("status", params)
        project_name = self._project()
        ids = params.get("representation_ids")
        if not isinstance(ids, list) or len(ids) > MAX_STATUS_ITEMS:
            msg = "Invalid representation_ids."
            raise PickerError(msg)
        repre_ids = {
            repre_id for repre_id in ids
            if isinstance(repre_id, str) and _ENTITY_ID.match(repre_id)
        }
        if not repre_ids:
            return {"project_name": project_name, "items": {}}

        api = self._api
        repres = {
            repre["id"]: repre
            for repre in api.get_representations(
                project_name,
                representation_ids=repre_ids,
                fields={"id", "name", "versionId"},
            )
        }
        version_ids = {repre["versionId"] for repre in repres.values()}
        versions = {
            version["id"]: version
            for version in api.get_versions(
                project_name,
                version_ids=version_ids,
                fields={"id", "version", "productId"},
            )
        } if version_ids else {}
        product_ids = {version["productId"] for version in versions.values()}
        products = {
            product["id"]: product
            for product in api.get_products(
                project_name,
                product_ids=product_ids,
                fields={"id", "name", "folderId"},
            )
        } if product_ids else {}
        folder_ids = {product["folderId"] for product in products.values()}
        folders = {
            folder["id"]: folder
            for folder in api.get_folders(
                project_name, folder_ids=folder_ids, fields={"id", "path"}
            )
        } if folder_ids else {}
        last_versions = api.get_last_versions(
            project_name, product_ids, fields={"id", "version", "productId"}
        ) if product_ids else {}

        items = {}
        for repre_id in repre_ids:
            repre = repres.get(repre_id)
            version = repre and versions.get(repre["versionId"])
            product = version and products.get(version["productId"])
            folder = product and folders.get(product["folderId"])
            if not repre:
                items[repre_id] = {"missing": "representation"}
                continue
            if not (version and product and folder):
                items[repre_id] = {"missing": "version"}
                continue
            last = last_versions.get(product["id"]) or version
            items[repre_id] = {
                "folder_id": folder["id"],
                "folder_path": folder["path"],
                "product_id": product["id"],
                "product_name": product["name"],
                "version_id": version["id"],
                "version": version["version"],
                "representation_id": repre["id"],
                "representation_name": repre["name"],
                "latest_version_id": last["id"],
                "latest_version": last["version"],
            }
        return {"project_name": project_name, "items": items}

    # --- loading ------------------------------------------------------------

    def validate_browse(self, params: dict) -> dict:
        """Check an "Open AYON Loader" request from the tab."""
        token = params.get("token")
        if not isinstance(token, str) or not _TOKEN.match(token):
            msg = "Invalid token."
            raise PickerError(msg)
        container_uuid = params.get("container_uuid")
        if container_uuid in {None, ""}:
            container_uuid = None
        elif not (
            isinstance(container_uuid, str)
            and _CONTAINER_UUID.match(container_uuid)
        ):
            msg = "Invalid container_uuid."
            raise PickerError(msg)
        node_type = _node_type(params)
        reference = params.get("reference", False)
        if not isinstance(reference, bool):
            msg = "Invalid reference."
            raise PickerError(msg)
        now = time.monotonic()
        with self._apply_lock:
            if now - self._last_browse < MIN_BROWSE_INTERVAL:
                msg = "The AYON Loader is opening."
                raise PickerError(msg)
            self._last_browse = now
        return {
            "token": token,
            "node_type": node_type,
            "container_uuid": container_uuid,
            "reference": reference,
        }

    def validate_apply(self, params: dict) -> dict:
        """Check a load request from the tab and reserve its node.

        Raises:
            PickerError: The request is invalid or too many loads ran.
        """
        token = params.get("token")
        if not isinstance(token, str) or not _TOKEN.match(token):
            msg = "Invalid token."
            raise PickerError(msg)
        container_uuid = params.get("container_uuid")
        if container_uuid in {None, ""}:
            container_uuid = None
        elif not (
            isinstance(container_uuid, str)
            and _CONTAINER_UUID.match(container_uuid)
        ):
            msg = "Invalid container_uuid."
            raise PickerError(msg)
        version_mode = params.get("version_mode")
        if version_mode not in VERSION_MODES:
            msg = "Invalid version_mode."
            raise PickerError(msg)
        representation_name = params.get("representation_name")
        if not (
            isinstance(representation_name, str)
            and 0 < len(representation_name) <= MAX_NAME_LENGTH
        ):
            msg = "Invalid representation_name."
            raise PickerError(msg)
        # Whether the node references its files by path (it keeps doing
        # so when the server can read them; see `load_util`).
        reference = params.get("reference", False)
        if not isinstance(reference, bool):
            msg = "Invalid reference."
            raise PickerError(msg)
        request = {
            "token": token,
            "node_type": _node_type(params),
            "container_uuid": container_uuid,
            "product_id": _entity_id(params, "product_id"),
            "version_mode": version_mode,
            "version_id": _entity_id(
                params, "version_id", required=version_mode == "pinned"
            ),
            "representation_name": representation_name,
            "reference": reference,
        }

        now = time.monotonic()
        key = container_uuid or token
        with self._apply_lock:
            while self._apply_times and now - self._apply_times[0] > 60:
                self._apply_times.popleft()
            if len(self._apply_times) >= MAX_APPLIES_PER_MINUTE:
                msg = "Too many AYON loads in a short time, try again soon."
                raise PickerError(msg)
            if len(self._applying) >= MAX_APPLIES_IN_FLIGHT:
                msg = "AYON is busy loading, try again in a moment."
                raise PickerError(msg)
            if key in self._applying:
                msg = "AYON is still loading into this node."
                raise PickerError(msg)
            self._apply_times.append(now)
            self._applying.add(key)
        request["_key"] = key
        return request

    def release(self, request: dict) -> None:
        """Allow loading into the request's node again."""
        with self._apply_lock:
            self._applying.discard(request.get("_key"))

    def apply(self, request: dict) -> dict:
        """Upload the picked representation; return the node's container.

        Runs on the pickers' load worker thread. Does not touch the graph:
        the tab puts the container on the node that asked.
        """
        project_name = self._project()
        api = self._api
        product_id = request["product_id"]
        product = api.get_product_by_id(project_name, product_id)
        if not product:
            msg = "The product no longer exists in AYON."
            raise PickerError(msg)

        if request["version_mode"] == "latest":
            version = api.get_last_version_by_product_id(
                project_name, product_id
            )
            if not version:
                msg = f"{product['name']} has no versions."
                raise PickerError(msg)
        else:
            version = api.get_version_by_id(
                project_name, request["version_id"]
            )
            if not version or version.get("productId") != product_id:
                msg = "The version no longer exists in AYON."
                raise PickerError(msg)

        repre_name = request["representation_name"]
        repre = api.get_representation_by_name(
            project_name, repre_name, version["id"]
        )
        if not repre:
            msg = (
                f"{product['name']} {version_label(version['version'])} "
                f"has no '{repre_name}' representation."
            )
            raise PickerError(msg)

        context = self._representation_context(project_name, repre)
        loader_cls = self._loader(request["node_type"])
        if not loader_cls.is_compatible_loader(context):
            msg = (
                f"'{repre_name}' of {product['name']} can't be loaded by "
                f"an {request['node_type']} node."
            )
            raise PickerError(msg)

        loader = loader_cls(context)
        return loader.build_container(
            context,
            name=product["name"],
            namespace=context["folder"]["name"],
            container_uuid=request["container_uuid"],
            version_mode=request["version_mode"],
            reference=request.get("reference", False),
        )


# Errors for a node that waits for the Loader; the tab shows them quietly.
LOADER_TARGET_REPLACED = "The AYON Loader was opened for another node."
LOADER_CLOSED = "The AYON Loader was closed."


_CLOSE_FILTER_PROPERTY = "ayon_comfyui_picker_close_filter"


def artist_error(exc: Exception) -> str:
    """Return what to tell the ComfyUI tab about a failed load.

    Only our own messages are passed on; anything else can contain file
    paths or server addresses, which stay in the AYON log.
    """
    if isinstance(exc, PickerError) or type(exc).__name__ == "LoadError":
        return str(exc)
    return "Loading failed, see the AYON log for details."


def open_loader() -> Any:  # noqa: ANN401
    """Show the AYON Loader (on the Qt main thread); return its window."""
    from ayon_core.tools.utils import host_tools  # noqa: PLC0415

    return host_tools.show_loader(use_context=True)


def register_picker_handlers(
    bridge: ComfyUIBridge, service: PickerService | None = None
) -> PickerService:
    """Let the paired tab use the AYON pickers of this session."""
    if service is None:
        service = PickerService()
    client = bridge.client
    # Loads (uploads) run one at a time off the Qt main thread.
    load_worker = ThreadPoolExecutor(
        max_workers=1, thread_name_prefix="AYON-ComfyUI-picker-load"
    )

    def _warm_loaders() -> None:
        try:
            loaders_by_node_type()
        except Exception:  # noqa: BLE001
            log.warning(
                "Unable to discover the ComfyUI loaders", exc_info=True
            )

    # Discovery applies settings to the plugin classes: do it once, on the
    # Qt main thread, before the pickers or the Loader need it.
    bridge.run_in_main_thread(_warm_loaders)

    def _query(func: Callable[[dict], dict]) -> Callable[[dict], dict]:
        def _handler(params: dict) -> dict:
            try:
                return func(params)
            except PickerError:
                raise
            except Exception as exc:
                # The details (server URL, paths) stay in the AYON log.
                log.warning("AYON picker query failed", exc_info=True)
                msg = "The AYON query failed, see the AYON log for details."
                raise PickerError(msg) from exc

        return _handler

    def _apply(params: dict) -> dict:
        request = service.validate_apply(params)
        try:
            load_worker.submit(_run_apply, request)
        except Exception:
            service.release(request)
            raise
        return {"scheduled": True}

    def _run_apply(request: dict) -> None:
        container = None
        error = None
        try:
            container = service.apply(request)
        except Exception as exc:  # noqa: BLE001
            error = artist_error(exc)
            log.warning("AYON picker load failed", exc_info=True)
        finally:
            service.release(request)
        # The tab writes the container into the AYON Context node when it
        # gets it: send it from the Qt main thread, where the host's own
        # read-modify-writes of that node run, so they never interleave.
        # Don't hold it back while a publish waits for its render (see the
        # notes at the top): the tab could give up waiting meanwhile.
        bridge.run_in_main_thread(
            partial(_send_applied, request["token"], container, error),
            while_busy=True,
        )

    def _send_applied(
        token: str, container: dict | None, error: str | None
    ) -> None:
        try:
            bridge.stub.picker_applied(token, container=container, error=error)
        except Exception:  # noqa: BLE001
            log.warning(
                "Unable to send the loaded container to ComfyUI",
                exc_info=True,
            )

    client.register_handler("picker.folders", _query(service.folders))
    client.register_handler("picker.options", _query(service.options))
    client.register_handler("picker.status", _query(service.status))
    client.register_handler("picker.apply", _apply)

    def _browse(params: dict) -> dict:
        request = service.validate_browse(params)
        # Waits while the bridge is busy: during a publish render only the
        # render's progress window takes input.
        bridge.run_in_main_thread(partial(_open_loader, request))
        return {"scheduled": True}

    def _notify(token: str, error: str) -> None:
        try:
            bridge.stub.picker_applied(token, error=error)
        except Exception:  # noqa: BLE001
            log.debug("Unable to notify the ComfyUI tab", exc_info=True)

    def _open_loader(request: dict) -> None:
        previous = set_load_target(request)
        if previous and previous["token"] != request["token"]:
            _notify(previous["token"], LOADER_TARGET_REPLACED)
        try:
            window = open_loader()
        except Exception as exc:  # noqa: BLE001
            log.warning("Unable to open the AYON Loader", exc_info=True)
            take_load_target(request["token"])
            _notify(request["token"], artist_error(exc))
            return
        _watch_loader_close(window)

    def _watch_loader_close(window: Any) -> None:  # noqa: ANN401
        """End the load target when the Loader window closes."""
        if window is None or window.property(_CLOSE_FILTER_PROPERTY):
            return
        from qtpy import QtCore  # noqa: PLC0415

        class _CloseFilter(QtCore.QObject):
            def eventFilter(self, obj, event):  # noqa: ANN001, ANN202, N802, PLR6301
                if event.type() == QtCore.QEvent.Close:
                    target = take_load_target()
                    if target:
                        _notify(target["token"], LOADER_CLOSED)
                return False

        window.installEventFilter(_CloseFilter(window))
        window.setProperty(_CLOSE_FILTER_PROPERTY, True)

    client.register_handler("picker.browse", _browse)

    def _on_context_changed(*_args: Any) -> None:  # noqa: ANN401
        service.clear_cache()
        try:
            bridge.stub.picker_invalidate()
        except Exception:  # noqa: BLE001
            log.debug("Unable to refresh the pickers", exc_info=True)

    try:
        from ayon_core.lib import register_event_callback  # noqa: PLC0415

        register_event_callback("taskChanged", _on_context_changed)
    except Exception:  # noqa: BLE001
        log.debug("Unable to track context changes", exc_info=True)
    return service
