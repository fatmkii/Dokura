from __future__ import annotations

import argparse
import json
import os
from collections import Counter
from pathlib import Path

from dokura.metadata.zip_analyzer import TemporaryReadError, ZipAnalysisError, analyze_zip


def tree_snapshot(root: Path) -> dict[str, tuple[int, int, int]]:
    snapshot: dict[str, tuple[int, int, int]] = {}
    for path in root.rglob("*"):
        stat = path.lstat()
        snapshot[str(path.relative_to(root))] = (stat.st_mode, stat.st_size, stat.st_mtime_ns)
    return snapshot


def analyze_content(content: Path) -> dict[str, object]:
    before = tree_snapshot(content)
    zip_paths: list[Path] = []
    ignored_files = 0
    ignored_symlinks = 0
    for root, directories, files in os.walk(content, followlinks=False):
        root_path = Path(root)
        directories[:] = [name for name in directories if not (root_path / name).is_symlink()]
        for name in files:
            path = root_path / name
            if path.is_symlink():
                ignored_symlinks += 1
            elif path.suffix.casefold() == ".zip":
                zip_paths.append(path)
            else:
                ignored_files += 1

    results: list[dict[str, object]] = []
    statuses: Counter[str] = Counter()
    for index, path in enumerate(sorted(zip_paths), start=1):
        relative = str(path.relative_to(content))
        try:
            analysis = analyze_zip(path)
            status = "ready" if analysis.has_valid_content else "no_valid_content"
            results.append({
                "path": relative, "status": status, "pages": len(analysis.pages),
                "unavailable_pages": len(analysis.unavailable_pages), "cover_page": analysis.cover_page,
            })
        except ZipAnalysisError as exc:
            status = "failed"
            results.append({"path": relative, "status": status, "reason": exc.code})
        except TemporaryReadError as exc:
            status = "temporary_read_failure"
            results.append({"path": relative, "status": status, "reason": str(exc)})
        statuses[status] += 1
        if index % 25 == 0:
            print(f"已分析 {index}/{len(zip_paths)}", flush=True)

    after = tree_snapshot(content)
    return {
        "content_root": str(content.resolve()),
        "zip_count": len(zip_paths),
        "ignored_non_zip_files": ignored_files,
        "ignored_symlinks": ignored_symlinks,
        "status_counts": dict(sorted(statuses.items())),
        "all_zips_accounted_for": sum(statuses.values()) == len(zip_paths),
        "content_tree_unchanged": before == after,
        "results": results,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="只读分析 Content 并输出阶段 1 JSON 报告")
    parser.add_argument("content", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not args.content.is_dir():
        parser.error(f"Content 目录不存在: {args.content}")
    report = analyze_content(args.content)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: report[key] for key in ("zip_count", "ignored_non_zip_files", "status_counts", "all_zips_accounted_for", "content_tree_unchanged")}, ensure_ascii=False))
    return 0 if report["all_zips_accounted_for"] and report["content_tree_unchanged"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
