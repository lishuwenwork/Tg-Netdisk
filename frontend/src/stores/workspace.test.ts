import { beforeEach, describe, expect, it, vi } from "vitest";
import { createPinia, setActivePinia } from "pinia";
import { api } from "../lib/api";
import { useWorkspace } from "./workspace";
import type { Asset, PublishTask } from "../types";

vi.mock("../lib/api", () => ({
  api: vi.fn(),
  initialize: vi.fn(),
  subscribe: vi.fn(),
}));

beforeEach(() => {
  setActivePinia(createPinia());
  vi.mocked(api).mockReset().mockResolvedValue({});
});

describe("reset current publication", () => {
  it("persists an empty draft with the default channel and keeps queued snapshots and files", async () => {
    const store = useWorkspace();
    const video: Asset = {
      id: "video",
      name: "source.mp4",
      path: "D:/source.mp4",
      kind: "video",
      origin: "local",
      status: "ready",
      size: 42,
      metadata: { video_decodable: true },
    };
    store.assets[video.id] = video;
    store.settings.default_channel = "-1001234567890123";
    Object.assign(store.draft, {
      title: "旧标题",
      description: "旧简介",
      tags: ["#4k"],
      bold_title: false,
      channel_id: "-100999",
      items: [{ media_id: "video", cover_id: "cover" }],
    });
    const queued: PublishTask = {
      id: "queued",
      state: "queued",
      created_at: "2026-10-27T00:00:00Z",
      error: "",
      attempts: 0,
      snapshot: {
        draft: JSON.parse(JSON.stringify(store.draft)),
        channel: { id: "-100999", name: "频道", can_post: true },
        caption: "旧标题",
        items: [
          {
            media_id: "video",
            cover_id: "cover",
            asset: video,
            cover: null,
            random_id: "9007199254740993",
          },
        ],
      },
      progress: { sent: 0, total: 42, speed: 0, item: 0 },
      messages: [],
    };
    store.tasks.push(queued);
    store.selectedId = "video";
    store.processing.add("video");
    await store.resetDraft();
    expect(store.draft).toEqual({
      id: "current",
      title: "",
      description: "",
      tags: [],
      bold_title: true,
      channel_id: "-1001234567890123",
      items: [],
    });
    expect(store.selectedId).toBe("");
    expect(store.processing.size).toBe(0);
    expect(store.draftRevision).toBe(1);
    expect(store.tasks[0]).toEqual(queued);
    expect(store.tasks[0].snapshot.draft.title).toBe("旧标题");
    expect(store.assets.video.path).toBe("D:/source.mp4");
    expect(api).toHaveBeenCalledExactlyOnceWith(
      "drafts/current",
      "PUT",
      JSON.parse(JSON.stringify(store.draft)),
    );
    store.dispose();
  });

  it("writes reset after an older in-flight save so the old content cannot return", async () => {
    const store = useWorkspace();
    let finish: (value: unknown) => void = () => {};
    vi.mocked(api).mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          finish = resolve;
        }),
    );
    store.draft.title = "保存中";
    const saving = store.save(true);
    await vi.waitFor(() => expect(api).toHaveBeenCalledTimes(1));
    store.draft.title = "尚未保存的改动";
    store.autosave();
    const reset = store.resetDraft();
    finish({});
    await Promise.all([saving, reset]);
    expect(
      vi
        .mocked(api)
        .mock.calls.map((call) => (call[2] as { title: string }).title),
    ).toEqual(["保存中", ""]);
    expect(store.draft.title).toBe("");
    expect(store.saving).toBe(false);
    store.dispose();
  });

  it("ignores an obsolete editing error after reset", async () => {
    const store = useWorkspace();
    const revision = store.draftRevision;
    let fail: (reason: Error) => void = () => {};
    const operation = store.guarded(
      () =>
        new Promise((_, reject) => {
          fail = reject;
        }),
      revision,
    );
    await store.resetDraft();
    fail(new Error("已移除素材的错误"));
    await operation;
    expect(store.error).toBe("");
    store.dispose();
  });
});
