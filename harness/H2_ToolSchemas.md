---
name: tool-schemas
description: DeepSeek function calling 工具定义——5个工具的 JSON Schema。
---

# Tool Schemas（DeepSeek function calling 格式）

## 工具1: db_lookup_receipt
```json
{
  "type": "function",
  "function": {
    "name": "db_lookup_receipt",
    "description": "从SQLite数据库查询单据。可根据单号、日期或状态查询。不指定条件时返回最近5条。",
    "parameters": {
      "type": "object",
      "properties": {
        "receipt_no": {"type": "string", "description": "单号，支持模糊匹配，如0000745"},
        "date": {"type": "string", "description": "日期，ISO格式如2025-08-16"},
        "status": {"type": "string", "enum": ["pending", "verified", "all"], "description": "状态筛选，默认all"},
        "limit": {"type": "integer", "description": "返回条数，默认5"}
      },
      "required": []
    }
  }
}
```

## 工具2: db_get_receipt_items
```json
{
  "type": "function",
  "function": {
    "name": "db_get_receipt_items",
    "description": "根据单据ID获取完整的物品明细列表。",
    "parameters": {
      "type": "object",
      "properties": {
        "receipt_id": {"type": "integer", "description": "单据ID"}
      },
      "required": ["receipt_id"]
    }
  }
}
```

## 工具3: spreadsheet_find_last_row
```json
{
  "type": "function",
  "function": {
    "name": "spreadsheet_find_last_row",
    "description": "找到对账单Excel指定sheet中最后一行数据的位置，返回建议写入起始行。",
    "parameters": {
      "type": "object",
      "properties": {
        "filepath": {"type": "string", "description": "Excel文件绝对路径"},
        "sheet": {"type": "string", "description": "sheet名称。用户说过的直接用，没说过的使用上下文中的名称。"}
      },
      "required": ["filepath", "sheet"]
    }
  }
}
```

## 工具4: spreadsheet_write_batch
```json
{
  "type": "function",
  "function": {
    "name": "spreadsheet_write_batch",
    "description": "将一个单据的所有物品写入对账单Excel。自动处理合并单元格、公式、格式。新建模式会先写表头再填数据。",
    "parameters": {
      "type": "object",
      "properties": {
        "filepath": {"type": "string", "description": "Excel文件绝对路径"},
        "sheet": {"type": "string", "description": "sheet名称。用户说过的直接用，没说过的使用上下文中的名称。"},
        "mode": {"type": "string", "enum": ["new", "append"], "description": "新建还是续写。新建会创建表头，续写追加到现有数据下方"},
        "start_row": {"type": "integer", "description": "数据起始行号。append模式由find_last_row返回；new模式固定为2（第1行是表头）"},
        "seq": {"type": "integer", "description": "序号"},
        "receipt_no": {"type": "string", "description": "单号"},
        "date": {"type": "string", "description": "日期，ISO格式如2025-08-16"},
        "items": {
          "type": "array",
          "description": "物品列表。name为空表示与上一行同品种，写入时自动合并D列",
          "items": {
            "type": "object",
            "properties": {
              "name": {"type": "string", "description": "品名，可与上一行相同则留空"},
              "spec": {"type": "string"},
              "unit": {"type": "string"},
              "qty": {"type": "number"},
              "price": {"type": "number"}
            },
            "required": ["spec", "unit", "qty", "price"]
          }
        }
      },
      "required": ["filepath", "sheet", "mode", "seq", "receipt_no", "date", "items"]
    }
  }
}
```

## 工具5: spreadsheet_verify
```json
{
  "type": "function",
  "function": {
    "name": "spreadsheet_verify",
    "description": "验证刚写入Excel的数据是否正确。写入完成后必须调用。",
    "parameters": {
      "type": "object",
      "properties": {
        "filepath": {"type": "string", "description": "Excel文件绝对路径"},
        "sheet": {"type": "string", "description": "sheet名称。用户说过的直接用，没说过的使用上下文中的名称。"},
        "start_row": {"type": "integer", "description": "写入起始行"},
        "end_row": {"type": "integer", "description": "写入结束行"}
      },
      "required": ["filepath", "sheet", "start_row", "end_row"]
    }
  }
}
```
