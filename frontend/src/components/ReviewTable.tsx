// SteelDigitize Pro — 可编辑识别结果表（原版细节保留：Enter/Tab/Esc 键盘导航、金额自动计算、
// 多选批量编辑、异常红/修正黄/疑似表头灰、未入库徽标）
import { useState, useCallback, useMemo, useEffect, useRef, type KeyboardEvent } from 'react';
import type { ReceiptItem } from '../types';
import { useToast } from '../hooks/useToast';
import ConfirmDialog from './ConfirmDialog';
import { Plus } from 'lucide-react';

interface Props {
  items: ReceiptItem[];
  onChange: (items: ReceiptItem[]) => void;
  headerRows?: number[];
  resetSignal?: number;
  recTotal?: number | null; // 识别出的合计金额（与计算合计对比审核）
  materialSet?: Set<string>; // 品名库集合（名称+别名），用于动态"未入库"判断
  focusIssueTick?: number;   // 点击"异常"徽标后自增，滚动聚焦第一条异常行
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

export default function ReviewTable({ items, onChange, headerRows = [], resetSignal = 0, recTotal = null, materialSet, focusIssueTick = 0 }: Props) {
  const { showToast } = useToast();
  const [editingCell, setEditingCell] = useState<{ row: number; col: string } | null>(null);
  const [editValue, setEditValue] = useState('');
  const [deleteConfirm, setDeleteConfirm] = useState<number | null>(null);
  const [selectedCells, setSelectedCells] = useState<Set<string>>(new Set());
  const [anchorCol, setAnchorCol] = useState<string | null>(null);
  const [batchValue, setBatchValue] = useState('');
  // 原生交互：单击 = 编辑，拖拽 = 框选（无需"多选"开关）
  const dragStartRef = useRef<{ row: number; col: string; x: number; y: number } | null>(null);
  const selectingRef = useRef(false);
  const selAnchorRef = useRef<{ row: number; col: string } | null>(null);
  const selCurrentRef = useRef<{ row: number; col: string } | null>(null);
  // 框选可视矩形（跟随鼠标展开）
  const [selRect, setSelRect] = useState<{ left: number; top: number; width: number; height: number } | null>(null);
  const wrapRef = useRef<HTMLDivElement>(null);
  const [flashRow, setFlashRow] = useState<number | null>(null);
  const flashTimer = useRef<number | null>(null);
  // 提交后的选中区域：相邻格子合并为一个选框（与拖拽选框同色）
  const [committedRects, setCommittedRects] = useState<{ left: number; top: number; width: number; height: number }[]>([]);

  useEffect(() => {
    setSelectedCells(new Set());
    setAnchorCol(null);
    setBatchValue('');
    setSelRect(null);
    setCommittedRects([]);
    dragStartRef.current = null;
    selectingRef.current = false;
    selAnchorRef.current = null;
    selCurrentRef.current = null;
  }, [resetSignal]);

  const totalAmount = useMemo(
    () => items.reduce((sum, it) => sum + (it.qty || 0) * (it.price || 0), 0),
    [items]
  );
  // 金额对比审核：识别合计 == 计算合计 → 三表头绿色；否则逐行找差异标红
  const totalMatch = recTotal != null && Math.abs(recTotal - totalAmount) < 0.01;
  const amtBad = (item: ReceiptItem) =>
    !totalMatch && item.rec_amount != null && Math.abs(item.rec_amount - (item.qty || 0) * (item.price || 0)) > 0.01;

  // 把选中的格子按"4 邻接"聚成若干组，同一组用一个大选框覆盖
  const computeSelGroups = (sel: Set<string>) => {
    const colIdx = (c: string) => COLS.findIndex((x) => x.key === c);
    const groups: { r1: number; r2: number; c1: number; c2: number }[] = [];
    const visited = new Set<string>();
    const list = Array.from(sel).map((s) => {
      const [r, c] = s.split(':');
      return { r: Number(r), c: colIdx(c) };
    }).filter((x) => !Number.isNaN(x.r) && x.c >= 0);
    for (const cell of list) {
      const k = `${cell.r}:${cell.c}`;
      if (visited.has(k)) continue;
      const stack = [cell];
      visited.add(k);
      let r1 = cell.r, r2 = cell.r, c1 = cell.c, c2 = cell.c;
      while (stack.length) {
        const cur = stack.pop()!;
        r1 = Math.min(r1, cur.r); r2 = Math.max(r2, cur.r);
        c1 = Math.min(c1, cur.c); c2 = Math.max(c2, cur.c);
        for (const [dr, dc] of [[1, 0], [-1, 0], [0, 1], [0, -1]] as const) {
          const nr = cur.r + dr, nc = cur.c + dc;
          const nk = `${nr}:${nc}`;
          if (!visited.has(nk) && sel.has(`${nr}:${COLS[nc]?.key}`)) {
            visited.add(nk);
            stack.push({ r: nr, c: nc });
          }
        }
      }
      groups.push({ r1, r2, c1, c2 });
    }
    return groups;
  };

  // 选中集合变化后：把每组相邻格子的边界框映射到 DOM 坐标
  useEffect(() => {
    const wrap = wrapRef.current;
    if (!wrap || selectedCells.size === 0) { setCommittedRects([]); return; }
    const rects: { left: number; top: number; width: number; height: number }[] = [];
    const wr = wrap.getBoundingClientRect();
    // 视口坐标 → 内容坐标：绝对定位在滚动容器内按内容坐标渲染，须加回滚动偏移
    const st = wrap.scrollTop;
    const sl = wrap.scrollLeft;
    computeSelGroups(selectedCells).forEach((g) => {
      const elA = wrap.querySelector(`td[data-row="${g.r1}"][data-col="${COLS[g.c1].key}"]`);
      const elB = wrap.querySelector(`td[data-row="${g.r2}"][data-col="${COLS[g.c2].key}"]`);
      if (!elA || !elB) return;
      const ar = elA.getBoundingClientRect();
      const br = elB.getBoundingClientRect();
      const left = Math.min(ar.left, br.left) - wr.left + sl;
      const top = Math.min(ar.top, br.top) - wr.top + st;
      const right = Math.max(ar.right, br.right) - wr.left + sl;
      const bottom = Math.max(ar.bottom, br.bottom) - wr.top + st;
      rects.push({ left, top, width: right - left, height: bottom - top });
    });
    setCommittedRects(rects);
  }, [selectedCells, items]);

  // 计算框选矩形：以 .res-table-wrap 为坐标系，随锚点格与当前格展开
  const computeSelRect = (a: { row: number; col: string }, c: { row: number; col: string }) => {
    const wrap = wrapRef.current;
    if (!wrap) return null;
    const elA = wrap.querySelector(`td[data-row="${a.row}"][data-col="${a.col}"]`);
    const elC = wrap.querySelector(`td[data-row="${c.row}"][data-col="${c.col}"]`);
    if (!elA || !elC) return null;
    const ar = elA.getBoundingClientRect();
    const cr = elC.getBoundingClientRect();
    const wr = wrap.getBoundingClientRect();
    // 视口坐标 → 内容坐标：绝对定位在滚动容器内按内容坐标渲染，须加回滚动偏移
    const st = wrap.scrollTop;
    const sl = wrap.scrollLeft;
    const left = Math.min(ar.left, cr.left) - wr.left + sl;
    const top = Math.min(ar.top, cr.top) - wr.top + st;
    const right = Math.max(ar.right, cr.right) - wr.left + sl;
    const bottom = Math.max(ar.bottom, cr.bottom) - wr.top + st;
    return { left, top, width: right - left, height: bottom - top };
  };

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

  // 点击"异常"徽标：滚动到第一条异常行并闪烁高亮
  useEffect(() => {
    if (!focusIssueTick) return;
    const idx = items.findIndex((it, i) => !isHeaderRow(i) && (it.issues || []).length > 0);
    if (idx < 0) return;
    setFlashRow(idx);
    const td = wrapRef.current?.querySelector(`td[data-row="${idx}"]`);
    td?.scrollIntoView({ behavior: 'smooth', block: 'center' });
    if (flashTimer.current) window.clearTimeout(flashTimer.current);
    flashTimer.current = window.setTimeout(() => setFlashRow(null), 1600);
  }, [focusIssueTick, items]);

  useEffect(() => {
    return () => { if (flashTimer.current) window.clearTimeout(flashTimer.current); };
  }, []);

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

  // 原生交互：mousedown 记录起点，超过阈值进入框选；mouseup 判定 拖拽=选中 / 单击=编辑
  const handleCellDown = (e: React.MouseEvent, row: number, col: string) => {
    if (e.button !== 0 || editingCell) return; // 编辑中不干扰
    dragStartRef.current = { row, col, x: e.clientX, y: e.clientY };
    selectingRef.current = false;
    selAnchorRef.current = null;
    selCurrentRef.current = null;
  };

  const handleCellMove = (e: React.MouseEvent) => {
    const start = dragStartRef.current;
    if (!start) return;
    const td = (e.target as HTMLElement).closest('td');
    if (!td) return;
    const r = Number(td.getAttribute('data-row'));
    const c = td.getAttribute('data-col');
    if (c == null || Number.isNaN(r)) return;
    if (!selectingRef.current) {
      if (Math.hypot(e.clientX - start.x, e.clientY - start.y) < 4) return; // 未达拖拽阈值
      e.preventDefault(); // 阻止原生文字选中
      selectingRef.current = true;
      selAnchorRef.current = { row: start.row, col: start.col };
      selCurrentRef.current = { row: r, col: c };
      setSelRect(computeSelRect({ row: start.row, col: start.col }, { row: r, col: c }));
      return;
    }
    if (r !== selCurrentRef.current?.row || c !== selCurrentRef.current?.col) {
      selCurrentRef.current = { row: r, col: c };
      if (selAnchorRef.current) setSelRect(computeSelRect(selAnchorRef.current, { row: r, col: c }));
    }
  };

  // mouseup：拖拽 → 提交选中范围；单击 → 清空旧选中并进入编辑
  useEffect(() => {
    const up = () => {
      const start = dragStartRef.current;
      dragStartRef.current = null;
      if (!start) return;
      if (selectingRef.current) {
        const anchor = selAnchorRef.current || { row: start.row, col: start.col };
        const cur = selCurrentRef.current || anchor;
        const colKeys = COLS.map((x) => x.key);
        const r1 = Math.min(anchor.row, cur.row);
        const r2 = Math.max(anchor.row, cur.row);
        const ci1 = Math.min(colKeys.indexOf(anchor.col), colKeys.indexOf(cur.col));
        const ci2 = Math.max(colKeys.indexOf(anchor.col), colKeys.indexOf(cur.col));
        const inCols = colKeys.slice(ci1, ci2 + 1);
        const next = new Set<string>();
        for (let r = r1; r <= r2; r++) inCols.forEach((k) => next.add(`${r}:${k}`));
        setSelectedCells(next);
        setAnchorCol(inCols.length === 1 ? inCols[0] : null);
      } else {
        // 单击：已有选中则先清空，再编辑该格
        if (selectedCells.size > 0) {
          setSelectedCells(new Set());
          setAnchorCol(null);
          setBatchValue('');
        }
        startEdit(start.row, start.col);
      }
      selectingRef.current = false;
      selAnchorRef.current = null;
      selCurrentRef.current = null;
      setSelRect(null);
    };
    document.addEventListener('mouseup', up);
    return () => document.removeEventListener('mouseup', up);
  }, [selectedCells, items]);

  // Esc：取消多选（清空选中与选框）
  useEffect(() => {
    const onKey = (e: globalThis.KeyboardEvent) => {
      if (e.key !== 'Escape') return;
      if (selectedCells.size === 0) return;
      setSelectedCells(new Set());
      setAnchorCol(null);
      setBatchValue('');
      setSelRect(null);
      setCommittedRects([]);
      selectingRef.current = false;
      selAnchorRef.current = null;
      selCurrentRef.current = null;
      dragStartRef.current = null;
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [selectedCells]);

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
        <span style={{ fontSize: 12, color: 'var(--text-3)' }}>拖拽框选 · 单击编辑 · Esc 取消</span>
        {selectedCells.size > 0 && (
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

      <div className="res-table-wrap" ref={wrapRef} onMouseMove={handleCellMove}>
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
              <th style={{ width: 30 }}></th>
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
                <tr key={i} className={`${rowFlag} ${flashRow === i ? 'issue-flash' : ''}`}>
                  <td className="num" style={{ textAlign: 'center', color: 'var(--text-3)' }}>{i + 1}</td>
                  {COLS.map((c) => {
                    const isEditing = editingCell?.row === i && editingCell?.col === c.key;
                    const val = item[c.key as keyof ReceiptItem];
                    return (
                      <td
                        key={c.key}
                        data-row={i}
                        data-col={c.key}
                        className={cellBg(item, c.key)}
                        style={{ textAlign: c.align === 'right' ? 'right' : c.align === 'center' ? 'center' : 'left' }}
                        title={cellTitle(item, c.key) || undefined}
                        onMouseDown={(e) => handleCellDown(e, i, c.key)}
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
                            {c.key === 'name' && materialSet && item.name && !materialSet.has(item.name) && !header && (
                              <span className="pill amber" style={{ marginRight: 6, fontSize: 11 }} title="品名不在参考库中">未入库</span>
                            )}
                            {val || (c.key === 'qty' || c.key === 'price' ? '0' : '')}
                          </span>
                        )}
                      </td>
                    );
                  })}
                  <td className={`num ${amtBad(item) ? 'amt-err' : ''}`} style={{ textAlign: 'right', fontWeight: 700 }} title={amtBad(item) ? `识别金额 ¥${(item.rec_amount || 0).toFixed(2)} ≠ 计算金额` : undefined}>
                    {((item.qty || 0) * (item.price || 0)).toFixed(2)}
                  </td>
                  <td style={{ textAlign: 'center' }}>
                    <button
                      className="row-del"
                      title="删除此行"
                      aria-label="删除此行"
                      onClick={() => removeRow(i)}
                    >
                      <svg viewBox="0 0 16 16" width="15" height="15" fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round">
                        <circle cx="8" cy="8" r="6.2" />
                        <line x1="3.6" y1="8" x2="12.4" y2="8" />
                      </svg>
                    </button>
                  </td>
                </tr>
              );
            })}
            {items.length === 0 && (
              <tr><td colSpan={8} style={{ padding: '28px', textAlign: 'center', color: 'var(--text-3)' }}>暂无数据，请上传图片并识别</td></tr>
            )}
          </tbody>
          <tfoot>
            <tr style={{ background: '#f7f8fa' }}>
              <td colSpan={6} style={{ textAlign: 'right', fontWeight: 600 }}>合计金额</td>
              <td className="num" colSpan={2} style={{ textAlign: 'left', fontWeight: 700, color: 'var(--primary)' }}>
                {totalAmount.toFixed(2)}
              </td>
            </tr>
          </tfoot>
        </table>
        {selRect && (
          <div
            className="sel-rect"
            style={{ left: selRect.left, top: selRect.top, width: selRect.width, height: selRect.height }}
          />
        )}
        {committedRects.map((r, idx) => (
          <div
            key={idx}
            className="sel-rect sel-committed"
            style={{ left: r.left, top: r.top, width: r.width, height: r.height }}
          />
        ))}
      </div>

      <div style={{ padding: '10px 14px' }}>
        <button className="btn sm ghost" onClick={addRow}><Plus size={14} />添加行</button>
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
