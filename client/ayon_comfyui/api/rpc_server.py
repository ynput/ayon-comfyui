from __future__ import annotations

import asyncio
import json
import logging
import pathlib
import sys

import aiohttp.web
from ayon_core.tools.utils import host_tools
from wsrpc_aiohttp import ClientException, Route, WebSocketAsync, decorators

from ayon_comfyui.api.consts import LOG_LEVEL
from ayon_comfyui.api.qtthread_interface import QThread_interface

logging.basicConfig(force=True, stream=sys.stdout, level=LOG_LEVEL)
log = logging.getLogger("ayon_comfyui")


def filter_exceptions(result: list):
    return next(
        (r for r in result if not isinstance(r, ClientException)), None
    )


def show_tool_by_name(tool_name):
    kwargs = {}
    if tool_name == "loader":
        kwargs["use_context"] = True
        kwargs["on_top"] = True

    if tool_name == "create":
        tool_name = "publisher"
        kwargs["tab"] = "create"

    host_tools.show_tool_by_name(tool_name, **kwargs)


class AyonLocalHost(Route):
    """Handle Menu calls from JS part of ComfyUI plugin."""

    qt_thread: QThread_interface = None

    def init(self, **kwargs):
        """Override of init method. Can return anything."""
        return kwargs

    @classmethod
    def register_qrpc_manager(cls, qrpc: QThread_interface):
        cls.qt_thread = qrpc

    @decorators.proxy
    async def pingAyonMenu(self, message: str):
        return message

    @decorators.proxy
    async def requestToolByName(self, tool_name: str):
        # TODO(@sas): CALL TO QT THREAD
        # We're updating this right now
        if self.qt_thread:
            self.qt_thread.schedule(show_tool_by_name, tool_name)
            return f"{tool_name} scheduled in qt_thread"
        return tool_name

    @decorators.proxy
    async def do_update_publishnodes(self) -> None:
        """Call method on the other side to retrieve publish nodes."""

        def dummy_callback_printresult(arg) -> None:
            """Ideally, this sort of function would feed back data into the qt thread"""
            print(arg)

        # fire off function and feed back returned result into function
        # TODO(@sas): This function SHOULD be present on the qt thread
        await self.socket.broadcast(
            "getPublishNodes", dummy_callback_printresult
        )

    @decorators.proxy
    async def do_retrieve_workfile(self) -> None:
        """Call method on the other side to retrieve workfile."""

        def dummy_callback_printresult(arg: str) -> None:
            """This sort of function should feed back data into the qt thread.

            Forwarding to Qt is now being handled by the server stub
            since the Route is poorly accessible.
            """
            log.info(arg)

        # TODO(@sas): Remove dummy functions or reroute to temp file.
        result: list = await self.socket.broadcast("getWorkfile")
        if isinstance(result, list) and len(result) > 0:
            dummy_callback_printresult(result)  # dummy file
            return filter_exceptions(
                result
            )  # return for client.call("getWorkfile", arg)

        return None

    @decorators.proxy
    async def do_load_workfile(self, workfile_path: str | None = None) -> None:
        """Call method on other side to load workfile into JS session"""
        # Read raw json content of file first.
        if not workfile_path or workfile_path is None:
            return

        workfile_json = ""

        workfile_json = pathlib.Path(workfile_path).read_text()

        result: list = await self.socket.broadcast(
            "loadWorkfile",
            workfile_json=workfile_json,
        )

        return

    # TODO(@sas): DEPRECATE
    @decorators.proxy
    async def do_imprint(self, imprint_info: str = "No imprint.") -> bool:
        """Creates a node in the browser session.

        Returns:
            True/False based on whether operation was succesful
        """

        def dummy_callback_printresult(arg: str) -> None:
            """This sort of function should feed back data into the qt thread.

            Forwarding to Qt is now being handled by the server stub
            since the Route is poorly accessible.
            """
            log.info(arg)

        # TODO(@sas): sign this with a session_id that's obtained
        # at launch creator window
        result = await self.socket.broadcast(
            "imprint",
            imprint_info=imprint_info,
        )
        dummy_callback_printresult(result)
        if isinstance(result, list) and len(result) > 0:
            dummy_callback_printresult(result)
            return filter_exceptions(result)

        return None

    @decorators.proxy
    async def do_context_imprint(
        self, imprint_info: str = "No imprint."
    ) -> bool:
        """Creates a node in the browser session.

        Returns:
            True/False based on whether operation was succesful
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
        existing = await self.socket.broadcast("getImprintContext")

        # ensure valid context
        if isinstance(existing, list) and len(existing) > 0:
            existing_ctx = filter_exceptions(existing)
        if existing_ctx is not None and existing_ctx:
            existing_ctx = json.loads(existing_ctx)
        else:
            existing_ctx = {}

        existing_ctx = self._ensure_wellformed_context(existing_ctx)

        # update context by overwriting
        existing_ctx["context"] = json.loads(imprint_info)

        result = await self.socket.broadcast(
            "setImprintContext",
            imprint_info=json.dumps(existing_ctx),
        )

        if isinstance(result, list) and len(result) > 0:
            return filter_exceptions(result)

        return None

    @decorators.proxy
    async def do_instances_imprint(self, imprint_info: str = "[]") -> bool:
        """Updates (replaces) "instances" field of context node.

        Returns:
            True/False based on whether operation was succesful
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
        existing = await self.socket.broadcast("getImprintContext")

        # ensure valid context
        if isinstance(existing, list) and len(existing) > 0:
            existing_ctx = filter_exceptions(existing)
        if existing_ctx is not None and existing_ctx:
            existing_ctx = json.loads(existing_ctx)
        else:
            existing_ctx = {}

        existing_ctx = self._ensure_wellformed_context(existing_ctx)

        log.info("updating info")
        # update context by overwriting
        existing_ctx["instances"] = json.loads(imprint_info)

        log.info("imprinting")
        result = await self.socket.broadcast(
            "setImprintContext",
            imprint_info=json.dumps(existing_ctx),
        )

        if isinstance(result, list) and len(result) > 0:
            return filter_exceptions(result)

        return None

    @decorators.proxy
    async def do_publishnode_create(self, instance_json: str) -> None:
        """Helper for creator to create a Ayon Image Save node."""
        await self.socket.broadcast(
            "addPublishNode", instance_json=instance_json
        )

    @decorators.proxy
    async def do_publishnodes_remove(self, publish_instances: str) -> str:
        """Remove Ayon Image Save nodes in graph.

        Corresponds to IDs sent.

        Returns:
            JSON representation of removed nodes.
        """
        publish_instances = json.loads(publish_instances)
        ids_to_remove = [
            instance["instance_id"] for instance in publish_instances
        ]

        result = await self.socket.broadcast(
            "removePublishNodes", ids_to_remove=ids_to_remove
        )

        if isinstance(result, list) and len(result) > 0:
            return filter_exceptions(result)

        return []

    @decorators.proxy
    async def do_get_publishnode_images(self, publish_instance: str) -> str:
        """Retrieve images from a node."""
        instance = json.loads(publish_instance)
        id_ = instance["instance_id"]

        result = await self.socket.broadcast(
            "getPublishNodeImages", id_for_images=id_
        )

        if isinstance(result, list) and len(result) > 0:
            return filter_exceptions(result)

        return "[]"

    @decorators.proxy
    async def do_context_retrieve(self) -> dict:
        """Creates a node in the browser session.

        Returns:
            Optional[Dict[str, Any]] of context
        """
        result = await self.socket.broadcast("getImprintContext")

        if isinstance(result, list) and len(result) > 0:
            ctx = filter_exceptions(result)
            log.info(ctx)
            ctx = ctx or json.dumps({})
            try:
                ctx = json.loads(ctx)
            except json.JSONDecodeError as e:
                log.debug(f"Error loading json ctx: {e}")  # noqa: G004
                ctx = {}
            ctx = self._ensure_wellformed_context(ctx)
            log.info("sending json string back")
            return json.dumps(ctx)  # safer to send a string

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

        return context


class RPCServer:
    """Manages event loop for the server that recieves messages.

    In particular, deal with the JavaScript part of the plugin.
    """

    def __init__(self, port: int = 55056, qthread: QThread_interface = None):
        self._app = None
        self._port = port
        self._setup = False
        self._is_running = False

        AyonLocalHost.register_qrpc_manager(qthread)

    def setup_server(self) -> None:
        """Set up server, do not start it yet."""
        self._app = aiohttp.web.Application()
        self._app.router.add_route("*", "/ws/", WebSocketAsync)
        WebSocketAsync.add_route("ayonComfyUI", AyonLocalHost)
        self._setup = True

    def run_server(self, port: int, loop: asyncio.AbstractEventLoop) -> None:
        """Block thread and run server on localhost."""
        if self.is_set_up:
            self._is_running = True
            aiohttp.web.run_app(self._app, port=port, loop=loop)

    @property
    def is_set_up(self) -> bool:
        """Return whether the server is set up.

        This doesn't mean that the server is running,
        but it means that the server is ready to run.
        """
        return self._setup
