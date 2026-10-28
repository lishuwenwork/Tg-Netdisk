import argparse
import asyncio
import json
import os
import socket
import sys
import threading

import uvicorn

from tg_netdisk.api.app import create_app
from tg_netdisk.core.config import Config


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--diagnose-crypto", action="store_true")
    parser.add_argument("--benchmark", action="store_true")
    args = parser.parse_args()
    if args.diagnose_crypto:
        from tg_netdisk.core.diagnostics import crypto_report

        print(json.dumps(crypto_report(args.benchmark)), flush=True)
        return
    config = Config()
    if not os.environ.get("TG_RUNTIME_TOKEN"):
        parser.error("TG_RUNTIME_TOKEN must be supplied by the desktop launcher")
    config.data_dir.mkdir(parents=True, exist_ok=True)
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
    sock = socket.socket()
    sock.bind(("127.0.0.1", args.port))
    sock.listen(128)
    port = sock.getsockname()[1]
    app = create_app(config)
    server = uvicorn.Server(
        uvicorn.Config(app, host="127.0.0.1", port=port, workers=1, access_log=False, log_level="warning")
    )

    async def run():
        def read_commands():
            for line in sys.stdin:
                if line.strip() == "shutdown":
                    server.should_exit = True
                    break

        threading.Thread(target=read_commands, daemon=True).start()

        # Readiness is emitted only after lifespan / migration startup completes.
        async def announce():
            while not server.started:
                await asyncio.sleep(0.05)
            print(json.dumps({"event": "ready", "port": port}), flush=True)

        ready = asyncio.create_task(announce())
        try:
            await server.serve(sockets=[sock])
        finally:
            ready.cancel()
            lock.close()

    asyncio.run(run())


if __name__ == "__main__":
    main()
