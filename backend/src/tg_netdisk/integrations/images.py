import asyncio
from pathlib import Path

from PIL import Image, ImageOps


async def derivative(source: str, destination: Path, thumbnail: bool = False) -> str:
    def convert():
        with Image.open(source) as source_image:
            image = ImageOps.exif_transpose(source_image).convert("RGB")
            image.thumbnail((320, 320) if thumbnail else (2560, 2560))
            destination.parent.mkdir(parents=True, exist_ok=True)
            quality = 90
            while True:
                image.save(destination, "JPEG", quality=quality)
                if not thumbnail or destination.stat().st_size < 195_000 or quality <= 30:
                    break
                quality -= 10
        return str(destination)

    return await asyncio.to_thread(convert)
