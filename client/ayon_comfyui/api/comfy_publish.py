"""Run AYON publish outputs on ComfyUI and collect them from its history.

Publishing is driven by the AYON host, not by the browser:

1. The API-format prompt comes from the paired tab (`graphToPrompt`), and
   the AYON save nodes in it are matched to publish instances by their
   instance id (`find_save_nodes`).
2. With "recook", the host queues that prompt itself with a prompt id it
   chose, limited to the save nodes being published (`queue_prompt`), and
   waits for it in ComfyUI's history (`wait_for_prompt`). This needs no open
   tab while it runs, and has no time limit.
3. Without "recook", it takes the newest finished run of the save node among
   the prompts this AYON session queued or its paired tab queued
   (`find_latest_run`), never another artist's run of the same workfile.
4. The save nodes report their files in an `ayon` UI output entry
   (`node_files`). The host downloads them with URLs it builds itself from
   its own ComfyUI URL (`view_params`).

This module has no Qt or AYON dependencies, so it can be tested on its own;
`http` is anything with `ComfyHttp`'s `http_json`/`download` methods.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
import uuid
from collections import OrderedDict
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import Any, Protocol

from ayon_comfyui.api.bridge_client import BridgeError

log = logging.getLogger(__name__)

SAVE_NODE_TYPES = frozenset({
    "AYON Image Save",
    "AYON Video Save",
    "AYON 3D Model Save",
})
# Folder in ComfyUI's output directory the save nodes write into, as
# `AYON/<instance id>/<prompt id>/`.
AYON_OUTPUT_ROOT = "AYON"

# A prompt that is in neither the queue nor the history this many polls in
# a row was removed before it ran (or ComfyUI restarted and lost it).
MISSING_POLLS = 3
# Tolerate ComfyUI being unreachable (e.g. a proxy blip) this long.
UNREACHABLE_GRACE = 60.0
PROGRESS_LOG_INTERVAL = 30.0


class PublishError(RuntimeError):
    """Raised when ComfyUI outputs can't be produced or collected."""


class Http(Protocol):
    """What this module needs from `ComfyHttp`."""

    def http_json(self, method: str, path: str, **kwargs: Any) -> Any: ...  # noqa: ANN401, D102

    def download(self, path: str, dest: str, **kwargs: Any) -> int: ...  # noqa: ANN401, D102


@dataclass
class SaveNode:
    """An AYON save node in an API-format prompt."""

    node_id: str
    class_type: str
    instance_id: str
    recook: bool
    info: dict = field(repr=False)


@dataclass
class Run:
    """A finished ComfyUI run that produced an instance's outputs."""

    prompt_id: str
    node_id: str
    prompt: dict = field(repr=False)
    workflow: dict | None = field(repr=False)
    files: list[dict]


# --- prompts --------------------------------------------------------------


def new_prompt_id() -> str:
    """Return a prompt id ComfyUI accepts from clients (canonical UUID)."""
    return str(uuid.uuid4())


def find_save_nodes(prompt: dict) -> dict[str, SaveNode]:
    """Map instance ids to the AYON save nodes of an API-format prompt.

    Bypassed and muted nodes aren't part of an API prompt, so they're not
    found either.

    Raises:
        PublishError: When an AYON save node's data can't be read, or two
            save nodes belong to the same instance (e.g. a copy-pasted
            node), since it would be ambiguous which one to publish.
    """
    found: dict[str, SaveNode] = {}
    for node_id, node in (prompt or {}).items():
        if not isinstance(node, dict):
            continue
        class_type = node.get("class_type")
        if class_type not in SAVE_NODE_TYPES:
            continue
        inputs = node.get("inputs") or {}
        raw_info = inputs.get("ayon_info")
        if not isinstance(raw_info, str):
            msg = (
                f"The '{class_type}' node {node_id} gets its AYON info from "
                "another node. Its 'ayon_info' must be the node's own value."
            )
            raise PublishError(msg)
        try:
            info = json.loads(raw_info)
        except ValueError as exc:
            msg = f"The '{class_type}' node {node_id} has invalid AYON info."
            raise PublishError(msg) from exc
        if not isinstance(info, dict):
            info = {}
        instance_id = info.get("instance_id")
        if not isinstance(instance_id, str) or not instance_id:
            msg = f"The '{class_type}' node {node_id} has no instance id."
            raise PublishError(msg)
        if instance_id in found:
            msg = (
                f"AYON save nodes {found[instance_id].node_id} and {node_id} "
                f"both belong to the publish instance "
                f"'{info.get('productName', instance_id)}'. Delete one of "
                "them, or create a new instance for the copy."
            )
            raise PublishError(msg)
        recook = inputs.get("recook", False)
        found[instance_id] = SaveNode(
            node_id=str(node_id),
            class_type=class_type,
            instance_id=instance_id,
            # A linked value can't be read here; treat it as "recook".
            recook=True if isinstance(recook, list) else bool(recook),
            info=info,
        )
    return found


def queue_prompt(  # noqa: PLR0913
    http: Http,
    prompt: dict,
    *,
    prompt_id: str,
    targets: Iterable[str],
    workflow: dict | None = None,
    client_id: str | None = None,
    extra_data: dict | None = None,
) -> dict:
    """Queue `prompt` on ComfyUI, running only the `targets` output nodes.

    Args:
        http: ComfyUI HTTP client.
        prompt: API-format prompt.
        prompt_id: Id to queue the prompt under (see `new_prompt_id`).
        targets: Output node ids to run, with what they depend on.
        workflow: UI workflow, embedded in the outputs' metadata.
        client_id: ComfyUI client id of the tab that should show progress
            and previews. Only a display hint.
        extra_data: More `extra_data`, e.g. the tab's Comfy.org credentials
            for API nodes (ComfyUI keeps those out of its history).

    Raises:
        PublishError: When ComfyUI rejects the prompt, or would only run
            part of it.
    """
    targets = list(targets)
    body: dict[str, Any] = {
        "prompt": prompt,
        "prompt_id": prompt_id,
        "partial_execution_targets": targets,
        "extra_data": dict(extra_data or {}),
    }
    if workflow is not None:
        body["extra_data"]["extra_pnginfo"] = {"workflow": workflow}
    if client_id:
        body["client_id"] = client_id
    try:
        result = http.http_json("POST", "/prompt", json=body)
    except BridgeError as exc:
        if getattr(exc, "status", None) == 400:  # noqa: PLR2004
            details = describe_prompt_errors(
                getattr(exc, "body", None), prompt
            )
            msg = f"ComfyUI refused to run the graph:\n{details}"
            raise PublishError(msg) from exc
        raise PublishError(str(exc)) from exc
    if not isinstance(result, dict) or result.get("prompt_id") != prompt_id:
        msg = f"ComfyUI didn't queue the graph as expected: {result!r}"
        raise PublishError(msg)
    if result.get("node_errors"):
        # ComfyUI queues a prompt as long as *one* output validates, and
        # drops the others; a publish needs all of them.
        cancel_prompt(http, prompt_id)
        details = describe_prompt_errors(result, prompt)
        msg = f"ComfyUI can't run all AYON save nodes:\n{details}"
        raise PublishError(msg)
    return result


def cancel_prompt(http: Http, prompt_id: str) -> bool:
    """Cancel a queued or running prompt; never raises.

    Returns:
        Whether ComfyUI reports that it cancelled something.
    """
    try:
        result = http.http_json("POST", f"/api/jobs/{prompt_id}/cancel")
        return bool((result or {}).get("cancelled"))
    except BridgeError as exc:
        if getattr(exc, "status", None) != 404:  # noqa: PLR2004
            log.warning("Unable to cancel ComfyUI run %s: %s", prompt_id, exc)
            return False
    # ComfyUI without the jobs API.
    try:
        http.http_json("POST", "/queue", json={"delete": [prompt_id]})
        http.http_json("POST", "/interrupt", json={"prompt_id": prompt_id})
    except BridgeError as exc:
        log.warning("Unable to cancel ComfyUI run %s: %s", prompt_id, exc)
        return False
    return True


def describe_prompt_errors(body: Any, prompt: dict | None = None) -> str:  # noqa: ANN401
    """Return ComfyUI's validation errors for a refused prompt as text."""
    if not isinstance(body, dict):
        return "No details given."
    lines = []
    error = body.get("error")
    if isinstance(error, dict) and error.get("message"):
        line = str(error["message"])
        if error.get("details"):
            line = f"{line}: {error['details']}"
        lines.append(line)
    for node_id, node_error in (body.get("node_errors") or {}).items():
        class_type = (node_error or {}).get("class_type") or (
            (prompt or {}).get(node_id, {}).get("class_type", "")
        )
        for err in (node_error or {}).get("errors") or []:
            message = err.get("message", "")
            details = err.get("details", "")
            text = f"{message}: {details}" if details else message
            lines.append(f"- node {node_id} ({class_type}): {text}")
    return "\n".join(lines) or "No details given."


# --- waiting ----------------------------------------------------------------


def wait_for_prompt(  # noqa: C901, PLR0913
    http: Http,
    prompt_id: str,
    *,
    timeout: float | None = None,
    poll_interval: float = 1.0,
    max_poll_interval: float = 5.0,
    log_progress: Callable[[str], None] | None = None,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> dict:
    """Wait until ComfyUI finished `prompt_id`, and return its history entry.

    There is no time limit unless `timeout` is given: renders can take long,
    and nothing in ComfyUI waits for us meanwhile.

    Raises:
        PublishError: When the run failed or was interrupted, the prompt
            left the queue without running, ComfyUI stayed unreachable, or
            `timeout` passed.
    """
    started = clock()
    last_log = started
    unreachable_since: float | None = None
    missing = 0
    interval = poll_interval
    while True:
        try:
            history = http.http_json("GET", f"/history/{prompt_id}")
            entry = (history or {}).get(prompt_id)
            if entry is None:
                state = job_state(http, prompt_id)
            unreachable_since = None
        except BridgeError as exc:
            if exc.code != "unreachable":
                raise PublishError(str(exc)) from exc
            now = clock()
            unreachable_since = unreachable_since or now
            if now - unreachable_since > UNREACHABLE_GRACE:
                msg = f"Lost the connection to ComfyUI while waiting: {exc}"
                raise PublishError(msg) from exc
            sleep(interval)
            continue

        if entry is not None:
            status = entry.get("status") or {}
            if status.get("status_str") == "error":
                raise PublishError(describe_run_error(status))
            if status.get("completed", True):
                return entry
            # Finished without completing (e.g. no outputs ran).
            raise PublishError(describe_run_error(status))

        if state is None:
            missing += 1
            if missing >= MISSING_POLLS:
                msg = (
                    "The ComfyUI run was removed from the queue before it "
                    "finished (cancelled, or ComfyUI restarted)."
                )
                raise PublishError(msg)
        else:
            missing = 0

        now = clock()
        if timeout is not None and now - started > timeout:
            msg = f"ComfyUI didn't finish the run within {timeout:.0f} s."
            raise PublishError(msg)
        if log_progress and now - last_log >= PROGRESS_LOG_INTERVAL:
            last_log = now
            log_progress(
                f"Still waiting for ComfyUI ({state or 'unknown'}, "
                f"{now - started:.0f} s)..."
            )
        sleep(interval)
        interval = min(interval * 1.5, max_poll_interval)


def job_state(http: Http, prompt_id: str) -> str | None:
    """Return 'pending', 'running' (or 'finishing') or None when unknown.

    Uses ComfyUI's single-job API; the full `/queue` (every pending prompt
    with its whole graph) is only read on ComfyUI versions without it.
    """
    try:
        job = http.http_json("GET", f"/api/jobs/{prompt_id}")
    except BridgeError as exc:
        if getattr(exc, "status", None) != 404:  # noqa: PLR2004
            raise
        if isinstance(getattr(exc, "body", None), dict):
            return None  # {"error": "Job not found"}
        # No jobs API in this ComfyUI.
        return queue_state(http.http_json("GET", "/queue"), prompt_id)
    status = (job or {}).get("status")
    if status == "pending":
        return "pending"
    if status == "in_progress":
        return "running"
    if status:
        # Done, but not in the history we just read: it just finished.
        return "finishing"
    return None


def queue_state(queue: Any, prompt_id: str) -> str | None:  # noqa: ANN401
    """Return 'running', 'pending, N ahead' or None when not queued."""
    if not isinstance(queue, dict):
        return None
    for item in queue.get("queue_running") or []:
        if _queue_item_id(item) == prompt_id:
            return "running"
    pending = sorted(
        (item for item in queue.get("queue_pending") or []
         if isinstance(item, list) and item),
        key=lambda item: item[0],
    )
    for ahead, item in enumerate(pending):
        if _queue_item_id(item) == prompt_id:
            return f"pending, {ahead} ahead"
    return None


def _queue_item_id(item: Any) -> Any:  # noqa: ANN401
    if isinstance(item, list) and len(item) > 1:
        return item[1]
    return None


def describe_run_error(status: dict) -> str:
    """Return why a ComfyUI run failed, from its history status."""
    for message in status.get("messages") or []:
        if not isinstance(message, list) or len(message) < 2:  # noqa: PLR2004
            continue
        kind, data = message[0], message[1] or {}
        if kind == "execution_error":
            exception = str(data.get("exception_message") or "").strip()
            return (
                f"ComfyUI failed in node {data.get('node_id')} "
                f"({data.get('node_type')}): {exception or 'unknown error'}"
            )
        if kind == "execution_interrupted":
            return (
                f"The ComfyUI run was interrupted at node "
                f"{data.get('node_id')} ({data.get('node_type')})."
            )
    return "ComfyUI didn't finish the run."


# --- collecting -----------------------------------------------------------


def node_files(node_outputs: Any, instance_id: str) -> list[dict]:  # noqa: ANN401
    """Return the files an AYON save node reported for `instance_id`.

    Reads the node's `ayon` UI output entries (all of them: a node with a
    list input runs, and reports, more than once).
    """
    if not isinstance(node_outputs, dict):
        return []
    files = []
    for entry in node_outputs.get("ayon") or []:
        if not isinstance(entry, dict):
            continue
        if entry.get("instance_id") != instance_id:
            continue
        files.extend(
            item for item in entry.get("files") or []
            if isinstance(item, dict)
        )
    return files


def run_from_history(
    prompt_id: str, entry: dict, node_id: str, instance_id: str
) -> Run:
    """Return the run of `node_id` in a history entry.

    Raises:
        PublishError: When the node reported no files for the instance, or
            files outside the instance's AYON output folder.
    """
    node_outputs = (entry.get("outputs") or {}).get(node_id)
    files = node_files(node_outputs, instance_id)
    if not files:
        msg = (
            f"The AYON save node {node_id} produced no files in ComfyUI run "
            f"{prompt_id}."
        )
        raise PublishError(msg)
    expected = f"{AYON_OUTPUT_ROOT}/{instance_id}/"
    for file in files:
        subfolder = view_params(file)["subfolder"] + "/"
        if not subfolder.startswith(expected):
            msg = (
                f"The AYON save node {node_id} reported a file outside its "
                f"output folder: {file!r}"
            )
            raise PublishError(msg)
    prompt, workflow = prompt_of_entry(entry)
    return Run(prompt_id, node_id, prompt, workflow, files)


def prompt_of_entry(entry: dict) -> tuple[dict, dict | None]:
    """Return the API prompt and UI workflow stored in a history entry."""
    item = entry.get("prompt")
    prompt: dict = {}
    workflow = None
    if isinstance(item, list) and len(item) > 3:  # noqa: PLR2004
        if isinstance(item[2], dict):
            prompt = item[2]
        extra = item[3] if isinstance(item[3], dict) else {}
        pnginfo = extra.get("extra_pnginfo")
        if isinstance(pnginfo, dict) and isinstance(
            pnginfo.get("workflow"), dict
        ):
            workflow = pnginfo["workflow"]
    return prompt, workflow


def find_latest_run(
    http: Http, instance_id: str, *prompt_id_lists: Iterable[str]
) -> Run | None:
    """Return the newest successful run that has outputs for `instance_id`.

    Only the given prompts are considered: the ones this AYON session
    queued, and the ones its paired tab queued, each list newest first. They
    are fetched one by one, so a long or shared history is never downloaded
    as a whole, and each list is only read up to its first match.

    Raises:
        PublishError: When a prompt newer than the match is still queued or
            running, since it would probably make newer outputs.
    """
    best: tuple[int, Run] | None = None
    checked: set[str] = set()
    for prompt_ids in prompt_id_lists:
        for prompt_id in prompt_ids or []:
            if not isinstance(prompt_id, str) or prompt_id in checked:
                continue
            checked.add(prompt_id)
            entry = _history_entry(http, prompt_id)
            if entry is None:
                _check_not_running(http, prompt_id)
                continue
            found = _run_in_entry(prompt_id, entry, instance_id)
            if found is None:
                continue
            if best is None or found[0] > best[0]:
                best = found
            break
    return best[1] if best is not None else None


def _history_entry(http: Http, prompt_id: str) -> dict | None:
    try:
        history = http.http_json("GET", f"/history/{prompt_id}")
    except BridgeError as exc:
        raise PublishError(str(exc)) from exc
    entry = (history or {}).get(prompt_id)
    return entry if isinstance(entry, dict) else None


def _check_not_running(http: Http, prompt_id: str) -> None:
    try:
        state = job_state(http, prompt_id)
    except BridgeError as exc:
        raise PublishError(str(exc)) from exc
    if state and (state == "running" or state.startswith("pending")):
        msg = (
            f"A newer ComfyUI run of this workflow ({prompt_id}) is still "
            f"{state}. Wait for it to finish before publishing, or enable "
            "'Recook on publish'."
        )
        raise PublishError(msg)


def _run_in_entry(
    prompt_id: str, entry: dict, instance_id: str
) -> tuple[int, Run] | None:
    status = entry.get("status") or {}
    if status.get("status_str") != "success":
        return None
    for node_id, node_outputs in (entry.get("outputs") or {}).items():
        if node_files(node_outputs, instance_id):
            run = run_from_history(prompt_id, entry, node_id, instance_id)
            return finished_at(entry), run
    return None


def finished_at(entry: dict) -> int:
    """Return when a run finished (ms since epoch), 0 when unknown."""
    status = entry.get("status") or {}
    for message in status.get("messages") or []:
        if (
            isinstance(message, list)
            and len(message) > 1
            and message[0] == "execution_success"
            and isinstance(message[1], dict)
        ):
            return int(message[1].get("timestamp") or 0)
    item = entry.get("prompt")
    if isinstance(item, list) and len(item) > 3 and isinstance(item[3], dict):  # noqa: PLR2004
        return int(item[3].get("create_time") or 0)
    return 0


def upstream(prompt: dict, node_id: str) -> dict:
    """Return the part of `prompt` that `node_id` depends on.

    The node's own AYON inputs are left out, so comparing two of these
    tells whether two runs computed the same thing.
    """
    result: dict = {}
    pending = [str(node_id)]
    while pending:
        current = pending.pop()
        if current in result or current not in prompt:
            continue
        node = prompt[current]
        inputs = dict(node.get("inputs") or {})
        if current == str(node_id):
            inputs.pop("ayon_info", None)
            inputs.pop("recook", None)
        result[current] = {
            "class_type": node.get("class_type"),
            "inputs": inputs,
        }
        pending.extend(
            str(value[0]) for value in inputs.values()
            if isinstance(value, list) and value
        )
    return result


def view_params(file: dict) -> dict:
    """Return the `/view` query for an output file, after checking it.

    Raises:
        PublishError: For anything but a plain file name in a relative
            subfolder of ComfyUI's output directory.
    """
    filename = file.get("filename") if isinstance(file, dict) else None
    if (
        not isinstance(filename, str)
        or not filename
        or filename in {".", ".."}
        or os.path.basename(filename) != filename
        or "/" in filename
        or "\\" in filename
    ):
        msg = f"Refusing to download an invalid output file name: {file!r}"
        raise PublishError(msg)
    subfolder = str(file.get("subfolder") or "").replace("\\", "/")
    parts = [part for part in subfolder.split("/") if part]
    if (
        subfolder.startswith("/")
        or ":" in subfolder
        or any(part in {".", ".."} for part in parts)
    ):
        msg = f"Refusing to download from an invalid subfolder: {file!r}"
        raise PublishError(msg)
    if (file.get("type") or "output") != "output":
        msg = f"Refusing to download a file that isn't an output: {file!r}"
        raise PublishError(msg)
    return {
        "filename": filename,
        "subfolder": "/".join(parts),
        "type": "output",
    }


def download_files(
    http: Http, files: Iterable[dict], staging_dir: str
) -> list[str]:
    """Download output files into `staging_dir`; return their file names.

    Raises:
        PublishError: For invalid file references, duplicate names, or when
            a download fails.
    """
    names = []
    for file in files:
        params = view_params(file)
        name = params["filename"]
        if name in names:
            msg = f"Two outputs are both named '{name}'."
            raise PublishError(msg)
        try:
            http.download(
                "/view", os.path.join(staging_dir, name), params=params
            )
        except BridgeError as exc:
            raise PublishError(str(exc)) from exc
        names.append(name)
    return names


# --- prompts this session may collect ---------------------------------------


class PromptRegistry:
    """Prompts this AYON session queued itself, with their workflow."""

    def __init__(self, limit: int = 256) -> None:
        self._prompts: OrderedDict[str, str | None] = OrderedDict()
        self._limit = limit
        self._lock = threading.Lock()

    def add(self, prompt_id: str, workflow_path: str | None = None) -> None:
        """Remember that this session queued `prompt_id`."""
        with self._lock:
            self._prompts.pop(prompt_id, None)
            self._prompts[prompt_id] = workflow_path
            while len(self._prompts) > self._limit:
                self._prompts.popitem(last=False)

    def newest_first(self, workflow_path: str | None = None) -> list[str]:
        """Return the remembered ids, newest first.

        With `workflow_path`, only prompts queued from that ComfyUI
        workflow (or from an unknown one).
        """
        with self._lock:
            return [
                prompt_id
                for prompt_id, path in reversed(self._prompts.items())
                if not workflow_path or not path or path == workflow_path
            ]


#: Prompts queued by this AYON host process.
QUEUED_PROMPTS = PromptRegistry()


def tab_prompt_ids(
    entries: Iterable[Any],  # noqa: ANN401
    workflow_path: str | None = None,
) -> list[str]:
    """Return the ids of the tab's queued prompts for a workflow.

    `entries` are the tab's `{prompt_id, workflow_path}` records, newest
    first. A copy of a workflow keeps its AYON instance ids, so runs of
    other workflows (tabs) are left out.
    """
    ids = []
    for entry in entries or []:
        if not isinstance(entry, dict):
            continue
        prompt_id = entry.get("prompt_id")
        path = entry.get("workflow_path")
        if not isinstance(prompt_id, str) or not prompt_id:
            continue
        if workflow_path and path and path != workflow_path:
            continue
        ids.append(prompt_id)
    return ids
