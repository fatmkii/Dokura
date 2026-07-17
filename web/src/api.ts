import type { ApiErrorBody, CatalogResponse, CatalogState, FileDetail, OperationResult, Tag, TaskItem } from "./types";
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
  selection: (state: CatalogState) => request<{ id: string; count: number; expires_in_seconds: number }>("/api/v1/admin/selection", {
    method: "POST",
    body: JSON.stringify({
      path: state.path, query: state.query, scope: state.scope, tag_ids: state.tagIds,
      tag_mode: state.tagMode, rating_min: state.ratingMin, rating_max: state.ratingMax,
      sort: state.sort, direction: state.direction,
    }),
  }),
  selectionStatus: () => request<{ active: boolean; id: string | null; count: number }>("/api/v1/admin/selection"),
  clearSelection: () => request<void>("/api/v1/admin/selection", { method: "DELETE" }),
  deletePreview: () => request<{ snapshot_id: string; file_count: number; total_bytes: number }>("/api/v1/admin/selection/delete-preview", { method: "POST" }),
  deleteSelection: (snapshotId: string, fileCount: number, totalBytes: number) => request<OperationResult & { reconfirmation_required: boolean; snapshot_id?: string; file_count?: number; total_bytes?: number }>("/api/v1/admin/selection/delete", {
    method: "POST", body: JSON.stringify({ snapshot_id: snapshotId, file_count: fileCount, total_bytes: totalBytes }),
  }),
  moveSelection: (targetDirectory: string) => request<OperationResult>("/api/v1/admin/selection/move", { method: "POST", body: JSON.stringify({ target_directory: targetDirectory }) }),
  moveFiles: (fileIds: string[], targetDirectory: string) => request<OperationResult>("/api/v1/admin/files/move", { method: "POST", body: JSON.stringify({ file_ids: fileIds, target_directory: targetDirectory }) }),
  deleteFile: (id: string) => request<OperationResult>(`/api/v1/admin/files/${encodeURIComponent(id)}`, { method: "DELETE" }),
  renameFile: (id: string, name: string) => request<{ relative_path: string }>(`/api/v1/admin/files/${encodeURIComponent(id)}/name`, { method: "PUT", body: JSON.stringify({ name }) }),
  reprocess: (id: string) => request<{ accepted: boolean }>(`/api/v1/admin/files/${encodeURIComponent(id)}/reprocess`, { method: "POST" }),
  createDirectory: (parent: string, name: string) => request<{ relative_path: string }>("/api/v1/admin/directories", { method: "POST", body: JSON.stringify({ parent, name }) }),
  renameDirectory: (path: string, name: string) => request<{ relative_path: string }>(`/api/v1/admin/directories/name?path=${encodeURIComponent(path)}`, { method: "PUT", body: JSON.stringify({ name }) }),
  moveDirectory: (path: string, targetDirectory: string) => request<{ relative_path: string }>(`/api/v1/admin/directories/move?path=${encodeURIComponent(path)}`, { method: "POST", body: JSON.stringify({ target_directory: targetDirectory }) }),
  deleteDirectory: (path: string) => request<void>(`/api/v1/admin/directories?path=${encodeURIComponent(path)}`, { method: "DELETE" }),
  scanStatus: () => request<Record<string, unknown>>("/api/v1/admin/scan"),
  scan: () => request<{ accepted: boolean }>("/api/v1/admin/scan", { method: "POST" }),
  tasks: () => request<{ waiting_count: number; items: TaskItem[] }>("/api/v1/admin/tasks"),
  retryFailed: () => request<{ eligible: number; added: number; skipped: number }>("/api/v1/admin/tasks/retry-failed", { method: "POST" }),
  apiKey: () => request<{ suffix: string }>("/api/v1/admin/api-key"),
  rotateApiKey: (currentPassword: string) => request<{ api_key: string; suffix: string }>("/api/v1/admin/api-key", { method: "POST", body: JSON.stringify({ current_password: currentPassword, confirmed: true }) }),
  changePassword: (currentPassword: string, newPassword: string, confirmation: string) => request<void>("/api/v1/admin/password", { method: "PUT", body: JSON.stringify({ current_password: currentPassword, new_password: newPassword, new_password_confirmation: confirmation }) }),
  cleanupPreview: () => request<{ confirmation_id: string; file_count: number; cache_file_count: number; estimated_bytes: number }>("/api/v1/admin/cache-cleanup/preview", { method: "POST" }),
  cleanup: (confirmationId: string) => request<{ released_bytes: number; success_count: number; busy_skipped_count: number; failure_count: number }>("/api/v1/admin/cache-cleanup/execute", { method: "POST", body: JSON.stringify({ confirmation_id: confirmationId }) }),
  logs: (levels: string[]) => request<{ items: { level: string; message: string }[]; write_error: string | null }>(`/api/v1/admin/logs?${new URLSearchParams(levels.map((level) => ["level", level]))}`),
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
