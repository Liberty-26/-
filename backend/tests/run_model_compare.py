# -*- coding: utf-8 -*-
"""三模型两轮对比测试：识别+解构（第一轮） vs 识别+解构+AI审核（第二轮）"""
import sys, os, time, base64, json, io, glob
sys.path.insert(0, 'G:/SteelDigitize/backend')
import config
from PIL import Image
from openai import OpenAI

from ocr import call_qwen
from calibrate import (
    structural_decompose, _build_materials_block, CALIBRATE_PROMPT_TEMPLATE,
    _parse_model_output, _normalize_item, _match_material, _split_name_spec,
    _fill_down_names, _code_fallback,
)
from database import get_materials_for_prompt

MODELS = ["qwen-vl-plus", "qwen-vl-max", "qwen3-vl-flash"]
DATA_DIR = r"C:\Users\DIY\Pictures\数据集"
OUT_DIR = r"G:\SteelDigitize\backend\tests\model_compare"
os.makedirs(OUT_DIR, exist_ok=True)

def compress(path, max_w=1280, quality=80):
    """模拟前端压缩"""
    img = Image.open(path)
    w, h = img.size
    if w > max_w:
        img = img.resize((max_w, int(h * max_w / w)), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=quality)
    return base64.b64encode(buf.getvalue()).decode(), img.size

def calibrate_with(items, model):
    """AI审核（model 参数化，千问版：不加 thinking 参数）"""
    materials_block = _build_materials_block()
    prompt = CALIBRATE_PROMPT_TEMPLATE.format(
        materials=materials_block, items_json=json.dumps(items, ensure_ascii=False))
    max_tokens = min(8000, len(items) * 250 + 600)
    client = OpenAI(api_key=config.VISION_API_KEY, base_url=config.VISION_API_BASE, timeout=150.0)
    kwargs = dict(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.1,
        max_tokens=max_tokens,
        response_format={"type": "json_object"},
    )
    resp = client.chat.completions.create(**kwargs)
    content = resp.choices[0].message.content or ""
    parsed = _parse_model_output(content)
    if not parsed or not isinstance(parsed.get("items"), list):
        return None, content, resp.usage.completion_tokens if resp.usage else 0
    materials = get_materials_for_prompt()
    result = []
    for i, mit in enumerate(parsed["items"]):
        item = _normalize_item(mit)
        item["issues"] = list(mit.get("issues") or [])
        item["corrections"] = list(mit.get("corrections") or [])
        item["not_in_library"] = bool(mit.get("not_in_library", False))
        new_name = item.get("name", "").strip()
        old_name = items[i].get("name", "").strip() if i < len(items) else ""
        if new_name and old_name and new_name != old_name:
            hit = _match_material(new_name, materials)
            if not hit:
                item["name"] = old_name
                item["corrections"] = [c for c in item.get("corrections", []) if not c.startswith("name:")]
                item.setdefault("issues", []).append("name: 校准修正未命中品名库，已保留原名")
        result.append(item)
    result = _split_name_spec(result, materials)
    result = _fill_down_names(result)
    result = [_code_fallback(it) for it in result]
    return result, content, resp.usage.completion_tokens if resp.usage else 0

def main():
    all_imgs = sorted(glob.glob(os.path.join(DATA_DIR, "*.jpg")))
    # 抽 3 张：首/中/尾（两轮测试都用这三张）
    idx = [0, len(all_imgs) // 2, len(all_imgs) - 2]
    imgs = [all_imgs[i] for i in idx]
    print("抽选 3 张:", [os.path.basename(p) for p in imgs], flush=True)

    async def run():
        summary = []
        for model in MODELS:
            for img_path in imgs:
                name = os.path.basename(img_path)
                row = {"model": model, "img": name}
                b64, size = compress(img_path)
                # 第一轮：识别 + 解构（失败自动重试，最多 3 次）
                t_rec = 0
                items = None
                last_err = ""
                for attempt in range(1, 4):
                    t0 = time.time()
                    result = await call_qwen("data:image/jpeg;base64," + b64, model=model)
                    t_rec += time.time() - t0
                    if result.get("success") and result.get("items"):
                        items = structural_decompose(result.get("items", []))
                        break
                    last_err = result.get("error", "未知错误")[:100]
                    print("[%s] %s 识别第%d次失败: %s" % (model, name, attempt, last_err), flush=True)
                if items is None:
                    # 3 次全失败 → 程序暂停，汇报用户
                    print("[FATAL] %s %s 识别失败3次，最后错误: %s" % (model, name, last_err), flush=True)
                    print("[FATAL] 程序暂停，等待人工处理", flush=True)
                    sys.exit(2)
                row["round1"] = {"rows": len(items), "items": items, "sec": round(t_rec, 1)}
                # 第二轮：校准（同模型）
                t_cal = 0
                cal_items = None
                try:
                    t0 = time.time()
                    cal_items, raw, comp_tokens = calibrate_with(items, model)
                    t_cal = time.time() - t0
                    if cal_items is None:
                        row["round2_error"] = "校准解析失败: " + raw[:80]
                    else:
                        row["round2"] = {"rows": len(cal_items), "items": cal_items, "sec": round(t_cal, 1), "completion_tokens": comp_tokens}
                except Exception as e:
                    row["round2_error"] = str(e)[:100]
                print("[%s] %s 完成 识别%.1fs+校准%.1fs R1:%d行 R2:%d行" % (
                    model, name, t_rec, t_cal,
                    len(items),
                    len(cal_items) if cal_items else 0), flush=True)
                summary.append(row)
                with open(os.path.join(OUT_DIR, "%s_%s.json" % (model, name)), "w", encoding="utf-8") as f:
                    json.dump(row, f, ensure_ascii=False, indent=1, default=str)
        with open(os.path.join(OUT_DIR, "summary.json"), "w", encoding="utf-8") as f:
            json.dump(summary, f, ensure_ascii=False, indent=1, default=str)
        print("全部完成，结果在 %s" % OUT_DIR, flush=True)

    import asyncio
    asyncio.run(run())

if __name__ == "__main__":
    main()
