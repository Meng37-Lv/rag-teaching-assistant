from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np

from scripts.test_search import (
    DEFAULT_CHUNKS,
    DEFAULT_INDEX,
    DEFAULT_MODEL,
    load_embedding_model,
    load_knowledge_base,
)


@dataclass(frozen=True)
class RetrievedChunk:
    chunk_id: int
    text: str
    page: int | None
    score: float
    source: str


class CourseRetriever:
    """只读加载现有 Embedding 模型、FAISS 索引和文本映射。"""

    def __init__(
        self,
        index_path: Path = DEFAULT_INDEX,
        chunks_path: Path = DEFAULT_CHUNKS,
        model_name: str = DEFAULT_MODEL,
    ) -> None:
        self.index, self.chunks = load_knowledge_base(index_path, chunks_path)
        self.model = load_embedding_model(model_name)

    def retrieve(self, query: str, top_k: int = 4) -> list[RetrievedChunk]:
        query = query.strip()
        if not query:
            raise ValueError("检索问题不能为空。")
        if top_k <= 0:
            raise ValueError("top_k 必须大于 0。")

        embedding = self.model.encode(
            [query],
            convert_to_numpy=True,
            normalize_embeddings=True,
        )
        distances, ids = self.index.search(
            np.asarray(embedding, dtype="float32"),
            min(top_k, len(self.chunks)),
        )

        results: list[RetrievedChunk] = []
        for score, raw_id in zip(distances[0], ids[0]):
            chunk_id = int(raw_id)
            if chunk_id < 0:
                continue
            chunk = self.chunks[chunk_id]
            page_value = chunk.get("page") if isinstance(chunk, dict) else None
            page = int(page_value) if isinstance(page_value, int) else None
            source = f"第{page}页" if page is not None else f"课程资料片段{chunk_id + 1}"
            results.append(
                RetrievedChunk(
                    chunk_id=chunk_id,
                    text=str(chunk["text"]),
                    page=page,
                    score=float(score),
                    source=source,
                )
            )
        return results


def format_context(
    chunks: list[RetrievedChunk],
    max_context_chars: int,
    max_chunk_chars: int,
) -> str:
    if not chunks:
        return "未检索到可用课程资料。"

    parts: list[str] = []
    used = 0
    for chunk in chunks:
        text = chunk.text.strip()
        if len(text) > max_chunk_chars:
            marker = "（片段已截断）"
            keep_length = max(0, max_chunk_chars - len(marker))
            text = text[:keep_length].rstrip() + marker
        part = f"【来源：{chunk.source}；chunk_id：{chunk.chunk_id}】\n{text}"
        separator_length = 2 if parts else 0
        remaining = max_context_chars - used - separator_length
        if remaining <= 0:
            break
        if len(part) > remaining:
            marker = "（上下文已截断）"
            keep_length = max(0, remaining - len(marker))
            part = part[:keep_length].rstrip() + marker
            part = part[:remaining]
        parts.append(part)
        used += separator_length + len(part)
        if used >= max_context_chars:
            break
    return "\n\n".join(parts)


def relevance_label(score: float) -> str:
    if score >= 0.80:
        return "高"
    if score >= 0.70:
        return "中"
    return "较低"
