from sqlalchemy import JSON, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Document:
    id: Mapped[str] = mapped_column(String, primary_key=True)
    data: Mapped[dict] = mapped_column(JSON)


class Settings(Document, Base):
    __tablename__ = "settings"


class Channel(Document, Base):
    __tablename__ = "channels"


class Media(Document, Base):
    __tablename__ = "media_assets"


class Frame(Document, Base):
    __tablename__ = "frame_assets"


class DraftRow(Document, Base):
    __tablename__ = "drafts"


class Task(Document, Base):
    __tablename__ = "publish_tasks"


class DraftItemRow(Base):
    __tablename__ = "draft_items"
    id: Mapped[int] = mapped_column(primary_key=True)
    draft_id: Mapped[str] = mapped_column(ForeignKey("drafts.id", ondelete="CASCADE"))
    position: Mapped[int] = mapped_column(Integer)
    media_id: Mapped[str] = mapped_column(String)
    cover_id: Mapped[str | None] = mapped_column(String, nullable=True)
    __table_args__ = (UniqueConstraint("draft_id", "position"),)


class TaskItemRow(Base):
    __tablename__ = "task_items"
    id: Mapped[int] = mapped_column(primary_key=True)
    task_id: Mapped[str] = mapped_column(ForeignKey("publish_tasks.id", ondelete="CASCADE"))
    position: Mapped[int] = mapped_column(Integer)
    media_id: Mapped[str] = mapped_column(String)
    cover_id: Mapped[str | None] = mapped_column(String, nullable=True)
    random_id: Mapped[str] = mapped_column(String)
    __table_args__ = (UniqueConstraint("task_id", "position"),)


class TaskMessage(Base):
    __tablename__ = "task_messages"
    id: Mapped[int] = mapped_column(primary_key=True)
    task_id: Mapped[str] = mapped_column(ForeignKey("publish_tasks.id"))
    position: Mapped[int] = mapped_column(Integer)
    data: Mapped[dict] = mapped_column(JSON)


class TaskEvent(Base):
    __tablename__ = "task_events"
    id: Mapped[int] = mapped_column(primary_key=True)
    task_id: Mapped[str] = mapped_column(String)
    data: Mapped[dict] = mapped_column(JSON)


TABLES: dict[
    str, type[Settings] | type[Channel] | type[Media] | type[Frame] | type[DraftRow] | type[Task]
] = {
    "settings": Settings,
    "channels": Channel,
    "media": Media,
    "frames": Frame,
    "drafts": DraftRow,
    "tasks": Task,
}
