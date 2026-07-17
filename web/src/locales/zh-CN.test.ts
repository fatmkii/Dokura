import { describe, expect, it } from "vitest";

import { zhCN } from "./zh-CN";

describe("简体中文文案目录", () => {
  it("contains the application identity", () => {
    expect(zhCN.brand).toBe("Dokura");
    expect(zhCN.library).toBe("内容库");
    expect(zhCN.loadFailed.length).toBeGreaterThan(0);
  });
});
