// SteelDigitize Pro — 全局布局（工作区 / 管理 分组侧边栏，页面常驻状态保持）
import { useNav } from '../contexts/NavContext';
import type { ReactNode } from 'react';
import type { PageId } from '../types';

const PAGES: { id: PageId; label: string; icon: string; badge?: () => number | null }[] = [
  { id: 'workbench', label: '工作台', icon: '▦' },
  { id: 'review', label: '审核区', icon: '▤' },
  { id: 'library', label: '资料库', icon: '▥' },
  { id: 'materials', label: '品名库', icon: '▣' },
  { id: 'settings', label: '设置', icon: '⚙' },
];

export default function Layout({ children }: { children: ReactNode[] }) {
  const { page, setPage } = useNav();

  return (
    <div className="app">
      <aside className="sidebar">
        <div className="brand">
          <div className="brand-mark">钢</div>
          <div>
            <div className="brand-name">SteelDigitize Pro</div>
            <div className="brand-sub">本地工作台</div>
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
              <span className="nav-icon">{p.icon}</span>
              {p.label}
              {p.id === 'review' && <span className="badge nav-badge-review" id="navBadgeReview">0</span>}
            </button>
          ))}
          <div className="nav-sec">管理</div>
          {PAGES.slice(3).map((p) => (
            <button
              key={p.id}
              className={`nav-item ${page === p.id ? 'active' : ''}`}
              onClick={() => setPage(p.id)}
            >
              <span className="nav-icon">{p.icon}</span>
              {p.label}
              {p.id === 'materials' && <span className="badge" id="navBadgeCand">0</span>}
            </button>
          ))}
        </nav>
        <div className="sidebar-foot">
          <span className="dot" />
          数据都在本机 · 未连接云端
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
