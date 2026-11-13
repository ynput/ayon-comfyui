"""Tests for `ayon_comfyui.api.comfy_publish` (no ComfyUI or AYON needed).

Run from the repository root with `python -m unittest discover -s tests`
(needs `aiohttp`, which `bridge_client` imports) or with pytest.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(__file__))
import _stubs  # noqa: E402, F401

from ayon_comfyui.api import comfy_publish as cp  # noqa: E402
from ayon_comfyui.api.bridge_client import BridgeError  # noqa: E402

INSTANCE = "11111111-2222-3333-4444-555555555555"


def save_node(instance_id=INSTANCE, recook=True, class_type="AYON Image Save"):
    return {
        "class_type": class_type,
        "inputs": {
            "images_in": ["1", 0],
            "recook": recook,
            "ayon_info": json.dumps({
                "instance_id": instance_id,
                "productName": "imageMain",
                "creator_attributes": {},
            }),
        },
    }


def history_entry(prompt_id, node_id="2", instance_id=INSTANCE, *,
                  status="success", finished=1000, files=None):
    files = files if files is not None else [{
        "filename": "ayon_0001.png",
        "subfolder": f"AYON/{instance_id}/{prompt_id}",
        "type": "output",
        "role": "main",
    }]
    return {
        "prompt": [
            0, prompt_id, {node_id: save_node(instance_id)},
            {"extra_pnginfo": {"workflow": {"nodes": []}}, "create_time": 1},
            [node_id],
        ],
        "outputs": {node_id: {
            "images": [dict(f) for f in files],
            "ayon": [{
                "instance_id": instance_id,
                "prompt_id": prompt_id,
                "files": files,
            }],
        }},
        "status": {
            "status_str": status,
            "completed": status == "success",
            "messages": [["execution_success", {"timestamp": finished}]]
            if status == "success" else
            [["execution_error", {
                "node_id": "2", "node_type": "AYON Image Save",
                "exception_message": "boom\n",
            }]],
        },
    }


class FakeHttp:
    """Scripted ComfyHttp: `routes` maps (method, path) to a value, a list
    of values consumed per call, or an exception."""

    def __init__(self, routes=None):
        self.routes = routes or {}
        self.calls = []
        self.downloads = []

    def http_json(self, method, path, **kwargs):
        self.calls.append((method, path, kwargs))
        value = self.routes.get((method, path))
        if isinstance(value, list):
            value = value.pop(0) if len(value) > 1 else value[0]
        if isinstance(value, Exception):
            raise value
        if callable(value):
            return value(**kwargs)
        return value

    def download(self, path, dest, **kwargs):
        self.downloads.append((path, dest, kwargs))
        with open(dest, "wb") as f:
            f.write(b"data")
        return 4


class FindSaveNodesTests(unittest.TestCase):
    def test_finds_nodes_by_instance(self):
        prompt = {
            "1": {"class_type": "EmptyImage", "inputs": {}},
            "2": save_node(recook=False),
            "3": save_node("other", class_type="AYON Video Save"),
        }
        nodes = cp.find_save_nodes(prompt)
        self.assertEqual(set(nodes), {INSTANCE, "other"})
        self.assertEqual(nodes[INSTANCE].node_id, "2")
        self.assertFalse(nodes[INSTANCE].recook)
        self.assertEqual(nodes["other"].class_type, "AYON Video Save")

    def test_duplicate_instance_is_an_error(self):
        prompt = {"2": save_node(), "9": save_node()}
        with self.assertRaisesRegex(cp.PublishError, "2 and 9"):
            cp.find_save_nodes(prompt)

    def test_linked_info_is_an_error(self):
        node = save_node()
        node["inputs"]["ayon_info"] = ["5", 0]
        with self.assertRaisesRegex(cp.PublishError, "another node"):
            cp.find_save_nodes({"2": node})

    def test_linked_recook_means_recook(self):
        node = save_node(recook=False)
        node["inputs"]["recook"] = ["7", 0]
        self.assertTrue(cp.find_save_nodes({"2": node})[INSTANCE].recook)


class QueuePromptTests(unittest.TestCase):
    def test_body(self):
        http = FakeHttp({("POST", "/prompt"): lambda json: {
            "prompt_id": json["prompt_id"], "number": 3, "node_errors": {},
        }})
        cp.queue_prompt(
            http, {"2": save_node()}, prompt_id="abc", targets=["2"],
            workflow={"w": 1}, client_id="tab",
        )
        body = http.calls[0][2]["json"]
        self.assertEqual(body["prompt_id"], "abc")
        self.assertEqual(body["partial_execution_targets"], ["2"])
        self.assertEqual(body["extra_data"]["extra_pnginfo"]["workflow"],
                         {"w": 1})
        self.assertEqual(body["client_id"], "tab")

    def test_refused_prompt_is_readable(self):
        error = BridgeError("HTTP 400", "http_400")
        error.status = 400
        error.body = {
            "error": {"message": "Prompt outputs failed validation",
                      "details": ""},
            "node_errors": {"2": {
                "class_type": "AYON Image Save",
                "errors": [{"message": "Required input is missing",
                            "details": "images_in"}],
            }},
        }
        http = FakeHttp({("POST", "/prompt"): error})
        with self.assertRaises(cp.PublishError) as ctx:
            cp.queue_prompt(http, {}, prompt_id="abc", targets=["2"])
        text = str(ctx.exception)
        self.assertIn("failed validation", text)
        self.assertIn("node 2 (AYON Image Save): Required input is missing: "
                      "images_in", text)


class WaitTests(unittest.TestCase):
    def wait(self, http, **kwargs):
        clock = iter(range(0, 100000, 10))
        return cp.wait_for_prompt(
            http, "abc", sleep=lambda _s: None,
            clock=lambda: next(clock), **kwargs,
        )

    def test_waits_through_queue_until_done(self):
        running = {"queue_running": [[0, "abc", {}, {}, []]],
                   "queue_pending": []}
        http = FakeHttp({
            ("GET", "/history/abc"): [
                {}, {}, {}, {"abc": history_entry("abc")}],
            ("GET", "/queue"): running,
        })
        logged = []
        entry = self.wait(http, log_progress=logged.append)
        self.assertEqual(entry["status"]["status_str"], "success")
        self.assertTrue(logged)  # the fake clock advances 10 s per call

    def test_error_status(self):
        http = FakeHttp({("GET", "/history/abc"): {
            "abc": history_entry("abc", status="error")}})
        with self.assertRaisesRegex(cp.PublishError,
                                    r"node 2 \(AYON Image Save\): boom"):
            self.wait(http)

    def test_removed_from_queue(self):
        http = FakeHttp({
            ("GET", "/history/abc"): {},
            ("GET", "/queue"): {"queue_running": [], "queue_pending": []},
        })
        with self.assertRaisesRegex(cp.PublishError, "removed from the queue"):
            self.wait(http)

    def test_timeout(self):
        http = FakeHttp({
            ("GET", "/history/abc"): {},
            ("GET", "/queue"): {"queue_running": [],
                                "queue_pending": [[1, "abc", {}, {}, []]]},
        })
        with self.assertRaisesRegex(cp.PublishError, "within 25 s"):
            self.wait(http, timeout=25)

    def test_survives_short_outage(self):
        down = BridgeError("down", "unreachable")
        http = FakeHttp({("GET", "/history/abc"): [
            down, down, {"abc": history_entry("abc")}]})
        self.assertIn("outputs", self.wait(http))

    def test_gives_up_after_long_outage(self):
        down = BridgeError("down", "unreachable")
        http = FakeHttp({("GET", "/history/abc"): down})
        with self.assertRaisesRegex(cp.PublishError, "Lost the connection"):
            self.wait(http)

    def test_queue_state(self):
        queue = {"queue_running": [],
                 "queue_pending": [[5, "b", {}, {}, []],
                                   [4, "a", {}, {}, []]]}
        self.assertEqual(cp.queue_state(queue, "b"), "pending, 1 ahead")
        self.assertIsNone(cp.queue_state(queue, "c"))


class CollectTests(unittest.TestCase):
    def test_node_files_merges_list_runs_and_filters_instance(self):
        outputs = {"ayon": [
            {"instance_id": INSTANCE, "files": [{"filename": "a.png"}]},
            {"instance_id": "x", "files": [{"filename": "x.png"}]},
            {"instance_id": INSTANCE, "files": [{"filename": "b.png"}]},
        ]}
        names = [f["filename"] for f in cp.node_files(outputs, INSTANCE)]
        self.assertEqual(names, ["a.png", "b.png"])

    def test_node_files_without_ayon_entry(self):
        outputs = {"images": [{"filename": "a.png", "type": "output"}]}
        self.assertEqual(cp.node_files(outputs, INSTANCE), [])
        self.assertEqual(cp.node_files(outputs)[0]["role"], "main")

    def test_latest_run_only_considers_owned_prompts(self):
        # "foreign" is the newest run of the same instance (e.g. another
        # artist opened the same workfile) but this session didn't queue it.
        http = FakeHttp({
            ("GET", "/history/mine-old"): {"mine-old": history_entry(
                "mine-old", finished=100)},
            ("GET", "/history/tab-new"): {"tab-new": history_entry(
                "tab-new", node_id="7", finished=200)},
            ("GET", "/history/foreign"): {"foreign": history_entry(
                "foreign", finished=999)},
        })
        run = cp.find_latest_run(http, INSTANCE, ["mine-old"], ["tab-new"])
        self.assertEqual((run.prompt_id, run.node_id), ("tab-new", "7"))
        self.assertEqual(run.workflow, {"nodes": []})
        self.assertIn("7", run.prompt)
        fetched = [path for _m, path, _k in http.calls]
        self.assertNotIn("/history/foreign", fetched)

    def test_latest_run_skips_failed_and_evicted(self):
        http = FakeHttp({
            ("GET", "/history/gone"): {},
            ("GET", "/history/failed"): {"failed": history_entry(
                "failed", status="error")},
            ("GET", "/history/ok"): {"ok": history_entry("ok")},
        })
        run = cp.find_latest_run(http, INSTANCE, ["gone", "failed", "ok"])
        self.assertEqual(run.prompt_id, "ok")
        self.assertIsNone(cp.find_latest_run(http, "nope", ["ok"]))

    def test_view_params_rejects_traversal(self):
        good = {"filename": "a.png", "subfolder": "AYON\\x\\y",
                "type": "output"}
        self.assertEqual(cp.view_params(good)["subfolder"], "AYON/x/y")
        for bad in (
            {"filename": "../a.png"},
            {"filename": "a/b.png"},
            {"filename": ".."},
            {"filename": ""},
            {"filename": "a.png", "subfolder": "../.."},
            {"filename": "a.png", "subfolder": "/etc"},
            {"filename": "a.png", "subfolder": "C:/x"},
            {"filename": "a.png", "type": "secret"},
        ):
            with self.assertRaises(cp.PublishError, msg=bad):
                cp.view_params(bad)

    def test_download_files(self):
        http = FakeHttp()
        with tempfile.TemporaryDirectory() as staging:
            names = cp.download_files(http, [
                {"filename": "a.png", "subfolder": "AYON/x", "type": "output"},
                {"filename": "b.png", "subfolder": "AYON/x", "type": "output"},
            ], staging)
            self.assertEqual(names, ["a.png", "b.png"])
            self.assertTrue(os.path.isfile(os.path.join(staging, "a.png")))
        self.assertEqual(http.downloads[0][2]["params"]["subfolder"], "AYON/x")
        with tempfile.TemporaryDirectory() as staging, \
                self.assertRaisesRegex(cp.PublishError, "both named"):
            cp.download_files(http, [{"filename": "a.png"}] * 2, staging)

    def test_registry(self):
        registry = cp.PromptRegistry(limit=2)
        for prompt_id in ("a", "b", "a", "c"):
            registry.add(prompt_id)
        self.assertEqual(registry.newest_first(), ["c", "a"])


if __name__ == "__main__":
    unittest.main()
