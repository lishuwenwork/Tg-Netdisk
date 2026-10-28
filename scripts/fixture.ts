import {
  ALL_FORMATS,
  AudioBufferSource,
  BlobSource,
  BufferTarget,
  CanvasSource,
  EncodedAudioPacketSource,
  EncodedPacketSink,
  Input,
  Mp4OutputFormat,
  Output,
  WebMOutputFormat,
} from "mediabunny";
import {
  analyze,
  DecodedPlayer,
  exactFrame,
  openInput,
} from "../frontend/src/media/engine";

export async function generate(variable = false) {
  // Chromium on Windows can decode AAC but may not expose an AAC AudioEncoder.
  // MediaRecorder's platform AAC path supplies the test tone without installing codecs.
  const audioContext = new AudioContext();
  const destination = audioContext.createMediaStreamDestination();
  const oscillator = audioContext.createOscillator();
  oscillator.frequency.value = 220;
  const gain = audioContext.createGain();
  gain.gain.value = 0.02;
  oscillator.connect(gain);
  gain.connect(destination);
  oscillator.start();
  const recorder = new MediaRecorder(destination.stream, {
    mimeType: "audio/mp4;codecs=mp4a.40.2",
  });
  const chunks: Blob[] = [];
  recorder.ondataavailable = (event) => chunks.push(event.data);
  const ended = new Promise<void>((resolve) => {
    recorder.onstop = () => resolve();
  });
  recorder.start();
  await new Promise((resolve) => setTimeout(resolve, 1200));
  recorder.stop();
  await ended;
  oscillator.stop();
  destination.stream.getTracks().forEach((track) => track.stop());
  await audioContext.close();
  const audioInput = new Input({
    formats: ALL_FORMATS,
    source: new BlobSource(new Blob(chunks)),
  });
  const audioTrack = (await audioInput.getPrimaryAudioTrack())!;
  const canvas = new OffscreenCanvas(640, 360);
  const context = canvas.getContext("2d")!;
  const target = new BufferTarget();
  const output = new Output({ format: new Mp4OutputFormat(), target });
  const video = new CanvasSource(canvas, { codec: "avc", bitrate: 400_000 });
  const audio = new EncodedAudioPacketSource("aac");
  output.addVideoTrack(video, { frameRate: 24 });
  output.addAudioTrack(audio);
  await output.start();
  await Promise.all([
    (async () => {
      let timestamp = 0;
      for (let i = 0; i < 48; i++) {
        const gradient = context.createLinearGradient(0, 0, 640, 360);
        gradient.addColorStop(0, "#233f36");
        gradient.addColorStop(1, "#101d24");
        context.fillStyle = gradient;
        context.fillRect(0, 0, 640, 360);
        context.fillStyle = "#b8e994";
        context.fillRect(40 + ((i * 7) % 500), 120, 85, 85);
        context.fillStyle = "#dbe4df";
        context.font = "22px sans-serif";
        context.fillText("Tg Netdisk · local sample", 40, 65);
        context.font = "14px monospace";
        context.fillText(`Frame ${i}`, 40, 320);
        const duration = variable && i % 2 ? 1 / 12 : 1 / 24;
        await video.add(timestamp, duration);
        timestamp += duration;
      }
      video.close();
    })(),
    (async () => {
      for await (const packet of new EncodedPacketSink(audioTrack).packets()) {
        await audio.add(packet, {
          decoderConfig: (await audioTrack.getDecoderConfig())!,
        });
      }
      audio.close();
      audioInput.dispose();
    })(),
  ]);
  await output.finalize();
  return {
    mime: "video/mp4;codecs=avc1,mp4a.40.2",
    bytes: Array.from(new Uint8Array(target.buffer!)),
  };
}

export async function webm() {
  const canvas = new OffscreenCanvas(320, 180),
    context = canvas.getContext("2d")!;
  const target = new BufferTarget(),
    output = new Output({ format: new WebMOutputFormat(), target });
  const video = new CanvasSource(canvas, { codec: "vp9", bitrate: 200000 });
  const audio = new AudioBufferSource({ codec: "opus", bitrate: 32000 });
  output.addVideoTrack(video, { frameRate: 20 });
  output.addAudioTrack(audio);
  await output.start();
  await Promise.all([
    (async () => {
      for (let i = 0; i < 20; i++) {
        context.fillStyle = i % 2 ? "#2b483e" : "#314955";
        context.fillRect(0, 0, 320, 180);
        await video.add(i / 20, 1 / 20);
      }
      video.close();
    })(),
    (async () => {
      await audio.add(
        new AudioBuffer({
          length: 48000,
          numberOfChannels: 1,
          sampleRate: 48000,
        }),
      );
      audio.close();
    })(),
  ]);
  await output.finalize();
  return Array.from(new Uint8Array(target.buffer!));
}

export async function inspectMedia(url: string) {
  const input = openInput(url);
  try {
    const metadata = await analyze(input);
    const first = await exactFrame(input, 0),
      next = await exactFrame(input, 0, 1);
    const previous = await exactFrame(input, next.timestamp, -1);
    const canvas = document.createElement("canvas");
    const player = new DecodedPlayer(input, canvas);
    let ticks = 0,
      lastTime = 0;
    const playback = player.play(
      0,
      1,
      0,
      (time) => {
        ticks++;
        lastTime = time;
      },
      () => {},
    );
    await new Promise((resolve) => setTimeout(resolve, 600));
    player.pause();
    await playback;
    await player.dispose();
    return {
      metadata,
      firstTimestamp: first.timestamp,
      nextTimestamp: next.timestamp,
      previousTimestamp: previous.timestamp,
      width: first.width,
      height: first.height,
      customPlaybackTicks: ticks,
      customPlaybackTime: lastTime,
    };
  } finally {
    input.dispose();
  }
}
