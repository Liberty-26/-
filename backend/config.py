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

# ---- 数据库 & 存储 ----
DATABASE_PATH = os.getenv("DATABASE_PATH", str(BASE_DIR / "data.db"))
UPLOAD_DIR = os.getenv("UPLOAD_DIR", str(BASE_DIR / "uploads"))
WORK_DIR = os.getenv("WORK_DIR", "")


def reload_config():
    """重新加载 .env"""
    load_dotenv(BASE_DIR / ".env", override=True)
    for k in ("VISION_API_KEY", "VISION_API_BASE", "VISION_MODEL",
              "AGENT_API_KEY", "AGENT_API_BASE", "AGENT_MODEL",
              "WORK_DIR"):
        globals()[k] = os.getenv(k, globals().get(k, ""))


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
