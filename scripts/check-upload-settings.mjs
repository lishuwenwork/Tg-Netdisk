import { _electron as electron } from "playwright";
import assert from "node:assert/strict";
import fs from "node:fs/promises";
import path from "node:path";

const root = path.resolve(import.meta.dirname, "..");
const output = path.join(root, ".runtime/upload-settings-check");
await fs.mkdir(output, { recursive: true });
const dataDirectory = await fs.mkdtemp(path.join(output, "data-"));
const environment = { ...process.env, TG_DATA_DIR: dataDirectory };
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
  const errors = [];
  window.on("pageerror", (error) => errors.push(String(error)));
  await window
    .getByText("本地服务已连接", { exact: true })
    .waitFor({ timeout: 30000 });
  await window.getByRole("button", { name: "设置", exact: true }).click();
  const concurrency = window.getByRole("combobox", {
    name: "上传并发数",
    exact: true,
  });
  assert.equal(await concurrency.inputValue(), "4");
  assert.deepEqual(
    await concurrency
      .locator("option")
      .evaluateAll((options) => options.map((option) => option.value)),
    Array.from({ length: 10 }, (_, index) => String(index + 1)),
  );
  // Exercise the real settings API before installing proxy-only UI mocks below.
  for (const value of ["1", "10"]) {
    await concurrency.selectOption(value);
    const saving = window.waitForResponse(
      (response) =>
        response.url().endsWith("/api/settings") &&
        response.request().method() === "PUT",
    );
    await window.getByRole("button", { name: "保存设置", exact: true }).click();
    const response = await saving;
    assert.equal(response.status(), 200);
    assert.equal((await response.json()).upload_concurrency, Number(value));
    await window.waitForFunction(() => {
      const button = [...document.querySelectorAll("button")].find((item) =>
        item.textContent.includes("保存设置"),
      );
      return button && !button.disabled;
    });
  }
  await window.reload();
  await window.getByText("本地服务已连接", { exact: true }).waitFor();
  await window.getByRole("button", { name: "设置", exact: true }).click();
  assert.equal(await concurrency.inputValue(), "10");
  await window.screenshot({ path: path.join(output, "concurrency.png") });
  // Mock only UI proxy values; never save test proxies or credentials into the OS credential store.
  let proxies = {
    telegram_proxy: "socks5://example:pass@127.0.0.1:10808",
    download_proxy: "http://127.0.0.1:7890",
  };
  await window.route("**/api/settings/proxies", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(proxies),
    }),
  );
  await window.route("**/api/settings", async (route) => {
    if (route.request().method() !== "PUT") return route.continue();
    const data = route.request().postDataJSON();
    proxies = {
      telegram_proxy: data.telegram_proxy ?? proxies.telegram_proxy,
      download_proxy: data.download_proxy ?? proxies.download_proxy,
    };
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: "{}",
    });
  });
  await window.locator(".account-button").click();
  const telegram = window.getByLabel("Telegram 代理", { exact: true });
  const download = window.getByLabel("下载代理", { exact: true });
  await window.waitForFunction(() =>
    document
      .querySelector('input[placeholder="socks5://127.0.0.1:10808"]')
      ?.value.includes("example:pass"),
  );
  assert.equal(await telegram.getAttribute("type"), "text");
  assert.equal(await download.getAttribute("type"), "text");
  assert.equal(
    await window.getByLabel("API Hash", { exact: true }).getAttribute("type"),
    "password",
  );
  assert.equal(await telegram.inputValue(), proxies.telegram_proxy);
  await telegram.fill("socks5://127.0.0.1:2080");
  await download.fill("http://127.0.0.1:3080");
  await window.getByRole("button", { name: "保存设置", exact: true }).click();
  await window.getByText("设置已保存", { exact: true }).waitFor();
  assert.equal(await telegram.inputValue(), "socks5://127.0.0.1:2080");
  await window.getByRole("button", { name: "新建发布", exact: true }).click();
  await window.locator(".account-button").click();
  await window.waitForFunction(
    () =>
      document.querySelector('input[placeholder="socks5://127.0.0.1:10808"]')
        ?.value === "socks5://127.0.0.1:2080",
  );
  assert.equal(await download.inputValue(), "http://127.0.0.1:3080");
  await window.getByRole("button", { name: "上传诊断", exact: true }).click();
  const dialog = window.locator("dialog[open]");
  await dialog.getByText("已启用 · cryptg", { exact: true }).waitFor();
  await dialog.getByText("512 KiB", { exact: true }).waitFor();
  await dialog.getByText("10", { exact: true }).waitFor();
  await window.screenshot({ path: path.join(output, "diagnostics.png") });
  assert.equal(errors.length, 0, errors.join("\n"));
  await fs.writeFile(
    path.join(output, "result.json"),
    JSON.stringify(
      {
        passed: true,
        proxyPlainText: true,
        proxyRestore: true,
        apiHashMasked: true,
        nativeCryptoEnabled: true,
        concurrencyDefault: 4,
        concurrencyRange: [1, 10],
        concurrencySavedAndRestored: 10,
        diagnosticsUsesSavedConcurrency: true,
        errors,
      },
      null,
      2,
    ),
  );
  console.log(
    "Upload settings checks passed: concurrency default/range/save/restore, readable proxy fields, API Hash masking, native crypto and configured pipeline diagnostics.",
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
