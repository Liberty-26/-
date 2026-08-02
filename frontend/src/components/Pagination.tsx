// SteelDigitize Pro — 分页组件
interface Props {
  page: number;
  pageSize: number;
  total: number;
  onPageChange: (page: number) => void;
  onPageSizeChange: (size: number) => void;
}

const PAGE_SIZES = [10, 20, 50];

export default function Pagination({ page, pageSize, total, onPageChange, onPageSizeChange }: Props) {
  const totalPages = Math.ceil(total / pageSize);
  if (totalPages <= 1 && total <= pageSize) return null;

  const pages: number[] = [];
  const start = Math.max(1, page - 2);
  const end = Math.min(totalPages, page + 2);
  for (let i = start; i <= end; i++) pages.push(i);

  return (
    <div className="flex items-center justify-between mt-stack-md text-label-sm">
      <div className="flex items-center gap-2 text-on-surface-variant">
        <span>每页</span>
        <select
          value={pageSize}
          onChange={(e) => onPageSizeChange(Number(e.target.value))}
          className="bg-white border border-outline-variant rounded px-2 py-0.5"
        >
          {PAGE_SIZES.map((s) => (
            <option key={s} value={s}>{s}</option>
          ))}
        </select>
        <span>条，共 {total} 条</span>
      </div>
      <div className="flex items-center gap-1">
        <button
          onClick={() => onPageChange(page - 1)}
          disabled={page <= 1}
          className="px-2 py-1 rounded hover:bg-surface-container-high disabled:opacity-30 disabled:cursor-not-allowed"
        >
          ‹
        </button>
        {start > 1 && (
          <>
            <button onClick={() => onPageChange(1)} className="px-2 py-1 rounded hover:bg-surface-container-high">1</button>
            {start > 2 && <span className="px-1">…</span>}
          </>
        )}
        {pages.map((p) => (
          <button
            key={p}
            onClick={() => onPageChange(p)}
            className={`px-2 py-1 rounded ${
              p === page ? 'bg-primary text-white' : 'hover:bg-surface-container-high'
            }`}
          >
            {p}
          </button>
        ))}
        {end < totalPages && (
          <>
            {end < totalPages - 1 && <span className="px-1">…</span>}
            <button onClick={() => onPageChange(totalPages)} className="px-2 py-1 rounded hover:bg-surface-container-high">{totalPages}</button>
          </>
        )}
        <button
          onClick={() => onPageChange(page + 1)}
          disabled={page >= totalPages}
          className="px-2 py-1 rounded hover:bg-surface-container-high disabled:opacity-30 disabled:cursor-not-allowed"
        >
          ›
        </button>
      </div>
    </div>
  );
}
