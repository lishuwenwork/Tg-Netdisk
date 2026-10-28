import logging
import os
import secrets
from dataclasses import dataclass, field
from logging.handlers import RotatingFileHandler
from pathlib import Path


@dataclass
class Config:
    data_dir: Path = field(
        default_factory=lambda: Path(
            os.environ.get(
                "TG_DATA_DIR", str(Path(os.environ.get("LOCALAPPDATA", Path.home())) / "Tg Netdisk")
            )
        )
    )
    token: str = field(default_factory=lambda: os.environ.get("TG_RUNTIME_TOKEN", secrets.token_urlsafe(32)))
    origins: tuple[str, ...] = ("app://bundle", "http://127.0.0.1:5173")

    def prepare(self) -> None:
        for folder in ("cache/downloads", "cache/thumbnails", "media/frames", "logs"):
            (self.data_dir / folder).mkdir(parents=True, exist_ok=True)
        handler = RotatingFileHandler(
            self.data_dir / "logs/app.log", maxBytes=2_000_000, backupCount=3, encoding="utf-8"
        )
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        logger = logging.getLogger("tg_netdisk")
        logger.setLevel(logging.INFO)
        logger.addHandler(handler)


class AppError(Exception):
    def __init__(self, code: str, message: str, retryable: bool = False):
        self.code, self.message, self.retryable = code, message, retryable
        super().__init__(message)
