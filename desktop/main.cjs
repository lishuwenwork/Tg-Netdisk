const {
  app,
  BrowserWindow,
  dialog,
  ipcMain,
  protocol,
  net,
  shell,
  Tray,
  Menu,
  nativeImage,
} = require("electron");
const { spawn } = require("node:child_process");
const { randomBytes } = require("node:crypto");
const path = require("node:path");
const fs = require("node:fs");
const { pathToFileURL } = require("node:url");

protocol.registerSchemesAsPrivileged([
  {
    scheme: "app",
    privileges: {
      standard: true,
      secure: true,
      supportFetchAPI: true,
      corsEnabled: true,
      stream: true,
    },
  },
]);
const dev = !app.isPackaged && process.env.TG_DEV === "1";
const project = path.resolve(__dirname, "..");
const token = randomBytes(32).toString("hex");
let win,
  child,
  tray,
  port,
  quitting = false,
  quitPrompt = false;
let pendingFlush;
const dataDir =
  process.env.TG_DATA_DIR || path.join(app.getPath("appData"), "Tg Netdisk");
app.setPath("userData", dataDir);
fs.mkdirSync(path.join(dataDir, "chromium"), { recursive: true });
app.setPath("sessionData", path.join(dataDir, "chromium"));
if (!app.requestSingleInstanceLock()) app.quit();
app.on("second-instance", () => {
  win?.show();
  win?.focus();
});

function ipc(name, handler) {
  ipcMain.handle(name, (event, ...args) => {
    const url = event.senderFrame?.url || "";
    if (
      event.sender !== win?.webContents ||
      event.senderFrame !== win.webContents.mainFrame ||
      !(dev
        ? url.startsWith("http://127.0.0.1:5173/")
        : url.startsWith("app://bundle/"))
    ) {
      throw new Error("Untrusted IPC sender");
    }
    return handler(...args);
  });
}
async function backendRequest(route) {
  const response = await fetch(`http://127.0.0.1:${port}/api/${route}`, {
    headers: { Authorization: `Bearer ${token}` },
    signal: AbortSignal.timeout(3000),
  });
  if (!response.ok) throw new Error("Backend request failed");
  return response.json();
}
async function startBackend() {
  const executable = app.isPackaged
    ? path.join(process.resourcesPath, "backend", "tg-netdisk-backend.exe")
    : path.join(project, "backend", ".venv", "Scripts", "python.exe");
  const args = app.isPackaged ? [] : ["-m", "tg_netdisk"];
  child = spawn(executable, args, {
    cwd: app.isPackaged ? process.resourcesPath : path.join(project, "backend"),
    env: {
      ...process.env,
      TG_RUNTIME_TOKEN: token,
      TG_DATA_DIR: dataDir,
      PYTHONUTF8: "1",
    },
    windowsHide: true,
    stdio: ["pipe", "pipe", "pipe"],
  });
  return new Promise((resolve, reject) => {
    let buffer = "";
    const timeout = setTimeout(
      () => reject(new Error("后端启动超时，请查看日志")),
      60000,
    );
    child.stdout.on("data", async (chunk) => {
      buffer += chunk.toString();
      let end;
      while ((end = buffer.indexOf("\n")) !== -1) {
        const line = buffer.slice(0, end);
        buffer = buffer.slice(end + 1);
        try {
          const message = JSON.parse(line);
          if (message.event === "ready") {
            port = message.port;
            if ((await backendRequest("health")).ready) {
              clearTimeout(timeout);
              resolve();
            }
          }
        } catch {
          /* Non-protocol output is never forwarded to the renderer. */
        }
      }
    });
    child.stderr.on("data", (chunk) => {
      // Uvicorn warnings contain no request URLs; business logging is separately redacted.
      fs.mkdirSync(path.join(dataDir, "logs"), { recursive: true });
      const log = path.join(dataDir, "logs", "startup.log");
      if (fs.existsSync(log) && fs.statSync(log).size > 2_000_000)
        fs.writeFileSync(log, "");
      fs.appendFileSync(log, chunk);
    });
    child.once("error", (err) => {
      clearTimeout(timeout);
      reject(err);
    });
    child.once("exit", (code) => {
      clearTimeout(timeout);
      if (!port) reject(new Error(`后端启动失败 (${code})`));
      else if (!quitting)
        win?.webContents.send("backend-status", { ready: false });
    });
  });
}
async function stopBackend() {
  if (!child || child.exitCode !== null) return;
  await new Promise((resolve) => {
    const timeout = setTimeout(() => {
      child.kill();
      resolve();
    }, 12000);
    child.once("exit", () => {
      clearTimeout(timeout);
      resolve();
    });
    child.stdin.write("shutdown\n");
  });
}
async function requestQuit() {
  if (quitPrompt || quitting) return;
  quitPrompt = true;
  let status = { active: [], downloads: [] };
  try {
    status = await backendRequest("status");
  } catch {}
  const busy = status.active.length + status.downloads.length > 0;
  if (busy) {
    const result = await dialog.showMessageBox(win, {
      type: "question",
      title: "退出 Tg Netdisk",
      message: "仍有任务正在执行",
      detail: "退出将停止当前任务。发布已开始的任务需要核对频道。",
      buttons: ["后台运行", "取消任务并退出", "返回"],
      defaultId: 0,
      cancelId: 2,
    });
    if (result.response === 0) {
      win.hide();
      quitPrompt = false;
      return;
    }
    if (result.response === 2) {
      quitPrompt = false;
      return;
    }
  }
  if (win && !win.isDestroyed()) {
    const flushed = await new Promise((resolve) => {
      const nonce = randomBytes(16).toString("hex");
      const timeout = setTimeout(() => {
        pendingFlush = null;
        resolve(false);
      }, 5000);
      pendingFlush = {
        nonce,
        complete: (success) => {
          clearTimeout(timeout);
          pendingFlush = null;
          resolve(success);
        },
      };
      win.webContents.send("flush-draft", nonce);
    });
    if (!flushed) {
      const result = await dialog.showMessageBox(win, {
        type: "warning",
        title: "草稿未保存",
        message: "草稿保存失败",
        detail: "退出可能丢失最近的编辑。",
        buttons: ["返回", "仍然退出"],
        defaultId: 0,
        cancelId: 0,
      });
      if (result.response === 0) {
        quitPrompt = false;
        return;
      }
    }
  }
  quitting = true;
  await stopBackend();
  tray?.destroy();
  app.quit();
}
async function createWindow() {
  win = new BrowserWindow({
    width: 1460,
    height: 940,
    minWidth: 960,
    minHeight: 620,
    title: "Tg Netdisk",
    icon: path.join(__dirname, "icon.png"),
    backgroundColor: "#111315",
    show: false,
    autoHideMenuBar: true,
    webPreferences: {
      preload: path.join(__dirname, "preload.cjs"),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
      webSecurity: true,
      backgroundThrottling: false,
    },
  });
  win.webContents.setWindowOpenHandler(() => ({ action: "deny" }));
  win.webContents.on("will-navigate", (event) => event.preventDefault());
  win.webContents.session.setPermissionRequestHandler((_, __, callback) =>
    callback(false),
  );
  win.on("close", async (event) => {
    if (quitting) return;
    event.preventDefault();
    try {
      if ((await backendRequest("settings")).close_behavior === "hide") {
        win.hide();
        return;
      }
    } catch {}
    await requestQuit();
  });
  win.once("ready-to-show", () => win.show());
  if (dev) await win.loadURL("http://127.0.0.1:5173");
  else await win.loadURL("app://bundle/index.html");
  tray = new Tray(
    nativeImage
      .createFromPath(path.join(__dirname, "icon.png"))
      .resize({ width: 32, height: 32 }),
  );
  tray.setToolTip("Tg Netdisk");
  tray.setContextMenu(
    Menu.buildFromTemplate([
      { label: "打开 Tg Netdisk", click: () => win.show() },
      { label: "退出", click: requestQuit },
    ]),
  );
  tray.on("double-click", () => win.show());
}
app.whenReady().then(async () => {
  protocol.handle("app", (request) => {
    const url = new URL(request.url);
    if (url.host !== "bundle")
      return new Response("Forbidden", { status: 403 });
    let relative;
    try {
      relative = decodeURIComponent(url.pathname).replace(/^\/+/, "");
    } catch {
      return new Response("Bad path", { status: 400 });
    }
    const base = path.join(project, "dist");
    const target = path.resolve(base, relative || "index.html");
    const check = path.relative(base, target);
    if (check.startsWith("..") || path.isAbsolute(check))
      return new Response("Forbidden", { status: 403 });
    return net.fetch(pathToFileURL(target).toString());
  });
  ipc("connection", () => ({ baseUrl: `http://127.0.0.1:${port}`, token }));
  ipc("flush-complete", (nonce, success) => {
    if (pendingFlush?.nonce === nonce) pendingFlush.complete(success === true);
  });
  ipc(
    "choose-files",
    async () =>
      (
        await dialog.showOpenDialog(win, {
          properties: ["openFile", "multiSelections"],
          filters: [
            {
              name: "媒体",
              extensions: [
                "mp4",
                "m4v",
                "mov",
                "webm",
                "mkv",
                "avi",
                "png",
                "jpg",
                "jpeg",
                "webp",
              ],
            },
          ],
        })
      ).filePaths,
  );
  ipc(
    "choose-directory",
    async () =>
      (await dialog.showOpenDialog(win, { properties: ["openDirectory"] }))
        .filePaths[0] || "",
  );
  ipc("show-logs", () => shell.openPath(path.join(dataDir, "logs")));
  ipc("minimize", () => win.minimize());
  ipc("quit", requestQuit);
  try {
    await startBackend();
    await createWindow();
  } catch (error) {
    dialog.showErrorBox("Tg Netdisk 启动失败", String(error.message));
    quitting = true;
    await stopBackend();
    app.quit();
  }
});
app.on("before-quit", (event) => {
  if (!quitting) {
    event.preventDefault();
    void requestQuit();
  }
});
app.on("window-all-closed", () => {});
