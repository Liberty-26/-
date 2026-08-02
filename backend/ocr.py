"""
SteelDigitize Pro — 千问 OCR 封装
调用阿里云 DashScope 千问 VL 模型识别手写送货单。
"""
from __future__ import annotations
import json
import re
import httpx
from datetime import date
import config
from calibrate import inherit_abbrev_units

RECOGNITION_PROMPT = """你是一张建材五金送货单的识别器。单据上只会出现以下建筑材料：

管材类：镀锌管、PE管、PVC管、JDG线管、排水管、给水管
套管类：密闭套管、防水套管、A型柔性套管、预埋套筒
弯头/接头/三通类：弯头、45度弯头、三通、斜三通、顺水三通、直接、内插直接、大小头
盒箱类：86方盒、八角盒、过路盒、配电箱、弱电箱
螺丝/螺栓类：螺丝、螺帽、螺杆、膨胀螺丝、法兰螺丝
卡/箍类：U型卡、墙卡、管卡、卡箍、沟槽卡箍
钢材类：圆钢、槽钢、角钢、扁钢、钢板、钢筋网片
法兰/阀门类：法兰、止回阀、闸阀、角阀、铜球阀
其他：地漏、消防箱、消火栓、扎丝、胶带、切割片、钻头、焊条、油漆

【品名特征】
- 品名是2-5个汉字的名词短语，如"镀锌管""密闭套管""八角灯头盒"
- 品名不可能只包含数字和符号（如"4×400""DN100""8#"一定是规格，不是品名）
- 品名可能包含字母前缀：JDG线管、PVC弯头、PE管、KBG直接、HDPE雨水管、LEB等电位

【规格特征】
- 规格包含数字、×、#、DN、Φ、mm等符号：如"150×29""DN100""8#""4×40"
- 规格也可能是不含数字的简短描述：如"一通""二通"（管件通径规格）

【常见单位】
根、米、套、个、只、片、箱、桶、卷、盒、支、组、包、瓶、把、斤、吨、双、付、台、袋、块、条、张、对

【版式示例1：品名单独一行，下方是该品名的规格行】
┌─────────┬─────────┬────┬────┬─────┐
│ 密闭套管 │         │    │    │     │   ← 品名行（右侧全空）
│          │ 150×29  │ 套 │ 2  │ 76  │   ← 规格行
│          │ 150×60  │ 套 │ 2  │ 114 │   ← 规格行
└─────────┴─────────┴────┴────┴─────┘
正确输出：
items = [
  {"name":"密闭套管","spec":"150×29","unit":"套","qty":2,"price":76},
  {"name":"密闭套管","spec":"150×60","unit":"套","qty":2,"price":114}
]

【版式示例2：名称和规格混写在一列】
"镀锌管 DN100"      → {"name":"镀锌管","spec":"DN100"}
"弯头 6#"           → {"name":"弯头","spec":"6#"}
"热镀锌扁钢 4×40"   → {"name":"热镀锌扁钢","spec":"4×40"}
"A型柔性套管300*300" → {"name":"A型柔性套管","spec":"300*300"}

【版式示例3：规格误放在品名列】
如果品名列出现纯数字/符号内容（如"4*400*400""DN100""150×29"），说明位置错位：
→ 该内容应放入 spec 字段，name 留空（后续处理会自动从上方继承品名）

【规则】
1. 品名单独占一行时，把品名填写到下方每一行规格的 name，逐行填写，不允许任何一行 name 为空；品名行本身不输出
2. 遇到"合计/小计/大写金额/收货/经办/备注"字样，不要输出为物品行
3. 识别不出的字段用空字符串，不要填0；数量和单价必须是数字，必须从图片中准确读取
4. 品名列只放品名，不要把规格（含数字/×/#的内容）放进 name
5. 单位列遇形似冒号/分号的两个点记号（∶ ； ： 等，表示"与上一行单位相同"）时，
   unit 必须输出"略写"两个字，严禁臆测成"个"或其他任何正常单位
6. date 字段：年份优先按 202x 理解（当前 2026 年），禁止识别成 201x 等早期年代
7. 只输出JSON，不要其他文字

输出JSON格式：
{
  "receipt_no": "单号，如0000774，识别不出留空",
  "date": "日期，如2025.6.20，识别不出留空",
  "items": [{"name":"品名","spec":"规格","unit":"单位","qty":数量,"price":单价}]
}"""


async def call_qwen(image_base64: str, model: str = None, api_key: str = None) -> dict:
    """
    调用千问 VL 模型识别手写送货单。

    Args:
        image_base64: 图片 base64 编码（不含 data:image 前缀亦可）
        model: 模型名，默认 qwen-vl-plus
        api_key: API Key，默认从配置读取

    Returns:
        {"success": True, "items": [...], "raw_response": "..."}
        或 {"success": False, "error": "..."}
    """
    model = model or config.VISION_MODEL
    api_key = api_key or config.VISION_API_KEY

    if not api_key:
        return {"success": False, "error": "识图 API Key 未配置"}

    # 确保有 data:image 前缀
    if not image_base64.startswith("data:"):
        image_base64 = f"data:image/jpeg;base64,{image_base64}"

    payload = {
        "model": model,
        "temperature": 0.1,  # 识别任务确定性优先，降低随机输出
        "messages": [{
            "role": "user",
            "content": [
                {"type": "text", "text": RECOGNITION_PROMPT},
                {"type": "image_url", "image_url": {"url": image_base64}}
            ]
        }]
    }

    async with httpx.AsyncClient(timeout=60.0) as client:
        try:
            resp = await client.post(
                f"{config.VISION_API_BASE}/chat/completions",
                headers={"Authorization": f"Bearer {api_key}"},
                json=payload
            )
            # 非 200 时输出响应体方便排查
            if resp.status_code != 200:
                body = resp.text[:500]
                return {"success": False, "error": f"千问 API 调用失败: HTTP {resp.status_code} — {body}"}
            result = resp.json()
            # 记录 token 消耗
            _record_vision_tokens(result, model)
        except httpx.TimeoutException:
            return {"success": False, "error": "识别超时，请重试"}
        except Exception as e:
            return {"success": False, "error": f"千问 API 调用失败: {str(e)}"}

    # 提取 content
    try:
        content = result["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        return {"success": False, "error": "千问返回格式异常", "raw_response": json.dumps(result, ensure_ascii=False)}

    # 解析 JSON（兼容对象格式和旧数组格式）
    parsed = _parse_result(content)
    if parsed is None:
        return {"success": False, "error": "千问返回解析失败，请重试", "raw_response": content}

    # 单位"略写"继承（识别返回前：略写记号静默填充为上方单位，"略写"不泄漏到前端）
    items = inherit_abbrev_units(parsed.get("items", []))
    date_str, date_suspicious = normalize_date(parsed.get("date", ""))

    return {
        "success": True,
        "receipt_no": parsed.get("receipt_no", ""),
        "date": date_str,
        "date_suspicious": date_suspicious,
        "items": items,
        "raw_response": content,
    }


def _record_vision_tokens(result: dict, model: str):
    """从千问 API 响应中提取 token 用量并记录"""
    try:
        usage = result.get("usage", {})
        if usage:
            from database import record_token_usage
            record_token_usage(
                source="vision",
                model=model,
                prompt_tokens=usage.get("prompt_tokens", 0),
                completion_tokens=usage.get("completion_tokens", 0),
                total_tokens=usage.get("total_tokens", 0),
            )
    except Exception:
        pass


def _parse_result(content: str) -> dict | None:
    """
    从千问返回文本中提取 JSON。兼容两种格式：
    1. 对象格式：{"receipt_no":"...","date":"...","items":[...]}
    2. 旧数组格式：[{...}]（receipt_no/date 置空）
    多层降级：直接 json.loads → markdown 代码块 → 正则提取
    """
    content = content.strip()

    def extract() -> dict | None:
        # 对象格式
        try:
            data = json.loads(content)
        except (json.JSONDecodeError, TypeError):
            return None
        if isinstance(data, dict):
            if "items" in data and isinstance(data["items"], list):
                return {
                    "receipt_no": str(data.get("receipt_no", "")).strip(),
                    "date": str(data.get("date", "")).strip(),
                    "items": _normalize_items(data["items"]),
                }
            return None
        if isinstance(data, list):
            # 旧数组格式
            return {"receipt_no": "", "date": "", "items": _normalize_items(data)}
        return None

    r = extract()
    if r is not None:
        return r

    # markdown 代码块
    md_match = re.search(r'```(?:json)?\s*([\s\S]*?)\s*```', content)
    if md_match:
        content2 = md_match.group(1).strip()
        try:
            data = json.loads(content2)
            if isinstance(data, dict) and "items" in data and isinstance(data["items"], list):
                return {
                    "receipt_no": str(data.get("receipt_no", "")).strip(),
                    "date": str(data.get("date", "")).strip(),
                    "items": _normalize_items(data["items"]),
                }
            if isinstance(data, list):
                return {"receipt_no": "", "date": "", "items": _normalize_items(data)}
        except (json.JSONDecodeError, TypeError):
            pass

    # 正则提取最外层对象或数组
    obj_match = re.search(r'\{[\s\S]*\}', content)
    if obj_match:
        try:
            data = json.loads(obj_match.group(0))
            if isinstance(data, dict) and "items" in data and isinstance(data["items"], list):
                return {
                    "receipt_no": str(data.get("receipt_no", "")).strip(),
                    "date": str(data.get("date", "")).strip(),
                    "items": _normalize_items(data["items"]),
                }
        except (json.JSONDecodeError, TypeError):
            pass
    arr_match = re.search(r'\[[\s\S]*\]', content)
    if arr_match:
        try:
            data = json.loads(arr_match.group(0))
            if isinstance(data, list):
                return {"receipt_no": "", "date": "", "items": _normalize_items(data)}
        except (json.JSONDecodeError, TypeError):
            pass

    return None


def normalize_date(raw: str):
    """
    解析手写日期，返回 (date_str, suspicious)。
    - '2025.6.20'/'2025年6月20日'/'2025/6/20' → '2025-06-20'
    - 两位年份（如 '16.8.2'）→ 一律补 20xx（→ '2016-08-02'，交由人工核对）
    - 四位年份与当前年份相差 5 年以上（含未来年份）→ suspicious=True，不自动改
    - 解析失败 → ('', False)
    """
    if not raw:
        return "", False
    m = re.search(r'(\d{4}|\d{1,2})[年.\-/](\d{1,2})[月.\-/](\d{1,2})', str(raw))
    if not m:
        return "", False
    y_raw, mo, d = m.groups()
    year = 2000 + int(y_raw) if len(y_raw) == 2 else int(y_raw)
    date_str = f"{year}-{int(mo):02d}-{int(d):02d}"
    suspicious = abs(year - date.today().year) > 5
    return date_str, suspicious


def _normalize_items(items: list) -> list:
    """标准化 items 字段：确保所有字段存在且类型正确"""
    result = []
    for item in items:
        if not isinstance(item, dict):
            continue
        normalized = {
            "name": str(item.get("name", "")).strip(),
            "spec": str(item.get("spec", "")).strip(),
            "unit": str(item.get("unit", "")).strip(),
            "qty": _to_float(item.get("qty", 0)),
            "price": _to_float(item.get("price", 0)),
        }
        result.append(normalized)
    return result


def _to_float(val) -> float:
    """安全转 float"""
    try:
        return float(val)
    except (ValueError, TypeError):
        return 0.0
