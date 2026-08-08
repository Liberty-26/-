// SteelDigitize Pro — Electron 主进程
// 生产模式：拉起内置后端（resources/backend）→ 打开 http://127.0.0.1:8000
// 开发模式：直接加载 vite dev server（外部启动 uvicorn + vite）
const { app, BrowserWindow, dialog } = require('electron');
const { autoUpdater } = require('electron-updater');
const { spawn } = require('child_process');
const path = require('path');
const fs = require('fs');
const http = require('http');

const DEV_URL = process.env.STEEL_DEV_URL || 'http://localhost:5174';
const PROD_URL = 'http://127.0.0.1:8000';
let backendProc = null;
let mainWindow = null;

// 自动更新：打包版启动后检查 GitHub Releases，有新版本提示下载安装
function setupAutoUpdater() {
  if (!app.isPackaged) return;
  autoUpdater.autoDownload = false;
  autoUpdater.autoInstallOnAppQuit = true;

  autoUpdater.on('update-available', (info) => {
    dialog.showMessageBox(mainWindow, {
      type: 'info',
      title: '发现新版本',
      message: `发现新版本 ${info.version}，是否立即更新？`,
      detail: '更新完成后应用会自动重启。',
      buttons: ['立即更新', '稍后再说'],
      defaultId: 0,
      cancelId: 1,
    }).then(({ response }) => {
      if (response === 0) autoUpdater.downloadUpdate();
    });
  });

  autoUpdater.on('update-downloaded', () => {
    dialog.showMessageBox(mainWindow, {
      type: 'info',
      title: '更新已就绪',
      message: '新版本已下载完成，重启后生效。',
      buttons: ['立即重启', '稍后再说'],
      defaultId: 0,
      cancelId: 1,
    }).then(({ response }) => {
      if (response === 0) autoUpdater.quitAndInstall();
    });
  });

  autoUpdater.on('error', (e) => console.error('[updater]', e && e.message));
  autoUpdater.on('update-not-available', () => console.log('[updater] 已是最新版本'));

  // 启动 6 秒后再检查，避免影响首屏加载
  setTimeout(() => {
    autoUpdater.checkForUpdates().catch((e) => console.error('[updater] 检查失败', e && e.message));
  }, 6000);
}

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
