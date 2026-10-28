# 上传性能排查与修复（0.1.4）

日期：2026-10-28。对比条件经用户确认：同账号、同代理节点、同文件；Telegram 客户端约 2 MB/s，原工具为几百 KB/s，伴随间歇等待。

## 已确认的问题

1. **没有打包原生加密加速库。** 原依赖缺少 cryptg，当前 Windows Python 环境也未找到 Telethon 可使用的 OpenSSL AES-IGE，实际退回 pyaes。最初 128 KiB 随机数据加密用时约 0.3515 秒，吞吐约 0.356 MiB/s；另一轮同机对比得到 0.217 MiB/s。该计算路径本身已可能成为几百 KB/s 级别的瓶颈。
2. **逐块等待服务器确认。** 锁定的 Telethon 1.45 默认对小于等于 100 MiB 文件使用 128 KiB 分块、100–750 MiB 使用 256 KiB；原项目直接调用串行 upload_file。每块发送后等待响应，再读取下一块，吞吐受往返延迟影响。
3. **进度保存处在上传路径中。** 原进度回调直接等待 SQLite 写入与事件推送；在慢盘、繁忙后台或高延迟链路上会叠加等待。

这些是本地实现的性能瓶颈，没有发现主动把带宽设为几百 KB/s 的代码。尚未采集这次真实传输的 RPC 错误，不能仅凭间歇停顿判定 Telegram 对账号进行了限速。

## 已完成的修复

- 锁定 cryptg 0.6.0，并随 Python 后端打包。打包脚本直接运行冻结后的后端，强制检查 native_crypto / cryptg，避免构建产物悄悄退回 Python 加密。
- 使用协议允许的 512 KiB 分块，单个文件最多保持 4 个未完成请求。队列仍只有一个发布任务；相册文件与最终发送顺序不变。
- 按块读取，内存中只保留有限分块；小文件保留正确 MD5，大文件使用 InputFileBig。服务器确认后才累加进度，任一失败或取消会清理其余请求。
- 进度通过独立协程合并，数据库与界面每约 0.5 秒更新，不再让每个分块等待 SQLite。切换到发布阶段前会排空最后进度。
- 测速尚未形成时显示“测速中”，超过 5 秒没有确认时显示“等待响应”；不通过抬高显示值制造假提速。
- 识别并记录 FloodWait / FloodPremiumWait 的实际等待秒数，保留取消和重试上限，不绕过服务端限制。
- 代理框明文显示并支持保存后回显。代理值只通过账号编辑器专用的已认证接口读取，不写普通日志；API Hash / 两步验证规则不变。

## 本机基准与验证边界

机器记录：`.runtime/upload-investigation/benchmark.json`。

| 检查 | 实测 |
| --- | --- |
| Python AES-IGE | 0.217–0.356 MiB/s |
| cryptg AES-IGE | 约 467–478 MiB/s |
| 冻结后的 0.1.4 后端 cryptg AES-IGE | 本次约 583.52 MiB/s，原生加速已启用 |
| 模拟 80ms ACK，4 MiB，原 128 KiB 串行路径 | 2.995 秒 |
| 同一模拟 ACK，4×512 KiB 流水线 | 0.202 秒，最大并行 4 |

以上是**加密计算与模拟服务器基准**，不是实际 Telegram 上传测速，不能据此承诺真实上传达到某个速度。本次没有向私人频道发布测试内容。修复后需要用原来的同一文件复测真实链路。

## 继续定位实际链路

在“账号与连接 → 上传诊断”查看加密加速、分块和并行数、代理是否启用以及当前连接的 Ping 延迟。诊断只发协议 Ping，不发文件或消息；加密计算速度单独标注，不当作网络上传速度。

日志仅记录字节数、耗时、平均确认延迟、重试异常类型及限流秒数，不记录文件内容、代理密码、会话密钥或请求头：

- `runtime ... crypto_backend=...`：确认实际加密后端。
- `upload_complete bytes=... seconds=... kib_s=... mean_ack_ms=...`：真实完成吞吐与分块确认延迟。
- `upload_wait kind=... seconds=...`：服务端明确要求等待。
- `upload_connection_retry kind=...`：断网 / 超时导致的重试。

## 官方依据

- [Telethon FAQ：加密性能与串行上传](https://docs.telethon.dev/en/stable/quick-references/faq.html#file-download-is-slow-or-sending-files-takes-too-long)
- [Telegram 文件协议：512 KiB 分块与并行调用队列](https://core.telegram.org/api/files#uploading-files)
