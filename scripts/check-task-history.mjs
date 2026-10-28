import { _electron as electron } from "playwright";
import { execFile } from "node:child_process";
import { promisify } from "node:util";
import assert from "node:assert/strict";
import fs from "node:fs/promises";
import path from "node:path";

const root = path.resolve(import.meta.dirname, "..");
const output = path.join(root, ".runtime", "task-history-check");
const data = path.join(output, "data");
await fs.mkdir(output, { recursive: true });
const run = promisify(execFile);
const fixtures = (mode) =>
  run(
    path.join(root, "backend/.venv/Scripts/python.exe"),
    [
      path.join(root, "scripts/task-fixtures.py"),
      "--data-dir",
      data,
      "--mode",
      mode,
    ],
    { cwd: root, windowsHide: true, env: { ...process.env, PYTHONUTF8: "1" } },
  );
const environment = { ...process.env, TG_DATA_DIR: data };
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
try {
  window = await app.firstWindow({ timeout: 60000 });
  await window
    .getByText("本地服务已连接", { exact: true })
    .waitFor({ timeout: 30000 });
  const errors = [];
  window.on("pageerror", (error) => errors.push(String(error)));
  const connection = await window.evaluate(() =>
    globalThis.desktop.connection(),
  );
  const request = (route, method = "GET") =>
    fetch(`${connection.baseUrl}/api/${route}`, {
      method,
      headers: { Authorization: `Bearer ${connection.token}` },
    });
  await fixtures("seed");
  await window.getByRole("button", { name: "任务队列", exact: true }).click();
  await window.getByRole("button", { name: "刷新", exact: true }).click();
  const card = (title) =>
    window
      .locator(".task-card")
      .filter({
        has: window.getByRole("heading", { name: title, exact: true }),
      });
  await card("正在上传")
    .getByText("剩余时间：约 1 分 30 秒", { exact: true })
    .waitFor();
  await card("排队任务")
    .getByText("剩余时间：等待开始", { exact: true })
    .waitFor();
  await card("准备任务")
    .getByText("剩余时间：计算中", { exact: true })
    .waitFor();
  await card("限流任务")
    .getByText("剩余时间：等待重试", { exact: true })
    .waitFor();
  await card("发布任务")
    .getByText("剩余时间：等待发布结果", { exact: true })
    .waitFor();
  await window.screenshot({ path: path.join(output, "queue.png") });
  const blocked = await request("tasks/fixture-queued", "DELETE");
  assert.equal(blocked.status, 400);
  assert.equal((await blocked.json()).code, "TASK_ACTIVE");
  await window.getByRole("button", { name: "历史记录", exact: true }).click();
  await card("已发布记录").waitFor();
  await window.screenshot({ path: path.join(output, "history.png") });
  const dialog = window.locator("dialog[open]");
  await card("已发布记录")
    .getByRole("button", { name: "删除", exact: true })
    .click();
  await dialog.getByRole("button", { name: "取消", exact: true }).click();
  assert.equal(await card("已发布记录").count(), 1);
  await card("已发布记录")
    .getByRole("button", { name: "详情", exact: true })
    .click();
  await dialog.getByRole("button", { name: "删除记录", exact: true }).click();
  await dialog.getByRole("button", { name: "删除记录", exact: true }).click();
  await card("已发布记录").waitFor({ state: "detached" });
  for (const title of ["失败记录", "取消记录"]) {
    await card(title)
      .getByRole("button", { name: "删除", exact: true })
      .click();
    await dialog.getByRole("button", { name: "删除记录", exact: true }).click();
    await card(title).waitFor({ state: "detached" });
  }
  await card("待确认记录")
    .getByRole("button", { name: "删除", exact: true })
    .click();
  await dialog
    .getByText("结果仍待确认，删除后将失去本地核对信息。", { exact: true })
    .waitFor();
  await window.screenshot({ path: path.join(output, "delete-unknown.png") });
  const confirmation = window.waitForRequest(
    (req) =>
      req.method() === "DELETE" &&
      req.url().includes("fixture-unknown?confirm_unknown=true"),
  );
  await dialog.getByRole("button", { name: "仍然删除", exact: true }).click();
  await confirmation;
  await window.getByText("暂无记录", { exact: true }).waitFor();
  for (const key of ["success", "failed", "cancelled", "unknown"])
    assert.equal((await request(`tasks/fixture-${key}`)).status, 404);
  assert.ok((await fs.stat(path.join(output, "original.mp4"))).size > 0);
  await window.reload();
  await window
    .getByText("本地服务已连接", { exact: true })
    .waitFor({ timeout: 30000 });
  await window.getByRole("button", { name: "历史记录", exact: true }).click();
  await window.getByText("暂无记录", { exact: true }).waitFor();
  assert.equal(errors.length, 0, errors.join("\n"));
  await fs.writeFile(
    path.join(output, "result.json"),
    JSON.stringify(
      {
        passed: true,
        etaStates: true,
        deletionPersisted: true,
        activeTaskProtected: true,
        originalFilePreserved: true,
        errors,
      },
      null,
      2,
    ),
  );
  console.log(
    "Queue/history checks passed: ETA states, history deletion from row/detail, cancel, unknown confirmation, persistence and active-task/file protection.",
  );
} catch (error) {
  if (window)
    await window
      .screenshot({ path: path.join(output, "failed.png") })
      .catch(() => {});
  throw error;
} finally {
  await fixtures("finish").catch(() => {});
  if (window)
    await window.evaluate(() => globalThis.desktop.quit()).catch(() => {});
  await app.close().catch(() => {});
}
