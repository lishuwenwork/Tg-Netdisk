import { _electron as electron } from "playwright";
import assert from "node:assert/strict";
import fs from "node:fs/promises";
import path from "node:path";

const root = path.resolve(import.meta.dirname, "..");
const output = path.join(root, ".runtime", "modal-check");
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
const measurements = [];
try {
  window = await app.firstWindow({ timeout: 60000 });
  await window
    .getByText("本地服务已连接", { exact: true })
    .waitFor({ timeout: 30000 });
  const dialog = window.locator("dialog[open]");
  async function geometry() {
    return dialog.evaluate((element) => {
      const box = element.getBoundingClientRect();
      return {
        left: box.left,
        top: box.top,
        width: box.width,
        height: box.height,
        viewportWidth: innerWidth,
        viewportHeight: innerHeight,
      };
    });
  }
  async function centered(name) {
    await dialog.waitFor({ state: "visible" });
    await window.waitForFunction(
      () => {
        const element = document.querySelector("dialog[open]");
        if (!element) return false;
        const box = element.getBoundingClientRect();
        return (
          Math.abs(box.left + box.width / 2 - innerWidth / 2) < 2 &&
          Math.abs(box.top + box.height / 2 - innerHeight / 2) < 2
        );
      },
      null,
      { timeout: 3000 },
    );
    measurements.push({ name, ...(await geometry()) });
  }
  async function inBounds() {
    await window.waitForFunction(
      () => {
        const box = document
          .querySelector("dialog[open]")
          ?.getBoundingClientRect();
        return (
          box &&
          box.left >= 11 &&
          box.top >= 11 &&
          box.right <= innerWidth - 11 &&
          box.bottom <= innerHeight - 11
        );
      },
      null,
      { timeout: 3000 },
    );
  }
  async function drag(dx, dy) {
    const titlebar = await dialog.locator("header").boundingBox();
    assert.ok(titlebar);
    const x = titlebar.x + 80,
      y = titlebar.y + titlebar.height / 2;
    await window.mouse.move(x, y);
    await window.mouse.down();
    await window.mouse.move(x + dx, y + dy, { steps: 10 });
    await window.mouse.up();
  }
  await window.getByRole("button", { name: "视频直链", exact: true }).click();
  await centered("URL dialog");
  const before = await geometry();
  await drag(90, 55);
  const after = await geometry();
  assert.ok(
    Math.abs(after.left - before.left - 90) < 2,
    "Titlebar horizontal dragging failed",
  );
  assert.ok(
    Math.abs(after.top - before.top - 55) < 2,
    "Titlebar vertical dragging failed",
  );
  await dialog
    .getByLabel("视频 URL", { exact: true })
    .fill("https://example.com/video.mp4");
  await window.screenshot({ path: path.join(output, "dragged.png") });
  await window.keyboard.press("Escape");
  await dialog.waitFor({ state: "hidden" });
  await window.getByRole("button", { name: "视频直链", exact: true }).click();
  await centered("URL reopened");
  await drag(-3000, -3000);
  await inBounds();
  await drag(3000, 3000);
  await inBounds();
  await app.evaluate(({ BrowserWindow }) =>
    BrowserWindow.getAllWindows()[0].setSize(960, 620),
  );
  await inBounds();
  for (let i = 0; i < 8; i++) await window.keyboard.press("Tab");
  assert.equal(
    await dialog.evaluate((element) =>
      element.contains(document.activeElement),
    ),
    true,
    "Modal focus trap was lost",
  );
  await dialog.getByRole("button", { name: "关闭", exact: true }).click();
  await window.getByRole("button", { name: "帮助", exact: true }).click();
  await centered("Help at small window size");
  await window.screenshot({ path: path.join(output, "centered.png") });
  await window.mouse.click(5, 5);
  await dialog.waitFor({ state: "hidden" });
  await window
    .getByRole("button", { name: "打开发布设置", exact: true })
    .click();
  await window.getByRole("button", { name: "展开预览", exact: true }).click();
  await centered("Publish preview");
  await dialog.getByRole("button", { name: "返回编辑", exact: true }).click();
  await window
    .getByRole("button", { name: "关闭发布设置", exact: true })
    .click();
  await window.getByRole("button", { name: "帮助", exact: true }).click();
  await centered("Help before width change");
  await dialog.evaluate((element) => element.classList.add("wide"));
  await centered("Wide modal");
  await drag(70, 40);
  await inBounds();
  await fs.writeFile(
    path.join(output, "result.json"),
    JSON.stringify({ passed: true, measurements }, null, 2),
  );
  console.log(
    "Modal checks passed: centered opening/reopening, titlebar drag, viewport bounds, resize, focus, Escape, close button and backdrop.",
  );
} catch (error) {
  if (window)
    await window
      .screenshot({ path: path.join(output, "failed.png") })
      .catch(() => {});
  throw error;
} finally {
  if (window)
    await window.evaluate(() => globalThis.desktop.quit()).catch(() => {});
  await app.close().catch(() => {});
}
