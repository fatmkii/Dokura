from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

from dokura.real_zip_benchmark import select_representative
from dokura.stage3_dataset import generate


def main() -> int:
    parser = argparse.ArgumentParser(description="准备阶段 9 的 10 万条元数据和真实 ZIP 临时副本")
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--real-content", type=Path, required=True)
    parser.add_argument("--count", type=int, default=100_000)
    parser.add_argument("--real-count", type=int, default=3)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    content = args.data_root / "Content"
    metadata = args.data_root / "MetaData"
    config = args.data_root / "Config"
    for directory in (content, metadata, config):
        directory.mkdir(parents=True, exist_ok=True)
    result = generate(metadata / "dokura.sqlite3", args.count, content)
    real_root = content / "real"
    real_root.mkdir()
    selected = select_representative(args.real_content, args.real_count)
    copied = []
    for index, source in enumerate(selected):
        destination = real_root / f"representative-{index:02d}.zip"
        shutil.copy2(source, destination)
        copied.append({"source": str(source.relative_to(args.real_content)), "bytes": source.stat().st_size})
    result["real_zip_copies"] = copied
    args.report.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
