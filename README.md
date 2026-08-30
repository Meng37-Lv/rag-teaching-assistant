# 课程知识增强教学辅助系统

本项目使用课程 PPT 构建的只读 RAG 知识库，为学生提供基于课程资料的教学反馈。

核心功能：

- `question_optimize`：评价学生问题（60-100分及分级），生成 3 个优化问题和 2 个深度思考问题；
- `answer_evaluate`：评价学生答案，指出值得肯定、需要改进和改进建议，并生成优化答案。

## 系统架构

```text
Vue 3 + Vite 前端（localhost:5173）
              ↓ HTTP API
FastAPI 后端（Uvicorn）
              ↓
现有 FAISS 索引 + BAAI/bge-small-zh Embedding
              ↓
课程上下文 + 教学 Prompt
              ↓
DeepSeek Chat Completions API
```

前端只负责输入、请求和展示；课程检索、来源校验、JSON 校验和大模型调用由后端完成。

## 项目目录

```text
AI-teaching-assistant/
├── frontend/                # Vue 3 + Vite 单页前端
│   ├── src/App.vue          # 页面展示与交互
│   ├── src/api.ts           # 带类型约束的后端 API 请求
│   └── vite.config.js       # 本地开发地址与端口
├── src/
│   ├── web_api.py           # FastAPI 应用入口
│   ├── rag_service.py       # RAG 编排与结构化结果校验
│   ├── retriever.py         # FAISS 只读检索
│   ├── source_mapper.py     # 原始 PPT 章节页码映射
│   ├── prompts.py           # 教学 Prompt
│   └── llm_client.py        # DeepSeek Chat Completions 客户端
├── scripts/                 # PPT处理、检索和命令行测试脚本
├── vector_db/               # 现有 FAISS 索引与 chunk 映射（只读）
├── data/                    # 已生成文本与切片数据（只读）
├── ppt/                     # 原始课程 PPT（只读）
├── tests/                   # 离线组件测试与验收案例
├── .env.example             # 环境变量模板
├── .gitignore
└── requirements.txt
```

## 环境要求

- Python 3.12；
- Node.js 与 npm；
- 可访问 DeepSeek API 的网络环境；
- 已存在并可读取的 `vector_db/`、`data/` 和 `ppt/`。

安装 Python 依赖：

```powershell
python -m pip install -r requirements.txt
```

安装前端依赖：

```powershell
cd frontend
npm install
```

## 环境变量

在项目根目录创建 `.env`。以下只列出变量名和用途，不包含真实密钥：

| 变量名 | 说明 |
|---|---|
| `LLM_API_KEY` | DeepSeek API 密钥 |
| `LLM_BASE_URL` | DeepSeek API Base URL |
| `LLM_MODEL` | 实际使用的 DeepSeek 模型名称 |
| `LLM_REASONING_EFFORT` | 推理强度配置（如服务商支持） |
| `LLM_ENABLE_THINKING` | 是否启用 thinking 模式 |
| `LLM_TIMEOUT_SECONDS` | LLM 请求超时时间 |
| `RAG_TOP_K` | 默认检索数量 |
| `RAG_MAX_CONTEXT_CHARS` | 课程上下文字符上限 |
| `RAG_MAX_CHUNK_CHARS` | 单个 chunk 字符上限 |

真实 API Key 只放在本地 `.env`，不要写入源码、README 或提交记录。

## 启动方式

### 1. 启动后端

在项目根目录执行：

```powershell
python -m uvicorn src.web_api:app --host 127.0.0.1 --port 8000
```

### 2. 启动前端

新开终端执行：

```powershell
cd frontend
npm run dev
```

本地统一访问地址：

```text
http://localhost:5173
```

API 路径：

- `GET /api/health`
- `POST /api/question-optimize`
- `POST /api/answer-evaluate`

## API 连通性测试

不依赖 FAISS 的 LLM 测试：

```powershell
python scripts/test_llm_api.py
```

健康检查：

```powershell
Invoke-RestMethod http://127.0.0.1:8000/api/health
```

## 命令行 RAG 测试

```powershell
python scripts/rag_chat.py --mode question_optimize --question "什么是深度学习？"
python scripts/rag_chat.py --mode answer_evaluate --question "什么是深度学习？" --answer "深度学习是机器学习的一种。"
```

## 常见问题

### 5173 端口被占用

关闭占用端口的旧 Vite 进程后重新执行 `npm run dev`，或先检查：

```powershell
netstat -ano | Select-String ":5173"
```

### PowerShell 提示 npm.ps1 被禁止执行

使用 Windows 命令入口：

```powershell
npm.cmd install
npm.cmd run dev
```

### 出现 HF_TOKEN 警告

这是 Hugging Face 未配置 Token 的提示。若模型可以正常加载并完成检索，可暂不处理；不要把 Token 写入源码或 README。

### API 请求失败

确认后端已先启动在 8000 端口，并检查 `.env` 中的 LLM 配置。不要在此过程中重建向量库。

## 知识库保护要求

`vector_db/`、`data/`、`ppt/` 是已经验证的知识库产物和来源文件，运行网站或测试时只读使用，不应修改、删除或重建。不要重新解析 PPT、清洗文本、切片、生成 Embedding 或建立 FAISS 索引。

## 测试

离线组件测试：

```powershell
python -m unittest tests.test_components
```

前端生产构建：

```powershell
cd frontend
npm run build
```

## 后续在线部署计划

后续可采用 Docker 打包 FastAPI 后端与 Vue 构建产物，并部署到 Railway，配置生产环境变量和域名。本阶段不新增或修改 Docker、Railway 配置文件。
