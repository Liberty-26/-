# -*- coding: utf-8 -*-
import json
cases = []

# 0336 - 确认正确，期望=解构输出
c = {"image": "uploads/unknown_1785400336.jpg", "note": "全部正确——定位卡", "expected": [
  {"name":"套管","spec":"4×100","unit":"组","qty":4,"price":520},
  {"name":"套管","spec":"4×150","unit":"组","qty":2,"price":740},
  {"name":"PVC线管","spec":"25","unit":"米","qty":3000,"price":1.6},
  {"name":"PVC直接","spec":"20","unit":"只","qty":12000,"price":0.18},
  {"name":"PVC内插直接","spec":"110","unit":"只","qty":140,"price":3.5},
  {"name":"86方盒","spec":"10公分","unit":"只","qty":300,"price":2.6},
  {"name":"PVC斜三通","spec":"160×75","unit":"只","qty":8,"price":10},
  {"name":"定位卡","spec":"75","unit":"只","qty":2000,"price":1.2},
  {"name":"定位卡","spec":"50","unit":"只","qty":2400,"price":1},
  {"name":"内插直接","spec":"110","unit":"只","qty":140,"price":3.5},
  {"name":"PVC排水管","spec":"75","unit":"米","qty":160,"price":9.62}
 ]}
cases.append(c)
print(json.dumps(cases, ensure_ascii=False, indent=2)[:200])
print("...OK")
