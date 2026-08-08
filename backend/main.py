"""
SteelDigitize Pro — FastAPI 入口
"""
import os
from pathlib import Path
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles

import config
from database import init_db, import_materials_seed
from routers import recognize, history, agent_chat, settings, materials, memory

# 确保 uploads 目录存在
UPLOAD_DIR = Path(config.UPLOAD_DIR)
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

# 前端构建产物（单进程部署：FastAPI serve dist）
# 桌面版：Electron 通过 FRONTEND_DIR 环境变量传入打包的静态目录
_frontend_env = os.getenv("FRONTEND_DIR", "").strip()
FRONTEND_DIST = Path(_frontend_env) if _frontend_env else Path(__file__).resolve().parent.parent / "frontend" / "dist"

app = FastAPI(title="SteelDigitize Pro", version="1.0.0")

# CORS：本地使用，允许所有来源
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 静态文件：/uploads/{filename} 访问图片
app.mount("/uploads", StaticFiles(directory=str(UPLOAD_DIR)), name="uploads")

# 注册路由
app.include_router(recognize.router)
app.include_router(history.router)
app.include_router(agent_chat.router)
app.include_router(settings.router)
app.include_router(materials.router)
app.include_router(memory.router)


@app.on_event("startup")
def startup():
    """启动时初始化数据库 + 导入品名种子（幂等）"""
    init_db()
    added = import_materials_seed()
    if added:
        print(f"[startup] 品名种子导入完成: 新增 {added} 条")


@app.get("/api/health")
def health():
    return {"success": True, "data": {"status": "ok"}}


# 路由式 fallback：serve 前端 dist（必须在所有 API 路由之后注册）
# API 路径返回 JSON 404，不返回 index.html（避免前端解析 HTML 报错）
@app.get("/{full_path:path}")
async def serve_frontend(full_path: str):
    if full_path.startswith("api/") or full_path.startswith("openapi") or full_path in ("docs", "redoc") or full_path.startswith(("docs/", "redoc/")):
        return JSONResponse({"success": False, "error": "Not Found"}, status_code=404)
    if not FRONTEND_DIST.exists():
        return JSONResponse({"success": False, "error": "前端未构建（开发模式请用 vite dev）"}, status_code=404)
    file_path = FRONTEND_DIST / full_path
    if file_path.is_file():
        return FileResponse(file_path)
    return FileResponse(FRONTEND_DIST / "index.html")
