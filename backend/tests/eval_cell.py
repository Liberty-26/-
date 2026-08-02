# -*- coding: utf-8 -*-
"""新口径评估：位置对应 + 单元格（整行5字段全对才算对）"""
import json, os, sys

OUT = r"G:\SteelDigitize\backend\tests\model_compare"
TESTS = r"G:\SteelDigitize\backend\tests"

def norm(s):
    return str(s or "").strip().replace(" ", "").replace("×", "*").replace("X", "*").lower()

def cell_ok(rec, std):
    """整行5字段全对才返回 True"""
    for fld in ("name", "spec", "unit", "qty", "price"):
        sv, rv = std.get(fld, ""), rec.get(fld, "")
        if fld in ("qty", "price"):
            if abs(float(sv or 0) - float(rv or 0)) >= 0.01:
                return False
        else:
            if norm(str(sv)) != norm(str(rv)):
                return False
    return True

def evaluate(model, results):
    total = hit = 0
    detail = []
    for row in results:
        if row["model"] != model:
            continue
        no = row["receipt_no"]
        with open(os.path.join(TESTS, "std_%s.json" % no), encoding="utf-8") as f:
            std_items = json.load(f)
        rec = row.get("round2", {}).get("items", [])
        # 位置对应：识别第 i 行 vs 标准第 i 行
        n = max(len(std_items), len(rec))
        row_ok = 0
        for i in range(n):
            if i < len(std_items) and i < len(rec):
                ok = cell_ok(rec[i], std_items[i])
                row_ok += ok
                total += 1
                hit += ok
            else:
                total += 1  # 行数不齐，另一侧缺失算错
        detail.append({"img": row["img"].split("_")[2], "no": no,
                       "std_rows": len(std_items), "rec_rows": len(rec), "row_ok": row_ok})
    return hit, total, detail

def main():
    with open(os.path.join(OUT, "u3_summary.json"), encoding="utf-8") as f:
        results = json.load(f)
    for model in ["qwen-vl-plus", "qwen-vl-max", "qwen3-vl-flash"]:
        hit, total, detail = evaluate(model, results)
        print("=" * 60)
        print("[%s] 单元格准确率(位置对应): %d/%d = %.1f%%" % (model, hit, total, hit / total * 100))
        for d in detail:
            print("  图%s: 标准%d行 识别%d行 整行全对%d" % (d["img"], d["std_rows"], d["rec_rows"], d["row_ok"]))
    print("=" * 60)

if __name__ == "__main__":
    main()
