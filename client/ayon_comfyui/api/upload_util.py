"""Uploading stuff to ComfyUI."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import MutableMapping
from urllib.parse import urlparse

import aiohttp


async def upload_image(
    base_url: str,
    image_path: str | Path,
    *,
    type: str = "input",
    subfolder: str = "",
) -> MutableMapping | None:
    """Posts an image to /upload/image endpoint.

    Returns:
        JSON object response if succesful, otherwise None
    """
    if isinstance(image_path, str):
        image_path = Path(image_path)

    MIME_map = {  # noqa : N806
        # Common formats
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".jpe": "image/jpeg",
        ".jfif": "image/jpeg",
        ".webp": "image/webp",
        ".gif": "image/gif",
        ".bmp": "image/bmp",
        ".dib": "image/bmp",
        ".avif": "image/avif",
        ".heic": "image/heic",
        ".heif": "image/heif",
        ".jxl": "image/jxl",
        # Vector | Are we gonna use this?
        ".svg": "image/svg+xml",
        # TIFF
        ".tif": "image/tiff",
        ".tiff": "image/tiff",
        # Icons | Are we gonna use this?
        ".ico": "image/vnd.microsoft.icon",
        # Portable anymap formats | Are we gonna use this?
        ".pbm": "image/x-portable-bitmap",
        ".pgm": "image/x-portable-graymap",
        ".ppm": "image/x-portable-pixmap",
        # High dynamic range / VFX
        ".hdr": "image/vnd.radiance",  # Not sure about HDR
        ".exr": "image/x-exr",
        # Adobe / design  | Are we gonna use this?
        ".psd": "image/vnd.adobe.photoshop",
        # Less common / legacy
        ".pcx": "image/x-pcx",
        ".tga": "image/x-targa",
    }

    MIME_type = MIME_map.get(image_path.suffix)  # noqa : N806

    if MIME_type is None:
        # Maybe raise
        return None

    url_parsed = urlparse(base_url)
    post_url = url_parsed._replace(path="/upload/image").geturl()

    # we allow a file object here to allow for streaming in a session.
    async with aiohttp.ClientSession() as session:
        with image_path.open("rb") as image_file:  # noqa: ASYNC230
            data = aiohttp.FormData()
            data.add_field(
                "image",
                image_file,
                filename=image_path.name,
                content_type=MIME_type,
            )

            data.add_field("type", type)  # input by default

            if Path("AYON") in Path(subfolder).parents:
                # AYON folder is already present.
                subfolder_path = Path(subfolder)
            else:
                subfolder_path = (
                    (Path("AYON") / subfolder) if subfolder else Path("AYON")
                )

            data.add_field("subfolder", str(subfolder_path))

            async with session.post(post_url, data=data) as resp:
                return await resp.json()


def upload_input_image(
    base_url: str, image_path: str | Path, *, subfolder: str = ""
) -> dict:
    """Posts an image to /upload/image endpoint as input.

    Does so synchronously.

    The response JSON object has the following scheme:

    ```
    {
      'name': 'filename.png', # or other extension
      'subfolder': 'path/to/subfolder',
      'type': 'input'
    }
    ```

    Returns:
        JSON object response if succesful, otherwise None

    """
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    image_upload_info: dict[str, str] = loop.run_until_complete(
        upload_image(base_url, image_path, subfolder=subfolder)
    )

    image_upload_info["subfolder"] = image_upload_info["subfolder"].replace(
        "\\", "/"
    )

    return image_upload_info


def upload_input_images(
    image_paths: list[str], base_url: str, *, subfolder: str = ""
) -> list[MutableMapping] | None:
    """Posts an images to /upload/image endpoint as input.

    Waits synchronously, but images are all uploaded asynchronously.

    The response JSON objects have the following scheme:

    ```
    {
      'name': 'filename.png', # or other extension
      'subfolder': 'path/to/subfolder',
      'type': 'input'
    }
    ```

    Returns:
        JSON objects in list if response if succesful, otherwise None

    """
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    upload_infos = loop.run_until_complete(
        asyncio.gather(
            *[
                upload_image(base_url, image_path, subfolder=subfolder)
                for image_path in image_paths
            ]
        )
    )

    image_upload_info = []

    for upload_info in upload_infos:
        upload_info["subfolder"] = upload_info["subfolder"].replace("\\", "/")
        image_upload_info.append(upload_info)

    if image_upload_info:
        return image_upload_info

    return None
