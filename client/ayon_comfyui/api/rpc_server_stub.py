"""Runs a client to broadcast to JS."""

from __future__ import annotations

import asyncio
import logging
import sys
from collections import deque
from typing import TYPE_CHECKING, NoReturn

if TYPE_CHECKING:
    from collections.abc import Callable, Coroutine
import json
from concurrent.futures import Future
from threading import Thread
from typing import ClassVar

from wsrpc_aiohttp import WSRPCClient

from ayon_comfyui.api.qtthread_interface import QThread_interface

logging.basicConfig(force=True, stream=sys.stdout, level=logging.DEBUG)
log = logging.getLogger("ayon_comfyui")


# TODO(@sas): Deprecate
class TemporaryClientClass(Thread):
    def run(self):
        asyncio.run(self.async_run())

    async def async_run(self):
        log.info(
            "plan to attempt broadcast 'getWorkfile'"
            " to client websocket in 20 s"
        )
        await asyncio.sleep(20)

        temp_client = WSRPCClient("ws://localhost:55056/ws/")

        try:
            await temp_client.connect()
            result = await temp_client.call("ayonComfyUI.do_retrieve_workfile")
            log.info(result)
            result = await temp_client.call(
                "ayonComfyUI.do_imprint",
                imprint_info="Hi! I'm text that is going to be imprinted into the node.",
            )
        except BaseException as err:
            log.debug(f"Error on imprint: {err}")  # noqa: G004
        finally:
            await temp_client.close()


# TODO(@sas): Make sure this syncs with server settings for port.
class RPCServerStub:
    """Maintains a thread that executes functions on the server."""

    _awaitables_queue: ClassVar[deque] = deque()
    _qt_rpc: ClassVar[QThread_interface] | None = None
    _thread = None
    _ready = False
    _running = False

    class RPCServerClientThread(Thread):
        _client: ClassVar[WSRPCClient] = None

        def run(self):
            asyncio.run(self.async_run())

        async def async_run(self) -> NoReturn:
            """Plan to execute functions in queue."""
            self._client = WSRPCClient("ws://localhost:55056/ws/")
            try:
                await self._client.connect()
            except BaseException as e:  # noqa: BLE001
                log.debug(f"failure in server stub start {e}")  # noqa: G004

            while True:
                while len(RPCServerStub._awaitables_queue) > 0:
                    try:
                        coro, future, and_then = (
                            RPCServerStub._awaitables_queue.popleft()
                        )

                        # The return of this should be caught somehow
                        # Maybe we can schedule result processing with
                        # an associated function in the qt queue

                        result = await coro
                        log.info(result)
                        if future is not None:
                            future: Future
                            future.set_result(result)

                        if callable(and_then):
                            and_then(result)
                    except BaseException as e:  # noqa: PERF203, BLE001
                        log.debug(
                            "Error occured processing function "  # noqa: G004
                            f"in RPC Server Client Thread: {e}"
                        )

                await asyncio.sleep(0.1)

    @classmethod
    def setup_class(cls, qtrpc_man: QThread_interface) -> None:
        """Instantiate thread and link Qt thread."""
        cls._qt_rpc = qtrpc_man
        cls._thread = cls.RPCServerClientThread()
        cls._ready = True

    @property
    def is_ready(self) -> bool:
        """Indicates whether client thread is setup."""
        return self._ready

    @classmethod
    def run(cls) -> None:
        """Run internal thread if ready."""
        if not cls._ready:
            # Class is not ready yet
            return

        cls._thread.start()
        cls._running = True

    @property
    def is_running(self) -> bool:
        """Indicates whether internal thread is running."""
        return self._running

    @classmethod
    def _schedule(
        cls, coro: Coroutine, future: Future, and_then: Callable | None = None
    ) -> None:
        """Plan To Schedule function in held thread.

        Args:
            coro: Coroutine
            future: Future
            and_then: Callable

        Note that and_then should be a function that calls back to QRPCManager
        """
        cls._awaitables_queue.appendleft((coro, future, and_then))

    def query_workfile(self) -> None:
        """Query workfile operation and trigger the Qt loop after.

        WIP.
        """
        if not self._running:
            return None

        log.info("query_workfile")

        coro = self._thread._client.call("ayonComfyUI.do_retrieve_workfile")
        and_then = None

        workfile_fut = Future()

        if hasattr(self._qt_rpc, "schedule"):
            # and_then = self._qt_rpc.finish_workfiles
            and_then = None

        self._schedule(coro, workfile_fut, and_then)
        return workfile_fut.result()

    def load_workfile(self, path: str) -> None:
        """Query load workfile operation."""
        if not self._running:
            return

        log.info("load_workfile")

        coro = self._thread._client.call(
            "ayonComfyUI.do_load_workfile", workfile_path=path
        )
        and_then = None

        workfile_fut = Future()
        self._schedule(coro, workfile_fut, and_then)
        # block until load is complete.
        workfile_fut.result()

    def imprint_context(self, data: dict) -> None:
        """Query load workfile operation."""
        if not self._running:
            return

        log.info(f"imprint_context\n{data}")
        json_data = json.dumps(data)
        log.info(json_data)
        coro = self._thread._client.call(
            "ayonComfyUI.do_context_imprint", imprint_info=json_data
        )
        and_then = None

        context_set_fut = Future()
        self._schedule(coro, context_set_fut, and_then)
        # block until load is complete.
        context_set_fut.result()

    def _load_context(self) -> None:
        """Query load entire context operation."""
        if not self._running:
            return None
        log.info("_load_context (full context)")
        coro = self._thread._client.call("ayonComfyUI.do_context_retrieve")
        and_then = None

        context_get_fut = Future()
        self._schedule(coro, context_get_fut, and_then)
        # block until load is complete.
        context_json_raw = context_get_fut.result()
        log.info(context_json_raw)
        return (
            json.loads(context_json_raw)
            if context_json_raw is not None
            else {}
        )

    def load_context(self) -> None:
        """Query load context, return only the context."""
        context_json_raw = self._load_context()
        log.info("load context")
        if context_json_raw:
            return context_json_raw["context"]
        return None

    def list_instances(self) -> list[dict]:
        """Query load context, return only the instances."""
        context_json_raw = self._load_context()
        log.info("list instances")
        if context_json_raw:
            return context_json_raw["instances"]
        return None

    def _imprint_instances(self, data: list) -> None:
        """Hard update instance field of context node."""
        if not self._running:
            return

        log.info("imprint_instances")
        json_data = json.dumps(data)

        coro = self._thread._client.call(
            "ayonComfyUI.do_instances_imprint", imprint_info=json_data
        )
        and_then = None

        context_set_fut = Future()
        self._schedule(coro, context_set_fut, and_then)
        # block until load is complete.
        context_set_fut.result()

    @staticmethod
    def instances_check_duplicate(instances: list[dict]) -> list[dict]:
        encountered = []
        clean = []
        for instance in instances:
            id_ = instance.get("instance_id")
            if id_ not in encountered:
                encountered.append(id_)
                clean.append(instance)

        return clean

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
