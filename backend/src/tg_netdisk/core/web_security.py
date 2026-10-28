import asyncio
import hashlib
import hmac
import secrets
import time
from collections import OrderedDict

from tg_netdisk.core.config import Config

COOKIE_NAME = "tg_web_session"
SESSION_LIFETIME = 12 * 60 * 60


class WebAccess:
    """Single-owner Web login; sessions are hashed in memory and expire on process restart."""

    def __init__(self, config: Config):
        if not config.web_password_file:
            raise ValueError("TG_WEB_PASSWORD_FILE is required in Web mode")
        password = config.web_password_file.read_text(encoding="utf-8").strip()
        if len(password) < 16:
            raise ValueError("The Web access password must contain at least 16 characters")
        self.salt = secrets.token_bytes(16)
        self.password_hash = self._derive(password)
        self.sessions: OrderedDict[str, float] = OrderedDict()
        self.failures: OrderedDict[str, list[float]] = OrderedDict()
        self.secure_cookie = config.public_origin.startswith("https:")
        self.login_lock = asyncio.Lock()

    def _derive(self, password: str) -> bytes:
        return hashlib.scrypt(password.encode(), salt=self.salt, n=16384, r=8, p=1, dklen=32)

    @staticmethod
    def _session_key(token: str) -> str:
        return hashlib.sha256(token.encode()).hexdigest()

    def valid(self, token: str) -> bool:
        current = time.monotonic()
        for key, expiry in list(self.sessions.items()):
            if expiry <= current:
                del self.sessions[key]
        return self.sessions.get(self._session_key(token), 0) > current

    async def login(self, password: str, client: str) -> tuple[str | None, bool]:
        async with self.login_lock:
            current = time.monotonic()
            failures = [t for t in self.failures.get(client, []) if current - t < 60]
            # Bound both per-address attempts and overall work; forwarded IP headers aren't trusted.
            total = sum(sum(current - t < 60 for t in values) for values in self.failures.values())
            if len(failures) >= 5 or total >= 30:
                return None, True
            candidate = await asyncio.to_thread(self._derive, password)
            if not hmac.compare_digest(candidate, self.password_hash):
                self.failures[client] = [*failures, current]
                while len(self.failures) > 1024:
                    self.failures.popitem(last=False)
                return None, False
            self.failures.pop(client, None)
            token = secrets.token_urlsafe(32)
            self.sessions[self._session_key(token)] = current + SESSION_LIFETIME
            while len(self.sessions) > 32:
                self.sessions.popitem(last=False)
            return token, False

    def logout(self, token: str) -> None:
        self.sessions.pop(self._session_key(token), None)
