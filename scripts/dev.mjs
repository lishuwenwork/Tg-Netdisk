import { spawn } from "node:child_process";
import { createRequire } from "node:module";
const require = createRequire(import.meta.url);
const vite = spawn(
  process.execPath,
  ["node_modules/vite/bin/vite.js", "--config", "vite.config.ts"],
  { stdio: "inherit", windowsHide: true },
);
let desktop;
const environment = { ...process.env, TG_DEV: "1" };
delete environment.ELECTRON_RUN_AS_NODE;
for (let i = 0; i < 80; i++) {
  try {
    await fetch("http://127.0.0.1:5173");
    break;
  } catch {
    await new Promise((resolve) => setTimeout(resolve, 250));
  }
}
desktop = spawn(require("electron"), ["."], {
  env: environment,
  stdio: "inherit",
  windowsHide: true,
});
desktop.on("exit", (code) => {
  vite.kill();
  process.exit(code || 0);
});
process.on("SIGINT", () => {
  desktop.kill();
  vite.kill();
  process.exit();
});
