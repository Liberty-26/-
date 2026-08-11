// SteelDigitize Pro — Electron 主进程
// 生产模式：拉起内置后端（resources/backend）→ 打开 http://127.0.0.1:8000
// 开发模式：直接加载 vite dev server（外部启动 uvicorn + vite）
const { app, BrowserWindow, ipcMain, dialog } = require('electron');
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

// 单实例锁：防止重复打开导致多个后端抢占 8000 端口
const gotLock = app.requestSingleInstanceLock();
if (!gotLock) {
  app.quit();
}

function sendUpdate(payload) {
  if (mainWindow && !mainWindow.isDestroyed()) {
    mainWindow.webContents.send('update-event', payload);
  }
}

// 语义化比较版本号（仅支持 x.y.z）：remote > local 才算有新版本
function isNewerVersion(remote, local) {
  if (!remote || !local) return false;
  const r = String(remote).split('.').map((n) => parseInt(n, 10) || 0);
  const l = String(local).split('.').map((n) => parseInt(n, 10) || 0);
  const len = Math.max(r.length, l.length);
  for (let i = 0; i < len; i++) {
    const a = r[i] || 0;
    const b = l[i] || 0;
    if (a !== b) return a > b;
  }
  return false;
}

// 自动更新：启动后自动检查 GitHub Releases；前端设置页可手动检查/下载/安装
function setupAutoUpdater() {
  if (!app.isPackaged) return;
  autoUpdater.autoDownload = false;
  autoUpdater.autoInstallOnAppQuit = true;
  // 国内访问 GitHub 不稳定，更新源走加速镜像；发版仍自动上传 GitHub Releases
  autoUpdater.setFeedURL({
    provider: 'generic',
    url: 'https://gh-proxy.com/https://github.com/Liberty-26/-/releases/latest/download',
  });

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
    const hasNew = isNewerVersion(version, app.getVersion());
    return { ok: true, status: hasNew ? 'available' : 'uptodate', version };
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

ipcMain.handle('get-app-version', async () => app.getVersion());

// 桌面端使用 Electron 原生目录对话框；不依赖后端 Tkinter，避免打包后无法弹窗。
ipcMain.handle('pick-directory', async () => {
  const result = await dialog.showOpenDialog({
    title: '选择文件存放目录',
    properties: ['openDirectory', 'createDirectory'],
  });
  return {
    ok: !result.canceled && Boolean(result.filePaths && result.filePaths[0]),
    path: result.canceled ? '' : (result.filePaths?.[0] || ''),
  };
});

function backendExePath() {
  const name = process.platform === 'win32' ? 'SteelDigitizeBackend.exe' : 'SteelDigitizeBackend';
  // extraResources 把 backend-dist 整体复制到 resources/backend，保留了 SteelDigitizeBackend/ 一层目录
  return path.join(process.resourcesPath, 'backend', 'SteelDigitizeBackend', name);
}

function getDistMtime() {
  try {
    const p = path.join(process.resourcesPath, 'frontend', 'dist', 'index.html');
    if (fs.existsSync(p)) return String(Math.round(fs.statSync(p).mtimeMs));
  } catch (e) { /* ignore */ }
  return '';
}

function getDistHash() {
  // 前端构建产物内容哈希：与后端 health.dist_hash 比对，覆盖安装后也不会误判
  try {
    const p = path.join(process.resourcesPath, 'frontend', 'dist', 'index.html');
    if (fs.existsSync(p)) {
      const crypto = require('crypto');
      return crypto.createHash('sha256').update(fs.readFileSync(p)).digest('hex').slice(0, 16);
    }
  } catch (e) { /* ignore */ }
  return '';
}

function fetchHealth(timeoutMs = 1200) {
  return new Promise((resolve) => {
    const req = http.get(PROD_URL + '/api/health', { timeout: timeoutMs }, (res) => {
      let body = '';
      res.on('data', (c) => { body += c; });
      res.on('end', () => {
        try {
          const j = JSON.parse(body);
          resolve(j && j.success && j.data ? j.data : null);
        } catch (e) { resolve(null); }
      });
    });
    req.on('error', () => resolve(null));
    req.setTimeout(timeoutMs, () => { req.destroy(); resolve(null); });
  });
}

function killProcess(pid) {
  return new Promise((resolve) => {
    if (!pid || Number(pid) === process.pid) return resolve();
    try {
      if (process.platform === 'win32') {
        const { execFile } = require('child_process');
        execFile('taskkill', ['/F', '/PID', String(pid)], () => resolve());
      } else {
        process.kill(Number(pid), 'SIGTERM');
        resolve();
      }
    } catch (e) { resolve(); }
  });
}

// 按端口找出监听进程 PID（Windows: netstat；macOS/Linux: lsof）
function getPortPids(port) {
  return new Promise((resolve) => {
    const { execFile } = require('child_process');
    if (process.platform === 'win32') {
      execFile('netstat', ['-ano'], (err, stdout) => {
        if (err) return resolve([]);
        const pids = new Set();
        const re = new RegExp(`\\s*TCP\\s+127\\.0\\.0\\.1:${port}\\s+\\S+\\s+LISTENING\\s+(\\d+)`);
        for (const line of String(stdout).split(/\r?\n/)) {
          const m = line.match(re);
          if (m) pids.add(m[1]);
        }
        resolve([...pids]);
      });
    } else {
      execFile('lsof', ['-ti', `tcp:${port}`], (err, stdout) => {
        if (err) return resolve([]);
        resolve(String(stdout).trim().split(/\s+/).filter(Boolean));
      });
    }
  });
}

async function startBackend() {
  if (!app.isPackaged) return; // 开发模式：后端由外部 uvicorn 提供
  const exe = backendExePath();
  if (!fs.existsSync(exe)) {
    console.error('[electron] 内置后端不存在:', exe);
    return;
  }
  // 若 8000 已有健康后端：指纹一致（同一安装版本）→ 复用；指纹不一致（升级后残留的旧版后端）→ 杀掉重启
  const health = await fetchHealth();
  if (health) {
    const myDist = getDistMtime();
    const myHash = getDistHash();
    const myVersion = app.getVersion();
    const versionMatch = Boolean(health.version && myVersion && health.version === myVersion);
    const hashMatch = Boolean(health.dist_hash && myHash && health.dist_hash === myHash);
    const mtimeMatch = Boolean(health.dist_mtime && myDist && health.dist_mtime === myDist);
    // 版本一致且（哈希一致或旧后端不返回哈希但 mtime 一致）→ 复用
    const sameBuild = versionMatch && (hashMatch || (!health.dist_hash && mtimeMatch));
    if (sameBuild) {
      console.log('[electron] 复用已运行的后端服务');
      return;
    }
    console.log('[electron] 检测到旧版本残留后端（version=' + (health.version || '?') + '），关闭后启动新版');
    await killProcess(health.pid);
    await new Promise((r) => setTimeout(r, 800));
  }
  // 兜底：health 探测不到但端口仍被占用（残留进程不响应/异常）→ 按端口强清
  const portPids = await getPortPids(8000);
  if (portPids.length) {
    console.log('[electron] 端口 8000 存在残留监听进程，清理后启动新版');
    for (const pid of portPids) {
      if (Number(pid) === process.pid) continue;
      await killProcess(pid);
    }
    await new Promise((r) => setTimeout(r, 800));
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
      CONFIG_DIR: workDir,
      FRONTEND_DIR: path.join(process.resourcesPath, 'frontend', 'dist'),
      MATERIALS_SEED_CSV: path.join(process.resourcesPath, '品名种子清单.csv'),
      STEEL_VERSION: app.getVersion(),
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
    title: '数字化工作台',
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
    // 升级后清一次 HTTP 缓存，避免窗口加载到旧版前端资源
    try {
      await mainWindow.webContents.session.clearCache();
    } catch (e) { /* ignore */ }
    mainWindow.loadURL(PROD_URL);
  } else {
    mainWindow.loadURL(DEV_URL);
    mainWindow.webContents.openDevTools({ mode: 'detach' });
  }

  mainWindow.on('closed', () => { mainWindow = null; });
}

app.whenReady().then(async () => {
  await startBackend();
  createWindow();
  setupAutoUpdater();
});

app.on('window-all-closed', () => {
  // macOS 习惯：关窗不退出，保留后端以便再次点开立即可用；
  // 其他平台关窗即退出，由 before-quit 统一清理后端。
  if (process.platform !== 'darwin') {
    if (backendProc) {
      try { backendProc.kill(); } catch { /* ignore */ }
      backendProc = null;
    }
  }
  if (process.platform !== 'darwin') app.quit();
});

app.on('before-quit', () => {
  if (backendProc) {
    try { backendProc.kill(); } catch { /* ignore */ }
    backendProc = null;
  }
});

app.on('activate', () => {
  if (BrowserWindow.getAllWindows().length === 0) {
    // macOS 上后端可能已被外部终止/从未启动：重新拉起后再开窗
    startBackend().then(createWindow);
  }
});
