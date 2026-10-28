import type { PublishTask, TaskState } from "../types";
export const states: Record<TaskState, string> = {
  queued: "等待中",
  preparing: "准备中",
  uploading: "上传中",
  publishing: "发布中",
  waiting_retry: "等待重试",
  succeeded: "已发布",
  failed: "失败",
  cancelled: "已取消",
  unknown: "结果待确认",
};
export function bytes(value = 0) {
  if (!Number.isFinite(value) || value <= 0) return "0 B";
  const unit = Math.min(3, Math.floor(Math.log(value) / Math.log(1024)));
  return `${(value / 1024 ** unit).toFixed(unit ? 1 : 0)} ${["B", "KB", "MB", "GB"][unit]}`;
}
export function time(value = 0, milliseconds = false) {
  if (!Number.isFinite(value) || value < 0) value = 0;
  const hours = Math.floor(value / 3600),
    minutes = Math.floor(value / 60) % 60;
  return `${hours ? String(hours).padStart(2, "0") + ":" : ""}${String(minutes).padStart(2, "0")}:${String(Math.floor(value) % 60).padStart(2, "0")}${milliseconds ? "." + String(Math.floor((value % 1) * 1000)).padStart(3, "0") : ""}`;
}
export function caption(title: string, description: string, tags: string[]) {
  return [title.trim(), description.trim(), tags.join(" ")]
    .filter(Boolean)
    .join("\n\n");
}
export function remainingTime(
  task: Pick<PublishTask, "state" | "progress">,
  now = Date.now(),
): string {
  if (task.state === "queued") return "等待开始";
  if (task.state === "publishing") return "等待发布结果";
  if (task.state === "waiting_retry") return "等待重试";
  if (task.state !== "uploading") return "计算中";
  const progress = task.progress;
  if (progress.total > 0 && progress.sent >= progress.total)
    return "等待发布结果";
  const eta = progress.eta_seconds;
  const age = now - Date.parse(progress.sampled_at || "");
  if (
    eta == null ||
    !Number.isFinite(eta) ||
    eta <= 0 ||
    progress.speed <= 0 ||
    !Number.isFinite(age) ||
    age > 5000 ||
    age < -5000
  )
    return "计算中";
  const seconds = Math.ceil(eta),
    minutes = Math.floor(seconds / 60),
    hours = Math.floor(minutes / 60);
  if (hours)
    return `约 ${hours} 小时${minutes % 60 ? ` ${minutes % 60} 分` : ""}`;
  if (minutes)
    return `约 ${minutes} 分${seconds % 60 ? ` ${seconds % 60} 秒` : ""}`;
  return `约 ${seconds} 秒`;
}
export function transferSpeed(
  task: Pick<PublishTask, "state" | "progress">,
  now = Date.now(),
): string {
  if (task.state !== "uploading") return "—";
  const progress = task.progress;
  if (progress.total > 0 && progress.sent >= progress.total) return "上传完成";
  if (progress.sampled_at && now - Date.parse(progress.sampled_at) > 5000)
    return "等待响应";
  if (
    progress.speed_ready === false ||
    !Number.isFinite(progress.speed) ||
    progress.speed <= 0
  )
    return "测速中";
  return bytes(progress.speed) + "/s";
}
export function tag(value: string): string {
  const normalized = value.trim().replace(/^#/, "");
  if (!/^[\p{L}\p{N}_]+$/u.test(normalized) || /^\p{N}+$/u.test(normalized))
    throw new Error("标签只能包含中文、字母、数字和下划线，不能全为数字");
  return "#" + normalized;
}
export const activeStates: TaskState[] = [
  "queued",
  "preparing",
  "uploading",
  "publishing",
  "waiting_retry",
];
