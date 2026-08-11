// SteelDigitize Pro — 工作台（首页）：今日概览 + 技能 + 对话 + 右侧单据流/会话
import { useCallback, useEffect, useRef, useState } from 'react';
import { useAgentChat } from '../hooks/useAgentChat';
import { useToast } from '../hooks/useToast';
import { useNav } from '../contexts/NavContext';
import { useQueue } from '../contexts/QueueContext';
import SkillModal from '../components/SkillModal';
import { Table2, CalendarRange, Boxes, Upload, ArrowUp, Square } from 'lucide-react';
import {
  saveReceipt,
} from '../utils/api';
import { compressImage } from '../utils/image';
import type { AgentMessage, RunTrace } from '../types';

interface FlowItem {
  key: number;
  label: string;
  meta: string;
  status: '待识别' | '排队中' | '识别中' | '待审核' | '已入库' | '失败';
  stage?: number; // 1 提取单号和日期 → 2 识别中 → 3 转译 → 4 自审核中（来自后端真实进度）
  imagePath?: string;
  receiptId?: number;
  error?: string;
  time: string;
}

const STAGES = ['正在提取单号和日期', '识别中', '转译', '自审核中'];

// 展示层采用“中文动作 + 技术工具名”：老板能看懂正在做什么，技术细节也完整保留。
const TOOL_LABELS: Record<string, string> = {
  db_lookup_receipt: '查询单据',
  db_get_receipt_items: '读取明细',
  spreadsheet_find_last_row: '定位写入位置',
  spreadsheet_create_new: '创建对账单',
  spreadsheet_write_batch: '写入对账单',
  spreadsheet_verify: '核对写入结果',
  memory_list: '读取长期记忆',
  memory_add: '保存长期记忆',
  memory_replace: '更新长期记忆',
  memory_remove: '删除长期记忆',
  session_search: '检索历史对话',
};

const formatToolName = (name: string) => (TOOL_LABELS[name] || '执行操作') + ' · ' + name;

const timeNow = () =>
  new Date().toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' });

// 处理耗时格式化：秒 → 分秒 → 时分（单位自适应）
const formatElapsed = (s: number): string => {
  if (s < 60) return `${s}秒`;
  if (s < 3600) {
    const m = Math.floor(s / 60);
    const sec = s % 60;
    return sec > 0 ? `${m}分${sec}秒` : `${m}分`;
  }
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  return m > 0 ? `${h}小时${m}分` : `${h}小时`;
};

// 助手执行过程：完成后收起为一行摘要，可展开查看工具明细；与结果之间用细线分隔
function RunTraceView({ trace }: { trace: RunTrace }) {
  const [open, setOpen] = useState(false);
  const summary = trace.tools.length > 0
    ? trace.tools.map((t) => (t.ok ? '✓ ' : '✗ ') + formatToolName(t.name) + ' · ' + t.summary).join('　')
    : '思考 → 回复';
  return (
    <div className="run-trace">
      <button className="trace-toggle" onClick={() => setOpen((v) => !v)}>
        <span className={`trace-chevron ${open ? 'open' : ''}`}>▸</span>
        <span className="trace-summary">{summary}</span>
        <span className="trace-meta">· {formatElapsed(trace.elapsed)}</span>
      </button>
      {open && (
        <div className="trace-body">
          {trace.tools.length === 0 && <div className="trace-empty">思考 → 生成回复</div>}
          {trace.tools.map((t, i) => (
            <div key={i} className="trace-tool">
              <span className={`live-tool-dot ${t.ok ? 'ok' : 'fail'}`}>{t.ok ? '✓' : '✗'}</span>
              <span className="live-tool-name" title={t.name}>{formatToolName(t.name)}</span>
              <span className="live-tool-sum">{t.summary}</span>
            </div>
          ))}
        </div>
      )}
      <div className="trace-divider" />
    </div>
  );
}

export default function WorkbenchPage() {
  const { showToast } = useToast();
  const { setPage } = useNav();
  const { queue, addPending } = useQueue();
  const {
    messages, isLoading, live, sendMessage, messagesEndRef,
    sessions, currentSessionId, switchSession, newSession, deleteSessions, stopGenerating,
  } = useAgentChat();
  const [flow, setFlow] = useState<'stream' | 'sessions'>('stream');
  const [flowItems, setFlowItems] = useState<FlowItem[]>([]);
  const [skillOpen, setSkillOpen] = useState(false);
  const [taskCard, setTaskCard] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);
  // 会话批量管理：编辑 → 全选 → 删除（不给单个会话单独删除键）
  const [editSessions, setEditSessions] = useState(false);
  const [selectedSessions, setSelectedSessions] = useState<Set<string>>(new Set());
  const fileRef = useRef<HTMLInputElement>(null);
  const chatBodyRef = useRef<HTMLDivElement>(null);
  // 自动跟随滚动：仅当用户没有任何手动滚动操作时生效；
  // 一旦用户手动滚动（即使之后回到底部），本次生成内都不再跟随
  const followRef = useRef(true);
  const lastProgTopRef = useRef(-1);
  // 流式回复逐行揭示：模型一次吐一大段时也按段匀速展开（配合自动跟随滚动）
  const [revealLen, setRevealLen] = useState(0);
  const liveReplyRef = useRef('');
  liveReplyRef.current = live?.reply || '';
  // 处理耗时（秒/分/时）
  const [elapsed, setElapsed] = useState(0);
  const keySeq = useRef(0);
  const pendingFilesRef = useRef<Map<number, File>>(new Map());
  const savedKeys = useRef<Set<number>>(new Set());
  const pollRef = useRef<number | null>(null);

  const scrollToBottom = useCallback(() => {
    const el = chatBodyRef.current;
    if (!el) return;
    el.scrollTop = el.scrollHeight;
    lastProgTopRef.current = el.scrollTop; // 记录程序化滚动的实际位置，供 onScroll 区分人为滚动
  }, []);

  const handleChatScroll = useCallback(() => {
    const el = chatBodyRef.current;
    if (!el) return;
    // 与程序化目标不一致 → 用户手动滚动了，本次生成内停止跟随
    if (Math.abs(el.scrollTop - lastProgTopRef.current) > 2) {
      followRef.current = false;
    }
  }, []);

  // 跟随规则：live 从无到有 = 新一轮发送 → 重置跟随并滚到底；
  // 生成中仅在无人为滚动时持续跟随；结束收尾一次（同样只在无人为滚动时）
  const prevLiveRef = useRef(false);
  useEffect(() => {
    const started = !prevLiveRef.current && !!live;
    prevLiveRef.current = !!live;
    if (!live) {
      if (followRef.current) scrollToBottom();
      return;
    }
    if (started) {
      followRef.current = true;
      scrollToBottom();
      return;
    }
    if (followRef.current) scrollToBottom();
  }, [live, scrollToBottom]);

  // 切换会话：回到该会话最新消息
  useEffect(() => {
    followRef.current = true;
    scrollToBottom();
  }, [currentSessionId, scrollToBottom]);

  useEffect(() => {
    if (live?.phase !== 'streaming') {
      setRevealLen(0);
      return;
    }
    setRevealLen(0);
    // 平滑逐行揭示：打字机式按字符匀速展开（≈270 字/秒），
    // 换行自然呈现，配合自动跟随滚动形成「逐行长出来」的连续感
    const timer = window.setInterval(() => {
      setRevealLen((prev) => {
        const text = liveReplyRef.current;
        const total = text.length;
        if (prev >= total) return total;
        return Math.min(total, prev + 8);
      });
    }, 30);
    return () => window.clearInterval(timer);
  }, [live?.phase]);

  // 处理计时器：live 出现即从 0 开始每秒 +1，结束归零
  useEffect(() => {
    if (!live) {
      setElapsed(0);
      return;
    }
    setElapsed(0);
    const timer = window.setInterval(() => setElapsed((s) => s + 1), 1000);
    return () => window.clearInterval(timer);
  }, [live]);

  useEffect(() => {
    return () => {
      if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null; }
    };
  }, []);

  // 选择文件：只登记到待识别列表，不读取、不压缩、不识别
  const handleSelectFiles = useCallback((files: FileList | null) => {
    if (!files || files.length === 0) return;
    const newItems: FlowItem[] = [];
    for (const f of Array.from(files)) {
      const key = ++keySeq.current;
      pendingFilesRef.current.set(key, f);
      const fname = f.name || `单据 ${key}`;
      newItems.push({
        key,
        label: fname.length > 12 ? fname.slice(0, 12) + '…' : fname,
        meta: '已选，待开始识别',
        status: '待识别',
        time: timeNow(),
      });
    }
    setFlowItems((prev) => [...newItems, ...prev]);
    setFlow('stream');
  }, []);

  // 点击"开始识别"：才压缩 → 提交 batch → 轮询真实进度
  const handleStartRecognition = useCallback(async () => {
    if (uploading) return;
    const pendingItems = flowItems.filter((it) => it.status === '待识别');
    if (pendingItems.length === 0) return;
    setUploading(true);
    const images: { image_base64: string }[] = [];
    const addedKeys: number[] = [];
    const failedKeys: number[] = [];
    try {
      for (const it of pendingItems) {
        const f = pendingFilesRef.current.get(it.key);
        if (!f) { failedKeys.push(it.key); continue; }
        try {
          const b64 = await compressImage(f);
          images.push({ image_base64: b64 });
          addedKeys.push(it.key);
        } catch (e) {
          console.error('[识别] 图片处理失败:', it.label, e);
          failedKeys.push(it.key);
        }
      }
      if (failedKeys.length) {
        setFlowItems((prev) =>
          prev.map((x) =>
            failedKeys.includes(x.key)
              ? { ...x, status: '失败', meta: '图片处理失败', error: '图片处理失败，请换一张再试', time: timeNow() }
              : x
          )
        );
      }
      if (images.length === 0) return;
      pendingFilesRef.current.clear();

      const markAllFailed = (err: string) => {
        setFlowItems((prev) =>
          prev.map((x) =>
            addedKeys.includes(x.key) ? { ...x, status: '失败', meta: '识别失败', error: err, time: timeNow() } : x
          )
        );
      };

      let resp: Response;
      try {
        resp = await fetch('/api/recognize/batch', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ images }),
        });
      } catch (e) {
        console.error('[识别] 请求未送达:', e);
        markAllFailed('网络错误：识别请求未送达后端');
        showToast('网络错误：识别请求未送达后端', 'error');
        return;
      }

      let res: any;
      try {
        res = await resp.json();
      } catch (e) {
        markAllFailed('后端响应解析失败');
        showToast('后端响应解析失败', 'error');
        return;
      }
      if (!resp.ok || !res?.success) {
        markAllFailed(res?.detail || '识别请求失败');
        showToast(res?.detail || '识别请求失败', 'error');
        return;
      }
      const taskId = res?.data?.task_id;
      if (!taskId) {
        markAllFailed('后端未返回任务号');
        showToast('后端未返回任务号', 'error');
        return;
      }

      // 轮询后端任务进度：每张状态真实来自后端
      const applyItem = (key: number, patch: Partial<FlowItem>) => {
        setFlowItems((prev) => prev.map((x) => (x.key === key ? { ...x, ...patch } : x)));
      };

      const updateFromTask = async (): Promise<boolean> => {
        try {
          const sr = await fetch(`/api/recognize/batch/${taskId}`);
          const sj = await sr.json();
          if (!sr.ok || !sj?.success || !sj.data) return false;
          const d = sj.data;
          const batchItems: { status: string; success: boolean; error?: string; stage?: number; result?: any }[] = d.items || [];
          for (let i = 0; i < addedKeys.length; i++) {
            const key = addedKeys[i];
            const st = batchItems[i];
            if (!st) continue;
            if (st.status === 'pending') {
              applyItem(key, { status: '排队中', meta: '等待识别', stage: 0 });
            } else if (st.status === 'processing') {
              const stage = Math.max(1, Math.min(4, st.stage || 2));
              applyItem(key, { status: '识别中', meta: `${STAGES[stage - 1]}…`, stage });
            } else if (st.status === 'done' && st.success && st.result?.success) {
              const r = st.result;
              const labelPatch: Partial<FlowItem> = {
                status: '待审核',
                stage: 5,
                imagePath: r.image_path || undefined,
                error: undefined,
              };
              if (!savedKeys.current.has(key)) {
                savedKeys.current.add(key);
                const saved = await saveReceipt({
                  receipt_no: r.receipt_no || '',
                  date: r.date || '',
                  items: r.items || [],
                  image_path: r.image_path || '',
                  rec_total: r.rec_total ?? null,
                });
                if (saved.success) {
                  labelPatch.receiptId = saved.data?.id;
                  labelPatch.meta = `${r.date || '未填日期'} · ${(r.items || []).length} 行`;
                  labelPatch.label = r.receipt_no || undefined;
                  // 写入共享待审队列：审核区左侧立即出现，无需刷新
                  addPending({
                    id: saved.data?.id ?? 0,
                    receipt_no: r.receipt_no || '',
                    date: r.date || '',
                    total_amount: saved.data?.total_amount ?? 0,
                    status: 'pending',
                    operator: saved.data?.operator || '本地用户',
                    image_path: saved.data?.image_path ?? (r.image_path || ''),
                    summary: '',
                    item_count: (r.items || []).length,
                    created_at: saved.data?.created_at ?? null,
                  });
                } else {
                  labelPatch.status = '失败';
                  labelPatch.error = saved.error;
                  labelPatch.meta = '入库失败';
                }
              } else {
                labelPatch.meta = `${r.date || '未填日期'} · ${(r.items || []).length} 行`;
                labelPatch.label = r.receipt_no || undefined;
              }
              applyItem(key, labelPatch);
            } else {
              applyItem(key, {
                status: '失败',
                meta: '识别失败',
                stage: 5,
                error: st.error || '识别失败',
                imagePath: (st.result && st.result.image_path) || undefined,
                time: timeNow(),
              });
            }
          }
          if (d.finished) {
            showToast(
              d.failed > 0 ? `识别完成：${d.ok} 张待审核，${d.failed} 张失败` : `识别完成：${d.ok} 张已进审核区`,
              d.failed > 0 ? 'warning' : 'success'
            );
            return true;
          }
          return false;
        } catch (e) {
          console.error('[识别] 轮询任务状态失败:', e);
          return false;
        }
      };

      const done = await updateFromTask();
      if (done) return;
      pollRef.current = window.setInterval(async () => {
        const isDone = await updateFromTask();
        if (isDone && pollRef.current) { window.clearInterval(pollRef.current); pollRef.current = null; }
      }, 1200);
    } finally {
      setUploading(false);
    }
  }, [flowItems, uploading, showToast, saveReceipt, addPending]);

  // 重试：对已保存的原图重新识别（不重新选图）
  const handleRetry = useCallback(async (it: FlowItem) => {
    if (!it.imagePath) {
      showToast('缺少原图，无法重试，请重新上传', 'error');
      return;
    }
    setFlowItems((prev) =>
      prev.map((x) =>
        x.key === it.key
          ? { ...x, status: '识别中', meta: '重新识别中…', error: undefined, time: timeNow() }
          : x
      )
    );
    try {
      const resp = await fetch('/api/recognize/retry', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ image_path: it.imagePath }),
      });
      const res = await resp.json();
      if (!resp.ok || !res?.success) throw new Error(res?.detail || '重试失败');
      const r = res.data;
      if (!r?.success) throw new Error(r?.error || '重试失败');
      const saved = await saveReceipt({
        receipt_no: r.receipt_no || '',
        date: r.date || '',
        items: r.items || [],
        image_path: r.image_path || it.imagePath,
        rec_total: r.rec_total ?? null,
      });
      setFlowItems((prev) =>
        prev.map((x) =>
          x.key === it.key
            ? {
                ...x,
                label: r.receipt_no || x.label,
                meta: `${r.date || '未填日期'} · ${(r.items || []).length} 行`,
                status: saved.success ? '待审核' : '失败',
                receiptId: saved.success ? saved.data?.id : undefined,
                error: saved.success ? undefined : saved.error,
                time: timeNow(),
              }
            : x
        )
      );
      if (saved.success && saved.data?.id) {
        addPending({
          id: saved.data.id,
          receipt_no: r.receipt_no || '',
          date: r.date || '',
          total_amount: saved.data.total_amount ?? 0,
          status: 'pending',
          operator: saved.data.operator || '本地用户',
          image_path: saved.data.image_path ?? (r.image_path || ''),
          summary: '',
          item_count: (r.items || []).length,
          created_at: saved.data.created_at ?? null,
        });
      }
      showToast(saved.success ? `重试成功：${r.receipt_no || r.date || '单据'} 已进审核区` : `重试识别成功但入库失败：${saved.error}`, saved.success ? 'success' : 'warning');
    } catch (e) {
      const msg = (e as Error).message || '重试失败';
      setFlowItems((prev) =>
        prev.map((x) => (x.key === it.key ? { ...x, status: '失败', error: msg, time: timeNow() } : x))
      );
      showToast(msg, 'error');
    }
  }, [showToast, saveReceipt, addPending]);

  const handleRunSkill = useCallback(async (text: string, ids: number[]) => {
    setSkillOpen(false);
    const reply = await sendMessage(text, ids);
    setTaskCard(reply ?? null);
  }, [sendMessage]);

  // 批量删除会话（带确认；默认会话同样可删）
  const handleDeleteSessions = useCallback(async () => {
    if (selectedSessions.size === 0) return;
    const ok = window.confirm(`删除选中的 ${selectedSessions.size} 个会话？这些会话的全部消息将一并删除。`);
    if (!ok) return;
    const done = await deleteSessions(Array.from(selectedSessions));
    setSelectedSessions(new Set());
    setEditSessions(false);
    showToast(done ? `已删除 ${selectedSessions.size} 个会话` : '部分会话删除失败', done ? 'success' : 'warning');
  }, [selectedSessions, deleteSessions, showToast]);

  const toggleSelectSession = useCallback((sid: string) => {
    setSelectedSessions((prev) => {
      const next = new Set(prev);
      if (next.has(sid)) next.delete(sid); else next.add(sid);
      return next;
    });
  }, []);

  const toggleSelectAll = useCallback(() => {
    setSelectedSessions((prev) =>
      prev.size === sessions.length ? new Set() : new Set(sessions.map((s) => s.id))
    );
  }, [sessions]);

  const renderMsg = (m: AgentMessage, i: number) => (
    <div key={i} className={`msg ${m.role === 'user' ? 'user' : 'assistant'}`}>
      {m.role === 'assistant' && m.trace && <RunTraceView trace={m.trace} />}
      {m.content}
    </div>
  );

  const statusPill: Record<FlowItem['status'], { cls: string; label: string }> = {
    待识别: { cls: 'gray', label: '待识别' },
    排队中: { cls: 'gray', label: '排队中' },
    识别中: { cls: 'blue', label: '识别中' },
    待审核: { cls: 'amber', label: '待审核' },
    已入库: { cls: 'green', label: '已入库' },
    失败: { cls: 'gray', label: '失败' },
  };

  return (
    <div className="wb">
      <div className="wb-center">
        <div className="wb-title">工作台</div>

        <div className="ai-strip">
          <span className="lab">AI 工作台</span>
          <span>识别完成自动提取单号 / 日期 · 品名对齐 · 金额由代码计算</span>
          <span className="ac">{queue.length > 0 ? `· ${queue.length} 张待你核对` : '· 当前无待核对单据'}</span>
        </div>

        <div className="skills">
          <button className="skill-card" onClick={() => setSkillOpen(true)}>
            <div className="skill-ico"><Table2 size={19} strokeWidth={2} /></div>
            <div>
              <div className="skill-name">表格生成</div>
              <div className="skill-desc">把选中的单据写入对账单 Excel</div>
            </div>
          </button>
          <div className="skill-card disabled">
            <div className="skill-ico"><CalendarRange size={19} strokeWidth={2} /></div>
            <div>
              <div className="skill-name">月度汇总</div>
              <div className="skill-desc">按月汇总入库单据</div>
              <span className="tag-dev">开发中</span>
            </div>
          </div>
          <div className="skill-card disabled">
            <div className="skill-ico"><Boxes size={19} strokeWidth={2} /></div>
            <div>
              <div className="skill-name">品名建议</div>
              <div className="skill-desc">新品名收录与别名建议</div>
              <span className="tag-dev">开发中</span>
            </div>
          </div>
        </div>

        <div className="chat">
          <div className="chat-head">
            与助手对话
            <span className="live"><span className="dot" />助手在线</span>
          </div>
          <div className="chat-body" ref={chatBodyRef} onScroll={handleChatScroll}>
            {messages.length === 0 && sessions.length === 0 && (
              <div className="chat-empty">
                <div className="ce-title">请新建会话</div>
                <div className="ce-sub">说点什么吧——我会自动为你开一个新对话，也可以先点右侧「新对话」。</div>
              </div>
            )}
            {messages.length === 0 && sessions.length > 0 && (
              <div className="msg assistant">你好，我是你的本地工作助手。可以让我把单据写入对账单，也可以点上方「表格生成」技能，选好单据直接执行。</div>
            )}
            {messages.map(renderMsg)}
            {live && (
              <div className="assistant-turn">
                <div className="live-status" key={live.phase}>
                  <span className="live-spinner" />
                  <span>{live.stageLabel || (live.phase === 'thinking' ? '思考中' : live.phase === 'tool' ? '执行中' : '生成中')}</span>
                  <span className="live-elapsed">· {formatElapsed(elapsed)}</span>
                </div>
                {live.toolCalls.map((t, i) => (
                  <div key={i} className="live-tool">
                    <span className={`live-tool-dot ${t.ok === null ? 'wait' : t.ok ? 'ok' : 'fail'}`}>
                      {t.ok === null ? '…' : t.ok ? '✓' : '✗'}
                    </span>
                    <span className="live-tool-name">{t.name}</span>
                    <span className="live-tool-sum">{t.summary ?? '执行中…'}</span>
                  </div>
                ))}
                {live.reply && (
                  <div className="msg assistant live-reply">{live.reply.slice(0, revealLen)}<span className="caret" /></div>
                )}
              </div>
            )}
            {taskCard && (
              <div className="task-card">
                <div className="task-head"><span className="task-title">表格生成</span><span className="task-status">已完成</span></div>
                <div className="task-body">
                  <div className="task-row"><span className="lab">结果</span><span>{taskCard}</span></div>
                  <div className="task-bar"><i /></div>
                </div>
              </div>
            )}
            <div ref={messagesEndRef} />
          </div>
          <div className="chat-input">
            <input
              placeholder={isLoading ? '助手处理中…' : '输入指令，或点上方技能卡片…'}
              disabled={isLoading}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && !isLoading) {
                  const v = (e.target as HTMLInputElement).value.trim();
                  if (v) { sendMessage(v, []); (e.target as HTMLInputElement).value = ''; }
                }
              }}
            />
            <button
              className={`chat-send ${isLoading ? 'stop' : ''}`}
              title={isLoading ? '停止生成' : '发送'}
              onClick={(e) => {
                if (isLoading) { stopGenerating(); return; }
                const inp = (e.currentTarget.parentElement!.querySelector('input'))!;
                const v = inp.value.trim();
                if (v) { sendMessage(v, []); inp.value = ''; }
              }}
            >
              {isLoading ? <Square size={16} strokeWidth={3} /> : <ArrowUp size={20} strokeWidth={2.5} />}
            </button>
          </div>
        </div>
      </div>

      <aside className="flow">
        <div className="flow-tabs">
          <button className={`flow-tab ${flow === 'stream' ? 'active' : ''}`} onClick={() => setFlow('stream')}>单据流</button>
          <button className={`flow-tab ${flow === 'sessions' ? 'active' : ''}`} onClick={() => setFlow('sessions')}>会话</button>
        </div>
        <div className="flow-body">
          {flow === 'stream' ? (
            <>
              <input
                ref={fileRef}
                type="file"
                accept="image/*"
                multiple
                style={{ display: 'none' }}
                onChange={(e) => { handleSelectFiles(e.target.files); e.target.value = ''; }}
              />
              <button
                className="upload-zone"
                onClick={() => fileRef.current?.click()}
                disabled={uploading}
                onDragOver={(e) => { e.preventDefault(); e.dataTransfer.dropEffect = 'copy'; }}
                onDrop={(e) => { e.preventDefault(); if (!uploading) handleSelectFiles(e.dataTransfer.files); }}
              >
                <span className="up-ico"><Upload size={18} strokeWidth={2} /></span>
                <span className="up-tip">{uploading ? '识别处理中…' : '上传单据（可多选）'}</span>
                <div className="up-sub">点击或拖拽上传，识别在后台排队，完成后进审核区</div>
              </button>
              {flowItems.some((it) => it.status === '待识别') && (
                <button
                  className="start-btn"
                  onClick={handleStartRecognition}
                  disabled={uploading}
                >
                  {uploading ? '识别处理中…' : `开始识别（${flowItems.filter((it) => it.status === '待识别').length}）`}
                </button>
              )}
              {flowItems.length === 0 && (
                <div style={{ textAlign: 'center', color: 'var(--text-3)', fontSize: 13, padding: '18px 0' }}>
                  今天还没有上传，拍两张试试
                </div>
              )}
              {flowItems.map((it) => {
                const p = statusPill[it.status];
                const pct = it.status === '排队中' ? 18 : it.status === '识别中' ? (it.stage || 2) * 20 : 100;
                const progCls = it.status === '失败' ? 'fail' : it.status === '识别中' ? 'run' : it.status === '待审核' || it.status === '已入库' ? 'done' : '';
                return (
                  <div key={it.key} className="flow-item">
                    <div style={{ flex: 1, minWidth: 0 }}>
                      <div className="flow-no">{it.label}</div>
                      <div className="flow-meta">{it.time} · {it.meta}{it.error ? ` · ${it.error}` : ''}</div>
                      {it.status === '识别中' && it.stage ? (
                        <>
                          <div className="flow-meta" style={{ color: 'var(--primary)', fontWeight: 600 }}>
                            {STAGES[Math.max(0, Math.min(3, it.stage - 1))]}
                          </div>
                          <div className={`prog ${progCls}`}><i style={{ width: `${pct}%` }} /></div>
                        </>
                      ) : (
                        <div className={`prog ${progCls}`}><i style={{ width: `${pct}%` }} /></div>
                      )}
                    </div>
                    <span className={`pill ${p.cls}`} style={{ marginLeft: 'auto' }}>{p.label}</span>
                    {it.status === '待审核' && it.receiptId && (
                      <span className="go" onClick={() => setPage('review')}>去审核</span>
                    )}
                    {it.status === '失败' && (
                      <span className="go" onClick={() => handleRetry(it)}>重试</span>
                    )}
                  </div>
                );
              })}
            </>
          ) : (
            <>
              <div className="flow-section">最近会话</div>
              <div className="session-tools">
                <button className="start-btn" onClick={() => { newSession(); }}>新对话</button>
                {editSessions ? (
                  <>
                    <button className="tool-btn" onClick={toggleSelectAll}>
                      {selectedSessions.size === sessions.length && sessions.length > 0 ? '取消全选' : '全选'}
                    </button>
                    <button className="tool-btn danger" disabled={selectedSessions.size === 0} onClick={handleDeleteSessions}>
                      删除{selectedSessions.size > 0 ? `（${selectedSessions.size}）` : ''}
                    </button>
                    <button className="tool-btn" onClick={() => { setEditSessions(false); setSelectedSessions(new Set()); }}>完成</button>
                  </>
                ) : (
                  <button className="tool-btn" onClick={() => setEditSessions(true)} disabled={sessions.length === 0}>编辑</button>
                )}
              </div>
              {sessions.length === 0 && (
                <div className="sessions-empty">
                  <div>还没有会话</div>
                  <span>点「新对话」开始，或直接在下方向我提问</span>
                </div>
              )}
              {sessions.map((s) => (
                <div
                  key={s.id}
                  className={`session-item ${editSessions ? 'edit' : ''} ${selectedSessions.has(s.id) ? 'selected' : ''}`}
                  onClick={() => { if (editSessions) toggleSelectSession(s.id); else switchSession(s.id); }}
                >
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8, minWidth: 0 }}>
                    {editSessions && <span className={`q-check ${selectedSessions.has(s.id) ? 'on' : ''}`}>✓</span>}
                    <div style={{ minWidth: 0 }}>
                      <div className="session-title">{s.title || '新对话'}</div>
                      <div className="session-meta">{s.message_count} 条消息 · {(s.updated_at || '').slice(0, 16).replace('T', ' ')}</div>
                    </div>
                  </div>
                  <span className="session-count">{s.id === currentSessionId ? '当前对话' : '点击继续对话'}</span>
                </div>
              ))}
            </>
          )}
        </div>
      </aside>

      <SkillModal open={skillOpen} onClose={() => setSkillOpen(false)} onRun={handleRunSkill} />
    </div>
  );
}
