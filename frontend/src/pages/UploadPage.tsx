// SteelDigitize Pro — 上传与识别页
import { useState, useCallback, useEffect, useMemo } from 'react';
import UploadZone from '../components/UploadZone';
import ImagePreview from '../components/ImagePreview';
import ResultTable from '../components/ResultTable';
import { useToast } from '../hooks/useToast';
import { recognizeImage, saveReceipt, getHistory, getReceiptDetail } from '../utils/api';
import type { ReceiptItem, ReceiptSummary } from '../types';

const CALIBRATE_STEPS = ['文本归一化', 'AI语义校准', '代码规则兜底'];

export default function UploadPage() {
  const { showToast } = useToast();
  const [imageBase64, setImageBase64] = useState<string | null>(null);
  const [imageFilename, setImageFilename] = useState('');
  const [imagePath, setImagePath] = useState('');
  const [receiptNo, setReceiptNo] = useState('');
  const [receiptDate, setReceiptDate] = useState('');
  // 识别日期疑似异常标记（如 2016 等 10 年代/超 5 年偏差年份），黄标提示人工核对，不阻断保存
  const [dateSuspicious, setDateSuspicious] = useState(false);
  // 保存必填校验错误（单号/日期为空时提示）
  const [errors, setErrors] = useState<{ date?: string; no?: string }>({});
  const [recognizing, setRecognizing] = useState(false);
  const [calibrating, setCalibrating] = useState(false);
  const [calibrateProgress, setCalibrateProgress] = useState<{ step: number; label: string; model?: string; done: boolean } | null>(null);
  const [elapsed, setElapsed] = useState(0);
  const [saving, setSaving] = useState(false);

  // 校准计时器
  useEffect(() => {
    if (!calibrating) { setElapsed(0); return; }
    const t = setInterval(() => setElapsed(s => s + 1), 1000);
    return () => clearInterval(t);
  }, [calibrating]);
  const [items, setItems] = useState<ReceiptItem[]>([]);
  const [headerRows, setHeaderRows] = useState<number[]>([]);
  const [savedReceipt, setSavedReceipt] = useState<Record<string, unknown> | null>(null);
  const [recentHistory, setRecentHistory] = useState<ReceiptSummary[]>([]);
  // 表格多选状态重置信号：识别新图/重新审核/清空图片/加载历史时 +1，ResultTable 据此清空多选
  const [tableReset, setTableReset] = useState(0);

  // 校准摘要（已修正/异常/表头行计数）
  const summary = useMemo(() => {
    const corrected = items.filter(it => (it.corrections || []).length > 0).length;
    const issues = items.filter(it => (it.issues || []).length > 0).length;
    return { corrected, issues, headers: headerRows.length };
  }, [items, headerRows]);

  // AI 校准按钮可用：有识别结果且非空
  const canCalibrate = items.length > 0 && !recognizing && !calibrating;

  const loadRecentHistory = useCallback(async () => {
    const res = await getHistory({ page: 1, page_size: 10 });
    if (res.success && res.data) setRecentHistory(res.data.items);
  }, []);
  useEffect(() => { loadRecentHistory(); }, [loadRecentHistory]);

  const handleImageReady = useCallback((b64: string, filename: string) => {
    setImageBase64(b64); setImageFilename(filename); setImagePath(''); setItems([]); setHeaderRows([]); setSavedReceipt(null); setDateSuspicious(false); setTableReset(s => s + 1);
  }, []);
  const handleClearImage = useCallback(() => {
    setImageBase64(null); setImageFilename(''); setImagePath(''); setItems([]); setHeaderRows([]); setSavedReceipt(null); setDateSuspicious(false); setTableReset(s => s + 1);
  }, []);

  const handleRecognize = useCallback(async () => {
    if (!imageBase64 || recognizing) return;
    setRecognizing(true); setSavedReceipt(null); setHeaderRows([]); setDateSuspicious(false); setTableReset(s => s + 1);
    const res = await recognizeImage(imageBase64, receiptNo || undefined, receiptDate || undefined);
    setRecognizing(false);
    if (res.success && res.data) {
      setItems(res.data.items || []); setImagePath(res.data.image_path || '');
      if (res.data.receipt_no) setReceiptNo(res.data.receipt_no);
      if (res.data.date) { setReceiptDate(res.data.date); setDateSuspicious(!!res.data.date_suspicious); }
      showToast('识别完成', 'success');
    } else { showToast(res.error || '识别失败', 'error'); }
  }, [imageBase64, recognizing, receiptNo, receiptDate, showToast]);

  // AI 校准（SSE 流式）
  const handleCalibrate = useCallback(async () => {
    if (!canCalibrate) return;
    setCalibrating(true); setSavedReceipt(null); setCalibrateProgress({ step: 1, label: '文本归一化', done: false }); setTableReset(s => s + 1);
    try {
      const resp = await fetch('/api/recognize/calibrate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ items: items.map(it => ({ name: it.name, spec: it.spec, unit: it.unit, qty: it.qty, price: it.price })), receipt_no: receiptNo, date: receiptDate }),
      });
      if (!resp.ok) { throw new Error(`HTTP ${resp.status}`); }
      const reader = resp.body!.getReader();
      const decoder = new TextDecoder();
      let buf = '';
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buf += decoder.decode(value, { stream: true });
        const events = buf.split('\n\n');
        buf = events.pop() || '';
        for (const evt of events) {
          const line = evt.trim();
          if (!line.startsWith('data: ')) continue;
          const data = JSON.parse(line.slice(6));
          if (data.step === 0) {
            setCalibrating(false); setCalibrateProgress(null);
            if (data.done && data.result) {
              setItems(data.result.items || []);
              setHeaderRows(data.result.header_rows || []);
              if (data.result.truncated) {
                showToast('模型输出超限被截断，本次仅规则校验生效，请人工核对', 'warning');
              } else {
                const c = (data.result.items || []).filter((it: any) => (it.corrections || []).length > 0).length;
                const i = (data.result.items || []).filter((it: any) => (it.issues || []).length > 0).length;
                showToast(`AI审核完成：已修正 ${c} 项，${i} 项异常`, 'success');
              }
            } else {
              showToast(data.error || 'AI审核失败', 'error');
            }
            return;
          }
          setCalibrateProgress(data);
        }
      }
    } catch (e) {
      setCalibrating(false); setCalibrateProgress(null);
      showToast('校准请求失败: ' + (e as Error).message, 'error');
    }
  }, [canCalibrate, items, receiptNo, receiptDate, showToast]);

  const handleSave = useCallback(async () => {
    if (saving) return;
    // 必填校验：单号/日期为空时红字提示，不提交
    const errs: { date?: string; no?: string } = {};
    if (!receiptDate) errs.date = '请填写日期';
    if (!receiptNo.trim()) errs.no = '请填写单号';
    if (errs.date || errs.no) { setErrors(errs); return; }
    setErrors({});
    setSaving(true); setSavedReceipt(null);
    const res = await saveReceipt({
      receipt_no: receiptNo, date: receiptDate,
      items: items.map(it => ({ name: it.name, spec: it.spec, unit: it.unit, qty: it.qty, price: it.price })),
      image_path: imagePath,
    });
    setSaving(false);
    if (res.success && res.data) { setSavedReceipt(res.data as unknown as Record<string, unknown>); showToast('保存成功', 'success'); loadRecentHistory(); }
    else { showToast(res.error || '保存失败', 'error'); }
  }, [saving, receiptNo, receiptDate, items, imagePath, showToast, loadRecentHistory]);

  const handleCopy = useCallback(async () => {
    if (!savedReceipt) return;
    try { await navigator.clipboard.writeText(JSON.stringify(savedReceipt, null, 2)); showToast('已复制', 'success'); }
    catch { showToast('复制失败', 'error'); }
  }, [savedReceipt, showToast]);

  const handleLoadHistory = useCallback(async (id: number) => {
    setTableReset(s => s + 1);
    const res = await getReceiptDetail(id);
    if (res.success && res.data) {
      setItems(res.data.items || []); setReceiptNo(res.data.receipt_no); setReceiptDate(res.data.date); setSavedReceipt(null); setDateSuspicious(false);
      if (res.data.image_path) {
        setImagePath(res.data.image_path); setImageFilename(res.data.image_path);
        try {
          const imgResp = await fetch('/uploads/' + res.data.image_path);
          if (imgResp.ok) { const blob = await imgResp.blob(); const reader = new FileReader(); reader.onloadend = () => setImageBase64(reader.result as string); reader.readAsDataURL(blob); }
          else setImageBase64(null);
        } catch { setImageBase64(null); }
      } else setImageBase64(null);
      showToast('已加载单据', 'info');
    }
  }, [showToast]);

  return (
    <div className="flex h-full overflow-hidden">
      <aside className="w-[260px] bg-white border-r border-outline-variant flex flex-col shrink-0 overflow-y-auto">
        <div className="p-4 flex-1 flex flex-col gap-4 overflow-hidden">
          <h3 className="text-label-sm uppercase tracking-wider text-on-surface-variant/60">单据上传</h3>
          <UploadZone onImageReady={handleImageReady} disabled={recognizing} />
          <div className="flex flex-col gap-2">
            <label className="text-[10px] uppercase text-on-surface-variant font-medium">单据日期</label>
            <input type="date" value={receiptDate} onChange={e => { setReceiptDate(e.target.value); setDateSuspicious(false); setErrors(prev => ({ ...prev, date: undefined })); }}
              className={`w-full border rounded px-3 py-1.5 text-label-sm text-on-surface outline-none ${
                dateSuspicious
                  ? 'bg-amber-50 border-amber-400 focus:border-amber-500'
                  : 'bg-surface-container-low border-outline-variant focus:border-primary'
              }`} />
            {dateSuspicious && (
              <p className="text-amber-700 text-[11px] mt-1 font-medium flex items-center gap-1">
                <span className="material-symbols-outlined text-xs">warning</span>
                日期疑似异常，请核对
              </p>
            )}
            {errors.date && <p className="text-error text-[11px] mt-1">{errors.date}</p>}
            <label className="text-[10px] uppercase text-on-surface-variant font-medium mt-1">单据单号</label>
            <input type="text" value={receiptNo} onChange={e => { setReceiptNo(e.target.value); setErrors(prev => ({ ...prev, no: undefined })); }} placeholder="例如: DN-8892" className="w-full bg-surface-container-low border border-outline-variant rounded px-3 py-1.5 text-label-sm text-on-surface focus:border-primary outline-none" />
            {errors.no && <p className="text-error text-[11px] mt-1">{errors.no}</p>}
          </div>
          <div className="flex-1 flex flex-col gap-2 overflow-hidden">
            <h3 className="text-label-sm uppercase tracking-wider text-on-surface-variant/60 mt-4">历史记录</h3>
            <div className="flex-1 overflow-y-auto custom-scrollbar flex flex-col gap-2 pr-1">
              {recentHistory.length === 0 ? <div className="text-center py-10 text-on-surface-variant/40 text-label-sm">暂无历史</div> : recentHistory.map(item => (
                <button key={item.id} onClick={() => handleLoadHistory(item.id)} className="text-left text-label-sm p-2 rounded hover:bg-surface-container-low transition-colors flex flex-col gap-1 w-full">
                  <div className="flex justify-between items-center">
                    <span className="text-on-surface-variant truncate max-w-[120px]">{item.receipt_no || '无单号'}</span>
                    <span className={`text-[10px] px-1.5 py-0.5 rounded ${item.status === 'exported' ? 'bg-primary-container/30 text-primary' : item.status === 'verified' ? 'bg-tertiary-container/30 text-tertiary' : 'bg-surface-container-high text-on-surface-variant'}`}>{item.status === 'exported' ? '已导出' : item.status === 'verified' ? '已核对' : '待处理'}</span>
                  </div>
                  <div className="flex justify-between text-[11px] text-on-surface-variant/50"><span>{item.date}</span><span>¥{item.total_amount?.toFixed(2)}</span></div>
                </button>
              ))}
            </div>
          </div>
        </div>
      </aside>
      <section className="flex-1 bg-surface-container-low flex items-center justify-center overflow-hidden">
        {imageBase64 ? <ImagePreview src={imageBase64} filename={imageFilename} onClear={handleClearImage} /> : <div className="text-on-surface-variant/20 flex flex-col items-center gap-4"><span className="material-symbols-outlined text-6xl">image_search</span><p className="text-label-sm">预览区域</p></div>}
      </section>
      <aside className="flex-1 bg-white border-l border-outline-variant flex flex-col">
        <div className="p-margin-page h-full flex flex-col overflow-hidden">
          <div className="flex items-center justify-between mb-stack-md shrink-0">
            <h2 className="font-headline-md text-headline-md text-on-surface">识别结果</h2>
            <div className="flex items-center gap-2">
              <button onClick={handleCalibrate} disabled={calibrating || !canCalibrate} className="bg-tertiary-container text-on-tertiary-container px-5 py-2 rounded-lg font-semibold text-label-sm hover:bg-tertiary transition-all flex items-center gap-2 disabled:opacity-50 disabled:cursor-not-allowed">{calibrating && <span className="material-symbols-outlined animate-spin text-sm">sync</span>}{calibrating ? 'AI审核中...' : 'AI审核'}</button>
              <button onClick={handleRecognize} disabled={!imageBase64 || recognizing} className="bg-primary text-white px-6 py-2 rounded-lg font-semibold text-label-sm hover:bg-primary-container transition-all flex items-center gap-2 disabled:opacity-50 disabled:cursor-not-allowed">{recognizing && <span className="material-symbols-outlined animate-spin text-sm">sync</span>}{recognizing ? '识别中...' : '识别'}</button>
            </div>
          </div>
          {/* 校准步骤条 */}
          {calibrating && (
            <div className="flex items-center gap-2 mb-2 -mt-1 text-xs shrink-0">
              {CALIBRATE_STEPS.map((s, i) => {
                const stepNo = i + 1;
                const done = calibrateProgress && stepNo < (calibrateProgress.step || 1);
                const current = calibrateProgress?.step === stepNo;
                return (
                  <div key={s} className="flex items-center gap-1">
                    <span className={done ? 'text-green-600' : current ? 'text-blue-600 font-bold' : 'text-gray-400'}>
                      {done ? '✓' : current ? '◎' : '○'}
                    </span>
                    <span className={current ? 'text-blue-600 font-bold' : done ? 'text-green-600' : 'text-gray-400'}>{s}</span>
                    {current && stepNo === 2 && calibrateProgress?.model && (
                      <span className="text-gray-500">（{calibrateProgress.model}，已用时 {elapsed} 秒）</span>
                    )}
                    {i < 2 && <span className="text-gray-300 mx-1">→</span>}
                  </div>
                );
              })}
            </div>
          )}
          {/* 校准摘要 */}
          {(summary.corrected > 0 || summary.issues > 0 || summary.headers > 0) && (
            <div className="mb-stack-md -mt-2 text-label-sm text-on-surface-variant shrink-0">
              已修正 <span className="text-yellow-700 font-semibold">{summary.corrected}</span> 项，
              异常 <span className="text-red-600 font-semibold">{summary.issues}</span> 项，
              疑似表头 <span className="text-on-surface-variant font-semibold">{summary.headers}</span> 行
            </div>
          )}
          <div className="flex-1 overflow-hidden flex flex-col"><ResultTable items={items} onChange={setItems} headerRows={headerRows} resetSignal={tableReset} /></div>
          <div className="mt-stack-md pt-stack-md border-t border-outline-variant flex justify-between items-center shrink-0">
            <div className="text-label-sm text-on-surface-variant">{items.length > 0 && `${items.length} 项`}</div>
            <div className="flex gap-2">
              {savedReceipt && <button onClick={handleCopy} className="px-4 py-2 text-label-sm bg-secondary-container text-on-secondary-container rounded-lg hover:bg-secondary transition-colors flex items-center gap-1"><span className="material-symbols-outlined text-sm">content_copy</span>复制 JSON</button>}
              <button onClick={handleSave} disabled={items.length === 0 || saving} className="px-4 py-2 text-label-sm bg-primary text-on-primary rounded-lg hover:bg-primary-container transition-colors flex items-center gap-1 disabled:opacity-50 disabled:cursor-not-allowed">{saving ? '保存中...' : '保存'}</button>
            </div>
          </div>
        </div>
      </aside>
    </div>
  );
}
