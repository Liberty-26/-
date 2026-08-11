"""
POST /api/recognize — 夸克扫描王 OCR 识别接口
POST /api/recognize/calibrate — 规则校准接口（SSE 流式进度）
"""
import time
import asyncio
import uuid
import base64 as b64
import re
import json
from pathlib import Path
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
import config
from quark import call_quark_excel, parse_receipt
from models import RecognizeRequest, RecognizeBatchRequest, RetryRequest, CalibrateRequest
from calibrate import (
    calibrate_items,
    calibrate_items_progress,
)

router = APIRouter(prefix="/api", tags=["recognize"])

# 批量识别任务表：task_id -> {items: [{index,status,result,error}], done, ok, failed, finished}
_BATCH_TASKS: dict[str, dict] = {}
_BATCH_TASK_MAX = 50          # 最多保留任务数（超限淘汰最旧的已完成任务）
_BATCH_TASK_TTL = 30 * 60     # 已完成任务保留 30 分钟


def _prune_batch_tasks():
    """清理已完成/过期的批量任务，防止桌面端长期运行内存无限增长"""
    now = time.time()
    stale = [
        tid for tid, t in _BATCH_TASKS.items()
        if t.get("finished") and now - t.get("finished_at", 0) > _BATCH_TASK_TTL
    ]
    for tid in stale:
        _BATCH_TASKS.pop(tid, None)
    # 仍超过上限时，淘汰最旧的一批（已完成优先）
    if len(_BATCH_TASKS) > _BATCH_TASK_MAX:
        ordered = sorted(
            _BATCH_TASKS.items(),
            key=lambda kv: (not kv[1].get("finished"), kv[1].get("created_at", 0)),
        )
        for tid, _ in ordered[: len(_BATCH_TASKS) - _BATCH_TASK_MAX]:
            _BATCH_TASKS.pop(tid, None)


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
    # 加随机后缀：同一秒批量上传多张时避免同名覆盖
    filename = f"{safe_no}_{ts}_{uuid.uuid4().hex[:6]}.{ext}"

    upload_dir = Path(config.UPLOAD_DIR)
    upload_dir.mkdir(parents=True, exist_ok=True)
    filepath = upload_dir / filename
    with open(filepath, "wb") as f:
        f.write(img_bytes)

    return ext, filename, img_bytes


async def _recognize_one(image_data_url: str, receipt_no: str = "", date: str = "",
                         progress=None) -> dict:
    """
    单张识别（保存 → 调夸克 image-to-excel → 重试保护 → 结构化解构）。
    失败不抛异常，返回 {"success": False, "error": ...}，供单张/批量共用。

    progress: 可选回调 progress(stage)，stage 语义：
      1 正在提取单号和日期 / 2 识别中 / 3 转译 / 4 规则校准中
    """
    try:
        raw = image_data_url.strip()
        if not raw:
            return {"success": False, "error": "图片数据为空"}
        if raw.startswith("data:"):
            if not re.match(r'data:image/(jpe?g|png|webp);base64,', raw):
                return {"success": False, "error": "请上传 jpg/png 格式"}

        if progress:
            progress(1)  # 正在提取单号和日期（图片已保存，进入识别流程）
        try:
            ext, filename, img_bytes = _decode_and_save_image(raw, receipt_no or "")
            image_path = filename
        except HTTPException as e:
            return {"success": False, "error": e.detail}
        except Exception as e:
            return {"success": False, "error": f"图片保存失败: {str(e)}"}

        clean_b64 = b64.b64encode(img_bytes).decode("ascii")
        mime = "image/png" if ext == "png" else "image/jpeg"
        image_data_url = f"data:{mime};base64,{clean_b64}"

        if progress:
            progress(2)  # 识别中（调用扫描王）
        quark_resp = await call_quark_excel(image_data_url)
        if progress:
            progress(3)  # 转译（xlsx → 结构化明细）
        result = parse_receipt(quark_resp["raw"]) if quark_resp.get("success") else quark_resp

        # 识别不稳定保护：结果为空或全是空行时自动重试一次
        raw_items = result.get("items", []) if result.get("success") else []
        has_content = any(
            str(it.get("name", "")).strip() or str(it.get("spec", "")).strip()
            for it in raw_items
        )
        if len(raw_items) < 3 or not has_content:
            print(f"[recognize] 识别结果异常（{len(raw_items)}行无有效数据），自动重试...")
            quark_resp = await call_quark_excel(image_data_url)
            result = parse_receipt(quark_resp["raw"]) if quark_resp.get("success") else quark_resp

        if not result.get("success"):
            return {"success": False, "error": result.get("error", "识别失败"), "image_path": image_path}

        if progress:
            progress(4)  # 规则校准中
        # 识别后紧跟的纯代码校准：
        # 结构化解构 → 名称/规格拆分 → 品名库对齐 → 单位对齐 → 代码兜底
        # 让入库数据即是"名称/规格分开"的干净结构，AI 审核阶段再做一轮复核
        items = calibrate_items(result.get("items", [])).get("items", [])
        return {
            "success": True,
            "receipt_no": result.get("receipt_no") or receipt_no or "",
            "date": result.get("date") or date or "",
            "date_suspicious": bool(result.get("date_suspicious")) if result.get("date") else False,
            "image_path": image_path,
            "items": items,
            "rec_total": result.get("rec_total"),
            "raw_response": result.get("raw_response", ""),
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


@router.post("/recognize")
async def recognize(req: RecognizeRequest):
    """上传图片 base64，调用夸克扫描王识别手写送货单"""
    if not req.image_base64.strip():
        raise HTTPException(status_code=400, detail="图片数据为空")
    result = await _recognize_one(req.image_base64.strip(), req.receipt_no or "", req.date or "")
    if not result.get("success"):
        raise HTTPException(status_code=500, detail=result.get("error", "识别失败"))
    return {"success": True, "data": result}


@router.post("/recognize/retry")
async def recognize_retry(req: RetryRequest):
    """对已保存的原图重新识别（前端"重试"按钮调用，不重新选图）"""
    if not req.image_path:
        raise HTTPException(status_code=400, detail="缺少原图路径")
    safe_name = Path(req.image_path).name
    img_path = Path(config.UPLOAD_DIR) / safe_name
    if not img_path.exists():
        raise HTTPException(status_code=404, detail="原图不存在，请重新上传")
    img_bytes = img_path.read_bytes()
    data_url = b64.b64encode(img_bytes).decode("ascii")
    result = await _recognize_one(data_url, req.receipt_no or "", req.date or "")
    if not result.get("success"):
        raise HTTPException(status_code=500, detail=result.get("error", "识别失败"))
    return {"success": True, "data": result}


@router.post("/recognize/batch")
async def recognize_batch(req: RecognizeBatchRequest):
    """
    批量识别（任务化）：立即返回 task_id，后台逐张处理，
    前端轮询 GET /api/recognize/batch/{task_id} 获取每张真实进度与结果。
    每张图独立成功/失败，互不影响。
    """
    if not req.images:
        raise HTTPException(status_code=400, detail="images 不能为空")

    task_id = uuid.uuid4().hex[:12]
    task = {
        "task_id": task_id,
        "total": len(req.images),
        "created_at": time.time(),
        "items": [
            {"index": i, "status": "pending", "stage": 0, "result": None, "error": None}
            for i in range(len(req.images))
        ],
        "done": 0,
        "ok": 0,
        "failed": 0,
        "finished": False,
    }
    _BATCH_TASKS[task_id] = task
    _prune_batch_tasks()

    async def run():
        sem = asyncio.Semaphore(config.SCAN_MAX_CONCURRENCY)

        async def one(i: int, r: RecognizeRequest) -> None:
            item = task["items"][i]
            item["status"] = "processing"
            async with sem:
                result = await _recognize_one(
                    r.image_base64.strip(),
                    r.receipt_no or "",
                    r.date or "",
                    progress=lambda s: item.__setitem__("stage", s),
                )
            item["result"] = result
            if result.get("success"):
                item["status"] = "done"
                task["ok"] += 1
            else:
                item["status"] = "failed"
                item["error"] = result.get("error", "识别失败")
                task["failed"] += 1
            task["done"] += 1

        try:
            await asyncio.gather(*[one(i, r) for i, r in enumerate(req.images)])
        finally:
            task["finished"] = True
            task["finished_at"] = time.time()

    asyncio.create_task(run())
    return {"success": True, "data": {"task_id": task_id, "total": len(req.images)}}


@router.get("/recognize/batch/{task_id}")
async def recognize_batch_status(task_id: str):
    """查询批量识别任务的逐张真实状态（pending / processing / done / failed）"""
    task = _BATCH_TASKS.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="识别任务不存在或已过期")
    return {
        "success": True,
        "data": {
            "task_id": task_id,
            "total": task["total"],
            "done": task["done"],
            "ok": task["ok"],
            "failed": task["failed"],
            "finished": bool(task["finished"]),
            "items": [
                {
                    "index": it["index"],
                    "status": it["status"],
                    "stage": it.get("stage", 0),
                    "success": bool(it["result"] and it["result"].get("success")),
                    "error": it["error"],
                    "result": it["result"],
                }
                for it in task["items"]
            ],
        },
    }


@router.post("/recognize/calibrate")
async def calibrate(req: CalibrateRequest):
    """规则校准（SSE 流式）：阶段进度 → 最终结果"""
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
