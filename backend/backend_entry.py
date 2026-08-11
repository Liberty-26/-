"""SteelDigitize Pro — 桌面版后端入口（PyInstaller 打包用）

打包后直接运行本程序即可启动内置服务（127.0.0.1:8000）。
"""
import os
from pathlib import Path
import uvicorn


def main():
    # 应用数据目录与用户可修改的表格工作目录分离。
    # 旧版本使用 WORK_DIR 传应用数据目录，会在启动时覆盖 .env 里的用户选择。
    work_dir = (os.environ.get("STEEL_DATA_DIR", "").strip()
                or os.environ.get("WORK_DIR", "").strip())
    # 桌面版的 WORK_DIR 只在旧版本里代表应用数据目录；新版本由
    # STEEL_DATA_DIR 承载应用数据，必须移除旧环境变量后再加载 config。
    if os.environ.get("STEEL_DATA_DIR", "").strip():
        os.environ.pop("WORK_DIR", None)
    if not work_dir:
        work_dir = str(Path(__file__).resolve().parent)
    os.environ.setdefault("DATABASE_PATH", str(Path(work_dir) / "data.db"))
    os.environ.setdefault("UPLOAD_DIR", str(Path(work_dir) / "uploads"))

    from main import app  # noqa: E402  （确保上面环境变量先设置好）

    uvicorn.run(app, host="127.0.0.1", port=8000, log_level="warning")


if __name__ == "__main__":
    main()
