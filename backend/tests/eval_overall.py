# -*- coding: utf-8 -*-
"""评估：识别结果(overall_summary.json) vs 标准答案(cases_from_xlsx.json)，字段级准确率"""
import json, sys, os

OUT = r"G:\SteelDigitize\backend\tests\model_compare"

def norm_name(s):
    return str(s or "").strip().replace(" ", "")

def norm_spec(s):
    return str(s or "").strip().replace(" ", "").replace("×", "*").replace("X", "*").lower()

def norm_unit(s):
    return str(s or "").strip()

def match_row(rec, std):
    """宽松匹配：品名相等（或包含），规格相等或一方为空"""
    if norm_name(rec["name"]) != norm_name(std["name"]):
        return False
    rs, ss = norm_spec(rec.get("spec", "")), norm_spec(std.get("spec", ""))
    if rs and ss and rs != ss:
        return False
    return True

def evaluate(model, results):
    with open(os.path.join(os.path.dirname(OUT), "cases_from_xlsx.json"), encoding="utf-8") as f:
        cases = json.load(f)
    fields = ["name", "spec", "unit", "qty", "price"]
    total = hit = 0
    detail = []
    for img, case in cases.items():
        rec_items = [r for r in results if r["img"] == img and r["model"] == model]
        if not rec_items:
            continue
        rec = rec_items[0].get("round2", {}).get("items", [])
        std_items = case["items"]
        # 匹配：每行标准找对应识别行
        used = set()
        row_details = []
        for std in std_items:
            best = None
            for i, ri in enumerate(rec):
                if i in used:
                    continue
                if match_row(ri, std):
                    best = (i, ri)
                    break
            if best:
                used.add(best[0])
                ri = best[1]
                row_hit = []
                for fld in fields:
                    sv = std.get(fld, "")
                    rv = ri.get(fld, "")
                    if fld in ("qty", "price"):
                        ok = abs(float(sv or 0) - float(rv or 0)) < 0.01
                    else:
                        ok = norm_name(str(sv)) == norm_name(str(rv))
                    total += 1
                    hit += ok
                    row_hit.append((fld, sv, rv, ok))
                row_details.append((std["name"], row_hit))
            else:
                # 标准行没找到匹配 = 漏识别，5 字段全错
                for fld in fields:
                    total += 1
                row_details.append((std["name"], [("漏识别", std.get("name",""), "—", False)]))
        # 识别多出的行 = 不在 xlsx 中（不计错，仅报告）
        extra = len(rec) - len(used)
        detail.append({"img": img, "rows": row_details, "extra_rows": extra})
    return hit, total, detail

def main():
    with open(os.path.join(OUT, "overall_summary.json"), encoding="utf-8") as f:
        results = json.load(f)
    for model in ["qwen-vl-plus", "qwen-vl-max", "qwen3-vl-flash"]:
        hit, total, detail = evaluate(model, results)
        print("=" * 60)
        print("[%s] 字段级准确率: %d/%d = %.1f%%" % (model, hit, total, hit / total * 100))
        for d in detail:
            if d["extra_rows"]:
                print("  %s: 多识别 %d 行" % (d["img"][-14:], d["extra_rows"]))
    print("=" * 60)

if __name__ == "__main__":
    main()
