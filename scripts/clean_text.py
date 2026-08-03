from __future__ import annotations

import argparse
import re
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT = PROJECT_ROOT / "data" / "text.txt"
DEFAULT_OUTPUT = PROJECT_ROOT / "data" / "clean.txt"
PAGE_HEADER_PATTERN = re.compile(r"^===== 第\d+页 =====$")


def clean_text(raw_text: str) -> str:
    text = raw_text.replace("\r\n", "\n").replace("\r", "\n")
    text = text.replace("\u3000", " ")
    text = re.sub(r"[\u200b\u200c\u200d\ufeff]", "", text)

    cleaned_lines: list[str] = []
    previous_blank = False

    for line in text.splitlines():
        line = re.sub(r"[ \t]+", " ", line).strip()

        if not line:
            if cleaned_lines and not previous_blank:
                cleaned_lines.append("")
            previous_blank = True
            continue

        if not PAGE_HEADER_PATTERN.match(line):
            line = re.sub(r"^\s*[\u2022\-]\s*", "", line)
            line = re.sub(r"\s+([，。！？；：、])", r"\1", line)
            line = re.sub(r"([（《])\s+", r"\1", line)
            line = re.sub(r"\s+([）》])", r"\1", line)

        cleaned_lines.append(line)
        previous_blank = False

    cleaned = "\n".join(cleaned_lines)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    cleaned = cleaned.strip()
    return cleaned + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Clean extracted PPT text.")
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT, help="Input text path.")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help="Output clean text path.")
    args = parser.parse_args()

    if not args.input.exists():
        raise FileNotFoundError(f"Input text not found: {args.input}")

    raw_text = args.input.read_text(encoding="utf-8")
    cleaned = clean_text(raw_text)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(cleaned, encoding="utf-8")
    print("文本清洗完成")


if __name__ == "__main__":
    main()
