import { existsSync } from "node:fs";
import path from "node:path";
import { spawn } from "node:child_process";

const root = path.resolve(import.meta.dirname, "..");
const python = path.join(
  root,
  "backend",
  ".venv",
  process.platform === "win32" ? "Scripts/python.exe" : "bin/python",
);
if (!existsSync(python)) {
  console.error(
    "项目 Python 环境尚未初始化，请先执行 uv sync --project backend --group dev --locked。",
  );
  process.exitCode = 1;
} else {
  const child = spawn(
    python,
    [
      "-X",
      "utf8",
      path.join(root, "scripts/run-web.py"),
      ...process.argv.slice(2),
    ],
    {
      cwd: root,
      env: { ...process.env, PYTHONUTF8: "1" },
      stdio: "inherit",
      windowsHide: true,
    },
  );
  child.on("error", (error) => {
    console.error(`Web 服务启动失败：${error.message}`);
    process.exitCode = 1;
  });
  child.on("exit", (code, signal) => {
    process.exitCode = code ?? (signal === "SIGINT" ? 130 : 1);
  });
  // Keyboard Ctrl+C reaches both processes in the foreground console. Wait for Python cleanup.
  process.on("SIGINT", () => {});
  process.on("SIGTERM", () => child.kill("SIGTERM"));
}
