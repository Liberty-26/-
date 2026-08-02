// SteelDigitize Pro — 品名库管理页
import { useState, useEffect, useCallback } from 'react';
import { getMaterials, createMaterial, updateMaterial, deleteMaterial } from '../utils/api';
import { useToast } from '../hooks/useToast';
import ConfirmDialog from '../components/ConfirmDialog';
import type { Material } from '../types';

export default function MaterialsPage() {
  const { showToast } = useToast();
  const [items, setItems] = useState<Material[]>([]);
  const [total, setTotal] = useState(0);
  const [search, setSearch] = useState('');
  const [loading, setLoading] = useState(false);

  // 新增/编辑弹窗
  const [editing, setEditing] = useState<Material | null>(null);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [formName, setFormName] = useState('');
  const [formAliases, setFormAliases] = useState('');
  const [formUnit, setFormUnit] = useState('');

  // 删除确认
  const [deleteTarget, setDeleteTarget] = useState<number | null>(null);

  const fetchList = useCallback(async (kw: string) => {
    setLoading(true);
    const res = await getMaterials(kw || undefined);
    if (res.success && res.data) { setItems(res.data.items); setTotal(res.data.total); }
    else showToast(res.error || '查询失败', 'error');
    setLoading(false);
  }, [showToast]);

  useEffect(() => { fetchList(''); }, [fetchList]);

  const handleSearch = () => fetchList(search.trim());

  const openAdd = () => {
    setEditing(null); setFormName(''); setFormAliases(''); setFormUnit('');
    setDialogOpen(true);
  };

  const openEdit = (m: Material) => {
    setEditing(m); setFormName(m.name); setFormAliases(m.aliases || ''); setFormUnit(m.unit || '');
    setDialogOpen(true);
  };

  const handleSave = async () => {
    if (!formName.trim()) { showToast('品名不能为空', 'error'); return; }
    const data = { name: formName.trim(), aliases: formAliases.trim(), unit: formUnit.trim() };
    const res = editing
      ? await updateMaterial(editing.id, data)
      : await createMaterial(data);
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

  return (
    <div className="flex-1 p-margin-page overflow-auto h-full flex flex-col">
      <div className="flex items-center justify-between mb-stack-md shrink-0">
        <h2 className="font-headline-md text-headline-md text-on-surface">品名库</h2>
        <button onClick={openAdd} className="bg-primary text-white px-4 py-2 rounded-lg font-semibold text-label-sm hover:bg-primary-container flex items-center gap-1">
          <span className="material-symbols-outlined text-sm">add</span> 新增品名
        </button>
      </div>

      {/* 搜索栏 */}
      <div className="flex flex-wrap gap-3 items-end mb-stack-md shrink-0">
        <div className="flex flex-col gap-1">
          <label className="text-[10px] uppercase text-on-surface-variant font-medium">搜索</label>
          <input type="text" value={search} onChange={e => setSearch(e.target.value)}
            onKeyDown={e => e.key === 'Enter' && handleSearch()}
            placeholder="品名 / 别名"
            className="bg-white border border-outline-variant rounded px-3 py-1.5 text-label-sm focus:border-primary w-44" />
        </div>
        <button onClick={handleSearch} disabled={loading}
          className="bg-primary text-white px-6 py-1.5 rounded-lg font-medium text-label-sm hover:bg-primary-container disabled:opacity-50">
          {loading ? '搜索中...' : '搜索'}
        </button>
      </div>

      {/* 表格 */}
      <div className="border border-outline-variant rounded overflow-hidden bg-white flex-1 flex flex-col">
        <div className="overflow-y-auto flex-1">
          <table className="w-full border-collapse zebra-table">
            <thead className="sticky top-0 bg-surface-container-high border-b border-outline-variant z-10">
              <tr>
                <th className="p-2 text-left text-label-sm text-outline-variant font-medium w-12">序号</th>
                <th className="p-2 text-left text-label-sm text-outline-variant font-medium">品名</th>
                <th className="p-2 text-left text-label-sm text-outline-variant font-medium">别名</th>
                <th className="p-2 text-left text-label-sm text-outline-variant font-medium w-24">默认单位</th>
                <th className="p-2 text-center text-label-sm text-outline-variant font-medium w-28">操作</th>
              </tr>
            </thead>
            <tbody>
              {items.length === 0 && !loading ? (
                <tr><td colSpan={5} className="p-8 text-center text-on-surface-variant text-label-sm">暂无品名</td></tr>
              ) : items.map((m, idx) => (
                <tr key={m.id} className="border-b border-outline-variant/30">
                  <td className="p-2 text-table-cell font-mono">{idx + 1}</td>
                  <td className="p-2 text-table-cell font-medium">{m.name}</td>
                  <td className="p-2 text-table-cell text-on-surface-variant">{m.aliases || '-'}</td>
                  <td className="p-2 text-table-cell">{m.unit || '-'}</td>
                  <td className="p-2 text-center">
                    <div className="flex gap-1 justify-center">
                      <button onClick={() => openEdit(m)} className="text-primary text-label-sm hover:underline">编辑</button>
                      <button onClick={() => setDeleteTarget(m.id)} className="text-error text-label-sm hover:underline">删除</button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className="px-3 py-2 border-t border-outline-variant bg-surface-container-low text-label-sm text-on-surface-variant shrink-0">
          共 {total} 个品名
        </div>
      </div>

      {/* 新增/编辑弹窗 */}
      {dialogOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/30" onClick={() => setDialogOpen(false)}>
          <div className="bg-white rounded-xl shadow-lg p-6 w-[440px]" onClick={e => e.stopPropagation()}>
            <h3 className="font-headline-md text-headline-md text-on-surface mb-4">{editing ? '编辑品名' : '新增品名'}</h3>
            <div className="space-y-3">
              <div>
                <label className="block text-label-sm text-on-surface-variant mb-1">品名 *</label>
                <input type="text" value={formName} onChange={e => setFormName(e.target.value)}
                  className="w-full bg-white border border-outline-variant rounded-lg px-3 py-2 text-body-md focus:border-primary" />
              </div>
              <div>
                <label className="block text-label-sm text-on-surface-variant mb-1">别名（逗号分隔）</label>
                <input type="text" value={formAliases} onChange={e => setFormAliases(e.target.value)}
                  placeholder="例如：镀锌钢管,镀锌管件"
                  className="w-full bg-white border border-outline-variant rounded-lg px-3 py-2 text-body-md focus:border-primary" />
              </div>
              <div>
                <label className="block text-label-sm text-on-surface-variant mb-1">默认单位</label>
                <input type="text" value={formUnit} onChange={e => setFormUnit(e.target.value)}
                  placeholder="例如：米、只、套"
                  className="w-full bg-white border border-outline-variant rounded-lg px-3 py-2 text-body-md focus:border-primary" />
              </div>
            </div>
            <div className="flex gap-2 mt-5 justify-end">
              <button onClick={() => setDialogOpen(false)} className="px-4 py-2 text-label-sm border border-outline-variant rounded-lg hover:bg-surface-container-low">取消</button>
              <button onClick={handleSave} className="px-4 py-2 text-label-sm bg-primary text-white rounded-lg hover:bg-primary-container">保存</button>
            </div>
          </div>
        </div>
      )}

      <ConfirmDialog
        open={deleteTarget !== null}
        title="删除确认"
        message="确定删除此品名？删除后校准不再匹配该品名。"
        onConfirm={handleDelete}
        onCancel={() => setDeleteTarget(null)}
      />
    </div>
  );
}
