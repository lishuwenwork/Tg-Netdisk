from __future__ import annotations

import asyncio
import builtins
import copy
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import create_engine, delete, event, select
from sqlalchemy.orm import Session

from tg_netdisk.core.config import AppError
from tg_netdisk.models.database import TABLES, DraftItemRow, Task, TaskEvent, TaskItemRow, TaskMessage


def now() -> str:
    return datetime.now(UTC).isoformat()


class Store:
    """Serialize short SQLite transactions in a thread, keeping I/O off the asyncio loop."""

    def __init__(self, path: Path):
        self.engine = create_engine(f"sqlite:///{path}", connect_args={"check_same_thread": False})

        @event.listens_for(self.engine, "connect")
        def configure(dbapi_connection, _):
            dbapi_connection.execute("PRAGMA journal_mode=WAL")
            dbapi_connection.execute("PRAGMA foreign_keys=ON")
            dbapi_connection.execute("PRAGMA busy_timeout=5000")

        self.lock = asyncio.Lock()

    async def initialize(self) -> None:
        # Alembic records schema versions, including the first launch of a packaged app.
        from alembic import command
        from alembic.config import Config

        cfg = Config()
        import sys

        migration_dir = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[3])) / "migrations"
        cfg.set_main_option("script_location", str(migration_dir))
        cfg.set_main_option("sqlalchemy.url", str(self.engine.url).replace("%", "%%"))
        await asyncio.to_thread(command.upgrade, cfg, "head")

    async def run(self, operation):
        async with self.lock:

            def transaction():
                with Session(self.engine) as session, session.begin():
                    return operation(session)

            return await asyncio.to_thread(transaction)

    async def get(self, kind: str, key: str) -> dict | None:
        def read(session):
            row = session.get(TABLES[kind], key)
            return copy.deepcopy(row.data) if row else None

        return await self.run(read)

    async def list(self, kind: str) -> list[dict]:
        return await self.run(lambda s: [copy.deepcopy(r.data) for r in s.scalars(select(TABLES[kind]))])

    async def save(self, kind: str, data: dict) -> dict:
        payload = copy.deepcopy(data)

        def write(session):
            row = session.get(TABLES[kind], payload["id"])
            if row:
                row.data = payload
            else:
                session.add(TABLES[kind](id=payload["id"], data=payload))
            session.flush()
            if kind == "drafts":
                session.execute(delete(DraftItemRow).where(DraftItemRow.draft_id == payload["id"]))
                for index, item in enumerate(payload.get("items", [])):
                    session.add(DraftItemRow(draft_id=payload["id"], position=index, **item))
            if kind == "tasks" and not row:
                for index, item in enumerate(payload["snapshot"]["items"]):
                    session.add(
                        TaskItemRow(
                            task_id=payload["id"],
                            position=index,
                            media_id=item["media_id"],
                            cover_id=item.get("cover_id"),
                            random_id=str(item["random_id"]),
                        )
                    )
            return copy.deepcopy(payload)

        return await self.run(write)

    async def patch(self, kind: str, key: str, **changes) -> dict:
        def write(session):
            row = session.get(TABLES[kind], key)
            if row is None:
                raise KeyError(key)
            value = {**row.data, **copy.deepcopy(changes), "updated_at": now()}
            row.data = value
            if kind == "tasks" and "state" in changes:
                session.add(TaskEvent(task_id=key, data={"time": now(), **changes}))
            if kind == "tasks" and "messages" in changes:
                session.execute(delete(TaskMessage).where(TaskMessage.task_id == key))
                for i, message in enumerate(changes["messages"]):
                    session.add(TaskMessage(task_id=key, position=i, data=message))
            return copy.deepcopy(value)

        return await self.run(write)

    async def remove(self, kind: str, key: str) -> None:
        await self.run(lambda s: s.execute(delete(TABLES[kind]).where(TABLES[kind].id == key)))

    async def delete_task(self, key: str, confirm_unknown: bool = False) -> bool:
        def remove(session):
            row = session.get(Task, key)
            if row is None:
                return False
            # Validate the live state inside the same transaction as deletion.
            if row.data["state"] not in {"succeeded", "failed", "cancelled", "unknown"}:
                raise AppError("TASK_ACTIVE", "正在执行或排队的任务不能删除，请先取消")
            if row.data["state"] == "unknown" and not confirm_unknown:
                raise AppError("UNKNOWN_CONFIRMATION_REQUIRED", "结果待确认，请确认删除本地核对信息后再操作")
            session.execute(delete(TaskEvent).where(TaskEvent.task_id == key))
            session.execute(delete(TaskMessage).where(TaskMessage.task_id == key))
            session.execute(delete(TaskItemRow).where(TaskItemRow.task_id == key))
            session.delete(row)
            session.flush()
            return True

        return await self.run(remove)

    async def events(self, task_id: str) -> builtins.list[dict]:
        return await self.run(
            lambda s: [
                r.data
                for r in s.scalars(
                    select(TaskEvent).where(TaskEvent.task_id == task_id).order_by(TaskEvent.id)
                )
            ]
        )

    async def close(self) -> None:
        await asyncio.to_thread(self.engine.dispose)
