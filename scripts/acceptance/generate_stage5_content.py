from __future__ import annotations

import argparse
import base64
import zipfile
from pathlib import Path


PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
)


def write_zip(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("001.png", PNG)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=Path)
    args = parser.parse_args()
    for index in range(30):
        write_zip(args.root / f"[验收作者] 跨页删除 {index:02d}.zip")
    write_zip(args.root / "冲突甲" / "同名.zip")
    write_zip(args.root / "冲突乙" / "同名.zip")
    (args.root / "目标").mkdir(parents=True, exist_ok=True)
    (args.root / "非空目录").mkdir(parents=True, exist_ok=True)
    (args.root / "非空目录" / ".hidden").write_text("不得删除", encoding="utf-8")


if __name__ == "__main__":
    main()
