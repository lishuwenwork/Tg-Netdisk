export interface Metadata {
  duration: number;
  width: number;
  height: number;
  container: string;
  video_codec: string;
  audio_codec: string;
  readable: boolean;
  video_decodable: boolean;
  audio_decodable: boolean;
  error: string;
  thumbnails?: string[];
}
export interface Asset {
  id: string;
  name: string;
  path?: string;
  kind: "video" | "image";
  origin: "local" | "download" | "frame" | "thumbnail";
  status: "downloading" | "ready" | "failed" | "cancelled";
  size: number;
  metadata: Partial<Metadata>;
  width?: number;
  height?: number;
  error?: string;
  downloaded?: number;
  total?: number | null;
  speed?: number;
}
export interface DraftItem {
  media_id: string;
  cover_id: string | null;
}
export interface Draft {
  id: string;
  title: string;
  description: string;
  tags: string[];
  bold_title: boolean;
  channel_id: string;
  items: DraftItem[];
}
export interface Channel {
  id: string;
  name: string;
  can_post: boolean;
}
export type TaskState =
  | "queued"
  | "preparing"
  | "uploading"
  | "publishing"
  | "waiting_retry"
  | "succeeded"
  | "failed"
  | "cancelled"
  | "unknown";
export interface TaskMessage {
  media_id: string;
  message_id: number;
  channel_id: string;
  grouped_id: string;
}
export interface PublishTask {
  id: string;
  state: TaskState;
  created_at: string;
  error: string;
  attempts: number;
  snapshot: {
    draft: Draft;
    channel: Channel;
    caption: string;
    items: (DraftItem & {
      asset: Asset;
      cover: Asset | null;
      random_id: string;
    })[];
  };
  progress: {
    sent: number;
    total: number;
    speed: number;
    speed_ready?: boolean;
    item: number;
    eta_seconds?: number | null;
    sampled_at?: string;
  };
  messages: TaskMessage[];
  retry_in?: number;
}
export interface Auth {
  state:
    | "unconfigured"
    | "logged_out"
    | "waiting_qr"
    | "qr_expired"
    | "password_required"
    | "authorized"
    | "offline";
  user: { id: string; name: string; premium: boolean } | null;
  caption_limit: number;
  qr?: string;
  expires?: string;
}
export interface Settings {
  api_id: string;
  has_api_hash: boolean;
  has_telegram_proxy: boolean;
  has_download_proxy: boolean;
  default_channel: string;
  theme: "dark" | "light";
  close_behavior: "ask" | "hide";
  download_dir: string;
  upload_concurrency: number;
  data_dir: string;
}
export interface Snapshot {
  auth: Auth;
  draft: Draft;
  media: Asset[];
  channels: Channel[];
  tasks: PublishTask[];
  settings: Settings;
}
export interface Connection {
  baseUrl: string;
  token: string;
}
declare global {
  interface Window {
    desktop?: {
      connection(): Promise<Connection>;
      chooseFiles(): Promise<string[]>;
      chooseDirectory(): Promise<string>;
      droppedPaths(files: FileList | File[]): string[];
      showLogs(): Promise<void>;
      minimize(): Promise<void>;
      quit(): Promise<void>;
      onFlushDraft(callback: () => Promise<void>): () => void;
      onBackendStatus(
        callback: (status: { ready: boolean }) => void,
      ): () => void;
    };
  }
}
