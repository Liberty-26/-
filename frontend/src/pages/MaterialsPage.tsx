// SteelDigitize Pro — 品名库（分类目录 + 收录收件箱 + 增删改查）
import { useState, useEffect, useCallback } from 'react';
import {
  getMaterials, createMaterial, updateMaterial, deleteMaterial, getMaterialCandidates,
  getAliasSuggestions, acceptAliasSuggestion, ignoreAliasSuggestion,
} from '../utils/api';
import { useToast } from '../hooks/useToast';
import ConfirmDialog from '../components/ConfirmDialog';
import type { Material, MaterialCandidate, AliasSuggestion } from '../types';
import { Plus } from 'lucide-react';

const CATS = ['全部', '管材', '管件', '线盒', '网类', '其他'];

export default function MaterialsPage() {
  const { showToast } = useToast();
  const [items, setItems] = useState<Material[]>([]);
  const [cands, setCands] = useState<MaterialCandidate[]>([]);
  const [aliasSugg, setAliasSugg] = useState<AliasSuggestion[]>([]);
  const [search, setSearch] = useState('');
  const [curCat, setCurCat] = useState('全部');
  const [editing, setEditing] = useState<Material | null>(null);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [formName, setFormName] = useState('');
  const [formUnit, setFormUnit] = useState('');
  const [deleteTarget, setDeleteTarget] = useState<number | null>(null);

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

  useEffect(() => { fetchList(''); fetchCands(); fetchAliasSugg(); }, [fetchList, fetchCands, fetchAliasSugg]);

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

  const ignore = (name: string) => {
    setCands((prev) => prev.filter((x) => x.name !== name));
    showToast('已忽略该候选', 'info');
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

  const filtered = items.filter((m) => {
    if (curCat !== '全部' && !m.name.includes(curCat) && !(m.aliases || '').includes(curCat)) return false;
    return true;
  });

  return (
    <div className="plain">
      <div className="page-head">
        <div>
          <div className="page-title">品名库</div>
          <div className="page-sub">识别对齐的标准目录 · {items.length} 条 · 从识别中持续收录</div>
        </div>
        <button className="btn" style={{ marginLeft: 'auto' }} onClick={openAdd}><Plus size={15} />新增品名</button>
      </div>

      <div className="mat-layout">
        <div className="mat-side">
          <div className="cat-list">
            {CATS.map((c) => (
              <button key={c} className={`cat-item ${curCat === c ? 'active' : ''}`} onClick={() => setCurCat(c)}>
                <span>{c}</span>
                <span className="cnt">{c === '全部' ? items.length : filtered.length}</span>
              </button>
            ))}
          </div>
          <div className="inbox">
            <h4>收录收件箱 <span className="badge">{cands.length}</span></h4>
            <div className="hint">识别中出现的未收录品名，确认后进入品名库</div>
            {cands.length === 0 && <div style={{ fontSize: 12, color: 'var(--text-3)' }}>收件箱已清空</div>}
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
          <div className="inbox">
            <h4>错误名建议 <span className="badge">{aliasSugg.length}</span></h4>
            <div className="hint">来自人工修正的数据回流，采纳后识别自动纠错</div>
            {aliasSugg.length === 0 && <div style={{ fontSize: 12, color: 'var(--text-3)' }}>暂无待确认的错误名建议</div>}
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
        </div>

        <div className="mat-main">
          <div className="mat-toolbar">
            <input
              className="search"
              placeholder="搜索品名 / 别名…"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              onKeyDown={(e) => { if (e.key === 'Enter') fetchList(search.trim()); }}
            />
            <button className="btn sm ghost" onClick={() => fetchList(search.trim())}>搜索</button>
            <span style={{ marginLeft: 'auto', fontSize: 12, color: 'var(--text-3)' }}>{filtered.length} 条</span>
          </div>
          <div className="mat-table-wrap">
            <table className="mat-table">
              <thead><tr><th>品名</th><th>默认单位</th><th style={{ width: 110, textAlign: 'center' }}>操作</th></tr></thead>
              <tbody>
                {filtered.length === 0 && <tr><td colSpan={3} style={{ padding: 28, textAlign: 'center', color: 'var(--text-3)' }}>没有匹配的品名</td></tr>}
                {filtered.map((m) => (
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
              <input value={formName} onChange={(e) => setFormName(e.target.value)} />
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
