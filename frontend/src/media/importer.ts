import { api, mediaUrl } from "../lib/api";
import { dataUrl } from "./engine";
import type { Asset, Metadata } from "../types";
import type { useWorkspace } from "../stores/workspace";
type Workspace = ReturnType<typeof useWorkspace>;
const workers = new Map<string, Worker>();
export async function analyzeAsset(asset: Asset, store: Workspace) {
  if (
    asset.kind !== "video" ||
    asset.status !== "ready" ||
    workers.has(asset.id)
  )
    return;
  store.processing.add(asset.id);
  const revision = store.draftRevision;
  const worker = new Worker(
    new URL("../workers/thumbnails.worker.ts", import.meta.url),
    { type: "module" },
  );
  workers.set(asset.id, worker);
  const active = () =>
    revision === store.draftRevision && workers.get(asset.id) === worker;
  let metadata: Metadata | null = null;
  let sequence = Promise.resolve();
  const finish = () => {
    if (workers.get(asset.id) === worker) {
      workers.delete(asset.id);
      store.processing.delete(asset.id);
    }
    worker.terminate();
  };
  worker.onerror = () => {
    if (!active()) return;
    store.error = "媒体分析失败，请重新选择文件";
    finish();
  };
  worker.onmessage = (event) => {
    const message = event.data as {
      type: string;
      metadata?: Metadata;
      blob?: Blob;
      timestamp?: number;
      message?: string;
    };
    sequence = sequence
      .then(async () => {
        if (!active()) return;
        if (message.type === "metadata" && message.metadata) {
          metadata = { ...message.metadata, thumbnails: [] };
          const updated = await api<Asset>(
            `media/${asset.id}/metadata`,
            "PUT",
            metadata,
          );
          if (!active()) return;
          store.assets[asset.id] = updated;
          if (!metadata.video_decodable) finish();
        } else if (message.type === "thumbnail" && message.blob && metadata) {
          const saved = await api<Asset>("frames", "POST", {
            source_id: asset.id,
            timestamp: message.timestamp,
            image: await dataUrl(message.blob),
            purpose: "thumbnail",
          });
          if (!active()) return;
          metadata.thumbnails!.push(saved.id);
          store.assets[saved.id] = saved;
        } else if (message.type === "done" && metadata) {
          const updated = await api<Asset>(
            `media/${asset.id}/metadata`,
            "PUT",
            metadata,
          );
          if (!active()) return;
          store.assets[asset.id] = updated;
          finish();
        } else if (message.type === "error") {
          const failed: Metadata = {
            duration: 0,
            width: 0,
            height: 0,
            container: "",
            video_codec: "",
            audio_codec: "",
            readable: false,
            video_decodable: false,
            audio_decodable: false,
            error: message.message || "媒体解析失败",
          };
          const updated = await api<Asset>(
            `media/${asset.id}/metadata`,
            "PUT",
            failed,
          );
          if (!active()) return;
          store.assets[asset.id] = updated;
          finish();
        }
      })
      .catch((e) => {
        if (active())
          store.error = e instanceof Error ? e.message : "媒体分析失败";
        finish();
      });
  };
  worker.postMessage({ url: mediaUrl(asset.id) });
}
export function disposeWorkers() {
  for (const worker of workers.values()) worker.terminate();
  workers.clear();
}
