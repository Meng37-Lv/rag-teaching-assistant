from __future__ import annotations

import json
import re
from typing import Any, Iterable


SCORE_INTERPRETATION = "75分表示基本达标且有改进空间；不代表按批次强制调分。"

QUESTION_SCORING_DIMENSIONS = (
    {"key": "material_relevance", "label": "材料关联", "max_score": 25, "anchor": "0-8分几乎无课程材料关联；9-17分提及材料但关联较弱；18-25分准确连接当前课程片段并说明关联。"},
    {"key": "thinking_value", "label": "思考价值", "max_score": 35, "anchor": "0-11分停留在记忆复述；12-24分有解释、比较或应用方向；25-35分能推动机制分析、权衡、迁移或批判讨论。"},
    {"key": "clarity", "label": "表达清晰", "max_score": 15, "anchor": "0-4分含义不清；5-10分基本可理解但边界或术语不稳；11-15分对象、范围和要求明确。"},
    {"key": "discussability", "label": "可讨论性", "max_score": 25, "anchor": "0-8分只能得到简单事实；9-17分有一定讨论空间；18-25分允许多角度论证、比较或提出条件。"},
)

ANSWER_SCORING_DIMENSIONS = (
    {"key": "material_alignment", "label": "材料契合", "max_score": 30, "anchor": "0-9分与当前课程片段无关或无法核实；10-20分部分对应材料；21-30分准确使用材料并回应其适用范围。"},
    {"key": "correctness", "label": "正确性", "max_score": 40, "anchor": "0-12分存在核心错误；13-27分主体正确但有关键混淆；28-40分概念、因果和结论均受材料支持。"},
    {"key": "completeness", "label": "完整性", "max_score": 20, "anchor": "0-6分未回答关键部分；7-13分回答主要问题但有遗漏；14-20分覆盖问题要求、条件和必要限制。"},
    {"key": "expression", "label": "表达", "max_score": 10, "anchor": "0-3分难以理解；4-7分基本清楚但组织一般；8-10分结构清楚、术语恰当且无明显歧义。"},
)


def level_for_score(score: int) -> str:
    if score < 60 or score > 100:
        raise ValueError("总分必须是60至100分。")
    return "简单" if score <= 75 else "思考型" if score <= 90 else "深度型"


def scoring_prompt(dimensions: Iterable[dict[str, Any]]) -> str:
    return "\n".join(f"- {item['label']}（满分{item['max_score']}）：{item['anchor']}" for item in dimensions)


def _terms(text: str) -> set[str]:
    normalized = re.sub(r"\s+", "", text.lower())
    terms = set(re.findall(r"[a-z0-9_]+|[\u4e00-\u9fff]{2}", normalized))
    return {term for term in terms if term not in {"学生", "回答", "问题", "材料", "课程"}}


def validate_evidence(
    evidence: Any,
    allowed_sources: set[str],
    chunks: list[Any] | None,
    related_text: str,
    *,
    required: bool,
) -> None:
    if not isinstance(evidence, list):
        raise ValueError("score_breakdown.evidence 必须是数组。")
    if not evidence and required:
        raise ValueError("材料证据不足：每个评分项都必须提供真实材料片段。")
    chunk_by_source = {getattr(chunk, "source", ""): chunk for chunk in chunks or []}
    related_terms = _terms(related_text)
    for item in evidence:
        if not isinstance(item, dict) or set(item) != {"source", "quote"}:
            raise ValueError("材料证据必须只包含 source 和 quote。")
        source = item["source"]
        quote = item["quote"]
        if not isinstance(source, str) or not isinstance(quote, str) or not source.strip() or not quote.strip():
            raise ValueError("材料证据的 source 和 quote 必须是非空字符串。")
        if source not in allowed_sources:
            raise ValueError(f"材料证据使用了未提供的来源：{source}")
        if chunks is None:
            raise ValueError("当前未提供检索片段，无法校验证据真实性。")
        chunk = chunk_by_source.get(source)
        if chunk is None or quote.strip() not in str(getattr(chunk, "text", "")):
            raise ValueError("材料证据片段不在当前课程检索结果中。")
        quote_terms = _terms(quote)
        if related_terms and not (related_terms & quote_terms) and float(getattr(chunk, "score", 0.0)) < 0.7:
            raise ValueError("材料证据与当前问题或答案关联不足。")


def enrich_breakdown(
    breakdown: list[dict[str, Any]],
    dimensions: tuple[dict[str, Any], ...],
) -> tuple[list[dict[str, Any]], int]:
    if not isinstance(breakdown, list) or len(breakdown) != len(dimensions):
        raise ValueError("score_breakdown 必须按规定包含全部评分项。")
    enriched: list[dict[str, Any]] = []
    total = 0
    for item, dimension in zip(breakdown, dimensions):
        if not isinstance(item, dict) or set(item) != {"key", "score", "reason", "evidence"}:
            raise ValueError("score_breakdown 每项必须包含 key、score、reason、evidence。")
        if item["key"] != dimension["key"]:
            raise ValueError("score_breakdown 的评分项顺序或名称不正确。")
        score = item["score"]
        if type(score) is not int or not 0 <= score <= dimension["max_score"]:
            raise ValueError(f"{dimension['label']}分数必须在0至{dimension['max_score']}之间。")
        if not isinstance(item["reason"], str) or not item["reason"].strip():
            raise ValueError(f"{dimension['label']}必须提供评分理由。")
        total += score
        enriched.append({**item, "label": dimension["label"], "max_score": dimension["max_score"], "anchor": dimension["anchor"]})
    if not 0 <= total <= 100:
        raise ValueError("分项原始总分必须在0至100分之间。")
    return enriched, total


QUESTION_SYSTEM_PROMPT = f"""你是课程学习中的教学辅助助手，而不是普通聊天机器人。

你必须优先依据“课程资料上下文”进行分析和生成。课程资料没有支持的信息，不要当作课程结论陈述。若课程资料与学生问题关联不足，应如实说明“当前检索到的课程资料不足以支撑具体优化”，并提供围绕学生原问题的通用提问改进建议；不要捏造课程知识。

请保留学生原问题的核心意图，不要把它替换成完全不同的话题。不要直接替学生回答原问题，重点是帮助学生学会更好地提问。

请先评价学生原问题，再生成恰好3个优化后的问题和恰好2个递进式深度思考问题。问题评价必须包含 score、level、evaluation、suggestion、score_interpretation、evidence_status、score_breakdown。score由后端计算为max(60, raw_score)，raw_score为真实四项之和（0-100）；level 必须由分数唯一确定，60-75为“简单”、76-90为“思考型”、91-100为“深度型”。75分表示基本达标且有改进空间，不表示按批次强制调分。evaluation 要说明原问题属于哪一类及其依据；suggestion 要说明如何进一步完善或深化。

评分必须按以下四个固定分项给分，并为每项填写0至满分的score、简短reason和材料证据evidence；score_breakdown 顺序和 key 必须严格一致：
{scoring_prompt(QUESTION_SCORING_DIMENSIONS)}
每项 evidence 必须是当前课程检索片段中真实出现的 source 与 quote；不要编造页码、来源或原文。若当前检索片段不足以支撑某项，evidence 置为空数组，evidence_status 写“insufficient”，insufficiency_notice 说明不足原因；不得因检索不足直接压低分数或用外部常识补证据。否则 evidence_status 写“sufficient”。不得为达到60分而抬高分项；后端计算原始总分与保底成绩。评价原问题后，仍须保留并输出原有的3个优化问题和2个深度问题。

每个优化问题和深度问题最多100字，improvement_focus 和 thinking_dimension 各最多40字。三个优化问题应体现不同方向：明确概念边界或关键术语；补充机制、原因、过程或条件；联系课程案例、应用场景、比较关系或局限性。两个深度问题必须更进一步，优先体现机制分析、比较权衡、应用迁移、局限风险、条件或评价。难度应适合当前课程学生。所有说明应自然、具体，避免重复课程上下文。

course_basis 最多2条，每条 reason 最多60字。source 只能逐字使用程序提供的“允许使用的来源标识”，不得组合、改写或虚构来源。不得编造PPT页码、章节标题、课程案例、文献或数据。不得输出与任务无关的客套话。

必须输出合法 JSON，不要使用 Markdown 代码块。JSON必须严格符合指定结构，optimized_questions 恰好3项，deep_questions 恰好2项。"""


ANSWER_SYSTEM_PROMPT = f"""你是一名耐心、严谨的课程学习辅助教师。

请优先依据“课程资料上下文”评估学生答案，不要将课程资料外的推测当作错误判定的依据。先判断学生答案与问题是否匹配，再分析准确性、完整性、逻辑性和表达清晰度。

请对学生答案相对问题与课程资料的完成度和质量评分：score由后端计算为max(60, raw_score)，raw_score为真实四项之和（0-100）；60-75为“简单”、76-90为“思考型”、91-100为“深度型”。75分表示基本达标且有改进空间，不表示按批次强制调分。评分必须按以下固定分项给分，并为每项填写0至满分的score、简短reason和材料证据evidence；score_breakdown 顺序和 key 必须严格一致：
{scoring_prompt(ANSWER_SCORING_DIMENSIONS)}
每项 evidence 必须是当前课程检索片段中真实出现的 source 与 quote；不要编造页码、来源或原文。若当前检索片段不足以支撑某项，evidence 置为空数组，evidence_status 写“insufficient”，insufficiency_notice 说明不足原因；不得因检索不足直接压低分数或用外部常识补证据。否则 evidence_status 写“sufficient”。不得为达到60分而抬高分项；后端计算原始总分与保底成绩。

必须先指出学生回答中值得肯定的部分，再指出需要改进的部分。对每一项问题，说明它属于概念错误、关键遗漏、逻辑问题、表述不清、偏离问题或无法根据课程资料判断。如果课程资料不足以判断某个具体内容，必须明确说明“现有课程资料不足以核实”，不能编造事实或假装课程中讲过。

优化后的回答必须回应原问题，优先使用课程资料支持的表述，概念准确、逻辑完整、语言适合学生理解。不得凭空补充课程中没有依据的案例、数据、结论或页码。即使答案存在问题，也必须给出至少一项值得肯定之处；若没有实质内容，写“未提供可评价的实质性内容”。issues 可以为空，不得为了凑数强行挑错。

course_basis 中的 source 只能逐字使用程序提供的“允许使用的来源标识”，不得组合、改写或虚构来源。不得编造PPT页码、章节标题、案例、引用、数据和文献。不得输出与任务无关的客套话。

strengths、issues、improvement_suggestions 各最多3项。优化后的回答控制在200个中文字符以内，优先保留直接回答问题所需的课程知识，避免重复。

必须输出合法 JSON，不要使用 Markdown 代码块。"""


QUESTION_SCHEMA = {
    "task_type": "question_optimize",
    "original_question": "学生原始问题",
    "question_evaluation": {
        "score": 60,
        "level": "简单",
        "evaluation": "说明原问题所属类型及判断依据",
        "suggestion": "说明如何进一步完善或深化",
        "score_interpretation": "75分表示基本达标且有改进空间；不代表按批次强制调分。",
        "evidence_status": "sufficient",
        "score_breakdown": [
            {"key": "material_relevance", "score": 15, "reason": "材料关联评分理由", "evidence": [{"source": "真实来源标识", "quote": "材料中的真实片段"}]},
            {"key": "thinking_value", "score": 21, "reason": "思考价值评分理由", "evidence": [{"source": "真实来源标识", "quote": "材料中的真实片段"}]},
            {"key": "clarity", "score": 12, "reason": "表达清晰评分理由", "evidence": [{"source": "真实来源标识", "quote": "材料中的真实片段"}]},
            {"key": "discussability", "score": 12, "reason": "可讨论性评分理由", "evidence": [{"source": "真实来源标识", "quote": "材料中的真实片段"}]}
        ]
    },
    "optimized_questions": [
        {"question": "优化问题1", "improvement_focus": "该问题主要改善了什么"},
        {"question": "优化问题2", "improvement_focus": "该问题主要改善了什么"},
        {"question": "优化问题3", "improvement_focus": "该问题主要改善了什么"},
    ],
    "deep_questions": [
        {"question": "深度问题1", "thinking_dimension": "思考维度"},
        {"question": "深度问题2", "thinking_dimension": "思考维度"},
    ],
    "course_basis": [{"source": "真实来源标识", "reason": "关联说明"}],
    "insufficiency_notice": "资料充分时为空字符串",
}


ANSWER_SCHEMA = {
    "task_type": "answer_evaluate",
    "question": "学生回答对应的问题",
    "student_answer": "学生原始回答",
    "score": 60,
    "level": "简单",
    "score_interpretation": "75分表示基本达标且有改进空间；不代表按批次强制调分。",
    "evidence_status": "sufficient",
    "score_breakdown": [
        {"key": "material_alignment", "score": 18, "reason": "材料契合评分理由", "evidence": [{"source": "真实来源标识", "quote": "材料中的真实片段"}]},
        {"key": "correctness", "score": 24, "reason": "正确性评分理由", "evidence": [{"source": "真实来源标识", "quote": "材料中的真实片段"}]},
        {"key": "completeness", "score": 12, "reason": "完整性评分理由", "evidence": [{"source": "真实来源标识", "quote": "材料中的真实片段"}]},
        {"key": "expression", "score": 6, "reason": "表达评分理由", "evidence": [{"source": "真实来源标识", "quote": "材料中的真实片段"}]}
    ],
    "overall_evaluation": "总体评价",
    "strengths": ["值得肯定之处"],
    "issues": [
        {
            "type": "问题类型",
            "description": "具体问题说明",
            "evidence_or_reason": "基于课程资料的说明",
        }
    ],
    "improvement_suggestions": ["可执行的改进建议"],
    "improved_answer": "优化后的完整回答",
    "course_basis": [{"source": "真实来源标识", "reason": "关联说明"}],
    "insufficiency_notice": "资料充分时为空字符串",
}


def build_question_messages(question: str, context: str, sources: list[str]) -> list[dict[str, str]]:
    user_prompt = f"""课程资料上下文：
{context}

允许使用的来源标识：
{json.dumps(sources, ensure_ascii=False)}

学生原始问题：
{question}

请按以下 JSON 结构返回，字段名不得改变：
{json.dumps(QUESTION_SCHEMA, ensure_ascii=False, indent=2)}"""
    return [
        {"role": "system", "content": QUESTION_SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ]


def build_answer_messages(
    question: str,
    student_answer: str,
    context: str,
    sources: list[str],
) -> list[dict[str, str]]:
    user_prompt = f"""课程资料上下文：
{context}

允许使用的来源标识：
{json.dumps(sources, ensure_ascii=False)}

学生所回答的问题：
{question}

学生原始答案：
{student_answer}

请按以下 JSON 结构返回，字段名不得改变：
{json.dumps(ANSWER_SCHEMA, ensure_ascii=False, indent=2)}"""
    return [
        {"role": "system", "content": ANSWER_SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ]


def build_json_repair_messages(
    raw_output: str,
    task_type: str,
    validation_error: str,
    sources: list[str],
) -> list[dict[str, str]]:
    schema = QUESTION_SCHEMA if task_type == "question_optimize" else ANSWER_SCHEMA
    prompt = f"""下面的大模型输出不是合规 JSON。请只修复 JSON 格式和结构，不改变原本语义，不增加事实。

任务类型：{task_type}
校验错误：{validation_error}
允许使用的来源标识：{json.dumps(sources, ensure_ascii=False)}
目标结构：{json.dumps(schema, ensure_ascii=False)}

原始输出：
{raw_output}

只输出修复后的合法 JSON，不要使用 Markdown 代码块。"""
    return [{"role": "user", "content": prompt}]


def build_truncation_retry_messages(
    original_messages: list[dict[str, str]],
    task_type: str,
) -> list[dict[str, str]]:
    if task_type == "question_optimize":
        compact_rules = """上一次响应因输出长度限制被截断。请重新执行上面的原始任务，不要续写残缺JSON，并遵守以下长度限制：
- 先输出结构完整的问题评价；score为60-100整数，level与分数区间严格对应；
- 分项保持真实得分，后端计算raw_score及score=max(60, raw_score)；分项必须包含固定key、0至各自满分的score、reason和evidence；不得因材料不足直接压低分数；75分表示基本达标且有改进空间；
- evaluation说明所属类型和依据，suggestion说明如何完善或深化；不得按问题长度机械打分；
- 每个优化问题和深度问题不超过100字；
- improvement_focus 和 thinking_dimension 各不超过40字；
- course_basis 最多2条，每条 reason 不超过60字；
- 保留必要的教学分析，但不要重复课程原文；
- 仍须输出完整、合法、可被 json.loads() 直接解析的JSON，不要使用Markdown代码块。"""
    else:
        compact_rules = """上一次响应因输出长度限制被截断。请重新执行上面的原始任务，不要续写残缺JSON，并进一步压缩表达：
- course_basis 最多2条，每条 reason 不超过30字；
- 不重复课程原文，只保留完成教学任务必需的信息；
- strengths、issues、improvement_suggestions 各最多3条，improved_answer 不超过200字；
- 分项保持真实得分，后端计算raw_score及score=max(60, raw_score)；分项必须包含固定key、reason和当前检索片段中的真实evidence；
- 仍须输出完整、合法、可被 json.loads() 直接解析的JSON，不要使用Markdown代码块。"""
    return [*original_messages, {"role": "user", "content": compact_rules}]
