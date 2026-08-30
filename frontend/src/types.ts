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

export interface Course {
  id: string
  name: string
  description: string
  grade_level: string
  teaching_goal: string
  created_at: string
  status: 'draft' | 'building' | 'ready' | 'failed'
}

export interface CourseMaterial {
  id: string
  filename: string
  size: number
  uploaded_at: string
}

export interface CourseBuildStatus {
  course_id: string
  status: Course['status']
  error: string | null
}

export interface CourseSearchResult {
  chunk_id: number
  text: string
  page: number | null
  score: number
  source: string
}

export interface TeachingEvent {
  id: string
  course_id: string
  created_at: string
  task_type: string
  student_id: string | null
  input_json: Record<string, unknown>
  output_json: Record<string, unknown>
  score: number | null
  level: string | null
  course_basis_json: unknown[]
  duration_ms: number | null
}

export interface TeachingHistoryPage {
  items: TeachingEvent[]
  total: number
  page: number
  page_size: number
}

export interface TeachingAnalytics {
  sample_size: number
  data_insufficient: boolean
  usage_counts: Record<string, number>
  score_distribution: { scores: number[]; levels: Record<string, number> }
  common_issues: Array<{ value: string; count: number }>
  frequent_chapters: Array<{ value: string; count: number }>
  low_score_knowledge_points: Array<{ value: string; count: number; event_ids: string[] }>
}
