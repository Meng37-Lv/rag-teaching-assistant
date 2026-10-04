export type QuestionEvaluationLevel = "简单" | "思考型" | "深度型";
export type QuestionLevel = "easy" | "medium" | "hard";

export interface ScoreEvidence {
  source: string;
  quote: string;
}

export interface ScoreBreakdownItem {
  key: string;
  label: string;
  max_score: number;
  anchor: string;
  score: number;
  reason: string;
  evidence: ScoreEvidence[];
}

export interface QuestionEvaluation {
  raw_score?: number;
  floor_applied?: boolean;
  score: number;
  level: QuestionEvaluationLevel;
  evaluation: string;
  suggestion: string;
  score_interpretation: string;
  evidence_status: "sufficient" | "insufficient";
  score_breakdown: ScoreBreakdownItem[];
}

export interface OptimizedQuestion {
  question: string;
  improvement_focus: string;
  level: QuestionLevel;
  label: "简单" | "中等" | "困难";
  score: 60 | 80 | 100;
}

export interface DeepQuestion {
  question: string;
  thinking_dimension: string;
}

export interface CourseBasis {
  source: string;
  reason: string;
}

export interface QuestionOptimizeResponse {
  task_type: "question_optimize";
  original_question: string;
  question_evaluation: QuestionEvaluation;
  optimized_questions: OptimizedQuestion[];
  deep_questions: DeepQuestion[];
  course_basis: CourseBasis[];
  insufficiency_notice: string;
}

export interface PresentationQuestion {
  basis_summary?: string;
  relation_explanation?: string;
  source_hints?: Array<{ filename: string; location: string }>;
  level: QuestionLevel;
  label: "简单" | "中等" | "困难";
  score: 60 | 80 | 100;
  question: string;
}

export interface PresentationQuestionsResponse {
  status?: "ready" | "insufficient";
  notice?: string;
  questions: PresentationQuestion[];
}

export interface AnswerEvaluateResponse {
  raw_score?: number;
  floor_applied?: boolean;
  task_type: "answer_evaluate";
  question: string;
  student_answer: string;
  score: number;
  level: QuestionEvaluationLevel;
  score_interpretation?: string;
  evidence_status?: "sufficient" | "insufficient";
  score_breakdown?: ScoreBreakdownItem[];
  overall_evaluation: string;
  strengths: string[];
  issues: Array<{ type: string; description: string; evidence_or_reason: string }>;
  improvement_suggestions: string[];
  improved_answer: string;
  course_basis: CourseBasis[];
  insufficiency_notice: string;
}

export interface Course {
  id: string;
  name: string;
  description: string;
  grade_level: string;
  teaching_goal: string;
  created_at: string;
  status: "draft" | "building" | "ready" | "failed";
}

export interface CourseMaterial {
  id: string;
  filename: string;
  size: number;
  uploaded_at: string;
}

export interface CourseBuildStatus {
  course_id: string;
  status: Course["status"];
  error: string | null;
}

export interface TeachingEvent {
  id: string;
  course_id: string;
  created_at: string;
  task_type: string;
  student_id: string | null;
  input_json: Record<string, unknown>;
  output_json: Record<string, unknown>;
  score: number | null;
  level: string | null;
  course_basis_json: unknown[];
  duration_ms: number | null;
}

export interface TeachingHistoryPage {
  items: TeachingEvent[];
  total: number;
  page: number;
  page_size: number;
}

export interface TeachingAnalytics {
  sample_size: number;
  data_insufficient: boolean;
  usage_counts: Record<string, number>;
  score_distribution: { scores: number[]; levels: Record<string, number> };
  common_issues: Array<{ value: string; count: number }>;
  frequent_chapters: Array<{ value: string; count: number }>;
  low_score_knowledge_points: Array<{
    key: string;
    name: string;
    count: number;
    weakness: string;
    basis: string;
    advice: string;
    all_evidence: string[];
  }>;
}

export interface LearningReport {
  course_id: string;
  created_from: string | null;
  created_to: string | null;
  record_count: number;
  generated_at: string;
  report: Record<string, Array<{ conclusion: string; evidence: string }>>;
}
