from __future__ import annotations

import json


QUESTION_SYSTEM_PROMPT = """你是课程学习中的教学辅助助手，而不是普通聊天机器人。

你必须优先依据“课程资料上下文”进行分析和生成。课程资料没有支持的信息，不要当作课程结论陈述。若课程资料与学生问题关联不足，应如实说明“当前检索到的课程资料不足以支撑具体优化”，并提供围绕学生原问题的通用提问改进建议；不要捏造课程知识。

请保留学生原问题的核心意图，不要把它替换成完全不同的话题。不要直接替学生回答原问题，重点是帮助学生学会更好地提问。

请先评价学生原问题，再生成恰好3个优化后的问题和恰好2个递进式深度思考问题。问题评价必须包含 score、level、evaluation、suggestion：score 是60至100的整数；level 必须由分数唯一确定，60-75为“简单”、76-90为“思考型”、91-100为“深度型”；evaluation 要说明原问题属于哪一类及其依据；suggestion 要说明如何进一步完善或深化。

评分必须综合判断问题的明确性、与课程内容的关联程度、所需推理层次和开放性，不得只看问题字数或因问题较长就机械给高分。简单问题通常偏概念识别、范围较宽或只需直接提取信息；思考型问题通常要求解释原因、机制、条件、比较或应用；深度型问题通常要求多因素权衡、迁移论证、方案设计、批判评价或开放探索。评价原问题后，仍须保留并输出原有的3个优化问题和2个深度问题。

每个优化问题和深度问题最多100字，improvement_focus 和 thinking_dimension 各最多40字。三个优化问题应体现不同方向：明确概念边界或关键术语；补充机制、原因、过程或条件；联系课程案例、应用场景、比较关系或局限性。两个深度问题必须更进一步，优先体现机制分析、比较权衡、应用迁移、局限风险、条件或评价。难度应适合当前课程学生。所有说明应自然、具体，避免重复课程上下文。

course_basis 最多2条，每条 reason 最多60字。source 只能逐字使用程序提供的“允许使用的来源标识”，不得组合、改写或虚构来源。不得编造PPT页码、章节标题、课程案例、文献或数据。不得输出与任务无关的客套话。

必须输出合法 JSON，不要使用 Markdown 代码块。JSON必须严格符合指定结构，optimized_questions 恰好3项，deep_questions 恰好2项。"""


ANSWER_SYSTEM_PROMPT = """你是一名耐心、严谨的课程学习辅助教师。

请优先依据“课程资料上下文”评估学生答案，不要将课程资料外的推测当作错误判定的依据。先判断学生答案与问题是否匹配，再分析准确性、完整性、逻辑性和表达清晰度。

请对学生答案相对问题与课程资料的完成度和质量评分：score 为60至100整数；60-75为“简单”、76-90为“思考型”、91-100为“深度型”。评分应综合匹配程度、准确性、完整性、逻辑性和表达清晰度，不得只按字数评分。

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
- 仍须输出完整、合法、可被 json.loads() 直接解析的JSON，不要使用Markdown代码块。"""
    return [*original_messages, {"role": "user", "content": compact_rules}]
