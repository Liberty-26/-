// SteelDigitize Pro — Electron 主进程
// 生产模式：拉起内置后端（resources/backend）→ 打开 http://127.0.0.1:8000
// 开发模式：直接加载 vite dev server（外部启动 uvicorn + vite）
const { app, BrowserWindow, ipcMain } = require('electron');
const { autoUpdater } = require('electron-updater');
const { spawn } = require('child_process');
const path = require('path');
const fs = require('fs');
const http = require('http');

const DEV_URL = process.env.STEEL_DEV_URL || 'http://localhost:5174';
const PROD_URL = 'http://127.0.0.1:8000';
let backendProc = null;
let mainWindow = null;
let updateState = { available: false, version: '', downloaded: false };

function sendUpdate(payload) {
  if (mainWindow && !mainWindow.isDestroyed()) {
    mainWindow.webContents.send('update-event', payload);
  }
}

// 自动更新：启动后自动检查 GitHub Releases；前端设置页可手动检查/下载/安装
function setupAutoUpdater() {
  if (!app.isPackaged) return;
  autoUpdater.autoDownload = false;
  autoUpdater.autoInstallOnAppQuit = true;

  autoUpdater.on('update-available', (info) => {
    updateState.available = true;
    updateState.version = info.version;
    sendUpdate({ type: 'available', version: info.version });
  });

  autoUpdater.on('update-downloaded', () => {
    updateState.downloaded = true;
    sendUpdate({ type: 'downloaded', version: updateState.version });
  });

  autoUpdater.on('download-progress', (p) => {
    sendUpdate({ type: 'progress', percent: Math.round(p.percent || 0) });
  });

  autoUpdater.on('error', (e) => sendUpdate({ type: 'error', message: (e && e.message) || '更新失败' }));
  autoUpdater.on('update-not-available', () => sendUpdate({ type: 'uptodate' }));

  // 启动 6 秒后再检查，避免影响首屏加载
  setTimeout(() => {
    autoUpdater.checkForUpdates().catch((e) => console.error('[updater] 检查失败', e && e.message));
  }, 6000);
}

// 前端设置页手动触发
ipcMain.handle('check-updates', async () => {
  if (!app.isPackaged) return { ok: false, message: '当前是开发模式，请安装正式版后使用自动更新' };
  try {
    const result = await autoUpdater.checkForUpdates();
    const version = result && result.updateInfo ? result.updateInfo.version : '';
    return { ok: true, status: result ? 'available' : 'uptodate', version };
  } catch (e) {
    return { ok: false, message: (e && e.message) || '检查更新失败' };
  }
});

ipcMain.handle('download-update', async () => {
  if (!updateState.available) return { ok: false, message: '当前没有可用更新' };
  autoUpdater.downloadUpdate();
  return { ok: true };
});

ipcMain.handle('install-update', async () => {
  autoUpdater.quitAndInstall();
  return { ok: true };
});

function backendExePath() {
  const name = process.platform === 'win32' ? 'SteelDigitizeBackend.exe' : 'SteelDigitizeBackend';
  // extraResources 把 backend-dist 整体复制到 resources/backend，保留了 SteelDigitizeBackend/ 一层目录
  return path.join(process.resourcesPath, 'backend', 'SteelDigitizeBackend', name);
}

function startBackend() {
  if (!app.isPackaged) return; // 开发模式：后端由外部 uvicorn 提供
  const exe = backendExePath();
  if (!fs.existsSync(exe)) {
    console.error('[electron] 内置后端不存在:', exe);
    return;
  }
  // 工作目录放在用户数据目录，数据与安装目录分离（Windows 上 Program Files 只读）
  const workDir = path.join(app.getPath('userData'), 'appdata');
  fs.mkdirSync(workDir, { recursive: true });
  backendProc = spawn(exe, [], {
    cwd: workDir,
    stdio: 'ignore',
    windowsHide: true,
    env: {
      ...process.env,
      WORK_DIR: workDir,
      FRONTEND_DIR: path.join(process.resourcesPath, 'frontend', 'dist'),
    },
  });
  backendProc.on('exit', (code) => {
    console.error('[electron] 后端退出 code=', code);
    backendProc = null;
  });
}

function waitBackend(timeoutMs = 30000) {
  const start = Date.now();
  return new Promise((resolve, reject) => {
    const check = () => {
      const req = http.get(PROD_URL + '/api/health', (res) => {
        res.resume();
        resolve(true);
      });
      req.on('error', () => {
        if (Date.now() - start > timeoutMs) return reject(new Error('后端启动超时'));
        setTimeout(check, 400);
      });
    };
    check();
  });
}

async function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1500,
    height: 940,
    minWidth: 1100,
    minHeight: 700,
    title: 'SteelDigitize Pro',
    autoHideMenuBar: true,
    webPreferences: {
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
      preload: path.join(__dirname, 'preload.js'),
    },
  });

  if (app.isPackaged) {
    try {
      await waitBackend();
    } catch (e) {
      console.error('[electron] 后端未就绪，仍尝试打开页面:', e.message);
    }
    mainWindow.loadURL(PROD_URL);
  } else {
    mainWindow.loadURL(DEV_URL);
    mainWindow.webContents.openDevTools({ mode: 'detach' });
  }

  mainWindow.on('closed', () => { mainWindow = null; });
}

app.whenReady().then(() => {
  startBackend();
  createWindow();
  setupAutoUpdater();
});

app.on('window-all-closed', () => {
  if (backendProc) {
    try { backendProc.kill(); } catch { /* ignore */ }
    backendProc = null;
  }
  if (process.platform !== 'darwin') app.quit();
});

app.on('activate', () => {
  if (BrowserWindow.getAllWindows().length === 0) createWindow();
});
