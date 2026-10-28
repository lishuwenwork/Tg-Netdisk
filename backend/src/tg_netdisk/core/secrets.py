import keyring

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
