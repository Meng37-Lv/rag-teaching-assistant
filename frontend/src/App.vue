<script setup>
import { computed, ref, onMounted } from 'vue'
import { buildCourse, createCourse, createLearningReport, deleteCourse, deleteHistoryEvent, deleteMaterial, evaluateAnswer, generatePresentationQuestions, getAnalytics, getBuildStatus, getHistoryEvent, historyCsvUrl, listCourses, listHistory, listMaterials, optimizeQuestion, searchCourse, updateCourse, uploadMaterial, clearHistory } from './api.ts'

const page = ref('home')
const mode = ref(null)
const optimizedQuestionInput = ref('')
const answerQuestionInput = ref('')
const studentAnswer = ref('')
const loading = ref(false)
const errorMessage = ref('')
const result = ref(null)
const revealedOptimizedQuestions = ref([])
const revealedPresentationQuestions = ref([])
const presentationFiles = ref([])
const presentationText = ref('')
const fileInput = ref(null)
const courses = ref([])
const selectedCourse = ref(null)
const courseMaterials = ref([])
const courseLoading = ref(false)
const courseError = ref('')
const courseNotice = ref('')
const courseForm = ref({ name: '', description: '', grade_level: '', teaching_goal: '' })
const courseFileInput = ref(null)
const searchQuery = ref('')
const searchResults = ref([])
const courseSearchResult = ref(null)
const teachingCourseId = ref('')
const teachingCourseName = ref('')
const teachingCourses = ref([])
const teachingLoading = ref(false)
const teachingError = ref('')
const historyItems = ref([])
const historyTotal = ref(0)
const historyPage = ref(1)
const historyPageSize = ref(10)
const historyTaskType = ref('')
const historyFrom = ref('')
const historyTo = ref('')
const historyLoading = ref(false)
const historyError = ref('')
const historyDetail = ref(null)
const analyticsData = ref(null)
const analyticsFrom = ref('')
const analyticsTo = ref('')
const analyticsLoading = ref(false)
const analyticsError = ref('')
const learningReport = ref(null)
const reportLoading = ref(false)
const reportError = ref('')

const FEATURES = [
  { mode: 'question', number: '01', title: '优化问题', className: 'feature-question' },
  { mode: 'answer', number: '02', title: '评价答案', className: 'feature-answer' },
  { mode: 'presentation', number: '03', title: '课程汇报提问', className: 'feature-presentation' },
]
const QUESTION_LEVEL_CLASSES = {
  easy: 'level-easy',
  medium: 'level-medium',
  hard: 'level-hard',
}
const EVALUATION_LEVEL_CLASSES = {
  简单: 'evaluation-simple',
  思考型: 'evaluation-thinking',
  深度型: 'evaluation-deep',
}
const PRESENTATION_FILE_TYPES = ['.pptx', '.docx', '.md', '.txt', '.pdf']
const MAX_PRESENTATION_FILES = 10
const MAX_PRESENTATION_FILE_BYTES = 50 * 1024 * 1024
const MAX_PRESENTATION_TOTAL_FILE_BYTES = 100 * 1024 * 1024

const CHAPTER_PAGE_REFERENCE_PATTERN = /第\s*(\d+)\s*章(?:《([^》]+)》)?\s*[，,]?\s*第\s*(\d+)(?:\s*[-—–~～至到]\s*(\d+))?\s*页/g

function formatCourseReferences(value) {
  if (typeof value !== 'string' || !value) return value

  const matches = [...value.matchAll(CHAPTER_PAGE_REFERENCE_PATTERN)]
  if (!matches.length) return value

  const groups = new Map()
  for (const match of matches) {
    const chapter = Number(match[1])
    const title = match[2] || ''
    const start = Number(match[3])
    const end = Number(match[4] || match[3])
    if (!Number.isInteger(chapter) || !Number.isInteger(start) || end < start) continue

    const key = String(chapter)
    if (!groups.has(key)) groups.set(key, { chapter, title, pages: new Set() })
    const group = groups.get(key)
    if (!group.title && title) group.title = title
    for (let page = start; page <= end; page += 1) group.pages.add(page)
  }

  if (!groups.size) return value

  const formatPages = (pages) => {
    const sorted = [...pages].sort((a, b) => a - b)
    const ranges = []
    let start = sorted[0]
    let previous = sorted[0]
    for (const page of sorted.slice(1)) {
      if (page === previous + 1) {
        previous = page
        continue
      }
      ranges.push(start === previous ? String(start) : `${start}-${previous}`)
      start = previous = page
    }
    ranges.push(start === previous ? String(start) : `${start}-${previous}`)
    return ranges.join('、')
  }

  const citation = [...groups.values()]
    .map(({ chapter, title, pages }) => {
      const chapterName = title ? `第${chapter}章《${title}》` : `第${chapter}章`
      return `${chapterName}，第${formatPages(pages)}页`
    })
    .join('；')

  let remaining = value
    .replace(CHAPTER_PAGE_REFERENCE_PATTERN, '')
    .replace(/\s{2,}/g, ' ')
    .trim()
  if (!remaining.replace(/[；;，,\s]/g, '')) return citation
  remaining = remaining.replace(/^[；;，,\s]+|[；;，,\s]+$/g, '')
  return remaining ? `${remaining}（${citation}）` : citation
}

const isQuestionMode = computed(() => mode.value === 'question')
const isAnswerMode = computed(() => mode.value === 'answer')
const isPresentationMode = computed(() => mode.value === 'presentation')
const isHomePage = computed(() => page.value === 'home')
const isTeachingHome = computed(() => page.value === 'teaching-home')
const isTeachingSelect = computed(() => page.value === 'teaching-select')
const isHistoryPage = computed(() => page.value === 'teaching-history')
const isAnalyticsPage = computed(() => page.value === 'teaching-analytics')
const isPrepPage = computed(() => page.value.startsWith('prep-'))
const isPresetCourse = computed(() => selectedCourse.value?.id === teachingCourseId.value && selectedCourse.value?.name === '人工智能导论')
const isInputPage = computed(() => page.value === 'input')
const isResultPage = computed(() => page.value === 'result')
const currentFeature = computed(() => FEATURES.find((feature) => feature.mode === mode.value))
const question = computed({
  get: () => (isAnswerMode.value ? answerQuestionInput.value : optimizedQuestionInput.value),
  set: (value) => {
    if (isAnswerMode.value) answerQuestionInput.value = value
    else optimizedQuestionInput.value = value
  },
})
const hasPresentationText = computed(() => Boolean(presentationText.value.trim()))
const presentationQuestions = computed(() => {
  if (!Array.isArray(result.value?.questions)) return []
  return [...result.value.questions].sort((left, right) => Number(left.score) - Number(right.score))
})
const presentationQuestionGroups = computed(() => [
  { level: 'easy', label: '简单', score: 60 },
  { level: 'medium', label: '中等', score: 80 },
  { level: 'hard', label: '困难', score: 100 },
].map((group) => ({
  ...group,
  questions: presentationQuestions.value.filter((item) => item.level === group.level),
})))
const canSubmit = computed(() => {
  if (!teachingCourseId.value) return false
  if (isPresentationMode.value) {
    return (presentationFiles.value.length > 0 || hasPresentationText.value)
      && presentationText.value.length <= 30000
  }
  if (!question.value.trim() || question.value.length > 1000) return false
  if (isAnswerMode.value) {
    return Boolean(studentAnswer.value.trim()) && studentAnswer.value.length <= 1000
  }
  return true
})

function resetResultState() {
  result.value = null
  errorMessage.value = ''
  revealedOptimizedQuestions.value = []
  revealedPresentationQuestions.value = []
}

function openFeature(nextMode) {
  if (loading.value) return
  if (!teachingCourseId.value) { openTeaching(); return }
  mode.value = nextMode
  resetResultState()
  page.value = 'input'
}

async function openPrep() {
  page.value = 'prep-list'; courseError.value = ''; courseLoading.value = true
  try { const items = await listCourses(); teachingCourseId.value = items.find((course) => course.name === '人工智能导论')?.id || teachingCourseId.value; courses.value = await Promise.all(items.map(async (course) => ({ ...course, _materialCount: (await listMaterials(course.id)).length }))) } catch (error) { courseError.value = error instanceof Error ? error.message : '加载课程失败' } finally { courseLoading.value = false }
}
async function openTeaching() { page.value = 'teaching-select'; teachingError.value = ''; teachingLoading.value = true; clearCurrentSession(); try { teachingCourses.value = await listCourses() } catch (error) { teachingError.value = error instanceof Error ? error.message : '加载课程失败' } finally { teachingLoading.value = false } }
function chooseTeachingCourse(course) { if (course.status !== 'ready') return; teachingCourseId.value = course.id; teachingCourseName.value = course.name; resetResultState(); optimizedQuestionInput.value = ''; answerQuestionInput.value = ''; studentAnswer.value = ''; presentationFiles.value = []; presentationText.value = ''; page.value = 'teaching-home' }
function switchTeachingCourse() { teachingCourseId.value = ''; teachingCourseName.value = ''; clearCurrentSession(); openTeaching() }
function goBack() {
  if (isResultPage.value) returnToInput()
  else if (page.value === 'teaching-home') openTeaching()
  else if (isTeachingSelect.value || page.value === 'prep-list') goHome(false)
  else if (page.value === 'prep-form' || page.value === 'prep-detail') openPrep()
  else if (isHistoryPage.value || isAnalyticsPage.value) page.value = 'teaching-home'
  else if (isInputPage.value) page.value = 'teaching-home'
  else goHome(false)
}
async function openHistory() { page.value = 'teaching-history'; historyPage.value = 1; historyDetail.value = null; await loadHistory() }
async function loadHistory() { if (!teachingCourseId.value) return; historyLoading.value = true; historyError.value = ''; try { const data = await listHistory(teachingCourseId.value, { task_type: historyTaskType.value || undefined, created_from: historyFrom.value || undefined, created_to: historyTo.value || undefined, page: historyPage.value, page_size: historyPageSize.value }); historyItems.value = data.items; historyTotal.value = data.total } catch (error) { historyError.value = error instanceof Error ? error.message : '加载历史失败' } finally { historyLoading.value = false } }
async function showHistoryDetail(item) { try { historyDetail.value = await getHistoryEvent(teachingCourseId.value, item.id) } catch (error) { historyError.value = error instanceof Error ? error.message : '加载详情失败' } }
async function removeHistory(item) { if (!window.confirm('确认删除这条历史记录？')) return; try { await deleteHistoryEvent(teachingCourseId.value, item.id); await loadHistory(); historyDetail.value = null } catch (error) { historyError.value = error instanceof Error ? error.message : '删除历史失败' } }
async function removeAllHistory() { if (!window.confirm(`确认清空“${teachingCourseName.value}”的全部历史记录？`)) return; try { await clearHistory(teachingCourseId.value); await loadHistory(); historyDetail.value = null } catch (error) { historyError.value = error instanceof Error ? error.message : '清空历史失败' } }
function exportHistory() { window.open(historyCsvUrl(teachingCourseId.value, { task_type: historyTaskType.value || undefined, created_from: historyFrom.value || undefined, created_to: historyTo.value || undefined }), '_blank') }
function formatHistoryTime(value) { try { return new Date(value).toLocaleString('zh-CN') } catch { return value } }
function historySummary(item) { const input = item.input_json || {}; if (typeof input.question === 'string') return input.question.slice(0, 100); if (typeof input.text_length === 'number') return `汇报材料（${input.text_length}字）`; return '教学操作记录' }
async function openAnalytics() { page.value = 'teaching-analytics'; await loadAnalytics() }
async function loadAnalytics() { if (!teachingCourseId.value) return; analyticsLoading.value = true; analyticsError.value = ''; try { analyticsData.value = await getAnalytics(teachingCourseId.value, { created_from: analyticsFrom.value || undefined, created_to: analyticsTo.value || undefined }) } catch (error) { analyticsError.value = error instanceof Error ? error.message : '加载学情统计失败' } finally { analyticsLoading.value = false } }
async function generateLearningReport() { reportLoading.value = true; reportError.value = ''; try { learningReport.value = await createLearningReport(teachingCourseId.value, { created_from: analyticsFrom.value || undefined, created_to: analyticsTo.value || undefined }) } catch (error) { reportError.value = error instanceof Error ? error.message : '生成报告失败' } finally { reportLoading.value = false } }
function resetCourseForm() { courseForm.value = { name: '', description: '', grade_level: '', teaching_goal: '' } }
async function saveCourse() {
  courseLoading.value = true; courseError.value = ''
  try { const saved = selectedCourse.value ? await updateCourse(selectedCourse.value.id, courseForm.value) : await createCourse(courseForm.value); await openPrep(); await openCourse(saved.id) } catch (error) { courseError.value = error instanceof Error ? error.message : '保存课程失败' } finally { courseLoading.value = false }
}
async function openCourse(id) {
  selectedCourse.value = courses.value.find((item) => item.id === id) || selectedCourse.value
  if (!selectedCourse.value) return
  page.value = 'prep-detail'; courseLoading.value = true; courseError.value = ''; searchResults.value = []
  try { courseMaterials.value = await listMaterials(id); selectedCourse.value = courses.value.find((item) => item.id === id) || selectedCourse.value; const status = await getBuildStatus(id); selectedCourse.value = { ...selectedCourse.value, status: status.status }; if (status.error) courseNotice.value = status.error } catch (error) { courseError.value = error instanceof Error ? error.message : '加载课程详情失败' } finally { courseLoading.value = false }
}
async function removeCourse(course) { if (!window.confirm(`确认删除课程“${course.name}”？`)) return; try { await deleteCourse(course.id); await openPrep() } catch (error) { courseError.value = error instanceof Error ? error.message : '删除课程失败' } }
async function handleCourseFile(event) { const files = Array.from(event.target.files || []); event.target.value = ''; await uploadCourseFiles(files) }
async function uploadCourseFiles(files) { for (const file of files) { try { await uploadMaterial(selectedCourse.value.id, file) } catch (error) { courseError.value = error instanceof Error ? error.message : '上传资料失败' } } await openCourse(selectedCourse.value.id) }
function handleCourseDrop(event) { event.preventDefault(); if (!isPresetCourse.value && selectedCourse.value?.status !== 'building') uploadCourseFiles(Array.from(event.dataTransfer?.files || [])) }
async function removeMaterial(material) { if (!window.confirm(`确认删除资料“${material.filename}”？`)) return; try { await deleteMaterial(selectedCourse.value.id, material.id); courseNotice.value = '资料已删除，如需使用请重新构建知识库。'; await openCourse(selectedCourse.value.id) } catch (error) { courseError.value = error instanceof Error ? error.message : '删除资料失败' } }
async function rebuildCourse() { courseLoading.value = true; courseError.value = ''; try { const status = await buildCourse(selectedCourse.value.id); courseNotice.value = status.error || (status.status === 'ready' ? '知识库构建完成。' : '知识库构建失败。'); await openCourse(selectedCourse.value.id) } catch (error) { courseError.value = error instanceof Error ? error.message : '构建失败' } finally { courseLoading.value = false } }
async function runCourseSearch() { if (!searchQuery.value.trim()) return; courseLoading.value = true; courseError.value = ''; try { courseSearchResult.value = await searchCourse(selectedCourse.value.id, searchQuery.value.trim()) } catch (error) { courseError.value = error instanceof Error ? error.message : '检索失败' } finally { courseLoading.value = false } }
onMounted(() => { teachingCourseId.value = ''; teachingCourseName.value = '' })

function clearCurrentSession() {
  if (isQuestionMode.value) optimizedQuestionInput.value = ''
  if (isAnswerMode.value) {
    answerQuestionInput.value = ''
    studentAnswer.value = ''
  }
  if (isPresentationMode.value) {
    presentationFiles.value = []
    presentationText.value = ''
    if (fileInput.value) fileInput.value.value = ''
  }
  resetResultState()
}

function goHome(clearInput = false) {
  if (loading.value) return
  if (clearInput) clearCurrentSession()
  else resetResultState()
  page.value = 'home'
}

function returnToInput() {
  if (loading.value || !mode.value) return
  errorMessage.value = ''
  page.value = 'input'
}

function toggleOptimizedQuestion(index) {
  revealedOptimizedQuestions.value = revealedOptimizedQuestions.value.includes(index)
    ? revealedOptimizedQuestions.value.filter((itemIndex) => itemIndex !== index)
    : [...revealedOptimizedQuestions.value, index]
}

function isOptimizedQuestionRevealed(index) {
  return revealedOptimizedQuestions.value.includes(index)
}

function togglePresentationQuestion(index) {
  revealedPresentationQuestions.value = revealedPresentationQuestions.value.includes(index)
    ? revealedPresentationQuestions.value.filter((itemIndex) => itemIndex !== index)
    : [...revealedPresentationQuestions.value, index]
}

function isPresentationQuestionRevealed(index) {
  return revealedPresentationQuestions.value.includes(index)
}

function setPresentationFiles(files) {
  const selectedFiles = Array.from(files || [])
  if (!selectedFiles.length) return

  const unsupportedFile = selectedFiles.find((file) => {
    const dotIndex = file.name.lastIndexOf('.')
    const extension = dotIndex >= 0 ? file.name.slice(dotIndex).toLowerCase() : ''
    return !PRESENTATION_FILE_TYPES.includes(extension)
  })
  if (unsupportedFile) {
    errorMessage.value = `文件“${unsupportedFile.name}”格式不受支持，请上传PPTX、DOCX、MD或TXT文件。`
    return
  }

  const oversizedFile = selectedFiles.find((file) => file.size > MAX_PRESENTATION_FILE_BYTES)
  if (oversizedFile) {
    errorMessage.value = `文件“${oversizedFile.name}”超过单文件50MB限制。`
    return
  }

  const existingKeys = new Set(
    presentationFiles.value.map((file) => `${file.name}\u0000${file.size}\u0000${file.lastModified}`),
  )
  const addedKeys = new Set()
  const newFiles = selectedFiles.filter((file) => {
    const key = `${file.name}\u0000${file.size}\u0000${file.lastModified}`
    if (existingKeys.has(key) || addedKeys.has(key)) return false
    addedKeys.add(key)
    return true
  })
  const combinedFiles = [...presentationFiles.value, ...newFiles]

  if (combinedFiles.length > MAX_PRESENTATION_FILES) {
    errorMessage.value = '一次最多上传10个文件，本次新增文件未添加。'
    return
  }

  const totalBytes = combinedFiles.reduce((total, file) => total + file.size, 0)
  if (totalBytes > MAX_PRESENTATION_TOTAL_FILE_BYTES) {
    errorMessage.value = '本次所有文件合计不能超过100MB，本次新增文件未添加。'
    return
  }

  presentationFiles.value = combinedFiles
  errorMessage.value = ''
}

function handleFileInput(event) {
  setPresentationFiles(event.target.files)
  event.target.value = ''
}

function removePresentationFile(index) {
  presentationFiles.value = presentationFiles.value.filter((_, fileIndex) => fileIndex !== index)
}

function openFilePicker() {
  fileInput.value?.click()
}

function formatFileSize(size) {
  if (size < 1024 * 1024) return `${Math.max(1, Math.round(size / 1024))} KB`
  return `${(size / (1024 * 1024)).toFixed(1)} MB`
}

async function submit() {
  if (loading.value) return
  if (!canSubmit.value) {
    if (isPresentationMode.value) {
      errorMessage.value = '请上传一个文件或输入纯文本材料。'
    }
    return
  }
  loading.value = true
  errorMessage.value = ''
  result.value = null
  revealedOptimizedQuestions.value = []
  revealedPresentationQuestions.value = []

  try {
    let nextResult
    if (isQuestionMode.value) {
      nextResult = await optimizeQuestion(question.value.trim(), teachingCourseId.value)
    } else if (isAnswerMode.value) {
      nextResult = await evaluateAnswer(question.value.trim(), studentAnswer.value.trim(), teachingCourseId.value)
    } else {
      nextResult = await generatePresentationQuestions(
        presentationFiles.value,
        presentationText.value, teachingCourseId.value,
      )
    }
    result.value = nextResult
    page.value = 'result'
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '请求失败，请稍后重试。'
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <main class="page-shell">
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
      >主页</button>
      <template v-if="teachingCourseId && (isTeachingHome || isInputPage || isResultPage || isHistoryPage || isAnalyticsPage)">
        <span class="current-course-label">当前课程：{{ teachingCourseName }}</span>
        <button type="button" class="navigation-button" :disabled="loading" @click="switchTeachingCourse">切换课程</button>
      </template>
    </nav>

    <header class="hero">
      <div class="eyebrow">AI · 课程学习反馈</div>
      <h1>课程知识增强教学辅助系统</h1>
      <p>基于课程PPT知识库生成学习反馈</p>
    </header>

    <section v-if="isHomePage" class="home-menu landing-menu" aria-label="系统入口">
      <button type="button" class="home-feature-card feature-prep" @click="openPrep">
        <span class="entry-kicker">教师工作台</span><strong>教师备课端</strong><span class="entry-description">管理课程、资料、知识库与学情</span><span class="home-feature-arrow">进入</span>
      </button>
      <button type="button" class="home-feature-card feature-teaching" @click="openTeaching">
        <span class="entry-kicker">课堂学习</span><strong>教学端</strong><span class="entry-description">选择课程，开始学习反馈</span><span class="home-feature-arrow">进入</span>
      </button>
    </section>

    <section v-else-if="isTeachingHome" class="home-menu" aria-label="教学端功能">
      <button v-for="feature in FEATURES" :key="feature.mode" type="button" class="home-feature-card" :class="feature.className" @click="openFeature(feature.mode)"><strong>{{ feature.title }}</strong><span class="home-feature-arrow">进入</span></button>
      <button type="button" class="home-feature-card feature-history" @click="openHistory"><strong>历史记录</strong><span class="home-feature-arrow">进入</span></button>
      <button type="button" class="home-feature-card feature-analytics" @click="openAnalytics"><strong>学情概览</strong><span class="home-feature-arrow">进入</span></button>
    </section>

    <section v-else-if="isAnalyticsPage" class="workspace prep-workspace">
      <header class="view-heading"><span>ANALYTICS</span><h2>学情概览</h2></header>
      <div class="prep-content"><div class="history-filters"><label>起始日期<input v-model="analyticsFrom" type="date" @change="loadAnalytics" /></label><label>结束日期<input v-model="analyticsTo" type="date" @change="loadAnalytics" /></label><button type="button" class="text-button" @click="loadAnalytics">刷新统计</button><button type="button" class="submit-button small-button" :disabled="reportLoading" @click="generateLearningReport">{{ reportLoading ? '正在生成...' : '生成AI学情报告' }}</button></div><p v-if="analyticsError" class="message error-message">{{ analyticsError }}</p><p v-if="reportError" class="message error-message">{{ reportError }}</p><p v-if="analyticsLoading" class="muted-text">正在统计真实教学记录...</p><template v-else-if="analyticsData"><div v-if="analyticsData.data_insufficient" class="message notice-message">数据不足：当前范围仅 {{ analyticsData.sample_size }} 条记录，少于 10 条，仅展示事实统计，不生成结论。</div><div class="analytics-grid"><article class="analytics-card"><strong>{{ analyticsData.sample_size }}</strong><span>记录总数</span></article><article v-for="(count, task) in analyticsData.usage_counts" :key="task" class="analytics-card"><strong>{{ count }}</strong><span>{{ task }}</span></article></div><div class="analytics-sections"><section><h3>问题评价等级分布</h3><ul><li v-for="(count, level) in analyticsData.score_distribution.levels" :key="level">{{ level }}：{{ count }}</li></ul><p>分数：{{ analyticsData.score_distribution.scores.join('、') || '暂无' }}</p></section><section><h3>答案评价常见问题</h3><ul><li v-for="item in analyticsData.common_issues" :key="item.value">{{ item.value }}（{{ item.count }}）</li><li v-if="!analyticsData.common_issues.length">暂无</li></ul></section><section><h3>课程依据高频章节</h3><ul><li v-for="item in analyticsData.frequent_chapters" :key="item.value">{{ item.value }}（{{ item.count }}）</li><li v-if="!analyticsData.frequent_chapters.length">暂无</li></ul></section><section><h3>低分或待改进高频知识点</h3><ul><li v-for="item in analyticsData.low_score_knowledge_points" :key="item.value">{{ item.value }}（{{ item.count }}，可追溯 {{ item.event_ids.length }} 条记录）</li><li v-if="!analyticsData.low_score_knowledge_points.length">暂无</li></ul></section></div></template><section v-if="learningReport" class="report-panel"><h3>AI学情分析报告</h3><p class="muted-text">统计范围：{{ learningReport.created_from || '全部' }} 至 {{ learningReport.created_to || '全部' }} · {{ learningReport.record_count }} 条记录 · {{ formatHistoryTime(learningReport.generated_at) }}</p><article v-for="(items, section) in learningReport.report" :key="section" class="report-section"><h4>{{ section }}</h4><div v-for="item in items" :key="item.conclusion"><strong>{{ item.conclusion }}</strong><p>{{ item.evidence }}</p></div></article></section></div>
    </section>

    <section v-else-if="isHistoryPage" class="workspace prep-workspace">
      <header class="view-heading"><span>HISTORY</span><h2>教学历史记录</h2></header>
      <div class="prep-content"><div class="history-filters"><label>功能<select v-model="historyTaskType" @change="historyPage = 1; loadHistory()"><option value="">全部</option><option value="question_optimize">问题优化</option><option value="answer_evaluate">答案评价</option><option value="presentation_questions">汇报提问</option></select></label><label>起始日期<input v-model="historyFrom" type="date" @change="historyPage = 1; loadHistory()" /></label><label>结束日期<input v-model="historyTo" type="date" @change="historyPage = 1; loadHistory()" /></label><button type="button" class="text-button" @click="exportHistory">导出 CSV</button><button type="button" class="text-button danger-button" :disabled="!historyItems.length && !historyTotal" @click="removeAllHistory">清空当前课程</button></div><p v-if="historyError" class="message error-message">{{ historyError }}</p><p v-if="historyLoading" class="muted-text">正在加载历史记录...</p><p v-else-if="!historyItems.length" class="empty-state">当前筛选条件下暂无历史记录。</p><div v-else class="history-table"><div v-for="item in historyItems" :key="item.id" class="history-row"><div><strong>{{ formatHistoryTime(item.created_at) }}</strong><span>{{ item.task_type }}</span><p>{{ historySummary(item) }}</p></div><div class="history-score">{{ item.score ?? '—' }}<small>{{ item.level || '' }}</small></div><div class="card-actions"><button type="button" class="text-button" @click="showHistoryDetail(item)">详情</button><button type="button" class="text-button danger-button" @click="removeHistory(item)">删除</button></div></div></div><div class="history-pagination"><button type="button" class="text-button" :disabled="historyPage <= 1" @click="historyPage -= 1; loadHistory()">上一页</button><span>第 {{ historyPage }} / {{ Math.max(1, Math.ceil(historyTotal / historyPageSize)) }} 页 · 共 {{ historyTotal }} 条</span><button type="button" class="text-button" :disabled="historyPage >= Math.ceil(historyTotal / historyPageSize)" @click="historyPage += 1; loadHistory()">下一页</button></div><div v-if="historyDetail" class="history-detail"><h3>记录详情</h3><p>匿名学生：{{ historyDetail.student_id || '未提供' }}</p><pre>{{ JSON.stringify(historyDetail.output_json, null, 2) }}</pre><button type="button" class="text-button" @click="historyDetail = null">关闭</button></div></div>
    </section>

    <section v-else-if="isTeachingSelect" class="workspace prep-workspace">
      <header class="view-heading"><span>TEACH</span><h2>选择课程</h2></header>
      <div class="prep-content teaching-course-select"><p class="muted-text">请选择一门已构建完成的课程开始学习。</p><p v-if="teachingLoading" class="muted-text">正在加载课程...</p><p v-if="teachingError" class="message error-message">{{ teachingError }}</p><div v-if="!teachingLoading && !teachingCourses.length" class="empty-state">暂无课程。</div><button v-for="course in teachingCourses" :key="course.id" type="button" class="teaching-course-option" :disabled="course.status !== 'ready'" @click="chooseTeachingCourse(course)"><span><strong>{{ course.name }}</strong><small>{{ course.description || '暂无简介' }}</small></span><span class="course-status" :class="`status-${course.status}`">{{ course.status }}</span></button></div>
    </section>

    <section v-else-if="page === 'prep-list'" class="workspace prep-workspace">
      <header class="view-heading"><span>PREP</span><h2>课程列表</h2></header>
      <div class="prep-content">
        <div class="section-title-row"><p class="muted-text">管理课程资料并构建独立知识库</p><button class="submit-button small-button" type="button" @click="selectedCourse = null; resetCourseForm(); page = 'prep-form'">新建课程</button></div>
        <p v-if="courseLoading" class="muted-text">正在加载课程...</p>
        <p v-if="courseError" class="message error-message">{{ courseError }}</p>
        <p v-else-if="!courses.length" class="empty-state">暂无课程，先创建一门课程吧。</p>
        <div v-else class="course-grid"><article v-for="course in courses" :key="course.id" class="course-card"><div><span class="course-status" :class="`status-${course.status}`">{{ course.status }}</span><h3>{{ course.name }}</h3><p>{{ course.description || '暂无简介' }}</p><small>资料数：{{ course._materialCount ?? '—' }}</small></div><div class="card-actions"><button type="button" class="text-button" @click="openCourse(course.id)">详情</button><button type="button" class="text-button" @click="selectedCourse = course; courseForm = { name: course.name, description: course.description, grade_level: course.grade_level, teaching_goal: course.teaching_goal }; page = 'prep-form'">编辑</button><button type="button" class="text-button danger-button" :disabled="course.id === teachingCourseId" @click="removeCourse(course)">删除</button></div></article></div>
      </div>
    </section>

    <section v-else-if="page === 'prep-form'" class="workspace prep-workspace">
      <header class="view-heading"><span>PREP</span><h2>{{ selectedCourse ? '编辑课程' : '新建课程' }}</h2></header>
      <form class="prep-content course-form" @submit.prevent="saveCourse"><label>课程名称<input v-model="courseForm.name" maxlength="100" required /></label><label>简介<textarea v-model="courseForm.description" maxlength="2000" rows="3" /></label><label>年级<input v-model="courseForm.grade_level" maxlength="100" /></label><label>教学目标<textarea v-model="courseForm.teaching_goal" maxlength="2000" rows="3" /></label><button class="submit-button" :disabled="courseLoading">保存课程</button></form>
    </section>

    <section v-else-if="page === 'prep-detail'" class="workspace prep-workspace">
      <header class="view-heading"><span>PREP</span><h2>{{ selectedCourse?.name }}</h2></header>
      <div class="prep-content"><p v-if="courseLoading" class="muted-text">正在加载课程详情...</p><template v-else><div class="detail-meta"><span class="course-status" :class="`status-${selectedCourse?.status}`">{{ selectedCourse?.status }}</span><span>资料 {{ courseMaterials.length }} 份</span></div><div v-if="isPresetCourse" class="message notice-message">预置课程资料不可修改，如需新资料请创建课程。</div><div v-if="courseError" class="message error-message">{{ courseError }}</div><div v-if="courseNotice" class="message notice-message">{{ courseNotice }}</div><div class="material-toolbar drop-zone" @dragover.prevent @drop="handleCourseDrop"><input ref="courseFileInput" type="file" multiple accept=".pptx,.docx,.md,.txt,.pdf" :disabled="isPresetCourse || selectedCourse?.status === 'building'" @change="handleCourseFile" /><span>也可将资料拖拽到此处</span><button class="submit-button" type="button" :disabled="isPresetCourse || courseLoading || selectedCourse?.status === 'building' || !courseMaterials.length" @click="rebuildCourse">{{ selectedCourse?.status === 'building' ? '正在构建...' : '开始构建' }}</button></div><p v-if="!courseMaterials.length" class="empty-state">暂无资料，请上传 PPTX、DOCX、MD、TXT 或 PDF 文件。</p><ul v-else class="material-list"><li v-for="material in courseMaterials" :key="material.id"><span>{{ material.filename }} · {{ formatFileSize(material.size) }}</span><button class="text-button danger-button" type="button" :disabled="isPresetCourse || selectedCourse?.status === 'building'" @click="removeMaterial(material)">删除</button></li></ul><div class="search-box"><h3>测试检索</h3><div class="search-row"><input v-model="searchQuery" placeholder="输入问题测试课程知识库" @keyup.enter="runCourseSearch" /><button class="submit-button small-button" type="button" :disabled="courseLoading || selectedCourse?.status !== 'ready'" @click="runCourseSearch">检索</button></div><template v-if="courseSearchResult"><div class="search-answer"><strong>整理答案</strong><p>{{ courseSearchResult.answer }}</p></div><ul v-if="courseSearchResult.sources?.length" class="search-results"><li v-for="item in courseSearchResult.sources" :key="item.source"><strong>{{ item.source }}</strong><p>{{ item.summary }}</p><small>{{ item.relevance }}</small></li></ul><p v-if="courseSearchResult.insufficiency_notice" class="muted-text">{{ courseSearchResult.insufficiency_notice }}</p></template><p v-else class="muted-text">构建完成后可测试检索。</p></div></template></div>
    </section>

    <section v-else-if="isInputPage" class="workspace" aria-label="教学辅助输入区">
      <header class="view-heading">
        <span>教学端</span>
        <h2>{{ currentFeature?.title }}</h2>
      </header>

      <form class="input-area" :class="{ 'presentation-input-area': isPresentationMode }" @submit.prevent="submit">
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

            <div v-if="presentationFiles.length" class="selected-file-list" aria-label="已选汇报文件">
              <div
                v-for="(file, index) in presentationFiles"
                :key="`${file.name}-${file.size}-${file.lastModified}-${index}`"
                class="selected-file-card"
              >
                <div class="selected-file-copy">
                  <strong>{{ file.name }}</strong>
                  <span>{{ formatFileSize(file.size) }}</span>
                </div>
                <button
                  type="button"
                  class="selected-file-remove"
                  :aria-label="`删除文件 ${file.name}`"
                  @click="removePresentationFile(index)"
                >×</button>
              </div>
            </div>

            <label class="visually-hidden" for="presentation-text">汇报材料文本</label>
            <textarea
              id="presentation-text"
              v-model="presentationText"
              class="presentation-textarea"
              maxlength="30000"
              rows="10"
              placeholder="粘贴汇报摘要、讲稿或材料内容，也可以通过左下角添加文件..."
            />

            <div class="presentation-toolbar">
              <div class="presentation-toolbar-left">
                <button
                  type="button"
                  class="file-add-button"
                  aria-label="添加汇报文件"
                  title="添加PPTX、DOCX、MD或TXT文件"
                  @click="openFilePicker"
                >+</button>
                <span class="presentation-limit-hint">最多10个 · 单个50MB · 合计100MB</span>
              </div>
              <span class="presentation-char-count">{{ presentationText.length }}/30000</span>
              <button
                class="submit-button presentation-submit"
                type="submit"
                :disabled="loading || !canSubmit"
              >
                <span v-if="loading" class="spinner" aria-hidden="true" />
                {{ loading ? '正在解析材料并生成问题...' : '问题生成' }}
              </button>
            </div>
          </div>
        </template>

        <template v-else>
          <div class="field-block">
            <div class="field-heading">
              <label for="question">{{ isQuestionMode ? '学生原始问题' : '学生回答的问题' }}</label>
              <span>{{ question.length }}/1000</span>
            </div>
            <textarea
              id="question"
              v-model="question"
              maxlength="1000"
              rows="4"
              :placeholder="isQuestionMode ? '例如：卷积神经网络为什么适合处理图片？' : '请输入需要评价的课程问题'"
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
              placeholder="请输入学生的原始回答"
            />
          </div>
        </template>

        <button
          v-if="!isPresentationMode"
          class="submit-button"
          type="submit"
          :disabled="loading || !canSubmit"
        >
          <span v-if="loading" class="spinner" aria-hidden="true" />
          {{ loading
            ? '正在检索课程资料并生成反馈...'
            : (isQuestionMode ? '生成问题优化建议' : '评价并优化答案')
          }}
        </button>
      </form>
    </section>

    <p v-if="isInputPage && errorMessage" class="message error-message" role="alert">{{ errorMessage }}</p>

    <section v-if="isResultPage && result" class="result-area" aria-live="polite">
      <div v-if="result.insufficiency_notice" class="message notice-message">
        <strong>资料提示</strong>
        <span>{{ result.insufficiency_notice }}</span>
      </div>

      <template v-if="isPresentationMode && result.questions">
        <section class="result-section presentation-question-section">
          <h2>课程汇报提问</h2>
          <div class="level-question-list">
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
              <div v-if="isPresentationQuestionRevealed(index)" class="level-question-content">
                <ol class="presentation-group-list">
                  <li v-for="item in group.questions" :key="item.question">{{ item.question }}</li>
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
            <strong class="evaluation-score">{{ result.question_evaluation.score }}</strong>
            <div>
              <span class="evaluation-score-unit">分</span>
              <strong class="evaluation-level">{{ result.question_evaluation.level }}</strong>
            </div>
          </div>
          <div class="evaluation-details">
            <div>
              <strong>评价</strong>
              <p>{{ formatCourseReferences(result.question_evaluation.evaluation) }}</p>
            </div>
            <div>
              <strong>建议</strong>
              <p>{{ formatCourseReferences(result.question_evaluation.suggestion) }}</p>
            </div>
          </div>
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
              <div v-if="isOptimizedQuestionRevealed(index)" class="level-question-content">
                <p>{{ formatCourseReferences(item.question) }}</p>
                <div class="thinking-angle">
                  <strong>思考角度</strong>
                  <span>{{ formatCourseReferences(item.improvement_focus) }}</span>
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
        <section class="result-section diagnosis-section">
          <h2>总体评价</h2>
          <p class="lead-text">{{ formatCourseReferences(result.overall_evaluation) }}</p>
        </section>

        <div class="feedback-columns">
          <section class="result-section compact-section positive-section">
            <h2>值得肯定</h2>
            <ul class="simple-list">
              <li v-for="item in result.strengths" :key="item">{{ formatCourseReferences(item) }}</li>
            </ul>
          </section>

          <section class="result-section compact-section issue-section">
            <h2>需要改进</h2>
            <p v-if="!result.issues.length" class="muted-text">暂未发现需要改进的问题。</p>
            <article v-for="item in result.issues" :key="item.description" class="issue-item">
              <strong>· {{ item.type }}</strong>
              <p>{{ formatCourseReferences(item.description) }}</p>
              <small>{{ formatCourseReferences(item.evidence_or_reason) }}</small>
            </article>
          </section>
        </div>

        <section class="result-section">
          <h2>改进建议</h2>
          <ul class="numbered-advice">
            <li v-for="(item, index) in result.improvement_suggestions" :key="item">
              <span>{{ String(index + 1).padStart(2, '0') }}</span>
              <p>{{ formatCourseReferences(item) }}</p>
            </li>
          </ul>
        </section>

        <section class="result-section answer-section">
          <h2>优化答案</h2>
          <p class="improved-answer">{{ formatCourseReferences(result.improved_answer) }}</p>
        </section>
      </template>

      <section v-if="result.course_basis?.length" class="result-section source-section">
        <h2>课程依据</h2>
        <ul class="source-list">
          <li v-for="item in result.course_basis" :key="`${item.source}-${item.reason}`">
            <strong>{{ formatCourseReferences(item.source) }}</strong>
            <p>{{ formatCourseReferences(item.reason) }}</p>
          </li>
        </ul>
      </section>
    </section>

    <footer v-if="!isHomePage">
      {{ isPresentationMode
        ? '问题仅依据本次提交的汇报材料生成 · 生成结果用于辅助学习'
        : '课程内容由现有PPT知识库提供依据 · 生成结果用于辅助学习' }}
    </footer>
  </main>
</template>
