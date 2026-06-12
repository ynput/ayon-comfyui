"""Runs a client to broadcast to JS."""

from __future__ import annotations

import logging
import sys
from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import MutableMapping

import json
from pathlib import Path

from ayon_core.pipeline import get_current_context

from ayon_comfyui.api.consts import LOG_LEVEL
from ayon_comfyui.api.rpc_server import (
    call_on_origin,
    get_client_from_origin,
    pull_origin_from_settings,
)

logging.basicConfig(force=True, stream=sys.stdout, level=LOG_LEVEL)
log = logging.getLogger("ayon_comfyui")


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


# STUB TO CONTAIN CLIENT CONNECTION GOTTEN FROM SERVER
class RPCClientStub:  # noqa: PLR0904
    """Alias methods on the client <iframe> side.

    Also provides helper methods to process results.

    DO NOT USE DIRECTLY. These are meant to be used in RPCStub.
    """

    # Static site hosting iframe.
    # TODO(@sas): retrieve from url settings
    origin: str = "http://127.0.0.1:5454"

    def __init__(self):  # noqa: D107
        self.__class__.origin = pull_origin_from_settings()

    @property
    def client(self):  # noqa: ANN201
        """Returns WSRPCBase connection to client in origin.

        Should remain unused since @call_on_origin() takes care of this,
        but can be used for testing routes directly by calling them on
        the client.
        """
        return get_client_from_origin(self.origin)

    @call_on_origin()
    def getPublishNodes(self, node_type: str):  # noqa: N802, ANN201
        """Call getPublishNodes."""

    # def do_update_publishnodes(self) -> None: # Never used

    @call_on_origin()
    def getWorkfile(self):  # noqa: N802, ANN201
        """Call getWorkfile."""

    @call_on_origin()
    def updateTab(self, *, new_name: str):  # noqa: N802, ANN201
        """Call updateTab.

        switches context to a new tab with a new name.
        """

    @call_on_origin()
    def loadWorkfile(self, *, workfile_json: str, workfile_name: str):  # noqa: N802, ANN201
        """Call loadWorkfile."""

    def do_load_workfile(self, workfile_path: str | None = None) -> None:
        """Load contents of workfile into ComfyUI session."""
        if not workfile_path:
            return

        workfile_json = (workfile := Path(workfile_path)).read_text(
            encoding="utf-8"
        )
        self.loadWorkfile(
            workfile_json=workfile_json, workfile_name=workfile.name
        )

    @call_on_origin()
    def getImprintContext(self) -> str:  # noqa: N802
        """Call getImprintContext."""

    @call_on_origin()
    def setImprintContext(self, *, imprint_info: str) -> bool:  # noqa: N802, ANN201
        """Call setImprintContext."""

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

    @call_on_origin()
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

    @call_on_origin()
    def removePublishNodes(self, *, ids_to_remove: str, node_type: str) -> str:  # noqa: N802
        """Call removePublishNodes.

        ids_to_remove has to contain a json list of instance ids associated
        with publish instances to remove.

        Returns a string json representation of instances that were removed.
        """

    @call_on_origin(wait_forever=True)
    def getPublishNodeImages(  # noqa: N802
        self, *, id_for_images: str, node_type: str
    ) -> str:
        """Call getPublishNodeImages.

        id_for_images has to contain a single instance ids associated with
        publish instances to retrieve images from.

        Returns a string json representation of a list of image locations
        on network.

        Waits until graph has finished cooking.
        """

    @call_on_origin()
    def addLoadProductNode(  # noqa: N802
        self, *, container_json: str, node_type: str
    ) -> None:
        """Call addLoadProductNode.

        container_json has to contain a single image container dict serialized
        as json. This will be imprinted on the node.
        Make sure to upload the image before uploading.
        """

    @call_on_origin()
    def removeLoadProductNodes(  # noqa: N802
        self, *, ids_to_remove: str, node_type: str
    ) -> None:
        """Call removeLoadProductNodes.

        ids_to_remove has to contain a json list of container uuids associated
        with containers to remove.

        Returns a string json representation of containers that were removed.
        """

    @call_on_origin()
    def updateLoadProductNode(  # noqa: N802
        self, *, container_json: str, node_type: str = "ALL"
    ) -> None:
        """Call updateLoadProductNode.

        Uses the container_json container_uuid
        to match nodes present in the scene.

        Sentinel value ALL will match for all types of container nodes.
        """

    def do_get_publishnode_images(
        self, publish_instance: str, node_type: PublishType = PublishType.IMAGE
    ) -> str:
        """Retrieve images field from a node.

        Returns:
            string JSON list representation of links to output product type.
        """
        instance = json.loads(publish_instance)
        id_ = instance["instance_id"]

        result = self.getPublishNodeImages(
            id_for_images=id_, node_type=node_type.value
        )

        if result:
            return result

        return "[]"

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


class RPCStub:  # noqa : PLR0904
    """Wrapper to expose client functionality.

    Exposes client calls in a sane way to the plugin.
    """

    def __init__(self):  # noqa: D107
        self.client_stub = RPCClientStub()

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

    def imprint_context(self, data: dict) -> None:
        """Query imprint contect operation."""
        log.debug(f"imprint_context\n{data}")  # noqa: G004
        json_data = json.dumps(data)
        log.debug(json_data)
        self.client_stub.do_context_imprint(imprint_info=json_data)

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
            self.imprint_context(context)
            context_json_raw = self.client_stub.do_context_retrieve()

        log.debug(context_json_raw)
        return (
            json.loads(context_json_raw)
            if context_json_raw is not None
            else {}
        )

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

    def get_publish_node_images(
        self,
        instance_for_images: dict,
        publish_type: PublishType = PublishType.IMAGE,
    ) -> list[str]:
        """Returns list of products associated with node."""
        log.debug("stub get publish node images")
        id_ = instance_for_images["instance_id"]
        result = self.client_stub.getPublishNodeImages(
            id_for_images=id_, node_type=publish_type.value
        )
        try:
            return json.loads(result)
        except json.JSONDecodeError:
            return []
