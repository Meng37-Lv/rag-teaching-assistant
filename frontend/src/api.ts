import type {
  AnswerEvaluateResponse,
  PresentationQuestionsResponse,
  QuestionOptimizeResponse,
  Course,
  CourseMaterial,
  CourseBuildStatus,
  TeachingEvent,
  TeachingHistoryPage,
  TeachingAnalytics,
  LearningReport,
} from "./types";

const BROWSER_API_BASE_URL = (
  // Browser deployments proxy the existing `/api/*` routes from the same origin.
  import.meta.env.VITE_API_BASE_URL || ""
).replace(/\/$/, "");
let desktopApiBaseUrlPromise: Promise<string> | null = null;

async function getApiBaseUrl(): Promise<string> {
  if (!window.__TAURI_INTERNALS__) return BROWSER_API_BASE_URL;

  if (!desktopApiBaseUrlPromise) {
    desktopApiBaseUrlPromise = import("@tauri-apps/api/core")
      .then(({ invoke }) => invoke("api_base_url"))
      .then((value) => String(value).replace(/\/$/, ""));
  }
  return desktopApiBaseUrlPromise;
}

const SESSION_KEY = "teaching-account-session";
export function clearSession(): void { sessionStorage.removeItem(SESSION_KEY); }
async function authenticatedFetch(url: string, init: RequestInit = {}): Promise<Response> {
  const token = sessionStorage.getItem(SESSION_KEY);
  const headers = new Headers(init.headers);
  if (token) headers.set("Authorization", `Bearer ${token}`);
  const response = await fetch(url, { ...init, headers });
  if (response.status === 401 && token && !url.endsWith("/api/auth/login")) {
    clearSession();
    window.dispatchEvent(new Event("account-session-expired"));
  }
  if (token && sessionStorage.getItem(SESSION_KEY) !== token) throw new Error("登录状态已变化，请重新操作。");
  return response;
}
export interface Account { account_id: string; account_name: string; phone: string; }
export function registerAccount(payload: { account_name: string; phone: string; password: string; confirm_password: string }): Promise<{ message: string; account: Account }> {
  return postJson("/api/auth/register", payload);
}
export async function loginAccount(phone: string, password: string): Promise<Account> {
  const result = await postJson<{ token: string; expires_at: number; account: Account }>("/api/auth/login", { phone, password });
  sessionStorage.setItem(SESSION_KEY, result.token);
  return result.account;
}
export function currentAccount(): Promise<Account> { return getJson("/api/auth/me"); }
export async function logoutAccount(): Promise<void> {
  try { await postJson("/api/auth/logout", {}); } finally { clearSession(); }
}
export function authUiConfig(): Promise<{ school_image_url: string }> { return getJson("/api/auth/ui-config"); }

async function postJson<T>(path: string, body: object): Promise<T> {
  let response: Response;
  try {
    const apiBaseUrl = await getApiBaseUrl();
    response = await authenticatedFetch(`${apiBaseUrl}${path}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
  } catch {
    throw new Error("无法连接教学辅助服务，请确认后端已经启动。");
  }

  return parseResponse<T>(response);
}

async function postForm<T>(path: string, formData: FormData): Promise<T> {
  let response: Response;
  try {
    const apiBaseUrl = await getApiBaseUrl();
    response = await authenticatedFetch(`${apiBaseUrl}${path}`, {
      method: "POST",
      body: formData,
    });
  } catch {
    throw new Error("无法连接教学辅助服务，请确认后端已经启动。");
  }

  return parseResponse<T>(response);
}

async function parseResponse<T>(response: Response): Promise<T> {
  let payload: Record<string, unknown> | null = null;
  try {
    payload = await response.json();
  } catch {
    // 后端异常响应可能不是JSON，统一转为安全中文提示。
  }

  if (!response.ok) {
    const detail = payload?.detail;
    throw new Error(
      typeof detail === "string"
        ? detail
        : detail && typeof detail === "object" && typeof (detail as { message?: unknown }).message === "string"
          ? String((detail as { message: string }).message)
        : `请求失败（HTTP ${response.status}），请稍后重试。`,
    );
  }
  return payload as T;
}

export function optimizeQuestion(
  question: string,
  courseId: string,
): Promise<QuestionOptimizeResponse> {
  return postJson<QuestionOptimizeResponse>("/api/question-optimize", {
    course_id: courseId,
    question,
  });
}

export function evaluateAnswer(
  question: string,
  studentAnswer: string,
  courseId: string,
): Promise<AnswerEvaluateResponse> {
  return postJson<AnswerEvaluateResponse>("/api/answer-evaluate", {
    course_id: courseId,
    question,
    student_answer: studentAnswer,
  });
}

export function generatePresentationQuestions(
  files: File[],
  text: string,
  courseId: string,
): Promise<PresentationQuestionsResponse> {
  const cleanedText = text.trim();
  if (!files.length && !cleanedText) {
    throw new Error("请上传一个文件或输入纯文本材料。");
  }

  const formData = new FormData();
  files.forEach((file) => formData.append("files", file));
  if (cleanedText) formData.append("text", cleanedText);
  formData.append("course_id", courseId);
  return postForm<PresentationQuestionsResponse>(
    "/api/presentation-questions",
    formData,
  );
}

export function listCourses(): Promise<Course[]> {
  return getJson<Course[]>("/api/courses");
}
export function createCourse(
  payload: Pick<
    Course,
    "name" | "description" | "grade_level" | "teaching_goal"
  >,
): Promise<Course> {
  return postJson<Course>("/api/courses", payload);
}
export function updateCourse(
  id: string,
  payload: Partial<
    Pick<Course, "name" | "description" | "grade_level" | "teaching_goal">
  >,
): Promise<Course> {
  return requestJson<Course>(`/api/courses/${id}`, "PATCH", payload);
}
export function deleteCourse(id: string): Promise<void> {
  return requestJson<void>(`/api/courses/${id}`, "DELETE");
}
export function listMaterials(id: string): Promise<CourseMaterial[]> {
  return getJson<CourseMaterial[]>(`/api/courses/${id}/materials`);
}
export function uploadMaterial(
  id: string,
  file: File,
): Promise<CourseMaterial> {
  const form = new FormData();
  form.append("file", file);
  return postForm<CourseMaterial>(`/api/courses/${id}/materials`, form);
}
export function deleteMaterial(
  courseId: string,
  materialId: string,
): Promise<void> {
  return requestJson<void>(
    `/api/courses/${courseId}/materials/${materialId}`,
    "DELETE",
  );
}
export function buildCourse(id: string): Promise<CourseBuildStatus> {
  return postJson<CourseBuildStatus>(`/api/courses/${id}/materials/build`, {});
}
export function getBuildStatus(id: string): Promise<CourseBuildStatus> {
  return getJson<CourseBuildStatus>(
    `/api/courses/${id}/materials/build-status`,
  );
}
export function listHistory(
  courseId: string,
  params: Record<string, string | number | undefined> = {},
): Promise<TeachingHistoryPage> {
  const query = new URLSearchParams(
    Object.entries(params)
      .filter(([, value]) => value !== undefined)
      .map(([key, value]) => [key, String(value)]),
  );
  return getJson<TeachingHistoryPage>(
    `/api/courses/${courseId}/history${query.toString() ? `?${query}` : ""}`,
  );
}
export function getHistoryEvent(
  courseId: string,
  eventId: string,
): Promise<TeachingEvent> {
  return getJson<TeachingEvent>(`/api/courses/${courseId}/history/${eventId}`);
}
export function deleteHistoryEvent(
  courseId: string,
  eventId: string,
): Promise<void> {
  return requestJson<void>(
    `/api/courses/${courseId}/history/${eventId}`,
    "DELETE",
  );
}
export function clearHistory(courseId: string): Promise<{ deleted: number }> {
  return requestJson<{ deleted: number }>(
    `/api/courses/${courseId}/history`,
    "DELETE",
  );
}
export async function historyCsvUrl(
  courseId: string,
  params: Record<string, string | undefined> = {},
): Promise<string> {
  const query = new URLSearchParams(
    Object.entries(params).filter(([, value]) => value),
  );
  const base = await getApiBaseUrl();
  return `${base}/api/courses/${courseId}/history/export.csv${query.toString() ? `?${query}` : ""}`;
}
export async function downloadHistoryCsv(
  courseId: string,
  params: Record<string, string | undefined> = {},
): Promise<Blob> {
  const response = await authenticatedFetch(await historyCsvUrl(courseId, params));
  if (!response.ok) {
    let detail = "历史记录导出失败";
    try {
      const payload = await response.json();
      if (typeof payload?.detail === "string") detail = payload.detail;
    } catch {
      // 非 JSON 错误响应使用通用提示。
    }
    throw new Error(detail);
  }
  return response.blob();
}
export function getAnalytics(
  courseId: string,
  params: { created_from?: string; created_to?: string } = {},
): Promise<TeachingAnalytics> {
  const query = new URLSearchParams(
    Object.entries(params).filter(([, value]) => value),
  );
  return getJson<TeachingAnalytics>(
    `/api/courses/${courseId}/analytics${query.toString() ? `?${query}` : ""}`,
  );
}
export function createLearningReport(
  courseId: string,
  params: { created_from?: string; created_to?: string } = {},
): Promise<LearningReport> {
  return postJson<LearningReport>(
    `/api/courses/${courseId}/learning-report`,
    params,
  );
}
export async function exportLearningReport(
  courseId: string,
  format: "md" | "docx" | "pdf",
  report: LearningReport,
): Promise<Blob> {
  const base = await getApiBaseUrl();
  const response = await authenticatedFetch(
    `${base}/api/courses/${courseId}/learning-report/export/${format}`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(report),
    },
  );
  if (!response.ok) throw new Error("学情报告导出失败");
  return response.blob();
}

async function getJson<T>(path: string): Promise<T> {
  return requestJson<T>(path, "GET");
}
async function requestJson<T>(
  path: string,
  method: string,
  body?: object,
): Promise<T> {
  let response: Response;
  try {
    const apiBaseUrl = await getApiBaseUrl();
    response = await authenticatedFetch(`${apiBaseUrl}${path}`, {
      method,
      headers: body ? { "Content-Type": "application/json" } : undefined,
      body: body ? JSON.stringify(body) : undefined,
    });
  } catch {
    throw new Error("无法连接教学辅助服务，请确认后端已经启动。");
  }
  return parseResponse<T>(response);
}


export function previewPresentationMaterials(files: File[], text: string, courseId: string): Promise<{ materials: Array<{ filename: string; overview: string }> }> {
  const form = new FormData();
  files.forEach(file => form.append("files", file));
  if (text.trim()) form.append("text", text.trim());
  form.append("course_id", courseId);
  return postForm("/api/presentation-preview", form);
}

export function listClasses(courseId: string): Promise<any[]> { return getJson(`/api/courses/${courseId}/classes`); }
export function createClass(courseId: string, name: string): Promise<any> { return postJson(`/api/courses/${courseId}/classes`, {name}); }
export function importRoster(classId: string, file: File): Promise<any> { const f=new FormData(); f.append('file',file); return postForm(`/api/classes/${classId}/import`,f); }
export function startSession(classId: string): Promise<any> { return postJson(`/api/classes/${classId}/sessions`,{}); }
export function endSession(id: string): Promise<any> { return postJson(`/api/sessions/${id}/end`,{}); }
export function joinSession(token: string,name: string): Promise<any> { return postJson(`/api/join/${token}`,{name}); }
export function sendClassMessage(id: string,body: string): Promise<any> { return postJson(`/api/sessions/${id}/messages`,{body}); }
export function pollClassMessages(id: string): Promise<any[]> { return getJson(`/api/sessions/${id}/messages`); }

export function listPendingStudents(sessionId: string): Promise<any[]> { return getJson(`/api/sessions/${sessionId}/pending`); }
export function confirmStudent(sessionId: string, sessionStudentId: string, studentId: string): Promise<any> { return requestJson(`/api/sessions/${sessionId}/students/${sessionStudentId}/confirm?student_id=${encodeURIComponent(studentId)}`, 'POST'); }
export function rejectStudent(sessionId: string, sessionStudentId: string): Promise<any> { return postJson(`/api/sessions/${sessionId}/students/${sessionStudentId}/reject`, {}); }
export function studentStatus(sessionId: string): Promise<any> { return requestJson(`/api/sessions/${sessionId}/student-status`, 'GET'); }

async function studentRequest<T>(path: string, method: string, body?: object): Promise<T> {
  const token = sessionStorage.getItem("class-student-token");
  const response = await fetch(`${await getApiBaseUrl()}${path}`, { method, headers: { "Content-Type": "application/json", ...(token ? { "X-Student-Session": token } : {}) }, body: body ? JSON.stringify(body) : undefined });
  return parseResponse<T>(response);
}
export function studentState(): Promise<any> { return studentRequest('/api/student/state', 'GET'); }
export function sendStudentMessage(body: string): Promise<any> { return studentRequest('/api/student/messages','POST',{body}); }

export interface SubmissionFile { id: string; file_id: string; filename: string; file_type: string; size_bytes: number; size?: number; preview_type: string; chunk_summary?: string; uploaded_at: string; }
export interface Submission { submission_id: string; id: string; session_id: string; status: string; created_at: string; updated_at: string; student: { name?: string | null; student_no?: string | null }; files: SubmissionFile[]; }
export interface SubmissionPage { items: Submission[]; submissions?: Submission[]; total: number; page: number; page_size: number; }
export type PreviewStatus = "PREVIEW_OK" | "TEXT";
export interface SubmissionPreview { status: PreviewStatus; file_id: string; filename: string; file_type: string; preview_type: string; size_bytes: number; content_url: string; preview_url?: string; text?: string; }

export async function createSubmission(sessionId: string, files: File[]): Promise<Submission> {
  const form = new FormData(); files.forEach((file) => form.append("files", file));
  const token = sessionStorage.getItem("class-student-token");
  const base = await getApiBaseUrl();
  const response = await fetch(`${base}/api/sessions/${sessionId}/submissions`, { method: "POST", headers: token ? { "X-Student-Session": token } : undefined, body: form });
  return parseResponse<Submission>(response);
}
export function listSubmissions(sessionId: string, params: Record<string, string | number | undefined> = {}): Promise<SubmissionPage> {
  const query = new URLSearchParams(Object.entries(params).filter(([, value]) => value !== undefined).map(([key, value]) => [key, String(value)]));
  return getJson<SubmissionPage>(`/api/sessions/${sessionId}/submissions${query.toString() ? `?${query}` : ""}`);
}
export async function listStudentSubmissions(sessionId: string): Promise<SubmissionPage> {
  const query = new URLSearchParams({ page: "1", page_size: "50" });
  const token = sessionStorage.getItem("class-student-token");
  const base = await getApiBaseUrl();
  const response = await fetch(`${base}/api/sessions/${sessionId}/submissions?${query}`, { headers: token ? { "X-Student-Session": token } : undefined });
  return parseResponse<SubmissionPage>(response);
}
export async function getSubmission(id: string): Promise<Submission> {
  const token = sessionStorage.getItem("class-student-token");
  if (!token) return getJson<Submission>(`/api/submissions/${id}`);
  const base = await getApiBaseUrl();
  const response = await fetch(`${base}/api/submissions/${id}`, { headers: { "X-Student-Session": token } });
  return parseResponse<Submission>(response);
}
export async function previewSubmissionFile(id: string): Promise<SubmissionPreview> {
  const token = sessionStorage.getItem("class-student-token");
  if (!token) return getJson<SubmissionPreview>(`/api/submission-files/${id}/preview`);
  const base = await getApiBaseUrl();
  const response = await fetch(`${base}/api/submission-files/${id}/preview`, { headers: { "X-Student-Session": token } });
  return parseResponse<SubmissionPreview>(response);
}
export async function downloadSubmissionPreviewPdf(id: string): Promise<Blob> {
  const base = await getApiBaseUrl();
  const studentToken = sessionStorage.getItem("class-student-token");
  const response = await authenticatedFetch(`${base}/api/submission-files/${id}/preview/pdf`, { headers: studentToken ? { "X-Student-Session": studentToken } : undefined });
  if (!response.ok) throw new Error("原格式 PDF 预览读取失败");
  return response.blob();
}
export async function downloadSubmissionFile(id: string): Promise<Blob> {
  const base = await getApiBaseUrl();
  const studentToken = sessionStorage.getItem("class-student-token");
  const response = await authenticatedFetch(`${base}/api/submission-files/${id}/content`, { headers: studentToken ? { "X-Student-Session": studentToken } : undefined });
  if (!response.ok) throw new Error("文件读取失败");
  return response.blob();
}
export function generateSubmissionQuestion(id: string, prompt?: string): Promise<{ question: string; response: { citations?: Array<{ location: string; quote: string }> }; question_id: string }> {
  return postJson(`/api/submission-files/${id}/generate-question`, { prompt: prompt || "请基于材料生成一个适合课堂讨论的追问。" });
}

export function classroomJoinInfo(sessionId: string, token: string): Promise<{join_url?: string; qr_available: boolean}> { return requestWithJoinToken(`/api/sessions/${sessionId}/join-info`, token); }
export async function classroomQrBlob(sessionId: string, token: string): Promise<Blob> { const response=await authenticatedFetch(`${await getApiBaseUrl()}/api/sessions/${sessionId}/qrcode`, {headers:{"X-Join-Token":token}}); if(!response.ok) throw new Error("二维码生成失败"); return response.blob(); }
async function requestWithJoinToken(path:string, token:string): Promise<any> { const response=await authenticatedFetch(`${await getApiBaseUrl()}${path}`,{headers:{"X-Join-Token":token}}); return parseResponse(response); }
