<script setup>
import { computed, ref, onMounted, onUnmounted, nextTick } from "vue";
import * as pdfjsLib from "pdfjs-dist";
import pdfWorker from "pdfjs-dist/build/pdf.worker.min.mjs?url";
pdfjsLib.GlobalWorkerOptions.workerSrc = pdfWorker;
import {
  registerAccount, loginAccount, logoutAccount, currentAccount, authUiConfig, clearSession,
  buildCourse,
  createCourse,
  createLearningReport,
  deleteCourse,
  deleteHistoryEvent,
  deleteMaterial,
  evaluateAnswer,
  generatePresentationQuestions,
  previewPresentationMaterials,
  getAnalytics,
  getBuildStatus,
  getHistoryEvent,
  downloadHistoryCsv,
  exportLearningReport,
  listCourses,
  listHistory,
  listMaterials,
  optimizeQuestion,
  updateCourse,
  uploadMaterial,
  clearHistory,
  listClasses, createClass, importRoster, startSession, endSession, joinSession, sendClassMessage, pollClassMessages, listPendingStudents, confirmStudent, rejectStudent, studentStatus, studentState, sendStudentMessage,
  createSubmission, createSubmissionWithProgress, listSubmissions, listStudentSubmissions, getSubmission, previewSubmissionFile, downloadSubmissionFile, downloadSubmissionPreviewPdf, generateSubmissionQuestion, studentOralState, saveOralDraft, submitOralQuestion, submitOralAnswer, teacherOralState, optimizeOralQuestion, evaluateOralAnswer, createCollaborationRound, completeCollaborationRound, cancelCollaborationRound, listCollaborationClaims, acceptCollaborationClaim, rejectCollaborationClaim, releaseCollaborationClaim, returnCollaborationClaim, cancelCollaborationClaim, claimCollaborationToken, collaborationStudentState, completeCollaborationClaim, saveCollaborationEntry, getCollaborationEntry, saveTeacherCollaborationEntry, submitCollaborationRound,
} from "./api.ts";

const account = ref(null);
const authChecking = ref(true);
const authMode = ref("login");
const authPending = ref(false);
const authError = ref("");
const schoolImageUrl = ref("");
const authForm = ref({ account_name: "", phone: "", password: "", confirm_password: "" });
function switchAuth(mode) {
  if (authPending.value) return;
  authMode.value = mode;
  authError.value = "";
  authForm.value.password = "";
  authForm.value.confirm_password = "";
}
async function submitAuth() {
  if (authPending.value) return;
  authError.value = "";
  const form = authForm.value;
  if (!form.phone.trim() || !form.password || (authMode.value === "register" && (!form.account_name.trim() || !form.confirm_password))) {
    authError.value = "请完整填写所有必填项。"; return;
  }
  if (authMode.value === "register" && form.password !== form.confirm_password) {
    authError.value = "两次输入的密码不一致。"; return;
  }
  authPending.value = true;
  try {
    if (authMode.value === "register") {
      await registerAccount({ ...form });
      window.alert("注册成功，请登录");
      authMode.value = "login";
    } else {
      const loggedIn = await loginAccount(form.phone, form.password);
      window.alert("登录成功");
      account.value = loggedIn;
      page.value = "home";
    }
    authForm.value.password = "";
    authForm.value.confirm_password = "";
  } catch (error) { authError.value = error instanceof Error ? error.message : "请求失败，请重试。"; }
  finally { authPending.value = false; }
}
function resetAccountWorkspace() {
  page.value = "home"; mode.value = null; result.value = null;
  courses.value = []; selectedCourse.value = null; courseMaterials.value = [];
  teachingCourseId.value = ""; teachingCourseName.value = ""; teachingCourses.value = [];
  historyItems.value = []; historyDetail.value = null; analyticsData.value = null; learningReport.value = null;
  presentationFiles.value = []; presentationText.value = ""; materialPreviews.value = [];
  optimizedQuestionInput.value = ""; answerQuestionInput.value = ""; studentAnswer.value = "";
  courseForm.value = { name: "", description: "", grade_level: "", teaching_goal: "" };
  historyTotal.value = 0; historyPage.value = 1; historyTaskType.value = ""; historyFrom.value = ""; historyTo.value = "";
  analyticsFrom.value = ""; analyticsTo.value = "";
  excludedPresentationFiles.value = []; includePresentationText.value = true;
  errorMessage.value = ""; courseError.value = ""; courseNotice.value = ""; teachingError.value = "";
  historyError.value = ""; analyticsError.value = ""; reportError.value = ""; toastMessage.value = "";
}
function sessionExpired() {
  account.value = null; clearSession(); resetAccountWorkspace();
  authMode.value = "login"; authError.value = "登录已过期或失效，请重新登录。";
}
async function signOut() {
  if (authPending.value || loading.value || previewLoading.value || courseLoading.value || courseSaving.value || teachingLoading.value || historyLoading.value || analyticsLoading.value || reportLoading.value) return;
  authPending.value = true;
  try { await logoutAccount(); }
  catch (error) { authError.value = error instanceof Error ? error.message : "退出失败。"; }
  finally { account.value = null; resetAccountWorkspace(); authForm.value = { account_name: "", phone: "", password: "", confirm_password: "" }; authMode.value = "login"; authPending.value = false; }
}

const page = ref("home");
const mode = ref(null);
const optimizedQuestionInput = ref("");
const answerQuestionInput = ref("");
const studentAnswer = ref("");
const loading = ref(false);
const errorMessage = ref("");
const result = ref(null);
const revealedOptimizedQuestions = ref([]);
const revealedPresentationQuestions = ref([]);
const presentationFiles = ref([]);
const presentationText = ref("");
const excludedPresentationFiles = ref([]);
const includePresentationText = ref(true);
const materialPreviews = ref([]);
const previewLoading = ref(false);
async function previewCurrentMaterials() {
  previewLoading.value = true;
  errorMessage.value = "";
  try {
    const data = await previewPresentationMaterials(presentationFiles.value.filter(file => !excludedPresentationFiles.value.includes(file)), includePresentationText.value ? presentationText.value : "", teachingCourseId.value);
    materialPreviews.value = data.materials;
  } catch (error) { errorMessage.value = error instanceof Error ? error.message : "材料预览失败"; }
  finally { previewLoading.value = false; }
}

const fileInput = ref(null);
const courses = ref([]);
const selectedCourse = ref(null);
const courseMaterials = ref([]);
const courseLoading = ref(false);
const courseSaving = ref(false);
const courseError = ref("");
const courseNotice = ref("");
const courseForm = ref({
  name: "",
  description: "",
  grade_level: "",
  teaching_goal: "",
});
const courseFileInput = ref(null);
const teachingCourseId = ref("");
const teachingCourseName = ref("");
const teachingCourses = ref([]);
const teachingLoading = ref(false);
const teachingError = ref("");
const historyItems = ref([]);
const historyTotal = ref(0);
const historyPage = ref(1);
const historyPageSize = ref(10);
const historyTaskType = ref(""); const historyClassId = ref(""); const currentClassId = ref("");
const historyFrom = ref("");
const historyTo = ref("");
const historyLoading = ref(false);
const historyError = ref("");
const historyDetail = ref(null);
const analyticsData = ref(null);
const analyticsFrom = ref("");
const analyticsTo = ref("");
const analyticsLoading = ref(false);
const analyticsError = ref("");
const learningReport = ref(null);
const reportLoading = ref(false);
const reportError = ref("");
const toastMessage = ref("");
const classroomClasses = ref([]); const classroomName = ref(""); const classroomSession = ref(null); const classroomMessages = ref([]); const classroomText = ref(""); const classroomJoinToken = ref(""); const classroomJoinUrl = ref(""); const classroomQrUrl = ref(""); const classroomNotice = ref(""); const classroomStudentName = ref(""); const studentEntry = ref(Boolean(new URLSearchParams(window.location.search).get("join"))); const studentJoinToken = ref(new URLSearchParams(window.location.search).get("join") || ""); const studentInput = ref(""); const studentMessage = ref(""); const studentMessages = ref([]); const studentPending = ref(false); const classroomStatus = ref(""); const classroomTimer = ref(null); const studentTimer = ref(null); const classroomPending = ref([]); const classroomPendingBusy = ref({}); const classroomPendingError = ref(""); const classroomFilter = ref(""); const classroomRosterFile = ref(null); const studentSessionId = ref("");
const studentUploadProgress = ref(0); const studentSubmissionFiles = ref([]); const studentSubmissions = ref([]); const studentSubmissionLoading = ref(false); const studentSubmissionNotice = ref(""); const collaborationRoundId = ref(new URLSearchParams(window.location.search).get('round') || ''); const collaborationClaimId = ref(''); const collaborationFeature = ref(new URLSearchParams(window.location.search).get('feature') || ''); const collaborationState = ref(''); const collaborationQuestionSnapshot = ref(''); const collaborationAnswerDraft = ref('');
const teacherSubmissions = ref([]); const teacherSubmissionLoading = ref(false); const teacherSubmissionFilter = ref(""); const teacherSubmissionNoFilter = ref(""); const teacherSubmissionSort = ref("desc"); const teacherSubmissionDetail = ref(null); const teacherPreview = ref(null); const teacherQuestion = ref(null); const teacherQuestionLoading = ref(false);
const oralQuestionDraft = ref(""); const oralAnswerDraft = ref(""); const oralCurrentQuestion = ref(null); const oralAnswers = ref([]); const oralTeacherDrafts = ref([]); const oralTeacherState = ref(null); const oralActionLoading = ref(""); const oralActionResult = ref(null); const oralDraftTimers = {};
const collaborationRounds = ref({}); const collaborationClaims = ref({}); const collaborationEntries = ref({}); const collaborationBusy = ref(""); const collaborationTeacherEdited = ref({}); const collaborationPrompt = ref(null); const collaborationSeenClaims = ref({});
const answerRoundLocked = computed(() => collaborationRounds.value.answer_evaluate?.state === 'open');
async function openCollaboration(featureType, questionSnapshot) { if(!currentClassId.value || !classroomSession.value?.session_id){ classroomNotice.value='请先选择班级并开始课堂。'; return; } collaborationBusy.value=featureType; try { const previous=collaborationRounds.value[featureType]; if(previous?.state==='open') await cancelCollaborationRound(previous.round_id); const r=await createCollaborationRound({class_id:currentClassId.value,session_id:classroomSession.value.session_id,feature_type:featureType,question_snapshot:questionSnapshot||undefined}); collaborationRounds.value={...collaborationRounds.value,[featureType]:r}; classroomNotice.value=`已生成${featureType}协作二维码令牌，请展示加入链接。`; await refreshCollaborationClaims(featureType); if(featureType==='presentation_questions') await loadTeacherSubmissions(); } catch(e){ classroomNotice.value=e instanceof Error?e.message:'协作轮次创建失败'; } finally { collaborationBusy.value=''; } }
async function startAnswerCollaboration(){ const questionText=answerQuestionInput.value.trim(); if(!questionText){ classroomNotice.value='请先输入并确认题目，再生成答案评价二维码。'; return; } try{ await openCollaboration('answer_evaluate',questionText); collaborationTeacherEdited.value={...collaborationTeacherEdited.value,answer_evaluate:false}; }catch(e){ classroomNotice.value=e instanceof Error?e.message:'答案评价轮次创建失败'; } }
async function cancelAnswerRound(){ const round=collaborationRounds.value.answer_evaluate; if(!round)return; try{ await cancelCollaborationRound(round.round_id); collaborationRounds.value={...collaborationRounds.value,answer_evaluate:{...round,state:'cancelled'}}; classroomNotice.value='旧答案评价轮次已取消，可以重新出题。'; }catch(e){ classroomNotice.value=e instanceof Error?e.message:'取消答案评价轮次失败'; } }
async function refreshCollaborationClaims(featureType){ const r=collaborationRounds.value[featureType]; if(!r)return; try{ const [claims,entry]=await Promise.all([listCollaborationClaims(r.round_id),getCollaborationEntry(r.round_id)]); if(entry.round_state && entry.round_state !== r.state) collaborationRounds.value={...collaborationRounds.value,[featureType]:{...r,state:entry.round_state}}; collaborationClaims.value={...collaborationClaims.value,[featureType]:claims}; collaborationEntries.value={...collaborationEntries.value,[featureType]:entry}; const pending=claims.find(item=>item.state==='pending'); if(pending){ const seen=collaborationSeenClaims.value[featureType]; if(seen!==pending.claim_id){ collaborationSeenClaims.value={...collaborationSeenClaims.value,[featureType]:pending.claim_id}; collaborationPrompt.value={featureType,claim:pending}; } } else if(collaborationPrompt.value?.featureType===featureType){ collaborationPrompt.value=null; } if(!collaborationTeacherEdited.value[featureType] && entry && (entry.text || entry.answer)){ if(featureType==='question_optimize') optimizedQuestionInput.value=entry.text||''; else if(featureType==='answer_evaluate'){ answerQuestionInput.value=entry.text||''; studentAnswer.value=entry.answer||''; } } }catch(e){ classroomNotice.value=e instanceof Error?e.message:'协作申请加载失败'; } }
async function acceptClaim(featureType,id){ collaborationPrompt.value=null; await acceptCollaborationClaim(id); await refreshCollaborationClaims(featureType); }
async function rejectClaim(featureType,id){ collaborationPrompt.value=null; await rejectCollaborationClaim(id); await refreshCollaborationClaims(featureType); }
async function releaseClaim(featureType,id){ await releaseCollaborationClaim(id); await refreshCollaborationClaims(featureType); }
async function returnClaim(featureType,id){ await returnCollaborationClaim(id); collaborationTeacherEdited.value={...collaborationTeacherEdited.value,[featureType]:false}; await refreshCollaborationClaims(featureType); }
async function cancelClaim(featureType,id){ await cancelCollaborationClaim(id); await refreshCollaborationClaims(featureType); }
function markCollaborationTeacherEdited(){ const feature=isQuestionMode.value?'question_optimize':isAnswerMode.value?'answer_evaluate':''; if(feature) collaborationTeacherEdited.value={...collaborationTeacherEdited.value,[feature]:true}; }
function collaborationRoundForMode(){ return collaborationRounds.value[isQuestionMode.value?'question_optimize':isAnswerMode.value?'answer_evaluate':'presentation_questions']; }
const pdfViewerContainer = ref(null); const pdfCanvasRefs = ref([]); const pdfDocument = ref(null); const pdfPageCount = ref(0); const pdfRenderedPages = ref(new Set()); const pdfLoading = ref(false); const pdfError = ref(""); const pdfScale = ref(1.15); const pdfSourceBlob = ref(null); let pdfObserver = null;
async function loadClasses(){ if(!teachingCourseId.value)return; classroomClasses.value=await listClasses(teachingCourseId.value); if(classroomClasses.value.length && !classroomClasses.value.some(x=>x.class_id===classroomSession.value?.class_id)) classroomSession.value=null; }
async function addClass(){ if(!classroomName.value.trim())return; await createClass(teachingCourseId.value,classroomName.value.trim()); classroomName.value=""; await loadClasses(); }
async function beginClass(item){ currentClassId.value=item.class_id; classroomSession.value=await startSession(item.class_id); classroomSession.value.class_id=item.class_id; classroomJoinToken.value=classroomSession.value.join_token; try{ const info=await classroomJoinInfo(classroomSession.value.session_id,classroomJoinToken); classroomJoinUrl.value=info.join_url||""; if(info.qr_available){ const blob=await classroomQrBlob(classroomSession.value.session_id,classroomJoinToken); classroomQrUrl.value=URL.createObjectURL(blob); } }catch(error){ classroomNotice.value=error instanceof Error?error.message:"请先配置公网HTTPS地址"; } classroomStatus.value="教师课堂进行中"; classroomPending.value=[]; stopClassroomPolling(); classroomTimer.value=setInterval(pollClass,4000); await pollClass(); await loadTeacherSubmissions(); }
async function finishClass(){ if(classroomTimer.value)clearInterval(classroomTimer.value); if(classroomQrUrl.value){ URL.revokeObjectURL(classroomQrUrl.value); classroomQrUrl.value=""; } if(classroomSession.value){ const endedId=classroomSession.value.session_id; await endSession(endedId); classroomSession.value={...classroomSession.value,status:"ended"}; classroomStatus.value="课堂已结束"; if(classroomTimer.value)clearInterval(classroomTimer.value); await loadTeacherSubmissions(); } }
async function joinClass(){ if(!classroomJoinToken.value||!classroomStudentName.value.trim())return; const result=await joinSession(classroomJoinToken.value,classroomStudentName.value.trim()); classroomStatus.value=result.status==='confirmed'?"已进入课堂":"等待教师确认"; if(result.student_token)sessionStorage.setItem('class-student-token',result.student_token); }
async function sendClass(){ const body=classroomText.value.trim(); if(!body||!classroomSession.value)return; await sendClassMessage(classroomSession.value.session_id,body); classroomText.value=""; }
async function pollStudent(){ if(!studentEntry.value || !sessionStorage.getItem("class-student-token"))return; try{ const state=await studentState(); studentSessionId.value=state.session_id || studentSessionId.value; studentPending.value=state.status==='pending'; studentMessage.value=state.status==='confirmed'?'已确认进入课堂':state.status==='rejected'?'申请已拒绝':state.session_status==='ended'?'课堂已结束':'等待教师确认'; studentMessages.value=state.messages||[]; if(collaborationRoundId.value){ const collaboration=await collaborationStudentState(collaborationRoundId.value); collaborationState.value=collaboration.claim_state || collaboration.round_state || ''; collaborationClaimId.value=collaboration.claim_id || collaborationClaimId.value; collaborationQuestionSnapshot.value=collaboration.question_snapshot || ''; if(collaborationFeature.value==='answer_evaluate' && document.activeElement?.dataset?.collaborationAnswer !== 'true') collaborationAnswerDraft.value=collaboration.answer_text || ''; } if(state.status==='confirmed' && studentSessionId.value){ await loadStudentSubmissions(); await loadStudentOralState(); } }catch(error){studentMessage.value=error instanceof Error?error.message:'学生会话已失效';} }
async function joinStudent(){ if(!studentInput.value.trim())return; try{ const result=await joinSession(studentJoinToken.value,studentInput.value.trim()); studentSessionId.value=result.session_id || studentSessionId.value; if(result.student_token)sessionStorage.setItem('class-student-token',result.student_token); await pollStudent(); }catch(error){studentMessage.value=error instanceof Error?error.message:'加入失败';} }
async function requestCollaboration(){ if(!collaborationRoundId.value)return; try{ const result=await claimCollaborationToken(new URLSearchParams(window.location.search).get('round_token')||''); collaborationClaimId.value=result.claim_id; collaborationState.value=result.state; const state=await collaborationStudentState(collaborationRoundId.value); collaborationQuestionSnapshot.value=state.question_snapshot||''; }catch(error){studentMessage.value=error instanceof Error?error.message:'协作申请失败';} }
async function finishCollaboration(){ if(!collaborationClaimId.value)return; try{ await completeCollaborationClaim(collaborationClaimId.value); collaborationState.value='completed'; }catch(error){studentMessage.value=error instanceof Error?error.message:'协作完成失败';} }
async function syncCollaborationText(value){ if(!collaborationClaimId.value)return; try{ if(collaborationFeature.value==='answer_evaluate') await saveCollaborationEntry(collaborationClaimId.value,collaborationQuestionSnapshot.value, value); else await saveCollaborationEntry(collaborationClaimId.value,value,oralAnswerDraft.value); }catch(error){studentMessage.value=error instanceof Error?error.message:'协作草稿同步失败';} }
function leaveStudent(){ sessionStorage.removeItem("class-student-token"); window.location.href=window.location.pathname; }
async function sendStudent(){ const body=studentText.value.trim(); if(!body)return; await sendStudentMessage(body); studentText.value=""; await pollStudent(); }
const studentText = ref("");
async function loadStudentOralState(){ if(!studentSessionId.value)return; try{ const data=await studentOralState(studentSessionId.value); const question=data.current_question; oralCurrentQuestion.value=question; oralAnswers.value=data.answers||[]; const drafts=Object.fromEntries((data.drafts||[]).map(item=>[item.kind,item.body])); if(document.activeElement?.dataset?.oralInput !== 'question') oralQuestionDraft.value=drafts.question||""; if(document.activeElement?.dataset?.oralInput !== 'answer') oralAnswerDraft.value=drafts.answer||""; }catch(error){ studentSubmissionNotice.value=error instanceof Error?error.message:'口述输入同步失败'; } }
function debounceOralDraft(kind, body){ clearTimeout(oralDraftTimers[kind]); oralDraftTimers[kind]=setTimeout(async()=>{ try{ await saveOralDraft(studentSessionId.value,kind,body); }catch(error){ studentMessage.value=error instanceof Error?error.message:'草稿同步失败'; } },350); }
async function sendOralQuestion(){ if(!studentSessionId.value || !oralQuestionDraft.value.trim() || studentMessage.value==='课堂已结束')return; try{ await submitOralQuestion(studentSessionId.value,oralQuestionDraft.value.trim()); oralQuestionDraft.value=""; await loadStudentOralState(); }catch(error){ studentMessage.value=error instanceof Error?error.message:'问题提交失败'; } }
async function sendOralAnswer(){ if(!studentSessionId.value || !oralAnswerDraft.value.trim() || !oralCurrentQuestion.value || studentMessage.value==='课堂已结束')return; try{ await submitOralAnswer(studentSessionId.value,oralAnswerDraft.value.trim()); oralAnswerDraft.value=""; await loadStudentOralState(); }catch(error){ studentMessage.value=error instanceof Error?error.message:'回答提交失败'; } }
async function loadStudentSubmissions(){ if(!studentSessionId.value)return; studentSubmissionLoading.value=true; try{ const data=await listStudentSubmissions(studentSessionId.value); studentSubmissions.value=data.items||data.submissions||[]; }catch(error){studentSubmissionNotice.value=error instanceof Error?error.message:'提交记录加载失败';}finally{studentSubmissionLoading.value=false;} }
function onStudentSubmissionFiles(event){ studentSubmissionFiles.value=Array.from(event.target.files||[]); }
async function submitStudentMaterials(){ if(!studentSessionId.value || !studentSubmissionFiles.value.length || studentSubmissionLoading.value)return; const roundId=collaborationRoundId.value || collaborationRounds.value.presentation_questions?.round_id; if(!roundId){studentSubmissionNotice.value='请从当前汇报提问二维码进入后再上传。'; return;} studentSubmissionLoading.value=true; studentUploadProgress.value=0; studentSubmissionNotice.value=""; try{ await createSubmissionWithProgress(studentSessionId.value,studentSubmissionFiles.value,roundId,(value)=>studentUploadProgress.value=value); studentSubmissionFiles.value=[]; studentSubmissionNotice.value="提交成功"; await loadStudentSubmissions(); showToast("汇报材料提交成功"); }catch(error){studentSubmissionNotice.value=error instanceof Error?error.message:'提交失败，请检查文件后重试';}finally{studentSubmissionLoading.value=false;} }
async function loadTeacherSubmissions(){ if(!classroomSession.value?.session_id)return; const roundId=collaborationRounds.value.presentation_questions?.round_id; if(!roundId){ teacherSubmissions.value=[]; return; } teacherSubmissionLoading.value=true; try{ const data=await listSubmissions(classroomSession.value.session_id,{student_name:teacherSubmissionFilter.value||undefined,student_no:teacherSubmissionNoFilter.value||undefined,round_id:roundId,sort:teacherSubmissionSort.value,page:1,page_size:50}); teacherSubmissions.value=data.items||data.submissions||[]; await loadTeacherOralState(); }catch(error){classroomNotice.value=error instanceof Error?error.message:'汇报材料列表加载失败';}finally{teacherSubmissionLoading.value=false;} }
async function loadTeacherOralState(){ if(!classroomSession.value?.session_id)return; try{ oralTeacherState.value=await teacherOralState(classroomSession.value.session_id); oralTeacherDrafts.value=oralTeacherState.value.drafts||[]; }catch(error){ classroomNotice.value=error instanceof Error?error.message:'口述草稿加载失败'; } }
async function triggerOralAction(kind,item){ oralActionLoading.value=item.question_id||item.answer_id; oralActionResult.value=null; try{ oralActionResult.value=kind==='question'?await optimizeOralQuestion(item.question_id):await evaluateOralAnswer(item.answer_id); }catch(error){ classroomNotice.value=error instanceof Error?error.message:'教学处理失败'; }finally{ oralActionLoading.value=""; } }
async function openTeacherSubmission(item){ try{ teacherSubmissionDetail.value=await getSubmission(item.submission_id); teacherPreview.value=null; teacherQuestion.value=null; }catch(error){classroomNotice.value=error instanceof Error?error.message:'提交详情加载失败';} }
async function renderPdfPage(pageNumber){ const document=pdfDocument.value; const canvas=pdfCanvasRefs.value[pageNumber-1]; if(!document || !canvas || pdfRenderedPages.value.has(pageNumber))return; const page=await document.getPage(pageNumber); const viewport=page.getViewport({scale:pdfScale.value}); canvas.width=viewport.width; canvas.height=viewport.height; await page.render({canvasContext:canvas.getContext('2d'),viewport}).promise; pdfRenderedPages.value=new Set([...pdfRenderedPages.value,pageNumber]); }
function resetPdfViewer(){ if(pdfObserver){pdfObserver.disconnect();pdfObserver=null;} pdfDocument.value=null; pdfPageCount.value=0; pdfRenderedPages.value=new Set(); pdfCanvasRefs.value=[]; pdfError.value=""; }
async function loadPdfViewer(blob){ pdfSourceBlob.value=blob; resetPdfViewer(); pdfLoading.value=true; try{ const loadingTask=pdfjsLib.getDocument({data:await blob.arrayBuffer()}); const document=await loadingTask.promise; pdfDocument.value=document; pdfPageCount.value=document.numPages; await nextTick(); pdfObserver=new IntersectionObserver((entries)=>{ entries.filter(entry=>entry.isIntersecting).forEach(entry=>renderPdfPage(Number(entry.target.dataset.page))); },{root:pdfViewerContainer.value,rootMargin:'800px 0px'}); pdfCanvasRefs.value.forEach((canvas,index)=>{ if(canvas){canvas.dataset.page=String(index+1);pdfObserver.observe(canvas);} }); if(pdfPageCount.value) await renderPdfPage(1); }catch(error){pdfError.value=error instanceof Error?error.message:'PDF预览加载失败';}finally{pdfLoading.value=false;} }
async function zoomPdf(delta){ pdfScale.value=Math.min(2,Math.max(.7,pdfScale.value+delta)); if(pdfSourceBlob.value) await loadPdfViewer(pdfSourceBlob.value); }
async function previewTeacherFile(file){ try{ resetPdfViewer(); const id=file.file_id||file.id; const meta=await previewSubmissionFile(id); if(meta.preview_type==='pdf'){ const blob=await downloadSubmissionPreviewPdf(id); teacherPreview.value={...meta,url:URL.createObjectURL(blob)}; await loadPdfViewer(blob); }else{ teacherPreview.value={...meta,url:URL.createObjectURL(await downloadSubmissionFile(id))}; } }catch(error){pdfError.value=error instanceof Error?error.message:'文件预览失败';classroomNotice.value=pdfError.value;} }
async function downloadTeacherOriginal(file){ try{ const blob=await downloadSubmissionFile(file.file_id||file.id); const url=URL.createObjectURL(blob); const anchor=document.createElement('a'); anchor.href=url; anchor.download=file.filename; anchor.click(); URL.revokeObjectURL(url); }catch(error){ classroomNotice.value=error instanceof Error?error.message:'原文件下载失败'; } }
async function askTeacherQuestion(file){ if(classroomSession.value?.status==='ended')return; teacherQuestionLoading.value=true; try{ teacherQuestion.value=await generateSubmissionQuestion(file.file_id||file.id); }catch(error){classroomNotice.value=error instanceof Error?error.message:'提问失败';}finally{teacherQuestionLoading.value=false;} }
async function pollClass(){ if(classroomSession.value){ if(classroomSession.value.status==='ended'){ if(classroomTimer.value) clearInterval(classroomTimer.value); return; } classroomMessages.value=await pollClassMessages(classroomSession.value.session_id); classroomPending.value=await listPendingStudents(classroomSession.value.session_id); await loadTeacherOralState(); await Promise.all(Object.keys(collaborationRounds.value).map(refreshCollaborationClaims)); } if(studentSessionId.value && classroomSession.value){ const state=await studentStatus(classroomSession.value.session_id); classroomStatus.value=state.status==='confirmed'?'已确认进入课堂':state.status==='rejected'?'申请已拒绝':'等待教师确认'; } }
async function confirmPending(item,studentId){ if(classroomPendingBusy.value[item.session_student_id])return; classroomPendingBusy.value={...classroomPendingBusy.value,[item.session_student_id]:true}; classroomPendingError.value=""; try{ await confirmStudent(classroomSession.value.session_id,item.session_student_id,studentId); classroomStatus.value="已确认学生进入课堂"; await pollClass(); }catch(error){ classroomPendingError.value=error instanceof Error?error.message:"确认失败，请刷新后重试"; }finally{ const next={...classroomPendingBusy.value}; delete next[item.session_student_id]; classroomPendingBusy.value=next; } }
async function rejectPending(item){ if(classroomPendingBusy.value[item.session_student_id])return; classroomPendingBusy.value={...classroomPendingBusy.value,[item.session_student_id]:true}; classroomPendingError.value=""; try{ await rejectStudent(classroomSession.value.session_id,item.session_student_id); classroomStatus.value="已拒绝该申请"; await pollClass(); }catch(error){ classroomPendingError.value=error instanceof Error?error.message:"拒绝失败，请刷新后重试"; }finally{ const next={...classroomPendingBusy.value}; delete next[item.session_student_id]; classroomPendingBusy.value=next; } }
function onRosterFile(e){ classroomRosterFile.value=e.target.files?.[0]||null; }
async function uploadRoster(item){ if(!classroomRosterFile.value)return; await importRoster(item.class_id,classroomRosterFile.value); classroomRosterFile.value=null; }


let toastTimer = null;

const FEATURES = [
  {
    mode: "question",
    number: "01",
    title: "优化问题",
    className: "feature-question",
  },
  {
    mode: "answer",
    number: "02",
    title: "评价答案",
    className: "feature-answer",
  },
  {
    mode: "presentation",
    number: "03",
    title: "课程汇报提问",
    className: "feature-presentation",
  },
];
const QUESTION_LEVEL_CLASSES = {
  easy: "level-easy",
  medium: "level-medium",
  hard: "level-hard",
};
const EVALUATION_LEVEL_CLASSES = {
  简单: "evaluation-simple",
  思考型: "evaluation-thinking",
  深度型: "evaluation-deep",
};
const PRESENTATION_FILE_TYPES = [".pptx", ".docx", ".md", ".txt", ".pdf"];
const MAX_PRESENTATION_FILES = 10;
const MAX_PRESENTATION_FILE_BYTES = 50 * 1024 * 1024;
const MAX_PRESENTATION_TOTAL_FILE_BYTES = 100 * 1024 * 1024;

const CHAPTER_PAGE_REFERENCE_PATTERN =
  /第\s*(\d+)\s*章(?:《([^》]+)》)?\s*[，,]?\s*第\s*(\d+)(?:\s*[-—–~～至到]\s*(\d+))?\s*页/g;

function formatCourseReferences(value) {
  if (typeof value !== "string" || !value) return value;

  const matches = [...value.matchAll(CHAPTER_PAGE_REFERENCE_PATTERN)];
  if (!matches.length) return value;

  const groups = new Map();
  for (const match of matches) {
    const chapter = Number(match[1]);
    const title = match[2] || "";
    const start = Number(match[3]);
    const end = Number(match[4] || match[3]);
    if (!Number.isInteger(chapter) || !Number.isInteger(start) || end < start)
      continue;

    const key = String(chapter);
    if (!groups.has(key)) groups.set(key, { chapter, title, pages: new Set() });
    const group = groups.get(key);
    if (!group.title && title) group.title = title;
    for (let page = start; page <= end; page += 1) group.pages.add(page);
  }

  if (!groups.size) return value;

  const formatPages = (pages) => {
    const sorted = [...pages].sort((a, b) => a - b);
    const ranges = [];
    let start = sorted[0];
    let previous = sorted[0];
    for (const page of sorted.slice(1)) {
      if (page === previous + 1) {
        previous = page;
        continue;
      }
      ranges.push(start === previous ? String(start) : `${start}-${previous}`);
      start = previous = page;
    }
    ranges.push(start === previous ? String(start) : `${start}-${previous}`);
    return ranges.join("、");
  };

  const citation = [...groups.values()]
    .map(({ chapter, title, pages }) => {
      const chapterName = title
        ? `第${chapter}章《${title}》`
        : `第${chapter}章`;
      return `${chapterName}，第${formatPages(pages)}页`;
    })
    .join("；");

  let remaining = value
    .replace(CHAPTER_PAGE_REFERENCE_PATTERN, "")
    .replace(/\s{2,}/g, " ")
    .trim();
  if (!remaining.replace(/[；;，,\s]/g, "")) return citation;
  remaining = remaining.replace(/^[；;，,\s]+|[；;，,\s]+$/g, "");
  return remaining ? `${remaining}（${citation}）` : citation;
}

const isQuestionMode = computed(() => mode.value === "question");
const isAnswerMode = computed(() => mode.value === "answer");
const isPresentationMode = computed(() => mode.value === "presentation");
const isHomePage = computed(() => page.value === "home");
const isTeachingHome = computed(() => page.value === "teaching-home");
const isTeachingSelect = computed(() => page.value === "teaching-select");
const isHistoryPage = computed(() => page.value === "teaching-history");
const isAnalyticsPage = computed(() => page.value === "teaching-analytics");
const isPrepPage = computed(() => page.value.startsWith("prep-"));
const isPresetCourse = computed(
  () => selectedCourse.value?.id === "default",
);
const isInputPage = computed(() => page.value === "input");
const isResultPage = computed(() => page.value === "result");
const currentFeature = computed(() =>
  FEATURES.find((feature) => feature.mode === mode.value),
);
const question = computed({
  get: () =>
    isAnswerMode.value
      ? answerQuestionInput.value
      : optimizedQuestionInput.value,
  set: (value) => {
    if (isAnswerMode.value) answerQuestionInput.value = value;
    else optimizedQuestionInput.value = value;
  },
});
const hasPresentationText = computed(() =>
  Boolean(presentationText.value.trim()),
);
const presentationQuestions = computed(() => {
  if (!Array.isArray(result.value?.questions)) return [];
  return [...result.value.questions].sort(
    (left, right) => Number(left.score) - Number(right.score),
  );
});
const presentationQuestionGroups = computed(() =>
  [
    { level: "easy", label: "简单", score: 60 },
    { level: "medium", label: "中等", score: 80 },
    { level: "hard", label: "困难", score: 100 },
  ].map((group) => ({
    ...group,
    questions: presentationQuestions.value.filter(
      (item) => item.level === group.level,
    ),
  })),
);
const canSubmit = computed(() => {
  if (!teachingCourseId.value) return false;
  if (isPresentationMode.value) {
    return (
      (presentationFiles.value.some(file => !excludedPresentationFiles.value.includes(file)) || (includePresentationText.value && hasPresentationText.value)) &&
      presentationText.value.length <= 30000
    );
  }
  if (!question.value.trim() || question.value.length > 1000) return false;
  if (isAnswerMode.value) {
    return (
      Boolean(studentAnswer.value.trim()) && studentAnswer.value.length <= 1000
    );
  }
  return true;
});

function resetResultState() {
  result.value = null;
  errorMessage.value = "";
  revealedOptimizedQuestions.value = [];
  revealedPresentationQuestions.value = [];
}

function openFeature(nextMode) {
  if (loading.value) return;
  if (!teachingCourseId.value) {
    openTeaching();
    return;
  }
  mode.value = nextMode;
  resetResultState();
  const featureType = nextMode === "question" ? "question_optimize" : nextMode === "answer" ? "answer_evaluate" : "presentation_questions";
  if (classroomSession.value?.session_id && featureType !== "answer_evaluate" && !collaborationRounds.value[featureType]) openCollaboration(featureType, optimizedQuestionInput.value);
  page.value = "input";
}

async function openPrep() {
  page.value = "prep-list";
  courseError.value = "";
  courseLoading.value = true;
  try {
    const items = await listCourses();
    teachingCourseId.value =
      items.find((course) => course.name === "人工智能概论")?.id ||
      teachingCourseId.value;
    courses.value = await Promise.all(
      items.map(async (course) => ({
        ...course,
        _materialCount: (await listMaterials(course.id)).length,
      })),
    );
  } catch (error) {
    courseError.value = error instanceof Error ? error.message : "加载课程失败";
  } finally {
    courseLoading.value = false;
  }
}
async function openTeaching() {
  page.value = "teaching-select";
  teachingError.value = "";
  teachingLoading.value = true;
  clearCurrentSession();
  try {
    teachingCourses.value = await listCourses();
  } catch (error) {
    teachingError.value =
      error instanceof Error ? error.message : "加载课程失败";
  } finally {
    teachingLoading.value = false;
  }
}
function chooseTeachingCourse(course) {
  if (course.status !== "ready") return;
  teachingCourseId.value = course.id;
  teachingCourseName.value = course.name;
  resetResultState();
  optimizedQuestionInput.value = "";
  answerQuestionInput.value = "";
  studentAnswer.value = "";
  presentationFiles.value = [];
  presentationText.value = "";
  page.value = "teaching-home";
}
function switchTeachingCourse() {
  teachingCourseId.value = "";
  teachingCourseName.value = "";
  clearCurrentSession();
  openTeaching();
}
function goBack() {
  if (isResultPage.value) {
    clearCurrentSession();
    page.value = "teaching-home";
  } else if (page.value === "teaching-home") openTeaching();
  else if (isTeachingSelect.value || page.value === "prep-list") goHome(false);
  else if (page.value === "prep-form" || page.value === "prep-detail")
    openPrep();
  else if (isHistoryPage.value || isAnalyticsPage.value)
    page.value = "teaching-home";
  else if (isInputPage.value) {
    clearCurrentSession();
    page.value = "teaching-home";
  } else goHome(false);
}
async function openHistory() {
  page.value = "teaching-history";
  historyPage.value = 1;
  historyDetail.value = null;
  await loadHistory();
}
async function loadHistory() {
  if (!teachingCourseId.value) return;
  historyLoading.value = true;
  historyError.value = "";
  try {
    const data = await listHistory(teachingCourseId.value, {
      task_type: historyTaskType.value || undefined,
      class_id: historyClassId.value || undefined,
      created_from: historyFrom.value || undefined,
      created_to: historyTo.value || undefined,
      page: historyPage.value,
      page_size: historyPageSize.value,
    });
    historyItems.value = data.items;
    historyTotal.value = data.total;
  } catch (error) {
    historyError.value =
      error instanceof Error ? error.message : "加载历史失败";
  } finally {
    historyLoading.value = false;
  }
}
async function showHistoryDetail(item) {
  try {
    historyDetail.value = await getHistoryEvent(
      teachingCourseId.value,
      item.id,
    );
  } catch (error) {
    historyError.value =
      error instanceof Error ? error.message : "加载详情失败";
  }
}
async function removeHistory(item) {
  if (!window.confirm("确认删除这条历史记录？")) return;
  try {
    await deleteHistoryEvent(teachingCourseId.value, item.id);
    await loadHistory();
    historyDetail.value = null;
  } catch (error) {
    historyError.value =
      error instanceof Error ? error.message : "删除历史失败";
  }
}
async function removeAllHistory() {
  if (!window.confirm(`确认清空“${teachingCourseName.value}”的全部历史记录？`))
    return;
  try {
    await clearHistory(teachingCourseId.value);
    await loadHistory();
    historyDetail.value = null;
  } catch (error) {
    historyError.value =
      error instanceof Error ? error.message : "清空历史失败";
  }
}
function showToast(message) {
  toastMessage.value = message;
  if (toastTimer) window.clearTimeout(toastTimer);
  toastTimer = window.setTimeout(() => {
    toastMessage.value = "";
  }, 2400);
}
function safeFilename(value) {
  return value.replace(/[<>:"/\\|?*]/g, "-");
}
function submissionMarkdown(value) {
  const escaped = String(value || "").replace(/[&<>\"']/g, (character) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[character]);
  return escaped.replace(/^### (.*)$/gm, "<h4>$1</h4>").replace(/^## (.*)$/gm, "<h3>$1</h3>").replace(/^# (.*)$/gm, "<h2>$1</h2>").replace(/^[-*] (.*)$/gm, "<li>$1</li>").replace(/```([\s\S]*?)```/g, "<pre>$1</pre>").replace(/\n{2,}/g, "</p><p>").replace(/\n/g, "<br>").replace(/^/, "<p>").replace(/$/, "</p>");
}
async function saveBlob(blob, filename) {
  if (window.__TAURI_INTERNALS__) {
    const { invoke } = await import("@tauri-apps/api/core");
    const bytes = Array.from(new Uint8Array(await blob.arrayBuffer()));
    return invoke("save_export_file", { filename, bytes });
  }
  if (typeof window.showSaveFilePicker === "function") {
    try {
      const handle = await window.showSaveFilePicker({ suggestedName: filename });
      const writable = await handle.createWritable();
      await writable.write(blob);
      await writable.close();
      return handle.name;
    } catch (error) {
      if (error?.name === "AbortError") return null;
      throw error;
    }
  }
  throw new Error("当前环境不支持系统保存窗口，请在桌面应用中导出。");
}
async function exportHistory() {
  try {
    const blob = await downloadHistoryCsv(teachingCourseId.value, {
      task_type: historyTaskType.value || undefined,
      created_from: historyFrom.value || undefined,
      created_to: historyTo.value || undefined,
    });
    const savedPath = await saveBlob(
      blob,
      safeFilename(`teaching-history-${teachingCourseName.value}.csv`),
    );
    if (savedPath) showToast("下载成功！");
  } catch (error) {
    historyError.value =
      error instanceof Error ? error.message : "历史记录导出失败";
  }
}
function formatHistoryTime(value) {
  try {
    return new Date(value).toLocaleString("zh-CN");
  } catch {
    return value;
  }
}
function historySummary(item) {
  const input = item.input_json || {};
  if (typeof input.question === "string") return input.question.slice(0, 100);
  if (typeof input.text_length === "number")
    return `汇报材料（${input.text_length}字）`;
  return "教学操作记录";
}
const reportLabels = {
  score_distribution: "成绩分布",
  common_issues: "常见薄弱点",
  frequent_chapters: "课程依据",
  low_score_knowledge_points: "待改进知识点",
  usage_counts: "功能使用情况",
};
const taskLabels = {
  question_optimize: "问题优化",
  answer_evaluate: "答案评价",
  presentation_questions: "汇报提问",
};
function humanizeReportText(value) {
  const labels = {
    ...reportLabels,
    sample_size: "记录总数",
    data_insufficient: "数据是否充足",
    scores: "得分记录",
    levels: "评价等级",
    count: "出现次数",
    weakness: "薄弱表现",
    advice: "改进建议",
    course_basis: "课程依据",
    basis: "课程依据",
    question_optimize: "问题优化",
    answer_evaluate: "答案评价",
    presentation_questions: "汇报提问",
    task_type: "教学功能",
    input_summary: "问题概括",
    event_id: "记录编号",
  };
  return Object.entries(labels).reduce(
    (text, [key, label]) => text.replaceAll(key, label),
    String(value || ""),
  );
}
function reportSectionLabel(section) {
  return reportLabels[section] || humanizeReportText(section);
}
async function openAnalytics() {
  page.value = "teaching-analytics";
  await loadAnalytics();
}
async function loadAnalytics() {
  if (!teachingCourseId.value) return;
  analyticsLoading.value = true;
  analyticsError.value = "";
  try {
    analyticsData.value = await getAnalytics(teachingCourseId.value, {
      created_from: analyticsFrom.value || undefined,
      created_to: analyticsTo.value || undefined,
    });
  } catch (error) {
    analyticsError.value =
      error instanceof Error ? error.message : "加载学情统计失败";
  } finally {
    analyticsLoading.value = false;
  }
}
async function generateLearningReport() {
  reportLoading.value = true;
  reportError.value = "";
  try {
    learningReport.value = await createLearningReport(teachingCourseId.value, {
      created_from: analyticsFrom.value || undefined,
      created_to: analyticsTo.value || undefined,
    });
  } catch (error) {
    reportError.value = error instanceof Error ? error.message : "生成报告失败";
  } finally {
    reportLoading.value = false;
  }
}
async function exportReport(format) {
  try {
    const blob = await exportLearningReport(
      teachingCourseId.value,
      format,
      learningReport.value,
    );
    const savedPath = await saveBlob(
      blob,
      safeFilename(`learning-report-${teachingCourseName.value}.${format}`),
    );
    if (savedPath) showToast("下载成功！");
  } catch (error) {
    reportError.value =
      error instanceof Error ? error.message : "学情报告导出失败";
  }
}
function resetCourseForm() {
  courseForm.value = {
    name: "",
    description: "",
    grade_level: "",
    teaching_goal: "",
  };
}
async function saveCourse() {
  if (courseSaving.value) return;
  courseSaving.value = true;
  courseError.value = "";
  try {
    await (selectedCourse.value
      ? updateCourse(selectedCourse.value.id, courseForm.value)
      : createCourse(courseForm.value));
    await openPrep();
    showToast("保存成功！");
  } catch (error) {
    courseError.value = error instanceof Error ? error.message : "保存课程失败";
  } finally {
    courseSaving.value = false;
  }
}
async function openCourse(id) {
  selectedCourse.value =
    courses.value.find((item) => item.id === id) || selectedCourse.value;
  if (!selectedCourse.value) return;
  page.value = "prep-detail";
  courseLoading.value = true;
  courseError.value = "";
  try {
    courseMaterials.value = await listMaterials(id);
    selectedCourse.value =
      courses.value.find((item) => item.id === id) || selectedCourse.value;
    const status = await getBuildStatus(id);
    selectedCourse.value = { ...selectedCourse.value, status: status.status };
    if (status.error) courseNotice.value = status.error;
  } catch (error) {
    courseError.value =
      error instanceof Error ? error.message : "加载课程详情失败";
  } finally {
    courseLoading.value = false;
  }
}
async function removeCourse(course) {
  if (!window.confirm(`确认删除课程“${course.name}”？`)) return;
  try {
    await deleteCourse(course.id);
    await openPrep();
  } catch (error) {
    courseError.value = error instanceof Error ? error.message : "删除课程失败";
  }
}
async function handleCourseFile(event) {
  const files = Array.from(event.target.files || []);
  event.target.value = "";
  await uploadCourseFiles(files);
}
async function uploadCourseFiles(files) {
  for (const file of files) {
    try {
      await uploadMaterial(selectedCourse.value.id, file);
    } catch (error) {
      courseError.value =
        error instanceof Error ? error.message : "上传资料失败";
    }
  }
  await openCourse(selectedCourse.value.id);
}
async function removeMaterial(material) {
  if (!window.confirm(`确认删除资料“${material.filename}”？`)) return;
  try {
    await deleteMaterial(selectedCourse.value.id, material.id);
    courseNotice.value = "资料已删除，如需使用请重新构建知识库。";
    await openCourse(selectedCourse.value.id);
  } catch (error) {
    courseError.value = error instanceof Error ? error.message : "删除资料失败";
  }
}
async function rebuildCourse() {
  courseLoading.value = true;
  courseError.value = "";
  try {
    const courseId = selectedCourse.value.id;
    let status = await buildCourse(courseId);
    if (status.status === "building") {
      courseNotice.value = "正在解析资料并构建知识库，请稍候...";
      for (let attempt = 0; attempt < 180; attempt += 1) {
        await new Promise((resolve) => setTimeout(resolve, 2000));
        status = await getBuildStatus(courseId);
        if (status.status !== "building") break;
      }
    }
    courseNotice.value =
      status.error ||
      (status.status === "ready" ? "知识库构建完成。" : "知识库构建失败，请查看错误信息后重试。");
    await openCourse(selectedCourse.value.id);
  } catch (error) {
    courseError.value = error instanceof Error ? error.message : "构建失败";
  } finally {
    courseLoading.value = false;
  }
}
onMounted(async () => {
  window.addEventListener("account-session-expired", sessionExpired);
  if(studentEntry.value){ await pollStudent(); studentTimer.value=setInterval(pollStudent,4000); }
  try { schoolImageUrl.value = (await authUiConfig()).school_image_url; } catch { schoolImageUrl.value = ""; }
  try { account.value = await currentAccount(); }
  catch { clearSession(); account.value = null; }
  finally { authChecking.value = false; }
});
onUnmounted(() => { window.removeEventListener("account-session-expired", sessionExpired); if(classroomTimer.value) clearInterval(classroomTimer.value); if(studentTimer.value) clearInterval(studentTimer.value); if(classroomQrUrl.value) URL.revokeObjectURL(classroomQrUrl.value); resetPdfViewer(); });

function stopClassroomPolling() { if (classroomTimer.value) { clearInterval(classroomTimer.value); classroomTimer.value = null; } }

function clearCurrentSession() {
  stopClassroomPolling();
  if (isQuestionMode.value) optimizedQuestionInput.value = "";
  if (isAnswerMode.value) {
    answerQuestionInput.value = "";
    studentAnswer.value = "";
  }
  if (isPresentationMode.value) {
    presentationFiles.value = [];
    presentationText.value = "";
    materialPreviews.value = [];
    excludedPresentationFiles.value = [];
    includePresentationText.value = true;
    if (fileInput.value) fileInput.value.value = "";
  }
  resetResultState();
}

function goHome(clearInput = false) {
  if (loading.value) return;
  if (clearInput) clearCurrentSession();
  else resetResultState();
  page.value = "home";
}

function returnToInput() {
  if (loading.value || !mode.value) return;
  clearCurrentSession();
  page.value = "input";
}

function toggleOptimizedQuestion(index) {
  revealedOptimizedQuestions.value = revealedOptimizedQuestions.value.includes(
    index,
  )
    ? revealedOptimizedQuestions.value.filter(
        (itemIndex) => itemIndex !== index,
      )
    : [...revealedOptimizedQuestions.value, index];
}

function isOptimizedQuestionRevealed(index) {
  return revealedOptimizedQuestions.value.includes(index);
}

function togglePresentationQuestion(index) {
  revealedPresentationQuestions.value =
    revealedPresentationQuestions.value.includes(index)
      ? revealedPresentationQuestions.value.filter(
          (itemIndex) => itemIndex !== index,
        )
      : [...revealedPresentationQuestions.value, index];
}

function isPresentationQuestionRevealed(index) {
  return revealedPresentationQuestions.value.includes(index);
}

function setPresentationFiles(files) {
  const selectedFiles = Array.from(files || []);
  if (!selectedFiles.length) return;

  const unsupportedFile = selectedFiles.find((file) => {
    const dotIndex = file.name.lastIndexOf(".");
    const extension =
      dotIndex >= 0 ? file.name.slice(dotIndex).toLowerCase() : "";
    return !PRESENTATION_FILE_TYPES.includes(extension);
  });
  if (unsupportedFile) {
    errorMessage.value = `文件“${unsupportedFile.name}”格式不受支持，请上传PPTX、DOCX、MD或TXT文件。`;
    return;
  }

  const oversizedFile = selectedFiles.find(
    (file) => file.size > MAX_PRESENTATION_FILE_BYTES,
  );
  if (oversizedFile) {
    errorMessage.value = `文件“${oversizedFile.name}”超过单文件50MB限制。`;
    return;
  }

  const existingKeys = new Set(
    presentationFiles.value.map(
      (file) => `${file.name}\u0000${file.size}\u0000${file.lastModified}`,
    ),
  );
  const addedKeys = new Set();
  const newFiles = selectedFiles.filter((file) => {
    const key = `${file.name}\u0000${file.size}\u0000${file.lastModified}`;
    if (existingKeys.has(key) || addedKeys.has(key)) return false;
    addedKeys.add(key);
    return true;
  });
  const combinedFiles = [...presentationFiles.value, ...newFiles];

  if (combinedFiles.length > MAX_PRESENTATION_FILES) {
    errorMessage.value = "一次最多上传10个文件，本次新增文件未添加。";
    return;
  }

  const totalBytes = combinedFiles.reduce(
    (total, file) => total + file.size,
    0,
  );
  if (totalBytes > MAX_PRESENTATION_TOTAL_FILE_BYTES) {
    errorMessage.value = "本次所有文件合计不能超过100MB，本次新增文件未添加。";
    return;
  }

  presentationFiles.value = combinedFiles;
  materialPreviews.value = [];
  errorMessage.value = "";
}

function handleFileInput(event) {
  setPresentationFiles(event.target.files);
  event.target.value = "";
}

function removePresentationFile(index) {
  presentationFiles.value = presentationFiles.value.filter(
    (_, fileIndex) => fileIndex !== index,
  );
}

function openFilePicker() {
  fileInput.value?.click();
}

function formatFileSize(size) {
  if (size < 1024 * 1024) return `${Math.max(1, Math.round(size / 1024))} KB`;
  return `${(size / (1024 * 1024)).toFixed(1)} MB`;
}

async function submit() {
  if (loading.value) return;
  if (!canSubmit.value) {
    if (isPresentationMode.value) {
      errorMessage.value = "请上传一个文件或输入纯文本材料。";
    }
    return;
  }
  loading.value = true;
  errorMessage.value = "";
  result.value = null;
  revealedOptimizedQuestions.value = [];
  revealedPresentationQuestions.value = [];

  try {
    let nextResult;
    const round = collaborationRoundForMode();
    if (round && (isQuestionMode.value || isAnswerMode.value)) {
      await saveTeacherCollaborationEntry(round.round_id, question.value.trim(), isAnswerMode.value ? studentAnswer.value.trim() : "");
      nextResult = await submitCollaborationRound(round.round_id);
    } else if (isQuestionMode.value) {
      nextResult = await optimizeQuestion(question.value.trim(), teachingCourseId.value);
    } else if (isAnswerMode.value) {
      nextResult = await evaluateAnswer(question.value.trim(), studentAnswer.value.trim(), teachingCourseId.value);
    } else {
      nextResult = await generatePresentationQuestions(
        presentationFiles.value.filter(file => !excludedPresentationFiles.value.includes(file)),
        includePresentationText.value ? presentationText.value : "",
        teachingCourseId.value,
      );
    }
    result.value = nextResult;
    page.value = "result";
  } catch (error) {
    errorMessage.value =
      error instanceof Error ? error.message : "请求失败，请稍后重试。";
  } finally {
    loading.value = false;
  }
}
</script>

<template>
  <section v-if="studentEntry" class="auth-screen"><div class="auth-card"><h1>加入课堂</h1><section v-if="collaborationPrompt" class="message error-message" role="dialog"><strong>收到新的协作申请：{{ collaborationPrompt.featureType }}</strong><p>{{ collaborationPrompt.claim.requested_name || collaborationPrompt.claim.name || '学生' }} 正在申请加入。</p><button class="submit-button" type="button" @click="acceptClaim(collaborationPrompt.featureType,collaborationPrompt.claim.claim_id)">接受</button><button class="text-button" type="button" @click="rejectClaim(collaborationPrompt.featureType,collaborationPrompt.claim.claim_id)">拒绝</button></section><section v-if="collaborationRoundId" class="message notice-message"><strong>学生协作：{{ collaborationFeature || "课堂任务" }}</strong><p v-if="collaborationState">当前状态：{{ collaborationState }}</p><template v-if="collaborationFeature === 'answer_evaluate'"><p><strong>教师锁定题目：</strong>{{ collaborationQuestionSnapshot || '等待题目快照' }}</p><textarea v-if="collaborationState === 'accepted'" data-collaboration-answer="true" v-model="collaborationAnswerDraft" @input="syncCollaborationText(collaborationAnswerDraft)" placeholder="输入对该题目的回答"></textarea></template><textarea v-else-if="collaborationFeature === 'question_optimize' && collaborationState === 'accepted'" v-model="oralQuestionDraft" @input="debounceOralDraft('question', oralQuestionDraft); syncCollaborationText(oralQuestionDraft)" placeholder="输入协作内容"></textarea><button v-if="!collaborationState" class="submit-button" type="button" @click="requestCollaboration">申请开始</button><button v-if="collaborationState === 'accepted'" class="submit-button" type="button" @click="finishCollaboration">完成本轮</button></section><section v-if="collaborationFeature === 'presentation_questions'" class="message notice-message"><strong>汇报提问材料</strong><p>当前轮次：{{ collaborationRoundId }}</p><input type="file" multiple accept=".pdf,.pptx,.docx,.txt,.md" @change="onStudentSubmissionFiles" :disabled="studentSubmissionLoading || collaborationState !== 'accepted'" /><button class="submit-button" type="button" :disabled="studentSubmissionLoading || !studentSubmissionFiles.length || collaborationState !== 'accepted'" @click="submitStudentMaterials">{{ studentSubmissionLoading ? '正在上传...' : '上传当前轮次材料' }}</button><progress v-if="studentSubmissionLoading" max="100" :value="studentUploadProgress">{{ studentUploadProgress }}%</progress><button v-if="collaborationState === 'accepted'" class="submit-button" type="button" @click="finishCollaboration">完成本轮</button><p v-if="studentSubmissionNotice">{{ studentSubmissionNotice }}</p></section><p v-if="!sessionStorage.getItem('class-student-token')">请输入姓名后等待教师确认</p><input v-if="!sessionStorage.getItem('class-student-token')" v-model="studentInput" maxlength="100" placeholder="姓名" /><button v-if="!sessionStorage.getItem('class-student-token')" class="submit-button" type="button" @click="joinStudent">加入课堂</button><p class="message notice-message">{{ studentMessage }}</p><button v-if="sessionStorage.getItem('class-student-token')" class="text-button" type="button" @click="pollStudent">刷新状态</button><button v-if="sessionStorage.getItem('class-student-token')" class="text-button" type="button" @click="leaveStudent">退出课堂</button><div v-if="!studentPending && (studentMessage === '已确认进入课堂' || studentMessage === '课堂已结束')"><input v-model="studentText" maxlength="1000" placeholder="输入消息" :disabled="studentMessage === '课堂已结束'" /><button class="submit-button" type="button" :disabled="studentMessage === '课堂已结束'" @click="sendStudent">发送</button><ul><li v-for="(item,index) in studentMessages" :key="index">{{ item.body }} · {{ item.created_at }}</li></ul><hr /><h3>课堂口述输入</h3><label>提问<textarea data-oral-input="question" v-model="oralQuestionDraft" maxlength="2000" :disabled="studentMessage === '课堂已结束'" @input="debounceOralDraft('question', oralQuestionDraft)" placeholder="可使用手机输入法语音输入"></textarea></label><button class="submit-button" type="button" :disabled="!oralQuestionDraft.trim() || studentMessage === '课堂已结束'" @click="sendOralQuestion">提交问题</button><section v-if="oralCurrentQuestion" class="message notice-message"><strong>当前待回答问题</strong><p>整理版：{{ oralCurrentQuestion.cleaned_text }}</p><details><summary>查看问题原话</summary><p>{{ oralCurrentQuestion.original_text }}</p></details></section><section v-else class="message notice-message">当前没有待回答问题，回答入口已禁用。</section><label>回答<textarea data-oral-input="answer" v-model="oralAnswerDraft" maxlength="2000" :disabled="!oralCurrentQuestion || studentMessage === '课堂已结束'" @input="debounceOralDraft('answer', oralAnswerDraft)" placeholder="先等待课堂中出现待回答问题"></textarea></label><button class="submit-button" type="button" :disabled="!oralCurrentQuestion || !oralAnswerDraft.trim() || studentMessage === '课堂已结束'" @click="sendOralAnswer">提交回答</button><hr /><h3>提交汇报材料</h3><p class="muted-text">课堂进行中可提交，提交后不能修改或删除。</p><input type="file" multiple accept=".pdf,.pptx,.docx,.txt,.md" @change="onStudentSubmissionFiles" :disabled="studentMessage === '课堂已结束' || studentSubmissionLoading" /><button class="submit-button" type="button" :disabled="studentMessage === '课堂已结束' || !studentSubmissionFiles.length || studentSubmissionLoading" @click="submitStudentMaterials">{{ studentSubmissionLoading ? '正在上传...' : '提交材料' }}</button><p v-if="studentSubmissionNotice" class="message notice-message">{{ studentSubmissionNotice }}</p><div v-if="studentSubmissions.length"><h4>我的提交记录</h4><article v-for="submission in studentSubmissions" :key="submission.submission_id" class="history-detail"><strong>{{ formatHistoryTime(submission.created_at) }}</strong><span> · {{ submission.status }}</span><ul><li v-for="file in submission.files" :key="file.file_id">{{ file.filename }}（{{ file.file_type.toUpperCase() }}，{{ file.size_bytes }} bytes）</li></ul></article></div></div></div></section>
  <section v-else-if="!account || authChecking" class="auth-screen" :style="schoolImageUrl ? { backgroundImage: `linear-gradient(rgba(18, 45, 47, .45), rgba(18, 45, 47, .45)), url(${JSON.stringify(schoolImageUrl)})` } : {}">
    <div class="auth-card">
      <h1>课程教学助手</h1>
      <p>登录后管理自己的课程与教学记录</p>
      <p v-if="authChecking" role="status">正在检查登录状态...</p>
      <template v-else>
        <div class="auth-switch"><button type="button" :disabled="authPending" :class="{ active: authMode === 'login' }" @click="switchAuth('login')">登录</button><button type="button" :disabled="authPending" :class="{ active: authMode === 'register' }" @click="switchAuth('register')">注册</button></div>
        <form @submit.prevent="submitAuth">
          <fieldset :disabled="authPending">
            <label v-if="authMode === 'register'">账户名称<input v-model="authForm.account_name" required maxlength="100" autocomplete="nickname" /></label>
            <label>手机号<input v-model="authForm.phone" required type="tel" inputmode="tel" autocomplete="tel" /></label>
            <label>密码<input v-model="authForm.password" required type="password" :autocomplete="authMode === 'register' ? 'new-password' : 'current-password'" /></label>
            <label v-if="authMode === 'register'">确认密码<input v-model="authForm.confirm_password" required type="password" autocomplete="new-password" /></label>
            <p v-if="authError" class="message error-message" role="alert">{{ authError }}</p>
            <button class="submit-button" type="submit" :disabled="authPending">{{ authPending ? '正在处理...' : authMode === 'register' ? '注册' : '登录' }}</button>
          </fieldset>
        </form>
      </template>
    </div>
  </section>
  <main v-else class="page-shell">
    <div class="account-bar"><span>{{ account.account_name }}</span><button type="button" class="text-button" :disabled="authPending || loading || previewLoading || courseLoading || courseSaving || teachingLoading || historyLoading || analyticsLoading || reportLoading" @click="signOut">退出登录</button></div>
    <nav v-if="!isHomePage" class="page-navigation" aria-label="页面导航">
      <button
        type="button"
        class="navigation-button"
        :disabled="loading"
        @click="goBack"
      >
        <span aria-hidden="true">←</span>
        返回
      </button>
      <button
        type="button"
        class="navigation-button"
        :disabled="loading"
        @click="goHome(true)"
      >
        主页
      </button>
      <template
        v-if="
          teachingCourseId &&
          (isTeachingHome ||
            isInputPage ||
            isResultPage ||
            isHistoryPage ||
            isAnalyticsPage)
        "
      >
        <span class="current-course-label"
          >当前课程：{{ teachingCourseName }}</span
        >
        <select v-if="!isHistoryPage || classroomClasses.length" v-model="currentClassId" class="navigation-button" @change="classroomSession=null; classroomNotice=''">
          <option value="">当前班级</option>
          <option v-for="item in classroomClasses" :key="item.class_id" :value="item.class_id">{{ item.name }}</option>
        </select>
        <button
          type="button"
          class="navigation-button"
          :disabled="loading"
          @click="switchTeachingCourse"
        >
          切换课程
        </button>
      </template>
    </nav>

    <section v-if="isTeachingHome" class="workspace classroom-panel"><h2>当前班级课堂</h2><div v-if="collaborationPrompt" class="message error-message" role="dialog"><strong>新的协作申请：{{ collaborationPrompt.featureType }}</strong><p>{{ collaborationPrompt.claim.requested_name || collaborationPrompt.claim.name || '学生' }} 请求加入当前轮次。</p><button class="submit-button" type="button" @click="acceptClaim(collaborationPrompt.featureType,collaborationPrompt.claim.claim_id)">接受</button><button class="text-button" type="button" @click="rejectClaim(collaborationPrompt.featureType,collaborationPrompt.claim.claim_id)">拒绝</button></div><p v-if="!currentClassId" class="message notice-message">请选择当前班级；没有班级时请到备课端创建。</p><p v-else-if="!classroomSession" class="muted-text">已选择班级，请从课堂入口开始课堂。</p><div v-if="classroomSession" class="collaboration-tools"><p v-if="classroomNotice" class="message error-message">{{ classroomNotice }}</p><button class="text-button" type="button" :disabled="collaborationBusy" @click="openCollaboration('question_optimize')">显示优化问题协作二维码</button><button class="text-button" type="button" :disabled="collaborationBusy" @click="startAnswerCollaboration">锁定题目并生成答案评价二维码</button><button class="text-button" type="button" :disabled="collaborationBusy" @click="openCollaboration('presentation_questions')">显示汇报提问协作二维码</button><div v-for="(round,feature) in collaborationRounds" :key="round.round_id" class="message notice-message"><strong>{{ feature }}</strong><p>协作令牌已生成（仅本次显示）：{{ round.round_token }}</p><button class="text-button" type="button" @click="refreshCollaborationClaims(feature)">刷新申请</button><div v-for="claim in collaborationClaims[feature] || []" :key="claim.claim_id"><span>{{ claim.name || claim.requested_name || '学生' }} · {{ claim.state }}</span><button v-if="claim.state === 'pending'" class="text-button" type="button" @click="acceptClaim(feature,claim.claim_id)">接受</button><button v-if="claim.state === 'pending'" class="text-button" type="button" @click="rejectClaim(feature,claim.claim_id)">拒绝</button><button v-if="claim.state === 'accepted'" class="text-button" type="button" @click="releaseClaim(feature,claim.claim_id)">释放</button><button v-if="claim.state === 'completed'" class="text-button" type="button" @click="returnClaim(feature,claim.claim_id)">退回编辑</button><button v-if="claim.state === 'pending' || claim.state === 'accepted' || claim.state === 'completed'" class="text-button" type="button" @click="cancelClaim(feature,claim.claim_id)">取消</button></div><div v-if="collaborationEntries[feature]" class="collaboration-entry"><p>学生草稿：{{ collaborationEntries[feature].text || "（空）" }}</p><p v-if="collaborationEntries[feature].answer">学生回答：{{ collaborationEntries[feature].answer }}</p><p>教师可在对应功能页原问题框修改最终文本后提交。</p></div></div></div></section>
    <header class="hero">
      <div class="eyebrow">AI · 课程学习反馈</div>
      <h1>课程知识增强教学辅助系统</h1>
      <p>基于课程PPT知识库生成学习反馈</p>
    </header>

    <section
      v-if="isHomePage"
      class="home-menu landing-menu"
      aria-label="系统入口"
    >
      <button
        type="button"
        class="home-feature-card feature-prep"
        @click="openPrep"
      >
        <span class="entry-kicker">教师工作台</span><strong>教师备课端</strong
        ><span class="entry-description">管理课程、资料、知识库与学情</span
        ><span class="home-feature-arrow">→</span>
      </button>
      <button
        type="button"
        class="home-feature-card feature-teaching"
        @click="openTeaching"
      >
        <span class="entry-kicker">课堂学习</span><strong>教学端</strong
        ><span class="entry-description">选择课程，开始学习反馈</span
        ><span class="home-feature-arrow">→</span>
      </button>
    </section>

    <section
      v-else-if="isTeachingHome"
      class="home-menu teaching-feature-menu"
      aria-label="教学端功能"
    >
      <button
        v-for="feature in FEATURES"
        :key="feature.mode"
        type="button"
        class="home-feature-card"
        :class="feature.className"
        @click="openFeature(feature.mode)"
      >
        <strong>{{ feature.title }}</strong
        ><span class="home-feature-number">{{ feature.number }}</span
        ><span class="home-feature-arrow">→</span>
      </button>
      <button
        type="button"
        class="home-feature-card feature-history"
        @click="openHistory"
      >
        <strong>历史记录</strong><span class="home-feature-number">04</span
        ><span class="home-feature-arrow">→</span>
      </button>
      <button
        type="button"
        class="home-feature-card feature-analytics"
        @click="openAnalytics"
      >
        <strong>学情概览</strong><span class="home-feature-number">05</span
        ><span class="home-feature-arrow">→</span>
      </button>
    </section>

    <section v-if="page === 'prep-list'" class="classroom-panel workspace prep-workspace">
      <div class="prep-content"><h2>班级与课堂</h2><div><input v-model="classroomName" placeholder="班级名称" /><button class="submit-button small-button" type="button" @click="addClass">创建班级</button><button class="text-button" type="button" @click="loadClasses">刷新</button></div>
      <ul><li v-for="item in classroomClasses" :key="item.class_id"><strong>{{ item.name }}</strong><input type="file" accept=".xlsx" @change="onRosterFile" /><button class="text-button" type="button" @click="uploadRoster(item)">导入名单</button><button class="text-button" type="button" @click="beginClass(item)">开始课堂</button></li></ul>
      <div v-if="classroomSession"><p v-if="classroomPendingError" class="message error-message">{{ classroomPendingError }}</p><p v-if="classroomNotice" class="message error-message">{{ classroomNotice }}</p><img v-if="classroomQrUrl" class="classroom-qr" :src="classroomQrUrl" alt="微信扫码加入课堂" /><p v-if="classroomJoinUrl">加入链接：{{ classroomJoinUrl }} <button class="text-button" type="button" @click="navigator.clipboard?.writeText(classroomJoinUrl)">复制链接</button></p><button v-if="classroomSession.status !== 'ended'" class="text-button" type="button" @click="finishClass">结束课堂</button><select v-model="classroomFilter"><option value="">全部学生</option><option v-for="student in classroomMessages" :key="student.name" :value="student.name">{{ student.name }}</option></select><ul><li v-for="message in classroomMessages.filter(x => !classroomFilter || x.name === classroomFilter)" :key="message.message_id">{{ message.name }}：{{ message.body }}</li></ul><div v-for="item in classroomPending" :key="item.session_student_id"><span>{{ item.requested_name || item.name }} 待确认</span><button :disabled="classroomPendingBusy[item.session_student_id]" v-for="candidate in item.candidates || []" :key="candidate.student_id" @click="confirmPending(item,candidate.student_id)">{{ candidate.name }}（{{ candidate.student_no }}）</button><button :disabled="classroomPendingBusy[item.session_student_id]" @click="rejectPending(item)">{{ classroomPendingBusy[item.session_student_id] ? "处理中..." : "拒绝" }}</button></div><hr /><h3>课堂口述输入</h3><div v-if="oralTeacherState?.current_question" class="history-detail"><strong>当前待回答问题</strong><p>整理版：{{ oralTeacherState.current_question.cleaned_text }}</p><details><summary>查看问题原话</summary><p>{{ oralTeacherState.current_question.original_text }}</p></details><button class="text-button" type="button" :disabled="oralActionLoading === oralTeacherState.current_question.question_id || classroomSession.status === 'ended'" @click="triggerOralAction('question',oralTeacherState.current_question)">{{ oralActionLoading === oralTeacherState.current_question.question_id ? '处理中...' : '优化问题' }}</button></div><p v-else class="message notice-message">当前没有待回答问题。</p><div v-for="draft in oralTeacherDrafts" :key="draft.student_id + draft.kind" class="history-detail"><strong>{{ draft.student_name }}</strong><span> · {{ draft.kind === 'question' ? '提问草稿' : '回答草稿' }}</span><p>{{ draft.body }}</p></div><div v-for="answer in (oralTeacherState?.answers || [])" :key="answer.answer_id" class="history-detail"><strong>{{ answer.student_name }} 的回答</strong><p>{{ answer.original_text }}</p><button class="text-button" type="button" :disabled="oralActionLoading === answer.answer_id || classroomSession.status === 'ended'" @click="triggerOralAction('answer',answer)">{{ oralActionLoading === answer.answer_id ? '处理中...' : '答案评价' }}</button></div><div v-if="oralActionResult" class="message notice-message"><strong>处理结果</strong><p>{{ oralActionResult.overall_evaluation || oralActionResult.question_evaluation?.evaluation || oralActionResult.optimized_questions?.[0]?.question || '已完成' }}</p></div><hr /><h3>汇报材料</h3><div><input v-model="teacherSubmissionFilter" placeholder="按学生姓名筛选" @change="loadTeacherSubmissions" /><input v-model="teacherSubmissionNoFilter" placeholder="按学号筛选" @change="loadTeacherSubmissions" /><select v-model="teacherSubmissionSort" @change="loadTeacherSubmissions"><option value="desc">最新提交</option><option value="asc">最早提交</option></select><button class="text-button" type="button" @click="loadTeacherSubmissions">刷新</button></div><p v-if="teacherSubmissionLoading" class="muted-text">正在加载提交记录...</p><ul><li v-for="submission in teacherSubmissions" :key="submission.submission_id"><button class="text-button" type="button" @click="openTeacherSubmission(submission)">{{ submission.student.name || '未匹配学生' }}（{{ submission.student.student_no || '无学号' }}） · {{ formatHistoryTime(submission.created_at) }}</button><span> · {{ submission.files.map(file => file.filename).join('、') }}</span></li></ul><div v-if="teacherSubmissionDetail" class="history-detail"><h4>提交详情：{{ teacherSubmissionDetail.student.name }}（{{ teacherSubmissionDetail.student.student_no }}）</h4><p>{{ formatHistoryTime(teacherSubmissionDetail.created_at) }} · {{ teacherSubmissionDetail.status }}</p><div v-for="file in teacherSubmissionDetail.files" :key="file.file_id"><strong>{{ file.filename }}</strong><button class="text-button" type="button" @click="previewTeacherFile(file)">预览</button><button class="text-button" type="button" @click="downloadTeacherOriginal(file)">下载原文件</button><button class="text-button" type="button" :disabled="classroomSession.status === 'ended' || teacherQuestionLoading" @click="askTeacherQuestion(file)">{{ teacherQuestionLoading ? '提问中...' : '提问' }}</button></div><div v-if="teacherPreview" class="submission-preview"><h4>{{ teacherPreview.filename }}</h4><template v-if="teacherPreview.preview_type === 'text' || teacherPreview.preview_type === 'markdown'"><div class="markdown-preview" v-html="submissionMarkdown(teacherPreview.text)"></div></template><template v-else><p>PDF 原格式静态预览 · 共 {{ pdfPageCount }} 页 <button class="text-button" type="button" @click="zoomPdf(.15)">放大</button></p><p v-if="pdfLoading" class="muted-text">正在加载 PDF 预览...</p><p v-if="pdfError" class="message error-message">{{ pdfError }}。可下载原文件查看。</p><div v-else ref="pdfViewerContainer" class="pdf-scroll-viewer"><div v-for="page in pdfPageCount" :key="page" class="pdf-page"><span>第 {{ page }} / {{ pdfPageCount }} 页</span><canvas :ref="el => { if (el) pdfCanvasRefs[page - 1] = el }" :data-page="page"></canvas></div></div></template></div><div v-if="teacherQuestion" class="message notice-message"><strong>{{ teacherQuestion.question }}</strong><p v-if="teacherQuestion.response?.basis_summary">材料概述：{{ teacherQuestion.response.basis_summary }}</p><p v-if="teacherQuestion.response?.relation_explanation">提问依据：{{ teacherQuestion.response.relation_explanation }}</p><p v-for="citation in teacherQuestion.response?.citations || []" :key="citation.location">引用：{{ citation.filename }} · {{ citation.location }} · {{ citation.quote }}</p></div></div></div></div>
    </section>

    <section v-else-if="isAnalyticsPage" class="workspace prep-workspace">
      <header class="view-heading">
        <span>ANALYTICS</span>
        <h2>学情概览</h2>
      </header>
      <div class="prep-content">
        <div class="history-filters">
            <select v-model="historyClassId" @change="historyPage = 1; loadHistory()"><option value="">全部班级</option><option value="__unassigned__">未分班旧记录</option><option v-for="item in classroomClasses" :key="item.class_id" :value="item.class_id">{{ item.name }}</option></select>
          <label
            >起始日期<input
              v-model="analyticsFrom"
              type="date"
              @change="loadAnalytics" /></label
          ><label
            >结束日期<input
              v-model="analyticsTo"
              type="date"
              @change="loadAnalytics" /></label
          ><button type="button" class="text-button" @click="loadAnalytics">
            刷新统计</button
          ><button
            type="button"
            class="submit-button small-button"
            :disabled="reportLoading"
            @click="generateLearningReport"
          >
            {{ reportLoading ? "正在生成..." : "生成AI学情报告" }}
          </button>
        </div>
        <p v-if="analyticsError" class="message error-message">
          {{ analyticsError }}
        </p>
        <p v-if="reportError" class="message error-message">
          {{ reportError }}
        </p>
        <p v-if="analyticsLoading" class="muted-text">
          正在统计真实教学记录...
        </p>
        <template v-else-if="analyticsData"
          ><div
            v-if="analyticsData.data_insufficient"
            class="message notice-message"
          >
            数据不足：当前范围仅 {{ analyticsData.sample_size }} 条记录，少于 10
            条，仅展示事实统计，不生成结论。
          </div>
          <div class="analytics-grid">
            <article class="analytics-card">
              <strong>{{ analyticsData.sample_size }}</strong
              ><span>记录总数</span>
            </article>
            <article
              v-for="(count, task) in analyticsData.usage_counts"
              :key="task"
              class="analytics-card"
            >
              <strong>{{ count }}</strong
              ><span>{{ taskLabels[task] || "其他教学活动" }}</span>
            </article>
          </div>
          <div class="analytics-sections">
            <section>
              <h3>成绩分布</h3>
              <p class="muted-text">
                反映学生得分和评价等级的整体情况，帮助判断学习掌握程度。
              </p>
              <ul>
                <li
                  v-for="(count, level) in analyticsData.score_distribution
                    .levels"
                  :key="level"
                >
                  {{ level }}：{{ count }}
                </li>
              </ul>
              <p>
                分数：{{
                  analyticsData.score_distribution.scores.join("、") || "暂无"
                }}
              </p>
            </section>
            <section>
              <h3>常见薄弱点</h3>
              <p class="muted-text">
                汇总答案中反复出现的错误类型，次数越多越需要针对性讲解。
              </p>
              <ul>
                <li
                  v-for="item in analyticsData.common_issues"
                  :key="item.value"
                >
                  {{ item.value }}（{{ item.count }}）
                </li>
                <li v-if="!analyticsData.common_issues.length">暂无</li>
              </ul>
            </section>
            <section>
              <h3>课程依据高频章节</h3>
              <p class="muted-text">
                显示低分记录引用较多的课程章节，可作为复习重点。
              </p>
              <ul>
                <li
                  v-for="item in analyticsData.frequent_chapters"
                  :key="item.value"
                >
                  {{ item.value }}（{{ item.count }}）
                </li>
                <li v-if="!analyticsData.frequent_chapters.length">暂无</li>
              </ul>
            </section>
            <section>
              <h3>待改进知识点</h3>
              <p class="muted-text">
                每项说明薄弱表现、课程依据和改进方向；同文件相邻页码已合并。
              </p>
              <article
                v-for="item in analyticsData.low_score_knowledge_points"
                :key="item.key"
                class="knowledge-point knowledge-point-wide"
              >
                <h4>{{ item.chapter || item.name }}</h4>
                <ol class="knowledge-points-list">
                  <li v-for="point in item.points" :key="point.name">
                    <strong>{{ point.name }}</strong>
                    <span>薄弱表现：{{ point.weakness }}</span>
                    <span>改进方向：{{ point.advice }}</span>
                  </li>
                </ol>
                <small class="course-basis">课程依据：{{ item.basis }}</small>
              </article>
              <p v-if="!analyticsData.low_score_knowledge_points.length">
                暂无
              </p>
            </section>
          </div></template
        >
        <section v-if="learningReport" class="report-panel">
          <h3>AI学情分析报告</h3>
          <p class="muted-text">
            统计范围：{{ learningReport.created_from || "全部" }} 至
            {{ learningReport.created_to || "全部" }} ·
            {{ learningReport.record_count }} 条记录 ·
            {{ formatHistoryTime(learningReport.generated_at) }}
          </p>
          <article
            v-for="(items, section) in learningReport.report"
            :key="section"
            class="report-section"
          >
            <h4>{{ reportSectionLabel(section) }}</h4>
            <ul class="report-bullets">
              <li v-for="item in items" :key="item.conclusion">
                <strong>{{ humanizeReportText(item.conclusion) }}</strong>
                <span class="report-evidence">{{ humanizeReportText(item.evidence) }}</span>
              </li>
            </ul>
          </article>
        </section>
      </div>
    </section>

    <section v-else-if="isHistoryPage" class="workspace prep-workspace">
      <header class="view-heading">
        <span>HISTORY</span>
        <h2>教学历史记录</h2>
      </header>
      <div class="prep-content">
        <div class="history-filters">
          <label
            >功能<select
              v-model="historyTaskType"
              @change="
                historyPage = 1;
                loadHistory();
              "
            >
              <option value="">全部</option>
              <option value="question_optimize">问题优化</option>
              <option value="answer_evaluate">答案评价</option>
              <option value="presentation_questions">汇报提问</option>
            </select></label
          ><label
            >起始日期<input
              v-model="historyFrom"
              type="date"
              @change="
                historyPage = 1;
                loadHistory();
              " /></label
          ><label
            >结束日期<input
              v-model="historyTo"
              type="date"
              @change="
                historyPage = 1;
                loadHistory();
              " /></label
          ><button type="button" class="text-button" @click="exportHistory">
            导出 CSV</button
          ><button
            type="button"
            class="text-button danger-button"
            :disabled="!historyItems.length && !historyTotal"
            @click="removeAllHistory"
          >
            清空当前课程
          </button>
        </div>
        <p v-if="historyError" class="message error-message">
          {{ historyError }}
        </p>
        <p v-if="historyLoading" class="muted-text">正在加载历史记录...</p>
        <p v-else-if="!historyItems.length" class="empty-state">
          当前筛选条件下暂无历史记录。
        </p>
        <div v-else class="history-table">
          <div v-for="item in historyItems" :key="item.id" class="history-row">
            <div>
              <strong>{{ formatHistoryTime(item.created_at) }}</strong
              ><span>{{ item.task_type }}</span>
              <p>{{ historySummary(item) }}</p>
            </div>
            <div class="history-score">
              {{ item.score ?? "—" }}<small>{{ item.level || "" }}</small>
            </div>
            <div class="card-actions">
              <button
                type="button"
                class="text-button"
                @click="showHistoryDetail(item)"
              >
                详情</button
              ><button
                type="button"
                class="text-button danger-button"
                @click="removeHistory(item)"
              >
                删除
              </button>
            </div>
          </div>
        </div>
        <div class="history-pagination">
          <button
            type="button"
            class="text-button"
            :disabled="historyPage <= 1"
            @click="
              historyPage -= 1;
              loadHistory();
            "
          >
            上一页</button
          ><span
            >第 {{ historyPage }} /
            {{ Math.max(1, Math.ceil(historyTotal / historyPageSize)) }} 页 · 共
            {{ historyTotal }} 条</span
          ><button
            type="button"
            class="text-button"
            :disabled="historyPage >= Math.ceil(historyTotal / historyPageSize)"
            @click="
              historyPage += 1;
              loadHistory();
            "
          >
            下一页
          </button>
        </div>
        <div v-if="historyDetail" class="history-detail">
          <h3>记录详情</h3>
          <p>匿名学生：{{ historyDetail.student_id || "未提供" }}</p>
          <div v-if="historyDetail.input_json?.question_cleaned || historyDetail.input_json?.answer_cleaned"><p><strong>整理版：</strong>{{ historyDetail.input_json.question_cleaned || historyDetail.input_json.answer_cleaned }}<span v-if="historyDetail.input_json.cleanup_status === 'unformatted'">（未整理）</span></p><details><summary>查看原话</summary><p>{{ historyDetail.input_json.question || historyDetail.input_json.student_answer }}</p></details></div>
          <template v-if="historyDetail.task_type === 'presentation_questions'">
            <p v-if="historyDetail.output_json?.status === 'insufficient'">{{ historyDetail.output_json.notice }}</p>
            <ul><li v-for="(item, index) in historyDetail.output_json?.questions || []" :key="index">
              {{ item.question }}<p v-if="item.basis_summary">针对的材料内容：{{ item.basis_summary }}</p>
              <p v-if="item.relation_explanation">{{ item.relation_explanation }}</p>
              <details v-if="item.source_hints?.length"><summary>查看来源</summary><p v-for="(source, sourceIndex) in item.source_hints" :key="sourceIndex">{{ source.filename }} · {{ source.location }}</p></details>
            </li></ul>
          </template>
          <p v-else>{{ historyDetail.output_json?.overall_evaluation || historyDetail.output_json?.question_evaluation?.evaluation || '已生成教学反馈' }}</p>
          <button
            type="button"
            class="text-button"
            @click="historyDetail = null"
          >
            关闭
          </button>
        </div>
      </div>
    </section>

    <section v-else-if="isTeachingSelect" class="workspace prep-workspace">
      <header class="view-heading">
        <span>TEACH</span>
        <h2>选择课程</h2>
      </header>
      <div class="prep-content teaching-course-select">
        <p class="muted-text">请选择一门已构建完成的课程开始学习。</p>
        <p v-if="teachingLoading" class="muted-text">正在加载课程...</p>
        <p v-if="teachingError" class="message error-message">
          {{ teachingError }}
        </p>
        <div
          v-if="!teachingLoading && !teachingCourses.length"
          class="empty-state"
        >
          暂无课程。
        </div>
        <button
          v-for="course in teachingCourses"
          :key="course.id"
          type="button"
          class="teaching-course-option"
          :disabled="course.status !== 'ready'"
          @click="chooseTeachingCourse(course)"
        >
          <span
            ><strong>{{ course.name }}</strong
            ><small>{{ course.description || "暂无简介" }}</small></span
          ><span class="course-status" :class="`status-${course.status}`">{{
            course.status
          }}</span>
        </button>
      </div>
    </section>

    <section v-else-if="page === 'prep-list'" class="workspace prep-workspace">
      <header class="view-heading">
        <span>PREP</span>
        <h2>课程列表</h2>
      </header>
      <div class="prep-content">
        <section class="classroom-panel"><h3>班级管理</h3><p v-if="!teachingCourseId" class="message notice-message">请先打开课程后管理班级。</p><div v-else><input v-model="classroomName" placeholder="班级名称" /><button class="submit-button small-button" type="button" :disabled="courseLoading" @click="addClass">创建班级</button><button class="text-button" type="button" @click="loadClasses">刷新</button><p v-if="!classroomClasses.length" class="muted-text">当前课程暂无班级。</p><ul><li v-for="item in classroomClasses" :key="item.class_id"><strong>{{ item.name }}</strong><input type="file" accept=".xlsx" @change="onRosterFile" /><button class="text-button" type="button" @click="uploadRoster(item)">导入名单</button><button class="text-button" type="button" @click="beginClass(item)">开始课堂</button></li></ul></div></section>
        <div class="section-title-row">
          <p class="muted-text">管理课程资料并构建独立知识库</p>
          <button
            class="submit-button small-button"
            type="button"
            @click="
              selectedCourse = null;
              resetCourseForm();
              page = 'prep-form';
            "
          >
            新建课程
          </button>
        </div>
        <p v-if="courseLoading" class="muted-text">正在加载课程...</p>
        <p v-if="courseError" class="message error-message">
          {{ courseError }}
        </p>
        <p v-else-if="!courses.length" class="empty-state">
          暂无课程，先创建一门课程吧。
        </p>
        <div v-else class="course-grid">
          <article
            v-for="course in courses"
            :key="course.id"
            class="course-card"
          >
            <div>
              <span class="course-status" :class="`status-${course.status}`">{{
                course.status
              }}</span>
              <h3>{{ course.name }}</h3>
              <p>{{ course.description || "暂无简介" }}</p>
              <small>资料数：{{ course._materialCount ?? "—" }}</small>
            </div>
            <div class="card-actions">
              <button
                type="button"
                class="text-button"
                @click="openCourse(course.id)"
              >
                详情</button
              ><button
                type="button"
                class="text-button"
                @click="
                  selectedCourse = course;
                  courseForm = {
                    name: course.name,
                    description: course.description,
                    grade_level: course.grade_level,
                    teaching_goal: course.teaching_goal,
                  };
                  page = 'prep-form';
                "
              >
                编辑</button
              ><button
                type="button"
                class="text-button danger-button"
                :disabled="course.id === teachingCourseId"
                @click="removeCourse(course)"
              >
                删除
              </button>
            </div>
          </article>
        </div>
      </div>
    </section>

    <section v-else-if="page === 'prep-form'" class="workspace prep-workspace">
      <header class="view-heading">
        <span>PREP</span>
        <h2>{{ selectedCourse ? "编辑课程" : "新建课程" }}</h2>
      </header>
      <form class="prep-content course-form" @submit.prevent="saveCourse">
        <p v-if="courseError" class="message error-message">
          {{ courseError }}
        </p>
        <label
          >课程名称<input
            v-model="courseForm.name"
            maxlength="100"
            required /></label
        ><label
          >简介<textarea
            v-model="courseForm.description"
            maxlength="2000"
            rows="3"
          /></label
        ><label
          >年级<input v-model="courseForm.grade_level" maxlength="100" /></label
        ><label
          >教学目标<textarea
            v-model="courseForm.teaching_goal"
            maxlength="2000"
            rows="3"
          /></label
        ><button class="submit-button" :disabled="courseSaving">
          {{ courseSaving ? "保存中..." : "保存课程" }}
        </button>
      </form>
    </section>

    <section
      v-else-if="page === 'prep-detail'"
      class="workspace prep-workspace"
    >
      <header class="view-heading">
        <span>PREP</span>
        <h2>{{ selectedCourse?.name }}</h2>
      </header>
      <div class="prep-content">
        <p v-if="courseLoading" class="muted-text">正在加载课程详情...</p>
        <template v-else
          ><div class="detail-meta">
            <span
              class="course-status"
              :class="`status-${selectedCourse?.status}`"
              >{{ selectedCourse?.status }}</span
            ><span>资料 {{ courseMaterials.length }} 份</span>
          </div>
          <div v-if="isPresetCourse" class="message notice-message">
            预置课程资料不可修改，如需新资料请创建课程。
          </div>
          <div v-if="courseError" class="message error-message">
            {{ courseError }}
          </div>
          <div v-if="courseNotice" class="message notice-message">
            {{ courseNotice }}
          </div>
          <div class="material-toolbar">
            <input
              ref="courseFileInput"
              type="file"
              multiple
              accept=".pptx,.docx,.md,.txt,.pdf"
              :disabled="
                isPresetCourse || selectedCourse?.status === 'building'
              "
              @change="handleCourseFile"
            /><button
              class="submit-button"
              type="button"
              :disabled="
                isPresetCourse ||
                courseLoading ||
                selectedCourse?.status === 'building' ||
                !courseMaterials.length
              "
              @click="rebuildCourse"
            >
              {{
                selectedCourse?.status === "building"
                  ? "正在构建..."
                  : "开始构建"
              }}
            </button>
          </div>
          <p v-if="!courseMaterials.length" class="empty-state">
            暂无资料，请上传 PPTX、DOCX、MD、TXT 或 PDF 文件。
          </p>
          <ul v-else class="material-list">
            <li v-for="material in courseMaterials" :key="material.id">
              <span
                >{{ material.filename }} ·
                {{ formatFileSize(material.size) }}</span
              ><button
                class="text-button danger-button"
                type="button"
                :disabled="
                  isPresetCourse || selectedCourse?.status === 'building'
                "
                @click="removeMaterial(material)"
              >
                删除
              </button>
            </li>
          </ul>
        </template>
      </div>
    </section>

    <section
      v-else-if="isInputPage"
      class="workspace"
      aria-label="教学辅助输入区"
    >
      <header class="view-heading">
        <span>教学端</span>
        <h2>{{ currentFeature?.title }}</h2>
      </header>

      <form
        class="input-area"
        :class="{ 'presentation-input-area': isPresentationMode }"
        @submit.prevent="submit"
      >
        <template v-if="isPresentationMode">
          <div class="presentation-composer">
            <input
              id="presentation-file"
              ref="fileInput"
              class="visually-hidden"
              type="file"
              multiple
              accept=".pptx,.docx,.md,.txt,.pdf"
              @change="handleFileInput"
            />

            <div
              v-if="presentationFiles.length"
              class="selected-file-list"
              aria-label="已选汇报文件"
            >
              <div
                v-for="(file, index) in presentationFiles"
                :key="`${file.name}-${file.size}-${file.lastModified}-${index}`"
                class="selected-file-card"
              >
                <label><input type="checkbox" :checked="!excludedPresentationFiles.includes(file)" @change="excludedPresentationFiles = $event.target.checked ? excludedPresentationFiles.filter(item => item !== file) : [...excludedPresentationFiles, file]; materialPreviews = []" />用于本次提问</label>
                <div class="selected-file-copy">
                  <strong>{{ file.name }}</strong>
                  <span>{{ formatFileSize(file.size) }}</span>
                </div>
                <button
                  type="button"
                  class="selected-file-remove"
                  :aria-label="`删除文件 ${file.name}`"
                  @click="removePresentationFile(index)"
                >
                  ×
                </button>
              </div>
            </div>

            <label class="visually-hidden" for="presentation-text"
              >汇报材料文本</label
            >
            <textarea
              id="presentation-text"
              v-model="presentationText"
              class="presentation-textarea"
              maxlength="30000"
              rows="10"
              @input="materialPreviews = []"
              placeholder="粘贴汇报摘要、讲稿或材料内容，也可以通过左下角添加文件..."
            />

            <label><input type="checkbox" v-model="includePresentationText" @change="materialPreviews = []" />使用输入文本</label>
            <button type="button" class="text-button" :disabled="previewLoading || !canSubmit" @click="previewCurrentMaterials">{{ previewLoading ? "正在解析..." : "预览选定材料" }}</button>
            <section v-if="materialPreviews.length" aria-label="材料预览">
              <article v-for="(preview, index) in materialPreviews" :key="index">
                <strong>{{ preview.filename }}</strong>
                <p class="material-overview">{{ preview.overview }}</p>
              </article>
            </section>
            <div class="presentation-toolbar">
              <div class="presentation-toolbar-left">
                <button
                  type="button"
                  class="file-add-button"
                  aria-label="添加汇报文件"
                  title="添加PPTX、DOCX、MD或TXT文件"
                  @click="openFilePicker"
                >
                  +
                </button>
                <span class="presentation-limit-hint"
                  >最多10个 · 单个50MB · 合计100MB</span
                >
              </div>
              <span class="presentation-char-count"
                >{{ presentationText.length }}/30000</span
              >
              <button
                class="submit-button presentation-submit"
                type="submit"
                :disabled="loading || !canSubmit"
              >
                <span v-if="loading" class="spinner" aria-hidden="true" />
                {{ loading ? "正在解析材料并生成问题..." : "问题生成" }}
              </button>
            </div>
          </div>
        </template>

        <template v-else>
          <div class="field-block">
            <div class="field-heading">
              <label for="question">{{
                isQuestionMode ? "学生原始问题" : "学生回答的问题"
              }}</label>
              <span>{{ question.length }}/1000</span>
            </div>
            <textarea
              id="question"
              v-model="question"
              maxlength="1000"
              rows="4"
              :disabled="answerRoundLocked"
              @input="markCollaborationTeacherEdited"
              :placeholder="
                isQuestionMode
                  ? '例如：卷积神经网络为什么适合处理图片？'
                  : '请输入需要评价的课程问题'
              "
            />
          </div>

          <div v-if="isAnswerMode" class="field-block">
            <div class="field-heading">
              <label for="student-answer">学生回答</label>
              <span>{{ studentAnswer.length }}/1000</span>
            </div>
            <textarea
              id="student-answer"
              v-model="studentAnswer"
              maxlength="1000"
              rows="6"
              @input="markCollaborationTeacherEdited"
              placeholder="请输入学生的原始回答"
            />
          </div>

          <div v-if="isAnswerMode && classroomSession"><button v-if="!answerRoundLocked" type="button" class="text-button" :disabled="collaborationBusy" @click="startAnswerCollaboration">锁定当前题目并生成学生二维码</button><button v-else type="button" class="text-button" :disabled="collaborationBusy" @click="cancelAnswerRound">取消旧轮次，重新出题</button></div>
        </template>

        <button
          v-if="!isPresentationMode"
          class="submit-button"
          type="submit"
          :disabled="loading || !canSubmit"
        >
          <span v-if="loading" class="spinner" aria-hidden="true" />
          {{
            loading
              ? "正在检索课程资料并生成反馈..."
              : isQuestionMode
                ? "生成问题优化建议"
                : "评价并优化答案"
          }}
        </button>
      </form>
    </section>

    <p
      v-if="isInputPage && errorMessage"
      class="message error-message"
      role="alert"
    >
      {{ errorMessage }}
    </p>

    <section
      v-if="isResultPage && result"
      class="result-area"
      aria-live="polite"
    >
      <div v-if="result.insufficiency_notice" class="message notice-message">
        <strong>资料提示</strong>
        <span>{{ result.insufficiency_notice }}</span>
      </div>

      <template v-if="isPresentationMode && result.questions">
        <section class="result-section presentation-question-section">
          <h2>课程汇报提问</h2>
          <p v-if="result.status === 'insufficient'" class="message notice-message">{{ result.notice }}</p>
          <div v-if="result.status !== 'insufficient'" class="level-question-list">
            <article
              v-for="(group, index) in presentationQuestionGroups"
              :key="group.level"
              class="level-question-item"
            >
              <button
                type="button"
                class="level-selector"
                :class="[
                  QUESTION_LEVEL_CLASSES[group.level],
                  { revealed: isPresentationQuestionRevealed(index) },
                ]"
                :aria-expanded="isPresentationQuestionRevealed(index)"
                @click="togglePresentationQuestion(index)"
              >
                <span>{{ group.label }} · 3题</span>
                <strong>{{ group.score }}分</strong>
              </button>
              <div
                v-if="isPresentationQuestionRevealed(index)"
                class="level-question-content"
              >
                <ol class="presentation-group-list">
                  <li v-for="item in group.questions" :key="item.question">
                    {{ item.question }}
                    <p v-if="item.basis_summary" class="question-basis">针对的材料内容：{{ item.basis_summary }}</p>
                    <p v-if="item.relation_explanation" class="question-basis">{{ item.relation_explanation }}</p>
                    <details v-if="item.source_hints?.length"><summary>查看来源</summary><p v-for="(source, sourceIndex) in item.source_hints" :key="sourceIndex">{{ source.filename }} · {{ source.location }}</p></details>
                  </li>
                </ol>
              </div>
            </article>
          </div>
        </section>
      </template>

      <template v-if="result.task_type === 'question_optimize'">
        <section
          class="result-section evaluation-section"
          :class="EVALUATION_LEVEL_CLASSES[result.question_evaluation.level]"
        >
          <h2>问题评价</h2>
          <div class="evaluation-summary">
            <strong class="evaluation-score">{{
              result.question_evaluation.score
            }}</strong>
            <div>
              <span class="evaluation-score-unit">分</span>
              <strong class="evaluation-level">{{
                result.question_evaluation.level
              }}</strong>
            </div>
          </div>
          <div class="evaluation-details">
            <div>
              <strong>评价</strong>
              <p>
                {{
                  formatCourseReferences(result.question_evaluation.evaluation)
                }}
              </p>
            </div>
            <div>
              <strong>建议</strong>
              <p>
                {{
                  formatCourseReferences(result.question_evaluation.suggestion)
                }}
              </p>
            </div>
          </div>
          <div
            v-if="result.question_evaluation.score_breakdown?.length"
            class="score-breakdown"
          >
            <h3>分项评分</h3>
            <article
              v-for="item in result.question_evaluation.score_breakdown"
              :key="item.key"
              class="score-breakdown-item"
            >
              <div class="score-breakdown-heading">
                <strong>{{ item.label }}</strong>
                <span>{{ item.score }}/{{ item.max_score }}分</span>
              </div>
              <small>评分锚点：{{ item.anchor }}</small>
              <p>{{ formatCourseReferences(item.reason) }}</p>
              <ul v-if="item.evidence?.length" class="score-evidence-list">
                <li v-for="evidence in item.evidence" :key="`${evidence.source}-${evidence.quote}`">
                  <strong>{{ formatCourseReferences(evidence.source) }}</strong>
                  <span>“{{ formatCourseReferences(evidence.quote) }}”</span>
                </li>
              </ul>
              <small v-else class="muted-text">当前检索片段不足以提供该项材料依据。</small>
            </article>
          </div>
          <p class="score-interpretation">
            {{ result.question_evaluation.score_interpretation }}
            <span v-if="result.question_evaluation.floor_applied">原始总分{{ result.question_evaluation.raw_score }}，按最低分规则计60分。</span>
            <span v-if="result.question_evaluation.evidence_status === 'insufficient'">
              当前材料证据不足，未据此直接压低分数。
            </span>
          </p>
        </section>

        <section class="result-section">
          <div class="section-title-row">
            <h2>优化后的问题</h2>
          </div>
          <div class="level-question-list">
            <article
              v-for="(item, index) in result.optimized_questions"
              :key="`${item.level}-${item.question}`"
              class="level-question-item"
            >
              <button
                type="button"
                class="level-selector"
                :class="[
                  QUESTION_LEVEL_CLASSES[item.level],
                  { revealed: isOptimizedQuestionRevealed(index) },
                ]"
                :aria-expanded="isOptimizedQuestionRevealed(index)"
                @click="toggleOptimizedQuestion(index)"
              >
                <span>{{ item.label }}</span>
                <strong>{{ item.score }}分</strong>
              </button>
              <div
                v-if="isOptimizedQuestionRevealed(index)"
                class="level-question-content"
              >
                <p>{{ formatCourseReferences(item.question) }}</p>
                <div class="thinking-angle">
                  <strong>思考角度</strong>
                  <span>{{
                    formatCourseReferences(item.improvement_focus)
                  }}</span>
                </div>
              </div>
            </article>
          </div>
        </section>

        <section class="result-section deep-section">
          <div class="section-title-row">
            <h2>深度思考问题</h2>
          </div>
          <ol class="question-list deep-list">
            <li v-for="item in result.deep_questions" :key="item.question">
              <p>{{ formatCourseReferences(item.question) }}</p>
              <span>{{ formatCourseReferences(item.thinking_dimension) }}</span>
            </li>
          </ol>
        </section>
      </template>

      <template v-else-if="result.task_type === 'answer_evaluate'">
        <section class="result-section evaluation-section">
          <h2>答案评分</h2>
          <div class="evaluation-summary">
            <strong class="evaluation-score">{{ result.score }}</strong>
            <div>
              <span class="evaluation-score-unit">分</span
              ><strong class="evaluation-level">{{ result.level }}</strong>
            </div>
          </div>
          <div v-if="result.score_breakdown?.length" class="score-breakdown">
            <h3>分项评分</h3>
            <article
              v-for="item in result.score_breakdown"
              :key="item.key"
              class="score-breakdown-item"
            >
              <div class="score-breakdown-heading">
                <strong>{{ item.label }}</strong>
                <span>{{ item.score }}/{{ item.max_score }}分</span>
              </div>
              <small>评分锚点：{{ item.anchor }}</small>
              <p>{{ formatCourseReferences(item.reason) }}</p>
              <ul v-if="item.evidence?.length" class="score-evidence-list">
                <li v-for="evidence in item.evidence" :key="`${evidence.source}-${evidence.quote}`">
                  <strong>{{ formatCourseReferences(evidence.source) }}</strong>
                  <span>“{{ formatCourseReferences(evidence.quote) }}”</span>
                </li>
              </ul>
              <small v-else class="muted-text">当前检索片段不足以提供该项材料依据。</small>
            </article>
          </div>
          <p v-if="result.score_interpretation" class="score-interpretation">
            {{ result.score_interpretation }}
            <span v-if="result.floor_applied">原始总分{{ result.raw_score }}，按最低分规则计60分。</span>
            <span v-if="result.evidence_status === 'insufficient'">
              当前材料证据不足，未据此直接压低分数。
            </span>
          </p>
        </section>
        <section class="result-section diagnosis-section">
          <h2>总体评价</h2>
          <p class="lead-text">
            {{ formatCourseReferences(result.overall_evaluation) }}
          </p>
        </section>

        <div class="feedback-columns">
          <section class="result-section compact-section positive-section">
            <h2>值得肯定</h2>
            <ul class="simple-list">
              <li v-for="item in result.strengths" :key="item">
                {{ formatCourseReferences(item) }}
              </li>
            </ul>
          </section>

          <section class="result-section compact-section issue-section">
            <h2>需要改进</h2>
            <p v-if="!result.issues.length" class="muted-text">
              暂未发现需要改进的问题。
            </p>
            <article
              v-for="item in result.issues"
              :key="item.description"
              class="issue-item"
            >
              <strong>· {{ item.type }}</strong>
              <p>{{ formatCourseReferences(item.description) }}</p>
              <small>{{
                formatCourseReferences(item.evidence_or_reason)
              }}</small>
            </article>
          </section>
        </div>

        <section class="result-section">
          <h2>改进建议</h2>
          <ul class="numbered-advice">
            <li
              v-for="(item, index) in result.improvement_suggestions"
              :key="item"
            >
              <span>{{ String(index + 1).padStart(2, "0") }}</span>
              <p>{{ formatCourseReferences(item) }}</p>
            </li>
          </ul>
        </section>

        <section class="result-section answer-section">
          <h2>优化答案</h2>
          <p class="improved-answer">
            {{ formatCourseReferences(result.improved_answer) }}
          </p>
        </section>
      </template>

      <section
        v-if="result.course_basis?.length"
        class="result-section source-section"
      >
        <h2>课程依据</h2>
        <ul class="source-list">
          <li
            v-for="item in result.course_basis"
            :key="`${item.source}-${item.reason}`"
          >
            <strong>{{ formatCourseReferences(item.source) }}</strong>
            <p>{{ formatCourseReferences(item.reason) }}</p>
          </li>
        </ul>
      </section>
    </section>

    <div v-if="learningReport" class="report-export-dock">
      <button type="button" class="text-button" @click="exportReport('md')">
        导出 MD</button
      ><button type="button" class="text-button" @click="exportReport('docx')">
        导出 Word</button
      ><button type="button" class="text-button" @click="exportReport('pdf')">
        导出 PDF</button
      ><button type="button" class="text-button" @click="learningReport = null">
        关闭报告
      </button>
    </div>

    <div
      v-if="historyDetail"
      class="history-modal-overlay"
      @click.self="historyDetail = null"
    >
      <div class="history-modal">
        <div class="section-title-row">
          <h3>历史详情</h3>
          <button
            type="button"
            class="text-button"
            @click="historyDetail = null"
          >
            关闭
          </button>
        </div>
        <p><strong>功能：</strong>{{ historyDetail.task_type }}</p>
        <ul v-if="historyDetail.task_type === 'presentation_questions'">
          <li v-for="(item, index) in historyDetail.output_json?.questions || []" :key="index">{{ item.question }}<p v-if="item.basis_summary">针对的材料内容：{{ item.basis_summary }}</p><p v-if="item.relation_explanation">{{ item.relation_explanation }}</p><details v-if="item.source_hints?.length"><summary>查看来源</summary><p v-for="(source, sourceIndex) in item.source_hints" :key="sourceIndex">{{ source.filename }} · {{ source.location }}</p></details></li>
        </ul>
        <p v-if="historyDetail.output_json?.status === 'insufficient'">{{ historyDetail.output_json.notice }}</p>
        <p>
          <strong>时间：</strong
          >{{ formatHistoryTime(historyDetail.created_at) }}
        </p>
        <p v-if="(historyDetail.output_json?.question_evaluation || historyDetail.output_json)?.floor_applied">原始总分{{ (historyDetail.output_json?.question_evaluation || historyDetail.output_json).raw_score }}，按最低分规则计60分。</p>
        <p><strong>输入摘要：</strong>{{ historySummary(historyDetail) }}</p>
        <p v-if="historyDetail.score !== null">
          <strong>评分：</strong>{{ historyDetail.score }}分
          {{ historyDetail.level || "" }}
        </p>
        <p>
          <strong>课程资料依据：</strong
          >{{
            historyDetail.course_basis_json
              ?.map((item) => item.source || item)
              .join("；") || "无"
          }}
        </p>
        <p>
          <strong>结果概览：</strong
          >{{
            historyDetail.output_json?.overall_evaluation ||
            historyDetail.output_json?.question_evaluation?.evaluation ||
            "已完成"
          }}
        </p>
      </div>
    </div>

    <footer v-if="!isHomePage">
      {{
        isPresentationMode
          ? "问题仅依据本次提交的汇报材料生成 · 生成结果用于辅助学习"
          : "课程内容由现有PPT知识库提供依据 · 生成结果用于辅助学习"
      }}
    </footer>
  </main>
  <div v-if="toastMessage" class="toast-message" role="status">
    {{ toastMessage }}
  </div>
</template>

