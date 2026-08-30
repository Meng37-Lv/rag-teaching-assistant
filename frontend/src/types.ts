export type QuestionEvaluationLevel = '简单' | '思考型' | '深度型'
export type QuestionLevel = 'easy' | 'medium' | 'hard'

export interface QuestionEvaluation {
  score: number
  level: QuestionEvaluationLevel
  evaluation: string
  suggestion: string
}

export interface OptimizedQuestion {
  question: string
  improvement_focus: string
  level: QuestionLevel
  label: '简单' | '中等' | '困难'
  score: 60 | 80 | 100
}

export interface DeepQuestion {
  question: string
  thinking_dimension: string
}

export interface CourseBasis {
  source: string
  reason: string
}

export interface QuestionOptimizeResponse {
  task_type: 'question_optimize'
  original_question: string
  question_evaluation: QuestionEvaluation
  optimized_questions: OptimizedQuestion[]
  deep_questions: DeepQuestion[]
  course_basis: CourseBasis[]
  insufficiency_notice: string
}

export interface PresentationQuestion {
  level: QuestionLevel
  label: '简单' | '中等' | '困难'
  score: 60 | 80 | 100
  question: string
}

export interface PresentationQuestionsResponse {
  questions: PresentationQuestion[]
}

export interface AnswerEvaluateResponse {
  task_type: 'answer_evaluate'
  [key: string]: unknown
}
