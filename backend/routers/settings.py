"""
配置管理接口 — 通用化，不绑定特定厂商
"""
import time
import base64
import struct
import zlib
import httpx
from fastapi import APIRouter, HTTPException
import config
from models import TestQwenRequest
from quark import call_quark_excel

router = APIRouter(prefix="/api/settings", tags=["settings"])


def _make_test_png() -> str:
    """动态生成 20x20 白色 PNG，返回 base64 data URL"""
    w, h = 20, 20
    sig = b'\x89PNG\r\n\x1a\n'
    ihdr = struct.pack('>IIBBBBB', w, h, 8, 2, 0, 0, 0)
    ihdr_crc = zlib.crc32(b'IHDR' + ihdr) & 0xffffffff
    ihdr_c = struct.pack('>I', 13) + b'IHDR' + ihdr + struct.pack('>I', ihdr_crc)
    raw = b''.join(b'\x00' + b'\xff\xff\xff' * w for _ in range(h))
    compressed = zlib.compress(raw)
    idat_crc = zlib.crc32(b'IDAT' + compressed) & 0xffffffff
    idat_c = struct.pack('>I', len(compressed)) + b'IDAT' + compressed + struct.pack('>I', idat_crc)
    iend_crc = zlib.crc32(b'IEND') & 0xffffffff
    iend_c = struct.pack('>I', 0) + b'IEND' + struct.pack('>I', iend_crc)
    return "data:image/png;base64," + base64.b64encode(sig + ihdr_c + idat_c + iend_c).decode()


@router.get("")
async def get_settings():
    def mask(key: str) -> str:
        if not key: return ""
        return "*" * max(0, len(key) - 4) + key[-4:]
    return {
        "success": True,
        "data": {
            "vision_api_key": mask(config.VISION_API_KEY),
            "vision_api_base": config.VISION_API_BASE,
            "vision_model": config.VISION_MODEL,
            "agent_api_key": mask(config.AGENT_API_KEY),
            "agent_api_base": config.AGENT_API_BASE,
            "agent_model": config.AGENT_MODEL,
            "scan_api_key": mask(config.SCAN_API_KEY),
            "scan_api_base": config.SCAN_API_BASE,
            "scan_scene": config.SCAN_SCENE,
            "work_dir": config.WORK_DIR,
        }
    }


@router.post("")
async def save_settings(req: dict):
    config.save_config(**req)
    return {"success": True}


@router.post("/fetch-models")
async def fetch_models(req: dict):
    """通过 OpenAI 兼容接口拉取模型列表"""
    api_base = req.get("api_base", "").strip()
    api_key = req.get("api_key", "").strip()
    if not api_base or not api_key:
        raise HTTPException(status_code=400, detail="api_base 和 api_key 不能为空")
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                f"{api_base}/models",
                headers={"Authorization": f"Bearer {api_key}"}
            )
            if resp.status_code == 404:
                resp = await client.get(
                    api_base.rstrip("/") + "/v1/models",
                    headers={"Authorization": f"Bearer {api_key}"}
                )
            if resp.status_code != 200:
                raise HTTPException(status_code=502, detail=f"获取模型列表失败: HTTP {resp.status_code}")
            data = resp.json()
            models = []
            raw = data.get("data", data.get("models", []))
            for m in raw:
                mid = m.get("id", m.get("model", ""))
                if not mid:
                    continue
                # 识图模型：严格匹配视觉/多模态关键词
                is_vision = any(kw in mid.lower() for kw in [
                    "vl-", "vision", "omni",
                    "gpt-4o", "gpt-4-turbo",
                    "gemini-2", "gemini-1.5", "gemini-pro-vision",
                    "glm-4v",
                    "claude-3", "claude-3.5", "claude-3.7",
                ])
                # qwen 系列：只留带 vl 的
                if not is_vision and "qwen" in mid.lower():
                    is_vision = any(kw in mid.lower() for kw in ["vl-", "vl2", "vl3", "vision"])
                if is_vision:
                    models.append({"id": mid, "label": mid})
            if not models:
                models = [{"id": m.get("id", m.get("model", "")), "label": m.get("id", m.get("model", ""))}
                          for m in raw[:30] if m.get("id") or m.get("model")]
            return {"success": True, "data": {"models": models}}
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"获取模型列表失败: {str(e)}")


@router.post("/test-vision")
async def test_vision(req: dict):
    """测试识图模型：用真实图片调一次 API"""
    api_base = req.get("api_base", "").strip()
    api_key = req.get("api_key", "").strip()
    model = req.get("model", "").strip()
    if not api_key or not model:
        raise HTTPException(status_code=400, detail="参数不全")

    test_img = _make_test_png()
    start = time.time()
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            f"{api_base}/chat/completions",
            headers={"Authorization": f"Bearer {api_key}"},
            json={
                "model": model,
                "messages": [{"role": "user", "content": [
                    {"type": "text", "text": "say ok"},
                    {"type": "image_url", "image_url": {"url": test_img}}
                ]}]
            }
        )
    elapsed = round((time.time() - start) * 1000)
    if resp.status_code != 200:
        raise HTTPException(status_code=502, detail=f"连接失败 HTTP {resp.status_code}: {resp.text[:300]}")
    return {"success": True, "data": {"latency_ms": elapsed, "status": "ok"}}


@router.post("/test-agent")
async def test_agent(req: dict):
    """测试 Agent 模型：纯文本调一次 API"""
    api_base = req.get("api_base", "").strip()
    api_key = req.get("api_key", "").strip()
    model = req.get("model", "").strip()
    if not api_key or not model:
        raise HTTPException(status_code=400, detail="参数不全")

    start = time.time()
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            f"{api_base}/chat/completions",
            headers={"Authorization": f"Bearer {api_key}"},
            json={"model": model, "messages": [{"role": "user", "content": "hi"}]}
        )
    elapsed = round((time.time() - start) * 1000)
    if resp.status_code != 200:
        raise HTTPException(status_code=502, detail=f"连接失败 HTTP {resp.status_code}: {resp.text[:300]}")
    return {"success": True, "data": {"latency_ms": elapsed, "status": "ok"}}


@router.get("/pick-dir")
async def pick_dir():
    """打开系统原生目录选择对话框，返回选择的目录路径"""
    try:
        import tkinter as tk
        from tkinter import filedialog
        root = tk.Tk()
        root.withdraw()
        root.attributes('-topmost', True)
        path = filedialog.askdirectory(title="选择文件存放目录")
        root.destroy()
        return {"success": True, "data": {"path": path or ""}}
    except Exception as e:
        return {"success": False, "error": f"无法打开目录选择器: {str(e)}"}


@router.get("/scan-scenes")
async def scan_scenes():
    """扫描王官方场景列表（来自开放平台文档；场景可在设置页自定义输入）"""
    scenes = [
        {"scene": "image-to-excel", "label": "图片转 Excel（表格提取）", "type": "文档转换"},
        {"scene": "typeset", "label": "图片转 Word（排版还原）", "type": "文档转换"},
        {"scene": "word", "label": "图片转 Word", "type": "文档转换"},
        {"scene": "ocr", "label": "通用文字识别（OCR）", "type": "OCR"},
    ]
    return {"success": True, "data": {"scenes": scenes, "current": config.SCAN_SCENE}}


@router.post("/test-scan")
async def test_scan(req: dict):
    """测试扫描王连接并测速：用 1 张最小图片真实调用一次 API（消耗一次识别额度）"""
    api_key = (req.get("api_key") or "").strip() or config.SCAN_API_KEY
    api_base = (req.get("api_base") or "").strip() or config.SCAN_API_BASE
    scene = (req.get("scene") or "").strip() or config.SCAN_SCENE
    if not api_key:
        raise HTTPException(status_code=400, detail="识别 API Key 未配置")

    test_img = _make_test_png()
    old_key, old_base, old_scene = config.SCAN_API_KEY, config.SCAN_API_BASE, config.SCAN_SCENE
    config.SCAN_API_KEY, config.SCAN_API_BASE, config.SCAN_SCENE = api_key, api_base, scene
    start = time.time()
    try:
        resp = await call_quark_excel(test_img)
    finally:
        config.SCAN_API_KEY, config.SCAN_API_BASE, config.SCAN_SCENE = old_key, old_base, old_scene
    elapsed = round((time.time() - start) * 1000)
    if resp.get("success"):
        return {"success": True, "data": {"latency_ms": elapsed, "status": "ok", "message": f"连接正常（场景 {scene}，{elapsed}ms）"}}
    err = resp.get("error") or "未知错误"
    if any(k in err for k in ("Timeout", "Connect", "网络", "DNS")):
        raise HTTPException(status_code=502, detail=f"网络不可达（{elapsed}ms）：{err}")
    # API 已响应但识别失败（测试图不是表格）——说明 Key/地址链路本身是通的
    return {"success": True, "data": {"latency_ms": elapsed, "status": "connected", "message": f"API 已响应（{elapsed}ms），测试图非表格：{err}"}}
