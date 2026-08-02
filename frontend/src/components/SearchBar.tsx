// SteelDigitize Pro — 历史搜索栏
import { useState, type FormEvent } from 'react';
import type { HistoryQuery } from '../types';

interface Props {
  onSearch: (query: HistoryQuery) => void;
  loading?: boolean;
}

export default function SearchBar({ onSearch, loading }: Props) {
  const [dateFrom, setDateFrom] = useState('');
  const [dateTo, setDateTo] = useState('');
  const [receiptNo, setReceiptNo] = useState('');
  const [status, setStatus] = useState('all');

  const handleSubmit = (e: FormEvent) => {
    e.preventDefault();
    onSearch({
      page: 1,
      date_from: dateFrom || undefined,
      date_to: dateTo || undefined,
      receipt_no: receiptNo || undefined,
      status: status || undefined,
    });
  };

  return (
    <form onSubmit={handleSubmit} className="flex flex-wrap gap-3 items-end mb-stack-md">
      <div className="flex flex-col gap-1">
        <label className="text-[10px] uppercase text-on-surface-variant font-medium">开始日期</label>
        <input
          type="date"
          value={dateFrom}
          onChange={(e) => setDateFrom(e.target.value)}
          className="bg-white border border-outline-variant rounded px-3 py-1.5 text-label-sm focus:border-primary transition-colors"
        />
      </div>
      <div className="flex flex-col gap-1">
        <label className="text-[10px] uppercase text-on-surface-variant font-medium">结束日期</label>
        <input
          type="date"
          value={dateTo}
          onChange={(e) => setDateTo(e.target.value)}
          className="bg-white border border-outline-variant rounded px-3 py-1.5 text-label-sm focus:border-primary transition-colors"
        />
      </div>
      <div className="flex flex-col gap-1">
        <label className="text-[10px] uppercase text-on-surface-variant font-medium">单号</label>
        <input
          type="text"
          value={receiptNo}
          onChange={(e) => setReceiptNo(e.target.value)}
          placeholder="模糊搜索"
          className="bg-white border border-outline-variant rounded px-3 py-1.5 text-label-sm focus:border-primary transition-colors w-32"
        />
      </div>
      <div className="flex flex-col gap-1">
        <label className="text-[10px] uppercase text-on-surface-variant font-medium">状态</label>
        <select
          value={status}
          onChange={(e) => setStatus(e.target.value)}
          className="bg-white border border-outline-variant rounded px-3 py-1.5 text-label-sm focus:border-primary transition-colors"
        >
          <option value="all">全部</option>
          <option value="pending">待处理</option>
          <option value="verified">已核对</option>
          <option value="exported">已导出</option>
        </select>
      </div>
      <button
        type="submit"
        disabled={loading}
        className="bg-primary text-white px-6 py-1.5 rounded-lg font-medium text-label-sm hover:bg-primary-container transition-colors disabled:opacity-50"
      >
        {loading ? '搜索中...' : '搜索'}
      </button>
    </form>
  );
}
