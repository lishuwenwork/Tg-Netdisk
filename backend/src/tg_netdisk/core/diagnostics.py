import os
import time

from telethon.crypto import aes

from tg_netdisk.integrations.uploader import DEFAULT_CONCURRENCY, PART_SIZE


def crypto_backend() -> str:
    if aes.cryptg:
        return "cryptg"
    return "openssl" if aes.libssl.encrypt_ige else "python"


def crypto_report(benchmark: bool = False, concurrency: int = DEFAULT_CONCURRENCY) -> dict:
    backend = crypto_backend()
    result = {
        "crypto_backend": backend,
        "native_crypto": backend != "python",
        "part_size_kib": PART_SIZE // 1024,
        "max_in_flight": concurrency,
    }
    if benchmark:
        data, key, iv = os.urandom(128 * 1024), os.urandom(32), os.urandom(32)
        rounds = 128 if backend != "python" else 1
        started = time.perf_counter()
        for _ in range(rounds):
            aes.AES.encrypt_ige(data, key, iv)
        elapsed = max(time.perf_counter() - started, 0.000001)
        result["aes_mib_s"] = round(len(data) * rounds / elapsed / 1024**2, 2)
    return result
