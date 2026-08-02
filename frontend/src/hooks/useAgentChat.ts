// SteelDigitize Pro — Agent 聊天 hook（支持持久化）
import { useState, useCallback, useRef, useEffect } from 'react';
import { agentChat as apiAgentChat, loadMessages, saveMessage } from '../utils/api';
import type { AgentMessage } from '../types';

export function useAgentChat() {
  const [messages, setMessages] = useState<AgentMessage[]>([]);
  const [history, setHistory] = useState<{ role: string; content: string }[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [loadedFromDb, setLoadedFromDb] = useState(false);
  const messagesEndRef = useRef<HTMLDivElement>(null);

  // 启动时从数据库恢复对话
  useEffect(() => {
    (async () => {
      const res = await loadMessages();
      if (res.success && res.data?.messages) {
        const msgs: AgentMessage[] = res.data.messages.map(
          (m: { role: string; content: string }) => ({ role: m.role as 'user' | 'assistant', content: m.content })
        );
        setMessages(msgs);
      }
      setLoadedFromDb(true);
    })();
  }, []);

  const persistMsg = useCallback((role: string, content: string) => {
    saveMessage(role, content).catch(() => {}); // fire-and-forget
  }, []);

  const sendMessage = useCallback(async (text: string, selectedIds: number[], uploadedFile?: string) => {
    if (!text.trim() || isLoading) return;

    const userMsg: AgentMessage = { role: 'user', content: text };
    setMessages((prev) => [...prev, userMsg]);
    persistMsg('user', text);
    setIsLoading(true);

    const res = await apiAgentChat(text, history, selectedIds, uploadedFile);

    if (res.success && res.data) {
      const agentMsg: AgentMessage = { role: 'assistant', content: res.data.reply };
      setMessages((prev) => [...prev, agentMsg]);
      setHistory(res.data.history || []);
      persistMsg('assistant', res.data.reply);
    } else {
      const errMsg: AgentMessage = { role: 'assistant', content: `处理失败：${res.error || '未知错误'}` };
      setMessages((prev) => [...prev, errMsg]);
    }

    setIsLoading(false);
    setTimeout(() => messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' }), 100);
  }, [history, isLoading, persistMsg]);

  return { messages, isLoading, sendMessage, messagesEndRef, loadedFromDb };
}
