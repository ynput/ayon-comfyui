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
            return value(json=kwargs.get("json"))
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


def not_found():
    error = BridgeError("HTTP 404", "http_404")
    error.status = 404
    error.body = {"error": "Job not found"}
    return error


class WaitTests(unittest.TestCase):
    def wait(self, http, **kwargs):
        clock = iter(range(0, 100000, 10))
        return cp.wait_for_prompt(
            http, "abc", sleep=lambda _s: None,
            clock=lambda: next(clock), **kwargs,
        )

    def test_waits_until_done(self):
        http = FakeHttp({
            ("GET", "/history/abc"): [
                {}, {}, {}, {"abc": history_entry("abc")}],
            ("GET", "/api/jobs/abc"): {"id": "abc", "status": "in_progress"},
        })
        logged = []
        entry = self.wait(http, log_progress=logged.append)
        self.assertEqual(entry["status"]["status_str"], "success")
        self.assertTrue(logged)  # the fake clock advances 10 s per call
        paths = {path for _m, path, _k in http.calls}
        self.assertNotIn("/queue", paths)  # never the whole queue

    def test_error_status(self):
        http = FakeHttp({("GET", "/history/abc"): {
            "abc": history_entry("abc", status="error")}})
        with self.assertRaisesRegex(cp.PublishError,
                                    r"node 2 \(AYON Image Save\): boom"):
            self.wait(http)

    def test_removed_from_queue(self):
        http = FakeHttp({
            ("GET", "/history/abc"): {},
            ("GET", "/api/jobs/abc"): not_found(),
        })
        with self.assertRaisesRegex(cp.PublishError, "removed from the queue"):
            self.wait(http)

    def test_old_comfyui_without_jobs_api(self):
        no_route = BridgeError("HTTP 404", "http_404")
        no_route.status = 404
        no_route.body = None
        http = FakeHttp({
            ("GET", "/history/abc"): [{}, {"abc": history_entry("abc")}],
            ("GET", "/api/jobs/abc"): no_route,
            ("GET", "/queue"): {"queue_running": [[0, "abc", {}, {}, []]],
                                "queue_pending": []},
        })
        self.assertIn("outputs", self.wait(http))

    def test_timeout(self):
        http = FakeHttp({
            ("GET", "/history/abc"): {},
            ("GET", "/api/jobs/abc"): {"id": "abc", "status": "pending"},
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


class PartialPromptTests(unittest.TestCase):
    def test_node_errors_on_200_cancel_and_fail(self):
        # ComfyUI queues a prompt when one output validates and silently
        # drops the others.
        http = FakeHttp({
            ("POST", "/prompt"): lambda json: {
                "prompt_id": json["prompt_id"], "number": 1,
                "node_errors": {"9": {
                    "class_type": "AYON Video Save",
                    "errors": [{"message": "Required input is missing",
                                "details": "video_in"}],
                }},
            },
            ("POST", "/api/jobs/abc/cancel"): {"cancelled": True},
        })
        with self.assertRaisesRegex(cp.PublishError,
                                    "node 9 .*video_in"):
            cp.queue_prompt(http, {}, prompt_id="abc", targets=["2", "9"])
        self.assertIn(("POST", "/api/jobs/abc/cancel", {}), http.calls)

    def test_extra_data_is_passed(self):
        http = FakeHttp({("POST", "/prompt"): lambda json: {
            "prompt_id": json["prompt_id"], "node_errors": {}}})
        cp.queue_prompt(http, {}, prompt_id="abc", targets=["2"],
                        workflow={"w": 1},
                        extra_data={"auth_token_comfy_org": "t"})
        extra = http.calls[0][2]["json"]["extra_data"]
        self.assertEqual(extra["auth_token_comfy_org"], "t")
        self.assertEqual(extra["extra_pnginfo"], {"workflow": {"w": 1}})


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

    def test_run_rejects_files_outside_instance_folder(self):
        entry = history_entry("p1", files=[{
            "filename": "a.png", "subfolder": "AYON/other-instance/p1",
            "type": "output"}])
        with self.assertRaisesRegex(cp.PublishError, "outside its output"):
            cp.run_from_history("p1", entry, "2", INSTANCE)

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
            ("GET", "/api/jobs/gone"): not_found(),
            ("GET", "/history/failed"): {"failed": history_entry(
                "failed", status="error")},
            ("GET", "/history/ok"): {"ok": history_entry("ok")},
        })
        run = cp.find_latest_run(http, INSTANCE, ["gone", "failed", "ok"])
        self.assertEqual(run.prompt_id, "ok")
        self.assertIsNone(cp.find_latest_run(http, "nope", ["ok"]))

    def test_newer_run_still_running_is_an_error(self):
        http = FakeHttp({
            ("GET", "/history/new"): {},
            ("GET", "/api/jobs/new"): {"id": "new", "status": "in_progress"},
            ("GET", "/history/old"): {"old": history_entry("old")},
        })
        with self.assertRaisesRegex(cp.PublishError, "still running"):
            cp.find_latest_run(http, INSTANCE, ["new", "old"])

    def test_upstream_ignores_ayon_inputs(self):
        prompt = {
            "1": {"class_type": "EmptyImage", "inputs": {"width": 8}},
            "2": save_node(recook=True),
            "3": {"class_type": "PreviewImage",
                  "inputs": {"images": ["1", 0]}},
        }
        other = json.loads(json.dumps(prompt))
        other["2"]["inputs"]["recook"] = False
        other["2"]["inputs"]["ayon_info"] = "{}"
        other["3"]["inputs"]["images"] = ["9", 0]
        self.assertEqual(set(cp.upstream(prompt, "2")), {"1", "2"})
        self.assertEqual(cp.upstream(prompt, "2"), cp.upstream(other, "2"))
        other["1"]["inputs"]["width"] = 16
        self.assertNotEqual(cp.upstream(prompt, "2"), cp.upstream(other, "2"))

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
            {"filename": "a.png", "type": "temp"},
            {"filename": "a.png", "type": "input"},
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
        registry = cp.PromptRegistry(limit=3)
        w1 = {"workflow_id": "g1", "workflow_path": "workflows/a.json"}
        w2 = {"workflow_id": "g2", "workflow_path": "workflows/b.json"}
        for prompt_id, workflow in (("a", w1), ("b", w2), ("a", w1),
                                    ("c", None), ("d", w1)):
            registry.add(prompt_id, workflow)
        self.assertEqual(registry.newest_first(), ["d", "c", "a"])
        self.assertEqual(registry.newest_first(w1), ["d", "c", "a"])
        self.assertEqual(registry.newest_first(w2), ["c"])
        # Renamed (e.g. saved as a new workfile version): same graph id.
        renamed = {"workflow_id": "g1", "workflow_path": "workflows/v2.json"}
        self.assertEqual(registry.newest_first(renamed), ["d", "c", "a"])

    def test_tab_prompt_ids_per_workflow(self):
        entries = [
            # A duplicated workflow: new graph id.
            {"prompt_id": "d", "workflow_id": "copy",
             "workflow_path": "workflows/shot (Copy).json"},
            # Queued before the tab was renamed to the workfile name.
            {"prompt_id": "c", "workflow_id": "g1",
             "workflow_path": "workflows/Unsaved Workflow.json"},
            # Recorded by an older version: path only.
            {"prompt_id": "b", "workflow_path": "workflows/shot.json"},
            {"prompt_id": "a", "workflow_path": "workflows/other.json"},
            "junk",
        ]
        current = {"workflow_id": "g1", "workflow_path": "workflows/shot.json"}
        self.assertEqual(cp.tab_prompt_ids(entries, current), ["c", "b"])
        self.assertEqual(cp.tab_prompt_ids(entries), ["d", "c", "b", "a"])

    def test_same_workflow(self):
        self.assertTrue(cp.same_workflow(
            {"workflow_id": "g", "workflow_path": "a"},
            {"workflow_id": "g", "workflow_path": "b"}))
        self.assertFalse(cp.same_workflow(
            {"workflow_id": "g", "workflow_path": "a"},
            {"workflow_id": "h", "workflow_path": "a"}))
        self.assertTrue(cp.same_workflow({"workflow_path": "a"}, None))

    def test_lookup_cache_and_lookback(self):
        http = FakeHttp({
            ("GET", "/history/ok"): {"ok": history_entry("ok")},
            ("GET", "/history/far"): {"far": history_entry("far")},
        })
        cache = {}
        cp.find_latest_run(http, INSTANCE, ["ok"], cache=cache)
        cp.find_latest_run(http, INSTANCE, ["ok"], cache=cache)
        fetched = [path for _m, path, _k in http.calls]
        self.assertEqual(fetched.count("/history/ok"), 1)
        self.assertIsNone(cp.find_latest_run(
            http, INSTANCE, ["x1", "x2", "far"], lookback=2))
        self.assertNotIn("/history/far",
                         [path for _m, path, _k in http.calls])

    def test_upstream_can_ignore_seeds(self):
        prompt = {
            "1": {"class_type": "KSampler",
                  "inputs": {"seed": 1, "steps": 20}},
            "2": {"class_type": "AYON Image Save",
                  "inputs": {"images_in": ["1", 0]}},
        }
        other = json.loads(json.dumps(prompt))
        other["1"]["inputs"]["seed"] = 2
        self.assertNotEqual(cp.upstream(prompt, "2"), cp.upstream(other, "2"))
        self.assertEqual(cp.upstream(prompt, "2", cp.SEED_INPUTS),
                         cp.upstream(other, "2", cp.SEED_INPUTS))

    def test_download_of_pruned_output(self):
        gone = BridgeError("HTTP 404", "http_404")
        gone.status = 404

        class GoneHttp(FakeHttp):
            def download(self, path, dest, **kwargs):
                raise gone

        with tempfile.TemporaryDirectory() as staging, \
                self.assertRaisesRegex(cp.PublishError, "no longer exists"):
            cp.download_files(GoneHttp(), [{"filename": "a.png"}], staging)


class RobustnessTests(unittest.TestCase):
    def test_wait_survives_proxy_errors(self):
        bad_gateway = BridgeError("HTTP 502", "http_502")
        bad_gateway.status = 502
        clock = iter(range(0, 100000, 10))
        http = FakeHttp({("GET", "/history/abc"): [
            bad_gateway, bad_gateway, {"abc": history_entry("abc")}]})
        entry = cp.wait_for_prompt(
            http, "abc", sleep=lambda _s: None, clock=lambda: next(clock))
        self.assertIn("outputs", entry)

    def test_queue_failure_cancels(self):
        timeout = BridgeError("timed out", "unreachable")
        http = FakeHttp({
            ("POST", "/prompt"): timeout,
            ("POST", "/api/jobs/abc/cancel"): {"cancelled": True},
        })
        with self.assertRaises(cp.PublishError):
            cp.queue_prompt(http, {}, prompt_id="abc", targets=["2"])
        self.assertIn(("POST", "/api/jobs/abc/cancel", {}), http.calls)

    def test_other_prompt_id_is_cancelled(self):
        http = FakeHttp({
            ("POST", "/prompt"): {"prompt_id": "theirs", "node_errors": {}},
            ("POST", "/api/jobs/abc/cancel"): {"cancelled": False},
            ("POST", "/api/jobs/theirs/cancel"): {"cancelled": True},
        })
        with self.assertRaisesRegex(cp.PublishError, "didn't queue"):
            cp.queue_prompt(http, {}, prompt_id="abc", targets=["2"])
        self.assertIn(("POST", "/api/jobs/theirs/cancel", {}), http.calls)


def probed(*streams, duration=None, error=None):
    """Return a fake `get_ffprobe_data` with this result."""
    data = {"streams": list(streams), "format": {}}
    if duration is not None:
        data["format"]["duration"] = duration
    if error is not None:
        data = {"error": {"code": -1, "string": error}}
    calls = []

    def probe(path):
        calls.append(path)
        return data

    probe.calls = calls
    return probe


class FrameRangeTests(unittest.TestCase):
    def test_images_are_frames_from_one_without_handles(self):
        self.assertEqual(cp.frame_range(3, 25.0), {
            "frameStart": 1, "frameEnd": 3,
            "handleStart": 0, "handleEnd": 0,
            "frameStartHandle": 1, "frameEndHandle": 3,
            "fps": 25.0,
        })

    def test_parse_frame_rate(self):
        self.assertEqual(cp.parse_frame_rate("24/1"), 24.0)
        self.assertAlmostEqual(cp.parse_frame_rate("24000/1001"), 23.976, 3)
        self.assertEqual(cp.parse_frame_rate(" 25 "), 25.0)
        for bad in ("0/0", "0/1", "-24/1", "", None, "N/A", "1/0",
                    "__import__('os').getcwd()", "24*2"):
            self.assertIsNone(cp.parse_frame_rate(bad), msg=bad)

    def test_mp4_uses_frame_count_and_rate(self):
        probe = probed(
            {"codec_type": "audio", "nb_frames": "94"},
            {"codec_type": "video", "nb_frames": "48",
             "r_frame_rate": "24000/1001", "avg_frame_rate": "24000/1001",
             "duration": "2.002000"},
        )
        data = cp.video_frame_range("/stage/v.mp4", 25.0, probe)
        self.assertEqual(probe.calls, ["/stage/v.mp4"])
        self.assertEqual((data["frameStart"], data["frameEnd"]), (1, 48))
        self.assertEqual((data["handleStart"], data["handleEnd"]), (0, 0))
        self.assertAlmostEqual(data["fps"], 24000 / 1001)

    def test_webm_without_frame_count_uses_duration(self):
        # What ffprobe tells of a 49 frame WebM from the AYON video save.
        probe = probed(
            {"codec_type": "video", "r_frame_rate": "2997/125",
             "avg_frame_rate": "2997/125"},
            duration="2.044000",
        )
        data = cp.video_frame_range("v.webm", 25.0, probe)
        self.assertEqual(data["frameEnd"], 49)
        self.assertAlmostEqual(data["fps"], 23.976)

    def test_rate_falls_back(self):
        probe = probed({"codec_type": "video", "r_frame_rate": "0/0",
                        "avg_frame_rate": "30/1", "duration": "2"})
        self.assertEqual(
            cp.video_frame_range("v.webm", 25.0, probe)["fps"], 30.0)
        probe = probed({"codec_type": "video", "r_frame_rate": "0/0",
                        "avg_frame_rate": "0/0"}, duration="2.0")
        data = cp.video_frame_range("v.webm", 25.0, probe)
        self.assertEqual((data["frameEnd"], data["fps"]), (50, 25.0))

    def test_unreadable_video_is_an_error_naming_it(self):
        def missing_ffprobe(_path):
            raise FileNotFoundError("[WinError 2] ffprobe not found")

        def no_json(_path):
            return json.loads(b"")

        for probe, reason in (
            (probed(error="Invalid data found when processing input"),
             "Invalid data found"),
            (probed({"codec_type": "audio"}, duration="2"),
             "no video stream"),
            (probed({"codec_type": "video", "r_frame_rate": "24/1"}),
             "neither the frame count nor the duration"),
            (missing_ffprobe, "ffprobe not found"),
            (no_json, "JSONDecodeError|Expecting value"),
            (lambda _path: None, "no video stream"),
        ):
            with self.assertRaisesRegex(cp.PublishError, reason) as ctx:
                cp.video_frame_range("/stage/broken.mp4", 25.0, probe)
            self.assertIn("/stage/broken.mp4", str(ctx.exception))


class ReviewFixTests(unittest.TestCase):
    def no_jobs_api(self):
        error = BridgeError("HTTP 404", "http_404")
        error.status = 404
        error.body = None  # no route, unlike {"error": "Job not found"}
        return error

    def test_fallback_cancel_only_interrupts_our_run(self):
        someone_else = {"queue_running": [[0, "theirs", {}, {}, []]],
                        "queue_pending": []}
        http = FakeHttp({
            ("POST", "/api/jobs/abc/cancel"): self.no_jobs_api(),
            ("POST", "/queue"): {},
            ("GET", "/queue"): someone_else,
        })
        cp.cancel_prompt(http, "abc")
        paths = [path for _m, path, _k in http.calls]
        self.assertNotIn("/interrupt", paths)

        ours = {"queue_running": [[0, "abc", {}, {}, []]],
                "queue_pending": []}
        http = FakeHttp({
            ("POST", "/api/jobs/abc/cancel"): self.no_jobs_api(),
            ("POST", "/queue"): {},
            ("GET", "/queue"): ours,
            ("POST", "/interrupt"): {},
        })
        self.assertTrue(cp.cancel_prompt(http, "abc"))
        self.assertIn("/interrupt", [path for _m, path, _k in http.calls])

    def test_view_params_refuses_streams(self):
        with self.assertRaises(cp.PublishError):
            cp.view_params({"filename": "a.png:secret", "type": "output"})

    def test_run_files_must_be_in_their_run_folder(self):
        for subfolder in (f"AYON/{INSTANCE}", f"AYON/{INSTANCE}/p1/deeper"):
            entry = history_entry("p1", files=[{
                "filename": "a.png", "subfolder": subfolder,
                "type": "output"}])
            with self.assertRaises(cp.PublishError, msg=subfolder):
                cp.run_from_history("p1", entry, "2", INSTANCE)


if __name__ == "__main__":
    unittest.main()
