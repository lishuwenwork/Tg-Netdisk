import { CanvasSink } from "mediabunny";
import { analyze, canvasBlob, openInput } from "../media/engine";
export interface AnalyzeRequest {
  url: string;
}
self.onmessage = async (event: MessageEvent<AnalyzeRequest>) => {
  const input = openInput(event.data.url);
  try {
    const metadata = await analyze(input);
    self.postMessage({ type: "metadata", metadata });
    const track = await input.getPrimaryVideoTrack();
    if (!track || !metadata.video_decodable) return;
    const sink = new CanvasSink(track, { width: 160, poolSize: 1 });
    const first = Math.max(0, await track.getFirstTimestamp());
    const times = Array.from(
      { length: 10 },
      (_, i) => first + ((metadata.duration - first) * i) / 10,
    );
    for await (const frame of sink.canvasesAtTimestamps(times)) {
      if (frame)
        self.postMessage({
          type: "thumbnail",
          blob: await canvasBlob(frame.canvas, "image/jpeg"),
          timestamp: frame.timestamp,
        });
    }
    self.postMessage({ type: "done" });
  } catch (cause) {
    console.warn(
      "media-analysis",
      cause instanceof Error
        ? `${cause.name}: ${cause.message}`.replace(
            /https?:\/\/\S+/g,
            "[media]",
          )
        : "unknown",
    );
    self.postMessage({
      type: "error",
      message: "媒体解析失败，请选择有效且可解码的视频",
    });
  } finally {
    input.dispose();
  }
};
