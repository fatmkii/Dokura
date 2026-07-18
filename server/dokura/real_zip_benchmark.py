from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import statistics
import time
import zipfile
from pathlib import Path

from PIL import Image

from dokura.metadata.zip_analyzer import analyze_zip


def select_representative(root: Path, count: int) -> list[Path]:
    candidates = sorted(
        (path for path in root.rglob("*") if path.is_file() and not path.is_symlink() and path.suffix.casefold() == ".zip"),
        key=lambda path: (path.stat().st_size, str(path)),
    )
    if not candidates:
        raise ValueError("Content 中没有 ZIP")
    if len(candidates) <= count:
        return candidates
    indexes = {round(index * (len(candidates) - 1) / (count - 1)) for index in range(count)} if count > 1 else {len(candidates) // 2}
    return [candidates[index] for index in sorted(indexes)]


def benchmark_zip(path: Path, root: Path, pages: int) -> dict[str, object]:
    before = path.stat()
    started = time.perf_counter()
    analysis = analyze_zip(path)
    analyze_ms = (time.perf_counter() - started) * 1_000
    page_results = []
    for page in analysis.pages[:pages]:
        started = time.perf_counter()
        with zipfile.ZipFile(path) as archive:
            data = archive.read(page.entry_name)
        read_ms = (time.perf_counter() - started) * 1_000
        started = time.perf_counter()
        with Image.open(io.BytesIO(data)) as image:
            image.thumbnail((768, 768))
            output = io.BytesIO()
            image.convert("RGB").save(output, "JPEG", quality=85)
        preview_ms = (time.perf_counter() - started) * 1_000
        page_results.append({
            "entry": page.entry_name, "source_bytes": len(data), "read_ms": round(read_ms, 3),
            "preview_ms": round(preview_ms, 3), "preview_bytes": len(output.getvalue()),
        })
    after = path.stat()
    return {
        "path": str(path.relative_to(root)), "zip_bytes": before.st_size,
        "zip_sha256": _hash(path), "analyze_ms": round(analyze_ms, 3),
        "page_count": len(analysis.pages), "sampled_pages": page_results,
        "unchanged": (before.st_size, before.st_mtime_ns, before.st_ino) == (after.st_size, after.st_mtime_ns, after.st_ino),
    }


def _hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def run(root: Path, count: int, pages: int) -> dict[str, object]:
    selected = select_representative(root, count)
    results = [benchmark_zip(path, root, pages) for path in selected]
    read_samples = [page["read_ms"] for result in results for page in result["sampled_pages"]]
    return {
        "content_root": str(root.resolve()), "zip_count": len(list(root.rglob("*.zip"))),
        "selected_count": len(results), "selection": "ZIP 大小等距分位（含最小和最大）",
        "results": results, "all_unchanged": all(item["unchanged"] for item in results),
        "median_page_read_ms": round(statistics.median(read_samples), 3) if read_samples else None,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="阶段 9 真实 ZIP 只读图片基准")
    parser.add_argument("content", type=Path)
    parser.add_argument("--report", required=True, type=Path)
    parser.add_argument("--count", type=int, default=9)
    parser.add_argument("--pages", type=int, default=3)
    args = parser.parse_args()
    if not args.content.is_dir() or args.count < 1 or args.pages < 1:
        parser.error("Content 必须存在，样本数和页数必须大于 0")
    result = run(args.content, args.count, args.pages)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"selected_count": result["selected_count"], "all_unchanged": result["all_unchanged"]}, ensure_ascii=False))
    return 0 if result["all_unchanged"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
