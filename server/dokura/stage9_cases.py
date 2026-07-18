from __future__ import annotations

import argparse
import json
import os
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import urlencode

from dokura.release_benchmark import HttpProbe


def discover(probe: HttpProbe, timeout: float) -> tuple[dict[str, object], str]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        scan, _ = probe.request("/api/v1/admin/scan")
        tasks, _ = probe.request("/api/v1/admin/tasks")
        active = [item for item in tasks["items"] if item["status"] in {"waiting_stable", "retry_wait", "analyzing"}]
        if scan.get("status") != "running" and not active and tasks["waiting_count"] == 0:
            break
        time.sleep(2)
    else:
        raise TimeoutError("代表性真实 ZIP 在规定时间内未完成分析")

    query = urlencode({"path": "real", "scope": "recursive", "page": 1, "per_page": 50})
    catalog, _ = probe.request(f"/api/v1/catalog?{query}")
    files = [item for item in catalog["items"] if item["kind"] == "file" and item.get("cover_status") == "complete"]
    if not files:
        raise RuntimeError("真实 ZIP 没有生成可用于图片验收的记录")
    covers, previews, originals = [], [], []
    for item in files:
        detail, _ = probe.request(f"/api/v1/files/{item['id']}")
        available = [page["number"] for page in detail["pages"] if not page["unavailable"]]
        if not available:
            continue
        covers.append(f"/api/v1/files/{item['id']}/cover")
        for page in (available[0], available[-1]):
            previews.append(f"/api/v1/files/{item['id']}/pages/{page}/preview?size=768&purpose=preview")
            originals.append(f"/api/v1/files/{item['id']}/pages/{page}/original?purpose=current")
    if not previews or not originals:
        raise RuntimeError("真实 ZIP 没有可用图片页")
    key, _ = probe.request(
        "/api/v1/admin/api-key", method="POST",
        body={"current_password": "admin", "confirmed": True},
    )
    initial_scan_seconds = None
    if scan.get("started_at") and scan.get("completed_at"):
        initial_scan_seconds = (
            datetime.fromisoformat(scan["completed_at"]) - datetime.fromisoformat(scan["started_at"])
        ).total_seconds()
    return {
        "covers": covers, "previews": previews, "originals": originals,
        "rating_file_id": files[0]["id"], "real_zip_files": len(files),
        "initial_scan_seconds": initial_scan_seconds,
    }, key["api_key"]


def main() -> int:
    parser = argparse.ArgumentParser(description="等待真实 ZIP 分析并生成阶段 9 HTTP 图片用例")
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--cases", type=Path, required=True)
    parser.add_argument("--api-key-file", type=Path, required=True)
    parser.add_argument("--timeout", type=float, default=1_800)
    args = parser.parse_args()
    probe = HttpProbe(args.base_url)
    probe.login("admin")
    cases, api_key = discover(probe, args.timeout)
    args.cases.write_text(json.dumps(cases, ensure_ascii=False, indent=2) + "\n")
    args.api_key_file.write_text(api_key)
    os.chmod(args.api_key_file, 0o600)
    print(json.dumps({key: len(value) if isinstance(value, list) else value for key, value in cases.items()}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
