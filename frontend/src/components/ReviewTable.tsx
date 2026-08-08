// SteelDigitize Pro — 可编辑识别结果表（原版细节保留：Enter/Tab/Esc 键盘导航、金额自动计算、
// 多选批量编辑、异常红/修正黄/疑似表头灰、未入库徽标）
import { useState, useCallback, useMemo, useEffect, useRef, type KeyboardEvent } from 'react';
import type { ReceiptItem } from '../types';
import { useToast } from '../hooks/useToast';
import ConfirmDialog from './ConfirmDialog';

interface Props {
  items: ReceiptItem[];
  onChange: (items: ReceiptItem[]) => void;
  headerRows?: number[];
  resetSignal?: number;
}

const COL_LABELS: Record<string, string> = {
  name: '品名', spec: '规格', unit: '单位', qty: '数量', price: '单价',
};

const NUM_RE = /^\d+(\.\d+)?$/;

const COLS: { key: string; label: string; align: string }[] = [
  { key: 'name', label: '品名', align: 'left' },
  { key: 'spec', label: '规格', align: 'left' },
  { key: 'unit', label: '单位', align: 'center' },
  { key: 'qty', label: '数量', align: 'right' },
  { key: 'price', label: '单价', align: 'right' },
];

export default function ReviewTable({ items, onChange, headerRows = [], resetSignal = 0 }: Props) {
  const { showToast } = useToast();
  const [editingCell, setEditingCell] = useState<{ row: number; col: string } | null>(null);
  const [editValue, setEditValue] = useState('');
  const [deleteConfirm, setDeleteConfirm] = useState<number | null>(null);
  const [multiSelect, setMultiSelect] = useState(false);
  const [selectedCells, setSelectedCells] = useState<Set<string>>(new Set());
  const [anchorCol, setAnchorCol] = useState<string | null>(null);
  const [batchValue, setBatchValue] = useState('');
  const [selectAnchor, setSelectAnchor] = useState<{ row: number; col: string } | null>(null);
  const [selectCurrent, setSelectCurrent] = useState<{ row: number; col: string } | null>(null);
  const selMovedRef = useRef(false);

  useEffect(() => {
    setMultiSelect(false);
    setSelectedCells(new Set());
    setAnchorCol(null);
    setBatchValue('');
    setSelectAnchor(null);
    setSelectCurrent(null);
    selMovedRef.current = false;
  }, [resetSignal]);

  const totalAmount = useMemo(
    () => items.reduce((sum, it) => sum + (it.qty || 0) * (it.price || 0), 0),
    [items]
  );

  const cellBg = (item: ReceiptItem, key: string): string => {
    const issues = item.issues || [];
    if (issues.some((i) => i.startsWith('整行'))) return 'flag-err';
    if (issues.some((i) => i.startsWith(key + ':'))) return 'flag-err';
    if (key === 'name' && (item.corrections || []).some((c) => c.startsWith('name'))) return 'flag-new';
    return '';
  };

  const cellTitle = (item: ReceiptItem, key: string): string => {
    const parts: string[] = [];
    (item.issues || []).forEach((i) => {
      if (i.startsWith(key + ':') || i.startsWith('整行')) parts.push(i);
    });
    (item.corrections || []).forEach((c) => {
      if (key === 'name' && c.startsWith('name')) parts.push(c);
    });
    return parts.join('\n');
  };

  const isHeaderRow = (i: number) => headerRows.includes(i);

  const updateItem = useCallback(
    (idx: number, field: string, val: string | number) => {
      const next = items.map((item, i) => {
        if (i !== idx) return item;
        const updated: ReceiptItem = { ...item, [field]: val };
        if (field === 'qty' || field === 'price') updated.amount = (updated.qty || 0) * (updated.price || 0);
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
    const val = col === 'qty' || col === 'price' ? parseFloat(editValue) || 0 : editValue;
    updateItem(row, col, val);
    setEditingCell(null);
  };

  const handleKeyDown = (e: KeyboardEvent, row: number, col: string) => {
    if (e.key === 'Enter') {
      e.preventDefault();
      commitEdit();
      if (row + 1 < items.length) startEdit(row + 1, col);
    } else if (e.key === 'Tab') {
      e.preventDefault();
      commitEdit();
      const idx = COLS.findIndex((c) => c.key === col);
      const next = COLS[(idx + 1) % COLS.length];
      startEdit(row, next.key);
    } else if (e.key === 'Escape') {
      setEditingCell(null);
    }
  };

  const handleCellClick = (i: number, colKey: string) => {
    if (multiSelect) return; // 多选模式由 mousedown/mouseup 处理（单击/框选）
    if (!editingCell || editingCell.row !== i || editingCell.col !== colKey) {
      startEdit(i, colKey);
    }
  };

  // 多选：单击 toggle（保留原"同列"约束）
  const toggleCell = (row: number, col: string) => {
    const cellKey = `${row}:${col}`;
    if (selectedCells.size === 0) {
      setAnchorCol(col);
      setSelectedCells(new Set([cellKey]));
      return;
    }
    if (anchorCol !== col) {
      showToast('只能选择同一列的格子', 'warning');
      return;
    }
    const next = new Set(selectedCells);
    if (next.has(cellKey)) next.delete(cellKey);
    else next.add(cellKey);
    setSelectedCells(next);
  };

  // 多选：开始框选（记录起点）
  const handleSelDown = (e: React.MouseEvent, row: number, col: string) => {
    if (!multiSelect) return;
    e.preventDefault();
    selMovedRef.current = false;
    setSelectAnchor({ row, col });
    setSelectCurrent({ row, col });
  };

  // 多选：拖拽经过的格子作为框选终点
  const handleSelMove = (e: React.MouseEvent) => {
    if (!selectAnchor) return;
    const td = (e.target as HTMLElement).closest('td');
    if (!td) return;
    const r = Number(td.getAttribute('data-row'));
    const c = td.getAttribute('data-col');
    if (c == null || Number.isNaN(r)) return;
    if (r !== selectCurrent?.row || c !== selectCurrent?.col) {
      selMovedRef.current = true;
      setSelectCurrent({ row: r, col: c });
    }
  };

  // 多选：mouseup 判定 单击 toggle / 拖拽框选
  useEffect(() => {
    if (!multiSelect) return;
    const up = () => {
      if (!selectAnchor) return;
      const cur = selectCurrent || selectAnchor;
      if (!selMovedRef.current && cur.row === selectAnchor.row && cur.col === selectAnchor.col) {
        toggleCell(selectAnchor.row, selectAnchor.col);
      } else {
        const colKeys = COLS.map((c) => c.key);
        const r1 = Math.min(selectAnchor.row, cur.row);
        const r2 = Math.max(selectAnchor.row, cur.row);
        const ci1 = Math.min(colKeys.indexOf(selectAnchor.col), colKeys.indexOf(cur.col));
        const ci2 = Math.max(colKeys.indexOf(selectAnchor.col), colKeys.indexOf(cur.col));
        const inCols = colKeys.slice(ci1, ci2 + 1);
        const next = new Set<string>();
        for (let r = r1; r <= r2; r++) inCols.forEach((k) => next.add(`${r}:${k}`));
        setSelectedCells(next);
        setAnchorCol(inCols.length === 1 ? inCols[0] : null);
      }
      setSelectAnchor(null);
      setSelectCurrent(null);
      selMovedRef.current = false;
    };
    document.addEventListener('mouseup', up);
    return () => document.removeEventListener('mouseup', up);
  }, [multiSelect, selectAnchor, selectCurrent, selectedCells, anchorCol]);

  const applyBatch = () => {
    if (selectedCells.size === 0) return;
    const count = selectedCells.size;
    const val = batchValue;
    if (!anchorCol) {
      // 框选跨列：值应用到所有选中格；数值列要求纯数字
      const hasNumeric = [...selectedCells].some((k) => k.endsWith(':qty') || k.endsWith(':price'));
      const isNum = NUM_RE.test(val.trim());
      if (hasNumeric && !isNum) {
        showToast('选中包含数量/单价列，请输入有效数字', 'error');
        return;
      }
      onChange(
        items.map((item, ri) => {
          let next: ReceiptItem = item;
          COLS.forEach((c) => {
            if (!selectedCells.has(`${ri}:${c.key}`)) return;
            if (c.key === 'qty' || c.key === 'price') {
              next = { ...next, [c.key]: Number(val) };
              next.amount = (next.qty || 0) * (next.price || 0);
            } else {
              next = { ...next, [c.key]: val };
            }
          });
          return next;
        })
      );
    } else {
      const col = anchorCol;
      const isNumeric = col === 'qty' || col === 'price';
      if (isNumeric) {
        const numVal = val.trim();
        if (!NUM_RE.test(numVal)) {
          showToast('请输入有效数字', 'error');
          return;
        }
        const num = Number(numVal);
        onChange(
          items.map((item, i) => {
            if (!selectedCells.has(`${i}:${anchorCol}`)) return item;
            const updated: ReceiptItem = { ...item, [col]: num };
            updated.amount = (updated.qty || 0) * (updated.price || 0);
            return updated;
          })
        );
      } else {
        onChange(
          items.map((item, i) => (selectedCells.has(`${i}:${anchorCol}`) ? { ...item, [col]: val } : item))
        );
      }
    }
    setSelectedCells(new Set());
    setAnchorCol(null);
    setBatchValue('');
    showToast(`已修改 ${count} 格`, 'success');
  };

  const addRow = () => {
    onChange([...items, { name: '', spec: '', unit: '', qty: 0, price: 0 }]);
  };

  const removeRow = (idx: number) => {
    setSelectedCells(new Set());
    setAnchorCol(null);
    const row = items[idx];
    const hasContent = row.name || row.spec || row.unit || row.qty || row.price;
    if (hasContent) setDeleteConfirm(idx);
    else onChange(items.filter((_, i) => i !== idx));
  };

  return (
    <>
      <div className="rt-toolbar">
        <button
          className={`mini-btn ${multiSelect ? 'on' : ''}`}
          onClick={() => {
            if (editingCell) commitEdit();
            setMultiSelect(!multiSelect);
            setSelectedCells(new Set());
            setAnchorCol(null);
            setBatchValue('');
            setSelectAnchor(null);
            setSelectCurrent(null);
            selMovedRef.current = false;
          }}
        >
          多选
        </button>
        {multiSelect && selectedCells.size > 0 && (
          <div className="rt-batch">
            <span>
              已选 <b style={{ color: 'var(--primary)' }}>{selectedCells.size}</b> 格
              {anchorCol ? `（${COL_LABELS[anchorCol] || anchorCol}）` : '（跨列）'}
            </span>
            <input
              value={batchValue}
              onChange={(e) => setBatchValue(e.target.value)}
              onKeyDown={(e) => { if (e.key === 'Enter') applyBatch(); }}
              placeholder={anchorCol === 'qty' || anchorCol === 'price' ? '输入数值' : '输入新值'}
            />
            <button className="btn sm" onClick={applyBatch}>应用</button>
            <button className="btn sm ghost" onClick={() => { setSelectedCells(new Set()); setAnchorCol(null); setBatchValue(''); }}>清除</button>
          </div>
        )}
      </div>

      <div className="res-table-wrap" onMouseMove={multiSelect ? handleSelMove : undefined}>
        <table className="res-table">
          <thead>
            <tr>
              <th style={{ width: 44 }}>序号</th>
              {COLS.map((c) => (
                <th key={c.key} style={{ textAlign: c.align === 'right' ? 'right' : c.align === 'center' ? 'center' : 'left' }}>
                  {c.label}
                </th>
              ))}
              <th style={{ textAlign: 'right' }}>金额</th>
              <th style={{ width: 90 }}></th>
              <th style={{ width: 34 }}></th>
            </tr>
          </thead>
          <tbody>
            {items.map((item, i) => {
              const header = isHeaderRow(i);
              const rowFlag = header
                ? 'row-header'
                : (item.issues || []).some((x) => x.startsWith('整行'))
                  ? 'flag-err'
                  : '';
              return (
                <tr key={i} className={rowFlag}>
                  <td className="num" style={{ textAlign: 'center', color: 'var(--text-3)' }}>{i + 1}</td>
                  {COLS.map((c) => {
                    const isEditing = editingCell?.row === i && editingCell?.col === c.key;
                    const isSelected = multiSelect && selectedCells.has(`${i}:${c.key}`);
                    const val = item[c.key as keyof ReceiptItem];
                    return (
                      <td
                        key={c.key}
                        data-row={i}
                        data-col={c.key}
                        className={`${cellBg(item, c.key)} ${isSelected ? 'cell-selected' : ''}`}
                        style={{ textAlign: c.align === 'right' ? 'right' : c.align === 'center' ? 'center' : 'left' }}
                        title={cellTitle(item, c.key) || undefined}
                        onClick={() => handleCellClick(i, c.key)}
                        onMouseDown={multiSelect ? (e) => handleSelDown(e, i, c.key) : undefined}
                      >
                        {isEditing ? (
                          <input
                            autoFocus
                            type={c.key === 'qty' || c.key === 'price' ? 'number' : 'text'}
                            className={c.key === 'qty' || c.key === 'price' ? 'num' : ''}
                            style={{ textAlign: c.align === 'right' ? 'right' : c.align === 'center' ? 'center' : 'left' }}
                            value={editValue}
                            onChange={(e) => setEditValue(e.target.value)}
                            onBlur={commitEdit}
                            onKeyDown={(e) => handleKeyDown(e, i, c.key)}
                          />
                        ) : (
                          <span className={c.key === 'qty' || c.key === 'price' ? 'num' : ''}>
                            {c.key === 'name' && item.not_in_library && !header && (
                              <span className="pill amber" style={{ marginRight: 6, fontSize: 11 }} title="品名不在参考库中">未入库</span>
                            )}
                            {val || (c.key === 'qty' || c.key === 'price' ? '0' : '')}
                          </span>
                        )}
                      </td>
                    );
                  })}
                  <td className="num" style={{ textAlign: 'right', fontWeight: 700 }}>
                    {((item.qty || 0) * (item.price || 0)).toFixed(2)}
                  </td>
                  <td>
                    {!header && (() => {
                      const errs = (item.issues || []).length;
                      const news = item.not_in_library ? 1 : 0;
                      if (errs) return <span className="cell-flag" style={{ color: 'var(--err)' }}>⚠ {errs} 项异常</span>;
                      if (news) return <span className="cell-flag" style={{ color: 'var(--warn)' }}>◈ 未入库</span>;
                      return <span className="cell-flag" style={{ color: 'var(--text-3)' }}>—</span>;
                    })()}
                  </td>
                  <td style={{ textAlign: 'center' }}>
                    <button title="移除行" style={{ color: 'var(--err)', opacity: .65 }} onClick={() => removeRow(i)}>✕</button>
                  </td>
                </tr>
              );
            })}
            {items.length === 0 && (
              <tr><td colSpan={9} style={{ padding: '28px', textAlign: 'center', color: 'var(--text-3)' }}>暂无数据，请上传图片并识别</td></tr>
            )}
          </tbody>
          <tfoot>
            <tr style={{ background: '#f7f8fa' }}>
              <td colSpan={7} style={{ textAlign: 'right', fontWeight: 600 }}>合计金额</td>
              <td className="num" colSpan={2} style={{ textAlign: 'left', fontWeight: 700, color: 'var(--primary)' }}>
                {totalAmount.toFixed(2)}
              </td>
            </tr>
          </tfoot>
        </table>
      </div>

      <div style={{ padding: '10px 14px' }}>
        <button className="btn sm ghost" onClick={addRow}>＋ 添加行</button>
      </div>

      <ConfirmDialog
        open={deleteConfirm != null}
        title="删除确认"
        message="确定删除此行？"
        onConfirm={() => {
          if (deleteConfirm != null) onChange(items.filter((_, i) => i !== deleteConfirm));
          setDeleteConfirm(null);
        }}
        onCancel={() => setDeleteConfirm(null)}
      />
    </>
  );
}
