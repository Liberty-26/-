// SteelDigitize Pro — 公共类型定义

export interface ReceiptItem {
  row_num?: number;
  id?: number;
  /** 审核会话内稳定的行标识；避免增删行后训练数据按数组下标错配 */
  review_key?: string;
  name: string;
  spec: string;
  unit: string;
  qty: number;
  price: number;
  amount?: number; // 自动计算 qty × price
  rec_amount?: number; // 识别出的每行金额（仅对比审核用，不参与计算）
  // 规则校准附加字段（仅存在于校准响应和前端内存，不入库）
  issues?: string[];      // 异常标记，如 "qty: 数量超出范围"
  corrections?: string[]; // 修正记录，如 "name: 镀锋管→镀锌管"
  not_in_library?: boolean; // 品名不在参考库
}

export interface Material {
  id: number;
  name: string;
  aliases: string;
  unit: string;
  created_at?: string;
}

export interface Receipt {
  id?: number;
  receipt_no: string;
  date: string; // ISO YYYY-MM-DD
  items: ReceiptItem[];
  total_amount?: number;
  rec_total?: number; // 识别出的合计金额（仅对比审核用）
  status?: 'pending' | 'verified' | 'exported';
  image_path?: string;
  operator?: string;
  created_at?: string;
  updated_at?: string;
}

export interface ReceiptSummary {
  id: number;
  receipt_no: string;
  date: string;
  total_amount: number;
  status: string;
  operator: string;
  image_path: string | null;
  summary: string;
  item_count: number;
  created_at: string | null;
}

export interface ApiResponse<T = unknown> {
  success: boolean;
  error?: string;
  data?: T;
}

export interface PaginatedData {
  items: ReceiptSummary[];
  total: number;
  page: number;
  page_size: number;
}

export interface HistoryQuery {
  page?: number;
  page_size?: number;
  date_from?: string;
  date_to?: string;
  receipt_no?: string;
  status?: string;
  date_empty?: boolean; // 只查未填日期单据（资料库"未填日期"账本）
}

export interface MonthStat {
  month: string; // 'YYYY-MM'；'' 表示未填日期单据
  count: number;
  total_amount: number;
}

export interface AgentMessage {
  role: 'user' | 'assistant' | 'system';
  content: string;
  trace?: RunTrace; // 运行痕迹（思考/工具调用过程，完成后收起可展开）
}

// 运行痕迹：一次助手回复的完整执行过程
export interface RunTrace {
  steps: string[];   // 状态序列，如 ['思考中', '执行中', '生成中']
  tools: { name: string; ok: boolean; summary: string; risk?: string; blocked?: boolean }[]; // 工具调用记录
  elapsed: number;   // 总耗时（秒）
  audit?: { tool_calls: number; blocked_calls: number; verified_writes: number; write_authorized: boolean; memory_authorized: boolean; memory_read_revision?: number | null; run_id?: string; execution_failures?: string[] };
}

// ---- 新工作台类型 ----

/** 品名库收录候选：识别中出现的未收录品名 */
export interface MaterialCandidate {
  name: string;
  count: number;
  latest_date: string;
  source?: 'correction' | 'recognition'; // 数据回流：人工修正优先
}

// 别名建议（数据回流 v1：人工修正 → 待确认别名）
export interface AliasSuggestion {
  id: number;
  before_val: string;
  after_val: string;
  count: number;
  status: 'pending' | 'accepted' | 'ignored';
  created_at: string;
}

/** 识别纠错记录 */
export interface CorrectionRecord {
  id: number;
  receipt_no: string;
  field: string;
  before_val: string;
  after_val: string;
  created_at: string;
}

/** 训练数据聚合（数据回流）：字段错误统计 + 错误名→修正结果配对 */
export interface TrainingAggregate {
  total: number;
  fields: { field: string; label: string; count: number; pct: number }[];
  pairs: { before: string; after: string; count: number; pct: number }[];
  quality?: { field: string; label: string; observed: number; corrected: number; rate: number }[];
}

export type PageId = 'workbench' | 'review' | 'library' | 'materials' | 'settings';
