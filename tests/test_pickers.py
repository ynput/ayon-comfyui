"""Tests for `ayon_comfyui.api.pickers` with a fake `ayon_api`.

No AYON, ComfyUI or Qt needed. Run from the repository root with
`python -m unittest discover -s tests`, or with pytest.
"""

from __future__ import annotations

import importlib
import json
import os
import queue
import sys
import threading
import time
import types
import unittest
import uuid
from functools import partial
from unittest import mock

sys.path.insert(0, os.path.dirname(__file__))
import _stubs  # noqa: E402, F401

from ayon_comfyui.api import pickers  # noqa: E402


def eid(number: int) -> str:
    return f"{number:032x}"


F1, F2 = eid(1), eid(2)
P1, P2, P3 = eid(11), eid(12), eid(13)
V1, V2, V3, VH = eid(21), eid(22), eid(23), eid(24)
R1, R2, R3, R4 = eid(31), eid(32), eid(33), eid(34)

FOLDERS = {
    F1: {"id": F1, "path": "/shots/sh010", "name": "sh010"},
    F2: {"id": F2, "path": "/assets/hero", "name": "hero"},
}
PRODUCTS = {
    P1: {"id": P1, "name": "renderMain", "productType": "render",
         "folderId": F1},
    P2: {"id": P2, "name": "plateMain", "productType": "plate",
         "folderId": F1},
    P3: {"id": P3, "name": "modelMain", "productType": "model",
         "folderId": F2},
}
VERSIONS = {
    V1: {"id": V1, "version": 1, "productId": P1},
    V2: {"id": V2, "version": 2, "productId": P1},
    V3: {"id": V3, "version": 1, "productId": P2},
    # The hero version of renderMain.
    VH: {"id": VH, "version": -2, "productId": P1, "hero": True},
}
REPRES = {
    R1: {"id": R1, "name": "png", "versionId": V1, "context": {"ext": "png"}},
    R2: {"id": R2, "name": "png", "versionId": V2, "context": {"ext": "png"}},
    R3: {"id": R3, "name": "mp4", "versionId": V2, "context": {"ext": "mp4"}},
    R4: {"id": R4, "name": "exr", "versionId": V3, "context": {"ext": "exr"}},
}


class FakeApi:
    """The `ayon_api` calls the pickers make, over the entities above."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def get_folders(self, project_name, folder_ids=None, has_products=None,
                    fields=None):
        self.calls.append("get_folders")
        for folder in FOLDERS.values():
            if folder_ids is None or folder["id"] in folder_ids:
                yield {"id": folder["id"], "path": folder["path"]}

    def get_products(self, project_name, folder_ids=None, product_ids=None,
                     fields=None):
        self.calls.append("get_products")
        for product in PRODUCTS.values():
            if folder_ids is not None and (
                product["folderId"] not in folder_ids
            ):
                continue
            if product_ids is not None and product["id"] not in product_ids:
                continue
            yield dict(product)

    def get_versions(self, project_name, product_ids=None, version_ids=None,
                     hero=True, fields=None):
        self.calls.append("get_versions")
        for version in VERSIONS.values():
            if product_ids is not None and (
                version["productId"] not in product_ids
            ):
                continue
            if version_ids is not None and version["id"] not in version_ids:
                continue
            if version.get("hero") and not hero:
                continue
            yield dict(version)

    def get_representations(self, project_name, version_ids=None,
                            representation_ids=None, fields=None):
        self.calls.append("get_representations")
        for repre in REPRES.values():
            if version_ids is not None and (
                repre["versionId"] not in version_ids
            ):
                continue
            if representation_ids is not None and (
                repre["id"] not in representation_ids
            ):
                continue
            yield dict(repre)

    def get_last_versions(self, project_name, product_ids, fields=None):
        result = {}
        for product_id in product_ids:
            versions = [
                version for version in VERSIONS.values()
                if version["productId"] == product_id
                and not version.get("hero")
            ]
            result[product_id] = max(
                versions, key=lambda version: version["version"]
            ) if versions else None
        return result

    def get_product_by_id(self, project_name, product_id):
        return PRODUCTS.get(product_id)

    def get_last_version_by_product_id(self, project_name, product_id):
        return self.get_last_versions(project_name, [product_id])[product_id]

    def get_version_by_id(self, project_name, version_id):
        return VERSIONS.get(version_id)

    def get_representation_by_name(self, project_name, name, version_id):
        for repre in REPRES.values():
            if repre["versionId"] == version_id and repre["name"] == name:
                return repre
        return None


class FakeLoader:
    """Loads png and exr; records what `build_container` was asked."""

    product_types = {"*"}
    exts = {"png", "exr"}
    built: list[dict] = []

    def __init__(self, context: dict) -> None:
        self.context = context

    @classmethod
    def is_compatible_loader(cls, context: dict) -> bool:
        return context["representation"]["context"]["ext"] in cls.exts

    def build_container(self, context: dict, **kwargs) -> dict:
        FakeLoader.built.append(
            {**kwargs, "thread": threading.current_thread().name})
        return {
            "representation": context["representation"]["id"],
            "container_uuid": kwargs["container_uuid"] or "new",
            "version_mode": kwargs["version_mode"],
        }


class FakeModelLoader(FakeLoader):
    product_types = {"model"}


def representation_context(project_name: str, repre: dict) -> dict:
    version = VERSIONS[repre["versionId"]]
    product = PRODUCTS[version["productId"]]
    return {
        "project": {"name": project_name},
        "folder": FOLDERS[product["folderId"]],
        "product": product,
        "version": version,
        "representation": repre,
    }


def make_service(api: FakeApi | None = None, project: str = "demo"):
    return pickers.PickerService(
        api or FakeApi(),
        project_name=lambda: project,
        loaders=lambda: {
            "AYON Load Image": FakeLoader,
            "AYON Load 3D Model": FakeModelLoader,
        },
        representation_context=representation_context,
    )


APPLY = {
    "token": "tok1",
    "node_type": "AYON Load Image",
    "container_uuid": str(uuid.uuid4()),
    "product_id": P1,
    "version_mode": "latest",
    "representation_name": "png",
}


class QueryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.api = FakeApi()
        self.service = make_service(self.api)

    def test_folders_sorted_and_scoped(self) -> None:
        result = self.service.folders({"project_name": "other"})
        self.assertEqual(result["project_name"], "demo")
        self.assertEqual(
            [folder["path"] for folder in result["folders"]],
            ["/assets/hero", "/shots/sh010"],
        )

    def test_folders_cached_and_refresh_throttled(self) -> None:
        self.service.folders({})
        self.service.folders({})
        self.assertEqual(self.api.calls.count("get_folders"), 1)
        self.service.folders({"refresh": True})
        self.assertEqual(self.api.calls.count("get_folders"), 2)
        # A second refresh right away is served from the cache.
        self.service.folders({"refresh": True})
        self.assertEqual(self.api.calls.count("get_folders"), 2)
        self.service._last_refresh["folders"] -= 10
        self.service.folders({"refresh": True})
        self.assertEqual(self.api.calls.count("get_folders"), 3)

    def test_queries_rate_limited(self) -> None:
        self.service._query_times.extend(
            [time.monotonic()] * pickers.MAX_QUERIES_PER_MINUTE
        )
        with self.assertRaisesRegex(pickers.PickerError, "Too many"):
            self.service.folders({})

    def test_options(self) -> None:
        options = self.service.options(
            {"node_type": "AYON Load Image", "folder_id": F1}
        )
        self.assertEqual(
            [product["name"] for product in options["products"]],
            ["plateMain", "renderMain"],
        )
        self.assertEqual(options["versions"], [])

        options = self.service.options({
            "node_type": "AYON Load Image", "folder_id": F1,
            "product_id": P1,
        })
        self.assertEqual(
            [version["label"] for version in options["versions"]],
            ["v002", "v001"],
        )
        self.assertEqual(options["version_id"], V2)
        # mp4 isn't something an image node loads.
        self.assertEqual(
            [repre["name"] for repre in options["representations"]], ["png"]
        )

    def test_options_hero_version(self) -> None:
        options = self.service.options({
            "node_type": "AYON Load Image", "folder_id": F1,
            "product_id": P1, "version_id": VH,
        })
        self.assertEqual(options["version_id"], VH)

    def test_options_validation(self) -> None:
        cases = [
            ({"node_type": "AYON Load Image", "folder_id": F2,
              "product_id": P1}, "isn't in this folder"),
            ({"node_type": "AYON Load Image", "folder_id": F1,
              "product_id": P1, "version_id": V3}, "doesn't belong"),
            ({"node_type": "Evil", "folder_id": F1}, "don't support"),
            ({"node_type": "AYON Load Image", "folder_id": "../etc"},
             "Invalid"),
            ({"node_type": "AYON Load Video", "folder_id": F1},
             "No AYON loader"),
        ]
        for params, message in cases:
            with self.subTest(params=params), self.assertRaisesRegex(
                pickers.PickerError, message
            ):
                self.service.options(params)

    def test_options_loader_product_filter(self) -> None:
        options = self.service.options(
            {"node_type": "AYON Load 3D Model", "folder_id": F1}
        )
        self.assertEqual(options["products"], [])

    def test_no_project(self) -> None:
        with self.assertRaisesRegex(pickers.PickerError, "no current project"):
            make_service(project="").folders({})

    def test_status(self) -> None:
        status = self.service.status(
            {"representation_ids": [R1, eid(99), "bad"]}
        )
        item = status["items"][R1]
        self.assertEqual(
            (item["folder_path"], item["product_name"], item["version"],
             item["representation_name"], item["latest_version"]),
            ("/shots/sh010", "renderMain", 1, "png", 2),
        )
        self.assertEqual(
            status["items"][eid(99)], {"missing": "representation"}
        )
        self.assertNotIn("bad", status["items"])
        with self.assertRaises(pickers.PickerError):
            self.service.status({"representation_ids": "x"})
        with self.assertRaises(pickers.PickerError):
            self.service.status({"representation_ids": [R1] * 501})


class ApplyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.service = make_service()

    def apply(self, **changes) -> dict:
        request = self.service.validate_apply({**APPLY, **changes})
        try:
            return self.service.apply(request)
        finally:
            self.service.release(request)

    def test_validation(self) -> None:
        cases = [
            ({"token": "a b"}, "token"),
            ({"container_uuid": "x"}, "container_uuid"),
            ({"version_mode": "hero"}, "version_mode"),
            ({"version_mode": "pinned"}, "version_id"),
            ({"node_type": "AYON Image Save"}, "don't support"),
            ({"representation_name": ""}, "representation_name"),
            ({"reference": "yes"}, "reference"),
        ]
        for changes, message in cases:
            with self.subTest(changes=changes), self.assertRaisesRegex(
                pickers.PickerError, message
            ):
                self.service.validate_apply({**APPLY, **changes})

    def test_one_load_per_node(self) -> None:
        request = self.service.validate_apply(dict(APPLY))
        with self.assertRaisesRegex(pickers.PickerError, "still loading"):
            self.service.validate_apply({**APPLY, "token": "tok2"})
        self.service.release(request)
        self.service.release(self.service.validate_apply(dict(APPLY)))

    def test_loads_in_flight_capped(self) -> None:
        first = self.service.validate_apply(
            {**APPLY, "token": "c1", "container_uuid": None})
        second = self.service.validate_apply(
            {**APPLY, "token": "c2", "container_uuid": None})
        with self.assertRaisesRegex(pickers.PickerError, "busy loading"):
            self.service.validate_apply(
                {**APPLY, "token": "c3", "container_uuid": None})
        self.service.release(first)
        self.service.release(second)
        self.assertFalse(self.service._applying)

    def test_loads_rate_limited(self) -> None:
        for index in range(pickers.MAX_APPLIES_PER_MINUTE):
            self.service.release(self.service.validate_apply(
                {**APPLY, "token": f"r{index}"}))
        with self.assertRaisesRegex(pickers.PickerError, "Too many"):
            self.service.validate_apply({**APPLY, "token": "rx"})

    def test_latest(self) -> None:
        container = self.apply()
        self.assertEqual(container["representation"], R2)
        self.assertEqual(container["container_uuid"], APPLY["container_uuid"])
        built = FakeLoader.built[-1]
        self.assertEqual(
            (built["name"], built["namespace"], built["reference"]),
            ("renderMain", "sh010", False),
        )

    def test_pinned_new_container_by_path(self) -> None:
        container = self.apply(
            container_uuid=None, version_mode="pinned", version_id=V1,
            reference=True,
        )
        self.assertEqual(container["representation"], R1)
        self.assertEqual(container["container_uuid"], "new")
        self.assertIs(FakeLoader.built[-1]["reference"], True)

    def test_apply_errors(self) -> None:
        cases = [
            ({"version_mode": "pinned", "version_id": V3},
             "no longer exists"),
            ({"representation_name": "mp4"}, "can't be loaded"),
            ({"representation_name": "abc"}, "has no 'abc'"),
        ]
        for changes, message in cases:
            with self.subTest(changes=changes), self.assertRaisesRegex(
                pickers.PickerError, message
            ):
                self.apply(**changes)


class HelperTests(unittest.TestCase):
    def test_pick_node_loaders(self) -> None:
        def make_load_type(value):
            return type("LoadType", (), {"value": value})

        class Base:
            skip_discovery = True
            product_types: set = set()
            representations: set = set()
            load_type = make_load_type("AYON Load Image")

            def build_container(self):
                pass

        class NoFilters(Base):
            """Inherits skip_discovery and has no filters."""

        class Action(Base):
            load_type = None
            product_types = {"*"}
            representations = {"*"}

        class Image(Base):
            load_type = make_load_type("AYON Load Image")
            product_types = {"*"}
            representations = {"*"}

        self.assertEqual(
            pickers.pick_node_loaders([Base, NoFilters, Action, Image]),
            {"AYON Load Image": Image},
        )

    def test_artist_error(self) -> None:
        self.assertEqual(
            pickers.artist_error(OSError("C:/secret/plate.exr missing")),
            "Loading failed, see the AYON log for details.",
        )
        self.assertEqual(
            pickers.artist_error(pickers.PickerError("No such version.")),
            "No such version.",
        )
        load_error = type("LoadError", (Exception,), {})
        self.assertEqual(
            pickers.artist_error(load_error("Unable to upload png.")),
            "Unable to upload png.",
        )

    def test_cache_bounded(self) -> None:
        cache = pickers._Cache(ttl=60)
        for index in range(pickers.MAX_CACHE_ITEMS + 50):
            cache.get(index, lambda i=index: i)
        self.assertEqual(len(cache._items), pickers.MAX_CACHE_ITEMS)
        # The oldest entries went first.
        self.assertNotIn(0, cache._items)
        self.assertIn(pickers.MAX_CACHE_ITEMS + 49, cache._items)

    def test_cache_drops_expired(self) -> None:
        cache = pickers._Cache(ttl=60)
        cache.get("old", lambda: 1)
        cache._items["old"] = (time.monotonic() - 120, 1)
        cache.get("new", lambda: 2)
        self.assertNotIn("old", cache._items)

    def test_load_target(self) -> None:
        pickers.set_load_target({"token": "t1", "node_type": "x"})
        self.assertIsNone(pickers.take_load_target("other"))
        self.assertEqual(pickers.get_load_target()["token"], "t1")
        self.assertEqual(pickers.take_load_target("t1")["token"], "t1")
        self.assertIsNone(pickers.get_load_target())


class FakeBridge:
    """Records what the handlers ask of `ComfyUIBridge`."""

    def __init__(self) -> None:
        self.handlers: dict = {}
        handlers = self.handlers

        class Client:
            def register_handler(self, name, func):
                handlers[name] = func

        self.client = Client()
        self.main_thread_calls: list = []
        self.while_busy: list[bool] = []
        self.applied = threading.Event()
        self.applied_from: str | None = None
        self.applied_args: tuple | None = None
        bridge = self

        class Stub:
            def picker_applied(self, token, container=None, error=None):
                bridge.applied_from = threading.current_thread().name
                bridge.applied_args = (token, container, error)
                bridge.applied.set()
                return True

            def picker_invalidate(self):
                pass

        self.stub = Stub()

    def run_in_main_thread(self, func, *, while_busy=False) -> None:
        self.main_thread_calls.append(func)
        self.while_busy.append(while_busy)


class HandlerTests(unittest.TestCase):
    def test_loads_run_on_the_load_worker(self) -> None:
        bridge = FakeBridge()
        pickers.register_picker_handlers(bridge, service=make_service())
        self.assertEqual(
            set(bridge.handlers),
            {"picker.folders", "picker.options", "picker.status",
             "picker.apply", "picker.browse"},
        )
        # The loader discovery warm-up goes to the Qt main thread.
        self.assertEqual(len(bridge.main_thread_calls), 1)

        answer = bridge.handlers["picker.apply"](dict(APPLY))
        self.assertEqual(answer, {"scheduled": True})
        # The upload ran on the load worker...
        deadline = time.monotonic() + 5
        while len(bridge.main_thread_calls) < 2:
            self.assertLess(time.monotonic(), deadline)
            time.sleep(0.01)
        self.assertTrue(FakeLoader.built[-1]["thread"].startswith(
            "AYON-ComfyUI-picker-load"))
        # ...and the result goes to the tab from the Qt main thread (here
        # the test's thread), where the AYON Context node is written, also
        # while a publish waits for its render.
        self.assertEqual(bridge.while_busy, [False, True])
        self.assertFalse(bridge.applied.is_set())
        bridge.main_thread_calls[1]()
        self.assertEqual(
            bridge.applied_from, threading.current_thread().name)
        token, container, error = bridge.applied_args
        self.assertEqual((token, container["representation"], error),
                         ("tok1", R2, None))

    def test_query_errors_are_generic(self) -> None:
        bridge = FakeBridge()
        service = make_service()

        def broken(_params):
            msg = "C:/secret path"
            raise OSError(msg)

        service.folders = broken
        pickers.register_picker_handlers(bridge, service=service)
        with self.assertRaises(pickers.PickerError) as caught:
            bridge.handlers["picker.folders"]({})
        self.assertNotIn("secret", str(caught.exception))


# --- the real bridge, with stand-ins for Qt and ayon-core --------------------

# Calls posted to the Qt main thread; `process_events` runs them.
EVENTS: queue.Queue = queue.Queue()


def process_events() -> None:
    """Run what was posted to the Qt main thread, like its event loop."""
    while True:
        try:
            event = EVENTS.get_nowait()
        except queue.Empty:
            return
        event()


class _BoundSignal:
    def __init__(self) -> None:
        self.slots: list = []

    def connect(self, slot) -> None:
        self.slots.append(slot)

    def emit(self, *args) -> None:
        # A queued connection: the slot runs on the Qt main thread later.
        for slot in self.slots:
            EVENTS.put(partial(slot, *args))


class _Signal:
    """Stand-in for `QtCore.Signal`, connected to the main thread."""

    def __init__(self, *_types) -> None:
        self.name = ""

    def __set_name__(self, owner, name) -> None:
        self.name = name

    def __get__(self, obj, objtype=None):
        if obj is None:
            return self
        return obj.__dict__.setdefault(f"_signal_{self.name}", _BoundSignal())


def import_bridge() -> types.ModuleType:
    """Import `api/bridge.py` with stand-ins for Qt and ayon-core."""
    qtcore = types.ModuleType("qtpy.QtCore")
    qtcore.QObject = type(
        "QObject", (), {"__init__": lambda self, parent=None: None})
    qtcore.Signal = _Signal
    qtcore.QTimer = lambda *_args: mock.MagicMock()
    qtgui = types.ModuleType("qtpy.QtGui")
    qtwidgets = types.ModuleType("qtpy.QtWidgets")
    qtwidgets.QWidget = type("QWidget", (), {})
    qtpy = types.ModuleType("qtpy")
    qtpy.QtCore, qtpy.QtGui, qtpy.QtWidgets = qtcore, qtgui, qtwidgets
    ayon_core = mock.MagicMock()
    fakes = {
        "qtpy": qtpy,
        "qtpy.QtCore": qtcore,
        "qtpy.QtGui": qtgui,
        "qtpy.QtWidgets": qtwidgets,
        "ayon_core": ayon_core,
        "ayon_core.pipeline": ayon_core.pipeline,
        "ayon_core.tools": ayon_core.tools,
        "ayon_core.tools.utils": ayon_core.tools.utils,
    }
    package = sys.modules["ayon_comfyui.api"]
    # Only for this import: other tests may use the real modules.
    with mock.patch.dict(sys.modules, fakes), \
            mock.patch.dict(vars(package)):
        for name in ("bridge", "menu_actions", "rpc_stub"):
            sys.modules.pop(f"ayon_comfyui.api.{name}", None)
        return importlib.import_module("ayon_comfyui.api.bridge")


class BusyBridgeTests(unittest.TestCase):
    """Picks while the bridge is busy, e.g. a publish waiting for a render.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.module = import_bridge()

    def setUp(self) -> None:
        module = self.module
        self.calls: list = []
        calls = self.calls

        class Client:
            """Records what is sent to the ComfyUI tab."""

            def __init__(self, *_args, **_kwargs) -> None:
                self.handlers: dict = {}

            def register_handler(self, name, func) -> None:
                self.handlers[name] = func

            def call(self, method, params, timeout=None):
                calls.append((method, params))
                return True

        register = module.register_picker_handlers
        # The pickers module the bridge uses.
        self.pickers = register.__globals__
        for patch in (
            mock.patch.object(module, "BridgeClient", Client),
            mock.patch.object(module, "SessionWindow", mock.MagicMock()),
            mock.patch.object(module, "get_session_info", dict),
            mock.patch.object(
                module, "register_picker_handlers",
                lambda bridge: register(bridge, service=make_service()),
            ),
        ):
            patch.start()
            self.addCleanup(patch.stop)
        # No loader discovery: it needs ayon-core.
        self.set_picker_global("loaders_by_node_type", dict)
        self.opened: list = []
        self.set_picker_global(
            "open_loader", lambda: self.opened.append(True))
        self.addCleanup(self.pickers["take_load_target"])

        self.bridge = module.ComfyUIBridge("http://127.0.0.1:8188")
        self.handlers = self.bridge.client.handlers
        process_events()

    def set_picker_global(self, name: str, value) -> None:
        original = self.pickers[name]
        self.pickers[name] = value
        self.addCleanup(self.pickers.__setitem__, name, original)

    def test_picks_are_applied_while_busy(self) -> None:
        saves: list = []
        with mock.patch.object(
            self.module, "save_current_workfile", lambda: saves.append(True)
        ):
            with self.bridge.busy():
                # Both clicked in the tab while busy. "Save Workfile" waits
                # until the bridge is no longer busy...
                self.handlers["requestSaveWorkfile"]({})
                self.assertEqual(
                    self.handlers["picker.apply"](dict(APPLY)),
                    {"scheduled": True},
                )
                # ...but the pick is loaded into its node right away.
                deadline = time.monotonic() + 5
                while not self.calls:
                    self.assertLess(time.monotonic(), deadline)
                    time.sleep(0.01)
                    process_events()
                [(method, params)] = self.calls
                self.assertEqual(method, "pickerApplied")
                self.assertEqual(params["token"], "tok1")
                self.assertIsNone(params["error"])
                container = json.loads(params["container_json"])
                self.assertEqual(container["representation"], R2)
                self.assertEqual(saves, [])
            process_events()
            self.assertEqual(saves, [True])

    def test_loader_opens_when_no_longer_busy(self) -> None:
        browse = {"token": "tok2", "node_type": "AYON Load Image"}
        with self.bridge.busy():
            self.assertEqual(
                self.handlers["picker.browse"](browse), {"scheduled": True})
            process_events()
            self.assertEqual(self.opened, [])
            self.assertIsNone(self.pickers["get_load_target"]())
        process_events()
        self.assertEqual(self.opened, [True])
        self.assertEqual(self.pickers["get_load_target"]()["token"], "tok2")


if __name__ == "__main__":
    unittest.main()
