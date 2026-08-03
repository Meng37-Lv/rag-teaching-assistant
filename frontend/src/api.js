const BROWSER_API_BASE_URL = (import.meta.env.VITE_API_BASE_URL || 'http://127.0.0.1:8000').replace(/\/$/, '')
let desktopApiBaseUrlPromise = null

async function getApiBaseUrl() {
  if (!window.__TAURI_INTERNALS__) return BROWSER_API_BASE_URL

  if (!desktopApiBaseUrlPromise) {
    desktopApiBaseUrlPromise = import('@tauri-apps/api/core')
      .then(({ invoke }) => invoke('api_base_url'))
      .then((value) => String(value).replace(/\/$/, ''))
  }
  return desktopApiBaseUrlPromise
}

async function postJson(path, body) {
  let response
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

  return parseResponse(response)
}

async function postForm(path, formData) {
  let response
  try {
    const apiBaseUrl = await getApiBaseUrl()
    response = await fetch(`${apiBaseUrl}${path}`, {
      method: 'POST',
      body: formData,
    })
  } catch {
    throw new Error('无法连接教学辅助服务，请确认后端已经启动。')
  }

  return parseResponse(response)
}

async function parseResponse(response) {
  let payload = null
  try {
    payload = await response.json()
  } catch {
    // 后端异常响应可能不是JSON，统一转为安全中文提示。
  }

  if (!response.ok) {
    throw new Error(payload?.detail || `请求失败（HTTP ${response.status}），请稍后重试。`)
  }
  return payload
}

export function optimizeQuestion(question) {
  return postJson('/api/question-optimize', { question })
}

export function evaluateAnswer(question, studentAnswer) {
  return postJson('/api/answer-evaluate', {
    question,
    student_answer: studentAnswer,
  })
}

export function generatePresentationQuestions(files, text) {
  const cleanedText = text.trim()
  if (!files.length && !cleanedText) {
    throw new Error('请上传一个文件或输入纯文本材料。')
  }

  const formData = new FormData()
  files.forEach((file) => formData.append('files', file))
  if (cleanedText) formData.append('text', cleanedText)
  return postForm('/api/presentation-questions', formData)
}
