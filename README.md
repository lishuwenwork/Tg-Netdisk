# Tg Netdisk

Windows 本地 Telegram 媒体发布客户端。需求原件已保存在根目录 [Tg-Netdisk.md](Tg-Netdisk.md)，版本 v1.5。实现使用 Electron + Vue 3 + TypeScript + Tailwind CSS + Mediabunny，以及 Python 3.12 + FastAPI + Telethon + SQLite。

## 启动

开发环境需要 Windows、Node.js 22.17 或更新版本、Python 3.12。

```powershell
cd D:\Project\Tg-Netdisk
python -m pip install uv
npm ci
python -m uv sync --project backend --group dev --locked
npm run dev
```

`npm run dev` 同时启动 Vite 和 Electron；Electron 启动 Python 并等待健康检查。首次打开不包含示例账号、频道或伪造的发布记录。生产资源已构建时可运行 `npm start`。不要直接双击 `dist/index.html`。

## 首次使用

1. 在“账号与连接”填写自己的 API ID / API Hash，保存。应用凭据由 [Telegram 应用管理](https://my.telegram.org) 创建；它们与扫码授权个人账号是两件事。
2. 根据网络环境配置 Telegram 代理与下载代理，二者独立；保存后可测试连接。支持 Telegram 的 SOCKS5 / SOCKS4 / HTTP 代理，下载可使用 HTTP / HTTPS / SOCKS5。
3. 点击“扫码登录”，使用 Telegram 手机客户端扫码。启用两步验证时填写密码；密码仅用于此次请求。二维码过期后刷新，旧等待任务会取消。
4. 在“新建发布”选择频道，或填写 `-100…` 数字 ID 并校验。先刷新频道列表可以加载私人频道实体缓存。必须已经加入并拥有发帖权限。
5. 添加本地视频 / 图片或拖入文件；视频直链先下载到本地。HTML 页面、HLS / DASH、网站解析和 DRM 不在范围内。
6. 预览视频，定位时间，逐帧微调，点击“截取图片”。确认图来自 Mediabunny 解码后的原始画面；可分别设为封面、加入相册或导出。
7. 拖拽相册素材排序，也可使用前移 / 后移按钮。单项必须为视频；相册须有视频且总共 2–10 项。封面不占相册项。
8. 填写标题、简介、标签，预览最终顺序后加入队列。任务保存独立快照，继续编辑草稿不会修改已入队任务。

常用键：播放器聚焦后空格播放 / 暂停，左右键按真实帧时间戳逐帧。时间输入单位为秒。标签输入 `4k` 或 `#4k` 后回车。文案按 Telegram UTF-16 单位检查长度，默认保守限制 1024，登录后尝试读取当前账号的服务端上限。

新建发布页顶部的“重置”会清空当前草稿并立即保存，恢复默认频道、标题加粗和本地来源；未完成的草稿下载和媒体分析会停止。原始文件、已入队任务、历史和账号设置保留。

「设置 → 常规 → 上传并发数」可配置为 1～10，默认 4；点击“保存设置”后永久保存，从下一个文件上传开始生效，正在上传的文件保持原并发数。这里调整的是同一连接内并发的分块请求数量，每块仍为 512 KiB。

## 状态与恢复

- 同时执行一个发布任务，队列和历史保存在 SQLite。
- 上传完全部字节后仍需等待发布结果，上传 100% 不代表发布成功。
- 队列显示上传剩余时间，按近期实际速度估算；没有可靠进度时显示“计算中”，排队 / 重试 / 发布时显示对应状态，不把网络等待伪装成固定倒计时。
- 发布之前取消会停止任务；发布请求发出后取消不撤回消息，而是保存“结果待确认”。
- 发布响应丢失或应用在发布阶段退出，任务进入 `unknown`，禁止直接重试。去频道核对，按素材顺序填写消息 ID，或明确确认未发布后再重试。
- 时间、文案、文件名相同不足以证明某个任务已发布。自动核对缺少 random_id → message_id 证据时保留 unknown，不猜测成功。
- 重启保留队列；中断于准备 / 上传阶段的任务标为失败，可由用户重试。无法续传之前的上传分片。
- 历史列表与详情可删除本地记录，保留原文件和远端消息；活动任务需先结束或取消。结果待确认的记录会提示删除核对信息的影响，删除不会撤回 Telegram 消息。
- 关闭窗口可选择后台运行；退出会停止 Python、Worker、播放器和解码器。处于发布阶段的任务保留核对记录。

## 媒体能力

视频按原路径引用，通过受控 ID 和 HTTP Range 分段读取，不把大视频整体读入前端或通过文件上传接口复制。元数据、能力检测、缩略图、选帧由 Mediabunny + WebCodecs 完成；Python 不解码或转码视频。媒体库和 Worker 包含在前端构建中，无需另装视频程序。

原生 `<video>` 可播放时优先使用；其他可读取、可解码的容器通过 Canvas / Web Audio 播放。音轨无法解码时明确提示，允许无声预览，上传仍保留原音轨。无法解码的视频不能提交。

MP4 / H.264 + AAC 是核心基线；MOV、WebM、MKV、VFR、旋转、长视频、HEVC / AV1 需要按实际容器、轨道编码和运行环境记录测试。最新本地记录见 [验证记录](docs/verification.md)。本地能播放不保证所有 Telegram 客户端都能在线播放。

封面适配同时处理 `thumb` 与独立 `video_cover`，保留源图并生成派生 JPEG，不覆盖源图。单视频和混合相册的实际封面显示、相册布局、标签点击效果都必须通过真实 Telegram 客户端验证。

## 目录

```text
desktop/              Electron 主进程、受限 preload、图标
frontend/src/
  components/         工作台、播放器、相册、账号、任务和设置
  stores/             Pinia 草稿与服务端快照
  lib/                类型化 API、事件重连、caption 与显示格式
  media/              Mediabunny 输入、能力检测、精确帧、自定义播放
  workers/            媒体分析和缩略图 Worker
backend/src/tg_netdisk/
  api/                Controller：HTTP / WebSocket 与输入校验
  services/           Service：媒体、文案、事件、任务状态机
  repositories/       Repository：SQLite 事务、持久化和迁移
  integrations/       Telethon 和 Pillow 适配
  models/             Pydantic 输入模型、SQLAlchemy 数据模型
  core/               路径、凭据、错误和日志
backend/migrations/   Alembic 版本
backend/tests/        不连接 Telegram 的自动化测试
scripts/              开发、图标、桌面检查和打包
docs/                 架构、接口、验证和打包说明
```

“从点击上传到发布完成”的分层说明见 [开发说明](docs/development.md)，接口见 [API](docs/api.md)。

## 数据与凭据

正常运行的数据目录为 `%APPDATA%\Tg Netdisk`；Electron 提供固定目录给后端，安装升级不会替换业务数据。可以用 `TG_DATA_DIR` 指定隔离目录，自动化检查使用项目下 `.runtime`。

`app.db` 保存业务数据；`telegram.session` 保存 Telethon 登录和实体缓存；`media/frames` 保存截图；`cache/downloads` 和 `cache/thumbnails` 保存缓存；`logs` 保存轮转日志。

API Hash 和代理连接串通过 Windows Credential Manager 保存，普通配置接口只返回“是否已保存”；代理由账号编辑器专用接口回显。留空保留旧凭据，移除代理需勾选移除。二维码不入库，2FA 密码不持久化。签名 URL / 请求头仅存在当前下载任务内存中，不写普通日志；未完成下载重启后需重新输入链接。会话、数据库和 `.env` 已加入忽略规则。

从 0.1.4 起，代理输入按用户要求明文显示并支持回显，由账号编辑器专用的认证接口读取；普通快照仍只返回代理是否存在，API Hash 不回显。账号页“上传诊断”可查看原生加速与连接延迟。上传性能问题及本机基准见 [排查报告](docs/upload-performance.md)。

缓存清理只处理应用登记的生成 / 下载文件，不删除本地原视频；仍被草稿、封面或任务引用的文件受保护。历史记录保守保留引用。若手工移动或修改原文件，需重新添加。

## 检查

```powershell
npm run typecheck
npm test
npm run build
python -m uv run --project backend pytest backend/tests -q
python -m uv run --project backend ruff check backend
python -m uv run --project backend mypy --config-file backend/pyproject.toml backend/src
npm audit
npm run test:desktop
npm run test:media
npm run test:exit
npm run test:modals
npm run test:reset
npm run test:tasks
npm run test:upload-settings
```

桌面检查在独立数据目录生成短视频样本，验证本地分析、选帧、封面、相册和持久化，不登录 Telegram、不发布消息。截图输出至 `.runtime`。媒体矩阵检查使用桌面检查生成的基线样本，补测 MOV / MKV / WebM / 旋转和可变帧率。真实账号联调需自行提供 API 凭据和有权限的频道，不属于普通测试。

## Windows 安装包

```powershell
npm run pack
```

构建流程：Vue 静态构建 → PyInstaller 文件夹模式 → electron-builder NSIS。产物在 `release`，包含 Electron、前端 Worker、cryptg 和 Python 后端；安装后无需 Node.js / Python。打包会检查原生加密组件实际可用。`npm run pack:dir` 可生成便携式目录用于排查。本次 0.1.5 安装包保存在 `release/0.1.5`。

当前安装包未配置代码签名，Windows 可能显示发布者未知。关于安装、数据备份、数据库迁移和干净 Windows 验收见 [打包说明](docs/packaging.md)。真实 Telegram、不同硬件编码能力和干净系统验收结果以验证记录为准。
