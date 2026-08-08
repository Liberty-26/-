"""
SteelDigitize Pro — 配置加载
通用化设计，不绑定特定厂商。
"""
import os
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

# ---- 识图模型配置 ----
VISION_API_KEY = os.getenv("VISION_API_KEY", "")
VISION_API_BASE = os.getenv("VISION_API_BASE", "https://dashscope.aliyuncs.com/compatible-mode/v1")
VISION_MODEL = os.getenv("VISION_MODEL", "qwen-vl-plus")

# ---- Agent 模型配置 ----
AGENT_API_KEY = os.getenv("AGENT_API_KEY", "")
AGENT_API_BASE = os.getenv("AGENT_API_BASE", "https://api.deepseek.com")
AGENT_MODEL = os.getenv("AGENT_MODEL", "deepseek-chat")

# ---- 夸克扫描王配置（识别引擎）----
# 注意：转 Excel（image-to-excel）是 Agent 专用能力，密钥必须是 Agent 接入的
# SCAN_WEBSERVICE_KEY（在设置页填写的识别引擎 Key 即为此值）。
# 调用统一走官方 CLI（yescan），不直接发 REST 请求。
SCAN_API_KEY = os.getenv("SCAN_API_KEY", "")
SCAN_API_BASE = os.getenv("SCAN_API_BASE", "https://scan-business.quark.cn/vision")
SCAN_SCENE = os.getenv("SCAN_SCENE", "image-to-excel")
YESCAN_BIN = os.getenv("YESCAN_BIN", str(BASE_DIR / ".venv/bin/yescan"))
# 批量识别并发上限（同时最多几个请求在飞）
# 实测并发 3 会触发夸克 QPS 限流（A0300），默认降到 2；A0300 会自动退避重试
SCAN_MAX_CONCURRENCY = int(os.getenv("SCAN_MAX_CONCURRENCY", "2"))

# ---- 数据库 & 存储 ----
DATABASE_PATH = os.getenv("DATABASE_PATH", str(BASE_DIR / "data.db"))
UPLOAD_DIR = os.getenv("UPLOAD_DIR", str(BASE_DIR / "uploads"))
WORK_DIR = os.getenv("WORK_DIR", "")


def reload_config():
    """重新加载 .env"""
    load_dotenv(BASE_DIR / ".env", override=True)
    for k in ("VISION_API_KEY", "VISION_API_BASE", "VISION_MODEL",
              "AGENT_API_KEY", "AGENT_API_BASE", "AGENT_MODEL",
              "SCAN_API_KEY", "SCAN_API_BASE", "SCAN_SCENE",
              "WORK_DIR", "YESCAN_BIN"):
        globals()[k] = os.getenv(k, globals().get(k, ""))
    try:
        globals()["SCAN_MAX_CONCURRENCY"] = int(os.getenv("SCAN_MAX_CONCURRENCY", "5"))
    except ValueError:
        pass


def save_config(**kwargs):
    """保存配置到 .env"""
    env_path = BASE_DIR / ".env"
    existing = {}
    if env_path.exists():
        with open(env_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    existing[k.strip()] = v.strip()

    key_map = {
        "vision_key": "VISION_API_KEY", "vision_base": "VISION_API_BASE", "vision_model": "VISION_MODEL",
        "agent_key": "AGENT_API_KEY", "agent_base": "AGENT_API_BASE", "agent_model": "AGENT_MODEL",
        "scan_key": "SCAN_API_KEY", "scan_base": "SCAN_API_BASE", "scan_scene": "SCAN_SCENE",
        "work_dir": "WORK_DIR",
    }
    for short, full in key_map.items():
        if short in kwargs and kwargs[short]:
            existing[full] = kwargs[short]

    with open(env_path, "w", encoding="utf-8") as f:
        f.write("# SteelDigitize Pro 配置文件\n")
        for k, v in existing.items():
            f.write(f"{k}={v}\n")

    reload_config()
