import type { LocationQuery, LocationQueryRaw } from "vue-router";
import type { CatalogState, SortDirection, SortKey } from "./types";

const defaults: CatalogState = {
  path: "",
  page: 1,
  perPage: 50,
  query: "",
  scope: "current",
  tagIds: [],
  tagMode: "all",
  ratingMin: 0,
  ratingMax: 5,
  sort: "name",
  direction: "asc",
};

function one(value: LocationQuery[string]): string | undefined {
  return Array.isArray(value) ? value[0] ?? undefined : value ?? undefined;
}

function integer(value: LocationQuery[string], fallback: number, min: number, max: number): number {
  const parsed = Number(one(value));
  return Number.isInteger(parsed) && parsed >= min && parsed <= max ? parsed : fallback;
}

export function parseCatalogState(query: LocationQuery): CatalogState {
  const sortValue = one(query.sort);
  const directionValue = one(query.direction);
  const scopeValue = one(query.scope);
  const tagModeValue = one(query.tag_mode);
  const tagValues = Array.isArray(query.tag) ? query.tag : query.tag == null ? [] : [query.tag];
  const ratingMin = integer(query.rating_min, defaults.ratingMin, 0, 5);
  const ratingMax = integer(query.rating_max, defaults.ratingMax, 0, 5);
  const rawPath = (one(query.path) ?? "").replace(/\\/g, "/").replace(/^\/+|\/+$/g, "");
  const path = rawPath.split("/").some((part) => part === "." || part === "..") ? "" : rawPath;
  return {
    path,
    page: integer(query.page, defaults.page, 1, 1_000_000),
    perPage: integer(query.per_page, defaults.perPage, 1, 200),
    query: one(query.q) ?? defaults.query,
    scope: scopeValue === "recursive" ? "recursive" : "current",
    tagIds: [...new Set(tagValues.map(Number).filter((id) => Number.isInteger(id) && id > 0))],
    tagMode: tagModeValue === "any" ? "any" : "all",
    ratingMin: ratingMin <= ratingMax ? ratingMin : defaults.ratingMin,
    ratingMax: ratingMin <= ratingMax ? ratingMax : defaults.ratingMax,
    sort: (["name", "size", "modified", "rating"] as string[]).includes(sortValue ?? "")
      ? (sortValue as SortKey)
      : defaults.sort,
    direction: (["asc", "desc"] as string[]).includes(directionValue ?? "")
      ? (directionValue as SortDirection)
      : defaults.direction,
  };
}

export function catalogQuery(state: CatalogState): LocationQueryRaw {
  const query: LocationQueryRaw = {};
  if (state.path) query.path = state.path;
  if (state.page !== defaults.page) query.page = String(state.page);
  if (state.perPage !== defaults.perPage) query.per_page = String(state.perPage);
  if (state.query) query.q = state.query;
  if (state.scope !== defaults.scope) query.scope = state.scope;
  if (state.tagIds.length) query.tag = state.tagIds.map(String);
  if (state.tagMode !== defaults.tagMode) query.tag_mode = state.tagMode;
  if (state.ratingMin !== defaults.ratingMin) query.rating_min = String(state.ratingMin);
  if (state.ratingMax !== defaults.ratingMax) query.rating_max = String(state.ratingMax);
  if (state.sort !== defaults.sort) query.sort = state.sort;
  if (state.direction !== defaults.direction) query.direction = state.direction;
  return query;
}
