import { describe, expect, it } from "vitest";
import {
  bytes,
  caption,
  remainingTime,
  tag,
  time,
  transferSpeed,
} from "./format";
import type { PublishTask } from "../types";
describe("publication text", () => {
  it("omits empty caption sections and preserves literal input", () => {
    expect(caption("  😀 title  ", "<b>literal</b>", ["#4k", "#中文"])).toBe(
      "😀 title\n\n<b>literal</b>\n\n#4k #中文",
    );
    expect(caption("", "", [])).toBe("");
  });
  it("normalizes valid hashtags and rejects invalid strings", () => {
    expect(tag("中文")).toBe("#中文");
    expect(tag("#4k")).toBe("#4k");
    expect(() => tag("bad tag")).toThrow();
    expect(() => tag("123")).toThrow();
    expect(() => tag("＃tag")).toThrow();
  });
});
describe("progress display", () => {
  it("formats byte progress and exact frame times", () => {
    expect(bytes(1024)).toBe("1.0 KB");
    expect(bytes(0)).toBe("0 B");
    expect(time(3661.125, true)).toBe("01:01:01.125");
    expect(time(NaN)).toBe("00:00");
  });
});
describe("remaining transfer time", () => {
  const now = Date.parse("2026-10-27T12:00:00Z");
  function task(
    state: PublishTask["state"],
    eta: number | null = 90,
  ): Pick<PublishTask, "state" | "progress"> {
    return {
      state,
      progress: {
        sent: 100,
        total: 1000,
        speed: 10,
        item: 0,
        eta_seconds: eta,
        sampled_at: new Date(now).toISOString(),
      },
    };
  }
  it("shows estimates only during an active and fresh transfer", () => {
    expect(remainingTime(task("uploading"), now)).toBe("约 1 分 30 秒");
    expect(remainingTime(task("uploading", 3660), now)).toBe("约 1 小时 1 分");
    expect(remainingTime(task("uploading", null), now)).toBe("计算中");
    expect(remainingTime(task("uploading"), now + 6000)).toBe("计算中");
    const stopped = task("uploading");
    stopped.progress.speed = 0;
    expect(remainingTime(stopped, now)).toBe("计算中");
  });
  it("does not invent a completion time while queued, retrying or publishing", () => {
    expect(remainingTime(task("queued"), now)).toBe("等待开始");
    expect(remainingTime(task("preparing"), now)).toBe("计算中");
    expect(remainingTime(task("waiting_retry"), now)).toBe("等待重试");
    expect(remainingTime(task("publishing"), now)).toBe("等待发布结果");
    const uploaded = task("uploading", 0);
    uploaded.progress.sent = uploaded.progress.total;
    expect(remainingTime(uploaded, now)).toBe("等待发布结果");
  });
  it("distinguishes measurement warm-up and missing ACKs from a real measured rate", () => {
    const value = task("uploading");
    value.progress.speed_ready = false;
    expect(transferSpeed(value, now)).toBe("测速中");
    value.progress.speed_ready = true;
    expect(transferSpeed(value, now)).toBe("10 B/s");
    expect(transferSpeed(value, now + 6000)).toBe("等待响应");
    expect(transferSpeed(task("queued"), now)).toBe("—");
  });
});
