// SteelDigitize Pro — 技能参数卡（通用数据选择器：技能声明要什么数据，界面自动生成选择面板）
import { useEffect, useState } from 'react';
import { getHistory } from '../utils/api';
import { useToast } from '../hooks/useToast';
import type { ReceiptSummary } from '../types';
import { X } from 'lucide-react';

interface Props {
  open: boolean;
  onClose: () => void;
  onRun: (text: string, selectedIds: number[]) => void;
}

type Filter = 'all' | 'verified' | 'pending' | 'month8';

export default function SkillModal({ open, onClose, onRun }: Props) {
  const { showToast } = useToast();
  const [receipts, setReceipts] = useState<ReceiptSummary[]>([]);
  const [filter, setFilter] = useState<Filter>('all');
  const [picked, setPicked] = useState<Set<number>>(new Set());
  const [sheet, setSheet] = useState('水电');

  useEffect(() => {
    if (!open) return;
    setPicked(new Set());
    getHistory({ page: 1, page_size: 50 }).then((res) => {
      if (res.success && res.data) setReceipts(res.data.items);
      else showToast(res.error || '加载单据失败', 'error');
    });
  }, [open, showToast]);

  if (!open) return null;

  const filtered = receipts.filter((r) => {
    if (filter === 'verified' && r.status !== 'verified') return false;
    if (filter === 'pending' && r.status !== 'pending') return false;
    if (filter === 'month8' && !r.date.startsWith('2026-08') && !r.date.startsWith('2025-08')) return false;
    return true;
  });
  const pickedList = receipts.filter((r) => picked.has(r.id));
  const sum = pickedList.reduce((s, r) => s + (r.total_amount || 0), 0);

  const toggle = (id: number) => {
    const next = new Set(picked);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    setPicked(next);
  };

  const run = () => {
    if (picked.size === 0) {
      showToast('请先勾选单据', 'warning');
      return;
    }
    const text = `把选中的 ${picked.size} 张单据写入对账单（${sheet} sheet）`;
    onRun(text, [...picked]);
  };

  const statusLabel: Record<string, string> = { pending: '待审核', verified: '已核对', exported: '已导出' };

  return (
    <div className="modal-mask show" onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div className="modal">
        <div className="modal-head">
          <div className="modal-title">
            表格生成
            <div className="sub">选择单据与目标表格，确认后由工作助手执行</div>
          </div>
          <button className="modal-close" onClick={onClose} aria-label="关闭"><X size={16} /></button>
        </div>
        <div className="modal-body">
          <div className="step"><span className="n">1</span>选择单据（从资料库中勾选，无需记单号）</div>
          <div className="filter-chips">
            {([['all', '全部'], ['verified', '已核对'], ['pending', '待审核'], ['month8', '2026年8月']] as [Filter, string][]).map(([f, label]) => (
              <button key={f} className={`chip ${filter === f ? 'active' : ''}`} onClick={() => setFilter(f)}>{label}</button>
            ))}
          </div>
          <div className="pick-list">
            {filtered.length === 0 && <div style={{ padding: 20, textAlign: 'center', color: 'var(--text-3)' }}>没有符合条件的单据</div>}
            {filtered.map((r) => (
              <label key={r.id} className="pick-row">
                <input type="checkbox" checked={picked.has(r.id)} onChange={() => toggle(r.id)} />
                <span className="no num">{r.receipt_no || '—'}</span>
                <span className="meta">
                  <span>{r.date || '未填日期'}</span>
                  <span>{r.item_count} 行</span>
                  <span>{statusLabel[r.status] || r.status}</span>
                </span>
                <span className="amt num">¥{(r.total_amount || 0).toFixed(2)}</span>
              </label>
            ))}
          </div>
          <div className="pick-foot">
            <span>已选 {pickedList.length} 张</span>
            <span className="sum">合计 <span className="num">¥{sum.toFixed(2)}</span></span>
          </div>

          <div className="step" style={{ marginTop: 18 }}><span className="n">2</span>目标表格</div>
          <div className="form-row">
            <div className="field">
              <label>对账单文件</label>
              <select defaultValue="对账单.xlsx">
                <option>对账单.xlsx</option>
                <option>对账单-2026.xlsx</option>
              </select>
            </div>
            <div className="field">
              <label>写入 sheet</label>
              <select value={sheet} onChange={(e) => setSheet(e.target.value)}>
                <option>水电</option>
                <option>土建</option>
              </select>
            </div>
          </div>
          <div style={{ fontSize: 12, color: 'var(--text-3)', marginTop: 10 }}>
            规则：只追加不覆盖；金额由代码计算；写入后自动验证。
          </div>
        </div>
        <div className="modal-foot">
          <button className="btn ghost" onClick={onClose}>取消</button>
          <button className="btn" onClick={run}>确认执行</button>
        </div>
      </div>
    </div>
  );
}
