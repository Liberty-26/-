"""
SteelDigitize Pro — AI 校准模块 v2（结构化解构 + 语义校准双层架构）
结构问题（品名行归属、幽灵行、空 name）→ 代码解构，确定性 100%
语义问题（名称规格拆分、品名归一化、表头识别）→ 纯代码品名库对齐
规则问题（数值范围、单位白名单）→ 代码兜底
"""
from __future__ import annotations
import json
import re
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

# 规格特征（含数字/乘号/除号/直径符号）
SPEC_MARK = re.compile(r'[0-9×xX*÷#]|DN\d')

# 纯规格特征：去掉所有数字/乘除号/#/DN/Φ/单位符号后什么都不剩
PURE_SPEC_RE = re.compile(r'[0-9×xX*÷#DNdnΦφ.+\-/\s()（）]')

# 规格行可带的量词/单位字（"6,5米×12支"→去掉数字符号后剩"米支"也算规格行）
# 注意避开品名词：如"86拉伸盒"的"盒"虽在列表，但整体仍剩"拉伸"等字，不会被误判
SPEC_LIKE_UNIT_CHARS = "米支根捆卷盒组套只个片桶包瓶袋块条张对双平方寸角孔号口"
SPEC_LIKE_STRIP_RE = re.compile(
    r'[0-9×xX*÷#DNdnΦφ.+\-/\s()（）,，、]|[' + SPEC_LIKE_UNIT_CHARS + r']'
)

# 汉字规格穷举（用户确认 2026-08-11）："一通/二通/三通/对通"这类词出现在
# 名称栏 = 规格误写（与数字规格同理），移入规格列并继承上方品名。
# 当前用模式匹配覆盖 一~十/对 + 通 的组合，后续遇到新词直接补进字符集。
HANZI_SPEC_RE = re.compile(r'^[一二三四五六七八九十对]{1,2}通$')


def is_pure_spec(name: str) -> bool:
    """name 全由数字和规格符号组成，不可能是品名"""
    return bool(name) and PURE_SPEC_RE.sub('', name).strip() == ''


def is_spec_like(name: str) -> bool:
    """规格行检测：name 基本由数字/规格符号 + 少量单位字组成（如 "6,5米×12支"、"3.2米"）。
    这是原版设计"纯规格错位"规则的纯代码实现：此类行视为规格而不是品名，
    移到规格列后由结构化解构继承上方最近品名。
    约束：必须含数字或乘号，避免误判纯汉字行。
    """
    if not name:
        return False
    if not re.search(r'[0-9×]', name):
        return False
    return SPEC_LIKE_STRIP_RE.sub('', name).strip() == ''

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

        # 纯规格检测（原版"纯规格错位"规则）：name 是纯数字规格，或数字+单位字规格
        # （如 "6,5米×12支"、"3.2米"）→ 并入 spec，name 清空，由下方继承品名
        if is_pure_spec(name) or is_spec_like(name) or HANZI_SPEC_RE.match(name):
            item["spec"] = (name + spec) if spec else name
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
# 分层定位（映射对 = materials.aliases，即「已确认错误名」，概念与形近词统一）：
#   L1 标准名前缀：识别文本以标准名开头（可带规格尾巴）
#   L2 错误名前缀（映射对）：以已确认错误名开头 → 映射到标准名。
#      定位：编辑距离最多兜 ≤2；系统性/远距离/无规律错误（如 王通→三通）只有映射对能处理。
#      顺序：强证据（人工确认）优先于猜测（编辑距离），故 L2 排在 L3/L4 之前。
#   L3 编辑距离 ≤1 唯一候选：近形字自动兜底
#   L4 编辑距离 ≤2 唯一候选：更松的近形（仍要求唯一）
#   L5 未命中 → not_in_library（橙色标记）+ 进入待收录

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


# ---- 纯代码品名库对齐（替代原 DeepSeek 语义校准） ----

# 规格段字符（数字/乘号/#/DN/Φ/符号/空格/括号）
_SPEC_CHARS = set("0123456789×xX*#ΦφDNdn.+-()（）/ ")
# 规格尾缀可带的量词类汉字（仅当前面紧邻数字/规格符号时允许，如 "20角"、"32号"）
_SPEC_UNIT_CHARS = set("角孔号口寸")
# 手写字母形近数字：I/l→1，O/o→0（如 "IIO" → "110"、"IOO" → "100"）
_LOOKALIKE = {"I": "1", "i": "1", "l": "1", "O": "0", "o": "0"}


def _match_material_loose(text: str, materials: list, max_d: int = 2) -> str | None:
    """宽松品名匹配：精确/别名/前缀失败后，按编辑距离分级收敛。
    1) 大小写不敏感精确匹配（V型卡 → v型卡）
    2) 距离 1 唯一候选（亭头 → 弯头）
    3) 距离 2 唯一候选（小云水三通 → 顺水三通）
    """
    hit = _match_material(text, materials)
    if hit:
        return hit
    low = text.lower()
    ci = [m["name"] for m in materials if m["name"].lower() == low]
    if len(ci) == 1:
        return ci[0]
    if len(text) < 2:
        return None
    cands = []
    for m in materials:
        if len(m["name"]) < 2:
            continue
        if abs(len(text) - len(m["name"])) > max_d:
            continue
        d = _edit_distance(text, m["name"], max_d)
        if d <= max_d:
            cands.append((d, m["name"]))
    d1 = sorted({n for d, n in cands if d == 1})
    if len(d1) == 1:
        return d1[0]
    if d1:
        return None  # 距离 1 有多个候选，不猜测
    d2 = sorted({n for d, n in cands if d == 2})
    return d2[0] if len(d2) == 1 else None


def _generic_split(items: list) -> list:
    """
    通用名称/规格拆分：把"名称 + 尾部规格"拆开（品名库前缀匹配失败时的兜底）。
    例：斜三通110×75 → 斜三通 + 110×75；PVC排水管 IIO → PVC排水管 + 110。
    约束：前缀非空且以中文/字母结尾，避免拆坏 "86拉伸盒" 这类数字开头品名。
    """
    for it in items:
        name = str(it.get("name", "")).strip()
        spec = str(it.get("spec", "")).strip()
        if not name or spec:
            continue
        i = len(name)
        tail = ""
        has_digit_or_mark = False
        letter_look = 0
        while i > 0:
            ch = name[i - 1]
            if ch in _SPEC_CHARS:
                has_digit_or_mark = has_digit_or_mark or ch.isdigit() or ch in "×xX*#Φφ"
                tail = ch + tail
                i -= 1
            elif ch in _LOOKALIKE:
                letter_look += 1
                tail = ch + tail
                i -= 1
            elif ch in _SPEC_UNIT_CHARS and i >= 2 and name[i - 2] in _SPEC_CHARS:
                # "20角"/"32号" 的量词尾缀：仅当前一个字符是数字/规格符号时并入规格
                tail = ch + tail
                i -= 1
            else:
                break
        if not tail or i == 0:
            continue
        if not has_digit_or_mark and letter_look < 2:
            continue
        prefix = name[:i]
        if not prefix or not (prefix[-1].isalpha() or "\u4e00" <= prefix[-1] <= "\u9fff"):
            continue
        norm_tail = "".join(_LOOKALIKE.get(c, c) for c in tail)
        it["name"] = prefix
        it["spec"] = norm_tail
        it.setdefault("corrections", []).append(f"name: 拆分→{prefix} / spec: {norm_tail}")
    return items


def _align_names(items: list, materials: list) -> list:
    """形近字/别名归一：库外品名 → 编辑距离 ≤2 唯一候选 → 标准名"""
    for it in items:
        name = str(it.get("name", "")).strip()
        if not name:
            continue
        std = _match_material_loose(name, materials)
        if std and std != name:
            it["name"] = std
            it.setdefault("corrections", []).append(f"name: {name}→{std}（形近字修正）")
    return items


def _align_units(items: list, materials: list) -> list:
    """单位对齐：识别单位异常/非白名单且品名库有默认单位时，对齐为库内单位"""
    for it in items:
        name = str(it.get("name", "")).strip()
        unit = str(it.get("unit", "")).strip()
        if not name or not unit or unit in UNIT_WHITELIST:
            continue
        std_unit = get_material_unit(name)
        if not std_unit:
            std_name = _match_material(name, materials)
            if std_name:
                std_unit = get_material_unit(std_name)
        if std_unit:
            it["unit"] = std_unit
            it.setdefault("corrections", []).append(f"unit: {unit}→{std_unit}（对齐品名库）")
    return items


def calibrate_items(items: list, receipt_no: str = "", date: str = "") -> dict:
    """
    校准主流程 v3（纯代码，无模型调用）：
    1. 文本归一化
    2. 结构化解构（品名行归属，纯代码）
    3. 品名库对齐（通用规格拆分 → 形近字/别名归一 → 单位对齐）
    4. 名称规格拆分（品名库前缀）+ 继承补刀 + 代码兜底
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
            # 识别金额（原样保留，仅用于前后端对比审核，不参与计算）
            "rec_amount": it.get("rec_amount"),
        }
        normalized.append(norm)

    # 2. 结构化解构（新：识别后、模型前）
    normalized = structural_decompose(normalized)
    # 单位"略写"继承（模型前：输入中不含略写记号，杜绝模型臆测）
    normalized = inherit_abbrev_units(normalized)

    # 3. 品名库对齐（纯代码，替代 DeepSeek）
    materials = get_materials_for_prompt()
    normalized = _generic_split(normalized)
    normalized = _align_names(normalized, materials)
    normalized = _align_units(normalized, materials)

    # 4. 代码兜底：名称规格拆分 + 继承补刀 + 略写兜底 + 规则校验
    result_items = _split_name_spec(normalized, materials)
    result_items = _fill_down_names(result_items)
    # 单位"略写"兜底（模型输出残留的略写记号，静默继承，"略写"绝不泄漏）
    result_items = inherit_abbrev_units(result_items)
    result_items = [_code_fallback(it, materials) for it in result_items]

    # 未入库标记（品名不在库中 → 前端橙色徽标；空品名行不标记）
    for it in result_items:
        name = str(it.get("name", "")).strip()
        it["not_in_library"] = bool(name) and _match_material(name, materials) is None

    return {
        "success": True,
        "items": result_items,
        "header_rows": [],
        "truncated": False,
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
            "rec_amount": it.get("rec_amount"),
        }
        normalized.append(norm)
    # 单位"略写"继承（模型前：输入中不含略写记号，杜绝模型臆测）
    normalized = inherit_abbrev_units(normalized)
    yield {"step": 1, "label": "文本归一化", "done": True}

    # 2. 品名库对齐（纯代码，替代 DeepSeek）
    yield {"step": 2, "label": "品名库对齐", "done": False}
    normalized = structural_decompose(normalized)
    materials = get_materials_for_prompt()
    normalized = _generic_split(normalized)
    normalized = _align_names(normalized, materials)
    normalized = _align_units(normalized, materials)
    yield {"step": 2, "label": "品名库对齐", "done": True}

    # 3. 代码兜底
    yield {"step": 3, "label": "代码规则兜底", "done": False}
    result_items = _split_name_spec(normalized, materials)
    result_items = _fill_down_names(result_items)
    # 单位"略写"兜底（模型输出残留的略写记号，静默继承，"略写"绝不泄漏）
    result_items = inherit_abbrev_units(result_items)
    result_items = [_code_fallback(it, materials) for it in result_items]
    for it in result_items:
        name = str(it.get("name", "")).strip()
        it["not_in_library"] = bool(name) and _match_material(name, materials) is None
    header_rows = []
    yield {"step": 3, "label": "代码规则兜底", "done": True}

    # 完成
    yield {
        "step": 0,
        "done": True,
        "result": {
            "items": result_items,
            "header_rows": header_rows,
            "truncated": False,
        }
    }
