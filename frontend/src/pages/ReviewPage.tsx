// SteelDigitize Pro — 审核区：待审队列 + 原图对照 + 可编辑结果 + 确认入库（保留单号/日期自动提取）
import { useCallback, useEffect, useRef, useState } from 'react';
import ReviewTable from '../components/ReviewTable';
import { useNav } from '../contexts/NavContext';
import { useQueue } from '../contexts/QueueContext';
import { useToast } from '../hooks/useToast';
import ConfirmDialog from '../components/ConfirmDialog';
import { Inbox, RotateCcw, Plus, Minus, BookOpen } from 'lucide-react';
import {
  getReceiptDetail, updateReceipt, verifyReceipt, deleteReceipt,
  calibrateItemsSSE, recognizeImage, addCorrections, getMaterials,
} from '../utils/api';
import { fetchUploadAsDataUrl } from '../utils/image';
import type { ReceiptSummary, ReceiptItem } from '../types';

// 与后端 calibrate 规则一致的单位白名单（用于编辑后动态重算异常）
const UNIT_WHITELIST = new Set([
  '只', '米', '片', '箱', '桶', '卷', '盒', '支', '组', '套', '包', '瓶',
  '根', '捆', '把', '斤', '平方', '台', '袋', '吨', '块', '条', '张', '对',
  '双', '付',
]);
const HEADER_KW = ['品种', '单位', '数量', '单价', '金额', '合计'];
const MAX_QTY = 100000;
const MAX_PRICE = 10000;

// 编辑后即时重算可判定异常：数字范围 / 单位 / 空行 / 表头字样
// 无法本地判定的异常（如"名称规格混写"）原样保留
function refreshIssues(it: ReceiptItem): string[] {
  const orig = it.issues || [];
  const name = (it.name || '').trim();
  const spec = (it.spec || '').trim();
  const unit = (it.unit || '').trim();
  const qtyOk = (it.qty || 0) > 0 && (it.qty || 0) <= MAX_QTY;
  const priceOk = (it.price || 0) > 0 && (it.price || 0) <= MAX_PRICE;
  const unitInvalid = !!unit && !UNIT_WHITELIST.has(unit);
  const unitMissing = !unit && !!name;
  const headerLike = !!name && HEADER_KW.some((k) => name.includes(k));
  const nameEmpty = !name && !spec;
  const next: string[] = [];
  orig.forEach((iss) => {
    if (iss.startsWith('qty:') || iss.startsWith('price:')) return; // 数字类按当前值重判
    if (iss.startsWith('unit:')) return; // 单位类按当前值重判
    if (iss === '整行: 品名为空') return;
    if (iss === '整行: 疑似表头行') return;
    next.push(iss); // 其他异常保留
  });
  if (!qtyOk) next.push('qty: 数量超出范围');
  if (!priceOk) next.push('price: 单价超出范围');
  if (unitInvalid) next.push('unit: 单位不在常见单位集合');
  if (unitMissing) next.push('unit: 缺失单位');
  if (headerLike) next.push('整行: 疑似表头行');
  if (nameEmpty) next.push('整行: 品名为空');
  return next;
}

export default function ReviewPage() {
  const { showToast } = useToast();
  const { page, setPage } = useNav();
  const { queue, refreshQueue, removePending } = useQueue();
  const active = page === 'review';
  const [currentId, setCurrentId] = useState<number | null>(null);
  const [no, setNo] = useState('');
  const [date, setDate] = useState('');
  const [items, setItems] = useState<ReceiptItem[]>([]);
  const [recTotal, setRecTotal] = useState<number | null>(null);
  const [headerRows, setHeaderRows] = useState<number[]>([]);
  const [originalItems, setOriginalItems] = useState<ReceiptItem[]>([]);
  const [imageUrl, setImageUrl] = useState('');
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [zoom, setZoom] = useState(1);
  const [pan, setPan] = useState({ x: 0, y: 0 });
  const [dragStart, setDragStart] = useState<{ x: number; y: number; px: number; py: number } | null>(null);
  const [requireDialog, setRequireDialog] = useState(false);
  const [tableReset, setTableReset] = useState(0);
  const [queueEditing, setQueueEditing] = useState(false);
  const [selectedIds, setSelectedIds] = useState<Set<number>>(new Set());
  const [deleteOpen, setDeleteOpen] = useState(false);
  const [deleting, setDeleting] = useState(false);
  // 点击"异常"徽标：通知表格滚动聚焦到第一条异常行
  const [issueFocusTick, setIssueFocusTick] = useState(0);
  // 品名库集合：用于动态计算"品名对齐/未入库"（修改品名后即时更新）
  const [materialSet, setMaterialSet] = useState<Set<string>>(new Set());
  const origRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    getMaterials().then((res) => {
      if (res.success && res.data) {
        const set = new Set<string>();
        (res.data.items || []).forEach((m) => {
          const name = (m.name || '').trim();
          if (name) set.add(name);
          (m.aliases || '').split(/[,，/]/).forEach((a) => {
            const t = a.trim();
            if (t) set.add(t);
          });
        });
        setMaterialSet(set);
      }
    });
  }, []);

  // 原图滚轮缩放：原生非 passive 监听，阻止页面滚动，只缩原图；
  // 依赖 currentId/imageUrl：原图容器挂载后重新绑定（此前只在组件挂载时绑定一次，单据加载后失效）
  useEffect(() => {
    const el = origRef.current;
    if (!el) return;
    const handler = (e: WheelEvent) => {
      e.preventDefault();
      setZoom((z) => Math.min(2.5, Math.max(0.5, Math.round((z + (e.deltaY > 0 ? -0.05 : 0.05)) * 100) / 100)));
    };
    el.addEventListener('wheel', handler, { passive: false });
    return () => el.removeEventListener('wheel', handler);
  }, [currentId, imageUrl]);

  // 进入审核区时校准一次（共享队列已实时同步，这里只保证与后端一致）
  useEffect(() => { if (active) refreshQueue(); }, [active, refreshQueue]);

  // 共享队列变化时（首页识别完成/入库移除）自动同步当前选中单据：
  // 优先恢复上次在审单据，其次保留当前选中，否则选队列第一项（最新单据）
  useEffect(() => {
    setCurrentId((cur) => {
      const savedId = Number(sessionStorage.getItem('steel_review_id'));
      if (savedId && queue.some((q) => q.id === savedId)) return savedId;
      if (cur != null && queue.some((q) => q.id === cur)) return cur;
      return queue.length > 0 ? queue[0].id : null;
    });
    if (queue.length === 0) {
      setItems([]);
      setImageUrl('');
    }
  }, [queue]);

  const loadDetail = useCallback(async (id: number) => {
    setLoading(true);
    const res = await getReceiptDetail(id);
    if (res.success && res.data) {
      const d = res.data;
      setNo(d.receipt_no || '');
      setDate(d.date || '');
      setRecTotal(d.rec_total ?? null);
      setImageUrl(d.image_path ? '/uploads/' + d.image_path : '');
      try { sessionStorage.setItem('steel_review_id', String(id)); } catch { /* ignore */ }
      setZoom(1);
      setPan({ x: 0, y: 0 });
      setDragStart(null);
      const saved: ReceiptItem[] = (d.items || []).map((it) => ({
        name: it.name || '', spec: it.spec || '', unit: it.unit || '',
        qty: it.qty || 0, price: it.price || 0,
        ...(it.rec_amount != null ? { rec_amount: it.rec_amount } : {}),
      }));
      setOriginalItems(saved);
      setItems(saved);
      setHeaderRows([]);
      setTableReset((s) => s + 1);
      // 纯代码校准：品名对齐/形近字/名称规格拆分/单位补全（无 LLM，不烧额度）
      const cal = await calibrateItemsSSE(saved, d.receipt_no || '', d.date || '');
      if (cal.success && cal.data) {
        setItems(cal.data.items);
        setHeaderRows(cal.data.header_rows || []);
      }
    } else {
      showToast(res.error || '加载详情失败', 'error');
    }
    setLoading(false);
  }, [showToast]);

  useEffect(() => {
    if (currentId) loadDetail(currentId);
  }, [currentId, loadDetail]);

  const saveCurrent = useCallback(async (verify: boolean): Promise<boolean> => {
    if (currentId == null) return false;
    if (verify && (!date || !no.trim())) {
      setRequireDialog(true);
      return false;
    }
    setSaving(true);
    const changes: { receipt_no: string; field: string; before_val: string; after_val: string }[] = [];
    items.forEach((it, i) => {
      const orig = originalItems[i];
      if (!orig) return;
      // 训练数据只收集品名错误与修改（规格/单位/数量/单价不再入训练集）
      (['name'] as const).forEach((f) => {
        const b = String(orig[f] ?? '');
        const a = String(it[f] ?? '');
        if (b !== a) changes.push({ receipt_no: no, field: f, before_val: b, after_val: a });
      });
    });
    const res = await updateReceipt(currentId, {
      receipt_no: no, date, rec_total: recTotal ?? undefined,
      items: items.map((it) => ({
        name: it.name, spec: it.spec, unit: it.unit, qty: it.qty, price: it.price,
        ...(it.rec_amount != null ? { rec_amount: it.rec_amount } : {}),
      })),
    });
    if (!res.success) {
      showToast(res.error || '保存失败', 'error');
      setSaving(false);
      return false;
    }
    if (changes.length > 0) addCorrections(changes).catch(() => {});
    if (verify) {
      const vr = await verifyReceipt(currentId);
      if (!vr.success) {
        showToast(vr.error || '确认入库失败', 'error');
        setSaving(false);
        return false;
      }
      showToast('已确认入库：' + no, 'success');
    } else {
      showToast('草稿已保存', 'success');
    }
    setSaving(false);
    return true;
  }, [currentId, date, no, items, originalItems, recTotal, showToast]);

  const handleVerify = useCallback(async () => {
    if (!currentId) return;
    const ok = await saveCurrent(true);
    if (ok) {
      removePending(currentId);
      const next = queue.filter((q) => q.id !== currentId)[0]?.id ?? null;
      if (next) setCurrentId(next);
      else { setCurrentId(null); setItems([]); setImageUrl(''); }
    }
  }, [currentId, queue, saveCurrent, removePending]);

  const toggleSelect = (id: number) => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });
  };

  const toggleSelectAll = () => {
    setSelectedIds((prev) => (prev.size === queue.length && queue.length > 0 ? new Set() : new Set(queue.map((q) => q.id))));
  };

  const exitQueueEdit = () => {
    setQueueEditing(false);
    setSelectedIds(new Set());
  };

  const doDeleteSelected = async () => {
    if (selectedIds.size === 0) return;
    if (deleting) return;
    setDeleting(true);
    for (const id of Array.from(selectedIds)) {
      const res = await deleteReceipt(id);
      if (res.success) removePending(id);
      else showToast(res.error || `删除单据 ${id} 失败`, 'error');
    }
    setDeleting(false);
    setDeleteOpen(false);
    exitQueueEdit();
    showToast(`已删除 ${selectedIds.size} 张单据`, 'success');
  };

  const handleReRecognize = useCallback(async () => {
    if (!imageUrl) return;
    setLoading(true);
    try {
      const b64 = await fetchUploadAsDataUrl(imageUrl);
      const res = await recognizeImage(b64, no, date);
      if (res.success && res.data) {
        setNo(res.data.receipt_no || no);
        setDate(res.data.date || date);
        setItems(res.data.items || []);
        setHeaderRows([]);
        setTableReset((s) => s + 1);
        const cal = await calibrateItemsSSE(res.data.items || [], res.data.receipt_no || no, res.data.date || date);
        if (cal.success && cal.data) {
          setItems(cal.data.items);
          setHeaderRows(cal.data.header_rows || []);
        }
        showToast('重新识别完成', 'success');
      } else {
        showToast(res.error || '重新识别失败', 'error');
      }
    } catch (e) {
      showToast((e as Error).message || '重新识别失败', 'error');
    }
    setLoading(false);
  }, [imageUrl, no, date, showToast]);

  const groups: { month: string; list: ReceiptSummary[] }[] = [];
  queue.forEach((q) => {
    const m = q.date ? q.date.slice(0, 7) : '';
    const g = groups.find((x) => x.month === m);
    if (g) g.list.push(q);
    else groups.push({ month: m, list: [q] });
  });

  // 动态状态：品名对齐 / 未入库 / 金额 / 异常（每次编辑即时更新）
  const liveItems = items.map((it) => ({ ...it, issues: refreshIssues(it) }));
  const nonHeader = liveItems.filter((_, i) => !headerRows.includes(i));
  const aligned = nonHeader.filter((it) => it.name && materialSet.has(it.name)).length;
  const notInLib = nonHeader.filter((it) => it.name && !materialSet.has(it.name)).length;
  const computedTotal = nonHeader.reduce((s, it) => s + (it.qty || 0) * (it.price || 0), 0);
  // 金额动态判定：合计一致 → 正确；合计不一致但每行识别金额全部核对一致 → 也正确（说明 OCR 合计读错）
  const totalMatch = recTotal != null && Math.abs(recTotal - computedTotal) < 0.01;
  const recRows = nonHeader.filter((it) => it.rec_amount != null);
  const rowsAllMatch = nonHeader.length > 0
    && recRows.length === nonHeader.length
    && recRows.every((it) => Math.abs((it.rec_amount || 0) - (it.qty || 0) * (it.price || 0)) < 0.01);
  const amountOk = recTotal != null && (totalMatch || rowsAllMatch);
  const amountBad = recTotal != null && !amountOk;
  const summary = {
    issues: liveItems.filter((it) => (it.issues || []).length > 0).length,
  };

  return (
    <div className="review">
      <aside className="queue">
        <div className="queue-head">
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <div className="queue-title">待审核单据 <span className="badge">{queue.length}</span></div>
            <span style={{ flex: 1 }} />
            {!queueEditing ? (
              <button className="link" onClick={() => setQueueEditing(true)} disabled={queue.length === 0}>编辑</button>
            ) : (
              <>
                <button className="link" onClick={toggleSelectAll}>
                  {selectedIds.size === queue.length && queue.length > 0 ? '取消全选' : '全选'}
                </button>
                <button className="link danger" onClick={() => setDeleteOpen(true)} disabled={selectedIds.size === 0}>删除</button>
                <button className="link" onClick={exitQueueEdit}>完成</button>
              </>
            )}
          </div>
          <div className="queue-sub">识别结果需与原图核对后入库</div>
          <div style={{ marginTop: 10 }}>
            <button className="link" onClick={() => setPage('materials')}><BookOpen size={13} />品名库</button>
          </div>
        </div>
        <div className="queue-list">
          {groups.length === 0 && <div className="empty" style={{ marginTop: 40 }}>队列已清空，今天的单据都核对完了</div>}
          {groups.map((g) => (
            <div key={g.month}>
              <div className="q-group">{g.month || '未填日期'}</div>
              {g.list.map((r) => (
                <button
                  key={r.id}
                  className={`q-item ${currentId === r.id && !queueEditing ? 'active' : ''} ${queueEditing && selectedIds.has(r.id) ? 'selected' : ''}`}
                  onClick={() => (queueEditing ? toggleSelect(r.id) : setCurrentId(r.id))}
                >
                  <div className="q-top">
                    {queueEditing && (
                      <span className={`q-check ${selectedIds.has(r.id) ? 'on' : ''}`}>{selectedIds.has(r.id) ? '✓' : ''}</span>
                    )}
                    <span className="q-no num">{r.receipt_no || '未填单号'}</span>
                    <span className="pill amber" style={{ marginLeft: 'auto' }}>待审核</span>
                  </div>
                  <div className="q-meta">
                    <span>{r.date || '未填日期'}</span>
                    <span>{r.item_count} 行</span>
                    <span className="num">¥{(r.total_amount || 0).toFixed(2)}</span>
                  </div>
                </button>
              ))}
            </div>
          ))}
        </div>
      </aside>

      <div className="work">
        {currentId == null ? (
          <>
            <div className="work-head">
              <div className="field">
                <label>单号（已自动提取，可改）</label>
                <input className="num" value="" disabled placeholder="—" />
              </div>
              <div className="field">
                <label>日期（已自动提取，可改）</label>
                <input type="date" value="" disabled />
              </div>
              <span className="pill blue">识别自动提取</span>
              <div className="spacer" />
              <div className="work-actions">
                <button className="btn ghost sm" disabled><RotateCcw size={14} />重新识别</button>
                <button className="btn ghost sm" disabled>保存草稿</button>
                <button className="btn ok sm" disabled>确认入库</button>
              </div>
            </div>

            <div className="work-status">
              <span className="pill gray">暂无待审核单据</span>
              <span className="pill gray">首页上传识别后会进入待审队列</span>
            </div>

            <div className="split">
              <div className="orig">
                <div className="orig-head">上传原图（不裁剪）</div>
                <div className="orig-img">
                  <div className="empty" style={{ padding: '70px 0' }}>
                    <div style={{ opacity: .4 }}><Inbox size={40} strokeWidth={1.5} /></div>
                    <div>没有待审核单据</div>
                    <div style={{ fontSize: 12 }}>上传识别后原图会显示在这里</div>
                  </div>
                </div>
              </div>
              <div className="res">
                <div className="res-head">识别结果（逐格可改）</div>
                <div className="res-table-wrap" style={{ display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                  <div style={{ color: 'var(--text-3)', fontSize: 13 }}>识别结果将在这里显示</div>
                </div>
                <div className="res-foot">
                  <span>共 0 行</span>
                  <span className="total">合计 <span className="num">¥0.00</span></span>
                </div>
              </div>
            </div>
          </>
        ) : (
          <>
            <div className="work-head">
              <div className="field">
                <label>单号（已自动提取，可改）</label>
                <input className="num" value={no} onChange={(e) => setNo(e.target.value)} />
              </div>
              <div className="field">
                <label>日期（已自动提取，可改）</label>
                <input type="date" value={date} onChange={(e) => setDate(e.target.value)} />
              </div>
              <span className="pill blue">识别自动提取</span>
              <div className="spacer" />
              <div className="work-actions">
                <button className="btn ghost sm" onClick={handleReRecognize} disabled={loading || saving}><RotateCcw size={14} />重新识别</button>
                <button className="btn ghost sm" onClick={() => saveCurrent(false)} disabled={loading || saving}>保存草稿</button>
                <button className="btn ok sm" onClick={handleVerify} disabled={loading || saving}>
                  {saving ? '处理中…' : '确认入库'}
                </button>
              </div>
            </div>

            <div className="work-status">
              <span className="pill green">品名对齐 {aligned}/{nonHeader.length}</span>
              <span className={`pill ${notInLib > 0 ? 'amber' : 'gray'}`}>未入库 {notInLib}</span>
              {amountOk && <span className="pill green">金额识别正确</span>}
              {amountBad && <span className="pill gray" style={{ color: 'var(--err)', background: 'var(--err-soft)' }}>请审核金额</span>}
              {summary.issues > 0 && (
                <button
                  className="pill gray"
                  style={{ color: 'var(--err)', background: 'var(--err-soft)', cursor: 'pointer' }}
                  title="点击定位到第一条异常行"
                  onClick={() => setIssueFocusTick((t) => t + 1)}
                >
                  异常 {summary.issues}（点击定位）
                </button>
              )}
            </div>

            <div className="split">
              <div className="orig">
                <div className="orig-head">
                  上传原图（不裁剪）
                  <div className="orig-zoom">
                    <button onClick={() => setZoom((z) => Math.min(2.5, z + 0.25))} title="放大"><Plus size={14} /></button>
                    <button onClick={() => setZoom((z) => Math.max(0.5, z - 0.25))} title="缩小"><Minus size={14} /></button>
                    <button onClick={() => setZoom(1)}>1:1</button>
                  </div>
                </div>
                <div
                  ref={origRef}
                  className="orig-img"
                  style={{ cursor: 'grab' }}
                  onMouseDown={(e) => setDragStart({ x: e.clientX, y: e.clientY, px: pan.x, py: pan.y })}
                  onMouseMove={(e) => {
                    if (dragStart) setPan({ x: dragStart.px + e.clientX - dragStart.x, y: dragStart.py + e.clientY - dragStart.y });
                  }}
                  onMouseUp={() => setDragStart(null)}
                  onMouseLeave={() => setDragStart(null)}
                >
                  {imageUrl ? (
                    <img
                      src={imageUrl}
                      alt="单据原图"
                      style={{
                        transform: `translate(${pan.x}px, ${pan.y}px) scale(${zoom})`,
                        transformOrigin: 'center',
                        transition: dragStart ? 'none' : 'transform 0.1s ease-out',
                        pointerEvents: 'none',
                        userSelect: 'none',
                      }}
                    />
                  ) : (
                    <div style={{ color: 'var(--text-3)', fontSize: 13 }}>无原图</div>
                  )}
                </div>
              </div>
              <div className="res">
                <div className="res-head">
                  识别结果（逐格可改）
                  <span className="pill gray">Enter 下一行 · Tab 下一格 · Esc 取消</span>
                </div>
                {loading ? (
                  <div className="empty" style={{ margin: '40px auto' }}>加载中…</div>
                ) : (
                  <ReviewTable items={liveItems} onChange={setItems} headerRows={headerRows} resetSignal={tableReset} recTotal={recTotal} materialSet={materialSet} focusIssueTick={issueFocusTick} />
                )}
                <div className="res-foot">
                  <span>共 {items.length} 行</span>
                  <span className="total">合计 <span className="num">¥{items.reduce((s, it) => s + (it.qty || 0) * (it.price || 0), 0).toFixed(2)}</span></span>
                </div>
              </div>
            </div>
          </>
        )}
      </div>

      {requireDialog && (
        <div className="modal-mask show" onClick={() => setRequireDialog(false)}>
          <div className="modal" style={{ maxWidth: 340 }}>
            <div className="modal-head">
              <div className="modal-title">无法确认入库</div>
              <button className="modal-close" onClick={() => setRequireDialog(false)}>✕</button>
            </div>
            <div className="modal-body" style={{ padding: '18px 20px', fontSize: 13, color: 'var(--text-2)' }}>
              请先填写单号和日期
            </div>
            <div style={{ display: 'flex', justifyContent: 'flex-end', padding: '0 20px 16px', gap: 8 }}>
              <button className="btn" onClick={() => setRequireDialog(false)}>知道了</button>
            </div>
          </div>
        </div>
      )}

      <ConfirmDialog
        open={deleteOpen}
        title="删除确认"
        message={`确定删除选中的 ${selectedIds.size} 张待审核单据？删除后不可恢复。`}
        onConfirm={doDeleteSelected}
        onCancel={() => setDeleteOpen(false)}
      />
    </div>
  );
}
