# SteelDigitize Pro

手写送货单 AI 识别与对账系统。

**拍照 → 千问 OCR 识别 → 人工核对修正 → Agent 自动写入对账单 Excel**

## 技术栈

- **前端**：React 18 + Vite + TypeScript + Tailwind CSS
- **后端**：Python FastAPI + SQLite
- **OCR**：阿里云千问 qwen-vl-flash
- **Agent**：DeepSeek + openpyxl

## 快速开始

### 1. 后端

```bash
cd backend
pip install -r requirements.txt
cp .env.example .env
# 编辑 .env 填入千问 API Key 和 DeepSeek API Key
uvicorn main:app --reload --port 8000
```

### 2. 前端

```bash
cd frontend
npm install
npm run dev
```

打开浏览器访问 `http://localhost:5174`

### 3. 配置

打开「API与模型」页面：
- 输入千问 API Key
- 输入 DeepSeek API Key
- 配置对账单 Excel 文件路径
- 点击「测试连接」验证

## 使用流程

1. **上传与识别**：拖拽/点击上传手写送货单照片 → 点击「识别」→ AI 自动识别品名、规格、单位、数量、单价
2. **核对修改**：在可编辑表格中核对/修改识别结果（Enter/Tab 键盘导航，自动计算金额）
3. **保存**：点击「保存」→ 数据存入本地 SQLite
4. **Agent 写入**：切换到 Agent 页面，输入「写入单号到对账单」→ Agent 自动写入 Excel（宋体 11pt、居中、公式、合并单元格）

## 项目结构

```
backend/
├── main.py          # FastAPI 入口
├── config.py        # 配置加载
├── database.py      # SQLite 初始化 + 查询
├── models.py        # Pydantic 模型
├── ocr.py           # 千问 OCR
├── agent.py         # DeepSeek Agent 调度
├── spreadsheet.py   # openpyxl MCP 工具
├── routers/         # API 路由
│   ├── recognize.py # POST /api/recognize
│   ├── history.py   # CRUD /api/history
│   ├── agent_chat.py# POST /api/agent/chat
│   └── settings.py  # GET/POST /api/settings
└── .env.example

frontend/
└── src/
    ├── pages/       # 4 个页面
    ├── components/  # 共享组件
    ├── hooks/       # 自定义 hooks
    ├── types/       # TypeScript 类型
    └── utils/       # API 封装 + 工具函数
```

## API 接口

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | /api/health | 健康检查 |
| POST | /api/recognize | 上传图片识别 |
| GET | /api/history | 历史列表（分页搜索） |
| GET | /api/history/months | 按月统计（资料库书架，空日期聚合为 month=''） |
| POST | /api/history | 保存单据 |
| GET | /api/history/:id | 单据详情 |
| PUT | /api/history/:id | 更新单据 |
| DELETE | /api/history/:id | 删除单据 |
| GET | /api/settings | 获取配置 |
| POST | /api/settings | 保存配置 |
| POST | /api/settings/test-qwen | 测试千问连接 |
| POST | /api/agent/chat | Agent 对话 |

所有接口返回 `{"success": true/false, "error": "...", "data": {...}}`。
