from __future__ import annotations

from comfy_api.latest import io


class AyonContextNode(io.ComfyNode):
    """A node that is there for info to be imprinted upon."""

    @staticmethod
    def define_inputs() -> list[io.Input]:
        return [
            io.String.Input("ayon_context_info", "AYON context"),
        ]

    @classmethod
    def define_schema(cls):
        """Setup node definition."""
        return io.Schema(
            node_id="AYON Context",
            display_name="AYON Context",
            category="AYON",
            inputs=AyonContextNode.define_inputs(),
            hidden=[io.Hidden.unique_id],
        )

    @classmethod
    def execute(
        cls,
        ayon_context_info: str,
        unique_id: str,
    ) -> io.NodeOutput:
        """Main execution function."""

        return io.NodeOutput()
