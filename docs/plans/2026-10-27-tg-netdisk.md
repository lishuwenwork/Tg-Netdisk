# Tg Netdisk Implementation Plan

**Goal:** 按 v1.5 需求构建 Windows Telegram 媒体发布客户端。

**Architecture:** Electron 管理单实例、文件授权与 Python 子进程。Vue 负责编辑和 Mediabunny 解码，FastAPI Service / Repository / Integration 负责持久化和发布。入队保存不可变快照；发布阶段不确定结果禁止自动重发。

**Tech Stack:** Electron、Vue 3、TypeScript、Pinia、Tailwind CSS、Mediabunny、FastAPI、SQLAlchemy、Alembic、Telethon、HTTPX、Pillow。

## 方案与取舍

采用需求指定的本机三层结构，原视频按路径引用，受控 Range 流读取。浏览器纯前端方案不能管理 Telegram 会话与独立后台任务；Python 原生 UI 不符合 Electron / Vue 要求。媒体处理不引入转码工具。

## 执行步骤

1. 保存原始需求至根目录 `Tg-Netdisk.md`，建立依赖清单和锁文件。
2. `backend/src/tg_netdisk/models` 定义有序媒体、草稿、任务快照；`repositories` 提供 SQLite 事务和迁移。用 pytest 验证重启恢复、引用保护、顺序不可变。
3. `integrations/telegram.py` 实现二维码、2FA、频道权限、上传和底层发送；每项 random_id 入队固定；仅最终发送阶段进入 publishing。
4. `services` 实现媒体签名校验、流式下载、图片派生、单任务队列、有限重试、取消和 unknown 核对。用故障适配器测试发送响应丢失。
5. `api` 实现运行时令牌、精确来源、WebSocket 补偿快照及受控文件 ID / Range。
6. `desktop` 实现动态端口、有限 IPC、受控文件选择、数据目录、隐藏 / 退出、后端崩溃反馈。
7. `frontend/src/media` 和 Worker 完成能力检测、分段解析、缩略图、原帧导出和按真实时间戳逐帧；独立组件组成工作台、队列、历史、账号和设置。
8. 完成草稿恢复、排序、封面、标签、预览及提交前验证；测试 UTF-16 实体、caption 和快照。
9. `npm run typecheck`、`npm test`、`uv run pytest`、`uv run ruff check` 和生产构建。启动应用做本地素材与 UI 检查。
10. PyInstaller 文件夹模式和 NSIS 打包，记录安装产物及真实 Telegram / 干净 Windows 的待联调项，不虚报验收。

## 验证边界

本地自动化不向 Telegram 发消息。真实扫码、私人频道、相册拼图、可点击标签、video_cover、干净 Windows 和硬件编码组合均需实际环境验证，结果记录在 `docs/verification.md`。
