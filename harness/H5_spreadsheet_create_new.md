---
name: spreadsheet-create-new
description: 创建新的对账单Excel文件——解决Agent找不到文件时卡死的根因。
---

# H5: spreadsheet_create_new

```json
{
  "type": "function",
  "function": {
    "name": "spreadsheet_create_new",
    "description": "创建一个新的空白对账单Excel文件，自动写入表头（序号|单号|日期|品种|规格|单位|数量|单价|金额|合计金额），应用宋体11pt/居中/细线边框格式。如果文件已存在则报错，不会覆盖。",
    "parameters": {
      "type": "object",
      "properties": {
        "filepath": {"type": "string", "description": "Excel文件绝对路径，如 /Users/xxx/Desktop/对账单.xlsx"},
        "sheets": {
          "type": "array",
          "description": "要创建的sheet名称列表",
          "items": {"type": "string"},
          "default": ["水电"]
        }
      },
      "required": ["filepath"]
    }
  }
}
```

同时更新 `find_last_row` 的返回——文件不存在时返回 `{"exists": false}` 而不是报错，Agent 切换去调 `create_new`。

## Orchestration Loop 更新

在步骤4之前插入文件检查：

```
3. DeepSeek 返回 function_call:
   ├─ 调 find_last_row
   │  ├─ 文件存在 → 返回 start_row → 调 write_batch(mode=append)
   │  └─ 文件不存在 → 返回 exists=false → DeepSeek 调 create_new
   │     └─ create_new 成功 → 调 write_batch(mode=new, start_row=2)
   └─ 普通文本/其他工具 → 正常流程
```

## System Prompt 更新

加一条规则：

```
- 如果用户让你写入Excel但文件路径不存在，先调 spreadsheet_create_new 创建文件，再调 spreadsheet_write_batch 写入数据。不要问用户"文件存不存在"，直接尝试 find_last_row，文件不存在时自动创建。
```
