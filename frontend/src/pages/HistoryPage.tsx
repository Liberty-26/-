// SteelDigitize Pro — 资料库页（书架账本总览 + 月份单据列表）
import { Fragment, useState, useEffect, useCallback } from 'react';
import { getHistory, getHistoryMonths, getReceiptDetail, deleteReceipt } from '../utils/api';
import { formatAmount } from '../utils/format';
import { useToast } from '../hooks/useToast';
import Pagination from '../components/Pagination';
import ConfirmDialog from '../components/ConfirmDialog';
import type { ReceiptSummary, Receipt, ReceiptItem, HistoryQuery, MonthStat } from '../types';

// 未填日期账本：months 接口中 month='' 表示空日期单据
const EMPTY_MONTH = '';

export default function HistoryPage() {
  const { showToast } = useToast();
  // 视图切换：shelf = 账本总览，list = 单据列表（某月 / 全库搜索）
  const [view, setView] = useState<'shelf' | 'list'>('shelf');
  // 当前打开的账本：null = 全库（书架搜索），'2026-07' = 某月，'' = 未填日期
  const [selectedMonth, setSelectedMonth] = useState<string | null>(null);
  const [months, setMonths] = useState<MonthStat[]>([]);
  const [monthsLoading, setMonthsLoading] = useState(false);
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
  const [expanding, setExpanding] = useState(false);
  const [fullImage, setFullImage] = useState<string | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<number | null>(null);

  // 是否处于"某月/未填日期"账本列表（区别于全库搜索结果列表）
  const isMonthView = view === 'list' && selectedMonth !== null;

  // 加载账本列表（书架）
  const loadMonths = useCallback(async () => {
    setMonthsLoading(true);
    const res = await getHistoryMonths();
    if (res.success && res.data) setMonths(res.data.months);
    else showToast(res.error || '加载账本失败', 'error');
    setMonthsLoading(false);
  }, [showToast]);

  useEffect(() => { loadMonths(); }, [loadMonths]);

  // 按当前视图拼查询参数：月份/未填日期视图的日期条件由代码锁死
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

  // 拉取列表。notifyEmptySearch：仅用户点搜索时提示"无此单据"，内部刷新（删除/翻页）不打扰
  const fetchList = useCallback(async (q: HistoryQuery, opts?: { notifyEmptySearch?: boolean }) => {
    setLoading(true);
    const res = await getHistory(q);
    if (res.success && res.data) {
      const d = res.data;
      if (opts?.notifyEmptySearch && isMonthView && q.receipt_no && d.total === 0) {
        // 账本内按单号搜索无结果：不替换列表，仅提示（用户需求：不跳转、不显示结果）
        showToast(selectedMonth === EMPTY_MONTH ? '未填日期单据中无此单号' : '当前月份无此单据', 'info');
      } else if (d.items.length === 0 && d.total > 0 && d.page > 1) {
        // 删除后当前页变空：自动回退到最后一页
        fetchList({ ...q, page: Math.ceil(d.total / d.page_size) });
        return;
      } else {
        setItems(d.items);
        setTotal(d.total);
        setPage(d.page);
      }
    } else {
      showToast(res.error || '查询失败', 'error');
    }
    setLoading(false);
  }, [isMonthView, selectedMonth, showToast]);

  // 书架搜索 → 进入全库列表；列表内搜索 → 当前视图刷新（页码重置为 1）
  const handleSearch = () => {
    if (view === 'shelf') setView('list');
    fetchList({ ...buildQuery(), page: 1, page_size: pageSize }, { notifyEmptySearch: true });
  };

  // 点击账本卡片进入该月/未填日期列表（setState 异步，查询参数直接构造，不能依赖 buildQuery 新值）
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

  // 返回书架：刷新账本统计（删除后计数/金额可能已变化）
  const handleBackToShelf = () => {
    setView('shelf');
    setSelectedMonth(null);
    setExpandedId(null);
    setExpandedDetail(null);
    loadMonths();
  };

  // 翻页：当前筛选条件 + 目标页码（修复原 onPageChange 永远请求第 1 页的 bug）
  const handlePageChange = (p: number) => {
    fetchList({ ...buildQuery(), page: p, page_size: pageSize });
  };

  const handlePageSizeChange = (s: number) => {
    setPageSize(s);
    fetchList({ ...buildQuery(), page: 1, page_size: s });
  };

  const handleToggleExpand = async (id: number) => {
    if (expandedId === id) { setExpandedId(null); setExpandedDetail(null); return; }
    setExpandedId(id); setExpanding(true);
    const res = await getReceiptDetail(id);
    if (res.success && res.data) setExpandedDetail(res.data);
    else { showToast('加载详情失败', 'error'); setExpandedId(null); }
    setExpanding(false);
  };

  const handleDelete = async () => {
    if (deleteTarget === null) return;
    const res = await deleteReceipt(deleteTarget);
    if (res.success) {
      showToast('删除成功', 'success');
      setDeleteTarget(null);
      // 留在当前列表，刷新当前页（若该页变空会自动回退）
      fetchList({ ...buildQuery(), page: page, page_size: pageSize });
    } else showToast(res.error || '删除失败', 'error');
  };

  const statusBadge = (status: string) => {
    const map: Record<string, { label: string; cls: string }> = {
      pending: { label: '待处理', cls: 'bg-primary-fixed text-primary-fixed-variant' },
      verified: { label: '已核对', cls: 'bg-success-container text-on-success-container' },
      exported: { label: '已导出', cls: 'bg-primary text-on-primary' },
    };
    const s = map[status] || map.pending;
    return <span className={`px-2.5 py-0.5 rounded-full text-label-sm ${s.cls}`}>{s.label}</span>;
  };

  // 列表视图标题：资料库 › 2026年7月 / 资料库 › 未填日期
  const listTitle = (() => {
    if (selectedMonth === EMPTY_MONTH) return '未填日期';
    if (selectedMonth) {
      const [y, mo] = selectedMonth.split('-');
      return `${y}年${Number(mo)}月`;
    }
    return '';
  })();

  const searchBar = (showDateStatus: boolean) => (
    <div className="flex flex-wrap gap-3 items-end mb-stack-md shrink-0">
      {showDateStatus && (
        <>
          <div className="flex flex-col gap-1">
            <label className="text-[10px] uppercase text-on-surface-variant font-medium">日期</label>
            <input type="date" value={dateInput} onChange={e => setDateInput(e.target.value)}
              className="bg-white border border-outline-variant rounded px-3 py-1.5 text-label-sm focus:border-primary w-36" />
          </div>
          <div className="flex flex-col gap-1">
            <label className="text-[10px] uppercase text-on-surface-variant font-medium">状态</label>
            <select value={status} onChange={e => setStatus(e.target.value)}
              className="bg-white border border-outline-variant rounded px-3 py-1.5 text-label-sm focus:border-primary">
              <option value="all">全部</option><option value="pending">待处理</option>
              <option value="verified">已核对</option><option value="exported">已导出</option>
            </select>
          </div>
        </>
      )}
      <div className="flex flex-col gap-1">
        <label className="text-[10px] uppercase text-on-surface-variant font-medium">单号</label>
        <input type="text" value={receiptNo} onChange={e => setReceiptNo(e.target.value)} placeholder="模糊搜索"
          className="bg-white border border-outline-variant rounded px-3 py-1.5 text-label-sm focus:border-primary w-32" />
      </div>
      <button onClick={handleSearch} disabled={loading}
        className="bg-primary text-white px-6 py-1.5 rounded-lg font-medium text-label-sm hover:bg-primary-container disabled:opacity-50">
        {loading ? '搜索中...' : '搜索'}
      </button>
    </div>
  );

  return (
    <div className="flex-1 p-margin-page overflow-auto h-full flex flex-col">
      <h2 className="font-headline-md text-headline-md text-on-surface mb-stack-md">
        {isMonthView ? <>资料库 › {listTitle}</> : '资料库'}
      </h2>

      {view === 'shelf' ? (
        <div key="shelf" className="animate-fadein flex flex-col flex-1 min-h-0">
          {/* 书架搜索：日期 + 单号 + 状态，全库范围 */}
          {searchBar(true)}
          {/* 账本书架：新月份在前（后端 DESC），flex-wrap 左为新、上为新 */}
          <div className="flex-1 overflow-y-auto p-6 bg-surface-container-low/50 rounded-lg border border-outline-variant/40 content-start">
            {months.length === 0 ? (
              <div className="w-full text-center py-16 text-on-surface-variant/50 text-label-sm">
                {monthsLoading ? '加载中...' : '暂无数据'}
              </div>
            ) : (
              <div className="flex flex-wrap gap-6">
                {months.map(m => {
                  const isEmpty = m.month === EMPTY_MONTH;
                  const [y, mo] = isEmpty ? ['', ''] : m.month.split('-');
                  return (
                    <button key={m.month || '__empty__'} onClick={() => handleEnterMonth(m.month)}
                      className={`w-48 h-64 rounded-lg bg-white border text-left overflow-hidden
                        transition-all duration-500 ease-out hover:-translate-y-2 hover:shadow-[0_12px_28px_-8px_rgba(0,0,0,0.3)]
                        motion-reduce:transition-none ${
                        isEmpty ? 'border-dashed border-outline-variant opacity-80' : 'border-outline-variant/70 shadow-[0_2px_6px_rgba(0,0,0,0.08)]'
                      }`}>
                      {/* 书脊色条 */}
                      <div className={`h-2 w-full ${isEmpty ? 'bg-outline-variant' : 'bg-primary'}`} />
                      {/* 封面主体 */}
                      <div className="flex flex-col items-center justify-center px-4 h-[calc(100%-8px)]">
                        {isEmpty ? (
                          <>
                            <span className="text-headline-md font-bold text-outline">未填日期</span>
                            <span className="mt-1 text-label-sm text-on-surface-variant">无日期单据</span>
                          </>
                        ) : (
                          <>
                            <span className="text-label-sm text-on-surface-variant/70 tracking-widest">{y}</span>
                            <span className="text-headline-lg font-bold text-on-surface mt-1">{Number(mo)}月</span>
                          </>
                        )}
                        <div className="w-12 border-t border-outline-variant/60 my-4" />
                        <span className="text-label-sm text-on-surface-variant">共 {m.count} 张单据</span>
                        <span className="text-label-sm text-on-surface-variant mt-1.5">总金额 ¥{formatAmount(m.total_amount)}</span>
                      </div>
                    </button>
                  );
                })}
              </div>
            )}
          </div>
        </div>
      ) : (
        <div key={`list-${selectedMonth ?? 'all'}`} className="animate-fadein flex flex-col flex-1 min-h-0">
          <button onClick={handleBackToShelf}
            className="mb-4 self-start px-5 py-2.5 text-label-sm bg-primary text-white rounded-lg font-semibold
              transition-all duration-300 ease-[cubic-bezier(0.16,1,0.3,1)] hover:bg-primary-container flex items-center gap-2">
            <span className="material-symbols-outlined text-base">arrow_back</span>
            返回资料库
          </button>
          {/* 月份/未填日期视图只保留单号搜索；全库搜索结果保留三个条件 */}
          {searchBar(selectedMonth === null)}
          <div className="border border-outline-variant rounded overflow-hidden bg-white flex-1 flex flex-col">
            <div className="overflow-y-auto flex-1">
              <table className="w-full border-collapse zebra-table">
                <thead className="sticky top-0 bg-surface-container-high border-b border-outline-variant z-10">
                  <tr>
                    <th className="p-2 text-left text-label-sm text-outline-variant font-medium w-12">序号</th>
                    <th className="p-2 text-left text-label-sm text-outline-variant font-medium">日期</th>
                    <th className="p-2 text-left text-label-sm text-outline-variant font-medium">单号</th>
                    <th className="p-2 text-left text-label-sm text-outline-variant font-medium">状态</th>
                    <th className="p-2 text-left text-label-sm text-outline-variant font-medium">物料概览</th>
                    <th className="p-2 text-right text-label-sm text-outline-variant font-medium">合计金额</th>
                    <th className="p-2 text-left text-label-sm text-outline-variant font-medium">操作人</th>
                    <th className="p-2 text-center text-label-sm text-outline-variant font-medium w-28">操作</th>
                  </tr>
                </thead>
                <tbody>
                  {items.length === 0 && !loading ? (
                    <tr><td colSpan={8} className="p-8 text-center text-on-surface-variant text-label-sm">暂无数据</td></tr>
                  ) : (<>
                    {items.map((item, idx) => (
                      <Fragment key={item.id}>
                        <tr className="border-b border-outline-variant/30">
                          <td className="p-2 text-table-cell font-mono">{(page-1)*pageSize+idx+1}</td>
                          <td className="p-2 text-table-cell">{item.date || '-'}</td>
                          <td className="p-2 text-table-cell font-mono">{item.receipt_no}</td>
                          <td className="p-2">{statusBadge(item.status)}</td>
                          <td className="p-2 text-table-cell text-on-surface-variant max-w-[200px] truncate" title={item.summary}>{item.summary||'-'}</td>
                          <td className="p-2 text-table-cell text-right font-mono font-bold">{formatAmount(item.total_amount)}</td>
                          <td className="p-2 text-table-cell text-on-surface-variant">{item.operator}</td>
                          <td className="p-2 text-center"><div className="flex gap-1 justify-center">
                            <button onClick={()=>handleToggleExpand(item.id)} className="text-primary text-label-sm hover:underline">{expandedId===item.id?'收起':'查看'}</button>
                            <button onClick={()=>setDeleteTarget(item.id)} className="text-error text-label-sm hover:underline">删除</button>
                          </div></td>
                        </tr>
                        {expandedId===item.id && expandedDetail && (
                          <tr className="bg-surface-container-low">
                            <td colSpan={8} className="p-4">
                              {expanding ? <p className="text-label-sm text-on-surface-variant">加载中...</p> : (
                                <div className="space-y-3">
                                  {expandedDetail.image_path && (
                                    <div className="flex items-center gap-2">
                                      <span className="text-label-sm text-outline-variant">单据照片：</span>
                                      <img src={`/uploads/${expandedDetail.image_path}`} alt="单据"
                                        className="max-h-32 rounded border border-outline-variant cursor-pointer hover:opacity-80"
                                        onClick={()=>setFullImage('/uploads/'+expandedDetail.image_path!)} />
                                    </div>
                                  )}
                                  <table className="w-full border-collapse border border-outline-variant/30 text-table-cell">
                                    <thead className="bg-surface-container-high"><tr>
                                      <th className="p-1.5 text-left text-label-sm text-outline-variant">序号</th>
                                      <th className="p-1.5 text-left text-label-sm text-outline-variant">品种</th>
                                      <th className="p-1.5 text-left text-label-sm text-outline-variant">规格</th>
                                      <th className="p-1.5 text-left text-label-sm text-outline-variant">单位</th>
                                      <th className="p-1.5 text-right text-label-sm text-outline-variant">数量</th>
                                      <th className="p-1.5 text-right text-label-sm text-outline-variant">单价</th>
                                      <th className="p-1.5 text-right text-label-sm text-outline-variant">金额</th>
                                    </tr></thead>
                                    <tbody>
                                      {expandedDetail.items?.map((it:ReceiptItem,i:number)=>(
                                        <tr key={i} className="border-b border-outline-variant/20">
                                          <td className="p-1.5 font-mono">{it.row_num||i+1}</td>
                                          <td className="p-1.5">{it.name}</td><td className="p-1.5">{it.spec}</td><td className="p-1.5">{it.unit}</td>
                                          <td className="p-1.5 text-right font-mono">{it.qty}</td><td className="p-1.5 text-right font-mono">{it.price}</td>
                                          <td className="p-1.5 text-right font-mono font-bold">{formatAmount(it.amount||it.qty*it.price)}</td>
                                        </tr>
                                      ))}
                                    </tbody>
                                  </table>
                                </div>
                              )}
                            </td>
                          </tr>
                        )}
                      </Fragment>
                    ))}
                  </>)}
                </tbody>
              </table>
            </div>
          </div>
          <Pagination page={page} pageSize={pageSize} total={total}
            onPageChange={handlePageChange} onPageSizeChange={handlePageSizeChange} />
        </div>
      )}

      <ConfirmDialog open={deleteTarget!==null} title="删除确认" message="确定删除此单据？" onConfirm={handleDelete} onCancel={()=>setDeleteTarget(null)} />
      {fullImage && (
        <div className="fixed inset-0 z-50 bg-black/80 flex items-center justify-center cursor-pointer" onClick={()=>setFullImage(null)}>
          <img src={fullImage} alt="单据原图" className="max-w-[90vw] max-h-[90vh] object-contain rounded shadow-2xl" onClick={e=>e.stopPropagation()} />
        </div>
      )}
    </div>
  );
}
