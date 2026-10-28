import { chromium } from "playwright";
import { spawn } from "node:child_process";
import fs from "node:fs/promises";
import path from "node:path";
import assert from "node:assert/strict";
import { randomBytes } from "node:crypto";
const root = path.resolve(import.meta.dirname, ".."),
  runtime = path.join(root, ".runtime/web-smoke");
await fs.mkdir(path.join(runtime, "media/folder"), { recursive: true });
const password = "test-web-password-" + randomBytes(8).toString("hex");
await fs.writeFile(path.join(runtime, "password"), password);
await fs.writeFile(
  path.join(runtime, "key"),
  randomBytes(32).toString("base64url") + "=",
);
await fs.copyFile(
  path.join(root, ".runtime/中文 样本.mp4"),
  path.join(runtime, "media/folder/中文 视频.mp4"),
);
await fs.copyFile(
  path.join(root, "desktop/icon.png"),
  path.join(runtime, "media/封面.png"),
);
const port = Number(process.env.TG_WEB_TEST_PORT || 18080),
  origin = `http://localhost:${port}`;
const environment = {
  ...process.env,
  TG_MODE: "web",
  TG_DATA_DIR: path.join(runtime, "data"),
  TG_MEDIA_ROOT: path.join(runtime, "media"),
  TG_PUBLIC_ORIGIN: origin,
  TG_FRONTEND_DIR: path.join(root, "dist"),
  TG_WEB_PASSWORD_FILE: path.join(runtime, "password"),
  TG_SECRET_KEY_FILE: path.join(runtime, "key"),
  TG_BIND: "127.0.0.1",
  TG_PORT: String(port),
  PYTHONUTF8: "1",
};
const python = path.join(
  root,
  process.platform === "win32"
    ? "backend/.venv/Scripts/python.exe"
    : "backend/.venv/bin/python",
);
const child = spawn(python, ["-m", "tg_netdisk.web"], {
  cwd: path.join(root, "backend"),
  env: environment,
  stdio: ["ignore", "pipe", "pipe"],
  windowsHide: true,
});
let diagnostics = "";
child.stderr.on("data", (chunk) => {
  diagnostics += chunk.toString();
});
let browser;
try {
  for (let attempt = 0; attempt < 100; attempt++) {
    try {
      if ((await fetch(origin + "/api/health")).ok) break;
    } catch {}
    if (child.exitCode !== null)
      throw new Error("Web server failed: " + diagnostics);
    await new Promise((resolve) => setTimeout(resolve, 200));
  }
  browser = await chromium.launch({ channel: "chrome", headless: true });
  const page = await browser.newPage({
    viewport: { width: 1440, height: 900 },
  });
  const errors = [],
    events = [];
  page.on("pageerror", (error) => errors.push(error.message));
  page.on("websocket", (socket) =>
    socket.on("framereceived", (event) => {
      try {
        events.push(JSON.parse(String(event.payload)).type);
      } catch {}
    }),
  );
  await page.goto(origin);
  await page.getByLabel("访问密码", { exact: true }).fill(password);
  await page.getByRole("button", { name: "登录", exact: true }).click();
  await page.getByText("服务已连接", { exact: true }).waitFor();
  for (
    let attempt = 0;
    attempt < 30 && !events.includes("connected");
    attempt++
  )
    await new Promise((resolve) => setTimeout(resolve, 100));
  assert.ok(
    events.includes("connected"),
    "Authenticated WebSocket did not connect",
  );
  assert.equal(
    await page.getByRole("button", { name: "本地文件", exact: true }).count(),
    0,
  );
  assert.equal(
    await page.getByRole("button", { name: "视频直链", exact: true }).count(),
    0,
  );
  await page
    .getByRole("button", { name: "添加素材", exact: true })
    .first()
    .click();
  await page
    .getByRole("dialog")
    .getByRole("button", { name: "folder 目录" })
    .click();
  await page
    .getByRole("dialog")
    .getByRole("button", { name: /中文 视频.mp4/ })
    .click();
  await page
    .getByRole("dialog")
    .getByRole("button", { name: "添加素材", exact: true })
    .click();
  await page.waitForFunction(
    () => !document.querySelector(".frame-controls .btn")?.disabled,
    null,
    { timeout: 30000 },
  );
  await page.getByRole("button", { name: "选择图片", exact: true }).click();
  await page
    .getByRole("dialog")
    .getByRole("button", { name: /封面.png/ })
    .click();
  await page
    .getByRole("dialog")
    .getByRole("button", { name: "选择图片", exact: true })
    .click();
  await page.getByAltText("视频封面", { exact: true }).waitFor();
  await page.locator('.player-controls button[aria-label="播放"]').click();
  await page.waitForFunction(
    () => document.querySelector("video")?.currentTime > 0.15,
  );
  await page.locator('.player-controls button[aria-label="暂停"]').click();
  await page.getByRole("button", { name: "截取图片", exact: true }).click();
  await page.getByAltText("选中的实际视频帧").waitFor();
  await page.getByRole("button", { name: "设为视频封面", exact: true }).click();
  await page.getByText("视频封面已设置", { exact: true }).waitFor();
  await page.getByRole("button", { name: "添加到相册", exact: true }).click();
  await page.getByText("图片已加入相册", { exact: true }).waitFor();
  await page
    .getByRole("dialog")
    .getByRole("button", { name: "关闭", exact: true })
    .click();
  await page.getByRole("button", { name: "保存草稿", exact: true }).click();
  await page.screenshot({ path: path.join(runtime, "web-workspace.png") });
  await page.getByRole("button", { name: "设置", exact: true }).click();
  assert.equal(await page.getByLabel("关闭窗口", { exact: true }).count(), 0);
  assert.equal(
    await page.getByRole("button", { name: "打开日志", exact: true }).count(),
    0,
  );
  await page.getByRole("button", { name: "退出工作台", exact: true }).click();
  await page.getByLabel("访问密码", { exact: true }).waitFor();
  assert.equal(
    (await page.request.get(origin + "/api/snapshot")).status(),
    401,
  );
  assert.deepEqual(errors, []);
  await fs.writeFile(
    path.join(runtime, "result.json"),
    JSON.stringify({ passed: true, errors }, null, 2),
  );
  console.log(
    "Web browser check passed: cookie login, server files, playback, frames, cover, album, draft, settings and logout.",
  );
} catch (error) {
  console.error(diagnostics);
  throw error;
} finally {
  await browser?.close();
  child.kill();
}
