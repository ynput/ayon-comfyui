from typing import TYPE_CHECKING

import ayon_api
from ayon_core.pipeline import AutoCreator, CreatedInstance

if TYPE_CHECKING:
    from ayon_core.pipeline.create import CreateContext


class ComfyAutoCreator(AutoCreator):
    """Generic Auto Creator"""

    def get_instance_attr_defs(self):
        # There's no extra attribute definitions.
        return []

    def create(self):
        existing_instance = None
        context: CreateContext = self.create_context

        for instance in context.instances:
            if instance.product_type == self.product_type:
                existing_instance = instance
                break

        if existing_instance is None:
            existing_instance_folder = None
        else:
            existing_instance_folder = existing_instance["folderPath"]

        project_name = context.get_current_project_name()
        folder_path = context.get_current_folder_path()
        task_name = context.get_current_task_name()
        host_name = context.host_name

        self.get_dynamic_data()

        if existing_instance is None:
            folder_entity = ayon_api.get_folder_by_path(
                project_name, folder_path
            )
            task_entity = ayon_api.get_task_by_name(
                project_name, folder_entity["id"], task_name
            )
            product_name = self.get_product_name(
                project_name=project_name,
                folder_entity=folder_entity,
                task_entity=task_entity,
                variant=self.default_variant,
                host_name=host_name,
            )
            data = {
                "folderPath": folder_path,
                "task": task_name,
                "variant": self.default_variant,
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
            # ADD TO STUB META
            self._add_instance_to_context(new_instance)
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
                project_name=project_name,
                folder_entity=folder_entity,
                task_entity=task_entity,
                variant=self.default_variant,
                host_name=host_name,
            )
            existing_instance["folderPath"] = folder_path
            existing_instance["task"] = task_name
            existing_instance["productName"] = product_name
