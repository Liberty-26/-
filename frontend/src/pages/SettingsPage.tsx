// SteelDigitize Pro — 设置中心（识别引擎 / 工作助手 / 对账单 / 助手记忆 / 关于）
import { useCallback, useEffect, useState, type ReactNode } from 'react';
import { useToast } from '../hooks/useToast';
import {
  getSettings, saveSettings, getScanScenes, testScanConnection,
  getFacts, addFact, deleteFact, getCorrections, deleteCorrection, clearCorrections,
} from '../utils/api';
import ConfirmDialog from '../components/ConfirmDialog';
import type { AssistantFact, CorrectionRecord } from '../types';

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

  const [masked, setMasked] = useState<{ agent_key: string; scan_key: string }>({ agent_key: '', scan_key: '' });
  const [workDir, setWorkDir] = useState('');
  const [facts, setFacts] = useState<AssistantFact[]>([]);
  const [corrections, setCorrections] = useState<CorrectionRecord[]>([]);
  const [factKey, setFactKey] = useState('');
  const [factVal, setFactVal] = useState('');
  const [clearOpen, setClearOpen] = useState(false);

  useEffect(() => {
    const saved = (k: string) => localStorage.getItem(k) || '';
    setAKey(saved(S.aKey));
    setABase(saved(S.aBase) || 'https://api.deepseek.com');
    setAModel(saved(S.aModel));
    setSKey(saved(S.sKey));
    getSettings().then((res) => {
      if (res.success && res.data) {
        const d = res.data;
        setMasked({ agent_key: d.agent_api_key || '', scan_key: d.scan_api_key || '' });
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
    getCorrections().then((r) => { if (r.success && r.data) setCorrections(r.data.corrections); });
  }, []);

  useEffect(() => { if (panel === 'memory') loadMemory(); }, [panel, loadMemory]);

  /* ---------- 工作助手 ---------- */
  const handleSaveAgent = async () => {
    const res = await saveSettings({ agent_key: aKey, agent_base: aBase, agent_model: aModel });
    if (aKey) localStorage.setItem(S.aKey, aKey);
    localStorage.setItem(S.aBase, aBase);
    localStorage.setItem(S.aModel, aModel);
    if (res.success) showToast('助手配置已保存', 'success');
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
    if (sKey) localStorage.setItem(S.sKey, sKey);
    if (res.success) showToast('识别引擎配置已保存', 'success');
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

  const inputRow = (label: string, value: string, set: (v: string) => void, placeholder = '', type = 'text') => (
    <div className="set-row">
      <span className="k">{label}</span>
      <input type={type} style={{ flex: 1, minWidth: 180 }} placeholder={placeholder} value={value} onChange={(e) => set(e.target.value)} />
    </div>
  );

  const panels: Record<string, { title: string; desc: string; body: ReactNode }> = {
    engine: {
      title: '识别与模型',
      desc: '识别引擎（扫描王）与工作助手（大模型）的真实 API 配置',
      body: (
        <>
          <div className="set-card">
            <h3>识别引擎 · 夸克扫描王</h3>
            <div className="desc">照片 → 表格提取；按场景计费，测试连接会消耗一次识别额度</div>
            {inputRow('API Key', sKey, setSKey, masked.scan_key ? `已配置（${masked.scan_key}），留空不修改` : 'aiApiKey', 'password')}
            {inputRow('API 地址', sBase, setSBase, 'https://scan-business.quark.cn/vision')}
            <div className="set-row">
              <span className="k">场景</span>
              <input list="scan-scenes" style={{ flex: 1, minWidth: 180 }} value={sScene} onChange={(e) => setSScene(e.target.value)} />
              <datalist id="scan-scenes">
                {scenes.map((sc) => <option key={sc.scene} value={sc.scene}>{sc.label}</option>)}
              </datalist>
            </div>
            <div className="set-row">
              <span className="k">操作</span>
              <span className="v" style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
                <button className="btn sm" onClick={handleSaveScan}>保存配置</button>
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
            <h3>工作助手 · 大模型</h3>
            <div className="desc">本地自研 harness，OpenAI 兼容端点；模型列表来自该端点真实返回</div>
            {inputRow('API 地址', aBase, setABase, 'https://api.deepseek.com')}
            {inputRow('API Key', aKey, setAKey, masked.agent_key ? `已配置（${masked.agent_key}），留空不修改` : 'sk-...', 'password')}
            <div className="set-row">
              <span className="k">模型</span>
              {aModels.length > 0 ? (
                <select style={{ flex: 1, minWidth: 180 }} value={aModel} onChange={(e) => setAModel(e.target.value)}>
                  {aModels.map((m) => <option key={m.id} value={m.id}>{m.label}</option>)}
                </select>
              ) : (
                <input style={{ flex: 1, minWidth: 180 }} placeholder={aKey ? '输入模型名，或点「获取模型列表」' : '先填写 API Key'} value={aModel} onChange={(e) => setAModel(e.target.value)} />
              )}
            </div>
            <div className="set-row">
              <span className="k">操作</span>
              <span className="v" style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
                <button className="btn sm" onClick={handleSaveAgent}>保存配置</button>
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
            <h3>校正层（纠正记录）</h3>
            <div className="desc">每次人工修改识别结果都会记录，用于以后识别得更准</div>
            {corrections.length === 0 && <div style={{ fontSize: 12, color: 'var(--text-3)' }}>还没有纠正记录</div>}
            {corrections.map((c) => (
              <div key={c.id} className="mem-item">
                <span className="num" style={{ color: 'var(--text-2)' }}>{c.receipt_no || '—'}</span>
                <span className="from" style={{ textDecoration: 'line-through', color: 'var(--text-2)' }}>{c.before_val}</span>
                <span className="arrow">→</span>
                <span>{c.after_val}</span>
                <span className="badge">{c.field}</span>
                <button className="act del" onClick={async () => { await deleteCorrection(c.id); loadMemory(); }}>删除</button>
              </div>
            ))}
            {corrections.length > 0 && (
              <div className="danger-zone" style={{ marginTop: 8 }}>
                <div><div className="d-title">清空校正记录</div><div className="d-sub">删除全部纠正记录，业务数据不受影响</div></div>
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
          <h3>关于 SteelDigitize Pro</h3>
          <div className="set-row"><span className="k">版本</span><span className="v">0.9 MVP（工作台重塑版）</span></div>
          <div className="set-row"><span className="k">数据</span><span className="v">全部在本机 SQLite，不上传云端</span></div>
          <div className="set-row"><span className="k">识别</span><span className="v">夸克扫描王 image-to-excel</span></div>
          <div className="set-row"><span className="k">助手</span><span className="v">自研 harness · 技能文件化 · 三层记忆</span></div>
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
