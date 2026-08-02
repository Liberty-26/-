// SteelDigitize Pro — 工具函数

/** 格式化金额（2 位小数，千分位） */
export function formatAmount(val: number): string {
  return val.toFixed(2);
}

/** 格式化日期为 YYYY-MM-DD */
export function formatDate(d: Date): string {
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, '0');
  const day = String(d.getDate()).padStart(2, '0');
  return `${y}-${m}-${day}`;
}

/** 获取今天的 ISO 日期字符串 */
export function todayISO(): string {
  return formatDate(new Date());
}

/** 计算 items 合计金额 */
export function calcTotal(items: { qty: number; price: number }[]): number {
  return items.reduce((sum, it) => sum + it.qty * it.price, 0);
}
