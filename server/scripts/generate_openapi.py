import argparse
import json
from pathlib import Path

from dokura.main import create_app


OUTPUT = Path(__file__).resolve().parents[1] / "openapi" / "openapi.json"


def render() -> str:
    return json.dumps(create_app().openapi(), ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="生成确定性的 Dokura OpenAPI 文件")
    parser.add_argument("--check", action="store_true", help="仅检查已提交文件是否最新")
    args = parser.parse_args()
    generated = render()
    if args.check:
        if not OUTPUT.exists() or OUTPUT.read_text(encoding="utf-8") != generated:
            print("OpenAPI 文件已漂移；请运行 server/scripts/generate_openapi.py")
            return 1
        print("OpenAPI 文件无漂移")
        return 0
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(generated, encoding="utf-8")
    print(f"已生成 {OUTPUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
