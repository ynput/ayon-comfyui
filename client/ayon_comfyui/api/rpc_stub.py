"""Calls into the paired ComfyUI tab, through the AYON bridge."""

from __future__ import annotations

import contextlib
import contextvars
import inspect
import json
import logging
import sys
from enum import Enum
from functools import wraps
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ayon_core.pipeline import get_current_context

from ayon_comfyui.api.consts import LOG_LEVEL

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator, MutableMapping

    from ayon_comfyui.api.bridge_client import BridgeClient

logging.basicConfig(force=True, stream=sys.stdout, level=LOG_LEVEL)
log = logging.getLogger("ayon_comfyui")

DEFAULT_CALL_TIMEOUT = 20.0

# The ComfyUI workflow (tab) the tab calls act on, see `target_workflow`.
_TARGET: contextvars.ContextVar[dict | None] = contextvars.ContextVar(
    "ayon_comfyui_workflow_target", default=None
)


@contextlib.contextmanager
def target_workflow(target: dict | None) -> Iterator[None]:
    """Make the tab calls in this block act on the workflow `target`.

    By default a tab call acts on the active ComfyUI workflow (tab). Within
    this block it acts on the workflow `target` (`{workflow_key,
    workflow_label}`, see `RPCStub.get_workflow_target`) instead, also when
    the artist switched to another tab meanwhile: e.g. publishing keeps
    acting on the workflow it collected. Calls that need the live graph
    (adding nodes, converting it to a prompt) then fail with code
    `workflow_inactive` while it isn't active, and every call fails with
    `workflow_closed` once its tab is closed.

    `None` acts on the active workflow again. Keep the block to the calls:
    what the Qt event loop runs meanwhile (e.g. a nested loop) would act on
    `target` too.
    """
    token = _TARGET.set(dict(target) if target else None)
    try:
        yield
    finally:
        _TARGET.reset(token)


def current_workflow_target() -> dict | None:
    """Return the workflow the tab calls act on now, None for the active."""
    return _TARGET.get()


def tab_method(*, timeout: float | None = DEFAULT_CALL_TIMEOUT) -> Callable:
    """Turn a method stub into a call of the same name in the ComfyUI tab.

    The arguments (with their defaults applied) become the call's params.
    `timeout=None` waits until the tab answers or disconnects.
    """

    def _decorator(func: Callable) -> Callable:
        signature = inspect.signature(func)

        @wraps(func)
        def _call(self: RPCClientStub, *args: Any, **kwargs: Any) -> Any:  # noqa: ANN401
            bound = signature.bind(self, *args, **kwargs)
            bound.apply_defaults()
            params = dict(bound.arguments)
            params.pop("self")
            target = _TARGET.get()
            if target:
                params.setdefault("workflow_key", target.get("workflow_key"))
                params.setdefault(
                    "workflow_label", target.get("workflow_label")
                )
            return self.client.call(func.__name__, params, timeout=timeout)

        return _call

    return _decorator


# Enum types for types of publish/load nodes.
class PublishType(Enum):
    """Correspond to custom AYON node IDs."""

    IMAGE = "AYON Image Save"
    VIDEO = "AYON Video Save"
    MODEL3D = "AYON 3D Model Save"


class LoadType(Enum):
    """Corresponds to custom AYON image loader nodes."""

    IMAGE = "AYON Load Image"
    VIDEO = "AYON Load Video"
    MODEL3D = "AYON Load 3D Model"
    ALL = "ALL"


class RPCClientStub:  # noqa: PLR0904
    """Methods of the paired ComfyUI tab (see `ayon_menu.js`).

    Also provides helper methods to process results.

    DO NOT USE DIRECTLY. These are meant to be used in RPCStub.
    """

    def __init__(self, client: BridgeClient) -> None:  # noqa: D107
        self.client = client

    # def do_update_publishnodes(self) -> None: # Never used

    @tab_method()
    def getWorkfile(self):  # noqa: N802, ANN201
        """Call getWorkfile."""

    @tab_method()
    def loadWorkfile(  # noqa: N802, ANN201
        self,
        *,
        workfile_json: str,
        workfile_name: str,
        workfile_path: str | None = None,
    ):
        """Call loadWorkfile.

        When `workfile_path` is passed it is stored in the loaded graph as
        `extra.AYON.workfile_path` to track the current AYON workfile.
        """

    def do_load_workfile(self, workfile_path: str | None = None) -> None:
        """Load contents of workfile into ComfyUI session."""
        if not workfile_path:
            return

        workfile_json = (workfile := Path(workfile_path)).read_text(
            encoding="utf-8"
        )
        self.loadWorkfile(
            workfile_json=workfile_json,
            workfile_name=workfile.name,
            workfile_path=str(workfile),
        )

    @tab_method()
    def getImprintContext(self) -> str:  # noqa: N802
        """Call getImprintContext."""

    @tab_method()
    def setImprintContext(self, *, imprint_info: str) -> bool:  # noqa: N802, ANN201
        """Call setImprintContext."""

    @tab_method()
    def setGraphExtra(self, *, extra_json: str):  # noqa: N802, ANN201
        """Call setGraphExtra.

        Merges arbitrary extra metadata into the current graph.extra.
        """

    @tab_method()
    def beginSaveWorkfile(  # noqa: N802, ANN201
        self,
        *,
        workfile_path: str,
        workflow_name: str | None = None,
        in_place: bool = False,
    ):
        """Call beginSaveWorkfile.

        Renames the active ComfyUI workflow (tab) to `workflow_name`, stores
        `workfile_path` in the graph and returns a dict with the serialized
        graph (`workfile`), the ComfyUI workflow path (`comfy_workflow_path`)
        and a list of `warnings`. Or a dict with an `error` when the active
        workflow must not be saved to `workfile_path`.
        """

    @tab_method()
    def finishSaveWorkfile(  # noqa: N802, ANN201
        self,
        *,
        comfy_workflow_path: str | None = None,
        snapshot: bool = False,
    ):
        """Call finishSaveWorkfile.

        Saves the ComfyUI workflow internally so it's no longer flagged as
        modified. Returns whether it was saved. With `snapshot`, only when
        the workflow still is exactly what `getApiPrompt(snapshot=True)`
        collected (the host wrote that to the workfile).
        """

    @tab_method()
    def getWorkflowTarget(self) -> dict:  # noqa: N802
        """Call getWorkflowTarget.

        Returns `{workflow_key, workflow_label}` of the active workflow, or
        of the targeted one.
        """

    @tab_method()
    def getQueueExtraData(self) -> dict:  # noqa: N802
        """Call getQueueExtraData.

        Returns the `extra_data` the tab adds when it queues a prompt
        (Comfy.org credentials: never store or log it).
        """

    @tab_method()
    def getWorkfilePath(self):  # noqa: N802, ANN201
        """Call getWorkfilePath.

        Returns stored workfile path metadata from active graph, or null.
        """

    @tab_method()
    def getGraphExtra(self, *, key: str | None = None):  # noqa: N802, ANN201
        """Call getGraphExtra.

        Returns stringified JSON of graph.extra (or {}), or of only
        graph.extra[key] when `key` is passed.
        """

    def do_context_imprint(self, imprint_info: str = "No imprint.") -> bool:
        """Creates a node in the browser session.

        Returns:
            True/False based on whether operation was successful
        """
        # Massage info to fit into a scheme
        # {
        #   "context" : {**context_imprint_info},
        #   "instances": [
        #       {
        #           "id" : ...,
        #           "images": ...,
        #       },
        #   ],
        # }

        # retrieve and set the context.
        existing_context = self.getImprintContext()

        # ensure valid context
        if existing_context is not None and existing_context:
            existing_context = json.loads(existing_context)
        else:
            existing_context = {}

        existing_context = self._ensure_wellformed_context(existing_context)

        # update context by overwriting
        existing_context["context"] = json.loads(imprint_info)

        return self.setImprintContext(
            imprint_info=json.dumps(existing_context)
        )

    def do_instances_imprint(self, imprint_info: str = "[]") -> bool:
        """Updates (replaces) "instances" field of context node.

        Returns:
            True/False based on whether operation was successful
        """
        # Massage info to fit into a scheme
        # {
        #   "context" : {**context_imprint_info},
        #   "instances": [
        #       {
        #           "id" : ...,
        #           "images": ...,
        #       },
        #   ],
        # }

        # retrieve and set the context.
        existing_context = self.getImprintContext()

        # ensure valid context
        if existing_context is not None and existing_context:
            existing_context = json.loads(existing_context)
        else:
            existing_context = {}

        existing_context = self._ensure_wellformed_context(existing_context)

        log.debug("updating info")
        # update context by overwriting
        existing_context["instances"] = json.loads(imprint_info)

        log.debug("imprinting")
        result = self.setImprintContext(
            imprint_info=json.dumps(existing_context),
        )

        if result:
            return result

        return None

    def do_containers_imprint(self, imprint_info: str = "[]") -> bool:
        """Updates (replaces) "containers" field of context node.

        Returns:
            True/False based on whether operation was successful
        """
        # Massage info to fit into a scheme
        # {
        #   "context" : {**context_imprint_info},
        #   "instances": [
        #       {
        #           "id" : ...,
        #           "images": ...,
        #       },
        #   ],
        #   "containers": [
        #       {
        #        "id": ...,
        #        "name": ...,
        #       },
        #   ],
        # }

        # retrieve and set the context.
        existing_context = self.getImprintContext()

        # ensure valid context
        if existing_context is not None and existing_context:
            existing_context = json.loads(existing_context)
        else:
            existing_context = {}

        existing_context = self._ensure_wellformed_context(existing_context)

        log.debug("updating info")
        # update context by overwriting
        existing_context["containers"] = json.loads(imprint_info)

        log.debug("imprinting containers")
        result = self.setImprintContext(
            imprint_info=json.dumps(existing_context),
        )

        if result:
            return result

        return None

    @tab_method()
    def addPublishNode(self, *, instance_json: str, node_type: str):  # noqa: N802, ANN201
        """Call addPublishNode."""

    async def do_publishnode_create(
        self, instance_json: str, node_type: PublishType = PublishType.IMAGE
    ) -> None:
        """Helper for creator to create a Ayon [Type] Save node.

        TODO(@sas): just call addPublishnode directly.
        """
        self.addPublishNode(
            instance_json=instance_json, node_type=node_type.value
        )

    @tab_method()
    def removePublishNodes(self, *, ids_to_remove: str, node_type: str) -> str:  # noqa: N802
        """Call removePublishNodes.

        ids_to_remove has to contain a json list of instance ids associated
        with publish instances to remove.

        Returns a string json representation of instances that were removed.
        """

    @tab_method(timeout=60.0)
    def getApiPrompt(self, *, snapshot: bool = False) -> dict:  # noqa: N802
        """Call getApiPrompt.

        Returns the workflow converted to an API-format prompt by the
        frontend (`prompt`), the UI workflow (`workflow`), the tab's
        ComfyUI client id (`client_id`), the workflow's identity
        (`workflow_key`, `workflow_label`, `workflow_id`,
        `workflow_path`), its AYON workfile (`workfile_path`, and
        `workfile_open_in`: another tab with it open) and the `extra_data`
        the tab would queue it with (`extra_data`, including its Comfy.org
        credentials: never store or log it).
        """

    @tab_method()
    def getQueuedPrompts(self) -> dict:  # noqa: N802
        """Call getQueuedPrompts.

        Returns `prompts`: `{prompt_id, workflow_path}` of the prompts the
        tab queued, newest first.
        """

    @tab_method()
    def addLoadProductNode(  # noqa: N802
        self, *, container_json: str, node_type: str
    ) -> None:
        """Call addLoadProductNode.

        container_json has to contain a single image container dict serialized
        as json. This will be imprinted on the node.
        Make sure to upload the image before uploading.
        """

    @tab_method()
    def removeLoadProductNodes(  # noqa: N802
        self, *, ids_to_remove: str, node_type: str
    ) -> None:
        """Call removeLoadProductNodes.

        ids_to_remove has to contain a json list of container uuids associated
        with containers to remove.

        Returns a string json representation of containers that were removed.
        """

    @tab_method()
    def updateLoadProductNode(  # noqa: N802
        self, *, container_json: str, node_type: str = "ALL"
    ) -> None:
        """Call updateLoadProductNode.

        Uses the container_json container_uuid
        to match nodes present in the scene.

        Sentinel value ALL will match for all types of container nodes.
        """

    def do_context_retrieve(self) -> str:
        """Creates a context node in the browser session if not present.

        Fills context node with context info.

        Returns:
            Optional[Dict[str, Any]] of context
        """
        result = self.getImprintContext()

        if result:
            context = result
            context = context or json.dumps({})
            try:
                context = json.loads(context)
            except json.JSONDecodeError as e:
                log.debug(f"Error loading json ctx: {e}")  # noqa: G004
                context = {}
            context = self._ensure_wellformed_context(context)
            return json.dumps(context)

        return None

    @staticmethod
    def _ensure_wellformed_context(context: dict) -> dict:
        """Basic data integrity.

        Returns:
            a dict[str, Any] with expected keys.
        """
        if context.get("context") is None:
            context["context"] = {}

        if context.get("instances") is None:
            context["instances"] = []

        if context.get("containers") is None:
            context["containers"] = []

        return context


def _publisher_scoped(func: Callable) -> Callable:
    """Act on the workflow whose instances the Publisher shows.

    See `RPCStub.pin_publisher_workflow`. An explicit `target_workflow`
    still wins.
    """

    @wraps(func)
    def _wrapper(self: RPCStub, *args: Any, **kwargs: Any) -> Any:  # noqa: ANN401
        with self.publisher_target():
            return func(self, *args, **kwargs)

    return _wrapper


class RPCStub:  # noqa : PLR0904
    """Wrapper to expose client functionality.

    Exposes client calls in a sane way to the plugin.
    """

    target_workflow = staticmethod(target_workflow)

    def __init__(self, client: BridgeClient) -> None:  # noqa: D107
        self.client_stub = RPCClientStub(client)
        # The workflow whose instances the Publisher shows, see
        # `pin_publisher_workflow`.
        self.publisher_workflow: dict | None = None

    def get_workflow_target(self) -> dict | None:
        """Return `{workflow_key, workflow_label}` of the active workflow.

        Or of the targeted one (see `target_workflow`). None when the tab
        can't tell (an older frontend without a workflow store).
        """
        result = self.client_stub.getWorkflowTarget()
        if not isinstance(result, dict) or not result.get("workflow_key"):
            return None
        return {
            "workflow_key": result["workflow_key"],
            "workflow_label": result.get("workflow_label"),
        }

    def pin_publisher_workflow(self) -> dict | None:
        """Pin the active workflow for the Publisher's instances.

        Called when a Publisher (CreateContext) resets: until it resets
        again, reading and writing its instances and context data acts on
        this workflow, also after the artist switched tabs, rather than
        writing them into another workflow.
        """
        try:
            with target_workflow(None):
                target = self.get_workflow_target()
        except Exception:  # noqa: BLE001
            log.debug("Unable to get the active workflow", exc_info=True)
            target = None
        self.publisher_workflow = target
        return target

    @contextlib.contextmanager
    def publisher_target(self) -> Iterator[None]:
        """Target the Publisher's workflow, unless a target is set already."""
        if _TARGET.get() is not None or not self.publisher_workflow:
            yield
            return
        with target_workflow(self.publisher_workflow):
            yield

    def query_workfile(self) -> str:
        """Query workfile.

        Returns:
            String JSON of Workfile from ComfyUI.
        """
        log.debug("query_workfile")
        return self.client_stub.getWorkfile()

    def load_workfile(self, path: str) -> None:
        """Query load workfile operation."""
        log.debug("load_workfile")
        self.client_stub.do_load_workfile(path)

    @_publisher_scoped
    def imprint_context(self, data: dict) -> None:
        """Query imprint contect operation."""
        log.debug(f"imprint_context\n{data}")  # noqa: G004
        json_data = json.dumps(data)
        log.debug(json_data)
        self.client_stub.do_context_imprint(imprint_info=json_data)

    def set_graph_extra(self, extra: dict) -> bool:
        """Set arbitrary extra metadata on the currently opened graph.

        The extra dict will be merged into graph.extra on the client side.
        Returns True on success, None/False on failure.
        """
        log.debug(f"set_graph_extra\n{extra}")  # noqa: G004
        try:
            json_data = json.dumps(extra)
            result = self.client_stub.setGraphExtra(extra_json=json_data)
            return result
        except Exception as e:  # noqa: BLE001
            log.debug(f"set_graph_extra failed: {e}")  # noqa: G004
            return None

    def save_workfile(self, path: str, *, in_place: bool = False) -> None:
        """Save the active ComfyUI workflow as AYON workfile to `path`.

        The active workflow (tab) is renamed to match the filename, the path
        is stored in the graph so `get_workfile_path` reports it, the graph
        is written to disk and finally saved in ComfyUI as well so the tab
        is no longer flagged as modified.

        Args:
            path: The workfile path to save to.
            in_place: Only save when `path` still is the workfile of the
                active workflow, e.g. because the user may have switched tabs
                since it was queried.

        Raises:
            RuntimeError: When the graph could not be retrieved from ComfyUI
                or ComfyUI refused to save the active workflow to `path`, e.g.
                because another tab has that workfile open.
        """
        log.debug(f"save_workfile: {path}")  # noqa: G004
        result = self.client_stub.beginSaveWorkfile(
            workfile_path=path,
            workflow_name=Path(path).stem,
            in_place=in_place,
        )
        if isinstance(result, dict) and result.get("error"):
            raise RuntimeError(result["error"])
        if not isinstance(result, dict) or not result.get("workfile"):
            msg = (
                f"Unable to retrieve workflow from ComfyUI to save: {path}\n"
                "Make sure the AYON ComfyUI page is open and up to date; "
                "if in doubt, reload it with Ctrl+Shift+R."
            )
            raise RuntimeError(msg)

        for warning in result.get("warnings") or []:
            log.warning(warning)

        Path(path).write_text(result["workfile"], encoding="utf-8")

        # Saving the workflow inside ComfyUI is a convenience (tab name and
        # modified state), the file on disk is what matters. So never fail
        # the save because of it.
        try:
            self.client_stub.finishSaveWorkfile(
                comfy_workflow_path=result.get("comfy_workflow_path")
            )
        except Exception:  # noqa: BLE001
            log.warning(
                "Saved workfile to disk, but failed to save the workflow "
                "inside ComfyUI.",
                exc_info=True,
            )

    def save_workfile_snapshot(self, path: str, workflow: dict) -> None:
        """Write a collected workflow to its AYON workfile `path`.

        `workflow` is what `get_api_prompt(snapshot=True)` returned for the
        targeted workflow (see `target_workflow`). Its tab is then saved
        in ComfyUI too when it still shows exactly that, so it's no longer
        flagged as modified; changes made since stay unsaved in the tab.
        """
        log.debug("save_workfile_snapshot: %s", path)
        Path(path).write_text(
            json.dumps(workflow, ensure_ascii=False), encoding="utf-8"
        )
        try:
            self.client_stub.finishSaveWorkfile(snapshot=True)
        except Exception:  # noqa: BLE001
            log.warning(
                "Saved workfile to disk, but failed to save the workflow "
                "inside ComfyUI.",
                exc_info=True,
            )

    def get_workfile_path(self) -> str | None:
        """Return the AYON workfile path of the active workflow, or None.

        Or of the targeted workflow (see `target_workflow`); then a closed
        workflow raises.
        """
        try:
            return self.client_stub.getWorkfilePath() or None
        except Exception as exc:
            if getattr(exc, "code", None) == "workflow_closed":
                raise
            # E.g. no browser connected (yet); treat as 'unsaved'
            log.warning("Unable to query workfile path.", exc_info=True)
            return None

    def get_graph_extra(self, key: str | None = None):  # noqa: ANN201
        """Retrieve graph.extra from the active workflow.

        Returns the full `extra` dict, or only `extra[key]` if key is passed.
        """
        raw = self.client_stub.getGraphExtra(key=key)
        if not raw:
            return None if key else {}
        return json.loads(raw)

    def _load_context(self) -> MutableMapping:
        """Query load entire context operation.

        Returns:
            JSON object if query was successful
        """
        log.debug("_load_context (full context)")
        context_json_raw = self.client_stub.do_context_retrieve()

        # Fallback if context doesn't exist, imprint it.
        # Sometimes, an attempt is made to load the context before
        # imprinting it. (e.g. Loader plugin)
        if not context_json_raw:
            context = get_current_context()
            # Not `imprint_context`: into the workflow read from.
            self.client_stub.do_context_imprint(
                imprint_info=json.dumps(context)
            )
            context_json_raw = self.client_stub.do_context_retrieve()

        log.debug(context_json_raw)
        return (
            json.loads(context_json_raw)
            if context_json_raw is not None
            else {}
        )

    @_publisher_scoped
    def load_context(self) -> MutableMapping | None:
        """Query load context, return only the context.

        Returns:
            dict with 'context' part of imprinted context.
        """
        context_json_raw = self._load_context()
        log.debug("load context")
        if context_json_raw:
            return context_json_raw["context"]
        return None

    @_publisher_scoped
    def list_instances(self) -> list[MutableMapping] | None:
        """Query load context.

        Returns:
            list[dict]; 'instances' part of imprintent context
        """
        context_json_raw = self._load_context()
        log.debug("list instances")
        if context_json_raw:
            return context_json_raw["instances"]
        return None

    def list_containers(self) -> list[MutableMapping] | None:
        """Query load context.

        Returns:
            list[dict]; 'containers' part of imprintent context
        """
        context_json_raw = self._load_context()
        log.debug("list containers")
        if context_json_raw:
            return context_json_raw["containers"]
        return None

    def _imprint_instances(self, data: list) -> None:
        """Hard update instance field of context node."""
        log.debug("imprint_instances")
        json_data = json.dumps(data)

        self.client_stub.do_instances_imprint(imprint_info=json_data)

    def _imprint_containers(self, data: list) -> None:
        """Hard update containers field of context node."""
        json_data = json.dumps(data)

        self.client_stub.do_containers_imprint(imprint_info=json_data)

    @staticmethod
    def instances_check_duplicate(instances: list[dict]) -> list[dict]:
        """Utility method to check duplicates in instances.

        Returns:
            list of duplicate free instances.
        """
        encountered = []
        clean = []
        for instance in instances:
            id_ = instance.get("instance_id")
            if id_ not in encountered:
                encountered.append(id_)
                clean.append(instance)

        return clean

    @staticmethod
    def containers_check_duplicate(containers: list[dict]) -> list[dict]:
        """Utility method to check duplicates in instances.

        Returns:
            list of duplicate free instances.
        """
        encountered = []
        clean = []
        for container in containers:
            id_ = container.get("container_uuid")
            if id_ not in encountered:
                encountered.append(id_)
                clean.append(container)

        return clean

    @_publisher_scoped
    def add_instance(self, instances_to_add: dict | list[dict]) -> None:
        """Add instances ensuring no duplicates."""
        instances = self.list_instances()

        if instances is None:
            instances = []

        if isinstance(instances_to_add, dict):
            instances.append(instances_to_add)
        elif isinstance(instances_to_add, list):
            instances.extend(instances_to_add)

        instances = self.instances_check_duplicate(instances)

        self._imprint_instances(instances)

    @_publisher_scoped
    def remove_instance(self, instances_to_remove: list[dict] | dict) -> None:
        """Remove instance(s)."""
        instances = self.list_instances()

        if instances is None:
            # nothing to remove
            return

        if isinstance(instances_to_remove, dict):
            instances = [
                instance
                for instance in instances
                if instance.get("instance_id")
                != instances_to_remove.get("instance_id")
            ]
        elif isinstance(instances_to_remove, list):
            ids_to_rem = [
                instance.get("instance_id") for instance in instances_to_remove
            ]
            instances = [
                instance
                for instance in instances
                if instance.get("instance_id") not in ids_to_rem
            ]

        self._imprint_instances(instances)

    @_publisher_scoped
    def update_instance(self, instances_to_update: list[dict] | dict) -> None:
        """Update instance(s) on hash collision, if hash not present, add."""
        instances = self.list_instances()

        if instances is None:
            # all instances will have to be added
            # if nothing is present on update.
            self.add_instance(instances_to_update)
            return

        if isinstance(instances_to_update, dict):
            instances = [
                instance
                if instance.get("instance_id")
                != instances_to_update.get("instance_id")
                else instances_to_update
                for instance in instances
            ]
            if instances_to_update.get("instance_id") not in [
                instance.get("instance_id") for instance in instances
            ]:
                instances.append(instances_to_update)
        elif isinstance(instances_to_update, list):
            ids_to_update = {
                instance.get("instance_id"): instance
                for instance in instances_to_update
            }
            instances = [
                ids_to_update.get(instance.get("instance_id"), instance)
                for instance in instances
            ]
            ids = {instance.get("instance_id") for instance in instances}
            # add the ones that were left behind
            instances.extend(
                [
                    instance
                    for instance in instances_to_update
                    if instance.get("instance_id") not in ids
                ]
            )

        self._imprint_instances(instances)

    def add_containers(self, containers_to_add: dict | list[dict]) -> None:
        """Add instances ensuring no duplicates."""
        containers = self.list_containers()

        if containers is None:
            containers = []

        if isinstance(containers_to_add, dict):
            containers.append(containers_to_add)
        elif isinstance(containers_to_add, list):
            containers.extend(containers_to_add)

        containers = self.containers_check_duplicate(containers)

        self._imprint_containers(containers)

    def remove_containers(
        self, containers_to_remove: list[dict] | dict
    ) -> None:
        """Remove instance(s)."""
        containers = self.list_containers()

        if containers is None:
            # nothing to remove
            return

        if isinstance(containers_to_remove, dict):
            containers = [
                instance
                for instance in containers
                if instance.get("container_uuid")
                != containers_to_remove.get("container_uuid")
            ]
        elif isinstance(containers_to_remove, list):
            ids_to_rem = [
                container.get("container_uuid")
                for container in containers_to_remove
            ]
            containers = [
                instance
                for instance in containers
                if instance.get("container_uuid") not in ids_to_rem
            ]

        self._imprint_containers(containers)

    def update_containers(
        self, containers_to_update: list[dict] | dict
    ) -> None:
        """Update instance(s) on hash collision, if hash not present, add."""
        containers = self.list_containers()

        if containers is None:
            # all instances will have to be added
            # if nothing is present on update.
            self.add_containers(containers_to_update)
            return

        if isinstance(containers_to_update, dict):
            containers = [
                container
                if container.get("container_uuid")
                != containers_to_update.get("container_uuid")
                else containers_to_update
                for container in containers
            ]
            if containers_to_update.get("container_uuid") not in [
                container.get("container_uuid") for container in containers
            ]:
                containers.append(containers_to_update)
        elif isinstance(containers_to_update, list):
            ids_to_update = {
                container.get("container_uuid"): container
                for container in containers_to_update
            }
            containers = [
                ids_to_update.get(instance.get("container_uuid"), instance)
                for instance in containers
            ]
            ids = {container.get("container_uuid") for container in containers}
            # add the ones that were left behind
            containers.extend(
                [
                    container
                    for container in containers_to_update
                    if container.get("container_uuid") not in ids
                ]
            )

        self._imprint_containers(containers)

        # Update all nodes.
        for container in containers:
            container_json = json.dumps(container)
            self.client_stub.updateLoadProductNode(
                container_json=container_json
            )

    @_publisher_scoped
    def create_publish_node(
        self,
        instance_to_create: dict,
        publish_type: PublishType = PublishType.IMAGE,
    ) -> None:
        """Pass along a call to create a Ayon Image Save node."""
        log.debug("stub create publish node")
        json_data = json.dumps(instance_to_create)

        self.client_stub.addPublishNode(
            instance_json=json_data, node_type=publish_type.value
        )

    @_publisher_scoped
    def remove_publish_nodes(
        self,
        instances_to_remove: dict | list,
        publish_type: PublishType = PublishType.IMAGE,
    ) -> None:
        """Pass along a call to remove a Ayon Image Save nodes."""
        log.debug("stub remove publish node")

        if isinstance(instances_to_remove, dict):
            instances_to_remove = [instances_to_remove]

        ids_to_remove = [
            instance["instance_id"] for instance in instances_to_remove
        ]

        json_ids_to_remove = json.dumps(ids_to_remove)

        self.client_stub.removePublishNodes(
            ids_to_remove=json_ids_to_remove, node_type=publish_type.value
        )

    def create_load_node(
        self, container_to_create: dict, node_type: LoadType = LoadType.IMAGE
    ) -> None:
        """Pass along a call to create a Ayon Load [Type] node."""
        log.debug("stub create load node:")
        log.debug(node_type.value)
        json_data = json.dumps(container_to_create)

        self.client_stub.addLoadProductNode(
            container_json=json_data, node_type=node_type.value
        )

    def update_load_node(
        self, container_to_update: dict, node_type: LoadType = LoadType.IMAGE
    ) -> None:
        """Pass along call to update Ayon Load [Type] node."""
        log.debug("stub update load node")
        log.debug(node_type.value)
        json_data = json.dumps(container_to_update)
        self.client_stub.updateLoadProductNode(
            container_json=json_data, node_type=node_type.value
        )

    def remove_load_nodes(
        self,
        containers_to_remove: dict | list,
        node_type: LoadType = LoadType.IMAGE,
    ) -> None:
        """Pass along a call to remove Ayon Load [Type] nodes."""
        log.debug("stub remove load node")
        log.debug(node_type.value)
        if isinstance(containers_to_remove, dict):
            containers_to_remove = [containers_to_remove]

        ids_to_remove = [
            container["container_uuid"] for container in containers_to_remove
        ]

        json_ids_to_remove = json.dumps(ids_to_remove)

        self.client_stub.removeLoadProductNodes(
            ids_to_remove=json_ids_to_remove, node_type=node_type.value
        )

    def get_api_prompt(self, *, snapshot: bool = False) -> dict:
        """Return the active workflow as an API-format prompt.

        The conversion is done by the ComfyUI frontend itself
        (`app.graphToPrompt`), so bypassed nodes, subgraphs, reroutes and
        primitives are handled exactly like when the artist runs the graph.
        A targeted workflow (see `target_workflow`) must be the active one.

        Args:
            snapshot: This is what will be published: the tab remembers it
                for `save_workfile_snapshot`.

        Returns:
            Dict with `prompt`, `workflow`, `client_id`, the workflow's
            identity and workfile, and `extra_data` (see
            `RPCClientStub.getApiPrompt`, `publish_lib.split_api_prompt`).
        """
        result = self.client_stub.getApiPrompt(snapshot=snapshot)
        if not isinstance(result, dict) or not isinstance(
            result.get("prompt"), dict
        ):
            msg = "The ComfyUI tab didn't return the workflow's prompt."
            raise RuntimeError(msg)
        return result

    def get_queue_extra_data(self) -> dict:
        """Return the `extra_data` the tab would queue a prompt with.

        Includes the artist's Comfy.org credentials: never store or log it.
        """
        result = self.client_stub.getQueueExtraData()
        return result if isinstance(result, dict) else {}

    def get_queued_prompts(self) -> list[dict]:
        """Return the prompts the paired tab queued, newest first.

        Each is `{prompt_id, workflow_path}`: the id ComfyUI gave it and
        the ComfyUI workflow (tab) it was queued from.
        """
        result = self.client_stub.getQueuedPrompts()
        if not isinstance(result, dict):
            return []
        prompts = result.get("prompts")
        if not isinstance(prompts, list):
            return []
        return [entry for entry in prompts if isinstance(entry, dict)]
