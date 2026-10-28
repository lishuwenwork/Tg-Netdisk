import re

from tg_netdisk.core.config import AppError


def utf16_length(text: str) -> int:
    return len(text.encode("utf-16-le")) // 2


def normalize_tags(tags: list[str]) -> list[str]:
    result: list[str] = []
    for text in tags:
        tag = text.strip().removeprefix("#")
        if not re.fullmatch(r"\w+", tag, re.UNICODE) or tag.isdecimal():
            raise AppError("INVALID_TAG", "标签仅可使用中文、字母、数字和下划线，不能全为数字")
        value = "#" + tag
        if value.casefold() not in [t.casefold() for t in result]:
            result.append(value)
    return result


def compose(
    title: str, description: str, tags: list[str], bold: bool = True, limit: int = 1024
) -> tuple[str, list[dict]]:
    title, description = title.strip(), description.strip()
    normalized = normalize_tags(tags)
    parts = [p for p in (title, description, " ".join(normalized)) if p]
    text = "\n\n".join(parts)
    if utf16_length(text) > limit:
        raise AppError("CAPTION_TOO_LONG", f"文案超过 {limit} 个 UTF-16 单位，请缩短后重试")
    entities = []
    if title and bold:
        entities.append({"type": "bold", "offset": 0, "length": utf16_length(title)})
    # Detect hashtags throughout plain user text too; offsets are MTProto UTF-16 units.
    for match in re.finditer(r"(?<!\w)#(\w+)", text, re.UNICODE):
        if not match.group(1).isdecimal():
            entities.append(
                {
                    "type": "hashtag",
                    "offset": utf16_length(text[: match.start()]),
                    "length": utf16_length(match.group()),
                }
            )
    return text, entities
