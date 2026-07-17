export type ThemeMode = "system" | "light" | "dark";
export type CatalogScope = "current" | "recursive";
export type SortKey = "name" | "size" | "modified" | "rating";
export type SortDirection = "asc" | "desc";

export interface ApiErrorBody {
  error?: { code?: string; message?: string; request_id?: string };
}

export interface Tag {
  id: number;
  category: string;
  value: string;
  uses?: number;
}

export interface DirectoryItem {
  kind: "directory";
  name: string;
  relative_path: string;
}

export interface FileItem {
  kind: "file";
  id: string;
  name: string;
  relative_path: string;
  display_path: string;
  size: number;
  modified_ns: number;
  rating: number;
  status: string;
  cover_status: string;
  content_version: string;
  tags: Tag[];
}

export type CatalogItem = DirectoryItem | FileItem;

export interface CatalogResponse {
  items: CatalogItem[];
  page: number;
  per_page: number;
  total: number;
  pages: number;
  result_version: string;
}

export interface PageInfo {
  number: number;
  unavailable: boolean;
  unavailable_reason: string | null;
}

export interface FileDetail extends FileItem {
  title: string | null;
  event: string | null;
  creator_raw: string | null;
  circle: string | null;
  translated: boolean;
  parser_version: string;
  parse_confidence: number | null;
  parse_warnings: string[];
  unclassified_tags: string[];
  last_error: string | null;
  device: number | null;
  inode: number | null;
  created_at: string;
  updated_at: string;
  page_count: number;
  unavailable_page_count: number;
  cover_cache_bytes: number;
  pages: PageInfo[];
  rating_updated_at: string | null;
}

export interface CatalogState {
  path: string;
  page: number;
  perPage: number;
  query: string;
  scope: CatalogScope;
  tagIds: number[];
  tagMode: "all" | "any";
  ratingMin: number;
  ratingMax: number;
  sort: SortKey;
  direction: SortDirection;
}
