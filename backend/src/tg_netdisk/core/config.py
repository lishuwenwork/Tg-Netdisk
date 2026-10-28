import logging
import os
import secrets
from dataclasses import dataclass, field
from logging.handlers import RotatingFileHandler
from pathlib import Path
from urllib.parse import urlsplit


@dataclass
class Config:
    mode: str = field(default_factory=lambda: os.environ.get("TG_MODE", "desktop"))
    data_dir: Path = field(
        default_factory=lambda: Path(
            os.environ.get(
                "TG_DATA_DIR", str(Path(os.environ.get("LOCALAPPDATA", Path.home())) / "Tg Netdisk")
            )
        )
    )
    token: str = field(default_factory=lambda: os.environ.get("TG_RUNTIME_TOKEN", secrets.token_urlsafe(32)))
    origins: tuple[str, ...] = ("app://bundle", "http://127.0.0.1:5173")
    public_origin: str = field(
        default_factory=lambda: os.environ.get("TG_PUBLIC_ORIGIN", "http://localhost:8080").rstrip("/")
    )
    media_root: Path = field(default_factory=lambda: Path(os.environ.get("TG_MEDIA_ROOT", "/media")))
    frontend_dir: Path | None = field(
        default_factory=lambda: Path(os.environ["TG_FRONTEND_DIR"])
        if os.environ.get("TG_FRONTEND_DIR")
        else None
    )
    web_password_file: Path | None = field(
        default_factory=lambda: Path(os.environ["TG_WEB_PASSWORD_FILE"])
        if os.environ.get("TG_WEB_PASSWORD_FILE")
        else None
    )
    secret_key_file: Path | None = field(
        default_factory=lambda: Path(os.environ["TG_SECRET_KEY_FILE"])
        if os.environ.get("TG_SECRET_KEY_FILE")
        else None
    )

    @property
    def allowed_origins(self) -> tuple[str, ...]:
        return (self.public_origin,) if self.mode == "web" else self.origins

    @property
    def allowed_hosts(self) -> list[str]:
        return (
            [urlsplit(self.public_origin).hostname or "localhost", "127.0.0.1", "localhost"]
            if self.mode == "web"
            else ["127.0.0.1", "testserver"]
        )

    def prepare(self) -> None:
        if self.mode not in ("desktop", "web"):
            raise ValueError("TG_MODE must be desktop or web")
        if self.mode == "web":
            origin = urlsplit(self.public_origin)
            if (
                origin.scheme not in ("http", "https")
                or not origin.hostname
                or origin.path
                or origin.query
                or origin.fragment
                or origin.username
            ):
                raise ValueError("TG_PUBLIC_ORIGIN must be a complete origin without path or credentials")
            if origin.scheme != "https" and origin.hostname not in ("localhost", "127.0.0.1", "::1"):
                raise ValueError(
                    "Remote Web mode requires HTTPS; use localhost / SSH forwarding for local testing"
                )
            if self.data_dir.resolve().is_relative_to(self.media_root.resolve()):
                raise ValueError("TG_DATA_DIR must be outside TG_MEDIA_ROOT")
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
