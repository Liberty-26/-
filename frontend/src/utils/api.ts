// SteelDigitize Pro — API 调用封装
import type { ApiResponse, Receipt, PaginatedData, HistoryQuery, MonthStat } from '../types';

const BASE = '/api';
const TIMEOUT_MS = 300000;

async function request<T>(method: string, path: string, body?: unknown): Promise<ApiResponse<T>> {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), TIMEOUT_MS);

  try {
    const opts: RequestInit = {
      method,
      headers: { 'Content-Type': 'application/json' },
      signal: controller.signal,
    };
    if (body !== undefined) {
      opts.body = JSON.stringify(body);
    }

    const resp = await fetch(`${BASE}${path}`, opts);
    const json = await resp.json();

    if (!resp.ok) {
      return { success: false, error: json.detail || `HTTP ${resp.status}` };
    }
    return json as ApiResponse<T>;
  } catch (err: unknown) {
    if (err instanceof DOMException && err.name === 'AbortError') {
      return { success: false, error: '请求超时，请重试' };
    }
    return { success: false, error: (err as Error).message || '网络错误' };
  } finally {
    clearTimeout(timeout);
  }
}

// ---- 识别 ----

export async function recognizeImage(imageBase64: string, receiptNo?: string, date?: string) {
  // 从 localStorage 读当前选的识图模型，传给后端优先使用（后端未传时用 .env 默认）
  const model = localStorage.getItem('steel_vision_model') || undefined;
  return request<{ receipt_no: string; date: string; date_suspicious?: boolean; image_path: string; items: import('../types').ReceiptItem[] }>(
    'POST', '/recognize', { image_base64: imageBase64, receipt_no: receiptNo, date, model }
  );
}

export async function calibrateItems(items: { name: string; spec: string; unit: string; qty: number; price: number }[], receiptNo?: string, date?: string) {
  return request<{ items: import('../types').ReceiptItem[]; header_rows: number[] }>(
    'POST', '/recognize/calibrate', { items, receipt_no: receiptNo, date }
  );
}

// ---- 品名库 ----

export async function getMaterials(search?: string) {
  const params = new URLSearchParams();
  if (search) params.set('search', search);
  return request<{ items: import('../types').Material[]; total: number }>('GET', `/materials?${params.toString()}`);
}

export async function createMaterial(data: { name: string; aliases: string; unit: string }) {
  return request<{ id: number }>('POST', '/materials', data);
}

export async function updateMaterial(id: number, data: { name: string; aliases: string; unit: string }) {
  return request<void>('PUT', `/materials/${id}`, data);
}

export async function deleteMaterial(id: number) {
  return request<void>('DELETE', `/materials/${id}`);
}

// ---- 历史 CRUD ----

export async function saveReceipt(receipt: Receipt) {
  return request<Receipt>('POST', '/history', {
    receipt_no: receipt.receipt_no,
    date: receipt.date,
    items: receipt.items,
    image_path: receipt.image_path || '',
  });
}

export async function getHistory(query: HistoryQuery) {
  const params = new URLSearchParams();
  if (query.page) params.set('page', String(query.page));
  if (query.page_size) params.set('page_size', String(query.page_size));
  if (query.date_from) params.set('date_from', query.date_from);
  if (query.date_to) params.set('date_to', query.date_to);
  if (query.receipt_no) params.set('receipt_no', query.receipt_no);
  if (query.status) params.set('status', query.status);
  if (query.date_empty) params.set('date_empty', '1');
  return request<PaginatedData>('GET', `/history?${params.toString()}`);
}

// 资料库书架：按月统计
export async function getHistoryMonths() {
  return request<{ months: MonthStat[] }>('GET', '/history/months');
}

export async function getReceiptDetail(id: number) {
  return request<Receipt>('GET', `/history/${id}`);
}

export async function updateReceipt(id: number, receipt: Receipt) {
  return request<void>('PUT', `/history/${id}`, {
    receipt_no: receipt.receipt_no,
    date: receipt.date,
    items: receipt.items,
  });
}

export async function deleteReceipt(id: number) {
  return request<void>('DELETE', `/history/${id}`);
}

// ---- 配置 ----

export async function getSettings() {
  return request<{
    qwen_api_key: string; qwen_model: string;
    deepseek_api_key: string; available_models?: { id: string; label: string }[];
  }>('GET', '/settings');
}

export async function saveSettings(settings: {
  qwen_api_key?: string; qwen_model?: string;
  deepseek_api_key?: string; work_dir?: string;
}) {
  return request<void>('POST', '/settings', settings);
}

export async function testQwenConnection(apiKey: string, model: string) {
  return request<{ latency_ms: number; status: string }>('POST', '/settings/test-qwen', {
    api_key: apiKey, model,
  });
}

// ---- Agent ----

export async function agentChat(message: string, history: { role: string; content: string }[], selectedIds?: number[], uploadedFile?: string) {
  return request<{ reply: string; history: { role: string; content: string }[] }>(
    'POST', '/agent/chat', { message, history, selected_ids: selectedIds, uploaded_file: uploadedFile }
  );
}

// 上传已有 Excel 文件（Agent 操作目标）
export async function uploadAgentFile(file: File): Promise<ApiResponse<{ path: string; url: string; filename: string }>> {
  const form = new FormData();
  form.append('file', file);
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 30000);
  try {
    const resp = await fetch('/api/agent/upload-file', { method: 'POST', body: form, signal: controller.signal });
    const json = await resp.json();
    if (!resp.ok) return { success: false, error: json.detail || `HTTP ${resp.status}` };
    return json as ApiResponse<{ path: string; url: string; filename: string }>;
  } catch (err) {
    return { success: false, error: (err as Error).message || '上传失败' };
  } finally { clearTimeout(timeout); }
}

export async function getAgentReceipts() {
  return request<{ receipts: { id: number; receipt_no: string; date: string; total_amount: number; status: string; item_count: number }[] }>(
    'GET', '/agent/receipts'
  );
}

export async function markExported(receiptId: number) {
  return request<void>('POST', '/agent/mark-exported', { receipt_id: receiptId });
}

// ---- 对话消息持久化 ----

export async function loadMessages() {
  return request<{ messages: { id: number; role: string; content: string; created_at: string }[] }>('GET', '/agent/messages');
}

export async function saveMessage(role: string, content: string) {
  return request<void>('POST', '/agent/messages', { role, content });
}

// ---- 技能 ----

export async function getSkills() {
  return request<{ skills: { id: number; name: string; description: string; prompt: string; system_instruction: string; enabled: number; created_at: string }[] }>('GET', '/agent/skills');
}

export async function generateSkill(description: string) {
  return request<{ name: string; description: string; prompt: string; system_instruction: string }>('POST', '/agent/skills/generate', { description });
}

export async function createSkill(skill: { name: string; description: string; prompt: string; system_instruction: string }) {
  return request<{ id: number }>('POST', '/agent/skills', skill);
}

export async function deleteSkillApi(id: number) {
  return request<void>('DELETE', `/agent/skills/${id}`);
}

// ---- 监控 ----

export async function getMonitor() {
  return request<{ total_receipts: number; today_count: number; exported: number; pending: number; verified: number; total_tokens: number; today_tokens: number; uptime_seconds: number }>('GET', '/agent/monitor');
}
