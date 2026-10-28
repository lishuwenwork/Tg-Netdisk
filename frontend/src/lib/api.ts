import type { Connection } from "../types";
let connection: Connection | null = null;
export function webMode() {
  return typeof window !== "undefined" && !window.desktop;
}
export async function initialize() {
  if (window.desktop) connection = await window.desktop.connection();
  else connection = { baseUrl: window.location.origin, token: "" };
}
export function mediaUrl(id: string): string {
  return connection
    ? `${connection.baseUrl}/api/media/${encodeURIComponent(id)}/file${connection.token ? `?token=${encodeURIComponent(connection.token)}` : ""}`
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
      credentials: "same-origin",
      headers: {
        ...(connection.token
          ? { Authorization: `Bearer ${connection.token}` }
          : {}),
        "Content-Type": "application/json",
      },
      body: data === undefined ? undefined : JSON.stringify(data),
    });
  } catch {
    throw new Error("无法连接服务，请检查网络");
  }
  if (!response.ok) {
    if (response.status === 401 && webMode())
      window.dispatchEvent(new Event("tg-session-expired"));
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
    const url = new URL("/api/events", connection.baseUrl);
    url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
    if (connection.token) url.searchParams.set("token", connection.token);
    socket = new WebSocket(url);
    socket.onopen = () => {
      connected(true);
      refresh();
    };
    socket.onmessage = (event) => {
      const value = JSON.parse(String(event.data)) as { type: string };
      if (value.type !== "heartbeat") refresh();
    };
    socket.onerror = () => socket?.close();
    socket.onclose = (event) => {
      connected(false);
      if (webMode() && [4401, 4403].includes(event.code))
        window.dispatchEvent(new Event("tg-session-expired"));
      else if (!disposed) timer = setTimeout(connect, 2000);
    };
  }
  connect();
  return () => {
    disposed = true;
    clearTimeout(timer);
    socket?.close();
  };
}
