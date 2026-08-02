// SteelDigitize Pro — 图片预览（缩放+拖拽，滚轮上限2x，不干扰页面滚动）
import { useRef, useState, useCallback, useEffect } from 'react';
import type { MouseEvent, WheelEvent } from 'react';

interface Props {
  src: string;
  filename: string;
  onClear: () => void;
}

export default function ImagePreview({ src, filename, onClear }: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [scale, setScale] = useState(1);
  const [pos, setPos] = useState({ x: 0, y: 0 });
  const [dragging, setDragging] = useState(false);
  const [dragStart, setDragStart] = useState({ x: 0, y: 0 });
  const [showHint, setShowHint] = useState(true);

  useEffect(() => {
    setScale(1);
    setPos({ x: 0, y: 0 });
    setShowHint(true);
    const timer = setTimeout(() => setShowHint(false), 3000);
    return () => clearTimeout(timer);
  }, [src]);

  // 非 passive 滚轮事件，确保 preventDefault 生效
  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const handler = (e: globalThis.WheelEvent) => {
      e.preventDefault();
      const delta = e.deltaY > 0 ? -0.08 : 0.08;
      setScale((s) => Math.min(2, Math.max(0.1, Math.round((s + delta) * 100) / 100)));
    };
    el.addEventListener('wheel', handler, { passive: false });
    return () => el.removeEventListener('wheel', handler);
  }, []);

  const handleWheel = useCallback((e: WheelEvent) => {
    e.preventDefault();
  }, []);

  const handleMouseDown = useCallback((e: MouseEvent) => {
    setDragging(true);
    setDragStart({ x: e.clientX - pos.x, y: e.clientY - pos.y });
  }, [pos]);

  const handleMouseMove = useCallback((e: MouseEvent) => {
    if (!dragging) return;
    setPos({ x: e.clientX - dragStart.x, y: e.clientY - dragStart.y });
  }, [dragging, dragStart]);

  const handleMouseUp = useCallback(() => setDragging(false), []);

  return (
    <div className="flex-1 flex flex-col bg-[#334155] relative overflow-hidden">
      {/* 顶栏 */}
      <div className="h-10 bg-surface-container-lowest border-b border-outline-variant flex items-center justify-between px-4 shrink-0">
        <div className="flex items-center gap-2">
          <span className="material-symbols-outlined text-primary text-sm">image</span>
          <span className="font-label-sm text-on-surface-variant truncate max-w-[200px]">{filename}</span>
        </div>
        <button
          onClick={onClear}
          className="text-outline hover:text-error transition-colors flex items-center"
          title="清除图片"
        >
          <span className="material-symbols-outlined text-sm">close</span>
        </button>
      </div>

      {/* 预览区 */}
      <div
        ref={containerRef}
        className="flex-1 flex items-center justify-center p-8 overflow-hidden cursor-crosshair"
        onWheel={handleWheel}
        onMouseDown={handleMouseDown}
        onMouseMove={handleMouseMove}
        onMouseUp={handleMouseUp}
        onMouseLeave={handleMouseUp}
      >
        <img
          src={src}
          alt="单据预览"
          className="shadow-2xl max-w-full select-none pointer-events-none"
          style={{
            transform: `translate(${pos.x}px, ${pos.y}px) scale(${scale})`,
            transformOrigin: 'center',
            transition: dragging ? 'none' : 'transform 0.1s ease-out',
          }}
        />
      </div>

      {/* 缩放提示 */}
      <div
        className={`absolute bottom-4 left-1/2 -translate-x-1/2 bg-black/60 text-white text-[10px] px-3 py-1 rounded-full backdrop-blur-sm transition-opacity pointer-events-none ${
          showHint ? 'opacity-100' : 'opacity-0'
        }`}
      >
        滚轮缩放 / 拖拽移动 (max 2x)
      </div>
    </div>
  );
}
