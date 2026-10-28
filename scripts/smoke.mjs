import { _electron as electron } from "playwright";
import fs from "node:fs/promises";
import path from "node:path";
import assert from "node:assert/strict";
import { build } from "esbuild";
const project = path.resolve(import.meta.dirname, "..");
const runtime = path.join(project, ".runtime");
await fs.mkdir(runtime, { recursive: true });
const environment = {
  ...process.env,
  TG_DATA_DIR: path.join(runtime, "smoke-data"),
};
delete environment.ELECTRON_RUN_AS_NODE;
delete environment.TG_DEV;
const desktop = await electron.launch({
  ...(process.env.TG_SMOKE_EXE
    ? { executablePath: process.env.TG_SMOKE_EXE, args: [] }
    : { args: [project] }),
  env: environment,
  timeout: 60000,
});
let window;
const diagnostics = [];
try {
  window = await desktop.firstWindow({ timeout: 60000 });
  const errors = [];
  window.on("pageerror", (error) => errors.push(String(error)));
  window.on("console", (message) => {
    if (["error", "warning"].includes(message.type()))
      diagnostics.push(
        message.text().replace(/token=[A-Za-z0-9_-]+/g, "token=[redacted]"),
      );
  });
  await window
    .getByText("本地服务已连接", { exact: true })
    .waitFor({ timeout: 30000 });
  await window.screenshot({ path: path.join(runtime, "workspace-empty.png") });
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
  assert.equal((await request("health")).ready, true);
  const fixtureBundle = await build({
    entryPoints: [path.join(project, "scripts/fixture.ts")],
    bundle: true,
    write: false,
    format: "iife",
    globalName: "__fixtures",
    platform: "browser",
  });
  const fixture = await window.evaluate(
    fixtureBundle.outputFiles[0].text + "\n__fixtures.generate()",
  );
  const fixturePath = path.join(
    runtime,
    fixture.mime.startsWith("video/mp4") ? "中文 样本.mp4" : "中文 样本.webm",
  );
  await fs.writeFile(fixturePath, Buffer.from(fixture.bytes));
  const registered = await request("media/register", "POST", {
    paths: [fixturePath],
  });
  assert.equal(registered.assets.length, 1);
  const id = registered.assets[0].id;
  await request("drafts/current", "PUT", {
    id: "current",
    title: "本地样本",
    description: "",
    tags: ["#4k"],
    bold_title: true,
    channel_id: "",
    items: [{ media_id: id, cover_id: null }],
  });
  await window.reload();
  await window
    .getByText("本地服务已连接", { exact: true })
    .waitFor({ timeout: 30000 });
  await window.getByRole("button", { name: "截取图片", exact: true }).waitFor();
  await window.waitForFunction(
    () => !document.querySelector(".frame-controls .btn")?.disabled,
    null,
    { timeout: 30000 },
  );
  await window.getByRole("button", { name: "后一帧", exact: true }).click();
  await window.waitForFunction(
    () => Number(document.querySelector(".time-input")?.value) > 0,
    null,
    { timeout: 5000 },
  );
  await window.getByRole("button", { name: "截取图片", exact: true }).click();
  await window.getByAltText("选中的实际视频帧").waitFor();
  await window
    .getByRole("button", { name: "设为视频封面", exact: true })
    .click();
  await window.getByText("视频封面已设置", { exact: true }).waitFor();
  await window.getByRole("button", { name: "添加到相册", exact: true }).click();
  await window.getByText("图片已加入相册", { exact: true }).waitFor();
  await window
    .getByRole("dialog")
    .getByRole("button", { name: "关闭", exact: true })
    .click();
  await window.getByRole("button", { name: "保存草稿", exact: true }).click();
  const snapshot = await request("snapshot");
  assert.equal(snapshot.draft.items.length, 2);
  assert.ok(snapshot.draft.items[0].cover_id);
  assert.equal(
    snapshot.media.find((a) => a.id === id).metadata.video_decodable,
    true,
  );
  await window.screenshot({ path: path.join(runtime, "workspace-media.png") });
  await window.getByRole("button", { name: "任务队列", exact: true }).click();
  await window.getByText("暂无任务", { exact: true }).waitFor();
  await window.getByRole("button", { name: "历史记录", exact: true }).click();
  await window.getByText("暂无记录", { exact: true }).waitFor();
  await window.getByRole("button", { name: "设置", exact: true }).click();
  await window.getByRole("heading", { name: "常规", exact: true }).waitFor();
  await window.getByLabel("主题", { exact: true }).selectOption("light");
  await window.getByRole("button", { name: "保存设置", exact: true }).click();
  await window.getByText("设置已保存", { exact: true }).waitFor();
  await window.getByRole("button", { name: "新建发布", exact: true }).click();
  await window.screenshot({ path: path.join(runtime, "workspace-light.png") });
  await desktop.evaluate(({ BrowserWindow }) =>
    BrowserWindow.getAllWindows()[0].setSize(1280, 720),
  );
  await window.screenshot({ path: path.join(runtime, "workspace-1280.png") });
  assert.equal(errors.length, 0, errors.join("\n"));
  await fs.writeFile(
    path.join(runtime, "smoke-result.json"),
    JSON.stringify(
      {
        passed: true,
        mime: fixture.mime,
        metadata: snapshot.media.find((a) => a.id === id).metadata,
        errors,
      },
      null,
      2,
    ),
  );
  console.log(
    "Desktop smoke passed: local media, decoding, exact frame, cover, album, persistence, navigation, theme and 1280x720.",
  );
} catch (error) {
  if (window)
    await window
      .screenshot({ path: path.join(runtime, "smoke-failed.png") })
      .catch(() => {});
  console.log(diagnostics.join("\n"));
  throw error;
} finally {
  if (window)
    await window.evaluate(() => globalThis.desktop.quit()).catch(() => {});
  await desktop.close().catch(() => {});
}
