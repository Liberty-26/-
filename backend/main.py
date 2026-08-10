"""
SteelDigitize Pro — FastAPI 入口
"""
import os
import json
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

def _app_version() -> str:
    """版本动态读取：桌面版由 Electron 注入 STEEL_VERSION，开发模式读 electron/package.json"""
    env_ver = os.getenv("STEEL_VERSION", "").strip()
    if env_ver:
        return env_ver
    pkg = Path(__file__).resolve().parent.parent / "electron" / "package.json"
    try:
        return json.loads(pkg.read_text(encoding="utf-8")).get("version", "0.0.0")
    except Exception:
        return "0.0.0"

app = FastAPI(title="SteelDigitize Pro", version=_app_version())

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
    # 桌面版：Electron 传入打包资源里的 CSV；开发模式：默认取项目根目录 CSV
    seed_csv = os.getenv("MATERIALS_SEED_CSV", "").strip() or None
    added = import_materials_seed(seed_csv)
    if added:
        print(f"[startup] 品名种子导入完成: 新增 {added} 条")


@app.get("/api/health")
def health():
    # 返回进程 PID 与前端构建指纹：Electron 据此判断 8000 端口上的后端是否与当前安装版本一致
    dist_mtime = None
    dist_hash = None
    try:
        idx = FRONTEND_DIST / "index.html"
        if idx.exists():
            dist_mtime = str(int(idx.stat().st_mtime * 1000))
            # 内容哈希比 mtime 更可靠：同一目录覆盖安装后 mtime 可能一致，哈希不会
            try:
                import hashlib
                dist_hash = hashlib.sha256(idx.read_bytes()).hexdigest()[:16]
            except Exception:
                pass
    except Exception:
        pass
    return {
        "success": True,
        "data": {
            "status": "ok",
            "pid": os.getpid(),
            "version": _app_version(),
            "dist_mtime": dist_mtime,
            "dist_hash": dist_hash,
        },
    }


# 路由式 fallback：serve 前端 dist（必须在所有 API 路由之后注册）
# API 路径返回 JSON 404，不返回 index.html（避免前端解析 HTML 报错）
@app.get("/{full_path:path}")
async def serve_frontend(full_path: str):
    if full_path.startswith("api/") or full_path.startswith("openapi") or full_path in ("docs", "redoc") or full_path.startswith(("docs/", "redoc/")):
        return JSONResponse({"success": False, "error": "Not Found"}, status_code=404)
    if not FRONTEND_DIST.exists():
        return JSONResponse({"success": False, "error": "前端未构建（开发模式请用 vite dev）"}, status_code=404)
    # 路径穿越防护：resolve 后必须仍在 dist 目录内，防 ../ 越界读文件
    try:
        file_path = (FRONTEND_DIST / full_path).resolve()
        file_path.relative_to(FRONTEND_DIST.resolve())
    except (ValueError, OSError):
        return JSONResponse({"success": False, "error": "Not Found"}, status_code=404)
    if file_path.is_file():
        return FileResponse(file_path, headers={"Cache-Control": "no-cache"})
    return FileResponse(FRONTEND_DIST / "index.html", headers={"Cache-Control": "no-cache"})
