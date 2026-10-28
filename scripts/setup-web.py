"""Initialize private Web deployment files without installing Python dependencies or overwriting data."""

import argparse
import base64
import json
import os
import secrets
from pathlib import Path

root = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser()
parser.add_argument("--media-root", type=Path, required=True)
parser.add_argument("--origin", default="http://localhost:8080")
args = parser.parse_args()
uid = os.getuid() if hasattr(os, "getuid") else 10001
gid = os.getgid() if hasattr(os, "getgid") else 10001
if uid == 0:
    uid = gid = 10001
media = args.media_root.resolve()
if not media.is_dir():
    parser.error("--media-root must be an existing readable directory")
private = root / "deploy/.secrets"
private.mkdir(parents=True, exist_ok=True, mode=0o700)
data = root / "deploy/data"
data.mkdir(parents=True, exist_ok=True, mode=0o700)
if data.is_relative_to(media):
    parser.error("The media root must not contain the application data directory")
for name, value in (
    ("web_password", secrets.token_urlsafe(24)),
    ("credential_key", base64.urlsafe_b64encode(secrets.token_bytes(32)).decode()),
):
    target = private / name
    if not target.exists():
        with target.open("x", encoding="utf-8") as stream:
            stream.write(value + "\n")
        os.chmod(target, 0o600)
if hasattr(os, "getuid") and os.getuid() == 0:
    for target in (private, data, private / "web_password", private / "credential_key"):
        os.chown(target, uid, gid)
environment = root / ".env"
if not environment.exists():
    with environment.open("x", encoding="utf-8") as stream:
        stream.write(
            f"TG_MEDIA_DIR={json.dumps(str(media), ensure_ascii=False)}\nTG_PUBLIC_ORIGIN={args.origin}\nTG_HTTP_PORT=8080\n"
            f"PUID={uid}\nPGID={gid}\n"
        )
    os.chmod(environment, 0o600)
print("Web configuration prepared. Existing secrets and data were preserved.")
print("Access password: read deploy/.secrets/web_password on the server.")
print("Start: docker compose up -d --build")
