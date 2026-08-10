// SteelDigitize Pro — 设置中心（识别引擎 / 工作助手 / 对账单 / 助手记忆 / 关于）
import { useCallback, useEffect, useState, type ReactNode } from 'react';
import { useToast } from '../hooks/useToast';
import {
  getSettings, saveSettings, getScanScenes, testScanConnection,
  getFacts, addFact, deleteFact, getCorrections, deleteCorrection, clearCorrections,
  exportBackup, getBackups,
} from '../utils/api';
import ConfirmDialog from '../components/ConfirmDialog';
import type { AssistantFact, CorrectionRecord } from '../types';

const S = { aKey: 'steel_agent_key', aBase: 'steel_agent_base', aModel: 'steel_agent_model', sKey: 'steel_scan_key' };
import { CheckCircle2 } from 'lucide-react';

interface ScanScene { scene: string; label: string; type: string }

// 训练数据图表（lieflat-charts 模板语法：F1 梯档柱 / F2 发丝折线）
const INK = '#1C1C1A';
const MUTED = '#8A8983';
const GRID = '#D8D7D1';
const FAINT = '#B0AFA9';
const FIELD_LABEL: Record<string, string> = { name: '品名', spec: '规格', unit: '单位', qty: '数量', price: '单价' };

function TrainingCharts({ corrections }: { corrections: { field: string; before_val: string; after_val: string; created_at?: string }[] }) {
  // F5 · Tick Rows：字段分布，1 tick = 1 次修正（横排，类目名左对齐）
  const fields = (['name', 'spec', 'unit', 'qty', 'price'] as const)
    .map((f) => ({ f, n: corrections.filter((c) => c.field === f).length }))
    .filter((x) => x.n > 0);

  // F2 · Hairline Line：近 7 天修正趋势
  const days: { label: string; n: number; key: string }[] = [];
  const now = new Date();
  for (let i = 6; i >= 0; i--) {
    const d = new Date(now.getFullYear(), now.getMonth(), now.getDate() - i);
    const key = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
    days.push({ label: `${String(d.getMonth() + 1)}-${String(d.getDate()).padStart(2, '0')}`, key, n: 0 });
  }
  corrections.forEach((c) => {
    const k = (c.created_at || '').slice(0, 10);
    const hit = days.find((x) => x.key === k);
    if (hit) hit.n += 1;
  });
  const maxDay = Math.max(1, ...days.map((x) => x.n));

  const W = 400, H = 150;
  const rowY = (i: number) => 16 + i * 24;
  const TICK_X0 = 104, TICK_PX = 6;

  return (
    <div className="td-charts">
      <div className="td-chart">
        <div className="td-chart-title">哪类最容易改错</div>
        <div className="td-chart-sub">1 tick = 1 次人工修正 · 行尾大数</div>
        <svg viewBox={`0 0 ${W} ${H}`} style={{ width: '100%', height: 150 }}>
          {fields.map((x, i) => {
            const y = rowY(i);
            const ticks = Math.min(x.n, 26);
            return (
              <g key={x.f}>
                <text x={94} y={y + 3} fontSize={9} fontWeight={700} fill="#6A6963" textAnchor="end" letterSpacing="0.04em">
                  {FIELD_LABEL[x.f] || x.f}
                </text>
                <line x1={TICK_X0} y1={y + 10} x2={TICK_X0 + 34 * TICK_PX} y2={y + 10} stroke={GRID} strokeWidth={0.6} />
                {Array.from({ length: ticks }, (_, k) => (
                  <line
                    key={k}
                    x1={TICK_X0 + k * TICK_PX + TICK_PX / 2}
                    x2={TICK_X0 + k * TICK_PX + TICK_PX / 2}
                    y1={y + 10}
                    y2={y + 1}
                    stroke={INK}
                    strokeWidth={0.9}
                    opacity={0.55 + (k % 3) * 0.15}
                  />
                ))}
                <text x={TICK_X0 + x.n * TICK_PX + 10} y={y + 4} fontSize={11} fontWeight={800} fill={INK}>
                  {x.n}
                </text>
              </g>
            );
          })}
          {fields.length === 0 && (
            <text x={200} y={70} fontSize={11} fill={FAINT} textAnchor="middle">暂无数据</text>
          )}
        </svg>
        <div className="td-chart-src">ONE TICK = ONE CORRECTION · 累计 {corrections.length} 条修正</div>
      </div>

      <div className="td-chart">
        <div className="td-chart-title">近 7 天修正趋势</div>
        <div className="td-chart-sub">1 点 = 1 天 · 发丝折线 = 修正量变化</div>
        <svg viewBox={`0 0 ${W} ${H}`} style={{ width: '100%', height: 150 }}>
          {days.map((_, i) => {
            const x = 26 + i * 58;
            return <line key={i} x1={x} y1={118} x2={x} y2={111} stroke="#CFCEC7" strokeWidth={0.6} />;
          })}
          <line x1={20} y1={118} x2={W - 20} y2={118} stroke={GRID} strokeWidth={0.8} />
          {(() => {
            const pts = days.map((d, i) => `${26 + i * 58} ${118 - (d.n / maxDay) * 78}`).join(' L ');
            return <path d={`M${pts}`} fill="none" stroke={INK} strokeWidth={1} />;
          })()}
          {days.map((d, i) => {
            const x = 26 + i * 58;
            const y = 118 - (d.n / maxDay) * 78;
            const peak = d.n > 0 && d.n === maxDay;
            return (
              <g key={i}>
                <circle cx={x} cy={y} r={d.n === 0 ? 1.6 : peak ? 4 : 2.2} fill={d.n === 0 ? '#fff' : INK} stroke={INK} strokeWidth={d.n === 0 ? 1 : 0} />
                {peak && <text x={x} y={y - 9} fontSize={9} fontWeight={800} fill={INK} textAnchor="middle">{d.n}</text>}
                <text x={x} y={136} fontSize={7.5} fontWeight={600} fill={MUTED} textAnchor="middle" letterSpacing="0.06em">{d.label}</text>
              </g>
            );
          })}
        </svg>
        <div className="td-chart-src">LAST 7 DAYS · 实心 = 有修正 · 空心 = 无</div>
      </div>
    </div>
  );
}

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
  const [workDir, setWorkDir] = useState('');
  const [facts, setFacts] = useState<AssistantFact[]>([]);
  const [corrections, setCorrections] = useState<CorrectionRecord[]>([]);
  const [factKey, setFactKey] = useState('');
  const [factVal, setFactVal] = useState('');
  const [clearOpen, setClearOpen] = useState(false);
  const [appVersion, setAppVersion] = useState('');
  const [backups, setBackups] = useState<{ name: string; size: number; created_at: string }[]>([]);
  const [backingUp, setBackingUp] = useState(false);

  // 桌面端自动更新状态
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
      showToast('备份完成：' + res.data.path, 'success');
      refreshBackups();
    } else {
      showToast(res.error || '备份失败', 'error');
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
    getCorrections(500).then((r) => { if (r.success && r.data) setCorrections(r.data.corrections); });
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

  const handlePickDir = async () => {
    const r = await fetch('/api/settings/pick-dir');
    const j = await r.json();
    if (j.success && j.data?.path) {
      setWorkDir(j.data.path);
      await saveSettings({ work_dir: j.data.path });
      showToast('工作目录已更新', 'success');
    } else showToast(j.error || '选择失败', 'error');
  };

  const handleAddFact = async () => {
    if (!factKey.trim() || !factVal.trim()) { showToast('请填写事实键与值', 'warning'); return; }
    const res = await addFact(factKey.trim(), factVal.trim());
    if (res.success) {
      showToast('已记住', 'success');
      setFactKey(''); setFactVal('');
      loadMemory();
    } else showToast(res.error || '保存失败', 'error');
  };

  const inputRow = (label: string, value: string, set: (v: string) => void, placeholder = '', type = 'text', readOnly = false) => (
    <div className="set-row">
      <span className="k">{label}</span>
      <input type={type} style={{ flex: 1, minWidth: 180 }} placeholder={placeholder} value={value} readOnly={readOnly} onChange={(e) => set(e.target.value)} />
    </div>
  );

  const panels: Record<string, { title: string; desc: string; body: ReactNode }> = {
    engine: {
      title: '识别与模型',
      desc: '识别引擎（扫描王）与工作助手（大模型）的真实 API 配置',
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
    excel: {
      title: '对账单',
      desc: '工作助手写入的 Excel 文件与规则',
      body: (
        <div className="set-card">
          <h3>对账单</h3>
          <div className="set-row"><span className="k">文件</span><span className="v">{workDir ? workDir + '/对账单.xlsx' : '未设置（新建时选择）'}</span></div>
          <div className="set-row"><span className="k">默认 sheet</span><span className="v">水电</span></div>
          <div className="set-row"><span className="k">工作目录</span><span className="v">{workDir || '未设置'}</span><button className="act" onClick={handlePickDir}>选择目录</button></div>
          <div className="set-row"><span className="k">写入规则</span><span className="v">只追加不覆盖 · 写入后自动验证 · 金额由代码计算</span></div>
        </div>
      ),
    },
    memory: {
      title: '助手记忆',
      desc: '三层记忆：会话 / 事实 / 校正记录，全部在本机，可查看可删除',
      body: (
        <>
          <div className="set-card">
            <h3>事实层（助手记住的事）</h3>
            <div className="desc">跨会话保留的偏好与约定</div>
            {facts.length === 0 && <div className="hint" style={{ fontSize: 12, color: 'var(--text-3)' }}>还没有记录</div>}
            {facts.map((f) => (
              <div key={f.id} className="set-row">
                <span className="k">{f.fact_key}</span>
                <span className="v">{f.fact_value}</span>
                <button className="act" style={{ color: 'var(--err)' }} onClick={async () => { await deleteFact(f.id); loadMemory(); }}>删除</button>
              </div>
            ))}
            <div className="set-row">
              <input placeholder="事实键，如：默认sheet" value={factKey} onChange={(e) => setFactKey(e.target.value)} style={{ flex: 1 }} />
              <input placeholder="事实值，如：水电" value={factVal} onChange={(e) => setFactVal(e.target.value)} style={{ flex: 1 }} />
              <button className="btn sm" onClick={handleAddFact}>记住</button>
            </div>
          </div>
          <div className="set-card">
            <h3>训练数据（校正记录）</h3>
            <div className="desc">审核区每次人工修改都会记录「识别结果 → 人工修正」，用于生成错误名规则</div>
            {corrections.length === 0 && <div style={{ fontSize: 12, color: 'var(--text-3)' }}>暂无训练数据：在审核区修改识别结果后，会自动在这里积累</div>}
            {corrections.length > 0 && (
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap', marginBottom: 8 }}>
                <span className="pill gray">共 {corrections.length} 条</span>
                {(['name', 'spec', 'unit', 'qty', 'price'] as const).map((f) => {
                  const n = corrections.filter((c) => c.field === f).length;
                  return n > 0 ? <span key={f} className={`pill ${f === 'name' ? 'amber' : 'blue'}`}>{f} × {n}</span> : null;
                })}
              </div>
            )}
            <TrainingCharts corrections={corrections} />
            {corrections.map((c) => (
              <div key={c.id} className="mem-item">
                <span className="badge">{c.field}</span>
                <span className="num" style={{ color: 'var(--text-2)', fontSize: 12 }}>{c.receipt_no || '—'}</span>
                <span style={{ textDecoration: 'line-through', color: 'var(--text-2)' }}>{c.before_val || '（空）'}</span>
                <span className="arrow">→</span>
                <span style={{ color: 'var(--ok)' }}>{c.after_val || '（空）'}</span>
                <span style={{ fontSize: 11, color: 'var(--text-3)', marginLeft: 'auto' }}>{(c.created_at || '').slice(5, 16)}</span>
                <button className="act del" onClick={async () => { await deleteCorrection(c.id); loadMemory(); }}>删除</button>
              </div>
            ))}
            {corrections.length > 0 && (
              <div className="danger-zone" style={{ marginTop: 8 }}>
                <div><div className="d-title">清空训练数据</div><div className="d-sub">删除全部校正记录，业务数据不受影响</div></div>
                <button className="btn danger sm" style={{ marginLeft: 'auto' }} onClick={() => setClearOpen(true)}>清空</button>
              </div>
            )}
          </div>
        </>
      ),
    },
    about: {
      title: '关于',
      desc: '版本与数据',
      body: (
        <div className="set-card">
          <h3>关于 数字化工作台</h3>
          <div className="set-row"><span className="k">版本</span><span className="v">{appVersion ? `v${appVersion}` : '桌面版（网页版无版本号）'}</span></div>
          <div className="set-row"><span className="k">数据</span><span className="v">全部在本机 SQLite，不上传云端</span></div>
          <div className="set-row"><span className="k">识别</span><span className="v">夸克扫描王 image-to-excel</span></div>
          <div className="set-row"><span className="k">助手</span><span className="v">自研 harness · 技能文件化 · 三层记忆</span></div>
          <div style={{ marginTop: 14, paddingTop: 14, borderTop: '1px solid var(--border)' }}>
            <div style={{ fontSize: 12, color: 'var(--text-2)', marginBottom: 10 }}>数据备份</div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
              <button className="btn sm" onClick={handleBackup} disabled={backingUp}>
                {backingUp ? '备份中…' : '立即备份'}
              </button>
              {backups.length > 0 && (
                <span style={{ fontSize: 12, color: 'var(--text-3)' }}>
                  最近：{backups[0].name}（{backups[0].created_at}）
                </span>
              )}
            </div>
            {backups.length > 1 && (
              <div style={{ marginTop: 8, fontSize: 12, color: 'var(--text-3)' }}>
                共 {backups.length} 份：{backups.slice(1).map((b) => b.name).join('、')}
              </div>
            )}
          </div>
          <div style={{ marginTop: 14, paddingTop: 14, borderTop: '1px solid var(--border)' }}>
            <div style={{ fontSize: 12, color: 'var(--text-2)', marginBottom: 10 }}>软件更新</div>
            {upd.state === 'idle' && (
              <button className="btn" onClick={handleCheckUpdate}>检查更新</button>
            )}
            {upd.state === 'checking' && (
              <button className="btn" disabled>检查中…</button>
            )}
            {upd.state === 'uptodate' && (
              <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
                <span style={{ fontSize: 13, color: 'var(--green, #34c77b)' }}><CheckCircle2 size={14} style={{ verticalAlign: '-2px' }} /> 已是最新版本</span>
                <button className="link" onClick={handleCheckUpdate}>重新检查</button>
              </div>
            )}
            {upd.state === 'available' && (
              <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
                <span style={{ fontSize: 13, color: 'var(--primary)' }}>发现新版本 v{upd.version}</span>
                <button className="btn sm" onClick={handleDownloadUpdate}>立即下载</button>
              </div>
            )}
            {upd.state === 'downloading' && (
              <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                <div style={{ flex: 1, height: 6, background: 'var(--border)', borderRadius: 999, overflow: 'hidden', maxWidth: 220 }}>
                  <i style={{ display: 'block', height: '100%', width: `${upd.percent}%`, background: 'var(--primary)', transition: 'width .3s' }} />
                </div>
                <span style={{ fontSize: 12, color: 'var(--text-2)' }}>{upd.percent}%</span>
              </div>
            )}
            {upd.state === 'downloaded' && (
              <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
                <span style={{ fontSize: 13, color: 'var(--green, #34c77b)' }}>更新已下载完成</span>
                <button className="btn sm" onClick={handleInstallUpdate}>立即重启安装</button>
              </div>
            )}
            {upd.state === 'error' && (
              <div style={{ fontSize: 12, color: 'var(--err)' }}>
                <div>{upd.message}</div>
                <div style={{ marginTop: 6, color: 'var(--text-2)' }}>
                  若提示网络连接失败，可到 <a href="https://github.com/Liberty-26/-/releases/latest" target="_blank" rel="noreferrer" style={{ color: 'var(--primary)' }}>下载页</a> 手动获取最新安装包
                </div>
                <button className="link" style={{ marginTop: 4 }} onClick={handleCheckUpdate}>重试</button>
              </div>
            )}
          </div>
        </div>
      ),
    },
  };

  const cur = panels[panel];

  return (
    <div className="plain">
      <div className="page-head">
        <div>
          <div className="page-title">设置</div>
          <div className="page-sub">识别、模型、对账单与助手记忆，全部存在本机</div>
        </div>
      </div>
      <div className="set-layout">
        <div className="set-nav">
          {Object.entries(panels).map(([k, p]) => (
            <button key={k} className={`nav-item ${panel === k ? 'active' : ''}`} onClick={() => setPanel(k)}>{p.title}</button>
          ))}
        </div>
        <div className="set-panel">
          <div className="page-sub" style={{ fontSize: 13 }}>{cur.desc}</div>
          {cur.body}
        </div>
      </div>

      <ConfirmDialog
        open={clearOpen}
        title="清空校正记录"
        message="确定清空全部纠正记录？"
        onConfirm={async () => { await clearCorrections(); setClearOpen(false); loadMemory(); showToast('已清空', 'success'); }}
        onCancel={() => setClearOpen(false)}
      />
    </div>
  );
}
