// SteelDigitize Pro — 配置页（模型选择器 + 工作目录）
import { useState, useEffect } from 'react';
import { useToast } from '../hooks/useToast';

const S = {
  vKey: 'steel_vision_key', vBase: 'steel_vision_base', vModel: 'steel_vision_model', vModels: 'steel_vision_models',
  aKey: 'steel_agent_key', aBase: 'steel_agent_base', aModel: 'steel_agent_model', aModels: 'steel_agent_models',
  workDir: 'steel_work_dir',
};

type ModelInfo = { id: string; label: string };

async function api<T>(path: string, body?: Record<string, unknown>): Promise<{ success: boolean; data?: T; error?: string }> {
  const r = await fetch('/api/settings' + path, {
    method: body ? 'POST' : 'GET',
    headers: body ? { 'Content-Type': 'application/json' } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  });
  const j = await r.json();
  if (!r.ok) return { success: false, error: j.detail || 'HTTP ' + r.status };
  return j;
}

export default function SettingsPage() {
  const { showToast } = useToast();
  const [vKey, setVKey] = useState('');
  const [vBase, setVBase] = useState('https://dashscope.aliyuncs.com/compatible-mode/v1');
  const [vModel, setVModel] = useState('');
  const [vModels, setVModels] = useState<ModelInfo[]>([]);
  const [aKey, setAKey] = useState('');
  const [aBase, setABase] = useState('https://api.deepseek.com');
  const [aModel, setAModel] = useState('');
  const [aModels, setAModels] = useState<ModelInfo[]>([]);
  const [workDir, setWorkDir] = useState('');
  const [fetching, setFetching] = useState<'vision' | 'agent' | null>(null);

  useEffect(() => {
    const saved = (k: string) => localStorage.getItem(k) || '';
    setVKey(saved(S.vKey)); setVBase(saved(S.vBase) || 'https://dashscope.aliyuncs.com/compatible-mode/v1'); setVModel(saved(S.vModel));
    setAKey(saved(S.aKey)); setABase(saved(S.aBase) || 'https://api.deepseek.com'); setAModel(saved(S.aModel));
    setWorkDir(saved(S.workDir) || '');
    // 恢复模型列表（持久化）
    try {
      const vm = localStorage.getItem(S.vModels);
      if (vm) setVModels(JSON.parse(vm));
      const am = localStorage.getItem(S.aModels);
      if (am) setAModels(JSON.parse(am));
    } catch { /* JSON 损坏忽略 */ }
    // 从后端拉权威配置
    (async () => {
      const res = await api<{ work_dir: string }>('');
      if (res.success && res.data?.work_dir) setWorkDir(res.data.work_dir);
    })();
  }, []);

  const save = (k: string, v: string) => { localStorage.setItem(k, v); };

  // 拉取模型列表（只来自 API 真实返回，禁止硬编码）
  const fetchModels = async (type: 'vision' | 'agent') => {
    const apiKey = type === 'vision' ? vKey : aKey;
    const apiBase = type === 'vision' ? vBase : aBase;
    if (!apiKey) { showToast('请先输入 API Key', 'error'); return; }
    setFetching(type);
    const res = await api<{ models: ModelInfo[] }>('/fetch-models', { api_base: apiBase, api_key: apiKey });
    setFetching(null);
    if (res.success && res.data?.models) {
      if (type === 'vision') { setVModels(res.data.models); localStorage.setItem(S.vModels, JSON.stringify(res.data.models)); }
      else { setAModels(res.data.models); localStorage.setItem(S.aModels, JSON.stringify(res.data.models)); }
      showToast('模型列表已获取', 'success');
    } else {
      showToast(res.error || '获取模型列表失败', 'error');
    }
  };

  // 测试连接
  const testConn = async (type: 'vision' | 'agent') => {
    const apiKey = type === 'vision' ? vKey : aKey;
    const apiBase = type === 'vision' ? vBase : aBase;
    const model = type === 'vision' ? vModel : aModel;
    if (!apiKey) { showToast('请先输入 API Key', 'error'); return; }
    if (!model) { showToast('请先选择或输入模型', 'error'); return; }
    const res = await api<{ latency_ms: number }>(type === 'vision' ? '/test-vision' : '/test-agent', {
      api_base: apiBase, api_key: apiKey, model,
    });
    if (res.success && res.data) showToast(`连接成功（${model}），耗时 ${res.data.latency_ms}ms`, 'success');
    else showToast(res.error || '连接失败', 'error');
  };

  // 选择工作目录
  const handlePickDir = async () => {
    const res = await api<{ path: string }>('/pick-dir');
    if (res.success && res.data?.path) { setWorkDir(res.data.path); save(S.workDir, res.data.path); }
    else if (!res.success) showToast(res.error || '选择失败', 'error');
  };

  const handleSave = async () => {
    [vKey, vBase, vModel, aKey, aBase, aModel, workDir].forEach((v, i) => {
      const k = [S.vKey, S.vBase, S.vModel, S.aKey, S.aBase, S.aModel, S.workDir][i];
      if (v) save(k, v);
    });
    await api('', { vision_key: vKey, vision_base: vBase, vision_model: vModel, agent_key: aKey, agent_base: aBase, agent_model: aModel, work_dir: workDir });
    showToast('配置保存成功', 'success');
  };

  return (
    <div className="h-full overflow-y-auto">
      <div className="p-margin-page max-w-xl mx-auto space-y-6 pb-24">
        <div className="flex items-center justify-between">
          <h2 className="font-headline-md text-headline-md text-on-surface">API 与模型配置</h2>
          <button onClick={handleSave} className="bg-primary text-white px-6 py-2 rounded-lg font-semibold text-label-sm hover:bg-primary-container">保存配置到后端</button>
        </div>

        {/* 识图模型 */}
        <section className="bg-surface-container-lowest border border-outline-variant rounded-xl p-5">
          <h3 className="font-headline-md text-on-surface mb-4">识图模型</h3>
          <div className="space-y-3">
            <div><label className="block text-label-sm text-on-surface-variant mb-1">API 地址</label><input type="text" value={vBase} onChange={e => setVBase(e.target.value)} className="w-full bg-white border border-outline-variant rounded-lg px-3 py-2 text-body-md" /></div>
            <div><label className="block text-label-sm text-on-surface-variant mb-1">API Key</label><input type="password" value={vKey} onChange={e => { setVKey(e.target.value); save(S.vKey, e.target.value); }} placeholder="sk-..." className="w-full bg-white border border-outline-variant rounded-lg px-3 py-2 text-body-md" /></div>
            <div>
              <label className="block text-label-sm text-on-surface-variant mb-1">模型</label>
              {vModels.length > 0 ? (
                <select value={vModel} onChange={e => { setVModel(e.target.value); save(S.vModel, e.target.value); }} className="w-full bg-white border border-outline-variant rounded-lg px-3 py-2 text-body-md">
                  {vModels.map(m => <option key={m.id} value={m.id}>{m.label}</option>)}
                </select>
              ) : (
                <div className="flex gap-2">
                  <input type="text" value={vModel} onChange={e => { setVModel(e.target.value); save(S.vModel, e.target.value); }}
                    placeholder={vKey ? '输入模型名 或 点击获取列表' : '请先输入 API Key'}
                    className="flex-1 bg-white border border-outline-variant rounded-lg px-3 py-2 text-body-md focus:border-primary" />
                  {vKey && (
                    <button onClick={() => fetchModels('vision')} disabled={fetching === 'vision'}
                      className="px-3 py-2 text-label-sm border border-outline-variant rounded-lg hover:bg-surface-container-low whitespace-nowrap disabled:opacity-50">
                      {fetching === 'vision' ? '获取中...' : '获取模型列表'}
                    </button>
                  )}
                </div>
              )}
            </div>
            <div className="flex items-center gap-3">
              <button onClick={() => testConn('vision')} className="px-4 py-2 text-label-sm border border-outline-variant rounded-lg hover:bg-surface-container-low">测试连接</button>
            </div>
          </div>
        </section>

        {/* Agent 模型 */}
        <section className="bg-surface-container-lowest border border-outline-variant rounded-xl p-5">
          <h3 className="font-headline-md text-on-surface mb-4">Agent 模型</h3>
          <div className="space-y-3">
            <div><label className="block text-label-sm text-on-surface-variant mb-1">API 地址</label><input type="text" value={aBase} onChange={e => setABase(e.target.value)} className="w-full bg-white border border-outline-variant rounded-lg px-3 py-2 text-body-md" /></div>
            <div><label className="block text-label-sm text-on-surface-variant mb-1">API Key</label><input type="password" value={aKey} onChange={e => { setAKey(e.target.value); save(S.aKey, e.target.value); }} placeholder="sk-..." className="w-full bg-white border border-outline-variant rounded-lg px-3 py-2 text-body-md" /></div>
            <div>
              <label className="block text-label-sm text-on-surface-variant mb-1">模型</label>
              {aModels.length > 0 ? (
                <select value={aModel} onChange={e => { setAModel(e.target.value); save(S.aModel, e.target.value); }} className="w-full bg-white border border-outline-variant rounded-lg px-3 py-2 text-body-md">
                  {aModels.map(m => <option key={m.id} value={m.id}>{m.label}</option>)}
                </select>
              ) : (
                <div className="flex gap-2">
                  <input type="text" value={aModel} onChange={e => { setAModel(e.target.value); save(S.aModel, e.target.value); }}
                    placeholder={aKey ? '输入模型名 或 点击获取列表' : '请先输入 API Key'}
                    className="flex-1 bg-white border border-outline-variant rounded-lg px-3 py-2 text-body-md focus:border-primary" />
                  {aKey && (
                    <button onClick={() => fetchModels('agent')} disabled={fetching === 'agent'}
                      className="px-3 py-2 text-label-sm border border-outline-variant rounded-lg hover:bg-surface-container-low whitespace-nowrap disabled:opacity-50">
                      {fetching === 'agent' ? '获取中...' : '获取模型列表'}
                    </button>
                  )}
                </div>
              )}
            </div>
            <div className="flex items-center gap-3">
              <button onClick={() => testConn('agent')} className="px-4 py-2 text-label-sm border border-outline-variant rounded-lg hover:bg-surface-container-low">测试连接</button>
            </div>
          </div>
        </section>

        {/* 文件存放路径（工作目录） */}
        <section className="bg-surface-container-lowest border border-outline-variant rounded-xl p-5">
          <h3 className="font-headline-md text-on-surface mb-4">文件存放路径（工作目录）</h3>
          <div className="space-y-3">
            <div>
              <label className="block text-label-sm text-on-surface-variant mb-1">目录</label>
              <div className="flex gap-2">
                <input type="text" value={workDir} onChange={e => { setWorkDir(e.target.value); save(S.workDir, e.target.value); }}
                  placeholder="选择文件存放目录" className="flex-1 bg-white border border-outline-variant rounded-lg px-3 py-2 text-body-md" />
                <button type="button" onClick={handlePickDir} className="px-4 py-2 text-label-sm bg-surface-container-high border border-outline-variant rounded-lg hover:bg-surface-container-low whitespace-nowrap">选择目录</button>
              </div>
              <p className="text-[10px] text-on-surface-variant/60 mt-1">Agent 新建的 Excel 文件都存放在此目录；对已有文件操作不移动原位置</p>
            </div>
          </div>
        </section>
      </div>
    </div>
  );
}
