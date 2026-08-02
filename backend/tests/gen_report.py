# -*- coding: utf-8 -*-
"""读取测试结果，生成三模型对比报告"""
import json, os, sys

OUT_DIR = r"G:\SteelDigitize\backend\tests\model_compare"
summary_path = os.path.join(OUT_DIR, "summary.json")

with open(summary_path, encoding="utf-8") as f:
    summary = json.load(f)

MODELS = ["qwen-vl-plus", "qwen-vl-max", "qwen3-vl-flash"]
imgs = ["微信图片_20260731134045_132_6.jpg", "微信图片_20260731134110_141_6.jpg", "微信图片_20260731134129_148_6.jpg"]

def fmt_item(it):
    return "%s %s %s %s %s" % (it.get("name", ""), it.get("spec", ""), it.get("unit", ""), it.get("qty", ""), it.get("price", ""))

report = ["# 三模型两轮对比报告\n"]
report.append("数据集: C:\\Users\\DIY\\Pictures\\数据集 (132/141/148)\n")
report.append("第一轮 = 识别(系统真实prompt)+结构化解构 | 第二轮 = 第一轮 + AI审核(同模型,品名库)\n")

for img in imgs:
    report.append("\n## %s\n" % img.replace("微信图片_", ""))
    rows = {}
    for m in MODELS:
        for r in summary:
            if r["img"] == img and r["model"] == m:
                rows[m] = r
                break
    for round_name, key in [("第一轮 识别+解构", "round1"), ("第二轮 +AI审核", "round2")]:
        report.append("\n### %s\n" % round_name)
        report.append("| 行 | plus | max | flash |")
        report.append("|---|---|---|---|")
        max_rows = max(len(rows[m].get(key, {}).get("items", [])) for m in MODELS if rows.get(m))
        for i in range(max_rows):
            cells = []
            for m in MODELS:
                items = rows[m].get(key, {}).get("items", []) if rows.get(m) else []
                if i < len(items):
                    cells.append(fmt_item(items[i]))
                else:
                    cells.append("—")
            report.append("| %d | %s | %s | %s |" % (i + 1, cells[0], cells[1], cells[2]))
    # 耗时
    report.append("\n耗时: " + " | ".join(
        "%s 识别%.1fs+校准%.1fs" % (m, rows[m].get("round1", {}).get("sec", 0), rows[m].get("round2", {}).get("sec", 0)) for m in MODELS if rows.get(m)
    ))

report_path = os.path.join(OUT_DIR, "对比报告.md")
with open(report_path, "w", encoding="utf-8") as f:
    f.write("\n".join(report))
print("报告已生成:", report_path)
print("\n".join(report[:20]))
