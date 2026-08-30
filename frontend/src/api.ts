import type {
  AnswerEvaluateResponse,
  PresentationQuestionsResponse,
  QuestionOptimizeResponse,
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

export function optimizeQuestion(question: string): Promise<QuestionOptimizeResponse> {
  return postJson<QuestionOptimizeResponse>('/api/question-optimize', { question })
}

export function evaluateAnswer(question: string, studentAnswer: string): Promise<AnswerEvaluateResponse> {
  return postJson<AnswerEvaluateResponse>('/api/answer-evaluate', {
    question,
    student_answer: studentAnswer,
  })
}

export function generatePresentationQuestions(files: File[], text: string): Promise<PresentationQuestionsResponse> {
  const cleanedText = text.trim()
  if (!files.length && !cleanedText) {
    throw new Error('请上传一个文件或输入纯文本材料。')
  }

  const formData = new FormData()
  files.forEach((file) => formData.append('files', file))
  if (cleanedText) formData.append('text', cleanedText)
  return postForm<PresentationQuestionsResponse>('/api/presentation-questions', formData)
}
