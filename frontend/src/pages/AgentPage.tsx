// SteelDigitize Pro — Agent 页
import { useState, useEffect, useCallback, useMemo, useRef, type FormEvent } from 'react';
import { useAgentChat } from '../hooks/useAgentChat';
import { getAgentReceipts, getSkills, getMonitor, generateSkill, createSkill, uploadAgentFile } from '../utils/api';
import { useToast } from '../hooks/useToast';

interface ReceiptLight { id: number; receipt_no: string; date: string; total_amount: number; status: string; item_count: number; }
interface Skill { id: number; name: string; description: string; prompt: string; system_instruction: string; enabled: number; }
interface MonitorData { total_receipts: number; today_count: number; exported: number; pending: number; verified: number; total_tokens: number; today_tokens: number; uptime_seconds: number; }

function fmtUptime(sec: number): string {
  const h = Math.floor(sec / 3600), m = Math.floor((sec % 3600) / 60);
  return h > 0 ? `${h}h ${m}min` : `${m}min`;
}

export default function AgentPage() {
  const { showToast } = useToast();
  const { messages, isLoading, sendMessage, messagesEndRef, loadedFromDb } = useAgentChat();
  const [input, setInput] = useState('');
  const [selectedIds, setSelectedIds] = useState<number[]>([]);

  const [receipts, setReceipts] = useState<ReceiptLight[]>([]);
  const [receiptOpen, setReceiptOpen] = useState(false);
  const [collapsedMonths, setCollapsedMonths] = useState<Set<string>>(new Set());
  const loadReceipts = useCallback(async () => {
    const res = await getAgentReceipts();
    if (res.success && res.data) setReceipts(res.data.receipts);
  }, []);
  useEffect(() => { loadReceipts(); }, [loadReceipts]);
  const toggleSelect = (id: number) => setSelectedIds(prev => prev.includes(id) ? prev.filter(x => x !== id) : [...prev, id]);
  const toggleMonth = (month: string) => setCollapsedMonths(prev => {
    const next = new Set(prev);
    if (next.has(month)) next.delete(month); else next.add(month);
    return next;
  });

  // 按月份分组（YYYY-MM），空日期归入"未填日期"，组内按日期倒序
  const groupedReceipts = useMemo(() => {
    const groups = new Map<string, ReceiptLight[]>();
    for (const r of receipts) {
      const key = r.date ? r.date.slice(0, 7) : '__empty__';
      if (!groups.has(key)) groups.set(key, []);
      groups.get(key)!.push(r);
    }
    const keys = [...groups.keys()].sort((a, b) => {
      if (a === '__empty__') return 1;
      if (b === '__empty__') return -1;
      return b.localeCompare(a);
    });
    return keys.map(k => ({
      month: k,
      items: groups.get(k)!.sort((x, y) => (y.date || '').localeCompare(x.date || '')),
    }));
  }, [receipts]);

  const [skills, setSkills] = useState<Skill[]>([]);
  useEffect(() => { getSkills().then(r => { if (r.success && r.data) setSkills(r.data.skills); }); }, []);

  const [monitor, setMonitor] = useState<MonitorData | null>(null);
  useEffect(() => {
    let active = true;
    const poll = async () => { const r = await getMonitor(); if (active && r.success && r.data) setMonitor(r.data); };
    poll(); const t = setInterval(poll, 5000);
    return () => { active = false; clearInterval(t); };
  }, []);

  const [skillDialog, setSkillDialog] = useState(false);
  const [skillDesc, setSkillDesc] = useState('');
  const [skillGenerating, setSkillGenerating] = useState(false);
  const [skillPreview, setSkillPreview] = useState<{name:string;description:string;prompt:string;system_instruction:string}|null>(null);

  // 上传的已有 Excel 文件
  const [uploadedFile, setUploadedFile] = useState<{ path: string; filename: string } | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const handleFileSelect = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    if (!file.name.toLowerCase().endsWith('.xlsx')) { showToast('仅支持 .xlsx 格式的 Excel 文件', 'error'); e.target.value = ''; return; }
    const res = await uploadAgentFile(file);
    e.target.value = '';
    if (res.success && res.data) {
      setUploadedFile({ path: res.data.path, filename: res.data.filename });
      showToast('文件已上传', 'success');
    } else {
      showToast(res.error || '上传失败', 'error');
    }
  };

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault(); if (!input.trim() || isLoading) return;
    await sendMessage(input, selectedIds, uploadedFile?.path); setInput('');
    setTimeout(loadReceipts, 1500);
  };

  const fireSkill = useCallback((prompt: string) => { sendMessage(prompt, selectedIds, uploadedFile?.path); }, [sendMessage, selectedIds, uploadedFile]);

  return (
    <div className="flex h-full">
      <div className="flex-1 flex flex-col min-w-0">
        <div className="border-b border-outline-variant bg-surface-container-lowest shrink-0">
          <button onClick={() => setReceiptOpen(!receiptOpen)} className="w-full flex items-center gap-2 px-4 py-2 text-label-sm text-on-surface-variant hover:bg-surface-container-low">
            <span className="material-symbols-outlined text-sm">{receiptOpen ? 'expand_less' : 'expand_more'}</span>
            单据库 ({receipts.length} 张)
            {selectedIds.length > 0 && <span className="text-primary text-[11px]">已选 {selectedIds.length}</span>}
          </button>
          {receiptOpen && (
            <div className="px-4 pb-3 max-h-[240px] overflow-y-auto space-y-3">
              {groupedReceipts.length === 0 ? (
                <p className="text-label-sm text-on-surface-variant/40 py-4 text-center">暂无单据</p>
              ) : groupedReceipts.map(g => {
                const isEmptyMonth = g.month === '__empty__';
                const label = isEmptyMonth ? '未填日期' : `${g.month.split('-')[0]}年${Number(g.month.split('-')[1])}月`;
                const collapsed = collapsedMonths.has(g.month);
                const selCount = g.items.filter(r => selectedIds.includes(r.id)).length;
                return (
                  <div key={g.month}>
                    {/* 月份头：可折叠，显示张数 + 已选数 */}
                    <button onClick={() => toggleMonth(g.month)}
                      className="w-full flex items-center gap-1.5 text-label-sm font-semibold text-on-surface hover:text-primary transition-colors duration-200 mb-1.5">
                      <span className="material-symbols-outlined text-sm">{collapsed ? 'expand_more' : 'expand_less'}</span>
                      {label}
                      <span className="text-on-surface-variant/60 font-normal">({g.items.length}张)</span>
                      {selCount > 0 && <span className="text-primary text-[11px] font-medium">已选 {selCount}</span>}
                    </button>
                    {!collapsed && (
                      <div className="flex flex-wrap gap-2">
                        {g.items.map(r => {
                          const checked = selectedIds.includes(r.id);
                          return <label key={r.id} className={`flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg border cursor-pointer text-label-sm transition-all duration-200 ${checked ? 'bg-primary/10 border-primary/40 text-primary' : 'border-outline-variant text-on-surface hover:border-outline hover:bg-surface-container-low'}`}>
                            <input type="checkbox" checked={checked} onChange={() => toggleSelect(r.id)} className="w-3 h-3 accent-primary" />
                            <span className="font-mono font-semibold">{r.receipt_no || `#${r.id}`}</span>
                            <span className="text-on-surface-variant/60 font-mono">{r.date || ''}</span>
                            <span className="text-on-surface-variant/40">{r.item_count}项</span>
                          </label>;
                        })}
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          )}
        </div>

        <div className="flex-1 overflow-y-auto p-4">
          {!loadedFromDb ? <div className="flex items-center justify-center h-full text-on-surface-variant/40">加载中...</div>
          : messages.length === 0 ? <div className="flex flex-col items-center justify-center h-full text-on-surface-variant/40 gap-3"><span className="material-symbols-outlined text-6xl">smart_toy</span><p>勾选单据 → 输入指令开始</p></div>
          : messages.map((msg, i) => <div key={i} className={`flex mb-4 ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}><div className={`max-w-[75%] px-4 py-2.5 rounded-xl text-body-md whitespace-pre-wrap ${msg.role === 'user' ? 'bg-primary-container text-on-primary' : 'bg-surface-container-high text-on-surface'}`}>{msg.content}</div></div>)}
          {isLoading && <div className="flex justify-start mb-4"><div className="bg-surface-container-high px-4 py-2.5 rounded-xl"><span className="inline-flex gap-1"><span className="w-1.5 h-1.5 bg-on-surface-variant/50 rounded-full animate-bounce" /><span className="w-1.5 h-1.5 bg-on-surface-variant/50 rounded-full animate-bounce" style={{animationDelay:'150ms'}} /><span className="w-1.5 h-1.5 bg-on-surface-variant/50 rounded-full animate-bounce" style={{animationDelay:'300ms'}} /></span></div></div>}
          <div ref={messagesEndRef} />
        </div>

        <form onSubmit={handleSubmit} className="p-4 border-t border-outline-variant bg-surface-container-lowest shrink-0">
          <div className="flex gap-3">
            <input type="file" accept=".xlsx" hidden ref={fileInputRef} onChange={handleFileSelect} />
            <button type="button" onClick={() => fileInputRef.current?.click()}
              className="px-2 py-2.5 border border-outline-variant rounded-lg hover:bg-surface-container-low text-on-surface-variant flex items-center"
              title="上传已有表格">
              <span className="material-symbols-outlined text-sm">upload_file</span>
            </button>
            <input type="text" value={input} onChange={e => setInput(e.target.value)}
              placeholder={selectedIds.length > 0 ? `已选 ${selectedIds.length} 张单据，输入指令…` : '输入指令，Agent 自动执行…'}
              disabled={isLoading} className="flex-1 bg-white border border-outline-variant rounded-lg px-4 py-2.5 text-body-md disabled:opacity-50" />
            <button type="submit" disabled={isLoading || !input.trim()} className="bg-primary text-white px-6 py-2.5 rounded-lg font-semibold text-label-sm disabled:opacity-50 flex items-center gap-1"><span className="material-symbols-outlined text-sm">send</span> 发送</button>
          </div>
          {uploadedFile && (
            <div className="mt-2 flex items-center gap-1.5">
              <span className="px-2 py-0.5 rounded text-label-sm bg-primary-fixed text-on-primary-fixed flex items-center gap-1">
                {uploadedFile.filename}
                <button type="button" onClick={() => setUploadedFile(null)} className="hover:text-error">×</button>
              </span>
              <span className="text-[10px] text-on-surface-variant/60">操作此文件不移动原位置</span>
            </div>
          )}
        </form>
      </div>

      <aside className="w-[280px] bg-surface-container-lowest border-l border-outline-variant flex flex-col shrink-0">
        <div className="flex-1 flex flex-col border-b border-outline-variant overflow-hidden">
          <div className="px-3 py-2 border-b border-outline-variant/50"><h3 className="text-label-sm font-semibold text-on-surface">技能快捷指令</h3></div>
          <div className="flex-1 overflow-y-auto p-2 space-y-1.5">
            {skills.length === 0 ? <p className="text-[11px] text-on-surface-variant/40 text-center py-6">暂无技能</p>
            : skills.map(s => <button key={s.id} onClick={() => fireSkill(s.prompt)} className="w-full text-left bg-white border border-outline-variant rounded-lg px-3 py-2 hover:bg-surface-container-low"><div className="text-label-sm font-medium text-on-surface truncate">{s.name}</div><div className="text-[11px] text-on-surface-variant/60 truncate mt-0.5">{s.description || s.prompt}</div></button>)}
          </div>
        </div>

        <div className="flex-1 flex flex-col border-b border-outline-variant overflow-hidden">
          <div className="px-3 py-2 border-b border-outline-variant/50"><h3 className="text-label-sm font-semibold text-on-surface">运行监控</h3></div>
          <div className="flex-1 overflow-y-auto p-2">
            {!monitor ? <p className="text-[11px] text-on-surface-variant/40 text-center py-6">加载中...</p> : <div className="space-y-1.5 text-label-sm">
              <div className="flex justify-between"><span className="text-on-surface-variant">总单据</span><span className="font-mono font-semibold">{monitor.total_receipts}</span></div>
              <div className="flex justify-between"><span className="text-on-surface-variant">今日处理</span><span className="font-mono font-semibold">{monitor.today_count}</span></div>
              <div className="flex justify-between"><span className="text-on-surface-variant">已导出</span><span className="font-mono text-primary">{monitor.exported}</span></div>
              <div className="flex justify-between"><span className="text-on-surface-variant">待处理</span><span className="font-mono text-amber-600">{monitor.pending}</span></div>
              <div className="flex justify-between"><span className="text-on-surface-variant">今日Token</span><span className="font-mono">{monitor.today_tokens.toLocaleString()}</span></div>
              <div className="flex justify-between"><span className="text-on-surface-variant">总Token</span><span className="font-mono text-on-surface-variant/60">{monitor.total_tokens.toLocaleString()}</span></div>
              <div className="flex justify-between"><span className="text-on-surface-variant">运行时长</span><span className="font-mono">{fmtUptime(monitor.uptime_seconds)}</span></div>
            </div>}
          </div>
        </div>

        <div className="flex-1 flex flex-col overflow-hidden">
          <div className="px-3 py-2 border-b border-outline-variant/50"><h3 className="text-label-sm font-semibold text-on-surface">自定义Agent技能</h3></div>
          <div className="flex-1 flex items-center justify-center p-3">
            <button onClick={() => setSkillDialog(true)} className="w-full h-full rounded-xl bg-gradient-to-br from-blue-50 to-white border border-blue-100 flex flex-col items-center justify-center gap-2 p-4 hover:shadow-md">
              <span className="text-body-md font-semibold text-blue-600">自定义Agent技能</span>
              <p className="text-[11px] text-on-surface-variant/60 text-center">为Agent配置特定的提取规则、计算逻辑或接口映射</p>
              <span className="text-label-sm text-blue-500 flex items-center gap-1">配置新技能 <span className="material-symbols-outlined text-sm">arrow_forward</span></span>
            </button>
          </div>
        </div>
      </aside>

      {skillDialog && <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/30" onClick={() => setSkillDialog(false)}>
        <div className="bg-white rounded-xl shadow-lg p-6 w-[480px] max-h-[80vh] overflow-y-auto" onClick={e => e.stopPropagation()}>
          <h3 className="font-headline-md text-headline-md text-on-surface mb-2">创建新技能</h3>
          <p className="text-label-sm text-on-surface-variant mb-4">用自然语言描述您的需求，AI 将自动生成技能配置。</p>
          {!skillPreview ? <>
            <textarea value={skillDesc} onChange={e => setSkillDesc(e.target.value)} placeholder="例如：识别到镀锌管时自动在备注标注防腐处理..." className="w-full bg-white border border-outline-variant rounded-lg px-3 py-2 text-body-md resize-none h-24" />
            <div className="flex gap-2 mt-3 justify-end"><button onClick={() => setSkillDialog(false)} className="px-4 py-2 text-label-sm border border-outline-variant rounded-lg">取消</button>
            <button onClick={async () => { if(!skillDesc.trim())return; setSkillGenerating(true); const r=await generateSkill(skillDesc); setSkillGenerating(false); if(r.success&&r.data){setSkillPreview(r.data);showToast('技能生成成功','success');}else showToast(r.error||'生成失败','error'); }} disabled={skillGenerating||!skillDesc.trim()} className="px-4 py-2 text-label-sm bg-primary text-white rounded-lg disabled:opacity-50">{skillGenerating?'生成中...':'生成技能'}</button></div>
          </> : <>
            <div className="space-y-3 mb-4">
              <div><label className="text-[10px] uppercase text-on-surface-variant">技能名称</label><input value={skillPreview.name} onChange={e=>setSkillPreview({...skillPreview,name:e.target.value})} className="w-full bg-white border border-outline-variant rounded px-3 py-1.5 text-body-md mt-0.5" /></div>
              <div><label className="text-[10px] uppercase text-on-surface-variant">描述</label><input value={skillPreview.description} onChange={e=>setSkillPreview({...skillPreview,description:e.target.value})} className="w-full bg-white border border-outline-variant rounded px-3 py-1.5 text-body-md mt-0.5" /></div>
              <div><label className="text-[10px] uppercase text-on-surface-variant">快捷指令 Prompt</label><textarea value={skillPreview.prompt} onChange={e=>setSkillPreview({...skillPreview,prompt:e.target.value})} className="w-full bg-white border border-outline-variant rounded px-3 py-2 text-body-md mt-0.5 resize-none h-16" /></div>
              <div><label className="text-[10px] uppercase text-on-surface-variant">持久规则（可选）</label><textarea value={skillPreview.system_instruction} onChange={e=>setSkillPreview({...skillPreview,system_instruction:e.target.value})} className="w-full bg-white border border-outline-variant rounded px-3 py-2 text-body-md mt-0.5 resize-none h-16" /></div>
            </div>
            <div className="flex gap-2 justify-end"><button onClick={()=>{setSkillPreview(null);setSkillDesc('');}} className="px-4 py-2 text-label-sm border border-outline-variant rounded-lg">重新生成</button>
            <button onClick={async ()=>{if(!skillPreview)return;const r=await createSkill(skillPreview);if(r.success){showToast('技能已保存','success');setSkillDialog(false);setSkillDesc('');setSkillPreview(null);getSkills().then(r2=>{if(r2.success&&r2.data)setSkills(r2.data.skills);});}else showToast(r.error||'保存失败','error');}} className="px-4 py-2 text-label-sm bg-primary text-white rounded-lg">保存技能</button></div>
          </>}
        </div>
      </div>}
    </div>
  );
}
