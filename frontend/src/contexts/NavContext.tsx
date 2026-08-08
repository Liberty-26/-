// SteelDigitize Pro — 页面导航上下文
import { createContext, useContext, useCallback, useState, type ReactNode } from 'react';
import type { PageId } from '../types';

interface NavCtx {
  page: PageId;
  setPage: (p: PageId) => void;
}

const Ctx = createContext<NavCtx>({ page: 'workbench', setPage: () => {} });

const STORAGE_KEY = 'steel_page';

export function NavProvider({ children }: { children: ReactNode }) {
  // 刷新后保持在原页面（本地持久化），不回跳首页
  const [page, setPageState] = useState<PageId>(() => {
    try {
      const saved = localStorage.getItem(STORAGE_KEY);
      if (saved === 'workbench' || saved === 'review' || saved === 'library' || saved === 'materials' || saved === 'settings') {
        return saved as PageId;
      }
    } catch { /* ignore */ }
    return 'workbench';
  });
  const setPage = useCallback((p: PageId) => {
    setPageState(p);
    try { localStorage.setItem(STORAGE_KEY, p); } catch { /* ignore */ }
  }, []);
  return <Ctx.Provider value={{ page, setPage }}>{children}</Ctx.Provider>;
}

export function useNav() {
  return useContext(Ctx);
}
