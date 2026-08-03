<script setup>
import { computed, ref } from 'vue'
import { evaluateAnswer, generatePresentationQuestions, optimizeQuestion } from './api.js'

const mode = ref('question')
const question = ref('')
const studentAnswer = ref('')
const loading = ref(false)
const errorMessage = ref('')
const result = ref(null)
const revealedOptimizedQuestions = ref([])
const revealedPresentationQuestions = ref([])
const presentationFiles = ref([])
const presentationText = ref('')
const fileInput = ref(null)

const QUESTION_LEVEL_CLASSES = {
  easy: 'level-easy',
  medium: 'level-medium',
  hard: 'level-hard',
}
const PRESENTATION_FILE_TYPES = ['.pptx', '.docx', '.md', '.txt']
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
const hasPresentationText = computed(() => Boolean(presentationText.value.trim()))
const presentationQuestions = computed(() => {
  if (!Array.isArray(result.value?.questions)) return []
  return [...result.value.questions].sort((left, right) => Number(left.score) - Number(right.score))
})
const canSubmit = computed(() => {
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

function selectMode(nextMode) {
  if (loading.value || mode.value === nextMode) return
  mode.value = nextMode
  result.value = null
  errorMessage.value = ''
  revealedOptimizedQuestions.value = []
  revealedPresentationQuestions.value = []
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
    if (isQuestionMode.value) {
      result.value = await optimizeQuestion(question.value.trim())
    } else if (isAnswerMode.value) {
      result.value = await evaluateAnswer(question.value.trim(), studentAnswer.value.trim())
    } else {
      result.value = await generatePresentationQuestions(
        presentationFiles.value,
        presentationText.value,
      )
    }
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '请求失败，请稍后重试。'
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <main class="page-shell">
    <header class="hero">
      <div class="eyebrow">AI · 课程学习反馈</div>
      <h1>课程知识增强教学辅助系统</h1>
      <p>基于课程PPT知识库生成学习反馈</p>
    </header>

    <section class="workspace" aria-label="教学辅助操作区">
      <nav class="mode-switch" aria-label="选择反馈模式">
        <button
          type="button"
          :class="{ active: isQuestionMode }"
          :aria-pressed="isQuestionMode"
          @click="selectMode('question')"
        >
          <span class="mode-number">01</span>
          优化学生问题
        </button>
        <button
          type="button"
          :class="{ active: isAnswerMode }"
          :aria-pressed="isAnswerMode"
          @click="selectMode('answer')"
        >
          <span class="mode-number">02</span>
          评价学生答案
        </button>
        <button
          type="button"
          :class="{ active: isPresentationMode }"
          :aria-pressed="isPresentationMode"
          @click="selectMode('presentation')"
        >
          <span class="mode-number">03</span>
          课程汇报提问
        </button>
      </nav>

      <form class="input-area" :class="{ 'presentation-input-area': isPresentationMode }" @submit.prevent="submit">
        <template v-if="isPresentationMode">
          <div class="presentation-composer">
            <input
              id="presentation-file"
              ref="fileInput"
              class="visually-hidden"
              type="file"
              multiple
              accept=".pptx,.docx,.md,.txt"
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

    <p v-if="errorMessage" class="message error-message" role="alert">{{ errorMessage }}</p>

    <section v-if="result" class="result-area" aria-live="polite">
      <div v-if="result.insufficiency_notice" class="message notice-message">
        <strong>资料提示</strong>
        <span>{{ result.insufficiency_notice }}</span>
      </div>

      <template v-if="isPresentationMode && result.questions">
        <section class="result-section presentation-question-section">
          <h2>课程汇报提问</h2>
          <div class="level-question-list">
            <article
              v-for="(item, index) in presentationQuestions"
              :key="`${item.level}-${item.question}`"
              class="level-question-item"
            >
              <button
                type="button"
                class="level-selector"
                :class="[
                  QUESTION_LEVEL_CLASSES[item.level],
                  { revealed: isPresentationQuestionRevealed(index) },
                ]"
                :aria-expanded="isPresentationQuestionRevealed(index)"
                @click="togglePresentationQuestion(index)"
              >
                <span>{{ item.label }}</span>
                <strong>{{ item.score }}分</strong>
              </button>
              <div v-if="isPresentationQuestionRevealed(index)" class="level-question-content">
                <p>{{ item.question }}</p>
              </div>
            </article>
          </div>
        </section>
      </template>

      <template v-if="result.task_type === 'question_optimize'">
        <section class="result-section diagnosis-section">
          <h2>问题诊断</h2>
          <p class="lead-text">{{ formatCourseReferences(result.question_diagnosis) }}</p>
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

    <footer>
      {{ isPresentationMode
        ? '问题仅依据本次提交的汇报材料生成 · 生成结果用于辅助学习'
        : '课程内容由现有PPT知识库提供依据 · 生成结果用于辅助学习' }}
    </footer>
  </main>
</template>
