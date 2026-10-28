"""Headless, single-worker Web entry point. Uvicorn handles SIGTERM and runs lifespan cleanup."""

import os
from pathlib import Path

import uvicorn

from tg_netdisk.api.app import create_app
from tg_netdisk.core.config import Config


def main():
    os.environ["TG_MODE"] = "web"
    config = Config()
    config.data_dir.mkdir(parents=True, exist_ok=True)
    if config.frontend_dir is None:
        config.frontend_dir = Path(__file__).resolve().parents[3] / "dist"
    lock = (config.data_dir / "instance.lock").open("a+b")
    lock.write(b"0")
    lock.flush()
    lock.seek(0)
    if os.name == "nt":
        import msvcrt

        msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
    else:
        import fcntl

        fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)  # type: ignore[attr-defined]
    try:
        uvicorn.run(
            create_app(config),
            host=os.environ.get("TG_BIND", "0.0.0.0"),
            port=int(os.environ.get("TG_PORT", "8080")),
            workers=1,
            proxy_headers=False,
            access_log=False,
            log_level="warning",
        )
    finally:
        lock.close()


if __name__ == "__main__":
    main()
