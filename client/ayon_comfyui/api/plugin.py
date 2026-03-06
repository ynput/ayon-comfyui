"""Plugin helpers."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import ayon_api
from ayon_core.pipeline import AutoCreator, CreatedInstance

if TYPE_CHECKING:
    from ayon_core.pipeline.create.context import CreateContext

from ayon_comfyui.api.pipeline import list_instances
from ayon_comfyui.api.qt_rpc import QRPCManager


# Adapting from Photoshop
class ComfyUIAutoCreator(AutoCreator):
    """Generic ComfyUI autocreator to extend."""

    def get_instance_attr_defs(self):
        return []

    def collect_instances(self):
        for instance_data in list_instances():
            # Process only instances that were created by this creator
            creator_id = instance_data.get("creator_identifier")
            if creator_id == self.identifier:
                # Create instance object from existing data
                instance = CreatedInstance.from_existing(instance_data, self)
                # Add instance to create context
                self._add_instance_to_context(instance)

    def update_instances(self, update_list: list[tuple[CreatedInstance, Any]]):
        stub = QRPCManager.get_instance().stub
        updated = [
            instance.data_to_store() for instance, _changes in update_list
        ]
        stub.update_instance(updated)

    def create(self, options=None):
        stub = QRPCManager.get_instance().stub
        existing_instance = None
        for instance in self.create_context.instances:
            if instance.product_type == self.product_type:
                existing_instance = instance
                break

        context: CreateContext = self.create_context
        project_name = context.get_current_project_name()
        folder_path = context.get_current_folder_path()
        task_name = context.get_current_task_name()
        host_name = context.host_name

        if existing_instance is None:
            existing_instance_folder = None
        else:
            existing_instance_folder = existing_instance["folderPath"]

        if existing_instance is None:
            folder_entity = ayon_api.get_folder_by_path(
                project_name, folder_path
            )
            task_entity = ayon_api.get_task_by_name(
                project_name, folder_entity["id"], task_name
            )
            product_name = self.get_product_name(
                project_name,
                folder_entity,
                task_entity,
                self.default_variant,
                host_name,
            )
            data = {
                "folderPath": folder_path,
                "task": task_name,
                "variant": self.default_variant,
                "productName": product_name,
                "projectName": project_name,
            }
            data.update(
                self.get_dynamic_data(
                    project_name,
                    folder_entity,
                    task_entity,
                    self.default_variant,
                    host_name,
                    None,
                )
            )

            if not self.active_on_create:
                data["active"] = False

            new_instance = CreatedInstance(
                self.product_type, product_name, data, self
            )
            self._add_instance_to_context(new_instance)
            stub.update_instance(new_instance.data_to_store())

        elif (
            existing_instance_folder != folder_path
            or existing_instance["task"] != task_name
        ):
            folder_entity = ayon_api.get_folder_by_path(
                project_name, folder_path
            )
            task_entity = ayon_api.get_task_by_name(
                project_name, folder_entity["id"], task_name
            )
            product_name = self.get_product_name(
                project_name,
                folder_entity,
                task_entity,
                self.default_variant,
                host_name,
            )
            existing_instance["folderPath"] = folder_path
            existing_instance["task"] = task_name
            existing_instance["productName"] = product_name
            existing_instance["projectName"] = project_name
