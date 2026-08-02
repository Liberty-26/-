# -*- coding: utf-8 -*-
"""评估 run_user3.py 结果：对照 std_<单号>.json 标准答案，字段级准确率（多出行不计错）"""
import json, os, sys

OUT = r"G:\SteelDigitize\backend\tests\model_compare"
TESTS = r"G:\SteelDigitize\backend\tests"

def norm_name(s):
    return str(s or "").strip().replace(" ", "")

def norm_spec(s):
    return str(s or "").strip().replace(" ", "").replace("×", "*").replace("X", "*").lower()

def match_row(rec, std):
    if norm_name(rec["name"]) != norm_name(std["name"]):
        return False
    rs, ss = norm_spec(rec.get("spec", "")), norm_spec(std.get("spec", ""))
    if rs and ss and rs != ss:
        return False
    return True

def evaluate(model, results):
    fields = ["name", "spec", "unit", "qty", "price"]
    total = hit = 0
    detail = []
    for row in results:
        if row["model"] != model:
            continue
        no = row["receipt_no"]
        std_path = os.path.join(TESTS, "std_%s.json" % no)
        with open(std_path, encoding="utf-8") as f:
            std_items = json.load(f)
        rec = row.get("round2", {}).get("items", [])
        used = set()
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
                for fld in fields:
                    sv = std.get(fld, "")
                    rv = ri.get(fld, "")
                    if fld in ("qty", "price"):
                        ok = abs(float(sv or 0) - float(rv or 0)) < 0.01
                    else:
                        ok = norm_name(str(sv)) == norm_name(str(rv))
                    total += 1
                    hit += ok
            else:
                for fld in fields:
                    total += 1
        extra = len(rec) - len(used)
        detail.append({"img": row["img"].split("_")[2], "no": no, "std_rows": len(std_items),
                       "rec_rows": len(rec), "matched": len(used), "extra": extra})
    return hit, total, detail

def main():
    with open(os.path.join(OUT, "u3_summary.json"), encoding="utf-8") as f:
        results = json.load(f)
    for model in ["qwen-vl-plus", "qwen-vl-max", "qwen3-vl-flash"]:
        hit, total, detail = evaluate(model, results)
        print("=" * 66)
        print("[%s] 字段级准确率: %d/%d = %.1f%%" % (model, hit, total, hit / total * 100))
        for d in detail:
            print("  图%s(单%s): 标准%d行 识别%d行 匹配%d 多出%d" % (
                d["img"], d["no"], d["std_rows"], d["rec_rows"], d["matched"], d["extra"]))
    print("=" * 66)

if __name__ == "__main__":
    main()
