from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from pptx import Presentation

from scripts.extract_ppt import CHAPTER_ORDER, ppt_sort_key
from src.retriever import RetrievedChunk


PAGE_HEADER_PATTERN = re.compile(r"===== 第(\d+)页 =====")
CHAPTER_PATTERN = re.compile(r"^第([一二三四五六七八九十]+)章\s*(.*)$")
VALID_ORIGINAL_PAGE_PATTERN = re.compile(
    r"第\d+章(?:《[^》]+》)?，第\d+页"
)
CHAPTER_PAGE_REFERENCE_PATTERN = re.compile(
    r"第\s*(\d+)\s*章(?:《([^》]+)》)?\s*[，,]?\s*第\s*(\d+)\s*页"
)
GLOBAL_PAGE_REFERENCE_PATTERN = re.compile(
    r"第\s*(\d+)\s*(?:[-—–~～至到]\s*(\d+)\s*)?页"
)


class SourceMappingError(ValueError):
    """表示原始 PPT 与合并页码无法可靠对应。"""


@dataclass(frozen=True)
class ChapterRange:
    chapter: int
    title: str
    filename: str
    slide_count: int
    global_start: int
    global_end: int


class RetrieverProtocol(Protocol):
    def retrieve(self, query: str, top_k: int = 4) -> list[RetrievedChunk]: ...


class SourcePageMapper:
    def __init__(self, chapters: list[ChapterRange]) -> None:
        if not chapters:
            raise SourceMappingError("PPT目录中没有可用于来源映射的正式课程PPT。")
        self.chapters = chapters
        self.total_slides = chapters[-1].global_end

    @classmethod
    def from_ppt_directory(cls, ppt_dir: Path) -> "SourcePageMapper":
        if not ppt_dir.exists():
            raise SourceMappingError(f"PPT目录不存在：{ppt_dir}")

        # PowerPoint 打开文件时可能产生 ~$ 开头的临时锁文件，它不属于课程内容。
        ppt_paths = sorted(
            [path for path in ppt_dir.glob("*.pptx") if not path.name.startswith("~$")],
            key=ppt_sort_key,
        )

        parsed: list[tuple[int, str, Path]] = []
        for path in ppt_paths:
            match = CHAPTER_PATTERN.match(path.stem)
            if not match or match.group(1) not in CHAPTER_ORDER:
                raise SourceMappingError(f"无法从PPT文件名确定章节顺序：{path.name}")
            chapter = CHAPTER_ORDER[match.group(1)]
            title = match.group(2).strip() or path.stem
            parsed.append((chapter, title, path))

        chapter_numbers = [item[0] for item in parsed]
        expected_numbers = list(range(1, len(parsed) + 1))
        if chapter_numbers != expected_numbers:
            raise SourceMappingError(
                f"PPT章节必须从第一章开始连续排列，实际章节为：{chapter_numbers}"
            )

        chapters: list[ChapterRange] = []
        global_start = 1
        for chapter, title, path in parsed:
            slide_count = len(Presentation(str(path)).slides)
            if slide_count <= 0:
                raise SourceMappingError(f"PPT不包含幻灯片：{path.name}")
            global_end = global_start + slide_count - 1
            chapters.append(
                ChapterRange(
                    chapter=chapter,
                    title=title,
                    filename=path.name,
                    slide_count=slide_count,
                    global_start=global_start,
                    global_end=global_end,
                )
            )
            global_start = global_end + 1
        return cls(chapters)

    def map_page(self, global_page: int) -> tuple[ChapterRange, int] | None:
        for chapter in self.chapters:
            if chapter.global_start <= global_page <= chapter.global_end:
                original_page = global_page - chapter.global_start + 1
                return chapter, original_page
        return None

    def format_global_page(self, global_page: int) -> str:
        mapped = self.map_page(global_page)
        if mapped is None:
            return f"合并课程资料第{global_page}页（原始章节页码映射不可用）"
        chapter, original_page = mapped
        return f"第{chapter.chapter}章《{chapter.title}》，第{original_page}页"

    def format_chunk_source(self, chunk: RetrievedChunk) -> str:
        global_pages = [int(value) for value in PAGE_HEADER_PATTERN.findall(chunk.text)]
        if not global_pages and chunk.page is not None:
            global_pages = [chunk.page]
        global_pages = list(dict.fromkeys(global_pages))

        if not global_pages:
            return f"课程资料片段{chunk.chunk_id + 1}（原始章节页码映射不可用）"
        return "；".join(self.format_global_page(page) for page in global_pages)

    def sanitize_text(self, text: str) -> str:
        def normalize_chapter_reference(match: re.Match[str]) -> str:
            chapter_number = int(match.group(1))
            supplied_title = match.group(2)
            original_page = int(match.group(3))
            chapter = next(
                (item for item in self.chapters if item.chapter == chapter_number),
                None,
            )
            if (
                chapter is None
                or not 1 <= original_page <= chapter.slide_count
                or (supplied_title is not None and supplied_title != chapter.title)
            ):
                return "课程页码引用已移除（原始章节页码映射不可用）"
            return f"第{chapter.chapter}章《{chapter.title}》，第{original_page}页"

        text = CHAPTER_PAGE_REFERENCE_PATTERN.sub(normalize_chapter_reference, text)
        protected: dict[str, str] = {}

        def protect(match: re.Match[str]) -> str:
            placeholder = f"__ORIGINAL_PAGE_{len(protected)}__"
            protected[placeholder] = match.group(0)
            return placeholder

        sanitized = VALID_ORIGINAL_PAGE_PATTERN.sub(protect, text)

        def replace_global_reference(match: re.Match[str]) -> str:
            start = int(match.group(1))
            end = int(match.group(2)) if match.group(2) else start
            if end < start or end - start > 50:
                return "课程页码引用已移除（原始章节页码映射不可用）"

            mapped_pages: list[str] = []
            for global_page in range(start, end + 1):
                mapped = self.map_page(global_page)
                if mapped is None:
                    return "课程页码引用已移除（原始章节页码映射不可用）"
                chapter, original_page = mapped
                mapped_pages.append(
                    f"第{chapter.chapter}章《{chapter.title}》，第{original_page}页"
                )
            return "、".join(mapped_pages)

        sanitized = GLOBAL_PAGE_REFERENCE_PATTERN.sub(replace_global_reference, sanitized)
        for placeholder, original in protected.items():
            sanitized = sanitized.replace(placeholder, original)
        return sanitized

    def sanitize_value(self, value: Any) -> Any:
        if isinstance(value, str):
            return self.sanitize_text(value)
        if isinstance(value, list):
            return [self.sanitize_value(item) for item in value]
        if isinstance(value, dict):
            return {key: self.sanitize_value(item) for key, item in value.items()}
        return value


class OriginalSourceRetriever:
    """仅替换检索结果的来源标签，不改变向量检索过程或排序。"""

    def __init__(self, retriever: RetrieverProtocol, mapper: SourcePageMapper) -> None:
        self.retriever = retriever
        self.mapper = mapper

    def retrieve(self, query: str, top_k: int = 4) -> list[RetrievedChunk]:
        chunks = self.retriever.retrieve(query, top_k)
        return [
            RetrievedChunk(
                chunk_id=chunk.chunk_id,
                text=chunk.text,
                page=chunk.page,
                score=chunk.score,
                source=self.mapper.format_chunk_source(chunk),
            )
            for chunk in chunks
        ]
