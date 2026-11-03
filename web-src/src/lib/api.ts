import type {
  EventsResponse,
  RunRequestBody,
  ScenariosResponse,
  StatusResponse,
} from "@/types/api";

/** 所有请求都走这里：统一错误语义，调用方只需要判断返回值。 */

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, init);
  if (!res.ok) throw new ApiError(`${path} 返回 ${res.status}`, res.status);
  return (await res.json()) as T;
}

function postJSON<T>(path: string, body?: unknown): Promise<T> {
  return request<T>(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
}

export const api = {
  scenarios: () => request<ScenariosResponse>("/api/scenarios"),

  status: () => request<StatusResponse>("/api/status"),

  events: (after: number) => request<EventsResponse>(`/api/events?after=${after}`),

  run: (id: string, body: RunRequestBody) =>
    postJSON<{ error?: string }>(`/api/scenario/${encodeURIComponent(id)}`, body),

  confirm: (ok: boolean) => postJSON<{ error?: string }>("/api/scenario/confirm", { ok }),

  ask: (ok: boolean) => postJSON<{ error?: string }>("/api/scenario/ask", { ok }),

  pause: () => postJSON<{ error?: string }>("/api/scenario/pause"),

  resume: () => postJSON<{ error?: string }>("/api/scenario/resume"),

  stop: () => postJSON<{ error?: string }>("/api/scenario/stop"),

  pickDevice: (serial: string) => postJSON<{ error?: string }>("/api/device", { serial }),

  scrcpy: () => postJSON<{ error?: string }>("/api/scrcpy"),

  /** 截图返回的是二进制，这里单独给一个不解析 JSON 的入口 */
  screenshot: (): Promise<Response> => fetch("/api/screenshot"),
};
