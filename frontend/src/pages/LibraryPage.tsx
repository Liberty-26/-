// SteelDigitize Pro — 资料库（账本书架 + 月份单据列表，保留原版搜索/展开/删除/分页细节）
import { Fragment, useState, useEffect, useCallback } from 'react';
import { getHistory, getHistoryMonths, getReceiptDetail, updateReceipt } from '../utils/api';
import { useToast } from '../hooks/useToast';
import Pagination from '../components/Pagination';
import type { ReceiptSummary, Receipt, ReceiptItem, HistoryQuery, MonthStat } from '../types';

const EMPTY_MONTH = '';

export default function LibraryPage() {
  const { showToast } = useToast();
  const [view, setView] = useState<'shelf' | 'list'>('shelf');
  const [selectedMonth, setSelectedMonth] = useState<string | null>(null);
  const [months, setMonths] = useState<MonthStat[]>([]);
  const [items, setItems] = useState<ReceiptSummary[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(10);
  const [loading, setLoading] = useState(false);
  const [dateInput, setDateInput] = useState('');
  const [receiptNo, setReceiptNo] = useState('');
  const [status, setStatus] = useState('all');
  const [expandedId, setExpandedId] = useState<number | null>(null);
  const [expandedDetail, setExpandedDetail] = useState<Receipt | null>(null);
  const [fullImage, setFullImage] = useState<string | null>(null);
  const [editNo, setEditNo] = useState('');
  const [editDate, setEditDate] = useState('');
  const [savingMeta, setSavingMeta] = useState(false);

  const isMonthView = view === 'list' && selectedMonth !== null;

  const loadMonths = useCallback(async () => {
    const res = await getHistoryMonths();
    if (res.success && res.data) setMonths(res.data.months);
    else showToast(res.error || '加载账本失败', 'error');
  }, [showToast]);

  useEffect(() => { loadMonths(); }, [loadMonths]);

  const buildQuery = useCallback((): HistoryQuery => {
    const q: HistoryQuery = {};
    if (view === 'list' && selectedMonth !== null) {
      if (selectedMonth) {
        const [y, mo] = selectedMonth.split('-');
        q.date_from = `${y}-${mo}-01`;
        q.date_to = `${y}-${mo}-31`;
      } else {
        q.date_empty = true;
      }
      if (receiptNo) q.receipt_no = receiptNo;
    } else {
      if (dateInput) q.date_from = dateInput;
      if (receiptNo) q.receipt_no = receiptNo;
      if (status !== 'all') q.status = status;
    }
    return q;
  }, [view, selectedMonth, dateInput, receiptNo, status]);

  const fetchList = useCallback(async (q: HistoryQuery) => {
    setLoading(true);
    const res = await getHistory(q);
    if (res.success && res.data) {
      const d = res.data;
      if (d.items.length === 0 && d.total > 0 && d.page > 1) {
        fetchList({ ...q, page: Math.ceil(d.total / d.page_size) });
      } else {
        setItems(d.items);
        setTotal(d.total);
        setPage(d.page);
      }
    } else {
      showToast(res.error || '查询失败', 'error');
    }
    setLoading(false);
  }, [showToast]);

  const handleSearch = () => {
    if (view === 'shelf') setView('list');
    fetchList({ ...buildQuery(), page: 1, page_size: pageSize });
  };

  const handleEnterMonth = (month: string) => {
    setSelectedMonth(month);
    setView('list');
    setReceiptNo('');
    setDateInput('');
    setExpandedId(null);
    setExpandedDetail(null);
    const q: HistoryQuery = {};
    if (month) {
      const [y, mo] = month.split('-');
      q.date_from = `${y}-${mo}-01`;
      q.date_to = `${y}-${mo}-31`;
    } else {
      q.date_empty = true;
    }
    fetchList({ ...q, page: 1, page_size: pageSize });
  };

  const handleBackToShelf = () => {
    setView('shelf');
    setSelectedMonth(null);
    setExpandedId(null);
    setExpandedDetail(null);
    loadMonths();
  };

  const handleToggleExpand = async (id: number) => {
    if (expandedId === id) { setExpandedId(null); setExpandedDetail(null); return; }
    setExpandedId(id);
    const res = await getReceiptDetail(id);
    if (res.success && res.data) {
      setExpandedDetail(res.data);
      setEditNo(res.data.receipt_no || '');
      setEditDate(res.data.date || '');
    }
    else { showToast('加载详情失败', 'error'); setExpandedId(null); }
  };

  // 资料库只读：唯一允许的修改是日期与单号；明细修改必须去审核区
  const handleSaveMeta = async () => {
    if (expandedId == null || !expandedDetail) return;
    if (!editDate || !editNo.trim()) {
      showToast('请先填写单号和日期', 'warning');
      return;
    }
    setSavingMeta(true);
    const res = await updateReceipt(expandedId, {
      receipt_no: editNo.trim(),
      date: editDate,
      items: (expandedDetail.items || []).map((it) => ({
        name: it.name || '', spec: it.spec || '', unit: it.unit || '',
        qty: it.qty || 0, price: it.price || 0,
      })),
    });
    setSavingMeta(false);
    if (res.success) {
      showToast('单号/日期已保存', 'success');
      setExpandedDetail({ ...expandedDetail, receipt_no: editNo.trim(), date: editDate });
      fetchList({ ...buildQuery(), page, page_size: pageSize });
      loadMonths();
    } else {
      showToast(res.error || '保存失败', 'error');
    }
  };

  const statusBadge = (status: string) => {
    const map: Record<string, { label: string; cls: string }> = {
      pending: { label: '待审核', cls: 'blue' },
      verified: { label: '已核对', cls: 'green' },
      exported: { label: '已导出', cls: 'gray' },
    };
    const s = map[status] || map.pending;
    return <span className={`pill ${s.cls}`}>{s.label}</span>;
  };

  const listTitle = (() => {
    if (selectedMonth === EMPTY_MONTH) return '未填日期';
    if (selectedMonth) {
      const [y, mo] = selectedMonth.split('-');
      return `${y}年${Number(mo)}月`;
    }
    return '';
  })();

  const totalAmount = months.reduce((s, m) => s + (m.total_amount || 0), 0);

  const searchBar = (showDateStatus: boolean) => (
    <div className="lib-toolbar">
      {showDateStatus && (
        <>
          <div className="field"><label>日期</label><input type="date" value={dateInput} onChange={(e) => setDateInput(e.target.value)} /></div>
          <div className="field">
            <label>状态</label>
            <select value={status} onChange={(e) => setStatus(e.target.value)}>
              <option value="all">全部</option>
              <option value="pending">待审核</option>
              <option value="verified">已核对</option>
              <option value="exported">已导出</option>
            </select>
          </div>
        </>
      )}
      <div className="field"><label>单号</label><input placeholder="模糊搜索" value={receiptNo} onChange={(e) => setReceiptNo(e.target.value)} /></div>
      <button className="btn" onClick={handleSearch} disabled={loading}>{loading ? '搜索中…' : '搜索'}</button>
      {isMonthView && (
        <button className="btn ghost" onClick={handleBackToShelf}>‹ 返回书架</button>
      )}
    </div>
  );

  return (
    <div className="plain">
      <div className="page-head">
        <div>
          <div className="page-title">{isMonthView ? <>资料库 › {listTitle}</> : '资料库'}</div>
          <div className="page-sub">已核对入库的单据按月归档，像账本一样摆放</div>
        </div>
        <div className="view-toggle" style={{ marginLeft: 'auto' }}>
          <button className={view === 'shelf' ? 'active' : ''} onClick={() => setView('shelf')}>书架</button>
          <button className={view === 'list' ? 'active' : ''} onClick={() => { setView('list'); fetchList({ ...buildQuery(), page: 1, page_size: pageSize }); }}>列表</button>
        </div>
      </div>

      {view === 'shelf' ? (
        <>
          {searchBar(true)}
          <div className="stats-strip">
            <div className="stat"><span className="v num">{months.reduce((s, m) => s + m.count, 0)}</span><span className="l">全部单据</span></div>
            <div className="stat"><span className="v num">{months.length}</span><span className="l">账本数量</span></div>
            <div className="stat"><span className="v"><span className="num">¥{totalAmount.toFixed(2)}</span></span><span className="l">合计金额（代码计算）</span></div>
          </div>
          <div className="year-sec">
            <div className="year-label">全部账本</div>
            {months.length === 0 && (
              <div className="empty" style={{ padding: '48px 0' }}>
                {loading ? '加载中…' : '还没有入库单据，识别后确认入库就会出现在这里'}
              </div>
            )}
            <div className="books">
              {months.map((m) => {
                const isEmpty = m.month === EMPTY_MONTH;
                const [y, mo] = isEmpty ? ['', ''] : m.month.split('-');
                return (
                  <button key={m.month || '__empty__'} className="book" onClick={() => handleEnterMonth(m.month)}>
                    <div className={`spine ${isEmpty ? 'warn' : 'teal'}`} />
                    <div className="cover">
                      {isEmpty ? (
                        <>
                          <div className="month">未填日期</div>
                          <div className="meta"><span>{m.count} 张单据</span><span>需补日期</span></div>
                          <div className="amt">待补充日期后归档</div>
                        </>
                      ) : (
                        <>
                          <div className="month">{y}年{Number(mo)}月</div>
                          <div className="meta"><span>{m.count} 张单据</span></div>
                          <div className="amt">合计 <span className="num">¥{(m.total_amount || 0).toFixed(2)}</span></div>
                        </>
                      )}
                      <span className="book-cta">打开账本 →</span>
                    </div>
                  </button>
                );
              })}
            </div>
          </div>
        </>
      ) : (
        <>
          {searchBar(selectedMonth === null)}
          <div className="tbl">
            <table>
              <thead>
                <tr>
                  <th style={{ width: 48 }}>序号</th><th>日期</th><th>单号</th><th>状态</th>
                  <th>物料概览</th><th style={{ textAlign: 'right' }}>合计金额</th><th>操作人</th><th style={{ width: 110, textAlign: 'center' }}>操作</th>
                </tr>
              </thead>
              <tbody>
                {items.length === 0 && !loading && (
                  <tr><td colSpan={8} style={{ padding: 28, textAlign: 'center', color: 'var(--text-3)' }}>暂无数据</td></tr>
                )}
                {items.map((item, idx) => (
                  <Fragment key={item.id}>
                    <tr>
                      <td className="num" style={{ color: 'var(--text-3)' }}>{(page - 1) * pageSize + idx + 1}</td>
                      <td>{item.date || '-'}</td>
                      <td className="num">{item.receipt_no || '—'}</td>
                      <td>{statusBadge(item.status)}</td>
                      <td style={{ color: 'var(--text-2)', maxWidth: 220, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }} title={item.summary}>{item.summary || '-'}</td>
                      <td className="num" style={{ textAlign: 'right', fontWeight: 700 }}>¥{(item.total_amount || 0).toFixed(2)}</td>
                      <td style={{ color: 'var(--text-2)' }}>{item.operator}</td>
                      <td style={{ textAlign: 'center' }}>
                        <button className="link" onClick={() => handleToggleExpand(item.id)}>{expandedId === item.id ? '收起' : '查看'}</button>
                      </td>
                    </tr>
                    {expandedId === item.id && expandedDetail && (
                      <tr style={{ background: '#fafbfc' }}>
                        <td colSpan={8} style={{ padding: 14 }}>
                          <div style={{ display: 'flex', gap: 16, alignItems: 'flex-start', flexWrap: 'wrap' }}>
                            <div style={{ display: 'flex', flexDirection: 'column', gap: 8, minWidth: 180 }}>
                              <label style={{ fontSize: 11, color: 'var(--text-3)' }}>单号（资料库仅可改日期与单号）</label>
                              <input
                                className="num"
                                style={{ border: '1px solid var(--border)', borderRadius: 8, padding: '6px 8px', fontSize: 13 }}
                                value={editNo}
                                onChange={(e) => setEditNo(e.target.value)}
                              />
                              <label style={{ fontSize: 11, color: 'var(--text-3)' }}>日期</label>
                              <input
                                type="date"
                                style={{ border: '1px solid var(--border)', borderRadius: 8, padding: '6px 8px', fontSize: 13 }}
                                value={editDate}
                                onChange={(e) => setEditDate(e.target.value)}
                              />
                              <button className="btn sm" onClick={handleSaveMeta} disabled={savingMeta}>
                                {savingMeta ? '保存中…' : '保存单号/日期'}
                              </button>
                              <div style={{ fontSize: 11, color: 'var(--text-3)' }}>明细修改请到审核区</div>
                            </div>
                            {expandedDetail.image_path && (
                              <img
                                src={'/uploads/' + expandedDetail.image_path}
                                alt="单据"
                                style={{ maxHeight: 130, borderRadius: 8, border: '1px solid var(--border)', cursor: 'zoom-in' }}
                                onClick={() => setFullImage('/uploads/' + expandedDetail.image_path!)}
                              />
                            )}
                            <table className="res-table" style={{ maxWidth: 720 }}>
                              <thead><tr><th>序号</th><th>品名</th><th>规格</th><th>单位</th><th style={{ textAlign: 'right' }}>数量</th><th style={{ textAlign: 'right' }}>单价</th><th style={{ textAlign: 'right' }}>金额</th></tr></thead>
                              <tbody>
                                {(expandedDetail.items || []).map((it: ReceiptItem, i: number) => (
                                  <tr key={i}>
                                    <td className="num" style={{ color: 'var(--text-3)' }}>{it.row_num || i + 1}</td>
                                    <td>{it.name}</td><td>{it.spec}</td><td>{it.unit}</td>
                                    <td className="num" style={{ textAlign: 'right' }}>{it.qty}</td>
                                    <td className="num" style={{ textAlign: 'right' }}>{it.price}</td>
                                    <td className="num" style={{ textAlign: 'right', fontWeight: 700 }}>¥{(it.amount || it.qty * it.price).toFixed(2)}</td>
                                  </tr>
                                ))}
                              </tbody>
                            </table>
                          </div>
                        </td>
                      </tr>
                    )}
                  </Fragment>
                ))}
              </tbody>
            </table>
          </div>
          <Pagination page={page} pageSize={pageSize} total={total} onPageChange={(p) => fetchList({ ...buildQuery(), page: p, page_size: pageSize })} onPageSizeChange={(s) => { setPageSize(s); fetchList({ ...buildQuery(), page: 1, page_size: s }); }} />
        </>
      )}

      {fullImage && (
        <div className="img-mask" onClick={() => setFullImage(null)}>
          <img src={fullImage} alt="单据原图" />
        </div>
      )}
    </div>
  );
}
