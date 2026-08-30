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


def calculate_statistics(events) -> dict:
    usage = Counter(event.task_type for event in events)
    scores = [event.score for event in events if event.score is not None]
    levels = Counter(event.level for event in events if event.level)
    issues: Counter[str] = Counter()
    chapters: Counter[str] = Counter()
    knowledge: Counter[str] = Counter()
    evidence: defaultdict[str, list[str]] = defaultdict(list)
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
                knowledge[source] += 1
                evidence[source].append(event.id)
    return {
        "sample_size": len(events),
        "data_insufficient": len(events) < 10,
        "usage_counts": dict(usage),
        "score_distribution": {"scores": scores, "levels": dict(levels)},
        "common_issues": _top(issues),
        "frequent_chapters": _top(chapters),
        "low_score_knowledge_points": [{"value": key, "count": count, "event_ids": evidence[key]} for key, count in knowledge.most_common(10)],
    }


router = APIRouter(prefix="/api/courses/{course_id}/analytics", tags=["teaching-analytics"])


@router.get("")
def analytics(course_id: str, created_from: str | None = Query(None), created_to: str | None = Query(None), store: CourseStore = Depends(get_course_store), history: TeachingHistoryStore = Depends(get_history_store)) -> dict:
    _ensure_course(course_id, store)
    events, _ = history.list(course_id, created_from=created_from, created_to=created_to, page=1, page_size=100000)
    return calculate_statistics(events)
