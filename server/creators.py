import re
from pydantic import validator

from ayon_server.exceptions import BadRequestException
from ayon_server.settings import (
    BaseSettingsModel,
    SettingsField,
)


class ProductTypeItemModel(BaseSettingsModel):
    _layout = "compact"
    product_type: str = SettingsField(
        title="Product type",
        description="Product type name",
    )
    label: str = SettingsField(
        "",
        title="Label",
        description="Label to display in UI for the product type",
    )


class BasicCreatorModel(BaseSettingsModel):
    enabled: bool = SettingsField(True, title="Enabled")
    default_variants: list[str] = SettingsField(
        default_factory=list, title="Default Variants"
    )
    product_type_items: list[ProductTypeItemModel] = SettingsField(
        default_factory=list,
        title="Product type items",
        description=(
            "Optional list of product types that this plugin can create."
        ),
    )

    @staticmethod
    def is_valid_variant(variant: str) -> bool:
        return re.fullmatch(r"[A-Za-z0-9_]+", variant)  # alphanumeric

    @validator("default_variants")
    def valid_variants(cls, value):
        for variant in value:
            if not cls.is_valid_variant(variant):
                raise BadRequestException(
                    f"Invalid characters in variant name {variant}. "
                    "Allowed characters are A-Za-z0-9_"
                )
        return value


class CreatorsModel(BaseSettingsModel):
    CreateImage: BasicCreatorModel = SettingsField(
        default_factory=BasicCreatorModel, title="Create Image"
    )
    CreateModel: BasicCreatorModel = SettingsField(
        default_factory=BasicCreatorModel, title="Create Model"
    )
    CreateVideo: BasicCreatorModel = SettingsField(
        default_factory=BasicCreatorModel, title="Create Video"
    )


DEFAULT_CREATORS_SETTINGS = {
    "CreateImage": {"default_variants": ["Main"], "enabled": True},
    "CreateModel": {"default_variants": ["Main"], "enabled": True},
    "CreateVideo": {"default_variants": ["Main"], "enabled": True},
}
