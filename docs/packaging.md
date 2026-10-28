# Windows 打包和迁移

## 构建

```powershell
npm ci
python -m uv sync --project backend --group dev --locked
npm run pack
```

`scripts/package-backend.ps1` 将 Python 运行时、tg_netdisk、Alembic migrations、Telethon、SQLite、Pillow、HTTPX、keyring Windows 后端一起放入 PyInstaller onedir 目录。electron-builder 把该目录放在 `resources/backend`，生产 Electron 使用绝对路径启动 exe，不依赖 PATH。

NSIS 允许选择安装目录，升级保留 `%APPDATA%\Tg Netdisk`，卸载默认保留数据。完全删除数据需用户主动退出应用并备份后删除该目录，同时按需清理 Windows Credential Manager 中对应的 Tg Netdisk 项。普通缓存清理不删除会话或原视频。

`release/win-unpacked/Tg Netdisk.exe` 可用于本机目录启动检查；`release/Tg Netdisk Setup 0.1.0.exe` 为安装程序。没有设置签名证书，测试包显示未知发布者。

## 数据库迁移

首次启动自动执行 Alembic `upgrade head`，记录在 `alembic_version`。当前 0001 包含 settings、channels、media_assets、frame_assets、drafts、draft_items、publish_tasks、task_items、task_messages 和 task_events。

新增字段应创建新 revision，不修改已经分发的旧迁移。升级前退出应用并备份整个用户数据目录；数据库与 Telethon 会话都不能在运行中直接搬移。发生迁移错误时保留原始文件并从日志定位，禁止删除数据库“修复”。降级仅在测试备份上执行；发布迁移应补充升级 / 回滚验证。

## 干净环境验收

在未安装 Node / Python / 视频工具的 Windows 虚拟机中安装，逐项记录：首次启动、动态端口、扫码和 2FA、重启会话、私人频道、中文及空格路径、MP4 H.264/AAC、WebM/MOV/MKV、封面、相册顺序、标签点击、发布超时与重启、后台上传、缓存引用保护、125%/150% 缩放、升级后数据保留。这里是必须执行的手工清单，不代表已有通过记录。

硬件与驱动会影响 HEVC / AV1 / 高位深解码，失败时应显示原因并阻止该视频提交，不安装额外组件。
