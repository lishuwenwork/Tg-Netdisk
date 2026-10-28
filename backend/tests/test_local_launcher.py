import importlib.util
import json
import shutil
from pathlib import Path

import pytest

PROJECT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("local_launcher", PROJECT / "scripts/run-web.py")
assert spec and spec.loader
launcher = importlib.util.module_from_spec(spec)
spec.loader.exec_module(launcher)


@pytest.fixture
def local_project(tmp_path):
    (tmp_path / "scripts").mkdir()
    shutil.copy2(PROJECT / "scripts/setup-web.py", tmp_path / "scripts/setup-web.py")
    media = tmp_path / "中文 视频"
    media.mkdir()
    return tmp_path, media


def test_local_configuration_is_saved_and_secrets_are_reused(local_project):
    root, media = local_project
    first = launcher.prepare_local(root, media, 18088)
    key = Path(first["TG_SECRET_KEY_FILE"]).read_bytes()
    password = Path(first["TG_WEB_PASSWORD_FILE"]).read_bytes()
    second = launcher.prepare_local(root)
    assert second == first
    assert Path(second["TG_SECRET_KEY_FILE"]).read_bytes() == key
    assert Path(second["TG_WEB_PASSWORD_FILE"]).read_bytes() == password
    assert first["TG_PUBLIC_ORIGIN"] == "http://localhost:18088"
    assert first["TG_FRONTEND_DIR"] == str(root / "dist")
    assert set(json.loads((root / ".local-web.json").read_text(encoding="utf-8"))) == {"media_root", "port"}


def test_local_setup_preserves_docker_environment(local_project):
    root, media = local_project
    original = "TG_MEDIA_DIR=/srv/production\nTG_PUBLIC_ORIGIN=https://example.test\n"
    (root / ".env").write_text(original)
    launcher.prepare_local(root, media)
    assert (root / ".env").read_text() == original


def test_missing_key_is_not_silently_regenerated(local_project):
    root, media = local_project
    first = launcher.prepare_local(root, media)
    Path(first["TG_DATA_DIR"], "credentials.enc").write_bytes(b"existing encrypted data")
    key = Path(first["TG_SECRET_KEY_FILE"])
    key.unlink()
    with pytest.raises(ValueError, match="密钥丢失"):
        launcher.prepare_local(root)
    assert not key.exists()
