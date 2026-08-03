from __future__ import annotations

import argparse
import pickle
import sys
from pathlib import Path

import faiss
import numpy as np
from sentence_transformers import SentenceTransformer


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INDEX = PROJECT_ROOT / "vector_db" / "course.index"
DEFAULT_CHUNKS = PROJECT_ROOT / "vector_db" / "chunks.pkl"
DEFAULT_MODEL = "BAAI/bge-small-zh"
DEFAULT_QUERY = "什么是深度学习？"
DEFAULT_TOP_K = 3
TEXT_PREVIEW_LENGTH = 500


def read_faiss_index(index_path: Path) -> faiss.Index:
    """Load an index without passing a Unicode path to the FAISS C++ layer."""
    serialized = np.frombuffer(index_path.read_bytes(), dtype=np.uint8)
    return faiss.deserialize_index(serialized)


def load_knowledge_base(index_path: Path, chunks_path: Path) -> tuple[faiss.Index, list[dict[str, object]]]:
    if not index_path.exists():
        raise FileNotFoundError(f"FAISS index not found: {index_path}")
    if not chunks_path.exists():
        raise FileNotFoundError(f"Chunks mapping not found: {chunks_path}")

    index = read_faiss_index(index_path)
    with chunks_path.open("rb") as file:
        chunks = pickle.load(file)

    if index.ntotal != len(chunks):
        raise ValueError(
            f"FAISS vector count ({index.ntotal}) does not match chunk count ({len(chunks)})."
        )

    return index, chunks


def load_embedding_model(model_name: str) -> SentenceTransformer:
    try:
        return SentenceTransformer(model_name, local_files_only=True)
    except TypeError:
        return SentenceTransformer(model_name)
    except Exception:
        return SentenceTransformer(model_name)


def encode_query(query: str, model_name: str) -> np.ndarray:
    model = load_embedding_model(model_name)
    return encode_query_with_model(query, model)


def encode_query_with_model(query: str, model: SentenceTransformer) -> np.ndarray:
    query_embedding = model.encode(
        [query],
        convert_to_numpy=True,
        normalize_embeddings=True,
    )
    return np.asarray(query_embedding, dtype="float32")


def search(
    query: str,
    index_path: Path,
    chunks_path: Path,
    model_name: str,
    top_k: int,
) -> list[dict[str, object]]:
    index, chunks = load_knowledge_base(index_path, chunks_path)
    model = load_embedding_model(model_name)
    return search_loaded(query, index, chunks, model, top_k)


def search_loaded(
    query: str,
    index: faiss.Index,
    chunks: list[dict[str, object]],
    model: SentenceTransformer,
    top_k: int,
) -> list[dict[str, object]]:
    query_embedding = encode_query_with_model(query, model)

    distances, ids = index.search(query_embedding, top_k)

    results: list[dict[str, object]] = []
    for distance, chunk_id in zip(distances[0], ids[0]):
        if chunk_id < 0:
            continue

        chunk = chunks[int(chunk_id)]
        results.append(
            {
                "text": str(chunk["text"]),
                "distance": float(distance),
                "chunk_id": int(chunk_id),
                "page": chunk.get("page"),
            }
        )

    return results


def read_interactive_query() -> str | None:
    prompt = "请输入要检索的课程问题（直接回车则使用默认问题‘什么是深度学习？’）："
    try:
        raw_query = input(prompt)
    except KeyboardInterrupt:
        print("\n已取消输入，本次检索结束。")
        return None
    except EOFError:
        print(f"\n未读取到输入，将使用默认问题“{DEFAULT_QUERY}”。")
        return DEFAULT_QUERY
    except Exception as error:
        print(f"\n读取输入时发生异常：{error}")
        print(f"将使用默认问题“{DEFAULT_QUERY}”。")
        return DEFAULT_QUERY

    if not isinstance(raw_query, str):
        print(f"输入格式异常，将使用默认问题“{DEFAULT_QUERY}”。")
        return DEFAULT_QUERY

    query = raw_query.strip()
    if not query:
        print(f"输入为空，将使用默认问题“{DEFAULT_QUERY}”。")
        return DEFAULT_QUERY
    return query


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(description="交互式测试课程知识库检索。")
    parser.add_argument("--top-k", type=int, default=DEFAULT_TOP_K, help="返回的文本块数量。")
    parser.add_argument("--index", type=Path, default=DEFAULT_INDEX, help="FAISS 索引路径。")
    parser.add_argument("--chunks", type=Path, default=DEFAULT_CHUNKS, help="文本块映射路径。")
    parser.add_argument("--model", default=DEFAULT_MODEL, help="Embedding 模型名称。")
    args = parser.parse_args()

    if args.top_k <= 0:
        print("参数错误：--top-k 必须大于 0。", file=sys.stderr)
        return 2

    try:
        index, chunks = load_knowledge_base(args.index, args.chunks)
        model = load_embedding_model(args.model)
    except Exception as error:
        print(f"模型或知识库加载失败：{error}", file=sys.stderr)
        return 1

    print("Embedding模型和FAISS索引加载完成。")
    query = read_interactive_query()
    if query is None:
        return 130

    try:
        results = search_loaded(query, index, chunks, model, args.top_k)
    except Exception as error:
        print(f"检索失败：{error}", file=sys.stderr)
        return 1

    print("问题：")
    print(query)
    print()

    for rank, result in enumerate(results, start=1):
        text = str(result["text"])[:TEXT_PREVIEW_LENGTH]
        distance = float(result["distance"])
        chunk_id = int(result["chunk_id"])
        page = result.get("page")

        print(f"结果{rank}：")
        if isinstance(page, int):
            print(f"来源：第{page}页（课程资料片段 {chunk_id + 1}）")
        else:
            print(f"来源：课程资料片段 {chunk_id + 1}")
        print("文本：")
        print(text)
        print()
        print("距离：")
        print(distance)
        print()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
