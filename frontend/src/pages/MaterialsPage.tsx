// SteelDigitize Pro — 品名库（收录收件箱 + 错误名记忆 + 标准目录增删改查）
import { useState, useEffect, useCallback, type MouseEvent } from 'react';
import {
  getMaterials, createMaterial, updateMaterial, deleteMaterial, getMaterialCandidates,
  getAliasSuggestions, acceptAliasSuggestion, ignoreAliasSuggestion, ignoreMaterialCandidate, getTrainingAggregate,
} from '../utils/api';
import { useToast } from '../hooks/useToast';
import ConfirmDialog from '../components/ConfirmDialog';
import type { Material, MaterialCandidate, AliasSuggestion, TrainingAggregate } from '../types';
import { Plus, ChevronDown, RefreshCw } from 'lucide-react';

interface ErrTip {
  x: number; y: number;
  before: string; after: string; count: number; pct: number;
}

export default function MaterialsPage() {
  const { showToast } = useToast();
  const [items, setItems] = useState<Material[]>([]);
  const [cands, setCands] = useState<MaterialCandidate[]>([]);
  const [aliasSugg, setAliasSugg] = useState<AliasSuggestion[]>([]);
  const [agg, setAgg] = useState<TrainingAggregate>({ total: 0, fields: [], pairs: [] });
  const [search, setSearch] = useState('');
  const [editing, setEditing] = useState<Material | null>(null);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [formName, setFormName] = useState('');
  const [formUnit, setFormUnit] = useState('');
  const [deleteTarget, setDeleteTarget] = useState<number | null>(null);
  // 左侧两个可展开面板
  const [openInbox, setOpenInbox] = useState(true);
  const [openErr, setOpenErr] = useState(true);
  const [syncing, setSyncing] = useState(false);
  const [tip, setTip] = useState<ErrTip | null>(null);
  const [graphOpen, setGraphOpen] = useState(false);

  const fetchList = useCallback(async (kw: string) => {
    const res = await getMaterials(kw || undefined);
    if (res.success && res.data) setItems(res.data.items);
    else showToast(res.error || '查询失败', 'error');
  }, [showToast]);

  const fetchCands = useCallback(async () => {
    const res = await getMaterialCandidates();
    if (res.success && res.data) setCands(res.data.items);
  }, []);

  const fetchAliasSugg = useCallback(async () => {
    const res = await getAliasSuggestions();
    if (res.success && res.data) setAliasSugg(res.data.items);
  }, []);

  const fetchAgg = useCallback(async () => {
    const res = await getTrainingAggregate();
    if (res.success && res.data) setAgg(res.data);
  }, []);

  // 一键从后端同步全部真实数据（训练聚合 + 待确认建议 + 收件箱）
  const syncAll = useCallback(async () => {
    setSyncing(true);
    await Promise.all([fetchCands(), fetchAliasSugg(), fetchAgg()]);
    setSyncing(false);
    showToast('修正记录已更新到最新数据', 'success');
  }, [fetchCands, fetchAliasSugg, fetchAgg, showToast]);

  useEffect(() => { fetchList(''); fetchCands(); fetchAliasSugg(); fetchAgg(); }, [fetchList, fetchCands, fetchAliasSugg, fetchAgg]);

  useEffect(() => {
    const badge = document.getElementById('navBadgeCand');
    if (badge) badge.textContent = String(cands.length);
  }, [cands.length]);

  const openAdd = () => {
    setEditing(null); setFormName(''); setFormUnit('');
    setDialogOpen(true);
  };

  const openEdit = (m: Material) => {
    setEditing(m); setFormName(m.name); setFormUnit(m.unit || '');
    setDialogOpen(true);
  };

  const handleSave = async () => {
    if (!formName.trim()) { showToast('品名不能为空', 'error'); return; }
    // 错误名（原别名）内置维护，不开放手编
    const data = { name: formName.trim(), aliases: '', unit: formUnit.trim() };
    const res = editing ? await updateMaterial(editing.id, data) : await createMaterial(data);
    if (res.success) {
      showToast(editing ? '已更新' : '已新增', 'success');
      setDialogOpen(false);
      fetchList(search.trim());
    } else {
      showToast(res.error || '保存失败', 'error');
    }
  };

  const handleDelete = async () => {
    if (deleteTarget === null) return;
    const res = await deleteMaterial(deleteTarget);
    if (res.success) { showToast('已删除', 'success'); setDeleteTarget(null); fetchList(search.trim()); }
    else showToast(res.error || '删除失败', 'error');
  };

  const adopt = async (c: MaterialCandidate) => {
    const res = await createMaterial({ name: c.name, aliases: '', unit: '' });
    if (res.success) {
      showToast('已收录：' + c.name, 'success');
      setCands((prev) => prev.filter((x) => x.name !== c.name));
      fetchList(search.trim());
    } else {
      showToast(res.error || '收录失败', 'error');
      setCands((prev) => prev.filter((x) => x.name !== c.name));
    }
  };

  const ignore = async (name: string) => {
    const res = await ignoreMaterialCandidate(name);
    if (res.success) {
      setCands((prev) => prev.filter((x) => x.name !== name));
      showToast('已忽略该候选', 'info');
    } else {
      showToast(res.error || '忽略失败', 'error');
    }
  };

  const adoptAlias = async (s: AliasSuggestion) => {
    const res = await acceptAliasSuggestion(s.id);
    if (res.success) {
      showToast(`已采纳：${s.before_val} → ${s.after_val}`, 'success');
      setAliasSugg((prev) => prev.filter((x) => x.id !== s.id));
      fetchList(search.trim());
    } else {
      showToast(res.error || '采纳失败', 'error');
    }
  };

  const ignoreAlias = async (s: AliasSuggestion) => {
    const res = await ignoreAliasSuggestion(s.id);
    if (res.success) {
      showToast('已忽略该建议', 'info');
      setAliasSugg((prev) => prev.filter((x) => x.id !== s.id));
    } else {
      showToast(res.error || '操作失败', 'error');
    }
  };

  const showTip = (e: MouseEvent, p: { before: string; after: string; count: number; pct: number }) => {
    setTip({ x: e.clientX, y: e.clientY, ...p });
  };

  // L12 Type Colonnade（lieflat-charts 原版骨架）：左列错误名 → 右列标准名，
  // 发丝曲线 + 右列圆点（大小 ∝ 次数）；曲线粗细 ∝ 次数占比，悬停左列名称/曲线查看次数
  const renderColonnade = (pairs: { before: string; after: string; count: number; pct: number }[]) => {
    const N = pairs.length;
    const itemY = (i: number) => 20 + i * (280 / Math.max(N, 1));
    const hubs: { name: string; count: number }[] = [];
    const hubIndex = new Map<string, number>();
    [...new Set(pairs.map((p) => p.after))].forEach((name) => {
      const count = pairs.filter((p) => p.after === name).reduce((s, p) => s + p.count, 0);
      hubIndex.set(name, hubs.length);
      hubs.push({ name, count });
    });
    const hubY = (j: number) => 34 + j * (292 / Math.max(hubs.length, 1));
    return (
      <div className="g-card">
        <h2>每一次人工修改，都汇向一个标准名</h2>
        <div className="sub">1 条曲线 = 1 次人工修正 · 右列圆点 = 修正后的标准名 · 圆点大小 ∝ 次数</div>
        <svg viewBox="0 0 400 360" preserveAspectRatio="xMidYMid meet" style={{ width: '100%', display: 'block' }}>
          {pairs.map((p, i) => {
            const yi = itemY(i);
            const yj = hubY(hubIndex.get(p.after)!);
            const sw = Math.max(0.6, Math.min(4, 0.6 + (p.pct / 100) * 3.4));
            return (
              <g key={`${p.before}→${p.after}`}>
                <text
                  x={112} y={yi + 2} fontSize={6.5} fill="#8F8E88" textAnchor="end"
                  className="g-fade" style={{ animationDelay: `${i * 0.02}s` }}
                  onMouseMove={(e) => showTip(e, p)}
                  onMouseLeave={() => setTip(null)}
                >{p.before}</text>
                <rect
                  x={117} y={yi - 1.2} width={4} height={2.4} fill="#B0AFA9"
                  className="g-fade" style={{ animationDelay: `${i * 0.02}s` }}
                  onMouseMove={(e) => showTip(e, p)}
                  onMouseLeave={() => setTip(null)}
                />
                <path
                  d={`M123 ${yi} C 200 ${yi} 220 ${yj} 288 ${yj}`}
                  fill="none" stroke="#A8A7A0" strokeWidth={sw} opacity={0.6} pathLength={1}
                  className="g-draw" style={{ animationDelay: `${0.2 + i * 0.02}s`, animationDuration: '0.6s' }}
                  onMouseMove={(e) => showTip(e, p)}
                  onMouseLeave={() => setTip(null)}
                />
              </g>
            );
          })}
          {hubs.map((h, j) => {
            const y = hubY(j);
            const r = 2.8 + h.count * 0.95;
            return (
              <g key={h.name}>
                <circle
                  cx={293} cy={y} r={r}
                  fill={h.count >= 2 ? '#1C1C1A' : h.count === 1 ? '#6A6963' : '#B0AFA9'}
                  className="g-pop" style={{ animationDelay: `${0.6 + j * 0.06}s` }}
                />
                <text
                  x={302 + r + 4} y={y + 2.6} fontSize={7} fontWeight={700} fill="#4A4944"
                  className="g-fade" style={{ animationDelay: `${0.65 + j * 0.06}s` }}
                >{h.name} · {h.count}</text>
              </g>
            );
          })}
        </svg>
        <div className="src">TYPE COLONNADE · 数据回流：识别结果 → 人工修正（correction_log）</div>
      </div>
    );
  };

  return (
    <div className="plain">
      <div className="page-head">
        <div>
          <div className="page-title">品名库</div>
          <div className="page-sub">识别对齐的标准目录 · {items.length} 条 · 错误名自动纠错</div>
        </div>
        <button className="btn" style={{ marginLeft: 'auto' }} onClick={openAdd}><Plus size={15} />新增品名</button>
      </div>

      <div className="mat-layout">
        <div className="mat-side">
          {/* 收录收件箱：点击展开完整信息 */}
          <div className={`inbox fold ${openInbox ? 'open' : ''}`}>
            <button className="fold-head" onClick={() => setOpenInbox((v) => !v)}>
              <span className="fold-title">收录收件箱 <span className="badge">{cands.length}</span></span>
              <span className={`fold-caret ${openInbox ? 'open' : ''}`}><ChevronDown size={15} /></span>
            </button>
            <div className="fold-body">
              <div className="fold-inner">
                <div className="hint">识别中出现的未收录品名，确认后进入品名库</div>
                {cands.length === 0 && <div className="fold-empty">收件箱已清空</div>}
                {cands.map((c) => (
                  <div key={c.name} className="cand">
                    <div><span className="to">{c.name}</span></div>
                    <div className="reason">出现 {c.count} 次 · 最近 {c.latest_date || '—'}</div>
                    <div className="acts">
                      <button className="mini" onClick={() => adopt(c)}>收录</button>
                      <button className="mini ghost" onClick={() => ignore(c.name)}>忽略</button>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          </div>

          {/* 修正记录（训练数据）：Colonnade 对照图 + 待确认建议 */}
          <div className={`inbox fold ${openErr ? 'open' : ''}`}>
            <button className="fold-head" onClick={() => setOpenErr((v) => !v)}>
              <span className="fold-title">修正记录 <span className="badge">{agg.total}</span></span>
              <span className={`fold-caret ${openErr ? 'open' : ''}`}><ChevronDown size={15} /></span>
            </button>
            <div className="fold-body">
              <div className="fold-inner">
                <div className="err-head">
                  <span className="hint">线越粗 = 次数占比越高 · 悬停查看次数</span>
                  <button className="sync-btn" onClick={syncAll} disabled={syncing}>
                    <RefreshCw size={13} className={syncing ? 'spin' : ''} />
                    {syncing ? '更新中…' : '更新数据'}
                  </button>
                </div>

                {agg.pairs.length === 0 && (
                  <div className="fold-empty">还没有训练数据：在审核区修改识别结果后会自动积累</div>
                )}

                {agg.pairs.length > 0 && (
                  <>
                    <div className="ef-title">修正次数前五</div>
                    <div className="top5">
                      {agg.pairs.slice(0, 5).map((p) => (
                        <div key={`${p.before}→${p.after}`} className="top5-row">
                          <span className="t5-from">{p.before}</span>
                          <span className="t5-arrow">→</span>
                          <span className="t5-to">{p.after}</span>
                          <span className="t5-count">{p.count} 次</span>
                        </div>
                      ))}
                    </div>
                    <button className="graph-btn" onClick={() => setGraphOpen(true)}>
                      查看修正图谱
                    </button>
                  </>
                )}

                {agg.quality && agg.quality.length > 0 && (
                  <div className="quality-grid" aria-label="识别质量统计">
                    <div className="ef-title">人工修改率（越低越好）</div>
                    {agg.quality.map((q) => (
                      <div className="quality-row" key={q.field}>
                        <span>{q.label}</span>
                        <span className="quality-count">{q.corrected} / {q.observed}</span>
                        <span className="quality-rate">{q.rate}%</span>
                      </div>
                    ))}
                  </div>
                )}

                {aliasSugg.length > 0 && (
                  <div className="err-sugg">
                    <div className="ef-title">待确认建议</div>
                    {aliasSugg.map((s) => (
                      <div key={s.id} className="cand">
                        <div><span className="from">{s.before_val}</span> → <span className="to">{s.after_val}</span></div>
                        <div className="reason">来自 {s.count} 次人工修正</div>
                        <div className="acts">
                          <button className="mini" onClick={() => adoptAlias(s)}>采纳</button>
                          <button className="mini ghost" onClick={() => ignoreAlias(s)}>忽略</button>
                        </div>
                      </div>
                    ))}
                  </div>
                )}

                {agg.total === 0 && aliasSugg.length === 0 && (
                  <div className="fold-empty">还没有训练数据：在审核区修改识别结果后会自动在这里积累</div>
                )}
              </div>
            </div>
          </div>

          {tip && (
            <div className="err-tip" style={{ left: tip.x + 14, top: tip.y + 14 }}>
              <div><b>{tip.before}</b> → {tip.after}</div>
      <div className="tip-meta">共 {tip.count} 次 · 占品名修正 {tip.pct}%</div>
            </div>
          )}
        </div>

        <div className="mat-main">
          <div className="mat-toolbar">
            <input
              className="search"
              placeholder="搜索品名 / 错误名…"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              onKeyDown={(e) => { if (e.key === 'Enter') fetchList(search.trim()); }}
            />
            <button className="btn sm ghost" onClick={() => fetchList(search.trim())}>搜索</button>
            <span style={{ marginLeft: 'auto', fontSize: 12, color: 'var(--text-3)' }}>{items.length} 条</span>
          </div>
          <div className="mat-table-wrap">
            <table className="mat-table">
              <thead><tr><th>品名</th><th>默认单位</th><th style={{ width: 110, textAlign: 'center' }}>操作</th></tr></thead>
              <tbody>
                {items.length === 0 && <tr><td colSpan={3} style={{ padding: 28, textAlign: 'center', color: 'var(--text-3)' }}>没有匹配的品名</td></tr>}
                {items.map((m) => (
                  <tr key={m.id}>
                    <td style={{ fontWeight: 600 }}>{m.name}</td>
                    <td>{m.unit || '—'}</td>
                    <td style={{ textAlign: 'center' }}>
                      <button className="link" onClick={() => openEdit(m)}>编辑</button>
                      <button className="link danger" style={{ marginLeft: 10 }} onClick={() => setDeleteTarget(m.id)}>删除</button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </div>

      {dialogOpen && (
        <div className="dlg-mask" onClick={() => setDialogOpen(false)}>
          <div className="dlg" onClick={(e) => e.stopPropagation()}>
            <h3>{editing ? '编辑品名' : '新增品名'}</h3>
            <div className="form-field">
              <label>品名 *</label>
              <input value={formName} onChange={(e) => setFormName(e.target.value)} autoFocus />
            </div>
            <div className="form-field">
              <label>默认单位</label>
              <input value={formUnit} onChange={(e) => setFormUnit(e.target.value)} placeholder="例如：米、只、套" />
            </div>
            <div className="dlg-acts">
              <button className="btn ghost" onClick={() => setDialogOpen(false)}>取消</button>
              <button className="btn" onClick={handleSave}>保存</button>
            </div>
          </div>
        </div>
      )}

      {graphOpen && (
        <div className="modal-mask show" onClick={() => setGraphOpen(false)}>
          <div className="modal graph-modal" onClick={(e) => e.stopPropagation()}>
            <button className="graph-close" onClick={() => setGraphOpen(false)} aria-label="关闭">✕</button>
            {agg.pairs.length > 0
              ? renderColonnade(agg.pairs)
              : <div className="g-card"><div className="fold-empty">还没有训练数据</div></div>}
          </div>
        </div>
      )}

      <ConfirmDialog
        open={deleteTarget !== null}
        title="删除确认"
        message="确定删除此品名？删除后识别对齐不再匹配该品名。"
        onConfirm={handleDelete}
        onCancel={() => setDeleteTarget(null)}
      />
    </div>
  );
}
