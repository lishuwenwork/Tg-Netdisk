"""Synthetic crypto and ACK-pipeline measurements. No Telegram connection is made."""

import asyncio
import json
import os
import time
from pathlib import Path

from telethon import functions
from telethon.crypto import aes

from tg_netdisk.core.diagnostics import crypto_report
from tg_netdisk.integrations.uploader import upload_file


async def main():
    directory = Path(__file__).resolve().parents[1] / ".runtime/upload-investigation"
    directory.mkdir(parents=True, exist_ok=True)
    native = crypto_report(True)
    previous_cryptg, previous_ssl = aes.cryptg, aes.libssl.encrypt_ige
    data, key, iv = os.urandom(128 * 1024), os.urandom(32), os.urandom(32)
    try:
        aes.cryptg = None
        aes.libssl.encrypt_ige = None
        started = time.perf_counter()
        aes.AES.encrypt_ige(data, key, iv)
        python_rate = 0.125 / (time.perf_counter() - started)
    finally:
        aes.cryptg, aes.libssl.encrypt_ige = previous_cryptg, previous_ssl
    source = directory / "synthetic.bin"
    source.write_bytes(os.urandom(4 * 1024 * 1024))

    class SimulatedACK:
        def __init__(self):
            self.active = 0
            self.maximum = 0

        async def __call__(self, request):
            assert isinstance(request, functions.upload.SaveFilePartRequest)
            self.active += 1
            self.maximum = max(self.maximum, self.active)
            try:
                await asyncio.sleep(0.08)
                return True
            finally:
                self.active -= 1

    sequential = SimulatedACK()
    started = time.perf_counter()
    with source.open("rb") as stream:
        index = 0
        while chunk := stream.read(128 * 1024):
            await sequential(functions.upload.SaveFilePartRequest(1, index, chunk))
            index += 1
    original_seconds = time.perf_counter() - started
    pipeline = SimulatedACK()
    started = time.perf_counter()
    await upload_file(pipeline, str(source))
    pipeline_seconds = time.perf_counter() - started
    result = {
        "network_test": "simulated 80 ms ACK; not actual Telegram throughput",
        "python_aes_mib_s": round(python_rate, 3),
        "native": native,
        "sequential_128k_seconds": round(original_seconds, 3),
        "pipeline_4x512k_seconds": round(pipeline_seconds, 3),
        "pipeline_max_in_flight": pipeline.maximum,
        "simulated_speedup": round(original_seconds / pipeline_seconds, 2),
    }
    (directory / "benchmark.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(result))


if __name__ == "__main__":
    asyncio.run(main())
