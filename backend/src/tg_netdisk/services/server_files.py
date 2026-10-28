import asyncio
from pathlib import Path, PurePosixPath

from tg_netdisk.core.config import AppError

EXTENSIONS = {
    ".mp4",
    ".m4v",
    ".mov",
    ".mkv",
    ".webm",
    ".avi",
    ".ogg",
    ".ogv",
    ".jpg",
    ".jpeg",
    ".png",
    ".webp",
}


class ServerFiles:
    def __init__(self, root: Path):
        self.root = root.resolve()

    def resolve(self, relative: str) -> Path:
        value = PurePosixPath(relative)
        if (
            "\\" in relative
            or value.is_absolute()
            or ".." in value.parts
            or ":" in relative
            or "\x00" in relative
        ):
            raise AppError("MEDIA_PATH_DENIED", "只能选择媒体目录内的相对路径")
        path = (self.root / relative).resolve()
        if not path.is_relative_to(self.root):
            raise AppError("MEDIA_PATH_DENIED", "文件位于允许的媒体目录之外")
        return path

    async def browse(
        self, relative: str = "", query: str = "", offset: int = 0, limit: int = 100, kind: str = "media"
    ) -> dict:
        directory = self.resolve(relative)

        def read():
            if not directory.is_dir():
                raise AppError("MEDIA_DIRECTORY", "目录不可访问，请检查媒体目录挂载和读取权限")
            entries = []
            try:
                for path in directory.iterdir():
                    if path.name.startswith(".") or query.casefold() not in path.name.casefold():
                        continue
                    try:
                        resolved = path.resolve()
                        if not resolved.is_relative_to(self.root):
                            continue
                        is_directory = path.is_dir()
                        if (
                            kind == "image"
                            and not is_directory
                            and path.suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp"}
                        ):
                            continue
                        if not is_directory and (not path.is_file() or path.suffix.lower() not in EXTENSIONS):
                            continue
                        entries.append(
                            {
                                "name": path.name,
                                "path": path.relative_to(self.root).as_posix(),
                                "directory": is_directory,
                                "size": 0 if is_directory else path.stat().st_size,
                            }
                        )
                    except OSError:
                        continue
            except OSError as exc:
                raise AppError("MEDIA_DIRECTORY", "目录无读取权限") from exc
            entries.sort(key=lambda e: (not e["directory"], str(e["name"]).casefold()))
            return {
                "path": "" if directory == self.root else directory.relative_to(self.root).as_posix(),
                "entries": entries[offset : offset + limit],
                "total": len(entries),
                "offset": offset,
                "limit": limit,
            }

        return await asyncio.to_thread(read)
