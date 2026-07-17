import type { ApiErrorBody, CatalogResponse, CatalogState, FileDetail, Tag } from "./types";
import { zhCN } from "./locales/zh-CN";

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    message: string,
    public readonly code = "http_error",
  ) {
    super(message);
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    credentials: "same-origin",
    ...init,
    headers: init?.body
      ? { "Content-Type": "application/json", ...init.headers }
      : init?.headers,
  });
  if (!response.ok) {
    let body: ApiErrorBody | undefined;
    try {
      body = (await response.json()) as ApiErrorBody;
    } catch {
      // A proxy may return an HTML error page. The status remains actionable.
    }
    throw new ApiError(
      response.status,
      body?.error?.message ?? (response.status === 401 ? zhCN.sessionExpired : zhCN.requestFailed),
      body?.error?.code,
    );
  }
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

export const api = {
  session: () => request<{ username: string }>("/api/v1/auth/session"),
  login: (username: string, password: string) =>
    request<{ username: string; default_password: boolean }>("/api/v1/auth/login", {
      method: "POST",
      body: JSON.stringify({ username, password }),
    }),
  logout: () => request<void>("/api/v1/auth/logout", { method: "POST" }),
  catalog(state: CatalogState, signal?: AbortSignal) {
    const query = new URLSearchParams();
    query.set("path", state.path);
    query.set("page", String(state.page));
    query.set("per_page", String(state.perPage));
    if (state.query) query.set("query", state.query);
    query.set("scope", state.scope);
    for (const id of state.tagIds) query.append("tag_id", String(id));
    query.set("tag_mode", state.tagMode);
    query.set("rating_min", String(state.ratingMin));
    query.set("rating_max", String(state.ratingMax));
    query.set("sort", state.sort);
    query.set("direction", state.direction);
    return request<CatalogResponse>(`/api/v1/catalog?${query}`, { signal });
  },
  tags(path: string, scope: string, signal?: AbortSignal) {
    const query = new URLSearchParams({ path, scope });
    return request<{ items: Tag[] }>(`/api/v1/tags?${query}`, { signal });
  },
  detail: (id: string, signal?: AbortSignal) => request<FileDetail>(`/api/v1/files/${encodeURIComponent(id)}`, { signal }),
  rating: (id: string, rating: number) =>
    request<{ rating: number; updated_at: string }>(`/api/v1/files/${encodeURIComponent(id)}/rating`, {
      method: "PUT",
      body: JSON.stringify({ rating }),
    }),
};

export function coverUrl(id: string): string {
  return `/api/v1/files/${encodeURIComponent(id)}/cover`;
}

export function previewUrl(id: string, page: number, size: number): string {
  return `/api/v1/files/${encodeURIComponent(id)}/pages/${page}/preview?size=${size}&purpose=preview`;
}

export function originalUrl(id: string, page: number): string {
  return `/api/v1/files/${encodeURIComponent(id)}/pages/${page}/original?purpose=current`;
}
