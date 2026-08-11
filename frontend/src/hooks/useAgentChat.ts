// SteelDigitize Pro — Agent 聊天 hook（会话化 + 滚动上下文 + 长期记忆 + 流式流程展示）
import { useState, useCallback, useRef, useEffect } from 'react';
import {
  agentChat as apiAgentChat, agentChatStream, loadMessages, saveMessage,
  getSessions, createSession, deleteSession,
} from '../utils/api';
import { useToast } from './useToast';
import type { AgentMessage, RunTrace } from '../types';

const SESSION_KEY = 'steel_session_id';

export interface ChatSession {
  id: string;
  title: string;
  message_count: number;
  last_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface LiveToolCall {
  name: string;
  ok: boolean | null;
  summary: string | null;
  risk?: string;
  blocked?: boolean;
}

export interface LiveState {
  phase: 'thinking' | 'tool' | 'streaming';
  stageLabel: string;
  toolCalls: LiveToolCall[];
  reply: string;
}

type StreamEvent =
  | { type: 'stage'; label: string }
  | { type: 'tool_call'; name: string; args: unknown; risk?: string }
  | { type: 'tool_result'; name: string; ok: boolean; summary: string; blocked?: boolean }
  | { type: 'delta'; content: string }
  | { type: 'done'; reply: string; history: unknown[]; audit?: RunTrace['audit'] }
  | { type: 'error'; message: string };

export function useAgentChat() {
  const { showToast } = useToast();
  const [messages, setMessages] = useState<AgentMessage[]>([]);
  const [sessions, setSessions] = useState<ChatSession[]>([]);
  const [currentSessionId, setCurrentSessionId] = useState<string>('');
  const [isLoading, setIsLoading] = useState(false);
  const [loadedFromDb, setLoadedFromDb] = useState(false);
  const [live, setLive] = useState<LiveState | null>(null);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const sessionIdRef = useRef<string>('');
  const abortRef = useRef<AbortController | null>(null);
  const userStoppedRef = useRef(false);
  // live 状态引用：SSE 事件回调里读取最新值（避免闭包过期）
  const liveRef = useRef<LiveState | null>(null);
  liveRef.current = live;

  const applySessions = useCallback((list: ChatSession[]) => {
    setSessions(list);
    return list;
  }, []);

  const refreshSessions = useCallback(async (): Promise<ChatSession[]> => {
    const res = await getSessions();
    return applySessions(res.success && res.data?.sessions ? res.data.sessions : []);
  }, [applySessions]);

  const loadMessagesFor = useCallback(async (sid: string) => {
    const res = await loadMessages(sid);
    if (res.success && res.data?.messages) {
      setMessages(res.data.messages.map((m) => {
        const msg: AgentMessage = { role: m.role as 'user' | 'assistant', content: m.content };
        if (m.trace) {
          try { msg.trace = JSON.parse(m.trace as string); } catch { /* 旧消息无痕迹 */ }
        }
        return msg;
      }));
    } else {
      setMessages([]);
    }
  }, []);

  // 启动：恢复上次会话（localStorage），否则用最近活跃的会话；
  // 一个都没有时不自动新建——首页显示「请新建会话」，首次提问时自动创建
  useEffect(() => {
    (async () => {
      const list = await refreshSessions();
      const saved = localStorage.getItem(SESSION_KEY) || '';
      let sid = saved && list.some((s) => s.id === saved) ? saved : '';
      if (!sid && list.length > 0) sid = list[0].id;
      sessionIdRef.current = sid;
      setCurrentSessionId(sid);
      if (sid) {
        try { localStorage.setItem(SESSION_KEY, sid); } catch { /* ignore */ }
        await loadMessagesFor(sid);
      } else {
        setMessages([]);
      }
      setLoadedFromDb(true);
    })();
  }, [refreshSessions, loadMessagesFor]);

  // 卸载时中断进行中的流
  useEffect(() => {
    return () => { abortRef.current?.abort(); };
  }, []);

  // 切换到指定会话
  const switchSession = useCallback(async (sid: string) => {
    if (!sid || sid === sessionIdRef.current) return;
    abortRef.current?.abort();
    sessionIdRef.current = sid;
    setCurrentSessionId(sid);
    setLive(null);
    try { localStorage.setItem(SESSION_KEY, sid); } catch { /* ignore */ }
    await loadMessagesFor(sid);
  }, [loadMessagesFor]);

  // 新会话
  const newSession = useCallback(async (): Promise<string> => {
    abortRef.current?.abort();
    const created = await createSession();
    if (!created.success || !created.data) return '';
    const sid = created.data.id;
    sessionIdRef.current = sid;
    setCurrentSessionId(sid);
    setMessages([]);
    setLive(null);
    try { localStorage.setItem(SESSION_KEY, sid); } catch { /* ignore */ }
    await refreshSessions();
    return sid;
  }, [refreshSessions]);

  // 删除会话（默认会话同样可删）；删除当前会话时自动切到最近会话或新建
  const deleteSessionById = useCallback(async (sid: string): Promise<boolean> => {
    const res = await deleteSession(sid);
    if (!res.success) return false;
    const list = await refreshSessions();
    if (sessionIdRef.current === sid) {
      if (list.length > 0) {
        await switchSession(list[0].id);
      } else {
        sessionIdRef.current = '';
        setCurrentSessionId('');
        setMessages([]);
        setLive(null);
        try { localStorage.removeItem(SESSION_KEY); } catch { /* ignore */ }
      }
    }
    return true;
  }, [refreshSessions, switchSession]);

  // 批量删除会话；删除后若当前会话被删则自动切换
  const deleteSessions = useCallback(async (ids: string[]): Promise<boolean> => {
    if (!ids.length) return false;
    let ok = true;
    for (const sid of ids) {
      const res = await deleteSession(sid);
      if (!res.success) ok = false;
    }
    const list = await refreshSessions();
    if (ids.includes(sessionIdRef.current)) {
      if (list.length > 0) {
        await switchSession(list[0].id);
      } else {
        // 全部删完：清空当前会话，首页显示「请新建会话」
        sessionIdRef.current = '';
        setCurrentSessionId('');
        setMessages([]);
        setLive(null);
        try { localStorage.removeItem(SESSION_KEY); } catch { /* ignore */ }
      }
    }
    return ok;
  }, [refreshSessions, switchSession]);

  // 停止生成：中断当前流；已生成的部分由 sendMessage 的 abort 分支保留
  const stopGenerating = useCallback(() => {
    userStoppedRef.current = true;
    abortRef.current?.abort();
  }, []);

  const persistMsg = useCallback(async (role: string, content: string, sid: string, trace?: RunTrace) => {
    try { await saveMessage(role, content, sid, trace); } catch { /* ignore */ }
  }, []);

  const finishAssistantMsg = useCallback(async (sid: string, content: string, trace?: RunTrace) => {
    setMessages((prev) => [...prev, { role: 'assistant', content, ...(trace ? { trace } : {}) }]);
    await persistMsg('assistant', content, sid, trace);
    await refreshSessions();
    setIsLoading(false);
    setLive(null);
  }, [persistMsg, refreshSessions]);

  const sendMessage = useCallback(async (text: string, selectedIds: number[], uploadedFile?: string): Promise<string | null> => {
    if (!text.trim() || isLoading) return null;

    // 确保有会话
    let sid = sessionIdRef.current;
    if (!sid) {
      const created = await createSession();
      if (created.success && created.data) {
        sid = created.data.id;
        sessionIdRef.current = sid;
        setCurrentSessionId(sid);
        try { localStorage.setItem(SESSION_KEY, sid); } catch { /* ignore */ }
      }
    }
    if (!sid) return null;

    const userMsg: AgentMessage = { role: 'user', content: text };
    setMessages((prev) => [...prev, userMsg]);
    await persistMsg('user', text, sid);
    setIsLoading(true);
    userStoppedRef.current = false;
    setLive({ phase: 'thinking', stageLabel: '正在思考', toolCalls: [], reply: '' });

    // 全量历史由后端按 session_id 从数据库加载（全量保留 + 摘要 + 最近窗口）
    const history: { role: string; content: string }[] = [];
    const abort = new AbortController();
    abortRef.current = abort;
    // 防卡死安全网：模型/后端无响应时自动中止，输入框绝不会被永久禁用
    let timedOut = false;
    let lastActivity = Date.now();
    const hardTimeout = window.setTimeout(() => {
      if (!abort.signal.aborted) { timedOut = true; abort.abort(); }
    }, 600000); // 绝对兜底 10 分钟（正常任务远到不了）
    const watchdog = window.setInterval(() => {
      if (!abort.signal.aborted && Date.now() - lastActivity > 90000) {
        timedOut = true;
        abort.abort(); // 90s 无任何数据/事件 → 判定停滞
      }
    }, 5000);

    const applyLive = (patch: Partial<LiveState>) => {
      setLive((prev) => (prev ? { ...prev, ...patch } : prev));
    };

    let finalReply = '';
    // 运行痕迹收集：状态序列 + 工具调用 + 总耗时（完成后随消息落库，可收起展开）
    const startTs = Date.now();
    const traceSteps: string[] = [];
    const traceTools: RunTrace['tools'] = [];
    const pushStep = (label: string) => {
      if (traceSteps[traceSteps.length - 1] !== label) traceSteps.push(label);
    };
    // 一次性守卫：done/error/降级/收尾可能多路径触发，只允许落库一次
    let finished = false;
    const finishOnce = async (content: string, trace?: RunTrace) => {
      if (finished) return;
      finished = true;
      // 用户已切走会话则丢弃本次落库（避免回复写到别的会话）
      if (sessionIdRef.current !== sid) return;
      await finishAssistantMsg(sid, content, trace);
    };
    // 中止后的统一收尾：无论用户停止还是超时，都保证输入框恢复
    const handleAborted = async (): Promise<string | null> => {
      if (finalReply.trim()) {
        await finishAssistantMsg(sid, finalReply, {
          steps: traceSteps,
          tools: traceTools,
          elapsed: Math.max(1, Math.round((Date.now() - startTs) / 1000)),
        });
        if (timedOut) showToast('生成超时，已保留已生成的内容', 'warning');
        else if (userStoppedRef.current) showToast('已停止生成，已保留已生成内容', 'info');
      } else {
        setIsLoading(false);
        setLive(null);
        if (timedOut) showToast('生成超时，请重试', 'warning');
        else if (userStoppedRef.current) showToast('已停止生成', 'info');
      }
      return null;
    };
    try {
      const resp = await agentChatStream(text, history, selectedIds, uploadedFile, sid, abort.signal);
      if (!resp.ok) {
        // 后端缺少流式接口（旧版本后端残留）→ 降级为阻塞接口，保证聊天可用
        console.warn('[chat] 流式接口不可用（HTTP ' + resp.status + '），降级为阻塞模式');
        try {
          const res = await apiAgentChat(text, history, selectedIds, uploadedFile, sid);
          if (res.success && res.data) {
            await finishOnce(res.data.reply);
            return res.data.reply;
          }
          await finishOnce(`处理失败：${res.error || '未知错误'}`);
          return null;
        } catch (e2) {
          await finishOnce(`处理失败：${(e2 as Error).message || '网络错误'}`);
          return null;
        }
      }
      if (!resp.body) throw new Error('无响应流');

      const reader = resp.body.getReader();
      const decoder = new TextDecoder();
      let buf = '';

      const handleEvent = async (evt: StreamEvent) => {
        // 停止后忽略后续事件：缓冲中的事件不再处理，立即生效
        if (abort.signal.aborted) return;
        lastActivity = Date.now();
        switch (evt.type) {
          case 'stage':
            pushStep('思考中');
            applyLive({ phase: 'thinking', stageLabel: evt.label });
            break;
          case 'tool_call':
            pushStep('执行中');
            traceTools.push({ name: evt.name, ok: false, summary: '执行中…', risk: evt.risk });
            applyLive({
              phase: 'tool',
              toolCalls: [...(liveRef.current?.toolCalls || []), { name: evt.name, ok: null, summary: null, risk: evt.risk }],
            });
            break;
          case 'tool_result':
            {
              const last = traceTools[traceTools.length - 1];
              if (last && last.name === evt.name) {
                last.ok = evt.ok;
                last.summary = evt.summary;
                last.blocked = evt.blocked;
              }
            }
            applyLive({
              toolCalls: (liveRef.current?.toolCalls || []).map((t, i) =>
                i === (liveRef.current?.toolCalls.length || 0) - 1 && t.name === evt.name
                  ? { ...t, ok: evt.ok, summary: evt.summary, blocked: evt.blocked }
                  : t
              ),
            });
            break;
          case 'delta':
            finalReply += evt.content;
            pushStep('生成中');
            applyLive({ phase: 'streaming', reply: finalReply });
            break;
          case 'done':
            // 最少让流程卡展示 ~0.9s：短消息秒回时也不会一闪而过
            await new Promise((r) => setTimeout(r, 900));
            const trace: RunTrace = {
              steps: traceSteps,
              tools: traceTools,
              elapsed: Math.max(1, Math.round((Date.now() - startTs) / 1000)),
              audit: evt.audit,
            };
            await finishOnce(evt.reply || finalReply || '处理完成', trace);
            break;
          case 'error':
            await finishOnce(`处理失败：${evt.message}`);
            break;
        }
      };

      for (;;) {
        const { done, value } = await reader.read();
        if (done || abort.signal.aborted) break;
        lastActivity = Date.now();
        buf += decoder.decode(value, { stream: true });
        let idx: number;
        while ((idx = buf.indexOf('\n\n')) !== -1) {
          const raw = buf.slice(0, idx);
          buf = buf.slice(idx + 2);
          const line = raw.split('\n').find((l) => l.startsWith('data: '));
          if (!line) continue;
          try {
            await handleEvent(JSON.parse(line.slice(6)) as StreamEvent);
          } catch (e) {
            console.error('[chat] SSE 解析失败:', e);
          }
          if (abort.signal.aborted) break;
        }
      }
      // 用户停止 / 超时中止：保留已生成的部分作为回复，一条都没有则恢复输入框
      if (abort.signal.aborted) {
        return await handleAborted();
      }
      // 流正常结束但没有 done 事件（异常中断兜底）
      await finishOnce(finalReply || '处理完成', {
        steps: traceSteps,
        tools: traceTools,
        elapsed: Math.max(1, Math.round((Date.now() - startTs) / 1000)),
      });
    } catch (e) {
      if (abort.signal.aborted) {
        // 用户主动停止 / 超时中止
        return await handleAborted();
      }
      console.error('[chat] 流式请求失败:', e);
      // 流式接口自身的响应头超时（AbortError 且非用户中止）→ 直接恢复，不再走 5 分钟阻塞降级
      if ((e as Error).name === 'AbortError' || (e as Error).message?.includes('abort')) {
        setIsLoading(false);
        setLive(null);
        showToast('请求超时，请重试', 'warning');
        return null;
      }
      // 降级：切回阻塞式接口，保证功能可用
      try {
        const res = await apiAgentChat(text, history, selectedIds, uploadedFile, sid);
        if (res.success && res.data) {
          await finishOnce(res.data.reply);
          return res.data.reply;
        }
        await finishOnce(`处理失败：${res.error || '未知错误'}`);
        return null;
      } catch (e2) {
        await finishOnce(`处理失败：${(e2 as Error).message || '网络错误'}`);
        return null;
      }
    } finally {
      window.clearTimeout(hardTimeout);
      window.clearInterval(watchdog);
    }
    return finalReply || null;
  }, [isLoading, liveRef, persistMsg, refreshSessions, finishAssistantMsg, showToast]);

  return {
    messages, isLoading, live, sendMessage, messagesEndRef, loadedFromDb,
    sessions, currentSessionId, switchSession, newSession, deleteSessionById, deleteSessions, refreshSessions,
    stopGenerating,
  };
}
