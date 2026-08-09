// 桌面端桥接：设置页"检查更新"通过这里与主进程通信
const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('steel', {
  isDesktop: true,
  checkForUpdates: () => ipcRenderer.invoke('check-updates'),
  downloadUpdate: () => ipcRenderer.invoke('download-update'),
  installUpdate: () => ipcRenderer.invoke('install-update'),
  getVersion: () => ipcRenderer.invoke('get-app-version'),
  onUpdateEvent: (cb) => {
    const handler = (_e, data) => cb(data);
    ipcRenderer.on('update-event', handler);
    return () => ipcRenderer.removeListener('update-event', handler);
  },
});
