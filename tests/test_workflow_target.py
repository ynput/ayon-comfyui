"""Tests of acting on a pinned ComfyUI workflow (tab) from the host.

Covers `rpc_stub.target_workflow`, the Publisher's pinned workflow and
saving a collected workflow. No ComfyUI or AYON needed.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import types
import unittest

sys.path.insert(0, os.path.dirname(__file__))
import _stubs  # noqa: E402, F401

try:  # `rpc_stub` needs `get_current_context` from ayon-core.
    import ayon_core.pipeline  # noqa: F401
except ImportError:
    _core = types.ModuleType("ayon_core")
    _core.__path__ = []
    _pipeline = types.ModuleType("ayon_core.pipeline")
    _pipeline.get_current_context = lambda: {"project_name": "demo"}
    _core.pipeline = _pipeline
    sys.modules.setdefault("ayon_core", _core)
    sys.modules.setdefault("ayon_core.pipeline", _pipeline)

from ayon_comfyui.api import rpc_stub  # noqa: E402
from ayon_comfyui.api.bridge_client import BridgeError  # noqa: E402

A = {"workflow_key": "key-a", "workflow_label": "shot_v001.json"}
B = {"workflow_key": "key-b", "workflow_label": "shot_v002.json"}


class FakeClient:
    """Answers tab calls like a tab whose context node holds `context`."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []
        self.active = A
        self.contexts = {
            "key-a": {"context": {}, "instances": [], "containers": []},
            "key-b": {"context": {}, "instances": [], "containers": []},
        }

    def _key(self, params: dict) -> str:
        return params.get("workflow_key") or self.active["workflow_key"]

    def call(self, method: str, params: dict, timeout=None):  # noqa: ANN001, ANN201, ARG002
        self.calls.append((method, dict(params)))
        if method == "getWorkflowTarget":
            return dict(self.active)
        if method == "getImprintContext":
            context = self.contexts[self._key(params)]
            return json.dumps(context) if context is not None else ""
        if method == "setImprintContext":
            self.contexts[self._key(params)] = json.loads(
                params["imprint_info"]
            )
            return True
        if method in {"finishSaveWorkfile", "addPublishNode"}:
            return True
        if method == "removePublishNodes":
            return "[]"
        msg = f"unexpected call {method}"
        raise AssertionError(msg)

    def keys_of(self, method: str) -> list:
        return [p.get("workflow_key") for m, p in self.calls if m == method]


class TargetTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = FakeClient()
        self.stub = rpc_stub.RPCStub(self.client)

    def test_calls_carry_the_target(self) -> None:
        self.stub.client_stub.getImprintContext()
        with self.stub.target_workflow(B):
            self.stub.client_stub.getImprintContext()
            with self.stub.target_workflow(None):
                self.stub.client_stub.getImprintContext()
        self.assertEqual(
            self.client.keys_of("getImprintContext"), [None, "key-b", None]
        )
        labels = [
            p.get("workflow_label") for m, p in self.client.calls
        ]
        self.assertEqual(labels, [None, "shot_v002.json", None])

    def test_publisher_instances_stay_on_their_workflow(self) -> None:
        self.stub.pin_publisher_workflow()
        self.assertEqual(self.stub.publisher_workflow, A)
        # The artist switches to another tab while the Publisher is open.
        self.client.active = B
        instance = {"instance_id": "i1", "productName": "imageMain"}
        self.stub.update_instance(instance)
        self.stub.create_publish_node(instance)
        self.assertEqual(
            self.client.contexts["key-a"]["instances"], [instance])
        self.assertEqual(self.client.contexts["key-b"]["instances"], [])
        self.assertEqual(self.client.keys_of("addPublishNode"), ["key-a"])
        self.assertEqual(self.stub.list_instances(), [instance])

        # The Loader and Scene Inventory act on the active workflow.
        self.stub.add_containers({"container_uuid": "c1"})
        self.assertEqual(
            self.client.contexts["key-b"]["containers"],
            [{"container_uuid": "c1"}],
        )
        self.assertEqual(self.client.contexts["key-a"]["containers"], [])

        # An explicit target wins over the Publisher's.
        with self.stub.target_workflow(B):
            self.stub.remove_instance(instance)
        self.assertEqual(
            self.client.contexts["key-a"]["instances"], [instance])

    def test_context_fallback_imprints_where_it_reads(self) -> None:
        self.stub.pin_publisher_workflow()
        self.client.active = B
        self.client.contexts["key-b"] = None
        self.stub.list_containers()
        self.assertEqual(
            self.client.keys_of("setImprintContext"), [None])
        self.assertEqual(
            self.client.contexts["key-b"]["context"], {"project_name": "demo"}
        )

    def test_pin_without_tab(self) -> None:
        def call(method, params, timeout=None):  # noqa: ANN001, ANN202, ARG001
            msg = "no tab"
            raise BridgeError(msg, "not_connected")

        self.client.call = call
        self.assertIsNone(self.stub.pin_publisher_workflow())
        self.assertIsNone(self.stub.publisher_workflow)

    def test_save_collected_workflow(self) -> None:
        workflow = {"nodes": [], "extra": {"AYON": {"workfile_path": "x"}}}
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "shot_v001.json")
            with self.stub.target_workflow(A):
                self.stub.save_workfile_snapshot(path, workflow)
            with open(path, encoding="utf-8") as f:
                self.assertEqual(json.load(f), workflow)
        self.assertEqual(
            [p for m, p in self.client.calls if m == "finishSaveWorkfile"],
            [{"comfy_workflow_path": None, "snapshot": True, **A}],
        )

    def test_closed_workflow_has_no_workfile_path(self) -> None:
        def call(method, params, timeout=None):  # noqa: ANN001, ANN202, ARG001
            msg = "closed"
            raise BridgeError(msg, "workflow_closed")

        self.client.call = call
        with self.stub.target_workflow(A), self.assertRaises(BridgeError):
            self.stub.get_workfile_path()

    def test_no_tab_means_unsaved(self) -> None:
        def call(method, params, timeout=None):  # noqa: ANN001, ANN202, ARG001
            msg = "no tab"
            raise BridgeError(msg, "not_connected")

        self.client.call = call
        self.assertIsNone(self.stub.get_workfile_path())


if __name__ == "__main__":
    unittest.main()
