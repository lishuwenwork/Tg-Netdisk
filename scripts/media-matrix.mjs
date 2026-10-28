import { _electron as electron } from "playwright";
import { build } from "esbuild";
import fs from "node:fs/promises";
import path from "node:path";
import assert from "node:assert/strict";
import {
  ALL_FORMATS,
  BlobSource,
  BufferTarget,
  EncodedAudioPacketSource,
  EncodedPacketSink,
  EncodedVideoPacketSource,
  Input,
  MkvOutputFormat,
  MovOutputFormat,
  Output,
} from "mediabunny";
const root = path.resolve(import.meta.dirname, ".."),
  directory = path.join(root, ".runtime");
const environment = {
  ...process.env,
  TG_DATA_DIR: path.join(directory, "matrix-data"),
};
delete environment.ELECTRON_RUN_AS_NODE;
delete environment.TG_DEV;
const desktop = await electron.launch({
  args: [root],
  env: environment,
  timeout: 60000,
});
let window;
try {
  window = await desktop.firstWindow({ timeout: 60000 });
  await window
    .getByText("本地服务已连接", { exact: true })
    .waitFor({ timeout: 30000 });
  const connection = await window.evaluate(() =>
    globalThis.desktop.connection(),
  );
  const bundle = await build({
    entryPoints: [path.join(root, "scripts/fixture.ts")],
    bundle: true,
    write: false,
    format: "iife",
    globalName: "__fixtures",
    platform: "browser",
  });
  await window.evaluate(
    bundle.outputFiles[0].text +
      "\nglobalThis.__fixtures = __fixtures; void 0;",
  );
  const baseline = await fs.readFile(path.join(directory, "中文 样本.mp4"));
  const variants = [
    { name: "MP4-H264-AAC", file: path.join(directory, "中文 样本.mp4") },
  ];
  for (const [name, format, rotation] of [
    ["MOV", new MovOutputFormat(), 0],
    ["MKV", new MkvOutputFormat(), 0],
    ["MOV-portrait", new MovOutputFormat(), 90],
  ]) {
    const input = new Input({
      formats: ALL_FORMATS,
      source: new BlobSource(new Blob([baseline])),
    });
    const videoTrack = await input.getPrimaryVideoTrack(),
      audioTrack = await input.getPrimaryAudioTrack();
    const target = new BufferTarget(),
      output = new Output({ format, target });
    const video = new EncodedVideoPacketSource(videoTrack.codec),
      audio = new EncodedAudioPacketSource(audioTrack.codec);
    output.addVideoTrack(video, { rotation });
    output.addAudioTrack(audio);
    await output.start();
    await Promise.all([
      (async () => {
        for await (const packet of new EncodedPacketSink(videoTrack).packets())
          await video.add(packet, {
            decoderConfig: await videoTrack.getDecoderConfig(),
          });
        video.close();
      })(),
      (async () => {
        for await (const packet of new EncodedPacketSink(audioTrack).packets())
          await audio.add(packet, {
            decoderConfig: await audioTrack.getDecoderConfig(),
          });
        audio.close();
      })(),
    ]);
    await output.finalize();
    input.dispose();
    const file = path.join(
      directory,
      `${name}.${name === "MKV" ? "mkv" : "mov"}`,
    );
    await fs.writeFile(file, new Uint8Array(target.buffer));
    variants.push({ name, file });
  }
  const webm = await window.evaluate("__fixtures.webm()");
  const webmFile = path.join(directory, "WebM-VP9-Opus.webm");
  await fs.writeFile(webmFile, Buffer.from(webm));
  variants.push({ name: "WebM-VP9-Opus", file: webmFile });
  const vfr = await window.evaluate("__fixtures.generate(true)");
  const vfrFile = path.join(directory, "MP4-VFR.mp4");
  await fs.writeFile(vfrFile, Buffer.from(vfr.bytes));
  variants.push({ name: "MP4-VFR", file: vfrFile });
  const results = [];
  for (const variant of variants) {
    const response = await fetch(`${connection.baseUrl}/api/media/register`, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${connection.token}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ paths: [variant.file] }),
    });
    const registered = await response.json();
    assert.equal(registered.assets.length, 1, JSON.stringify(registered));
    const url = `${connection.baseUrl}/api/media/${registered.assets[0].id}/file?token=${encodeURIComponent(connection.token)}`;
    const result = await window.evaluate(
      (url) => globalThis.__fixtures.inspectMedia(url),
      url,
    );
    assert.equal(result.metadata.video_decodable, true, variant.name);
    assert.equal(result.metadata.audio_decodable, true, variant.name);
    assert.ok(result.nextTimestamp > result.firstTimestamp, variant.name);
    assert.equal(result.previousTimestamp, result.firstTimestamp, variant.name);
    assert.ok(
      result.customPlaybackTicks > 1,
      `${variant.name} playback stalled`,
    );
    if (variant.name === "MOV-portrait") {
      assert.equal(result.width, 360);
      assert.equal(result.height, 640);
    }
    results.push({ name: variant.name, ...result });
  }
  await fs.writeFile(
    path.join(directory, "media-matrix.json"),
    JSON.stringify(
      {
        electron: await desktop.evaluate(() => process.versions.electron),
        platform: process.platform,
        results,
      },
      null,
      2,
    ),
  );
  console.log("Media matrix passed: " + results.map((r) => r.name).join(", "));
} finally {
  if (window)
    await window.evaluate(() => globalThis.desktop.quit()).catch(() => {});
  await desktop.close().catch(() => {});
}
