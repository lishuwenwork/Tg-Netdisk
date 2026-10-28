# Docker / Linux Web 模式

功能分支：`feat_支持web端`；`master` 保存原始 Windows 0.1.5 桌面版本。两种模式共用 Vue 工作台、Mediabunny、Python 队列和 SQLite。Web 容器不运行 Electron、浏览器或视频转码工具。

## 功能边界

Web 仅使用服务器媒体：在只读根目录中浏览、搜索、分页和多选视频 / 图片。不提供电脑文件上传、拖入或直链添加。封面从服务器图片选择，或使用视频截帧。视频分析、播放和截图在访问者浏览器完成，素材准备并入队后由服务器独立上传；关闭浏览器不取消已入队任务。

工作台访问密码与 Telegram 扫码登录相互独立。退出工作台不注销 Telegram，不停止任务；账号页退出登录会注销 Telegram 会话。当前仍是单账号、单个当前草稿，多浏览器共享同一工作区，不提供多人协作隔离。

## 初始化与启动

在当前 Windows / Linux 开发机直接运行 Web 服务，可使用本地入口，无需手动设置环境变量：

```powershell
cd D:\Project\Tg-Netdisk
npm run web
```

首次启动会询问已有媒体目录，自动生成访问密码和密钥；目录、端口保存到忽略提交的 `.local-web.json`，之后运行同一命令即可。已有的 Docker `.env` 不会被覆盖。前端未构建时自动构建；代码更新后可运行 `npm run web -- --build`。

也可以直接指定目录或端口：

```powershell
npm run web -- --media-root "D:\Videos"
npm run web -- --port 8081
```

默认访问 `http://localhost:8080`。密码保存在 `deploy/.secrets/web_password`；服务终端显示文件位置，按 Ctrl+C 停止。首次在新机器使用仍需安装 Node.js、Python 3.12 和 uv，并执行 `npm ci`、`python -m uv sync --project backend --group dev --locked`。

下面是 Linux Docker 部署步骤：

Linux 主机需要 Docker Engine + Compose 插件；初始化脚本只依赖 Python 3 标准库。

```bash
git clone --branch 'feat_支持web端' https://github.com/lishuwenwork/Tg-Netdisk.git
cd Tg-Netdisk
python3 scripts/setup-web.py --media-root /srv/videos
docker compose up -d --build
docker compose ps
```

将 `/srv/videos` 换成已有可读的服务器目录，容器中对应 `/media`，只读挂载。选择器仅接受相对路径，拒绝路径穿越和越出根目录的符号链接。数据目录不能位于媒体目录内。

初始化脚本创建 `.env`、`deploy/.secrets/web_password`、`deploy/.secrets/credential_key` 和 `deploy/data`，全部忽略提交；重复运行不覆盖原有内容。普通用户运行时 UID / GID 与该用户一致，root 运行时使用 10001；请保证该身份可读取媒体目录。

访问密码在服务器上读取，不要提交到仓库：

```bash
cat deploy/.secrets/web_password
```

默认只监听服务器 `127.0.0.1:8080`。可在自己的电脑通过 SSH 转发访问：

```bash
ssh -L 8080:127.0.0.1:8080 user@your-server
```

保持连接，电脑浏览器打开 `http://localhost:8080`。这里的 localhost 指浏览器所在电脑，经 SSH 到服务器，无需开放公网 8080。

## 域名 HTTPS

远程 WebCodecs 需要 HTTPS 安全上下文，普通 HTTP 服务器 IP 不作为支持的访问方式。可沿用已有反向代理，将静态页面、API、WebSocket 和 Range 请求转发到应用。在 `.env` 设置 `TG_PUBLIC_ORIGIN=https://你的域名`，必须与浏览器地址的协议、域名、端口一致，不含路径。

没有现成代理时可使用附带的 Caddy 配置。DNS 指向服务器并开放 80 / 443，在 `.env` 添加 `TG_DOMAIN=media.example.com`，然后：

```bash
docker compose -f compose.yaml -f compose.https.yaml up -d --build
```

自定义代理应保留 Host，支持 WebSocket Upgrade，并给视频 Range 请求足够的读取超时。前端使用同源 API，无需在构建时写入服务器地址或凭据。

## 数据、凭据和备份

| 目录 / 文件 | 内容 |
| --- | --- |
| `deploy/data/app.db` | 草稿、任务、历史、设置 |
| `deploy/data/telegram.session` | Telegram 会话和实体缓存 |
| `deploy/data/credentials.enc` | 加密的 API Hash 与代理 |
| `deploy/data/media/frames` | 截图和封面源图 |
| `deploy/data/cache` | 缩略图和派生图 |
| `deploy/data/logs` | 脱敏应用日志 |
| `deploy/.secrets/credential_key` | 独立于数据目录的主密钥 |

停止容器后同时备份 `deploy/data` 和 `deploy/.secrets`，恢复需要两者。不要用重新生成主密钥的方式处理解密错误。容器重建保留绑定目录中的数据；同一数据目录只运行一个实例。

容器正常停止会关闭队列、Telethon 和数据库；发布阶段中断后保留“结果待确认”，禁止自动重发。工作台会话存于内存，服务重启后需再次输入访问密码，Telegram 会话保留。缓存清理不删除服务器原视频 / 图片。

Telegram 代理按容器网络解释，`127.0.0.1` 指容器自己，不可照搬 Windows 本机代理地址。Web 保留上传并发配置，隐藏桌面关闭行为、下载目录和本机打开日志按钮。

访问认证使用 HttpOnly / SameSite Cookie，HTTPS 时启用 Secure。API 和 WebSocket 均检查会话，写请求校验 Origin。API Hash 和代理用 Fernet 加密，主密钥从 secret 文件读取。访问凭据不放进前端构建、localStorage 或媒体 URL。

## 检查与验证

```powershell
npm run build
npm test
python -m uv run --project backend pytest backend/tests -q
python -m uv run --project backend ruff check backend
python -m uv run --project backend mypy --config-file backend/pyproject.toml backend/src
npm run test:web
```

浏览器检查需要本机 Chrome 和 `.runtime/中文 样本.mp4`；可先运行 `npm run test:desktop` 生成样本。测试使用隔离数据目录，不向 Telegram 发消息。

Linux Docker 验证：

```bash
docker build -t tg-netdisk:web-check .
sh scripts/check-docker.sh
```

本次在 WSL Ubuntu 22.04 / Linux amd64 实际构建，并验证非 root 运行、Cookie 登录、服务器素材注册及 Range、凭据加密、草稿持久化、正常 SIGTERM 停止及重启后旧 Web 会话失效。Chrome 实测服务器视频、截图、封面、相册、草稿与退出；Windows 桌面媒体及退出恢复回归通过。

自动化结果：pytest 64 项通过、1 项 Windows 符号链接权限导致跳过；Vitest 9 项通过。本地入口额外验证了配置与密钥复用，并在没有 TG 环境变量时连续两次启动成功。类型检查、生产构建、Ruff、mypy、npm 生产依赖和 Python 依赖审计通过。Linux 容器另外实测越界符号链接不出现在目录列表，且不能注册为素材。

真实 Telegram 发送、独立封面最终显示、真实域名证书签发、ARM64 和更多浏览器 / 硬件编码组合仍需部署联调。
