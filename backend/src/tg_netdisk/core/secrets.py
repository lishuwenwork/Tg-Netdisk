import json
import os
import threading
from pathlib import Path

import keyring
from cryptography.fernet import Fernet, InvalidToken

from tg_netdisk.core.config import AppError


class SecretStore:
    """Windows Credential Manager via keyring; never silently fall back to a plaintext file."""

    def __init__(self, scope: str = "Tg Netdisk"):
        self.scope = scope

    def get(self, name: str) -> str:
        try:
            return keyring.get_password(self.scope, name) or ""
        except Exception as exc:
            raise AppError("SECRET_STORE", "无法读取系统凭据，请检查 Windows 凭据管理器") from exc

    def set(self, name: str, value: str) -> None:
        try:
            if value:
                keyring.set_password(self.scope, name, value)
            elif keyring.get_password(self.scope, name):
                keyring.delete_password(self.scope, name)
        except Exception as exc:
            raise AppError("SECRET_STORE", "无法保存系统凭据") from exc


class EncryptedSecretStore:
    """Web credentials are encrypted; the master key is mounted separately from the data volume."""

    def __init__(self, path: Path, key_file: Path | None):
        if key_file is None:
            raise ValueError("TG_SECRET_KEY_FILE is required in Web mode")
        self.cipher = Fernet(key_file.read_bytes().strip())
        self.path = path
        self.lock = threading.RLock()
        self._read()

    def _read(self) -> dict[str, str]:
        if not self.path.exists():
            return {}
        try:
            return json.loads(self.cipher.decrypt(self.path.read_bytes()))
        except (InvalidToken, ValueError, OSError) as exc:
            raise AppError("SECRET_STORE", "凭据解密失败，请检查加密密钥挂载") from exc

    def get(self, name: str) -> str:
        with self.lock:
            return self._read().get(name, "")

    def set(self, name: str, value: str) -> None:
        with self.lock:
            values = self._read()
            if value:
                values[name] = value
            else:
                values.pop(name, None)
            temporary = self.path.with_suffix(".tmp")
            temporary.write_bytes(self.cipher.encrypt(json.dumps(values).encode()))
            os.chmod(temporary, 0o600)
            os.replace(temporary, self.path)
