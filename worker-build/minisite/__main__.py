"""CLI: python -m minisite <input_dir> <output.html> [--title TITLE]."""
import argparse
import sys
from pathlib import Path

from .builder import build_site


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="minisite",
        description="Convert a folder of Markdown files into one styled HTML page.",
    )
    ap.add_argument("input_dir", help="folder of .md files (nested folders OK)")
    ap.add_argument("output", help="output .html file")
    ap.add_argument("--title", default="Minisite", help="site <title>")
    args = ap.parse_args(argv)
    try:
        html_doc = build_site(args.input_dir, title=args.title)
    except ValueError as e:
        print(f"minisite: error: {e}", file=sys.stderr)
        return 1
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html_doc, encoding="utf-8")
    print(f"minisite: wrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
