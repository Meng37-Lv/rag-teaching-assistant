import type {
  AnswerEvaluateResponse,
  PresentationQuestionsResponse,
  QuestionOptimizeResponse,
  Course, CourseMaterial, CourseBuildStatus, CourseSearchResult,
  TeachingEvent, TeachingHistoryPage,
  TeachingAnalytics,
} from './types'

const BROWSER_API_BASE_URL = (import.meta.env.VITE_API_BASE_URL || 'http://127.0.0.1:8000').replace(/\/$/, '')
let desktopApiBaseUrlPromise: Promise<string> | null = null

async function getApiBaseUrl(): Promise<string> {
  if (!window.__TAURI_INTERNALS__) return BROWSER_API_BASE_URL

  if (!desktopApiBaseUrlPromise) {
    desktopApiBaseUrlPromise = import('@tauri-apps/api/core')
      .then(({ invoke }) => invoke('api_base_url'))
      .then((value) => String(value).replace(/\/$/, ''))
  }
  return desktopApiBaseUrlPromise
}

async function postJson<T>(path: string, body: object): Promise<T> {
  let response: Response
  try {
    const apiBaseUrl = await getApiBaseUrl()
    response = await fetch(`${apiBaseUrl}${path}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    })
  } catch {
    throw new Error('无法连接教学辅助服务，请确认后端已经启动。')
  }

  return parseResponse<T>(response)
}

async function postForm<T>(path: string, formData: FormData): Promise<T> {
  let response: Response
  try {
    const apiBaseUrl = await getApiBaseUrl()
    response = await fetch(`${apiBaseUrl}${path}`, {
      method: 'POST',
      body: formData,
    })
  } catch {
    throw new Error('无法连接教学辅助服务，请确认后端已经启动。')
  }

  return parseResponse<T>(response)
}

async function parseResponse<T>(response: Response): Promise<T> {
  let payload: Record<string, unknown> | null = null
  try {
    payload = await response.json()
  } catch {
    // 后端异常响应可能不是JSON，统一转为安全中文提示。
  }

  if (!response.ok) {
    throw new Error(typeof payload?.detail === 'string' ? payload.detail : `请求失败（HTTP ${response.status}），请稍后重试。`)
  }
  return payload as T
}

export function optimizeQuestion(question: string, courseId: string): Promise<QuestionOptimizeResponse> {
  return postJson<QuestionOptimizeResponse>('/api/question-optimize', { course_id: courseId, question })
}

export function evaluateAnswer(question: string, studentAnswer: string, courseId: string): Promise<AnswerEvaluateResponse> {
  return postJson<AnswerEvaluateResponse>('/api/answer-evaluate', {
    course_id: courseId,
    question,
    student_answer: studentAnswer,
  })
}

export function generatePresentationQuestions(files: File[], text: string, courseId: string): Promise<PresentationQuestionsResponse> {
  const cleanedText = text.trim()
  if (!files.length && !cleanedText) {
    throw new Error('请上传一个文件或输入纯文本材料。')
  }

  const formData = new FormData()
  files.forEach((file) => formData.append('files', file))
  if (cleanedText) formData.append('text', cleanedText)
  formData.append('course_id', courseId)
  return postForm<PresentationQuestionsResponse>('/api/presentation-questions', formData)
}

export function listCourses(): Promise<Course[]> { return getJson<Course[]>('/api/courses') }
export function createCourse(payload: Pick<Course, 'name' | 'description' | 'grade_level' | 'teaching_goal'>): Promise<Course> { return postJson<Course>('/api/courses', payload) }
export function updateCourse(id: string, payload: Partial<Pick<Course, 'name' | 'description' | 'grade_level' | 'teaching_goal'>>): Promise<Course> { return requestJson<Course>(`/api/courses/${id}`, 'PATCH', payload) }
export function deleteCourse(id: string): Promise<void> { return requestJson<void>(`/api/courses/${id}`, 'DELETE') }
export function listMaterials(id: string): Promise<CourseMaterial[]> { return getJson<CourseMaterial[]>(`/api/courses/${id}/materials`) }
export function uploadMaterial(id: string, file: File): Promise<CourseMaterial> { const form = new FormData(); form.append('file', file); return postForm<CourseMaterial>(`/api/courses/${id}/materials`, form) }
export function deleteMaterial(courseId: string, materialId: string): Promise<void> { return requestJson<void>(`/api/courses/${courseId}/materials/${materialId}`, 'DELETE') }
export function buildCourse(id: string): Promise<CourseBuildStatus> { return postJson<CourseBuildStatus>(`/api/courses/${id}/materials/build`, {}) }
export function getBuildStatus(id: string): Promise<CourseBuildStatus> { return getJson<CourseBuildStatus>(`/api/courses/${id}/materials/build-status`) }
export function searchCourse(id: string, query: string, topK = 3): Promise<CourseSearchResult[]> { return postJson<CourseSearchResult[]>(`/api/courses/${id}/materials/search`, { query, top_k: topK }) }
export function listHistory(courseId: string, params: Record<string, string | number | undefined> = {}): Promise<TeachingHistoryPage> { const query = new URLSearchParams(Object.entries(params).filter(([, value]) => value !== undefined).map(([key, value]) => [key, String(value)])); return getJson<TeachingHistoryPage>(`/api/courses/${courseId}/history${query.toString() ? `?${query}` : ''}`) }
export function getHistoryEvent(courseId: string, eventId: string): Promise<TeachingEvent> { return getJson<TeachingEvent>(`/api/courses/${courseId}/history/${eventId}`) }
export function deleteHistoryEvent(courseId: string, eventId: string): Promise<void> { return requestJson<void>(`/api/courses/${courseId}/history/${eventId}`, 'DELETE') }
export function clearHistory(courseId: string): Promise<{ deleted: number }> { return requestJson<{ deleted: number }>(`/api/courses/${courseId}/history`, 'DELETE') }
export function historyCsvUrl(courseId: string, params: Record<string, string | undefined> = {}): string { const query = new URLSearchParams(Object.entries(params).filter(([, value]) => value)); return `${BROWSER_API_BASE_URL}/api/courses/${courseId}/history/export.csv${query.toString() ? `?${query}` : ''}` }
export function getAnalytics(courseId: string, params: { created_from?: string; created_to?: string } = {}): Promise<TeachingAnalytics> { const query = new URLSearchParams(Object.entries(params).filter(([, value]) => value)); return getJson<TeachingAnalytics>(`/api/courses/${courseId}/analytics${query.toString() ? `?${query}` : ''}`) }

async function getJson<T>(path: string): Promise<T> { return requestJson<T>(path, 'GET') }
async function requestJson<T>(path: string, method: string, body?: object): Promise<T> {
  let response: Response
  try { const apiBaseUrl = await getApiBaseUrl(); response = await fetch(`${apiBaseUrl}${path}`, { method, headers: body ? { 'Content-Type': 'application/json' } : undefined, body: body ? JSON.stringify(body) : undefined }) }
  catch { throw new Error('无法连接教学辅助服务，请确认后端已经启动。') }
  return parseResponse<T>(response)
}
