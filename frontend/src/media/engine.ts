import {
  ALL_FORMATS,
  AudioBufferSink,
  CanvasSink,
  Input,
  UrlSource,
} from "mediabunny";
import type { Metadata } from "../types";

export function openInput(url: string) {
  return new Input({
    formats: ALL_FORMATS,
    source: new UrlSource(url, {
      maxCacheSize: 16 * 1024 * 1024,
      getRetryDelay: (attempt) => (attempt < 2 ? 0.5 : null),
    }),
  });
}
export async function analyze(input: Input): Promise<Metadata> {
  const video = await input.getPrimaryVideoTrack(),
    audio = await input.getPrimaryAudioTrack();
  const format = await input.getFormat();
  if (!video) throw new Error("文件没有视频轨道");
  const canVideo = await video.canDecode();
  return {
    duration: await input.computeDuration(),
    width: video.displayWidth,
    height: video.displayHeight,
    container: format.name,
    video_codec:
      (await video.getCodecParameterString()) || String(video.codec || "未知"),
    audio_codec: audio
      ? (await audio.getCodecParameterString()) || String(audio.codec || "未知")
      : "",
    readable: true,
    video_decodable: canVideo,
    audio_decodable: audio ? await audio.canDecode() : true,
    error: canVideo ? "" : "当前视频编码无法解码，请移除或重新选择",
  };
}
export async function canvasBlob(
  canvas: HTMLCanvasElement | OffscreenCanvas,
  type = "image/png",
): Promise<Blob> {
  if (canvas instanceof OffscreenCanvas) return canvas.convertToBlob({ type });
  return new Promise((resolve, reject) =>
    canvas.toBlob(
      (blob) => (blob ? resolve(blob) : reject(new Error("图片导出失败"))),
      type,
      0.9,
    ),
  );
}
export async function dataUrl(blob: Blob): Promise<string> {
  const buffer = new Uint8Array(await blob.arrayBuffer());
  let binary = "";
  for (let i = 0; i < buffer.length; i += 16384)
    binary += String.fromCharCode(...buffer.subarray(i, i + 16384));
  return `data:${blob.type};base64,${btoa(binary)}`;
}
export async function exactFrame(
  input: Input,
  timestamp: number,
  direction = 0,
) {
  const track = await input.getPrimaryVideoTrack();
  if (!track || !(await track.canDecode())) throw new Error("当前视频无法截帧");
  const sink = new CanvasSink(track, { poolSize: 2 });
  const current = await sink.getCanvas(
    Math.max(await track.getFirstTimestamp(), timestamp),
  );
  if (!current) throw new Error("没有可用画面");
  let result = current;
  if (direction < 0) {
    result =
      (await sink.getCanvas(
        Math.max(
          await track.getFirstTimestamp(),
          current.timestamp - 0.5 / track.timeResolution,
        ),
      )) || current;
  } else if (direction > 0) {
    for await (const next of sink.canvases(current.timestamp)) {
      if (next.timestamp > current.timestamp + 1e-8) {
        result = next;
        break;
      }
    }
  }
  return {
    blob: await canvasBlob(result.canvas),
    timestamp: result.timestamp,
    width: result.canvas.width,
    height: result.canvas.height,
  };
}

/** Bounded decoded playback for containers the native media element cannot play. */
export class DecodedPlayer {
  revision = 0;
  context: AudioContext | null = null;
  gain: GainNode | null = null;
  sources = new Set<AudioBufferSourceNode>();
  constructor(
    public input: Input,
    public canvas: HTMLCanvasElement,
  ) {}
  pause() {
    this.revision++;
    for (const source of this.sources) {
      try {
        source.stop();
      } catch {}
    }
    this.sources.clear();
  }
  volume(value: number) {
    if (this.gain) this.gain.gain.value = value;
  }
  async play(
    start: number,
    rate: number,
    volume: number,
    tick: (time: number) => void,
    ended: () => void,
  ) {
    this.pause();
    const revision = this.revision;
    const video = await this.input.getPrimaryVideoTrack(),
      audio = await this.input.getPrimaryAudioTrack();
    if (!video || revision !== this.revision) return;
    const sink = new CanvasSink(video, { poolSize: 2 });
    this.canvas.width = video.displayWidth;
    this.canvas.height = video.displayHeight;
    const context = (this.context ||= new AudioContext());
    await context.resume();
    this.gain ||= context.createGain();
    this.gain.disconnect();
    this.gain.connect(context.destination);
    this.volume(volume);
    const clock = context.currentTime + 0.08;
    const alive = () => revision === this.revision;
    const wait = (ms: number) =>
      new Promise((resolve) => setTimeout(resolve, Math.min(ms, 100)));
    const audioLoop = async () => {
      if (!audio || !(await audio.canDecode())) return;
      for await (const item of new AudioBufferSink(audio).buffers(start)) {
        if (!alive()) break;
        const when = clock + (item.timestamp - start) / rate;
        while (when > context.currentTime + 0.6 && alive()) await wait(40);
        if (!alive()) break;
        const source = context.createBufferSource();
        source.buffer = item.buffer;
        source.playbackRate.value = rate;
        source.connect(this.gain!);
        this.sources.add(source);
        source.onended = () => this.sources.delete(source);
        const offset = Math.max(
          0,
          start - item.timestamp,
          (context.currentTime - when) * rate,
        );
        if (offset < item.buffer.duration)
          source.start(Math.max(context.currentTime, when), offset);
      }
    };
    void audioLoop().catch(() => {});
    for await (const frame of sink.canvases(start)) {
      if (!alive()) break;
      const when = clock + (frame.timestamp - start) / rate;
      while (when > context.currentTime && alive())
        await wait((when - context.currentTime) * 1000);
      if (!alive()) break;
      if (context.currentTime - when < 0.15)
        this.canvas.getContext("2d")?.drawImage(frame.canvas, 0, 0);
      tick(Math.max(0, start + (context.currentTime - clock) * rate));
    }
    if (alive()) {
      this.pause();
      ended();
    }
  }
  async dispose() {
    this.pause();
    await this.context?.close();
    this.context = null;
  }
}
