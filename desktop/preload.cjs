const { contextBridge, ipcRenderer, webUtils } = require("electron");
contextBridge.exposeInMainWorld("desktop", {
  connection: () => ipcRenderer.invoke("connection"),
  chooseFiles: () => ipcRenderer.invoke("choose-files"),
  chooseDirectory: () => ipcRenderer.invoke("choose-directory"),
  droppedPaths: (files) =>
    Array.from(files)
      .map((file) => webUtils.getPathForFile(file))
      .filter(Boolean),
  showLogs: () => ipcRenderer.invoke("show-logs"),
  minimize: () => ipcRenderer.invoke("minimize"),
  quit: () => ipcRenderer.invoke("quit"),
  onFlushDraft: (callback) => {
    const listener = async (_, nonce) => {
      let success = true;
      try {
        await callback();
      } catch {
        success = false;
      }
      await ipcRenderer.invoke("flush-complete", nonce, success);
    };
    ipcRenderer.on("flush-draft", listener);
    return () => ipcRenderer.removeListener("flush-draft", listener);
  },
  onBackendStatus: (callback) => {
    const listener = (_, value) => callback(value);
    ipcRenderer.on("backend-status", listener);
    return () => ipcRenderer.removeListener("backend-status", listener);
  },
});
