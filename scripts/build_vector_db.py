from __future__ import annotations

import argparse
import pickle
from pathlib import Path

import faiss
import numpy as np
from sentence_transformers import SentenceTransformer


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CHUNKS = PROJECT_ROOT / "data" / "chunks.pkl"
DEFAULT_INDEX = PROJECT_ROOT / "vector_db" / "course.index"
DEFAULT_MAPPING = PROJECT_ROOT / "vector_db" / "chunks.pkl"
DEFAULT_MODEL = "BAAI/bge-small-zh"
FALLBACK_MODEL = "paraphrase-multilingual-MiniLM-L12-v2"


def load_chunks(path: Path) -> list[dict[str, object]]:
    if not path.exists():
        raise FileNotFoundError(f"Chunks file not found: {path}")

    with path.open("rb") as file:
        chunks = pickle.load(file)

    if not chunks:
        raise ValueError("No chunks found. Please run scripts/split_text.py first.")

    return chunks


def load_embedding_model(model_name: str) -> SentenceTransformer:
    """Prefer an installed model so rebuilding also works without network access."""
    try:
        return SentenceTransformer(model_name, local_files_only=True)
    except TypeError:
        return SentenceTransformer(model_name)
    except Exception:
        return SentenceTransformer(model_name)


def encode_chunks(chunks: list[dict[str, object]], model_name: str) -> np.ndarray:
    model = load_embedding_model(model_name)
    texts = [str(chunk["text"]) for chunk in chunks]
    embeddings = model.encode(
        texts,
        batch_size=32,
        convert_to_numpy=True,
        normalize_embeddings=True,
        show_progress_bar=True,
    )
    return np.asarray(embeddings, dtype="float32")


def build_index(embeddings: np.ndarray) -> faiss.Index:
    if embeddings.ndim != 2 or embeddings.shape[0] == 0:
        raise ValueError("Embeddings must be a non-empty 2D array.")

    dimension = embeddings.shape[1]
    index = faiss.IndexFlatIP(dimension)
    index.add(embeddings)
    return index


def save_faiss_index(index: faiss.Index, output_path: Path) -> None:
    """Save an index without passing a Unicode path to the FAISS C++ layer."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    serialized = faiss.serialize_index(index)
    output_path.write_bytes(serialized.tobytes())


def save_chunks_mapping(chunks: list[dict[str, object]], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("wb") as file:
        pickle.dump(chunks, file)


def main() -> None:
    parser = argparse.ArgumentParser(description="Build a FAISS vector database from course chunks.")
    parser.add_argument("--chunks", type=Path, default=DEFAULT_CHUNKS, help="Input chunks pickle path.")
    parser.add_argument("--index", type=Path, default=DEFAULT_INDEX, help="Output FAISS index path.")
    parser.add_argument("--mapping", type=Path, default=DEFAULT_MAPPING, help="Output chunks mapping path.")
    parser.add_argument("--model", default=DEFAULT_MODEL, help="SentenceTransformer embedding model.")
    parser.add_argument(
        "--fallback-model",
        default=FALLBACK_MODEL,
        help="Alternative model to use manually if the preferred model cannot be downloaded.",
    )
    args = parser.parse_args()

    chunks = load_chunks(args.chunks)

    try:
        embeddings = encode_chunks(chunks, args.model)
    except Exception as error:
        message = (
            f"Embedding模型加载或下载失败：{args.model}\n"
            f"可替代方案：重新运行时指定 --model {args.fallback_model}\n"
            f"原始错误：{error}"
        )
        raise RuntimeError(message) from error

    index = build_index(embeddings)

    save_faiss_index(index, args.index)
    save_chunks_mapping(chunks, args.mapping)

    print("向量数据库创建完成")
    print(f"文本块数量：\n{len(chunks)}")
    print(f"向量维度：\n{embeddings.shape[1]}")


if __name__ == "__main__":
    main()
