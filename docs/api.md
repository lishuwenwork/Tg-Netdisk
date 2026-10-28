# 本地接口

地址由 Electron 启动 Python 后动态获得。除预检外均需 `Authorization: Bearer <runtime token>`。允许来源为生产 `app://bundle` 和开发 `http://127.0.0.1:5173`；不开放公网服务。

| 方法 | 路径 /api 下 | 输入 / 返回 |
| --- | --- | --- |
| GET | health | ready、version |
| GET | snapshot | 设置、登录、当前草稿、媒体、频道、有序任务列表 |
| GET / PUT | settings | 连接 / 显示 / 默认频道 / 上传并发设置；敏感值不返回 |
| GET | settings/proxies | 账号编辑器按需读取明文 Telegram / 下载代理；需要运行时令牌，不返回 API Hash |
| GET | diagnostics/upload | 原生加密 / 计算基准、分块、并发、代理使用状态及已连接账号的 Ping 延迟；不发送文件或消息 |
| POST | settings/test/telegram 或 download | 独立连接诊断 |
| GET | auth | 登录状态和账号 |
| POST | auth/qr | 新二维码、到期时间；取消旧等待 |
| POST | auth/password | `{password}`；仅本次登录 |
| POST | auth/cancel / auth/logout | 取消登录 / 注销当前会话 |
| GET | channels | 已缓存频道 |
| POST | channels/refresh | 加载已加入广播频道 |
| POST | channels/resolve | `{channel_id: string}`，解析且检查发帖权限 |
| POST | media/register | `{paths: string[]}` → assets、failures；只引用原路径 |
| PUT | media/{id}/metadata | duration、尺寸、容器、轨道编码、解码能力、缩略图 ID |
| GET | media/{id}/file | 已注册媒体文件，支持 Range；媒体元素允许 token 参数 |
| POST | downloads | `{url, headers}` → downloading 媒体准备项 |
| POST | downloads/{id}/cancel | 取消并移除 .part |
| POST | frames | source_id、timestamp、image（小图 data URL）、purpose |
| PUT | drafts/current | 当前草稿完整对象；保留素材顺序和封面引用 |
| POST | tasks | 草稿 → 校验后保存发布快照 |
| GET | tasks/{id} | 快照、状态、进度、消息与状态事件 |
| POST | tasks/{id}/cancel | 安全阶段 cancelled；发布阶段 unknown |
| POST | tasks/{id}/retry | 仅 failed / cancelled；复用逻辑操作 random_id |
| DELETE | tasks/{id} | 删除已结束的本地历史及关联项 / 消息 / 事件，不删除文件和 Telegram 消息；unknown 需 `confirm_unknown=true`；活动任务拒绝删除 |
| POST | tasks/{id}/reconcile | 有充分关联证据才成功，否则保持 unknown |
| POST | tasks/{id}/confirm | `{outcome, confirmed, message_ids}`；人工核对全部素材 |
| GET | cache | reclaimable、protected、removed（字节） |
| POST | cache/clean | 引用保护下清理受管理媒体 |
| GET | status | 活跃任务、下载 ID；用于窗口退出判断 |
| WS | events?token=… | `{type,id,time,data}`；断线重连后查询 snapshot |

业务错误返回 `{code, message, retryable}`；输入结构错误使用 FastAPI 422；不返回异常堆栈。主要业务错误码包括 API_REQUIRED、LOGIN_REQUIRED、NO_POST_PERMISSION、INVALID_MEDIA、FILE_CHANGED、MEDIA_NOT_READY、ALBUM_COUNT、VIDEO_REQUIRED、CAPTION_TOO_LONG、UNSAFE_RETRY。

设置字段 `upload_concurrency` 为严格整数，范围 1～10，默认 4。PUT 允许只提交变更字段，未提交值保留；非法并发值返回 422。旧配置缺少字段时 GET / snapshot 补 4。上传期间可保存常规设置，不断开当前连接；实际连接参数变更仍返回 TASK_ACTIVE。并发值在每个文件开始上传时读取，当前文件不受影响。health 和 diagnostics/upload 的 max_in_flight 返回保存后的配置值；独立 CLI 诊断使用默认值 4。

草稿 item 为 `{media_id, cover_id}`。任务快照包含频道快照、有序媒体、文件大小与修改时间、文案实体、封面引用、每项 random_id。消息结果按同一顺序返回 media_id、message_id、channel_id、grouped_id。

任务 progress 包含 sent、total、speed、item，以及可为空的 eta_seconds 和采样时间 sampled_at。eta_seconds 只估算上传字节的剩余时间，不承诺排队与发布响应耗时；缺少可靠样本时为空。重试会清空旧进度和估算。

WebSocket 是状态变化通知，客户端不依赖它保存唯一事实：连接成功 / 重连后重新获取 snapshot；队列持久化才是恢复依据。
