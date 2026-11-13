"""Tests of the node pickers' loader side against the real ayon-core.

Covers ayon-core's plugin discovery over `plugins/load` (which loader each
AYON Load node type gets, and when "Load into waiting ComfyUI node" is
offered), `ComfyUILoader.build_container` for uploaded and path-referenced
containers (file transfer stubbed) and `RPCStub.update_containers`.

Needs `ayon_core`, its vendored modules and Qt bindings. They are skipped
unless those import; list extra import paths in `AYON_TEST_SYS_PATH`
(separated by `os.pathsep`), e.g. on Windows with an AYON launcher and an
ayon-core checkout, using a Python matching the launcher's (3.11):

    set AYON_TEST_SYS_PATH=F:/dev/ayon-core/client;F:/dev/ayon-core/client/ayon_core/vendor/python;%LOCALAPPDATA%/Ynput/AYON/app/AYON 1.6.3/dependencies;%LOCALAPPDATA%/Ynput/AYON/app/AYON 1.6.3/vendor/python;<a pydeps env with ayon_api>
    python -m unittest discover -s tests -p "test_pickers_ayon_core.py"
"""  # noqa: E501

from __future__ import annotations

import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(__file__))
for _path in reversed(
    [p for p in os.environ.get("AYON_TEST_SYS_PATH", "").split(os.pathsep)
     if p]
):
    sys.path.insert(0, os.path.expandvars(_path))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import _stubs  # noqa: E402

try:
    import qtpy  # noqa: F401
    from ayon_core.pipeline.load import LoaderPlugin
    from ayon_core.pipeline.plugin_discover import discover_plugins
except Exception as exc:  # noqa: BLE001
    SKIP_REASON = f"ayon-core with Qt isn't importable: {exc}"
else:
    SKIP_REASON = ""
    # Use the real `ayon_comfyui` package (its __init__ needs ayon-core),
    # not the stand-ins `_stubs` registers for the other tests; those keep
    # the modules they already imported.
    for _name in [
        name for name in sys.modules
        if name == "ayon_comfyui" or name.startswith("ayon_comfyui.")
    ]:
        del sys.modules[_name]
    sys.path.insert(0, str(_stubs.CLIENT_DIR))
    from ayon_comfyui.api import pickers, plugin
    from ayon_comfyui.api.rpc_stub import RPCStub

LOAD_DIR = _stubs.CLIENT_DIR / "ayon_comfyui" / "plugins" / "load"

PRODUCT = {"productType": "render", "name": "renderMain"}
PNG = {"name": "png", "context": {"ext": "png"}}
MOV = {"name": "mov", "context": {"ext": "mov"}}


@unittest.skipIf(SKIP_REASON, SKIP_REASON)
class DiscoveryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        result = discover_plugins(LoaderPlugin, paths=[str(LOAD_DIR)])
        cls.crashed = dict(result.crashed_file_paths)
        cls.plugins = list(result.plugins)
        cls.loaders = pickers.pick_node_loaders(cls.plugins)

    def tearDown(self) -> None:
        pickers._loaders = None
        pickers.take_load_target()

    def test_plugins_import(self) -> None:
        self.assertEqual(self.crashed, {})

    def test_base_class_skipped(self) -> None:
        names = {cls.__name__ for cls in self.plugins}
        self.assertNotIn("ComfyUILoader", names)
        self.assertIn("LoadIntoComfyUINode", names)

    def test_each_node_type_gets_its_loader(self) -> None:
        self.assertEqual(
            {k: v.__name__ for k, v in self.loaders.items()},
            {
                "AYON Load Image": "ImageLoader",
                "AYON Load Video": "VideoLoader",
                "AYON Load 3D Model": "ModelLoader",
            },
        )

    def test_compatibility(self) -> None:
        image = self.loaders["AYON Load Image"]
        video = self.loaders["AYON Load Video"]
        self.assertTrue(image.is_compatible_loader(
            {"product": PRODUCT, "representation": PNG}))
        self.assertFalse(image.is_compatible_loader(
            {"product": PRODUCT, "representation": MOV}))
        self.assertTrue(video.is_compatible_loader(
            {"product": PRODUCT, "representation": MOV}))

    def test_load_into_node_action(self) -> None:
        action = next(
            cls for cls in self.plugins
            if cls.__name__ == "LoadIntoComfyUINode"
        )
        pickers._loaders = self.loaders
        png = {"product": PRODUCT, "representation": PNG}
        mov = {"product": PRODUCT, "representation": MOV}
        self.assertFalse(action.is_compatible_loader(png))
        pickers.set_load_target({
            "token": "t", "node_type": "AYON Load Video",
            "container_uuid": None,
        })
        self.assertTrue(action.is_compatible_loader(mov))
        self.assertFalse(action.is_compatible_loader(png))


CONTEXT = {
    "project": {"name": "demo"},
    "folder": {"id": "f" * 32, "path": "/shots/sh010", "name": "sh010"},
    "product": {"id": "p" * 32, "name": "plateMain", "productType": "plate"},
    "version": {"id": "v" * 32, "version": 3},
    "representation": {
        "id": "r" * 32, "name": "exr", "context": {"ext": "exr"},
    },
}


def make_loader_class():
    """A ComfyUILoader whose file transfer is recorded, not done."""
    calls = []

    class Loader(plugin.ComfyUILoader):
        mode = "upload"

        @property
        def comfy_url(self):
            return "http://comfy"

        def get_upload_files(self, context):
            return ["P:/project/plate.exr"]

        def make_files_available(self, context, filepaths, subfolder, *,
                                 reference=False):
            calls.append({"subfolder": subfolder, "reference": reference})
            if reference and self.mode == "reference":
                return {
                    "path_reference": {"files": ["{root[work]}/plate.exr"]},
                    "image_upload_info": [],
                }
            return {
                "path_reference": None,
                "image_upload_info": [{
                    "name": "plate.exr", "subfolder": subfolder,
                    "type": "input",
                }],
            }

    return Loader, calls


@unittest.skipIf(SKIP_REASON, SKIP_REASON)
class BuildContainerTests(unittest.TestCase):
    def test_new_container_uploads(self) -> None:
        loader_cls, calls = make_loader_class()
        container = loader_cls(CONTEXT).build_container(
            CONTEXT, name="plateMain", namespace="sh010",
            version_mode="pinned",
        )
        self.assertEqual(
            calls[-1], {"subfolder": "sh010_plateMain", "reference": False})
        self.assertTrue(container["image_upload_info"])
        self.assertNotIn("path_reference", container)
        self.assertEqual(container["project_name"], "demo")
        self.assertEqual(container["selection"]["version"], 3)
        self.assertEqual(container["selection"]["version_mode"], "pinned")
        self.assertEqual(container["loader"], "Loader")

    def test_path_reference_kept_on_update(self) -> None:
        loader_cls, calls = make_loader_class()
        loader_cls.mode = "reference"
        loader = loader_cls(CONTEXT)
        container = loader.build_container(
            CONTEXT, name="plateMain", namespace="sh010",
            version_mode="latest", reference=True,
            container_uuid="11111111-2222-4333-8444-555555555555",
        )
        self.assertEqual(
            container["path_reference"],
            {"files": ["{root[work]}/plate.exr"]},
        )
        self.assertEqual(container["image_upload_info"], [])

        container["extra_key"] = 1
        updated = loader.build_container(
            CONTEXT, container, version_mode="pinned")
        self.assertIs(calls[-1]["reference"], True)
        self.assertTrue(updated["path_reference"]["files"])
        self.assertEqual(
            (updated["container_uuid"], updated["extra_key"]),
            (container["container_uuid"], 1),
        )

        # The server can't read the files any more: uploaded after all.
        loader_cls.mode = "upload"
        fallback = loader.build_container(
            CONTEXT, container, version_mode="pinned")
        self.assertNotIn("path_reference", fallback)
        self.assertTrue(fallback["image_upload_info"])

    def test_update_keeps_upload_subfolder(self) -> None:
        loader_cls, _calls = make_loader_class()
        loader = loader_cls(CONTEXT)
        container = loader.build_container(
            CONTEXT, name="plateMain", namespace="sh010",
            version_mode="pinned",
        )
        updated = loader.build_container(
            CONTEXT, container, version_mode="pinned")
        self.assertEqual(
            updated["image_upload_info"][0]["subfolder"], "sh010_plateMain")

    def test_load_honours_reference_option(self) -> None:
        loader_cls, calls = make_loader_class()
        loader_cls.mode = "reference"
        added = []

        class Stub:
            def add_containers(self, container):
                added.append(container)

            def create_load_node(self, container, load_type):
                added.append(load_type)

        loader_cls.stub = property(lambda self: Stub())
        loader_cls(CONTEXT).load(
            CONTEXT, name="plateMain", namespace="sh010",
            options={"reference_files": True},
        )
        self.assertIs(calls[-1]["reference"], True)
        self.assertTrue(added[0].get("path_reference"))


@unittest.skipIf(SKIP_REASON, SKIP_REASON)
class UpdateContainersTests(unittest.TestCase):
    def setUp(self) -> None:
        self.calls = []
        calls = self.calls

        class Client:
            base_url = "http://comfy"

            def call(self, method, params, timeout=None):
                calls.append((method, params))
                return True

        self.stub = RPCStub(Client())
        existing = [
            {"container_uuid": f"u{index}", "representation": f"r{index}"}
            for index in range(5)
        ]
        self.imprinted = []
        self.stub.list_containers = lambda: [dict(c) for c in existing]
        self.stub._imprint_containers = self.imprinted.append

    def pushed(self) -> list[dict]:
        return [
            json.loads(params["container_json"])
            for method, params in self.calls
            if method == "updateLoadProductNode"
        ]

    def test_pushes_only_the_updated_container(self) -> None:
        self.stub.update_containers(
            {"container_uuid": "u2", "representation": "new"})
        self.assertEqual(
            [c["container_uuid"] for c in self.pushed()], ["u2"])
        self.assertEqual(len(self.imprinted[-1]), 5)
        self.assertEqual(self.imprinted[-1][2]["representation"], "new")

    def test_pushes_only_the_updated_containers(self) -> None:
        self.stub.update_containers([
            {"container_uuid": "u1", "representation": "a"},
            {"container_uuid": "u9", "representation": "b"},
        ])
        self.assertEqual(
            [c["container_uuid"] for c in self.pushed()], ["u1", "u9"])
        self.assertEqual(len(self.imprinted[-1]), 6)


if __name__ == "__main__":
    unittest.main()
