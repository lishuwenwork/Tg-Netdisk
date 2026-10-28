import { _electron as electron } from "playwright";
import { build } from "esbuild";
import fs from "node:fs/promises";
import path from "node:path";
import assert from "node:assert/strict";

const root = path.resolve(import.meta.dirname, "..");
const output = path.join(root, ".runtime", "reset-check");
await fs.mkdir(output, { recursive: true });
const environment = { ...process.env, TG_DATA_DIR: path.join(output, "data") };
delete environment.ELECTRON_RUN_AS_NODE;
delete environment.TG_DEV;
const app = await electron.launch({
  ...(process.env.TG_SMOKE_EXE
    ? { executablePath: process.env.TG_SMOKE_EXE, args: [] }
    : { args: [root] }),
  env: environment,
  timeout: 60000,
});
let window;
let releaseDownload;
try {
  window = await app.firstWindow({ timeout: 60000 });
  await window
    .getByText("本地服务已连接", { exact: true })
    .waitFor({ timeout: 30000 });
  const connection = await window.evaluate(() =>
    globalThis.desktop.connection(),
  );
  const request = async (route, method = "GET", data) => {
    const response = await fetch(`${connection.baseUrl}/api/${route}`, {
      method,
      headers: {
        Authorization: `Bearer ${connection.token}`,
        "Content-Type": "application/json",
      },
      body: data === undefined ? undefined : JSON.stringify(data),
    });
    assert.equal(
      response.ok,
      true,
      `${route}: ${await response.clone().text()}`,
    );
    return response.json();
  };
  const source = path.join(output, "original.mp4");
  const bundle = await build({
    entryPoints: [path.join(root, "scripts/fixture.ts")],
    bundle: true,
    write: false,
    format: "iife",
    globalName: "__fixtures",
    platform: "browser",
  });
  const fixture = await window.evaluate(
    bundle.outputFiles[0].text + "\n__fixtures.generate()",
  );
  await fs.writeFile(source, Buffer.from(fixture.bytes));
  const coverPath = path.join(output, "cover.png");
  const coverBytes = await window.evaluate(async () => {
    const canvas = document.createElement("canvas");
    canvas.width = 64;
    canvas.height = 36;
    const context = canvas.getContext("2d");
    context.fillStyle = "#b8e994";
    context.fillRect(0, 0, 64, 36);
    const image = await new Promise((resolve) =>
      canvas.toBlob(resolve, "image/png"),
    );
    return Array.from(new Uint8Array(await image.arrayBuffer()));
  });
  await fs.writeFile(coverPath, Buffer.from(coverBytes));
  const registered = await request("media/register", "POST", {
    paths: [source, coverPath],
  });
  assert.equal(registered.assets.length, 2);
  const [video, cover] = registered.assets;
  await request("drafts/current", "PUT", {
    id: "current",
    title: "待重置标题",
    description: "待重置简介",
    tags: ["#4k"],
    bold_title: false,
    channel_id: "-100123",
    items: [{ media_id: video.id, cover_id: cover.id }],
  });
  const tasksBefore = (await request("snapshot")).tasks;
  await window.reload();
  await window
    .getByText("本地服务已连接", { exact: true })
    .waitFor({ timeout: 30000 });
  await window.getByLabel("标题", { exact: true }).fill("输入后立即重置");
  await window.getByRole("button", { name: "视频直链", exact: true }).click();
  const dialog = window.locator("dialog[open]");
  await dialog
    .getByLabel("视频 URL", { exact: true })
    .fill("https://example.test/slow.mp4");
  await dialog.locator("summary").click();
  await dialog.locator("textarea").fill('{"Authorization":"temporary"}');
  const pending = new Promise((resolve) => {
    releaseDownload = resolve;
  });
  const started = window.waitForRequest(
    (request) =>
      new URL(request.url()).pathname === "/api/downloads" &&
      request.method() === "POST",
  );
  await window.route("**/api/downloads", async (route) => {
    await pending;
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        id: "late-download",
        name: "slow.mp4",
        kind: "video",
        origin: "download",
        status: "downloading",
        size: 0,
        metadata: {},
      }),
    });
  });
  await dialog.getByRole("button", { name: "开始下载", exact: true }).click();
  await started;
  await dialog.getByRole("button", { name: "关闭", exact: true }).click();
  await window.getByRole("button", { name: "重置", exact: true }).click();
  await window.getByText("已重置", { exact: true }).waitFor();
  const cancelled = window.waitForRequest(
    (request) =>
      new URL(request.url()).pathname === "/api/downloads/late-download/cancel",
  );
  releaseDownload();
  await cancelled;
  await window.getByText("暂无素材", { exact: true }).waitFor();
  assert.equal(
    await window.getByLabel("标题", { exact: true }).inputValue(),
    "",
  );
  assert.equal(
    await window.getByLabel("简介", { exact: true }).inputValue(),
    "",
  );
  assert.equal(await window.locator(".asset-card").count(), 0);
  assert.equal(await window.locator(".tag-chip").count(), 0);
  assert.equal(await window.locator(".cover-picker img").count(), 0);
  assert.equal(
    await window.getByLabel("标题加粗", { exact: true }).isChecked(),
    true,
  );
  assert.equal(
    await window.locator(".source-switch button.active").innerText(),
    "本地文件",
  );
  await window.getByRole("button", { name: "视频直链", exact: true }).click();
  assert.equal(
    await dialog.getByLabel("视频 URL", { exact: true }).inputValue(),
    "",
  );
  assert.equal(await dialog.locator("textarea").inputValue(), "");
  await window.keyboard.press("Escape");
  const empty = {
    id: "current",
    title: "",
    description: "",
    tags: [],
    bold_title: true,
    channel_id: "",
    items: [],
  };
  const snapshot = await request("snapshot");
  assert.deepEqual(snapshot.draft, empty);
  assert.deepEqual(snapshot.tasks, tasksBefore);
  assert.equal((await fs.stat(source)).size, fixture.bytes.length);
  assert.ok((await fs.stat(coverPath)).isFile());
  await window.reload();
  await window
    .getByText("本地服务已连接", { exact: true })
    .waitFor({ timeout: 30000 });
  await window.getByText("暂无素材", { exact: true }).waitFor();
  assert.equal(
    await window.getByLabel("标题", { exact: true }).inputValue(),
    "",
  );
  await app.evaluate(({ BrowserWindow }) =>
    BrowserWindow.getAllWindows()[0].setSize(960, 620),
  );
  await window.screenshot({ path: path.join(output, "cleared.png") });
  await fs.writeFile(
    path.join(output, "result.json"),
    JSON.stringify(
      {
        passed: true,
        draft: snapshot.draft,
        tasksUnchanged: true,
        filesPreserved: true,
        lateDownloadCancelled: true,
      },
      null,
      2,
    ),
  );
  console.log(
    "Reset checks passed: cleared content/media/cover, local source restored, persisted reset, original files/tasks preserved, obsolete download did not return.",
  );
} catch (error) {
  if (window)
    await window
      .screenshot({ path: path.join(output, "failed.png") })
      .catch(() => {});
  throw error;
} finally {
  releaseDownload?.();
  if (window)
    await window.evaluate(() => globalThis.desktop.quit()).catch(() => {});
  await app.close().catch(() => {});
}
