from __future__ import annotations

import argparse
import pickle
import re
from pathlib import Path

from langchain_text_splitters import RecursiveCharacterTextSplitter


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT = PROJECT_ROOT / "data" / "clean.txt"
DEFAULT_OUTPUT = PROJECT_ROOT / "data" / "chunks.pkl"
DEFAULT_CHUNK_SIZE = 800
DEFAULT_CHUNK_OVERLAP = 100


def infer_page_id(text: str) -> int | None:
    match = re.search(r"===== 第(\d+)页 =====", text)
    if not match:
        return None
    return int(match.group(1))


def split_text(text: str, chunk_size: int, chunk_overlap: int) -> list[dict[str, object]]:
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        separators=["\n\n", "\n", "。", "！", "？", "；", "，", ".", "!", "?", ";", ",", " ", ""],
    )
    raw_chunks = splitter.split_text(text)

    chunks: list[dict[str, object]] = []
    for index, chunk in enumerate(raw_chunks):
        content = chunk.strip()
        if not content:
            continue

        chunks.append(
            {
                "id": index,
                "text": content,
                "page": infer_page_id(content),
            }
        )

    return chunks


def main() -> None:
    parser = argparse.ArgumentParser(description="Split clean course text into RAG chunks.")
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT, help="Input clean text path.")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help="Output chunk pickle path.")
    parser.add_argument("--chunk-size", type=int, default=DEFAULT_CHUNK_SIZE, help="Maximum characters per chunk.")
    parser.add_argument("--chunk-overlap", type=int, default=DEFAULT_CHUNK_OVERLAP, help="Overlapped characters between chunks.")
    args = parser.parse_args()

    if not args.input.exists():
        raise FileNotFoundError(f"Clean text not found: {args.input}")

    text = args.input.read_text(encoding="utf-8")
    chunks = split_text(text, args.chunk_size, args.chunk_overlap)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("wb") as file:
        pickle.dump(chunks, file)

    print(f"总文本块数量：\n{len(chunks)}")


if __name__ == "__main__":
    main()
