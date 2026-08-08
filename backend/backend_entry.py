"""SteelDigitize Pro — 桌面版后端入口（PyInstaller 打包用）

打包后直接运行本程序即可启动内置服务（127.0.0.1:8000）。
"""
import os
from pathlib import Path
import uvicorn


def main():
    # 数据目录：优先使用 Electron 传入的 WORK_DIR，否则与可执行文件同目录
    work_dir = os.environ.get("WORK_DIR", "").strip()
    if not work_dir:
        work_dir = str(Path(__file__).resolve().parent)
    os.environ.setdefault("DATABASE_PATH", str(Path(work_dir) / "data.db"))
    os.environ.setdefault("UPLOAD_DIR", str(Path(work_dir) / "uploads"))

    from main import app  # noqa: E402  （确保上面环境变量先设置好）

    uvicorn.run(app, host="127.0.0.1", port=8000, log_level="warning")


if __name__ == "__main__":
    main()
