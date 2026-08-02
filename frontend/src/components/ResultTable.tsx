// SteelDigitize Pro — 可编辑结果表格（单格编辑 + 多选批量编辑）
import { useState, useCallback, useMemo, useEffect, type KeyboardEvent, type ChangeEvent } from 'react';
import type { ReceiptItem } from '../types';
import { formatAmount } from '../utils/format';
import { useToast } from '../hooks/useToast';
import ConfirmDialog from './ConfirmDialog';

interface Props {
  items: ReceiptItem[];
  onChange: (items: ReceiptItem[]) => void;
  headerRows?: number[]; // AI 校准标记的表头行（0-based），灰行显示
  resetSignal?: number;  // 外部（识别新图/重新审核/清空图片/加载历史）触发时清空多选状态
}

// 列名映射（批量输入条展示用）
const COL_LABELS: Record<string, string> = {
  name: '品种', spec: '规格', unit: '单位', qty: '数量', price: '单价',
};

// 数值列输入校验：非负数字（整数/小数），拒绝空串/负号/字母/进制前缀等
const NUM_RE = /^\d+(\.\d+)?$/;

export default function ResultTable({ items, onChange, headerRows, resetSignal = 0 }: Props) {
  const { showToast } = useToast();
  const [editingCell, setEditingCell] = useState<{ row: number; col: string } | null>(null);
  const [editValue, setEditValue] = useState('');
  const [deleteConfirm, setDeleteConfirm] = useState<number | null>(null);

  // ---- 多选批量状态 ----
  const [multiSelect, setMultiSelect] = useState(false);
  const [selectedCells, setSelectedCells] = useState<Set<string>>(new Set()); // "row:col" 键
  const [anchorCol, setAnchorCol] = useState<string | null>(null); // 第一次点击的列（同列硬约束）
  const [batchValue, setBatchValue] = useState('');

  // 外部重置：识别新图/重新审核/清空图片/加载历史时清空多选状态和选中集
  useEffect(() => {
    setMultiSelect(false);
    setSelectedCells(new Set());
    setAnchorCol(null);
    setBatchValue('');
  }, [resetSignal]);

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

  // ---- 多选批量逻辑 ----

  const clearMultiSelect = useCallback(() => {
    setSelectedCells(new Set());
    setAnchorCol(null);
    setBatchValue('');
  }, []);

  const toggleMultiSelect = () => {
    if (!multiSelect) {
      // 进入多选：提交未完成的单格编辑，避免两种交互冲突
      if (editingCell) commitEdit();
      clearMultiSelect();
      setMultiSelect(true);
    } else {
      clearMultiSelect();
      setMultiSelect(false);
    }
  };

  // 单元格点击：多选模式 = 选中/取消（同列硬约束）；单格模式 = 开始编辑
  const handleCellClick = (i: number, colKey: string, editable: boolean) => {
    if (multiSelect) {
      if (!editable) return;
      const cellKey = `${i}:${colKey}`;
      if (selectedCells.size === 0) {
        setAnchorCol(colKey);
        setSelectedCells(new Set([cellKey]));
        return;
      }
      if (anchorCol !== colKey) {
        showToast('只能选择同一列的格子', 'warning');
        return;
      }
      const next = new Set(selectedCells);
      if (next.has(cellKey)) next.delete(cellKey);
      else next.add(cellKey);
      setSelectedCells(next);
    } else if (!editingCell || editingCell.row !== i || editingCell.col !== colKey) {
      startEdit(i, colKey);
    }
  };

  // 批量应用：所有选中格统一变为输入值；数值列校验 + 金额联动；应用后清空选中
  const applyBatch = () => {
    if (selectedCells.size === 0 || !anchorCol) return;
    const count = selectedCells.size;
    const col = anchorCol as keyof ReceiptItem;
    const isNumeric = col === 'qty' || col === 'price';
    if (isNumeric) {
      const val = batchValue.trim();
      if (!NUM_RE.test(val)) {
        showToast('请输入有效数字', 'error');
        return;
      }
      const num = Number(val);
      onChange(items.map((item, i) => {
        if (!selectedCells.has(`${i}:${anchorCol}`)) return item;
        const updated = { ...item, [col]: num };
        updated.amount = (updated.qty || 0) * (updated.price || 0);
        return updated;
      }));
    } else {
      onChange(items.map((item, i) => {
        if (!selectedCells.has(`${i}:${anchorCol}`)) return item;
        return { ...item, [col]: batchValue };
      }));
    }
    // 应用即清空（用户确认：一次性操作，不保留选中）
    clearMultiSelect();
    showToast(`已修改 ${count} 格`, 'success');
  };

  const addRow = () => {
    onChange([...items, { name: '', spec: '', unit: '', qty: 0, price: 0 }]);
  };

  const removeRow = (idx: number) => {
    // 行删除会导致选中集索引错位，直接清空多选选中
    clearMultiSelect();
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
      {/* 工具栏：多选开关 + 批量输入条 */}
      <div className="flex items-center gap-2 mb-2 shrink-0 flex-wrap">
        <button
          onClick={toggleMultiSelect}
          className={`px-3 py-1 text-label-sm border rounded-lg transition-colors inline-flex items-center gap-1 ${
            multiSelect
              ? 'bg-primary text-white border-primary'
              : 'border-outline-variant text-on-surface-variant hover:bg-surface-container-low'
          }`}
        >
          <span className="material-symbols-outlined text-sm">{multiSelect ? 'check_box' : 'check_box_outline_blank'}</span>
          多选编辑
        </button>
        {multiSelect && selectedCells.size > 0 && anchorCol && (
          <div className="flex items-center gap-2 text-label-sm">
            <span className="text-on-surface-variant">
              已选 <span className="font-bold text-primary">{selectedCells.size}</span> 格（{COL_LABELS[anchorCol] || anchorCol}）
            </span>
            <input
              value={batchValue}
              onChange={(e) => setBatchValue(e.target.value)}
              onKeyDown={(e) => { if (e.key === 'Enter') applyBatch(); }}
              placeholder={anchorCol === 'qty' || anchorCol === 'price' ? '输入数值' : '输入新值'}
              className="w-36 bg-white border border-outline-variant rounded px-2 py-1 text-label-sm focus:border-primary outline-none"
            />
            <button onClick={applyBatch} className="px-3 py-1 bg-primary text-white rounded-lg text-label-sm hover:bg-primary-container transition-colors">
              应用
            </button>
            <button onClick={clearMultiSelect} className="px-3 py-1 border border-outline-variant rounded-lg text-label-sm text-on-surface-variant hover:bg-surface-container-low transition-colors">
              清除选择
            </button>
          </div>
        )}
      </div>

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
                    const isSelected = multiSelect && selectedCells.has(`${i}:${c.key}`);
                    const bg = isHeaderRow(i) ? '' : cellBg(item, c.key as string);
                    return (
                      <td
                        key={c.key}
                        className={`p-2 ${c.align === 'right' ? 'text-right' : c.align === 'center' ? 'text-center' : ''} ${bg} ${
                          isSelected ? 'bg-primary-fixed-dim/50 ring-2 ring-inset ring-primary' : ''
                        }`}
                        title={cellTitle(item, c.key as string) || undefined}
                        onClick={() => handleCellClick(i, c.key, true)}
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
