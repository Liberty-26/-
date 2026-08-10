// SteelDigitize Pro — Agent 聊天 hook（会话化 + 滚动上下文 + 长期记忆 + 流式流程展示）
import { useState, useCallback, useRef, useEffect } from 'react';
import {
  agentChat as apiAgentChat, agentChatStream, loadMessages, saveMessage,
  getSessions, createSession,
} from '../utils/api';
import type { AgentMessage } from '../types';

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
}

export interface LiveState {
  phase: 'thinking' | 'tool' | 'streaming';
  stageLabel: string;
  toolCalls: LiveToolCall[];
  reply: string;
}

type StreamEvent =
  | { type: 'stage'; label: string }
  | { type: 'tool_call'; name: string; args: unknown }
  | { type: 'tool_result'; name: string; ok: boolean; summary: string }
  | { type: 'delta'; content: string }
  | { type: 'done'; reply: string; history: unknown[] }
  | { type: 'error'; message: string };

export function useAgentChat() {
  const [messages, setMessages] = useState<AgentMessage[]>([]);
  const [sessions, setSessions] = useState<ChatSession[]>([]);
  const [currentSessionId, setCurrentSessionId] = useState<string>('');
  const [isLoading, setIsLoading] = useState(false);
  const [loadedFromDb, setLoadedFromDb] = useState(false);
  const [live, setLive] = useState<LiveState | null>(null);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const sessionIdRef = useRef<string>('');
  const abortRef = useRef<AbortController | null>(null);
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
      setMessages(res.data.messages.map(
        (m: { role: string; content: string }) => ({ role: m.role as 'user' | 'assistant', content: m.content })
      ));
    } else {
      setMessages([]);
    }
  }, []);

  // 启动：恢复上次会话（localStorage），否则用最近活跃的会话，都没有则新建
  useEffect(() => {
    (async () => {
      const list = await refreshSessions();
      const saved = localStorage.getItem(SESSION_KEY) || '';
      let sid = saved && list.some((s) => s.id === saved) ? saved : '';
      if (!sid && list.length > 0) sid = list[0].id;
      if (!sid) {
        const created = await createSession();
        if (created.success && created.data) sid = created.data.id;
      }
      sessionIdRef.current = sid;
      setCurrentSessionId(sid);
      if (sid) {
        try { localStorage.setItem(SESSION_KEY, sid); } catch { /* ignore */ }
        await loadMessagesFor(sid);
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

  const persistMsg = useCallback(async (role: string, content: string, sid: string) => {
    try { await saveMessage(role, content, sid); } catch { /* ignore */ }
  }, []);

  const finishAssistantMsg = useCallback(async (sid: string, content: string) => {
    setMessages((prev) => [...prev, { role: 'assistant', content }]);
    await persistMsg('assistant', content, sid);
    await refreshSessions();
    setIsLoading(false);
    setLive(null);
    setTimeout(() => messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' }), 80);
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
    setLive({ phase: 'thinking', stageLabel: '正在思考', toolCalls: [], reply: '' });

    // 全量历史由后端按 session_id 从数据库加载（全量保留 + 摘要 + 最近窗口）
    const history: { role: string; content: string }[] = [];
    const abort = new AbortController();
    abortRef.current = abort;

    const applyLive = (patch: Partial<LiveState>) => {
      setLive((prev) => (prev ? { ...prev, ...patch } : prev));
    };

    let finalReply = '';
    // 一次性守卫：done/error/降级/收尾可能多路径触发，只允许落库一次
    let finished = false;
    const finishOnce = async (content: string) => {
      if (finished) return;
      finished = true;
      // 用户已切走会话则丢弃本次落库（避免回复写到别的会话）
      if (sessionIdRef.current !== sid) return;
      await finishAssistantMsg(sid, content);
    };
    try {
      const resp = await agentChatStream(text, history, selectedIds, uploadedFile, sid);
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
        switch (evt.type) {
          case 'stage':
            applyLive({ phase: 'thinking', stageLabel: evt.label });
            break;
          case 'tool_call':
            applyLive({
              phase: 'tool',
              toolCalls: [...(liveRef.current?.toolCalls || []), { name: evt.name, ok: null, summary: null }],
            });
            break;
          case 'tool_result':
            applyLive({
              toolCalls: (liveRef.current?.toolCalls || []).map((t, i) =>
                i === (liveRef.current?.toolCalls.length || 0) - 1 && t.name === evt.name
                  ? { ...t, ok: evt.ok, summary: evt.summary }
                  : t
              ),
            });
            break;
          case 'delta':
            finalReply += evt.content;
            applyLive({ phase: 'streaming', reply: finalReply });
            setTimeout(() => messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' }), 30);
            break;
          case 'done':
            // 最少让流程卡展示 ~0.9s：短消息秒回时也不会一闪而过
            await new Promise((r) => setTimeout(r, 900));
            await finishOnce(evt.reply || finalReply || '处理完成');
            break;
          case 'error':
            await finishOnce(`处理失败：${evt.message}`);
            break;
        }
      };

      for (;;) {
        const { done, value } = await reader.read();
        if (done) break;
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
        }
      }
      // 流正常结束但没有 done 事件（异常中断兜底）
      await finishOnce(finalReply || '处理完成');
    } catch (e) {
      if (abort.signal.aborted) {
        setIsLoading(false);
        setLive(null);
        return null;
      }
      console.error('[chat] 流式请求失败:', e);
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
    }
    return finalReply || null;
  }, [isLoading, liveRef, persistMsg, refreshSessions, finishAssistantMsg]);

  return {
    messages, isLoading, live, sendMessage, messagesEndRef, loadedFromDb,
    sessions, currentSessionId, switchSession, newSession, refreshSessions,
  };
}
