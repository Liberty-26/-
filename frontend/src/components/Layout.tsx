// SteelDigitize Pro — 全局布局（工作区 / 管理 分组侧边栏，页面常驻状态保持）
import { useNav } from '../contexts/NavContext';
import { useQueue } from '../contexts/QueueContext';
import type { ReactNode } from 'react';
import type { ComponentType } from 'react';
import { LayoutDashboard, ClipboardCheck, Archive, Boxes, Settings } from 'lucide-react';
import type { PageId } from '../types';

const PAGES: { id: PageId; label: string; icon: ComponentType<{ size?: number; strokeWidth?: number }> }[] = [
  { id: 'workbench', label: '工作台', icon: LayoutDashboard },
  { id: 'review', label: '审核区', icon: ClipboardCheck },
  { id: 'library', label: '资料库', icon: Archive },
  { id: 'materials', label: '品名库', icon: Boxes },
  { id: 'settings', label: '设置', icon: Settings },
];

export default function Layout({ children }: { children: ReactNode[] }) {
  const { page, setPage } = useNav();
  const { queue } = useQueue();

  return (
    <div className="app">
      <aside className="sidebar">
        <div className="brand">
          <div className="brand-mark">数</div>
          <div>
            <div className="brand-name">数字化工作台</div>
            <div className="brand-sub">单据 · 表格 · 助手</div>
          </div>
        </div>
        <nav className="nav">
          <div className="nav-sec">工作区</div>
          {PAGES.slice(0, 3).map((p) => (
            <button
              key={p.id}
              className={`nav-item ${page === p.id ? 'active' : ''}`}
              onClick={() => setPage(p.id)}
            >
              <span className="nav-icon"><p.icon size={17} strokeWidth={2} /></span>
              {p.label}
              {p.id === 'review' && <span className="badge nav-badge-review" id="navBadgeReview">{queue.length}</span>}
            </button>
          ))}
          <div className="nav-sec">管理</div>
          {PAGES.slice(3).map((p) => (
            <button
              key={p.id}
              className={`nav-item ${page === p.id ? 'active' : ''}`}
              onClick={() => setPage(p.id)}
            >
              <span className="nav-icon"><p.icon size={17} strokeWidth={2} /></span>
              {p.label}
              {p.id === 'materials' && <span className="badge" id="navBadgeCand">0</span>}
            </button>
          ))}
        </nav>
        <div className="sidebar-foot">
          <span className="dot" />
          数据都在本机 · v{__APP_VERSION__}
        </div>
      </aside>
      <main>
        <section className={`page ${page === 'workbench' ? 'active' : ''}`}>{children[0]}</section>
        <section className={`page ${page === 'review' ? 'active' : ''}`}>{children[1]}</section>
        <section className={`page ${page === 'library' ? 'active' : ''}`}>{children[2]}</section>
        <section className={`page ${page === 'materials' ? 'active' : ''}`}>{children[3]}</section>
        <section className={`page ${page === 'settings' ? 'active' : ''}`}>{children[4]}</section>
      </main>
    </div>
  );
}
