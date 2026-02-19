"""Using the V3 API to remain compatible for a loooooong time."""

from comfy_api.latest import ComfyExtension, io, ui
from torch import Tensor
from torchvision.transforms.v2.functional import rotate
from typing_extensions import override


class SasTestNode(io.ComfyNode):
    """A node that allows the user to rotate an image."""

    def __init__(self, *args, **kwargs):
        """Catch initialisation of instance."""
        print("Sas test node Initialized.")
        super().__init__(*args, **kwargs)

    def __del__(self, *args, **kwargs):
        """Catch destruction of instance."""
        print("Sas test node Destroyed.")
        # No destructor up top in the MRO
        # super().__del__(*args, **kwargs)

    @staticmethod
    def define_inputs() -> list[io.Input]:
        return [
            io.Image.Input("image_in", "Input Image"),
            io.Float.Input(
                "rotation",
                "Rotation angle (degrees)",
                default=0,
                min=0,
                max=360,
                step=0.25,
                display_mode=io.NumberDisplay.slider,
            ),
        ]

    @staticmethod
    def define_outputs() -> list[io.Output]:
        return [io.Image.Output(display_name="Output Image")]

    @classmethod
    def define_schema(cls):
        """Setup node definition."""
        return io.Schema(
            node_id="Sassy Test Node",
            display_name="Sassy Test Node",
            category="Submarine",
            inputs=SasTestNode.define_inputs(),
            hidden=[
                io.Hidden.prompt,
                io.Hidden.extra_pnginfo,
            ],
            outputs=SasTestNode.define_outputs(),
        )

    @staticmethod
    def img_comfy_to_torch(image: Tensor):
        """Transform comfy tesnor to torch.

        B: Batches
        H: Height
        W: Width
        C: Channels

        [B, H, W, C] -> [B, C, H, W]
        [0, 1, 2, 3] -> [0, 3, 1, 2]
        """
        return image.permute(0, 3, 1, 2)

    @staticmethod
    def img_torch_to_comfy(image: Tensor):
        """Transform torch tensor to comfy
        [B, C, H, W] -> [B, H, W, C]
        [0, 1, 2, 3] -> [0, 2, 3, 1]
        """

        return image.permute(0, 2, 3, 1)

    @classmethod
    def execute(
        cls,
        image_in: Tensor,
        rotation: float,
    ) -> io.NodeOutput:
        """Main execution function.

        The arguments for this function are the inputs by id as arguments.
        lets's say I have a [io.String.Input("mystring"), io.Float.Input("myfloat")]
        as inputs, this means the function signature will be:
        ```
        @classmethod
        def execute(cls, mystring, myfloat) -> io.NodeOutput:
            ...
        ```
        """
        # Do a torchvision rotate.

        image = cls.img_comfy_to_torch(image_in)
        image = rotate(image, -rotation)
        image = cls.img_torch_to_comfy(image)

        return io.NodeOutput(image, ui=ui.PreviewImage(image=image, cls=cls))


class SasExtension(ComfyExtension):
    @override
    async def get_node_list(self) -> list[type[io.ComfyNode]]:
        return [SasTestNode]


async def comfy_entrypoint() -> SasExtension:
    """initialization routine.
    This is async so we can have a couple attempts at
    websocket connections over here!
    """
    print("We initialize The Sas Extension...")
    return SasExtension()
