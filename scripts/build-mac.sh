#!/usr/bin/env bash
# SteelDigitize Pro — Mac 本地构建 + 安装（不依赖 GitHub，不用下载安装包）
#
# 用法：
#   ./scripts/build-mac.sh            # 构建 + 替换安装到 /Applications 并启动
#   ./scripts/build-mac.sh --no-install  # 只构建，不安装
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

INSTALL=1
if [[ "${1:-}" == "--no-install" ]]; then INSTALL=0; fi

echo "==> [1/5] 构建前端"
if [[ ! -d frontend/node_modules ]]; then
  echo "    frontend 依赖缺失，先安装 npm ci …"
  (cd frontend && npm ci)
fi
(cd frontend && npm run build)

echo "==> [2/5] 安装后端依赖（PyInstaller + 识别 SDK）"
if [[ ! -x backend/.venv/bin/python ]]; then
  echo "    未找到 backend/.venv，创建虚拟环境 …"
  (cd backend && python3 -m venv .venv)
fi
(cd backend && .venv/bin/pip install -r requirements.txt pyinstaller yescan)

echo "==> [3/5] 打包内置后端（PyInstaller）"
(cd backend && rm -rf dist build && .venv/bin/pyinstaller \
  --noconfirm --clean --name SteelDigitizeBackend --onedir --noconsole \
  --collect-all uvicorn --collect-all fastapi --collect-all openpyxl --collect-all yescan \
  --hidden-import uvicorn.logging --hidden-import uvicorn.loops.auto \
  --hidden-import uvicorn.protocols.http.auto --hidden-import uvicorn.protocols.websockets.auto \
  --hidden-import uvicorn.lifespan.on backend_entry.py)

echo "==> [4/5] 准备 Electron 内置后端资源"
rm -rf electron/backend-dist/SteelDigitizeBackend
mkdir -p electron/backend-dist/SteelDigitizeBackend
cp -R backend/dist/SteelDigitizeBackend/* electron/backend-dist/SteelDigitizeBackend/

echo "==> [5/5] 打包 Mac 应用（dmg）"
if [[ ! -d electron/node_modules ]]; then
  echo "    electron 依赖缺失，先安装 npm ci …"
  (cd electron && npm ci)
fi
rm -rf electron/release   # 清理旧构建产物，避免混入历史版本
(cd electron && npm run dist:mac)

APP_SRC="$(find electron/release -maxdepth 3 -name "*.app" -print -quit || true)"
VER="$(node -p "require('./electron/package.json').version")"
DMG_SRC="electron/release/SteelDigitize-Pro-${VER}-arm64.dmg"
if [[ -z "$APP_SRC" ]]; then
  echo "错误：未找到构建产物（electron/release 下没有 .app）" >&2
  exit 1
fi

if [[ "$INSTALL" -eq 1 ]]; then
  echo "==> 安装到 /Applications（替换旧版，数据保留）"
  osascript -e 'quit app "SteelDigitize Pro"' 2>/dev/null || true
  sleep 3
  pkill -f "SteelDigitize Pro" 2>/dev/null || true
  sleep 1
  rm -rf "/Applications/SteelDigitize Pro.app"
  ditto "$APP_SRC" "/Applications/SteelDigitize Pro.app"
  open "/Applications/SteelDigitize Pro.app"
  INSTALLED_VER="$(defaults read "/Applications/SteelDigitize Pro.app/Contents/Info.plist" CFBundleShortVersionString 2>/dev/null || echo '?')"
  echo "完成：已安装并启动 v$INSTALLED_VER"
else
  echo "完成：已构建未安装 → $APP_SRC"
fi
[[ -f "$DMG_SRC" ]] && echo "安装包：$DMG_SRC"
