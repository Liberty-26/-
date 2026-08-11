// SteelDigitize Pro — 表格生成：真实单据分页 + 工作目录内真实 Excel/sheet 选择
import { useCallback, useEffect, useMemo, useState } from 'react';
import { getHistory, getSpreadsheetTargets } from '../utils/api';
import { useToast } from '../hooks/useToast';
import type { ReceiptSummary } from '../types';
import { ChevronLeft, ChevronRight, FileSpreadsheet, FolderOpen, Search, X } from 'lucide-react';

interface Props {
  open: boolean;
  onClose: () => void;
  onRun: (text: string, selectedIds: number[]) => void;
  onOpenSettings?: () => void;
}

type Filter = 'all' | 'verified' | 'pending';
type TargetMode = 'existing' | 'new';
type SpreadsheetTarget = {
  name: string;
  path: string;
  size: number;
  updated_at: string;
  sheets: string[];
  error: string;
};

const PAGE_SIZE = 24;
const MAX_BATCH = 50;
const statusLabel: Record<string, string> = { pending: '待审核', verified: '已核对', exported: '已导出' };

export default function SkillModal({ open, onClose, onRun, onOpenSettings }: Props) {
  const { showToast } = useToast();
  const [receipts, setReceipts] = useState<ReceiptSummary[]>([]);
  const [filter, setFilter] = useState<Filter>('all');
  const [queryDraft, setQueryDraft] = useState('');
  const [query, setQuery] = useState('');
  const [page, setPage] = useState(1);
  const [total, setTotal] = useState(0);
  const [loadingReceipts, setLoadingReceipts] = useState(false);
  const [picked, setPicked] = useState<Set<number>>(new Set());
  const [pickedMeta, setPickedMeta] = useState<Map<number, ReceiptSummary>>(new Map());
  const [configured, setConfigured] = useState(false);
  const [directoryExists, setDirectoryExists] = useState(false);
  const [directory, setDirectory] = useState('');
  const [files, setFiles] = useState<SpreadsheetTarget[]>([]);
  const [targetMode, setTargetMode] = useState<TargetMode>('new');
  const [targetFile, setTargetFile] = useState<SpreadsheetTarget | null>(null);
  const [sheet, setSheet] = useState('水电');
  const [newSheetMode, setNewSheetMode] = useState(false);
  const [newFileName, setNewFileName] = useState('');

  const loadReceipts = useCallback(async () => {
    setLoadingReceipts(true);
    const res = await getHistory({
      page,
      page_size: PAGE_SIZE,
      receipt_no: query || undefined,
      status: filter === 'all' ? undefined : filter,
    });
    setLoadingReceipts(false);
    if (res.success && res.data) {
      setReceipts(res.data.items);
      setTotal(res.data.total);
      setPickedMeta((prev) => {
        const next = new Map(prev);
        res.data!.items.forEach((item) => next.set(item.id, item));
        return next;
      });
    } else showToast(res.error || '加载单据失败', 'error');
  }, [filter, page, query, showToast]);

  useEffect(() => {
    if (!open) return;
    const defaultName = `对账单-${new Date().toISOString().slice(0, 10)}.xlsx`;
    setPicked(new Set());
    setPickedMeta(new Map());
    setPage(1);
    setQuery('');
    setQueryDraft('');
    setNewFileName(defaultName);
    getSpreadsheetTargets().then((res) => {
      if (!res.success || !res.data) {
        showToast(res.error || '读取表格目录失败', 'error');
        return;
      }
      setConfigured(res.data.configured);
      setDirectoryExists(res.data.directory_exists);
      setDirectory(res.data.directory);
      setFiles(res.data.files);
      const first = res.data.files.find((file) => !file.error) || null;
      setTargetFile(first);
      setTargetMode(first ? 'existing' : 'new');
      setSheet(first?.sheets[0] || '水电');
      setNewSheetMode(false);
    });
  }, [open, showToast]);

  useEffect(() => {
    if (open) void loadReceipts();
  }, [open, loadReceipts]);

  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));
  const pickedList = useMemo(() => [...picked].map((id) => pickedMeta.get(id)).filter(Boolean) as ReceiptSummary[], [picked, pickedMeta]);
  const sum = pickedList.reduce((value, receipt) => value + (receipt.total_amount || 0), 0);
  const currentPagePicked = receipts.filter((receipt) => picked.has(receipt.id));
  const allCurrentPicked = receipts.length > 0 && currentPagePicked.length === receipts.length;
  const sheetOptions = targetFile?.sheets || [];

  const toggle = (receipt: ReceiptSummary) => {
    if (!picked.has(receipt.id) && picked.size >= MAX_BATCH) {
      showToast(`单次最多选择 ${MAX_BATCH} 张单据，请分批执行`, 'warning');
      return;
    }
    setPicked((prev) => {
      const next = new Set(prev);
      if (next.has(receipt.id)) next.delete(receipt.id);
      else next.add(receipt.id);
      return next;
    });
    setPickedMeta((prev) => new Map(prev).set(receipt.id, receipt));
  };

  const toggleCurrentPage = () => {
    const newCount = receipts.filter((receipt) => !picked.has(receipt.id)).length;
    if (!allCurrentPicked && picked.size + newCount > MAX_BATCH) {
      showToast(`单次最多选择 ${MAX_BATCH} 张单据，请分批执行`, 'warning');
      return;
    }
    setPicked((prev) => {
      const next = new Set(prev);
      if (allCurrentPicked) receipts.forEach((receipt) => next.delete(receipt.id));
      else receipts.forEach((receipt) => next.add(receipt.id));
      return next;
    });
  };

  const applySearch = () => {
    setPage(1);
    setQuery(queryDraft.trim());
  };

  const chooseMode = (mode: TargetMode) => {
    setTargetMode(mode);
    setNewSheetMode(false);
    if (mode === 'existing') {
      const first = targetFile || files.find((file) => !file.error) || null;
      setTargetFile(first);
      setSheet(first?.sheets[0] || '');
    }
  };

  const run = () => {
    if (picked.size === 0) {
      showToast('请先勾选要导出的单据', 'warning');
      return;
    }
    if (!configured || !directory || !directoryExists) {
      showToast('请先到「设置 → Agent 记忆层」配置表格存放文件夹', 'warning');
      return;
    }

    if (targetMode === 'existing') {
      if (!targetFile || targetFile.error) {
        showToast('请选择一个可读取的 Excel 文件', 'warning');
        return;
      }
      if (!sheet.trim()) {
        showToast('请选择或填写要写入的 sheet', 'warning');
        return;
      }
      onRun(`把选中的 ${picked.size} 张单据追加写入真实文件「${targetFile.path}」的 sheet「${sheet.trim()}」，写入后核对结果`, [...picked]);
    } else {
      const filename = newFileName.trim().replace(/[\\/]/g, '');
      if (!filename) {
        showToast('请填写新表格文件名', 'warning');
        return;
      }
      const normalized = /\.xlsx$/i.test(filename) ? filename : `${filename.replace(/\.(xlsx|xlsm)$/i, '')}.xlsx`;
      if (!sheet.trim()) {
        showToast('请填写新表格的 sheet 名称', 'warning');
        return;
      }
      const filepath = `${directory.replace(/[\\/]+$/, '')}/${normalized}`;
      onRun(`新建真实表格「${filepath}」，创建并写入 sheet「${sheet.trim()}」，把选中的 ${picked.size} 张单据写入后核对结果`, [...picked]);
    }
  };

  if (!open) return null;

  return (
    <div className="modal-mask show" onClick={(event) => { if (event.target === event.currentTarget) onClose(); }}>
      <div className="modal skill-modal">
        <div className="modal-head">
          <div className="modal-title">
            <span className="modal-kicker">WORKFLOW / EXPORT</span>
            表格生成
            <div className="sub">选择单据，绑定真实工作目录中的表格，再交给工作助手执行</div>
          </div>
          <button className="modal-close" onClick={onClose} aria-label="关闭"><X size={17} /></button>
        </div>
        <div className="modal-body">
          <section className="skill-step">
            <div className="step"><span className="n">1</span><span>选择单据</span><small>支持分页、搜索，已选内容会跨页保留</small></div>
            <div className="receipt-toolbar">
              <div className="filter-chips">
                {([['all', '全部'], ['verified', '已核对'], ['pending', '待审核']] as [Filter, string][]).map(([value, label]) => (
                  <button key={value} className={`chip ${filter === value ? 'active' : ''}`} onClick={() => { setFilter(value); setPage(1); }}>{label}</button>
                ))}
              </div>
              <div className="receipt-search">
                <Search size={14} />
                <input value={queryDraft} placeholder="按单号搜索" onChange={(event) => setQueryDraft(event.target.value)} onKeyDown={(event) => { if (event.key === 'Enter') applySearch(); }} />
                <button onClick={applySearch}>搜索</button>
              </div>
            </div>
            <div className="pick-toolbar">
              <button className="select-page" onClick={toggleCurrentPage} disabled={loadingReceipts || receipts.length === 0}>{allCurrentPicked ? '取消本页全选' : '选择本页'}</button>
              <span>{total.toLocaleString('zh-CN')} 张单据 · 当前第 {page}/{totalPages} 页</span>
              <span className="pick-count">已选 <b>{picked.size}</b> 张 · 合计 <b>¥{sum.toFixed(2)}</b></span>
            </div>
            <div className="pick-list" aria-busy={loadingReceipts}>
              {loadingReceipts && <div className="pick-empty">正在查询单据…</div>}
              {!loadingReceipts && receipts.length === 0 && <div className="pick-empty">没有符合条件的单据</div>}
              {!loadingReceipts && receipts.map((receipt) => (
                <label key={receipt.id} className={`pick-row ${picked.has(receipt.id) ? 'picked' : ''}`}>
                  <input type="checkbox" checked={picked.has(receipt.id)} onChange={() => toggle(receipt)} />
                  <span className="no num">{receipt.receipt_no || '未填单号'}</span>
                  <span className="meta"><span>{receipt.date || '未填日期'}</span><span>{receipt.item_count} 行</span><span>{statusLabel[receipt.status] || receipt.status}</span></span>
                  <span className="amt num">¥{(receipt.total_amount || 0).toFixed(2)}</span>
                </label>
              ))}
            </div>
            <div className="pager">
              <button onClick={() => setPage((value) => Math.max(1, value - 1))} disabled={page <= 1}><ChevronLeft size={14} />上一页</button>
              <span>{page} / {totalPages}</span>
              <button onClick={() => setPage((value) => Math.min(totalPages, value + 1))} disabled={page >= totalPages}>下一页<ChevronRight size={14} /></button>
            </div>
          </section>

          <section className="skill-step target-step">
            <div className="step"><span className="n">2</span><span>绑定目标表格</span><small>只展示设置的工作目录内真实存在的文件</small></div>
            {!configured && <div className="target-alert"><FolderOpen size={16} /><span>还没有设置表格存放文件夹。请先到「设置 → Agent 记忆层」选择文件夹。</span>{onOpenSettings && <button onClick={onOpenSettings}>去设置</button>}</div>}
            {configured && !directoryExists && <div className="target-alert"><FolderOpen size={16} /><span>设置的文件夹当前不存在或不可访问，请重新选择。</span>{onOpenSettings && <button onClick={onOpenSettings}>重新选择</button>}</div>}
            {configured && directoryExists && files.length === 0 && <div className="target-empty"><FileSpreadsheet size={18} /><span>工作目录内还没有 Excel 文件，可以直接新建。</span></div>}
            {configured && directoryExists && files.length > 0 && !files.some((file) => !file.error) && <div className="target-alert"><FileSpreadsheet size={16} /><span>找到 Excel 文件，但当前都无法读取；请关闭占用文件或检查文件格式。</span></div>}
            <div className="target-modes">
              <button className={`target-mode ${targetMode === 'existing' ? 'active' : ''}`} onClick={() => chooseMode('existing')} disabled={!files.some((file) => !file.error)}>
                <span className="target-mode-title">追加到已有表格</span><span>从真实文件和真实 sheet 中选择</span>
              </button>
              <button className={`target-mode ${targetMode === 'new' ? 'active' : ''}`} onClick={() => chooseMode('new')}>
                <span className="target-mode-title">新建对账表</span><span>将在设置的文件夹中创建文件和 sheet</span>
              </button>
            </div>
            {targetMode === 'existing' ? (
              <div className="form-row target-fields">
                <div className="field"><label>真实对账单文件</label><select value={targetFile?.path || ''} onChange={(event) => { const next = files.find((file) => file.path === event.target.value) || null; setTargetFile(next); setSheet(next?.sheets[0] || ''); setNewSheetMode(false); }}>
                  <option value="">请选择文件</option>{files.map((file) => <option key={file.path} value={file.path} disabled={!!file.error}>{file.name}{file.error ? '（无法读取）' : ''}</option>)}
                </select><small className="field-hint">{targetFile?.path || '未选择文件'}</small></div>
                <div className="field"><label>真实 sheet / 新建 sheet</label>{sheetOptions.length > 0 && !newSheetMode ? <select value={sheet} onChange={(event) => { if (event.target.value === '__new__') { setNewSheetMode(true); setSheet(''); } else setSheet(event.target.value); }}>{sheetOptions.map((name) => <option key={name}>{name}</option>)}<option value="__new__">＋新建 sheet…</option></select> : <input value={sheet} onChange={(event) => setSheet(event.target.value)} placeholder="例如：水电" />}<small className="field-hint">文件内没有可读 sheet，或选择“新建 sheet”时可填写新名称</small></div>
              </div>
            ) : (
              <div className="form-row target-fields">
                <div className="field"><label>新文件名</label><input value={newFileName} onChange={(event) => setNewFileName(event.target.value)} placeholder="例如：对账单-2026-08.xlsx" /><small className="field-hint">创建位置：{directory || '未设置'}</small></div>
                <div className="field"><label>新建 sheet 名称</label><input value={sheet} onChange={(event) => setSheet(event.target.value)} placeholder="例如：水电" /><small className="field-hint">新表格没有 sheet 时，由系统创建</small></div>
              </div>
            )}
            <div className="target-rule">写入规则：只追加不覆盖 · 金额由代码计算 · 写入后自动验证 · 目标路径由 Agent 护栏校验</div>
          </section>
        </div>
        <div className="modal-foot"><span className="modal-selection">{picked.size > 0 ? `准备处理 ${picked.size} 张单据${picked.size >= MAX_BATCH ? ' · 已达单次上限' : ''}` : '尚未选择单据'}</span><button className="btn ghost" onClick={onClose}>取消</button><button className="btn" onClick={run} disabled={picked.size === 0}>确认执行</button></div>
      </div>
    </div>
  );
}
