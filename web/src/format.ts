import { zhCN } from "./locales/zh-CN";

export function formatBytes(bytes: number): string {
  if (!Number.isFinite(bytes) || bytes < 0) return "—";
  const units = ["B", "KB", "MB", "GB", "TB"];
  let value = bytes;
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024;
    unit += 1;
  }
  return `${value.toLocaleString("zh-CN", { maximumFractionDigits: unit === 0 ? 0 : 1 })} ${units[unit]}`;
}

export function formatDate(value: string | number): string {
  const date = typeof value === "number" ? new Date(value / 1_000_000) : new Date(value);
  if (Number.isNaN(date.getTime())) return "—";
  return new Intl.DateTimeFormat("zh-CN", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(date);
}

export function statusLabel(status: string): string {
  return zhCN.statusLabels[status as keyof typeof zhCN.statusLabels] ?? status;
}

export function categoryLabel(category: string): string {
  return zhCN.categoryLabels[category as keyof typeof zhCN.categoryLabels] ?? category;
}
