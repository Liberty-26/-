"""
SteelDigitize Pro — AI 校准模块 v2（结构化解构 + 语义校准双层架构）
结构问题（品名行归属、幽灵行、空 name）→ 代码解构，确定性 100%
语义问题（名称规格拆分、品名归一化、表头识别）→ DeepSeek 模型
规则问题（数值范围、单位白名单）→ 代码兜底
"""
from __future__ import annotations
import json
import re
from openai import OpenAI
import config
from database import get_materials_for_prompt, get_material_unit

# 常见单位白名单（方案文档 v0.4 校准值）
UNIT_WHITELIST = [
    "只", "米", "片", "箱", "桶", "卷", "盒", "支", "组", "套", "包", "瓶",
    "根", "捆", "把", "斤", "平方", "台", "袋", "吨", "块", "条", "张", "对",
    "双", "付",
]

# 数量/单价阈值（真实数据校准）
MAX_QTY = 100000
MAX_PRICE = 10000

# 规格特征（含数字/乘号/直径符号）
SPEC_MARK = re.compile(r'[0-9×xX*#]|DN\d')

# 纯规格特征：去掉所有数字/乘号/#/DN/Φ/单位符号后什么都不剩
PURE_SPEC_RE = re.compile(r'[0-9×xX*#DNdnΦφ.+\-/\s()（）]')

def is_pure_spec(name: str) -> bool:
    """name 全由数字和规格符号组成，不可能是品名"""
    return bool(name) and PURE_SPEC_RE.sub('', name).strip() == ''

# 合计/表尾防护词
HEADER_LIKE = ("合计", "小计", "大写", "收货", "经办", "备注", "金额")

CALIBRATE_PROMPT_TEMPLATE = """你是送货单数据校准器。以下是从手写送货单识别出的数据，请校正：

参考品名库（标准名:别名）：
{materials}

规则：
1. 品名必须归一化为参考库中的标准名（含别名匹配）；库外品名保持原样并标记"未入库"
2. 【名称规格拆分】name 或 spec 中混有名称和规格时拆分：
   - 品名部分用参考品名库匹配（含别名，最长匹配优先）
   - 剩余为规格；拆不出的保持原样并标记 issue "疑似名称规格混写"
3. 含"品种/单位/数量/单价/金额/合计"等表头字样的行标记为表头行
4. 数量、单价必须是有效数字；明显异常（0、负数、超范围）标记 issue
5. unit 为空的输入行：标记 issue "unit: 缺失单位"，unit 保持为空，
   禁止臆造单位、禁止输出无意义的 correction
6. 【纯规格错位】如果某行的 name 只包含数字、乘号、#、DN、Φ 等
   规格符号（如"4×400×400""DN100"），或为不含数字的简短规格描述
   （如"一通""二通"），且品名库中不存在该 name：
   → 将 name 内容移至 spec，品名设为上方最近非空品名（从输入数据的前一行取）
   → 在 corrections 中标注 "spec: 品名列纯规格→已移至规格列"
7. 【形近字修正】如果某行的 name 与品名库中某个标准名相似但不完全相同
   （如"镀锋管"≈"镀锌管"、"密闭套营"≈"密闭套管"），且无其他近似的候选品名：
   → 修正为标准品名，在 corrections 中标注 "name: 旧名→标准名（形近字修正）"
   → 如果有多个近似候选（如"线槽"同时接近"线管"和"线卡"）→ 不修正，只标 issue
   → 此规则仅适用于明显的单字错位/误识别，不得对完全不同的品名做猜测性修改
8. 只输出 JSON，不要其他文字
9. 只输出修正后的 items 结果。禁止输出品名库、禁止重复输入数据、
   禁止任何解释文字，禁止多余内容

输入数据：
{items_json}

输出格式（严格 JSON，不要 markdown）：
{{
  "items": [
    {{
      "name": "标准品名",
      "spec": "规格",
      "unit": "单位",
      "qty": 数量,
      "price": 单价,
      "issues": ["qty: 数量超出范围"],
      "corrections": ["name: 旧品名→新品名"],
      "not_in_library": false
    }}
  ],
  "header_rows": [0, 3]
}}"""


# ---- 文本归一化 ----

def normalize_text(text: str) -> str:
    """全角→半角、×统一、去空格"""
    if not text:
        return ""
    s = text.strip()
    # 全角 → 半角（数字/字母/标点）
    s = s.translate(str.maketrans(
        "０１２３４５６７８９ＡＢＣＤＥＦＧＨＩＪＫＬＭＮＯＰＱＲＳＴＵＶＷＸＹＺａｂｃｄｅｆｇｈｉｊｋｌｍｎｏｐｑｒｓｔｕｖｗｘｙｚ（）：；，。、？！＂＇－",
        "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz():;,.、?!\"'-"
    ))
    # 乘号统一：x/X/*/× → ×
    s = re.sub(r'[xX*]', '×', s)
    # 去掉所有空白（内部空格、全角空格）
    s = re.sub(r'\s+', '', s)
    return s


def _to_float(val) -> float:
    try:
        return float(val)
    except (ValueError, TypeError):
        return 0.0


# ---- 结构化解构：品名行归属（不依赖模型） ----

def is_ghost_row(item: dict) -> bool:
    """幽灵行判断：有品名但无规格且无数量（品名行右侧空白被识别成行）"""
    name = str(item.get("name", "")).strip()
    spec = str(item.get("spec", "")).strip()
    qty = _to_float(item.get("qty", 0))
    price = _to_float(item.get("price", 0))
    return bool(name) and not spec and qty == 0 and price == 0


def structural_decompose(items: list) -> list:
    """
    结构化解构：把模型输出整理成"每行都有品名"的展开结构。
    1. 幽灵行（品名行）→ 变为"品名源"，删除该行，品名向下填充
    2. 空 name 但含规格/数量的行 → 继承上方品名
    3. 返回展开后的行
    """
    result = []
    pending_name = ""      # 待继承的品名
    last_name = ""         # 上方最近的非空品名
    for it in items:
        item = dict(it)
        name = str(item.get("name", "")).strip()
        spec = str(item.get("spec", "")).strip()
        qty = _to_float(item.get("qty", 0))
        price = _to_float(item.get("price", 0))

        # 纯规格检测：name 全是数字/符号 → 移到 spec，name 清空，下方 fill-down 自动继承品名
        if is_pure_spec(name) and not spec:
            item["spec"] = name
            item["name"] = ""
            name = ""

        if is_ghost_row(item):
            # 品名行：作为品名源，自身不输出
            pending_name = name
            continue

        if not name:
            # 空品名行：优先用 pending_name（刚出现的品名行），否则用 last_name
            if pending_name:
                item["name"] = pending_name
            elif last_name:
                item["name"] = last_name
            # 都没有 → 保持空，交给校准/规则标红

        if name or pending_name:
            last_name = item.get("name") or pending_name
        pending_name = ""
        result.append(item)
    return result


# ---- 单位"略写"记号继承（纯代码，静默填充） ----

# 略写记号：形似冒号/分号的两个点，表示"与上一行单位相同"。
# 含全角变体（归一化前可能未转半角）和模型可能输出的"略写"二字。
ABBREV_UNIT_MARKS = {"略写", ":", ";", "∶", "：", "；", "∷"}


def is_abbrev_unit(unit: str) -> bool:
    """unit 是否为略写记号（两个点/冒号/分号形似记号）"""
    return str(unit or "").strip() in ABBREV_UNIT_MARKS


def inherit_abbrev_units(items: list) -> list:
    """
    单位略写继承：unit 为略写记号的行，静默继承上方最近一个非略写单位的单位；
    连续略写逐级传递（第二行略写继承的仍是同一单位）；
    上方无可用单位时置空（交给品名库补全 / "unit: 缺失单位"标记），不硬造。
    静默填充：不加 corrections/issues（用户明确不需要任何提示/标记）。
    """
    last_unit = ""
    for it in items:
        unit = str(it.get("unit", "")).strip()
        if is_abbrev_unit(unit):
            it["unit"] = last_unit
        elif unit:
            last_unit = unit
    return items


# ---- 品名库注入 ----

def _build_materials_block() -> str:
    """品名库 → '标准名:别名' 紧凑排列（分号分隔）"""
    materials = get_materials_for_prompt()
    parts = []
    for m in materials:
        aliases = (m.get("aliases") or "").strip()
        if aliases:
            parts.append(f"{m['name']}:{aliases}")
        else:
            parts.append(m["name"])
    return "; ".join(parts)


# ---- 品名匹配：三级（前缀 → 别名 → 编辑距离） ----

def _edit_distance(a: str, b: str, max_d: int = 1) -> int:
    """中文按字符算编辑距离，超过 max_d 提前返回"""
    if abs(len(a) - len(b)) > max_d:
        return max_d + 1
    dp = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        prev = dp[0]
        dp[0] = i
        for j, cb in enumerate(b, 1):
            cur = dp[j]
            dp[j] = min(dp[j] + 1, dp[j - 1] + 1, prev + (ca != cb))
            prev = cur
    return dp[-1]


def _match_material(text: str, materials: list) -> str | None:
    """三级匹配：标准名前缀 → 别名前缀 → 编辑距离≤1（仅唯一候选）。
    返回标准品名，未命中返回 None"""
    text = text.strip()
    if not text:
        return None
    # 1. 标准名前缀（最长优先）
    for m in sorted(materials, key=lambda x: -len(x["name"])):
        if text.startswith(m["name"]):
            return m["name"]
    # 2. 别名前缀
    for m in sorted(materials, key=lambda x: -max((len(a) for a in x.get("aliases", "").split(",") if a.strip()), default=0)):
        for alias in (m.get("aliases") or "").split(","):
            alias = alias.strip()
            if alias and text.startswith(alias):
                return m["name"]
    # 3. 编辑距离≤1（仅当唯一候选，防误伤）
    cands = [m["name"] for m in materials if _edit_distance(text, m["name"]) <= 1]
    if len(cands) == 1:
        return cands[0]
    return None


# ---- 名称规格拆分 + 兜底继承 ----

def _split_name_spec(items: list, materials: list) -> list:
    """名称/规格混写拆分（品名库匹配，含模糊）"""
    for it in items:
        name = str(it.get("name", "")).strip()
        spec = str(it.get("spec", "")).strip()
        # 场景A：name 含规格特征且 spec 空 → 拆
        if name and not spec and SPEC_MARK.search(name):
            std = _match_material(name, materials)
            if std:
                rest = name[len(std):].strip()
                it["name"] = std
                it["spec"] = rest
                it.setdefault("corrections", []).append(f"name: 拆分→{std}")
            else:
                it.setdefault("issues", []).append("name: 疑似名称规格混写，请人工确认")
        # 场景B：spec 含品名且 name 空 → 抽出
        elif not name and spec:
            std = _match_material(spec, materials)
            if std:
                it["name"] = std
                it["spec"] = spec[len(std):].strip()
                it.setdefault("corrections", []).append(f"spec: 拆分出{std}")
    return items


def _fill_down_names(items: list) -> list:
    """结构层之后仍有空 name 的行，继承上方非空品名（带合计行防护）"""
    last_name = ""
    for it in items:
        name = str(it.get("name", "")).strip()
        spec = str(it.get("spec", "")).strip()
        row_text = name + spec + str(it.get("unit", "")).strip()
        if any(kw in row_text for kw in HEADER_LIKE):
            continue
        if name:
            last_name = name
        elif last_name and spec:
            it["name"] = last_name
            it.setdefault("corrections", []).append(f"name: (继承){last_name}")
    return items


# ---- DeepSeek 校准 ----

def _parse_model_output(content: str) -> dict | None:
    """多层降级解析 DeepSeek 返回 JSON"""
    content = content.strip()
    # 去掉 markdown 代码块
    md = re.search(r'```(?:json)?\s*([\s\S]*?)\s*```', content)
    if md:
        content = md.group(1).strip()
    try:
        return json.loads(content)
    except (json.JSONDecodeError, TypeError):
        pass
    # 提取最外层 {...}
    obj = re.search(r'\{[\s\S]*\}', content)
    if obj:
        try:
            return json.loads(obj.group(0))
        except (json.JSONDecodeError, TypeError):
            pass
    return None


def _normalize_item(item: dict) -> dict:
    """单条 item 归一化 + 字段类型修正"""
    return {
        "name": str(item.get("name", "")).strip(),
        "spec": str(item.get("spec", "")).strip(),
        "unit": str(item.get("unit", "")).strip(),
        "qty": _to_float(item.get("qty", 0)),
        "price": _to_float(item.get("price", 0)),
    }


def _code_fallback(item: dict, materials: list = None) -> dict:
    """
    代码兜底：确定性规则校验。
    返回带 issues / corrections 的完整 item。
    """
    issues = list(item.get("issues") or [])
    corrections = list(item.get("corrections") or [])
    qty = item.get("qty", 0) or 0
    price = item.get("price", 0) or 0
    unit = item.get("unit", "").strip()
    name = item.get("name", "").strip()

    # 规则0：单位缺失 → 品名库补全
    if not unit and name and materials:
        std_name = _match_material(name, materials)
        if std_name:
            unit_from_db = get_material_unit(std_name)
            if unit_from_db:
                item["unit"] = unit_from_db
                unit = unit_from_db
                corrections.append(f"unit: 从品名库补全→{unit_from_db}")
            else:
                issues.append("unit: 缺失单位")
        else:
            issues.append("unit: 缺失单位")
    elif not unit and name:
        issues.append("unit: 缺失单位")

    # 规则1：数量有效
    if not (0 < qty <= MAX_QTY):
        issues.append("qty: 数量超出范围")
    # 规则2：单价有效
    if not (0 < price <= MAX_PRICE):
        issues.append("price: 单价超出范围")
    # 规则3：单位白名单（仅非空时校验）
    if unit and unit not in UNIT_WHITELIST:
        issues.append("unit: 单位不在常见单位集合")
    # 规则4：表头行（代码兜底确认）
    header_kw = ("品种", "单位", "数量", "单价", "金额", "合计")
    if name and any(kw in name for kw in header_kw):
        issues.append("整行: 疑似表头行")
    # 规则5：整行异常（品名+规格+单位全空）
    if not name and not item.get("spec", "").strip():
        issues.append("整行: 品名为空")

    item["issues"] = issues
    item["corrections"] = corrections
    return item


def calibrate_items(items: list, receipt_no: str = "", date: str = "") -> dict:
    """
    校准主流程 v2：
    1. 文本归一化
    2. 结构化解构（品名行归属，纯代码）
    3. DeepSeek 语义校准（品名库 + 拆分）
    4. 代码兜底（数值规则 + 模糊匹配拆分 + 继承补刀）
    """
    # 1. 归一化
    normalized = []
    for it in items:
        norm = {
            "name": normalize_text(str(it.get("name", ""))),
            "spec": normalize_text(str(it.get("spec", ""))),
            "unit": normalize_text(str(it.get("unit", ""))),
            "qty": _to_float(it.get("qty", 0)),
            "price": _to_float(it.get("price", 0)),
        }
        normalized.append(norm)

    # 2. 结构化解构（新：识别后、模型前）
    normalized = structural_decompose(normalized)
    # 单位"略写"继承（模型前：输入中不含略写记号，杜绝模型臆测）
    normalized = inherit_abbrev_units(normalized)

    # 2. DeepSeek 语义校准（prompt v2，不含继承规则）
    api_key = config.AGENT_API_KEY
    if not api_key:
        return {"success": False, "error": "Agent API Key 未配置，无法校准"}

    materials_block = _build_materials_block()
    prompt = CALIBRATE_PROMPT_TEMPLATE.format(
        materials=materials_block,
        items_json=json.dumps(normalized, ensure_ascii=False),
    )

    model_items = None
    model_header_rows = []
    truncated = False
    try:
        client = OpenAI(api_key=api_key, base_url=config.AGENT_API_BASE, timeout=60.0)
        # 动态输出上限：按行数计算，小单收紧防话痨，大单放宽不截断
        max_tokens = min(8000, len(normalized) * 250 + 600)
        resp = client.chat.completions.create(
            model=config.AGENT_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,        # 降随机，治话痨
            max_tokens=max_tokens,
            response_format={"type": "json_object"},   # 内容硬限制：强制输出合法 JSON 对象
            extra_body={"thinking": {"type": "disabled"}},   # 关闭思考链（校准是机械转换，不需要推理）
        )
        content = resp.choices[0].message.content or ""
        # 记录 token
        try:
            from database import record_token_usage
            usage = resp.usage
            if usage:
                record_token_usage("calibrate", config.AGENT_MODEL,
                                   usage.prompt_tokens or 0, usage.completion_tokens or 0,
                                   usage.total_tokens or 0)
                # 截断检测：输出 token 达到上限 → 模型输出大概率残缺
                truncated = usage.completion_tokens >= max_tokens
        except Exception:
            pass
        parsed = _parse_model_output(content)
        if parsed and isinstance(parsed.get("items"), list):
            model_items = parsed["items"]
            model_header_rows = parsed.get("header_rows") or []
    except Exception as e:
        return {"success": False, "error": f"校准调用失败: {str(e)}"}

    # 4. 组装结果（模型结果优先，缺失时用结构化数据）
    #    截断时模型输出大概率残缺 → 降级为归一化 + 代码兜底结果
    materials = get_materials_for_prompt()
    result_items = []
    if model_items and not truncated:
        for i, mit in enumerate(model_items):
            if not isinstance(mit, dict):
                continue
            item = _normalize_item(mit)
            item["issues"] = list(mit.get("issues") or [])
            item["corrections"] = list(mit.get("corrections") or [])
            item["not_in_library"] = bool(mit.get("not_in_library", False))
            # Bug1 修复：模型改品名前必须命中品名库（V型卡→v型卡 是无意义纠正）
            new_name = item.get("name", "").strip()
            old_name = (normalized[i].get("name", "") if i < len(normalized) else "").strip()
            if new_name and old_name and new_name != old_name:
                # 仅当新 name 在品名库（或别名匹配）时接受修正
                hit = _match_material(new_name, materials)
                if not hit:
                    # 未命中品名库 → 回退到旧 name，删除对应 corrections
                    item["name"] = old_name
                    item["corrections"] = [c for c in item.get("corrections", []) if not c.startswith("name:")]
                    item.setdefault("issues", []).append("name: 校准修正未命中品名库，已保留原名")
            result_items.append(item)
    else:
        for nit in normalized:
            item = dict(nit)
            item["issues"] = []
            item["corrections"] = []
            item["not_in_library"] = False
            result_items.append(item)

    # 5. 代码兜底：名称规格拆分 + 继承补刀 + 略写兜底 + 规则校验
    result_items = _split_name_spec(result_items, materials)
    result_items = _fill_down_names(result_items)
    # 单位"略写"兜底（模型输出残留的略写记号，静默继承，"略写"绝不泄漏）
    result_items = inherit_abbrev_units(result_items)
    result_items = [_code_fallback(it, materials) for it in result_items]

    # 表头行（0-based，过滤越界）
    header_rows = [r for r in model_header_rows if isinstance(r, int) and 0 <= r < len(result_items)]

    return {
        "success": True,
        "items": result_items,
        "header_rows": header_rows,
        "truncated": truncated,
    }


def calibrate_items_progress(items: list, receipt_no: str = "", date: str = ""):
    """
    校准主流程 v2 的进度版（生成器）。
    在每个阶段 yield 进度事件，供 SSE 流式传输。
    事件格式：{"step": 1-4, "label": "...", "model": "...", "done": false}
               {"step": 0, "done": true, "result": {...}}
    """
    # 1. 归一化
    yield {"step": 1, "label": "文本归一化", "done": False}
    normalized = []
    for it in items:
        norm = {
            "name": normalize_text(str(it.get("name", ""))),
            "spec": normalize_text(str(it.get("spec", ""))),
            "unit": normalize_text(str(it.get("unit", ""))),
            "qty": _to_float(it.get("qty", 0)),
            "price": _to_float(it.get("price", 0)),
        }
        normalized.append(norm)
    # 单位"略写"继承（模型前：输入中不含略写记号，杜绝模型臆测）
    normalized = inherit_abbrev_units(normalized)
    yield {"step": 1, "label": "文本归一化", "done": True}

    # 2. DeepSeek 语义校准
    yield {"step": 2, "label": "AI语义校准", "done": False, "model": config.AGENT_MODEL}
    api_key = config.AGENT_API_KEY
    if not api_key:
        yield {"step": 0, "done": False, "error": "Agent API Key 未配置，无法校准"}
        return
    materials_block = _build_materials_block()
    prompt = CALIBRATE_PROMPT_TEMPLATE.format(
        materials=materials_block,
        items_json=json.dumps(normalized, ensure_ascii=False),
    )

    model_items = None
    model_header_rows = []
    truncated = False
    try:
        client = OpenAI(api_key=api_key, base_url=config.AGENT_API_BASE, timeout=60.0)
        # 动态输出上限：按行数计算，小单收紧防话痨，大单放宽不截断
        max_tokens = min(8000, len(normalized) * 250 + 600)
        resp = client.chat.completions.create(
            model=config.AGENT_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,        # 降随机，治话痨
            max_tokens=max_tokens,
            response_format={"type": "json_object"},   # 内容硬限制：强制输出合法 JSON 对象
            extra_body={"thinking": {"type": "disabled"}},   # 关闭思考链（校准是机械转换，不需要推理）
        )
        content = resp.choices[0].message.content or ""
        try:
            from database import record_token_usage
            usage = resp.usage
            if usage:
                record_token_usage("calibrate", config.AGENT_MODEL,
                                   usage.prompt_tokens or 0, usage.completion_tokens or 0,
                                   usage.total_tokens or 0)
                # 截断检测：输出 token 达到上限 → 模型输出大概率残缺
                truncated = usage.completion_tokens >= max_tokens
        except Exception:
            pass
        parsed = _parse_model_output(content)
        if parsed and isinstance(parsed.get("items"), list):
            model_items = parsed["items"]
            model_header_rows = parsed.get("header_rows") or []
    except Exception as e:
        yield {"step": 0, "done": False, "error": f"校准调用失败: {str(e)}"}
        return
    yield {"step": 2, "label": "AI语义校准", "done": True, "model": config.AGENT_MODEL}

    # 3. 组装 + 代码兜底
    yield {"step": 3, "label": "代码规则兜底", "done": False}
    materials = get_materials_for_prompt()
    result_items = []
    if model_items and not truncated:
        for i, mit in enumerate(model_items):
            if not isinstance(mit, dict):
                continue
            item = _normalize_item(mit)
            item["issues"] = list(mit.get("issues") or [])
            item["corrections"] = list(mit.get("corrections") or [])
            item["not_in_library"] = bool(mit.get("not_in_library", False))
            new_name = item.get("name", "").strip()
            old_name = (normalized[i].get("name", "") if i < len(normalized) else "").strip()
            if new_name and old_name and new_name != old_name:
                hit = _match_material(new_name, materials)
                if not hit:
                    item["name"] = old_name
                    item["corrections"] = [c for c in item.get("corrections", []) if not c.startswith("name:")]
                    item.setdefault("issues", []).append("name: 校准修正未命中品名库，已保留原名")
            result_items.append(item)
    else:
        for nit in normalized:
            item = dict(nit)
            item["issues"] = []
            item["corrections"] = []
            item["not_in_library"] = False
            result_items.append(item)

    result_items = _split_name_spec(result_items, materials)
    result_items = _fill_down_names(result_items)
    # 单位"略写"兜底（模型输出残留的略写记号，静默继承，"略写"绝不泄漏）
    result_items = inherit_abbrev_units(result_items)
    result_items = [_code_fallback(it, materials) for it in result_items]
    header_rows = [r for r in model_header_rows if isinstance(r, int) and 0 <= r < len(result_items)]
    yield {"step": 3, "label": "代码规则兜底", "done": True}

    # 完成
    yield {
        "step": 0,
        "done": True,
        "result": {
            "items": result_items,
            "header_rows": header_rows,
            "truncated": truncated,
        }
    }
