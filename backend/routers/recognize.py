"""
POST /api/recognize — 千问 OCR 识别接口
POST /api/recognize/calibrate — AI 校准接口（SSE 流式进度）
"""
import time
import base64 as b64
import re
import json
from pathlib import Path
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
import config
from ocr import call_qwen
from models import RecognizeRequest, CalibrateRequest
from calibrate import calibrate_items, structural_decompose, calibrate_items_progress

router = APIRouter(prefix="/api", tags=["recognize"])


def _decode_and_save_image(image_base64: str, receipt_no: str = "") -> tuple[str, str, bytes]:
    """
    解码 base64 图片并保存到 uploads/ 目录。
    返回 (扩展名, 文件名, 原始图片字节)
    """
    header_match = re.match(r'data:image/(\w+);base64,(.+)', image_base64)
    if header_match:
        ext = header_match.group(1)
        raw_data = header_match.group(2)
    else:
        ext = "jpeg"
        raw_data = image_base64

    ext = ext.lower()
    if ext == "jpeg":
        ext = "jpg"
    if ext not in ("jpg", "jpeg", "png", "webp"):
        raise HTTPException(status_code=400, detail="不支持的图片格式，仅支持 jpg/png/webp")

    try:
        img_bytes = b64.b64decode(raw_data)
    except Exception:
        raise HTTPException(status_code=400, detail="图片 base64 解码失败")

    ts = int(time.time())
    safe_no = re.sub(r'[^a-zA-Z0-9_-]', '', receipt_no or "unknown")
    filename = f"{safe_no}_{ts}.{ext}"

    upload_dir = Path(config.UPLOAD_DIR)
    upload_dir.mkdir(parents=True, exist_ok=True)
    filepath = upload_dir / filename
    with open(filepath, "wb") as f:
        f.write(img_bytes)

    return ext, filename, img_bytes


@router.post("/recognize")
async def recognize(req: RecognizeRequest):
    """上传图片 base64，调用千问 OCR 识别手写送货单"""
    raw = req.image_base64.strip()
    if not raw:
        raise HTTPException(status_code=400, detail="图片数据为空")

    if raw.startswith("data:"):
        if not re.match(r'data:image/(jpe?g|png|webp);base64,', raw):
            raise HTTPException(status_code=400, detail="请上传 jpg/png 格式")

    # 保存图片到磁盘，同时得到干净的图片字节
    try:
        ext, filename, img_bytes = _decode_and_save_image(raw, req.receipt_no or "")
        image_path = filename
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"图片保存失败: {str(e)}")

    # 从磁盘保存的字节重新编码 base64（避免前端 Canvas 编码兼容性问题）
    clean_b64 = b64.b64encode(img_bytes).decode("ascii")
    mime = "image/png" if ext == "png" else "image/jpeg"
    image_data_url = f"data:{mime};base64,{clean_b64}"

    # 调用千问 OCR（前端传了模型名则优先使用，否则用后端默认）
    result = await call_qwen(image_data_url, model=req.model)

    # 识别不稳定保护：结果为空或全是空行时自动重试一次
    raw_items = result.get("items", []) if result.get("success") else []
    has_content = any(
        str(it.get("name", "")).strip() or str(it.get("spec", "")).strip()
        for it in raw_items
    )
    if len(raw_items) < 3 or not has_content:
        print(f"[recognize] 识别结果异常（{len(raw_items)}行无有效数据），自动重试...")
        result = await call_qwen(image_data_url, model=req.model)

    if not result.get("success"):
        raise HTTPException(status_code=500, detail=result.get("error", "识别失败"))

    # 结构化解构：识别返回前整理"每行都有品名"的展开结构（纯代码，不依赖模型）
    items = structural_decompose(result.get("items", []))

    return {
        "success": True,
        "data": {
            "receipt_no": result.get("receipt_no") or req.receipt_no or "",
            "date": result.get("date") or req.date or "",
            # 日期疑似异常标记：仅当日期来自识别结果时透传（识别不出日期、走前端传入值时无标记）
            "date_suspicious": bool(result.get("date_suspicious")) if result.get("date") else False,
            "image_path": image_path,
            "items": items,
            "raw_response": result.get("raw_response", ""),
        }
    }


@router.post("/recognize/calibrate")
async def calibrate(req: CalibrateRequest):
    """AI 校准（SSE 流式）：阶段进度 → 最终结果"""
    if not req.items:
        raise HTTPException(status_code=400, detail="items 不能为空")

    def event_stream():          # 同步生成器 → Starlette 线程池迭代，不阻塞事件循环
        try:
            for evt in calibrate_items_progress(
                [it.model_dump() for it in req.items],
                req.receipt_no or "",
                req.date or "",
            ):
                yield f"data: {json.dumps(evt, ensure_ascii=False)}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'step': 0, 'done': False, 'error': str(e)}, ensure_ascii=False)}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")
