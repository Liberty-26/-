// SteelDigitize Pro — 设置中心（识别与模型 / 助手记忆 / 关于）
import { useCallback, useEffect, useState, type ReactNode } from 'react';
import { useToast } from '../hooks/useToast';
import {
  getSettings, saveSettings, getScanScenes, testScanConnection,
  getFacts, addFact, deleteFact, updateFact, pickDirectory,
  exportBackup, getBackups,
} from '../utils/api';
import type { AssistantFact } from '../types';
import {
  CheckCircle2, FolderOpen, Database, RefreshCw, ChevronDown, Pencil, Trash2,
} from 'lucide-react';

const S = { aKey: 'steel_agent_key', aBase: 'steel_agent_base', aModel: 'steel_agent_model', sKey: 'steel_scan_key' };

interface ScanScene { scene: string; label: string; type: string }

export default function SettingsPage() {
  const { showToast } = useToast();
  const [panel, setPanel] = useState('engine');

  // 工作助手
  const [aKey, setAKey] = useState('');
  const [aBase, setABase] = useState('https://api.deepseek.com');
  const [aModel, setAModel] = useState('');
  const [aModels, setAModels] = useState<{ id: string; label: string }[]>([]);
  const [fetchingModels, setFetchingModels] = useState(false);
  const [testingAgent, setTestingAgent] = useState(false);

  // 识别引擎（扫描王）
  const [sKey, setSKey] = useState('');
  const [sBase, setSBase] = useState('https://scan-business.quark.cn/vision');
  const [sScene, setSScene] = useState('image-to-excel');
  const [scenes, setScenes] = useState<ScanScene[]>([]);
  const [testingScan, setTestingScan] = useState(false);
  const [engineEditing, setEngineEditing] = useState(false);
  const [agentEditing, setAgentEditing] = useState(false);

  // 助手记忆：文件存放位置 + 事实层
  const [workDir, setWorkDir] = useState('');
  const [facts, setFacts] = useState<AssistantFact[]>([]);
  const [factKey, setFactKey] = useState('');
  const [factVal, setFactVal] = useState('');
  const [editingFactId, setEditingFactId] = useState<number | null>(null);
  const [editFactKey, setEditFactKey] = useState('');
  const [editFactVal, setEditFactVal] = useState('');
  const [factScope, setFactScope] = useState<'memory' | 'user'>('memory');
  const [editFactScope, setEditFactScope] = useState<'memory' | 'user'>('memory');

  // 关于：版本 / 备份 / 更新
  const [appVersion, setAppVersion] = useState('');
  const [backupDir, setBackupDir] = useState('');
  const [backups, setBackups] = useState<{ name: string; size: number; created_at: string; path?: string }[]>([]);
  const [backingUp, setBackingUp] = useState(false);
  const [showBackupDetail, setShowBackupDetail] = useState(false);

  const [upd, setUpd] = useState<{
    state: 'idle' | 'checking' | 'available' | 'uptodate' | 'downloading' | 'downloaded' | 'error';
    version: string;
    percent: number;
    message: string;
  }>({ state: 'idle', version: '', percent: 0, message: '' });

  // 监听主进程推送的更新事件（桌面版）
  useEffect(() => {
    const steel = (window as any).steel;
    if (steel && steel.getVersion) {
      steel.getVersion().then((v: string) => setAppVersion(v || ''));
    }
    if (!steel || !steel.onUpdateEvent) return;
    const off = steel.onUpdateEvent((ev: any) => {
      if (ev.type === 'available') setUpd({ state: 'available', version: ev.version || '', percent: 0, message: '' });
      else if (ev.type === 'uptodate') { setUpd({ state: 'uptodate', version: '', percent: 0, message: '' }); }
      else if (ev.type === 'progress') setUpd((s) => ({ ...s, state: 'downloading', percent: ev.percent || 0 }));
      else if (ev.type === 'downloaded') setUpd((s) => ({ ...s, state: 'downloaded' }));
      else if (ev.type === 'error') setUpd({ state: 'error', version: '', percent: 0, message: ev.message || '更新失败' });
    });
    return off;
  }, []);

  const refreshBackups = useCallback(async () => {
    const res = await getBackups();
    if (res.success && res.data) setBackups(res.data.backups);
  }, []);

  useEffect(() => { refreshBackups(); }, [refreshBackups]);

  const handleBackup = async () => {
    setBackingUp(true);
    const res = await exportBackup();
    setBackingUp(false);
    if (res.success && res.data) {
      showToast('备份已更新到最新数据', 'success');
      refreshBackups();
    } else {
      showToast(res.error || '备份失败', 'error');
    }
  };

  const handlePickBackupDir = async () => {
    const res = await pickDirectory();
    if (res.success && res.data?.path) {
      setBackupDir(res.data.path);
      await saveSettings({ backup_dir: res.data.path });
      refreshBackups();
      showToast('备份位置已更新', 'success');
    } else {
      showToast(res.error || '选择失败', 'error');
    }
  };

  const handleCheckUpdate = async () => {
    const steel = (window as any).steel;
    if (!steel || !steel.checkForUpdates) { showToast('自动更新仅桌面版可用（网页版请手动下载安装包）', 'warning'); return; }
    setUpd({ state: 'checking', version: '', percent: 0, message: '' });
    const res = await steel.checkForUpdates();
    if (!res.ok) {
      setUpd({ state: 'error', version: '', percent: 0, message: res.message || '检查更新失败' });
      return;
    }
    if (res.status === 'available') setUpd({ state: 'available', version: res.version || '', percent: 0, message: '' });
    else { setUpd({ state: 'uptodate', version: '', percent: 0, message: '' }); }
  };

  const handleDownloadUpdate = async () => {
    const steel = (window as any).steel;
    if (!steel || !steel.downloadUpdate) return;
    setUpd((s) => ({ ...s, state: 'downloading', percent: 0 }));
    const res = await steel.downloadUpdate();
    if (res && !res.ok) {
      setUpd({ state: 'error', version: '', percent: 0, message: res.message || '下载失败，请重试' });
    }
  };

  const handleInstallUpdate = async () => {
    const steel = (window as any).steel;
    if (steel && steel.installUpdate) await steel.installUpdate();
  };

  useEffect(() => {
    const saved = (k: string) => localStorage.getItem(k) || '';
    setABase(saved(S.aBase) || 'https://api.deepseek.com');
    setAModel(saved(S.aModel));
    getSettings().then((res) => {
      if (res.success && res.data) {
        const d = res.data;
        // API Key 以后端实际保存值为准（有就是有，没有就是没有，不回填本地残留）
        setAKey(d.agent_api_key || '');
        setSKey(d.scan_api_key || '');
        setWorkDir(d.work_dir || '');
        setBackupDir(d.backup_dir || '');
        if (d.agent_api_base) setABase(d.agent_api_base);
        if (d.agent_model) setAModel(d.agent_model);
        if (d.scan_api_base) setSBase(d.scan_api_base);
        if (d.scan_scene) setSScene(d.scan_scene);
      }
    });
    getScanScenes().then((res) => {
      if (res.success && res.data) {
        setScenes(res.data.scenes);
        if (res.data.current) setSScene(res.data.current);
      }
    });
  }, []);

  const loadMemory = useCallback(() => {
    getFacts().then((r) => { if (r.success && r.data) setFacts(r.data.facts); });
  }, []);

  useEffect(() => { if (panel === 'memory') loadMemory(); }, [panel, loadMemory]);

  /* ---------- 工作助手 ---------- */
  const handleSaveAgent = async () => {
    const res = await saveSettings({ agent_key: aKey, agent_base: aBase, agent_model: aModel });
    localStorage.setItem(S.aBase, aBase);
    localStorage.setItem(S.aModel, aModel);
    if (res.success) { showToast('助手配置已保存', 'success'); setAgentEditing(false); }
    else showToast(res.error || '保存失败', 'error');
  };

  const handleTestAgent = async () => {
    if (!aKey || !aModel) { showToast('请先填写助手 API Key 与模型', 'warning'); return; }
    setTestingAgent(true);
    try {
      const r = await fetch('/api/settings/test-agent', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ api_base: aBase, api_key: aKey, model: aModel }),
      });
      const j = await r.json();
      if (r.ok && j.success) showToast(`连接成功（${aModel}），耗时 ${j.data.latency_ms}ms`, 'success');
      else showToast(j.detail || '连接失败', 'error');
    } catch (e) {
      showToast((e as Error).message || '连接失败', 'error');
    }
    setTestingAgent(false);
  };

  const handleFetchModels = async () => {
    if (!aKey) { showToast('请先填写助手 API Key', 'warning'); return; }
    setFetchingModels(true);
    try {
      const r = await fetch('/api/settings/fetch-models', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ api_base: aBase, api_key: aKey }),
      });
      const j = await r.json();
      if (r.ok && j.success && j.data?.models) {
        setAModels(j.data.models);
        if (j.data.models.length > 0 && !j.data.models.some((m: { id: string }) => m.id === aModel)) {
          setAModel(j.data.models[0].id);
        }
        showToast(`已获取 ${j.data.models.length} 个模型`, 'success');
      } else showToast(j.detail || '获取模型列表失败', 'error');
    } catch (e) {
      showToast((e as Error).message || '获取模型列表失败', 'error');
    }
    setFetchingModels(false);
  };

  /* ---------- 识别引擎（扫描王） ---------- */
  const handleSaveScan = async () => {
    const res = await saveSettings({ scan_key: sKey, scan_base: sBase, scan_scene: sScene });
    if (res.success) { showToast('识别引擎配置已保存', 'success'); setEngineEditing(false); }
    else showToast(res.error || '保存失败', 'error');
  };

  const handleTestScan = async () => {
    if (!sKey) { showToast('请先填写扫描王 API Key', 'warning'); return; }
    setTestingScan(true);
    const res = await testScanConnection(sKey, sBase, sScene);
    setTestingScan(false);
    if (res.success && res.data) showToast(res.data.message, res.data.status === 'ok' ? 'success' : 'warning');
    else showToast(res.error || '连接失败', 'error');
  };

  const handleRefreshScenes = async () => {
    const res = await getScanScenes();
    if (res.success && res.data) {
      setScenes(res.data.scenes);
      showToast('场景列表已刷新', 'success');
    } else showToast(res.error || '刷新失败', 'error');
  };

  /* ---------- 助手记忆 ---------- */
  const handlePickDir = async () => {
    const res = await pickDirectory();
    if (res.success && res.data?.path) {
      setWorkDir(res.data.path);
      await saveSettings({ work_dir: res.data.path });
      showToast('文件存放位置已更新', 'success');
    } else showToast(res.error || '选择失败', 'error');
  };

  const handleAddFact = async () => {
    if (!factKey.trim() || !factVal.trim()) { showToast('请填写记忆键与记忆值', 'warning'); return; }
    const res = await addFact(factKey.trim(), factVal.trim(), factScope);
    if (res.success) {
      showToast('已记住', 'success');
      setFactKey(''); setFactVal('');
      loadMemory();
    } else showToast(res.error || '保存失败', 'error');
  };

  const startFactEdit = (f: AssistantFact) => {
    setEditingFactId(f.id);
    setEditFactKey(f.fact_key);
    setEditFactVal(f.fact_value);
    setEditFactScope(f.scope || 'memory');
  };

  const cancelFactEdit = () => {
    setEditingFactId(null);
    setEditFactKey(''); setEditFactVal(''); setEditFactScope('memory');
  };

  const saveFactEdit = async () => {
    if (editingFactId === null) return;
    if (!editFactKey.trim()) { showToast('记忆键不能为空', 'warning'); return; }
    const res = await updateFact(editingFactId, editFactKey.trim(), editFactVal.trim(), editFactScope);
    if (res.success) {
      showToast('记忆已更新', 'success');
      cancelFactEdit();
      loadMemory();
    } else showToast(res.error || '保存失败', 'error');
  };

  const removeFact = async (id: number) => {
    const res = await deleteFact(id);
    if (res.success) { showToast('已删除', 'success'); loadMemory(); }
    else showToast(res.error || '删除失败', 'error');
  };

  const inputRow = (label: string, value: string, set: (v: string) => void, placeholder = '', type = 'text', readOnly = false) => (
    <div className="set-row">
      <span className="k">{label}</span>
      <input type={type} style={{ flex: 1, minWidth: 180 }} placeholder={placeholder} value={value} readOnly={readOnly} onChange={(e) => set(e.target.value)} />
    </div>
  );

  const backupDetail = (
    <div className="bk-detail">
      <div className="bk-desc">备份内容（4 类，全在本机）：</div>
      <ul className="bk-list">
        <li><b>data.db</b> —— 全部业务数据：单据、审核状态、品名库、错误名映射、助手记忆、会话记录、校正日志</li>
        <li><b>uploads/</b> —— 全部上传原图</li>
        <li><b>.env</b> —— 软件配置（API 地址与密钥，请勿外发）</li>
        <li><b>备份说明.txt</b> —— 本次备份的说明清单</li>
      </ul>
      <pre className="bk-example">{`数字化工作台备份.zip
├── data.db            # 全部业务数据
├── uploads/           # 上传原图
│   ├── IMG_6051.jpg
│   └── …
├── .env               # 软件配置（含密钥，勿外发）
└── 备份说明.txt`}</pre>
      <div className="bk-note">再次点击「立即备份」，会把该文件更新到最新数据，不会堆积历史备份。</div>
    </div>
  );

  const panels: Record<string, { title: string; body: ReactNode }> = {
    engine: {
      title: '识别与模型',
      body: (
        <>
          <div className="set-card">
            <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
              <h3 style={{ margin: 0 }}>识别引擎</h3>
              <span style={{ flex: 1 }} />
              <button className="btn sm ghost" onClick={() => setEngineEditing(true)} disabled={engineEditing}>编辑</button>
              <button className="btn sm" onClick={handleSaveScan} disabled={!engineEditing}>保存</button>
            </div>
            <div className="desc">照片 → 表格提取；按场景计费，测试连接会消耗一次识别额度</div>
            {inputRow('API Key', sKey, setSKey, '请输入扫描王 API Key（Agent 接入密钥）', 'text', !engineEditing)}
            {inputRow('API 地址', sBase, setSBase, 'https://scan-business.quark.cn/vision', 'text', !engineEditing)}
            <div className="set-row">
              <span className="k">场景</span>
              <input list="scan-scenes" style={{ flex: 1, minWidth: 180 }} value={sScene} readOnly={!engineEditing} onChange={(e) => setSScene(e.target.value)} />
              <datalist id="scan-scenes">
                {scenes.map((sc) => <option key={sc.scene} value={sc.scene}>{sc.label}</option>)}
              </datalist>
            </div>
            <div className="set-row">
              <span className="k">操作</span>
              <span className="v" style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
                <button className="btn sm ghost" onClick={handleTestScan} disabled={testingScan}>{testingScan ? '测速中…' : '测试连接并测速'}</button>
                <button className="btn sm ghost" onClick={handleRefreshScenes}>刷新场景列表</button>
              </span>
            </div>
            {scenes.length > 0 && (
              <div style={{ fontSize: 12, color: 'var(--text-3)', marginTop: 4 }}>
                官方场景：{scenes.map((sc) => sc.label).join(' · ')}
              </div>
            )}
          </div>
          <div className="set-card">
            <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
              <h3 style={{ margin: 0 }}>工作助手 · 大模型</h3>
              <span style={{ flex: 1 }} />
              <button className="btn sm ghost" onClick={() => setAgentEditing(true)} disabled={agentEditing}>编辑</button>
              <button className="btn sm" onClick={handleSaveAgent} disabled={!agentEditing}>保存</button>
            </div>
            <div className="desc">本地自研 harness，OpenAI 兼容端点；模型列表来自该端点真实返回</div>
            {inputRow('API 地址', aBase, setABase, 'https://api.deepseek.com', 'text', !agentEditing)}
            {inputRow('API Key', aKey, setAKey, '请输入助手 API Key', 'text', !agentEditing)}
            <div className="set-row">
              <span className="k">模型</span>
              {aModels.length > 0 ? (
                <select style={{ flex: 1, minWidth: 180 }} value={aModel} disabled={!agentEditing} onChange={(e) => setAModel(e.target.value)}>
                  {aModels.map((m) => <option key={m.id} value={m.id}>{m.label}</option>)}
                </select>
              ) : (
                <input style={{ flex: 1, minWidth: 180 }} placeholder={aKey ? '输入模型名，或点「获取模型列表」' : '先填写 API Key'} value={aModel} readOnly={!agentEditing} onChange={(e) => setAModel(e.target.value)} />
              )}
            </div>
            <div className="set-row">
              <span className="k">操作</span>
              <span className="v" style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
                <button className="btn sm ghost" onClick={handleTestAgent} disabled={testingAgent}>{testingAgent ? '测试中…' : '测试连接并测速'}</button>
                <button className="btn sm ghost" onClick={handleFetchModels} disabled={fetchingModels}>{fetchingModels ? '获取中…' : '获取模型列表'}</button>
              </span>
            </div>
            {aModels.length > 0 && (
              <div style={{ fontSize: 12, color: 'var(--text-3)', marginTop: 4 }}>
                当前端点返回 {aModels.length} 个模型（真实列表）
              </div>
            )}
          </div>
        </>
      ),
    },
    memory: {
      title: 'Agent 记忆层',
      body: (
        <>
          <div className="set-card">
            <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
              <h3 style={{ margin: 0 }}>文件存放位置</h3>
              <span style={{ flex: 1 }} />
              <button className="btn sm ghost" onClick={handlePickDir}><FolderOpen size={14} />选择文件夹…</button>
            </div>
            <div className="desc">工作助手写入表格的位置，修改后立即生效</div>
            <div className="set-row">
              <span className="k">位置</span>
              <span className="v mono">{workDir || '未设置（首次生成对账单时选择）'}</span>
            </div>
            <div className="set-row">
              <span className="k">写入文件</span>
              <span className="v">生成时从此文件夹选择真实 Excel，或在此目录新建 · 只追加不覆盖 · 金额由代码计算</span>
            </div>
          </div>
          <div className="set-card">
            <div className="memory-headline"><div><h3>Agent 记忆层</h3><div className="desc">这里就是助手跨会话使用的长期记忆，不是普通备注。</div></div><span className="memory-badge">本机持久化</span></div>
            <div className="memory-explain"><b>记忆如何参与工作：</b>助手每次执行前会读取这里的事实；会话记录属于会话层，人工修正属于校正层，三者用途不同。</div>
            {facts.length === 0 && <div className="hint" style={{ fontSize: 12, color: 'var(--text-3)' }}>还没有记忆，写一条试试</div>}
            {facts.map((f) => (
              editingFactId === f.id ? (
                <div key={f.id} className="set-row memory-row">
                  <select value={editFactScope} onChange={(e) => setEditFactScope(e.target.value as 'memory' | 'user')} aria-label="记忆类型">
                    <option value="memory">工作事实</option><option value="user">用户偏好</option>
                  </select>
                  <input value={editFactKey} onChange={(e) => setEditFactKey(e.target.value)} style={{ flex: 1, minWidth: 100 }} placeholder="记忆键" />
                  <input value={editFactVal} onChange={(e) => setEditFactVal(e.target.value)} style={{ flex: 1, minWidth: 120 }} placeholder="记忆值" />
                  <button className="btn sm" onClick={saveFactEdit}>保存</button>
                  <button className="act" onClick={cancelFactEdit}>取消</button>
                </div>
              ) : (
                <div key={f.id} className="set-row memory-row">
                  <span className="k">{f.fact_key}</span>
                  <span className="v">{f.fact_value}</span>
                  <span className={`memory-scope ${f.scope || 'memory'}`}>{f.scope === 'user' ? '用户偏好' : '工作事实'}</span>
                  <button className="act" onClick={() => startFactEdit(f)}><Pencil size={13} style={{ verticalAlign: '-2px' }} />编辑</button>
                  <button className="act del" onClick={() => removeFact(f.id)}><Trash2 size={13} style={{ verticalAlign: '-2px' }} />删除</button>
                </div>
              )
            ))}
            <div className="memory-add-row">
              <select value={factScope} onChange={(e) => setFactScope(e.target.value as 'memory' | 'user')} aria-label="记忆类型">
                <option value="memory">工作事实</option><option value="user">用户偏好</option>
              </select>
              <input placeholder="记忆键，如：默认sheet" value={factKey} onChange={(e) => setFactKey(e.target.value)} style={{ flex: 1 }} />
              <input placeholder="记忆值，如：水电" value={factVal} onChange={(e) => setFactVal(e.target.value)} style={{ flex: 1 }} />
              <button className="btn sm" onClick={handleAddFact}>写入记忆</button>
            </div>
          </div>
        </>
      ),
    },
    about: {
      title: '关于',
      body: (
        <>
          <div className="set-card">
            <h3>数字化工作台</h3>
            <div className="set-row"><span className="k">版本</span><span className="v">{appVersion ? `v${appVersion}` : '桌面版（网页版无版本号）'}</span></div>
            <div className="set-row"><span className="k">数据</span><span className="v">全部在本机 SQLite，不上传云端</span></div>
            <div className="set-row"><span className="k">助手</span><span className="v">自研 harness · 技能文件化 · 三层记忆</span></div>
          </div>

          <div className="set-card">
            <h3>数据备份</h3>
            <div className="set-row">
              <span className="k">存放位置</span>
              <span className="v mono">{backupDir || '默认：用户数据目录 backups/'}</span>
              <button className="btn sm ghost" onClick={handlePickBackupDir}><FolderOpen size={14} />选择文件夹…</button>
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap', marginTop: 4 }}>
              <button className="btn" onClick={handleBackup} disabled={backingUp}>
                <Database size={15} />{backingUp ? '备份中…' : '立即备份'}
              </button>
              {backups.length > 0 && (
                <span style={{ fontSize: 12, color: 'var(--text-3)' }}>
                  最近更新：{backups[0].name} · {(backups[0].size / 1024 / 1024).toFixed(1)} MB · {backups[0].created_at}
                </span>
              )}
              <button className="link" style={{ marginLeft: 'auto' }} onClick={() => setShowBackupDetail((v) => !v)}>
                备份内容<ChevronDown size={13} style={{ verticalAlign: '-2px', transform: showBackupDetail ? 'rotate(180deg)' : 'none', transition: 'transform .2s' }} />
              </button>
            </div>
            {showBackupDetail && backupDetail}
          </div>

          <div className="set-card">
            <h3>软件更新</h3>
            <div className="upd-body">
              {upd.state === 'idle' && (
                <div className="upd-line">
                  <span className="v" style={{ color: 'var(--text-2)' }}>当前版本 v{appVersion} · 更新源 GitHub Releases</span>
                  <button className="btn sm" onClick={handleCheckUpdate}>检查更新</button>
                </div>
              )}
              {upd.state === 'checking' && (
                <div className="upd-line"><span className="live-spinner" />正在检查最新版本…</div>
              )}
              {upd.state === 'uptodate' && (
                <div className="upd-line">
                  <span className="upd-ok"><CheckCircle2 size={15} />已是最新版本</span>
                  <button className="link" onClick={handleCheckUpdate}>重新检查</button>
                </div>
              )}
              {upd.state === 'available' && (
                <div className="upd-line">
                  <span className="v" style={{ fontWeight: 600 }}>发现新版本 v{upd.version}</span>
                  <button className="btn sm" onClick={handleDownloadUpdate}>立即下载</button>
                </div>
              )}
              {upd.state === 'downloading' && (
                <div className="upd-line">
                  <div className="upd-progress"><i style={{ width: `${upd.percent}%` }} /></div>
                  <span className="v" style={{ color: 'var(--text-2)' }}>正在下载 {upd.percent}%</span>
                </div>
              )}
              {upd.state === 'downloaded' && (
                <div className="upd-line">
                  <span className="upd-ok"><CheckCircle2 size={15} />更新已下载完成</span>
                  <button className="btn sm" onClick={handleInstallUpdate}>立即重启安装</button>
                </div>
              )}
              {upd.state === 'error' && (
                <div className="upd-line" style={{ flexDirection: 'column', alignItems: 'flex-start', gap: 6 }}>
                  <span style={{ color: 'var(--err)' }}>{upd.message}</span>
                  <span style={{ fontSize: 12, color: 'var(--text-2)' }}>
                    若网络失败，可到 <a href="https://github.com/Liberty-26/-/releases/latest" target="_blank" rel="noreferrer" style={{ color: 'var(--primary)' }}>下载页</a> 手动获取安装包；Mac 未签名时也请手动安装 dmg
                  </span>
                  <button className="link" onClick={handleCheckUpdate}><RefreshCw size={13} style={{ verticalAlign: '-2px' }} />重试</button>
                </div>
              )}
            </div>
          </div>
        </>
      ),
    },
  };

  const cur = panels[panel];

  return (
    <div className="plain">
      <div className="page-head">
        <div>
          <div className="page-title">设置</div>
          <div className="page-sub">
            {panel === 'engine' && '识别引擎（扫描王）与工作助手（大模型）的真实 API 配置'}
            {panel === 'memory' && 'Agent 记忆层与表格工作目录，全部存在本机'}
            {panel === 'about' && '版本、数据备份与软件更新'}
          </div>
        </div>
      </div>
      <div className="set-layout">
        <div className="set-nav">
          {Object.entries(panels).map(([k, p]) => (
            <button key={k} className={`nav-item ${panel === k ? 'active' : ''}`} onClick={() => setPanel(k)}>{p.title}</button>
          ))}
        </div>
        <div className="set-panel">
          {cur.body}
        </div>
      </div>
    </div>
  );
}
