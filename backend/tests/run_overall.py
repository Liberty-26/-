# -*- coding: utf-8 -*-
"""整体准确率：uploads 6 张 × 三模型识别 + DeepSeek 审核"""
import sys, os, time, base64, json, io, asyncio
sys.path.insert(0, 'G:/SteelDigitize/backend')
from PIL import Image

from ocr import call_qwen
from calibrate import structural_decompose, calibrate_items

MODELS = ["qwen-vl-plus", "qwen-vl-max", "qwen3-vl-flash"]
UPLOADS = r"G:\SteelDigitize\backend\uploads"
OUT = r"G:\SteelDigitize\backend\tests\model_compare"

IMGS = [
    "unknown_1785501223.jpg",
    "unknown_1785407181.jpg",
    "unknown_1785402093.jpg",
    "unknown_1785499654.jpg",
    "unknown_1785400400.jpg",
    "unknown_1785505765.jpg",
]

def compress(path, max_w=1280, quality=80):
    img = Image.open(path)
    w, h = img.size
    if w > max_w:
        img = img.resize((max_w, int(h * max_w / w)), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=quality)
    return base64.b64encode(buf.getvalue()).decode()

async def main():
    summary = []
    for model in MODELS:
        for name in IMGS:
            b64 = compress(os.path.join(UPLOADS, name))
            t0 = time.time()
            r = await call_qwen("data:image/jpeg;base64," + b64, model=model)
            t_rec = time.time() - t0
            if not r.get("success"):
                print("[%s] %s 识别失败，重试" % (model, name), flush=True)
                r = await call_qwen("data:image/jpeg;base64," + b64, model=model)
                t_rec = time.time() - t0
                if not r.get("success"):
                    print("[%s] %s 识别失败: %s" % (model, name, r.get("error","?")), flush=True)
                    summary.append({"model": model, "img": name, "error": r.get("error","?")})
                    continue
            items = structural_decompose(r.get("items", []))
            t0 = time.time()
            cal = calibrate_items(items)
            t_cal = time.time() - t0
            row = {
                "model": model, "img": name,
                "round1": {"rows": len(items), "items": items, "sec": round(t_rec, 1)},
                "round2": {"rows": len(cal.get("items", [])), "items": cal.get("items", []), "sec": round(t_cal, 1)},
                "truncated": cal.get("truncated", False),
            }
            summary.append(row)
            with open(os.path.join(OUT, "overall_%s_%s.json" % (model, name.replace(".jpg",""))), "w", encoding="utf-8") as f:
                json.dump(row, f, ensure_ascii=False, indent=1, default=str)
            print("[%s] %s 识别%.1fs+审核%.1fs R2:%d行" % (model, name, t_rec, t_cal, len(cal.get("items",[]))), flush=True)
    with open(os.path.join(OUT, "overall_summary.json"), "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=1, default=str)
    print("完成", flush=True)

asyncio.run(main())
