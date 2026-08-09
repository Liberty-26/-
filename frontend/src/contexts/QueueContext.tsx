// SteelDigitize Pro — 待审核队列共享数据源
// 首页单据流与审核区左侧队列共用同一份数据：任何一端识别完成/确认入库，另一端立即同步
import { createContext, useContext, useCallback, useState, useEffect, type ReactNode } from 'react';
import { getHistory } from '../utils/api';
import type { ReceiptSummary } from '../types';

interface QueueCtx {
  queue: ReceiptSummary[];
  refreshQueue: () => Promise<void>;
  addPending: (r: ReceiptSummary) => void;
  removePending: (id: number) => void;
}

const Ctx = createContext<QueueCtx>({
  queue: [],
  refreshQueue: async () => {},
  addPending: () => {},
  removePending: () => {},
});

export function QueueProvider({ children }: { children: ReactNode }) {
  const [queue, setQueue] = useState<ReceiptSummary[]>([]);

  // 从后端拉取待审队列（receipts 表中 status=pending）
  const refreshQueue = useCallback(async () => {
    const res = await getHistory({ page: 1, page_size: 50, status: 'pending' });
    if (res.success && res.data) setQueue(res.data.items);
  }, []);

  // 挂载时拉取一次；后续由业务动作（识别完成/确认入库）增量更新
  useEffect(() => { refreshQueue(); }, [refreshQueue]);

  // 识别完成：立即插入队首（去重），首页和审核区同时可见
  const addPending = useCallback((r: ReceiptSummary) => {
    setQueue((prev) => (prev.some((x) => x.id === r.id) ? prev : [r, ...prev]));
  }, []);

  // 确认入库/删除：立即从队列移除
  const removePending = useCallback((id: number) => {
    setQueue((prev) => prev.filter((x) => x.id !== id));
  }, []);

  return (
    <Ctx.Provider value={{ queue, refreshQueue, addPending, removePending }}>
      {children}
    </Ctx.Provider>
  );
}

export function useQueue() {
  return useContext(Ctx);
}
