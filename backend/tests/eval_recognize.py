"""
回归测试：跑识别 + 结构化解构 + 校准，输出逐行报告（无对比模式）
用法：python eval_recognize.py [image1.jpg image2.jpg ...]
      不带参数 = 跑 uploads/ 下全部照片
输出：每张照片的 识别原始 items → 结构化解构 items → 校准 items
"""
# -*- coding: utf-8 -*-
import json
import sys
import os
import asyncio
import base64

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ocr import call_qwen
from calibrate import calibrate_items, structural_decompose

UPLOADS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "uploads")


def load_image_b64(path):
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode()


def brief(items):
    """压缩输出：每行 name/spec/unit/qty/price"""
    out = []
    for it in items:
        out.append({
            "name": it.get("name", ""),
            "spec": it.get("spec", ""),
            "unit": it.get("unit", ""),
            "qty": it.get("qty", 0),
            "price": it.get("price", 0),
        })
    return out


async def process_one(path, name):
    print("=" * 60)
    print(f"### {name}")
    img = load_image_b64(path)
    # 1. 识别（prompt v2 + temperature 0.1）
    raw = await call_qwen(f"data:image/jpeg;base64,{img}")
    if not raw.get("success"):
        print("识别失败:", raw.get("error"))
        return
    raw_items = raw.get("items", [])
    print(f"[识别] 单号={raw.get('receipt_no', '')} 日期={raw.get('date', '')} 行数={len(raw_items)}")
    print("  原始:", json.dumps(brief(raw_items), ensure_ascii=False))
    # 2. 结构化解构
    structured = structural_decompose(raw_items)
    print(f"[解构] 行数={len(structured)}")
    print("  解构:", json.dumps(brief(structured), ensure_ascii=False))
    # 3. 校准
    cal = calibrate_items(structured)
    if not cal.get("success"):
        print("校准失败:", cal.get("error"))
        return
    cal_items = cal.get("items", [])
    print(f"[校准] 行数={len(cal_items)} 表头行={cal.get('header_rows', [])}")
    for i, it in enumerate(cal_items):
        flags = []
        if it.get("issues"):
            flags.append("issues=" + ";".join(it["issues"]))
        if it.get("corrections"):
            flags.append("corr=" + ";".join(it["corrections"]))
        if it.get("not_in_library"):
            flags.append("未入库")
        flag_str = ("  [" + ", ".join(flags) + "]") if flags else ""
        print(f"  {i:2d}. {it.get('name',''):<12} {it.get('spec',''):<16} {it.get('unit',''):<4} qty={it.get('qty',0):<8} price={it.get('price',0)}{flag_str}")


async def main():
    args = sys.argv[1:]
    if args:
        files = [a if os.path.isabs(a) else os.path.join(UPLOADS, a) for a in args]
    else:
        files = sorted(
            os.path.join(UPLOADS, f) for f in os.listdir(UPLOADS)
            if f.lower().endswith((".jpg", ".jpeg", ".png")) and not f.startswith(".")
        )
    if not files:
        print("uploads/ 下没有图片")
        return
    for p in files:
        await process_one(p, os.path.basename(p))
    print("=" * 60)
    print("完成。请对照输出为典型照片标注期望结果（tests/cases.json）")


if __name__ == "__main__":
    asyncio.run(main())
