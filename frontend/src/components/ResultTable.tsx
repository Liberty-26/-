// SteelDigitize Pro — 可编辑结果表格
import { useState, useCallback, useMemo, type KeyboardEvent, type ChangeEvent } from 'react';
import type { ReceiptItem } from '../types';
import { formatAmount } from '../utils/format';
import ConfirmDialog from './ConfirmDialog';

interface Props {
  items: ReceiptItem[];
  onChange: (items: ReceiptItem[]) => void;
  headerRows?: number[]; // AI 校准标记的表头行（0-based），灰行显示
}

export default function ResultTable({ items, onChange, headerRows }: Props) {
  const [editingCell, setEditingCell] = useState<{ row: number; col: string } | null>(null);
  const [editValue, setEditValue] = useState('');
  const [deleteConfirm, setDeleteConfirm] = useState<number | null>(null);

  // 单元格高亮：根据 issues/corrections 前缀决定背景色
  const cellBg = (item: ReceiptItem, key: string): string => {
    const issues = item.issues || [];
    // 整行异常优先
    if (issues.some(i => i.startsWith('整行'))) return 'bg-red-50';
    // 字段级异常（红）
    const fieldIssue = issues.find(i => i.startsWith(key + ':'));
    if (fieldIssue) return 'bg-red-50';
    // 修正（黄）
    const corrections = item.corrections || [];
    if (key === 'name' && corrections.some(c => c.startsWith('name'))) return 'bg-yellow-50';
    return '';
  };

  const cellTitle = (item: ReceiptItem, key: string): string => {
    const parts: string[] = [];
    (item.issues || []).forEach(i => {
      if (i.startsWith(key + ':') || i.startsWith('整行')) parts.push(i);
    });
    (item.corrections || []).forEach(c => {
      if (key === 'name' && c.startsWith('name')) parts.push(c);
    });
    return parts.join('\n');
  };

  const isHeaderRow = (i: number) => (headerRows || []).includes(i);

  const cols: { key: keyof ReceiptItem; label: string; editable: boolean; align: 'left' | 'right' | 'center' }[] = [
    { key: 'row_num', label: '序号', editable: false, align: 'center' },
    { key: 'name', label: '品种', editable: true, align: 'left' },
    { key: 'spec', label: '规格', editable: true, align: 'left' },
    { key: 'unit', label: '单位', editable: true, align: 'center' },
    { key: 'qty', label: '数量', editable: true, align: 'right' },
    { key: 'price', label: '单价', editable: true, align: 'right' },
  ];

  const totalAmount = useMemo(
    () => items.reduce((sum, it) => sum + (it.qty || 0) * (it.price || 0), 0),
    [items]
  );

  const updateItem = useCallback(
    (idx: number, field: keyof ReceiptItem, val: string | number) => {
      const next = items.map((item, i) => {
        if (i !== idx) return item;
        const updated = { ...item, [field]: val };
        if (field === 'qty' || field === 'price') {
          updated.amount = (updated.qty || 0) * (updated.price || 0);
        }
        return updated;
      });
      onChange(next);
    },
    [items, onChange]
  );

  const startEdit = (row: number, col: string) => {
    const item = items[row];
    const val = item[col as keyof ReceiptItem];
    setEditValue(val != null ? String(val) : '');
    setEditingCell({ row, col });
  };

  const commitEdit = () => {
    if (!editingCell) return;
    const { row, col } = editingCell;
    const key = col as keyof ReceiptItem;
    const val = key === 'qty' || key === 'price' ? parseFloat(editValue) || 0 : editValue;
    updateItem(row, key, val);
    setEditingCell(null);
  };

  const handleKeyDown = (e: KeyboardEvent, row: number, col: string) => {
    if (e.key === 'Enter') {
      e.preventDefault();
      commitEdit();
      if (row + 1 < items.length) {
        startEdit(row + 1, col);
      }
    } else if (e.key === 'Tab') {
      e.preventDefault();
      commitEdit();
      const editableCols = cols.filter((c) => c.editable);
      const idx = editableCols.findIndex((c) => c.key === col);
      const next = editableCols[(idx + 1) % editableCols.length];
      startEdit(row, next.key);
    } else if (e.key === 'Escape') {
      setEditingCell(null);
    }
  };

  const addRow = () => {
    onChange([...items, { name: '', spec: '', unit: '', qty: 0, price: 0 }]);
  };

  const removeRow = (idx: number) => {
    const row = items[idx];
    const hasContent = row.name || row.spec || row.unit || row.qty || row.price;
    if (hasContent) {
      setDeleteConfirm(idx);
    } else {
      onChange(items.filter((_, i) => i !== idx));
    }
  };

  const confirmDelete = () => {
    if (deleteConfirm != null) {
      onChange(items.filter((_, i) => i !== deleteConfirm));
      setDeleteConfirm(null);
    }
  };

  return (
    <>
      <div className="border border-outline-variant rounded overflow-hidden flex flex-col bg-white flex-1">
        <div className="overflow-y-auto custom-scrollbar flex-1">
          <table className="w-full border-collapse zebra-table">
            <thead className="sticky top-0 bg-surface-container-high border-b border-outline-variant z-10">
              <tr>
                {cols.map((c) => (
                  <th
                    key={c.key}
                    className={`p-2 text-label-sm uppercase text-outline-variant font-medium ${
                      c.align === 'right' ? 'text-right' : c.align === 'center' ? 'text-center' : 'text-left'
                    } ${c.key === 'qty' || c.key === 'price' ? 'font-mono' : ''}`}
                    style={{ width: c.key === 'row_num' ? 48 : c.key === 'unit' ? 64 : undefined }}
                  >
                    {c.label}
                  </th>
                ))}
                <th className="p-2 text-center text-label-sm uppercase text-outline-variant font-medium w-20">金额</th>
                <th className="p-2 text-center text-label-sm uppercase text-outline-variant font-medium w-10"></th>
              </tr>
            </thead>
            <tbody>
              {items.map((item, i) => (
                <tr key={i} className={`border-b border-outline-variant/30 group hover:bg-surface-container-low transition-colors ${isHeaderRow(i) ? 'bg-surface-container-high text-on-surface-variant' : ''}`}>
                  <td className="p-2 text-table-cell font-mono text-center">{i + 1}</td>
                  {cols.filter(c => c.editable).map((c) => {
                    const isEditing = editingCell?.row === i && editingCell?.col === c.key;
                    const bg = isHeaderRow(i) ? '' : cellBg(item, c.key as string);
                    return (
                      <td
                        key={c.key}
                        className={`p-2 ${c.align === 'right' ? 'text-right' : c.align === 'center' ? 'text-center' : ''} ${bg}`}
                        title={cellTitle(item, c.key as string) || undefined}
                        onClick={() => !isEditing && startEdit(i, c.key)}
                      >
                        {isEditing ? (
                          <input
                            autoFocus
                            type={c.key === 'qty' || c.key === 'price' ? 'number' : 'text'}
                            className={`table-input w-full bg-transparent p-1 text-table-cell border-none rounded ${
                              c.key === 'qty' || c.key === 'price'
                                ? 'text-right font-mono'
                                : c.key === 'unit' ? 'text-center' : ''
                            }`}
                            value={editValue}
                            onChange={(e: ChangeEvent<HTMLInputElement>) => setEditValue(e.target.value)}
                            onBlur={commitEdit}
                            onKeyDown={(e) => handleKeyDown(e, i, c.key)}
                          />
                        ) : (
                          <span className={`text-table-cell ${(c.key === 'qty' || c.key === 'price') ? 'font-mono' : ''}`}>
                            {c.key === 'name' && item.not_in_library && (
                              <span className="inline-block mr-1 text-[9px] px-1 py-0.5 rounded bg-orange-100 text-orange-700 align-middle" title="品名不在参考库中">未入库</span>
                            )}
                            {item[c.key] || (c.key === 'qty' || c.key === 'price' ? '0' : '')}
                          </span>
                        )}
                      </td>
                    );
                  })}
                  <td className="p-2 text-right text-table-cell font-mono font-bold">
                    {formatAmount((item.qty || 0) * (item.price || 0))}
                  </td>
                  <td className="p-2 text-center">
                    <button
                      onClick={() => removeRow(i)}
                      className="text-error/60 hover:text-error"
                      title="移除行"
                    >
                      <span className="material-symbols-outlined text-sm">remove_circle</span>
                    </button>
                  </td>
                </tr>
              ))}
              {items.length === 0 && (
                <tr>
                  <td colSpan={8} className="p-8 text-center text-body-md text-outline-variant/60">
                    暂无数据，请上传图片并点击识别
                  </td>
                </tr>
              )}
            </tbody>
            <tfoot className="sticky bottom-0 bg-surface-container-low border-t border-outline-variant z-10">
              <tr className="bg-surface-container-high">
                <td colSpan={6} className="p-2 text-right text-label-sm font-medium text-on-surface-variant">
                  合计金额 (Total):
                </td>
                <td className="p-2 text-right text-table-cell font-mono font-bold text-primary">
                  {formatAmount(totalAmount)}
                </td>
                <td className="p-2"></td>
              </tr>
            </tfoot>
          </table>
        </div>
      </div>

      {/* 添加行按钮 */}
      <button
        onClick={addRow}
        className="mt-2 px-3 py-1 text-label-sm border border-outline-variant rounded-lg text-on-surface-variant hover:bg-surface-container-low transition-colors inline-flex items-center gap-1 self-start"
      >
        <span className="material-symbols-outlined text-sm">add</span>
        添加行
      </button>

      {/* 删除确认 */}
      <ConfirmDialog
        open={deleteConfirm != null}
        message="确定删除此行？"
        onConfirm={confirmDelete}
        onCancel={() => setDeleteConfirm(null)}
      />
    </>
  );
}
