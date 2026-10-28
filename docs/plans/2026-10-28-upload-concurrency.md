# Upload Concurrency Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 在设置页常规设置中提供上传并发数，最小 1、默认 4、最大 10，保存并跨重启恢复。

**Architecture:** 沿用设置 API 和 SQLite JSON 配置，旧配置缺少字段时补默认值。每个文件开始上传时读取设置，当前文件保持原有并发窗口；常规设置保存不重连 Telegram，连接参数变更继续受活动任务保护。诊断显示保存后的并发值。

**Tech Stack:** Vue 3 / TypeScript、FastAPI / Pydantic、Telethon、SQLite、pytest、Playwright Electron。

### Task 1: 配置契约与持久化

- 修改 `backend/src/tg_netdisk/models/schemas.py`：`upload_concurrency` 为严格整数，默认 4，范围 1～10。
- 修改 `backend/src/tg_netdisk/api/app.py`：读取时补全旧配置默认值，部分更新保留其他设置，仅连接参数实际变化时重连及检查活动任务。
- 在 `backend/tests/test_api.py` 覆盖旧配置、1/4/10、非法值、重启、活动上传期间保存和连接参数保护。

### Task 2: 上传与诊断

- 修改 `backend/src/tg_netdisk/integrations/uploader.py`：默认并发 4，硬上限 10。
- 修改 `backend/src/tg_netdisk/integrations/telegram.py`：照片、视频、缩略图和封面统一在每个文件开始时读取并发值。
- 修改 `backend/src/tg_netdisk/core/diagnostics.py`：区分默认并发与上限，报告配置值。
- 在 `backend/tests/test_uploader.py` 和 `backend/tests/test_telegram_adapter.py` 验证真实在途请求上限、取消清理、所有上传入口及文件边界生效。

### Task 3: 设置界面与桌面验证

- 修改 `frontend/src/components/SettingsPage.vue`、`frontend/src/types.ts` 和 `frontend/src/stores/workspace.ts`：常规设置增加 1～10 的数字下拉框并接入保存、恢复。
- 扩展 `scripts/check-upload-settings.mjs`：在隔离数据目录使用真实 API 验证默认值、范围、保存、重载恢复及诊断回显，保留代理检查。
- 执行 `python -m uv run --project backend pytest backend/tests -q`、Ruff、mypy、`npm.cmd test` 和 `npm.cmd run build`，再运行桌面专项检查。

### Task 4: 交付

- 更新版本至 0.1.5，更新 API / 使用说明 / 版本及验证记录。
- 打包到 `release/0.1.5`，使用该目录的可运行程序复查设置并生成 SHA256。
- 不访问真实会话或发送 Telegram 文件；真实线路速度由用户自行对比。
