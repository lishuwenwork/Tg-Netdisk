import type { Connection } from "../types";
let connection: Connection | null = null;
export async function initialize() {
  if (window.desktop) connection = await window.desktop.connection();
  else {
    const cached = sessionStorage.getItem("tg-connection");
    if (cached) connection = JSON.parse(cached) as Connection;
  }
  if (!connection) throw new Error("请从桌面客户端启动");
}
export function mediaUrl(id: string): string {
  return connection
    ? `${connection.baseUrl}/api/media/${encodeURIComponent(id)}/file?token=${encodeURIComponent(connection.token)}`
    : "";
}
export async function api<T>(
  route: string,
  method = "GET",
  data?: unknown,
): Promise<T> {
  if (!connection) throw new Error("本地服务未连接");
  let response: Response;
  try {
    response = await fetch(`${connection.baseUrl}/api/${route}`, {
      method,
      headers: {
        Authorization: `Bearer ${connection.token}`,
        "Content-Type": "application/json",
      },
      body: data === undefined ? undefined : JSON.stringify(data),
    });
  } catch {
    throw new Error("无法连接本地服务，请重启应用");
  }
  if (!response.ok) {
    const error = (await response.json().catch(() => ({}))) as {
      message?: string;
    };
    throw new Error(error.message || `请求失败 (${response.status})`);
  }
  return response.json() as Promise<T>;
}
export function subscribe(
  refresh: () => void,
  connected: (state: boolean) => void,
) {
  let socket: WebSocket | undefined,
    timer: ReturnType<typeof setTimeout>,
    disposed = false;
  function connect() {
    if (disposed || !connection) return;
    socket = new WebSocket(
      `${connection.baseUrl.replace("http:", "ws:")}/api/events?token=${encodeURIComponent(connection.token)}`,
    );
    socket.onopen = () => {
      connected(true);
      refresh();
    };
    socket.onmessage = (event) => {
      const value = JSON.parse(String(event.data)) as { type: string };
      if (value.type !== "heartbeat") refresh();
    };
    socket.onerror = () => socket?.close();
    socket.onclose = () => {
      connected(false);
      if (!disposed) timer = setTimeout(connect, 2000);
    };
  }
  connect();
  return () => {
    disposed = true;
    clearTimeout(timer);
    socket?.close();
  };
}
