from __future__ import annotations

import re
from collections import Counter, defaultdict

from fastapi import APIRouter, Depends, HTTPException, Query

from src.course_data import CourseStore, get_course_store
from src.teaching_history import TeachingHistoryStore, get_history_store


def _ensure_course(course_id: str, store: CourseStore) -> None:
    if store.get(course_id) is None:
        raise HTTPException(status_code=404, detail="课程不存在")


def _top(counter: Counter[str], limit: int = 10) -> list[dict[str, object]]:
    return [{"value": key, "count": count} for key, count in counter.most_common(limit)]


def _compact_sources(sources: list[str]) -> str:
    grouped: defaultdict[str, set[int]] = defaultdict(set)
    plain: list[str] = []
    for source in sources:
        match = re.match(r"(.+?)[，,]\s*第\s*(\d+)\s*页$", source)
        if match:
            grouped[match.group(1).strip()].add(int(match.group(2)))
        elif source not in plain:
            plain.append(source)
    result = []
    for filename, pages in grouped.items():
        sorted_pages = sorted(pages)
        ranges: list[str] = []
        start = previous = sorted_pages[0]
        for page in sorted_pages[1:]:
            if page == previous + 1:
                previous = page
                continue
            ranges.append(str(start) if start == previous else f"{start}-{previous}")
            start = previous = page
        ranges.append(str(start) if start == previous else f"{start}-{previous}")
        result.append(f"{filename}，第{'、'.join(ranges)}页")
    return "；".join([*result, *plain])


def _display_source(source: str) -> str:
    page = re.search(r"第\s*(\d+)\s*页", source)
    chapter = re.search(r"第\s*[^章]+章(?:《[^》]+》)?", source)
    fragment = re.search(r"课程资料片段\s*(\d+)", source)
    if chapter and page:
        return f"{chapter.group(0)}，{page.group(0)}"
    if chapter:
        return chapter.group(0)
    if page:
        return page.group(0)
    if fragment:
        return f"课程资料第{fragment.group(1)}节"
    return "课程相关章节"


def _knowledge_name(reason: str) -> str:
    cleaned = re.sub(r"^(该来源(?:明确)?(?:提及|说明|包含)|课程独立资料主题为|课程资料主题为|课程资料(?:明确)?(?:提及|说明|包含))", "", reason).strip(" ：:'\"“”")
    cleaned = re.sub(r"[。；，,].*$", "", cleaned).strip(" ：:'\"“”")
    quoted = re.search(r"[‘'“\"]([^’'”\"]{2,30})[’'”\"]", cleaned)
    if quoted:
        cleaned = quoted.group(1)
    return cleaned[:30] or "相关概念"


def calculate_statistics(events, course_name: str = "当前课程") -> dict:
    usage = Counter(event.task_type for event in events)
    scores = [event.score for event in events if event.score is not None]
    levels = Counter(event.level for event in events if event.level)
    issues: Counter[str] = Counter()
    chapters: Counter[str] = Counter()
    knowledge: defaultdict[str, Counter[str]] = defaultdict(Counter)
    evidence: defaultdict[str, list[str]] = defaultdict(list)
    weaknesses: defaultdict[str, Counter[str]] = defaultdict(Counter)
    for event in events:
        for item in (event.output_json.get("issues", []) if isinstance(event.output_json, dict) else []):
            if isinstance(item, dict):
                label = str(item.get("type") or item.get("description") or "未分类问题")
                issues[label] += 1
        for item in event.course_basis_json:
            source = item.get("source") if isinstance(item, dict) else str(item)
            if not source:
                continue
            source = str(source)
            match = re.search(r"第\s*([^章]+)章", source)
            if match:
                chapters[f"第{match.group(1)}章"] += 1
            if event.score is not None and event.score <= 75:
                reason = str(item.get("reason") or "相关概念掌握不牢") if isinstance(item, dict) else "相关概念掌握不牢"
                chapter_match = re.search(r"第\s*([^章]+)章", source)
                chapter = f"第{chapter_match.group(1).strip()}章" if chapter_match else "课程综合"
                name = _knowledge_name(reason)
                knowledge[chapter][name] += 1
                evidence[chapter].append(_display_source(source))
                weaknesses[f"{chapter}:{name}"][f"得分 {event.score} 分，{event.level or '表现待改进'}"] += 1
    low_points = []
    for chapter, names in sorted(knowledge.items(), key=lambda item: -sum(item[1].values()))[:10]:
        all_evidence = list(dict.fromkeys(evidence[chapter]))
        compact = _compact_sources(all_evidence[:6])
        points = []
        for name, count in names.most_common(5):
            key = f"{chapter}:{name}"
            points.append({"name": name, "count": count,
                "weakness": weaknesses[key].most_common(1)[0][0],
                "advice": f"围绕“{name}”进行概念辨析、例题练习与订正。"})
        low_points.append({"key": chapter, "chapter": chapter, "name": chapter,
            "count": sum(names.values()), "points": points,
            "weakness": "；".join(f"{p['name']}（{p['weakness']}）" for p in points),
            "basis": f"{chapter}，{compact}" if compact else chapter,
            "advice": "按以上薄弱点安排分层讲解和练习。", "all_evidence": []})
    return {
        "sample_size": len(events),
        "data_insufficient": len(events) < 10,
        "usage_counts": dict(usage),
        "score_distribution": {"scores": scores, "levels": dict(levels)},
        "common_issues": _top(issues),
        "frequent_chapters": _top(chapters),
        "low_score_knowledge_points": low_points,
    }


router = APIRouter(prefix="/api/courses/{course_id}/analytics", tags=["teaching-analytics"])


@router.get("")
def analytics(course_id: str, created_from: str | None = Query(None), created_to: str | None = Query(None), store: CourseStore = Depends(get_course_store), history: TeachingHistoryStore = Depends(get_history_store)) -> dict:
    _ensure_course(course_id, store)
    events, _ = history.list(course_id, created_from=created_from, created_to=created_to, page=1, page_size=100000)
    course = store.get(course_id)
    return calculate_statistics(events, course.name if course else "当前课程")
