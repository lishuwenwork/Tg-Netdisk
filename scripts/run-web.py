"""Start the local Web workspace with saved configuration and no manual environment setup."""

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path


def prepare_local(
    root: Path, media_root: Path | None = None, port: int | None = None
) -> dict[str, str]:
    config_file = root / ".local-web.json"
    saved = (
        json.loads(config_file.read_text(encoding="utf-8"))
        if config_file.exists()
        else {}
    )
    selected = media_root or (
        Path(saved["media_root"]) if saved.get("media_root") else None
    )
    if selected is None:
        if not sys.stdin.isatty():
            raise ValueError(
                '首次启动请指定媒体目录：npm run web -- --media-root "D:\\Videos"'
            )
        value = input("媒体目录（已有的视频文件夹）：").strip().strip('"')
        if not value:
            raise ValueError("未选择媒体目录")
        selected = Path(value)
    selected = selected.expanduser().resolve()
    if not selected.is_dir():
        raise ValueError(f"媒体目录不存在：{selected}；请用 --media-root 指定已有目录")
    data = root / "deploy/data"
    if data.resolve().is_relative_to(selected):
        raise ValueError("媒体目录不能包含应用数据目录，请选择单独的视频文件夹")
    selected_port = port if port is not None else int(saved.get("port", 8080))
    if not 1 <= selected_port <= 65535:
        raise ValueError("端口必须为 1–65535")
    key = root / "deploy/.secrets/credential_key"
    if (data / "credentials.enc").exists() and not key.exists():
        raise ValueError("凭据密钥丢失，请从备份恢复 deploy/.secrets/credential_key")
    origin = f"http://localhost:{selected_port}"
    result = subprocess.run(
        [
            sys.executable,
            "-X",
            "utf8",
            str(root / "scripts/setup-web.py"),
            "--media-root",
            str(selected),
            "--origin",
            origin,
        ],
        cwd=root,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if result.returncode:
        raise ValueError("本地配置初始化失败：" + result.stderr.strip())
    config_file.write_text(
        json.dumps(
            {"media_root": str(selected), "port": selected_port},
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return {
        "TG_MODE": "web",
        "TG_MEDIA_ROOT": str(selected),
        "TG_DATA_DIR": str(data),
        "TG_FRONTEND_DIR": str(root / "dist"),
        "TG_MIGRATIONS_DIR": str(root / "backend/migrations"),
        "TG_WEB_PASSWORD_FILE": str(root / "deploy/.secrets/web_password"),
        "TG_SECRET_KEY_FILE": str(key),
        "TG_PUBLIC_ORIGIN": origin,
        "TG_BIND": "127.0.0.1",
        "TG_PORT": str(selected_port),
    }


def main():
    parser = argparse.ArgumentParser(
        description="本地 Web 工作台，一次选择目录后自动复用配置"
    )
    parser.add_argument("--media-root", type=Path, help="选择或更换服务器媒体根目录")
    parser.add_argument("--port", type=int, help="端口，默认 8080；设置后会保存")
    parser.add_argument("--build", action="store_true", help="重新构建前端页面")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    try:
        environment = prepare_local(root, args.media_root, args.port)
    except (ValueError, OSError) as error:
        parser.error(str(error))
    if args.build or not (root / "dist/index.html").is_file():
        print("正在构建页面…", flush=True)
        npm = "npm.cmd" if os.name == "nt" else "npm"
        subprocess.run([npm, "run", "build"], cwd=root, check=True)
    os.environ.update(environment)
    print(f"访问地址：{environment['TG_PUBLIC_ORIGIN']}", flush=True)
    print(f"媒体目录：{environment['TG_MEDIA_ROOT']}", flush=True)
    print(f"访问密码文件：{environment['TG_WEB_PASSWORD_FILE']}", flush=True)
    print("按 Ctrl+C 停止服务。", flush=True)
    from tg_netdisk.web import main as serve

    serve()


if __name__ == "__main__":
    main()
