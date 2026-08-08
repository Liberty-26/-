# SteelDigitize Pro

手写送货单识别与对账工作台（本地单机版，数据不上云）。

**上传单据 → 夸克扫描王识别 → 纯代码校准 → 人工审核 → Agent 生成对账单**

## 技术栈

- **前端**：React + Vite + TypeScript
- **后端**：Python FastAPI + SQLite
- **识别引擎**：夸克扫描王 image-to-excel（Agent 通道，官方 yescan SDK）
- **桌面壳**：Electron（内置后端，单进程部署）
- **自动更新**：electron-updater + GitHub Releases（云端打包）

## 目录结构

```
├── backend/            # FastAPI 后端（识别、校准、审核、品名库、记忆）
│   ├── main.py         # 入口（单进程：API + 前端静态资源）
│   ├── quark.py        # 扫描王识别封装（yescan SDK，Agent 通道）
│   ├── calibrate.py    # 纯代码校准（规格拆分 / 品名对齐 / 单位补全）
│   ├── backend_entry.py# 桌面版后端打包入口
│   └── routers/        # API 路由（recognize / history / agent / settings / materials / memory）
├── frontend/           # React 前端（工作台 / 审核区 / 资料库 / 品名库 / 设置）
├── electron/           # 桌面壳（主进程 + 自动更新 + 打包配置）
│   ├── main.js         # 启动内置后端 + 打开窗口 + 自动更新
│   ├── backend-dist/   # 打包时放内置后端（由脚本生成，不入库）
│   └── release/        # 打包产物（dmg/exe，不入库）
├── .github/workflows/  # GitHub Actions：云端自动打包 Windows 安装包
├── build_win.bat       # Windows 一键打包脚本
├── PRODUCT.md          # 产品决策记录
└── 项目经验笔记.md      # 开发过程沉淀
```

## 开发模式（浏览器）

```bash
# 后端（8000 端口）
cd backend
pip install -r requirements.txt yescan pyinstaller
cp .env.example .env   # 填入识别 Key（扫描王 Agent Key）
uvicorn main:app --port 8000

# 前端（5174 端口）
cd frontend
npm install
npm run dev
```

浏览器打开 http://localhost:5174 。识别 Key 也可在应用「设置」页填写保存。

## 桌面模式（Electron）

```bash
cd electron
npm install
npm start   # 开发模式：自动加载 vite dev server
```

生产打包：先 `cd frontend && npm run build`，再 `cd electron && npm run dist:mac`（Mac）或 `npm run dist:win`（Windows）。

## Windows 安装包（两种方式）

**方式一：本地一键脚本**（在 Windows 电脑上）

```
双击 build_win.bat
```

自动完成：装依赖 → 打包后端 → 构建前端 → 打 NSIS 安装包（含桌面快捷方式）。产物在 `electron\release\`。

**方式二：GitHub Actions 云端打包（推荐）**

仓库页面 → Actions → Build Windows Installer → Run workflow；或推送 `vX.Y.Z` 标签自动触发并发布到 Releases。

## 发布新版本（含自动更新）

1. 修改代码，提交推送
2. 更新 `electron/package.json` 的 `version`（如 `1.0.2`）
3. `git tag v1.0.2 && git push origin v1.0.2`
4. 云端自动打包并发布到 GitHub Releases
5. 已安装用户的应用启动时自动检查更新（设置页「关于」里也可手动检查）

## 主要页面

| 页面 | 说明 |
|---|---|
| 工作台 | 上传/拖拽单据 → 待识别队列 → 开始识别（四阶段真实进度）→ 对话/技能 |
| 审核区 | 待审队列、原图对照（缩放/拖拽）、逐格编辑（键盘导航/框选多选）、确认入库 |
| 资料库 | 账本书架、按月归档、搜索；仅可改日期与单号，明细修改去审核区 |
| 品名库 | 标准品名 + 别名，识别结果自动对齐 |
| 设置 | 识别引擎/工作助手 API 配置、测速、模型列表、检查更新 |

## 数据

- SQLite：`backend/data.db`（桌面版在应用数据目录）
- 上传原图：`backend/uploads/`
- 所有数据只存本机
