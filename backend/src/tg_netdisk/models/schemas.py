from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Metadata(StrictModel):
    duration: float = Field(0, ge=0)
    width: int = Field(0, ge=0)
    height: int = Field(0, ge=0)
    container: str = ""
    video_codec: str = ""
    audio_codec: str = ""
    readable: bool = False
    video_decodable: bool = False
    audio_decodable: bool = False
    error: str = ""
    thumbnails: list[str] = Field(default_factory=list)


class DraftItem(StrictModel):
    media_id: str
    cover_id: str | None = None


class Draft(StrictModel):
    id: str = "current"
    title: str = Field(default="", max_length=10000)
    description: str = Field(default="", max_length=10000)
    tags: list[str] = Field(default_factory=list, max_length=100)
    bold_title: bool = True
    channel_id: str = ""
    items: list[DraftItem] = Field(default_factory=list, max_length=100)


class RegisterFiles(StrictModel):
    paths: list[str] = Field(max_length=100)


class DownloadRequest(StrictModel):
    url: str = Field(max_length=10000)
    headers: dict[str, str] = Field(default_factory=dict)


class FrameRequest(StrictModel):
    source_id: str
    timestamp: float = Field(ge=0)
    image: str = Field(max_length=50_000_000)
    purpose: Literal["album", "cover", "thumbnail"] = "album"


class ConnectionSettings(StrictModel):
    api_id: str = ""
    api_hash: str | None = None
    telegram_proxy: str | None = None
    download_proxy: str | None = None
    default_channel: str = ""
    theme: Literal["dark", "light"] = "dark"
    close_behavior: Literal["ask", "hide"] = "ask"
    download_dir: str = ""
    upload_concurrency: int = Field(default=4, ge=1, le=10, strict=True)


class PasswordRequest(StrictModel):
    password: str = Field(max_length=1000)


class ResolveChannel(StrictModel):
    channel_id: str


class ConfirmResult(StrictModel):
    outcome: Literal["succeeded", "failed"]
    confirmed: bool
    message_ids: list[int] = Field(default_factory=list)
