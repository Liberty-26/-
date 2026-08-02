// SteelDigitize Pro — 全局布局（白色侧边栏 + 滑动填充悬停动画，Tab 切换不销毁页面）
import { useState } from 'react';

const TABS = [
  { id: 'upload', label: '上传与识别' },
  { id: 'history', label: '资料库' },
  { id: 'agent', label: 'Agent' },
  { id: 'materials', label: '品名库' },
  { id: 'settings', label: 'API与模型' },
] as const;
type TabId = (typeof TABS)[number]['id'];

const TAB_STORAGE_KEY = 'steel_active_tab';

function getInitialTab(): TabId {
  const saved = localStorage.getItem(TAB_STORAGE_KEY) as TabId | null;
  if (saved && TABS.some(t => t.id === saved)) {
    return saved;
  }
  return 'upload';
}

interface Props {
  children: (active: TabId, currentTab: TabId) => React.ReactNode;
}

export default function Layout({ children }: Props) {
  const [active, setActive] = useState<TabId>(getInitialTab);

  const switchTab = (id: TabId) => {
    setActive(id);
    localStorage.setItem(TAB_STORAGE_KEY, id);
  };

  return (
    <div className="h-screen overflow-hidden flex bg-background">
      {/* 侧边栏：260px 白色导航 */}
      <aside className="w-sidebar-width shrink-0 h-full bg-white border-r border-outline-variant flex flex-col fixed left-0 top-0 z-50">
        {/* 品牌区 */}
        <div className="h-16 flex items-center px-6 border-b border-outline-variant/50">
          <span className="font-bold text-headline-lg text-primary tracking-tight">
            SteelDigitize Pro
          </span>
        </div>

        {/* 导航项：hover 整体平滑过渡到蓝色（cubic-bezier 缓动），点击后蓝色常亮 */}
        <nav className="flex-1 py-4 flex flex-col gap-1.5 px-3 overflow-y-auto">
          {TABS.map((tab) => (
            <button
              key={tab.id}
              onClick={() => switchTab(tab.id)}
              className={`relative h-11 rounded-lg text-left px-4 text-label-sm
                transition-all duration-300 ease-[cubic-bezier(0.16,1,0.3,1)] ${
                active === tab.id
                  ? 'bg-primary text-white font-semibold'
                  : 'bg-transparent text-on-surface-variant hover:bg-primary hover:text-white'
              }`}
            >
              {tab.label}
            </button>
          ))}
        </nav>

        {/* 底部：刷新 */}
        <div className="p-3 border-t border-outline-variant/50">
          <button
            onClick={() => window.location.reload()}
            className="w-full h-10 rounded-lg text-label-sm text-on-surface-variant
              transition-all duration-300 ease-[cubic-bezier(0.16,1,0.3,1)]
              hover:bg-primary hover:text-white flex items-center justify-center gap-2"
            title="刷新页面"
          >
            <span className="material-symbols-outlined text-base">refresh</span>
            刷新
          </button>
        </div>
      </aside>

      {/* 主内容区 —— 所有页面常驻，只显示当前 */}
      <main className="flex-1 ml-sidebar-width overflow-hidden">
        {TABS.map((tab) => (
          <div key={tab.id} className="h-full" style={{ display: tab.id === active ? undefined : 'none' }}>
            {children(tab.id, active)}
          </div>
        ))}
      </main>
    </div>
  );
}
