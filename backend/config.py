"""
SteelDigitize Pro — 配置加载
通用化设计，不绑定特定厂商。
"""
import os
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent

# 配置目录：桌面版由 Electron 传入 CONFIG_DIR（用户数据目录，升级/重装不丢）；
# 开发模式默认使用源码目录 backend/.env
CONFIG_DIR = Path(os.getenv("CONFIG_DIR", str(BASE_DIR)))
ENV_PATH = CONFIG_DIR / ".env"

# 一次性迁移：若配置目录还没有 .env，而源码目录有旧配置（开发模式），复制过去
if ENV_PATH != BASE_DIR / ".env" and not ENV_PATH.exists() and (BASE_DIR / ".env").exists():
    try:
        ENV_PATH.parent.mkdir(parents=True, exist_ok=True)
        import shutil
        shutil.copyfile(BASE_DIR / ".env", ENV_PATH)
    except Exception:
        pass

load_dotenv(ENV_PATH)

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
BACKUP_DIR = os.getenv("BACKUP_DIR", "")


def reload_config():
    """重新加载 .env"""
    load_dotenv(ENV_PATH, override=True)
    for k in ("VISION_API_KEY", "VISION_API_BASE", "VISION_MODEL",
              "AGENT_API_KEY", "AGENT_API_BASE", "AGENT_MODEL",
              "SCAN_API_KEY", "SCAN_API_BASE", "SCAN_SCENE",
              "WORK_DIR", "BACKUP_DIR", "YESCAN_BIN"):
        globals()[k] = os.getenv(k, globals().get(k, ""))
    try:
        globals()["SCAN_MAX_CONCURRENCY"] = int(os.getenv("SCAN_MAX_CONCURRENCY", "2"))
    except ValueError:
        pass


def save_config(**kwargs):
    """保存配置到 .env（桌面版在用户数据目录，升级不丢）"""
    env_path = ENV_PATH
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
        "backup_dir": "BACKUP_DIR",
    }
    for short, full in key_map.items():
        if short in kwargs:
            if kwargs[short]:
                existing[full] = kwargs[short]
            else:
                # 显式传空值 = 清空该配置项（从 .env 移除，回落到默认值）
                existing.pop(full, None)

    with open(env_path, "w", encoding="utf-8") as f:
        f.write("# SteelDigitize Pro 配置文件\n")
        for k, v in existing.items():
            f.write(f"{k}={v}\n")

    reload_config()
