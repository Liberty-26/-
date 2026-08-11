// SteelDigitize Pro — API 调用封装
import type {
  ApiResponse, Receipt, PaginatedData, HistoryQuery, MonthStat,
  MaterialCandidate, CorrectionRecord, AliasSuggestion,
  TrainingAggregate,
} from '../types';

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
      // FastAPI 422 校验错误 detail 可能是对象/数组（如 [{type,loc,msg,input,ctx}]），归一为可读字符串
      const detail = json.detail;
      let errMsg: string;
      if (typeof detail === 'string') errMsg = detail;
      else if (Array.isArray(detail)) errMsg = detail.map((d: { msg?: string }) => d.msg || JSON.stringify(d)).join('；');
      else if (detail && typeof detail === 'object') errMsg = JSON.stringify(detail);
      else errMsg = `HTTP ${resp.status}`;
      return { success: false, error: errMsg };
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
  return request<{ receipt_no: string; date: string; date_suspicious?: boolean; rec_total?: number | null; image_path: string; items: import('../types').ReceiptItem[] }>(
    'POST', '/recognize', { image_base64: imageBase64, receipt_no: receiptNo, date }
  );
}

export async function calibrateItems(items: { name: string; spec: string; unit: string; qty: number; price: number; rec_amount?: number }[], receiptNo?: string, date?: string) {
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

/** 品名收录候选：识别中出现的未收录品名 */
export async function getMaterialCandidates() {
  return request<{ items: MaterialCandidate[] }>('GET', '/materials/candidates');
}

/** 持久化忽略一个品名候选，刷新后不再重复出现 */
export async function ignoreMaterialCandidate(name: string) {
  return request<void>('POST', `/materials/candidates/${encodeURIComponent(name)}/ignore`);
}

/** 别名建议（数据回流）：人工修正 → 待确认别名 */
export async function getAliasSuggestions() {
  return request<{ items: AliasSuggestion[] }>('GET', '/materials/alias-suggestions');
}

export async function acceptAliasSuggestion(id: number) {
  return request<{ before: string; after: string }>('POST', `/materials/alias-suggestions/${id}/accept`);
}

export async function ignoreAliasSuggestion(id: number) {
  return request<void>('POST', `/materials/alias-suggestions/${id}/ignore`);
}

// ---- 历史 CRUD ----

export async function saveReceipt(receipt: Receipt) {
  return request<Receipt>('POST', '/history', {
    receipt_no: receipt.receipt_no,
    date: receipt.date,
    items: receipt.items,
    image_path: receipt.image_path || '',
    rec_total: receipt.rec_total ?? null,
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
    rec_total: receipt.rec_total ?? null,
  });
}

/** 确认入库：标记单据为已核对 */
export async function verifyReceipt(id: number) {
  return request<void>('POST', `/history/${id}/verify`);
}

export async function deleteReceipt(id: number) {
  return request<void>('DELETE', `/history/${id}`);
}

// ---- 配置 ----

export async function getSettings() {
  return request<{
    qwen_api_key: string; qwen_model: string;
    deepseek_api_key: string; available_models?: { id: string; label: string }[];
    agent_api_key: string; agent_api_base: string; agent_model: string;
    scan_api_key: string; scan_api_base: string; scan_scene: string;
    work_dir: string; backup_dir: string;
  }>('GET', '/settings');
}

export async function saveSettings(settings: {
  qwen_api_key?: string; qwen_model?: string;
  deepseek_api_key?: string; work_dir?: string;
  agent_key?: string; agent_base?: string; agent_model?: string;
  scan_key?: string; scan_base?: string; scan_scene?: string;
  backup_dir?: string;
}) {
  return request<void>('POST', '/settings', settings);
}

/** 扫描王官方场景列表 */
export async function getScanScenes() {
  return request<{ scenes: { scene: string; label: string; type: string }[]; current: string }>('GET', '/settings/scan-scenes');
}

/** 一键备份（数据 + 上传图片 → zip） */
export async function exportBackup() {
  return request<{ path: string }>('POST', '/settings/backup');
}

/** 最近备份列表 */
export async function getBackups() {
  return request<{ backups: { name: string; size: number; created_at: string; path?: string }[] }>('GET', '/settings/backups');
}

/** 打开系统原生目录选择器（工作目录 / 备份目录共用） */
export async function pickDirectory(): Promise<ApiResponse<{ path: string }>> {
  try {
    const steel = (window as any).steel;
    if (steel && steel.pickDirectory) {
      const result = await steel.pickDirectory();
      return { success: Boolean(result?.ok && result.path), data: { path: result?.path || '' } };
    }
    const resp = await fetch('/api/settings/pick-dir');
    const json = await resp.json();
    if (!resp.ok) return { success: false, error: json.detail || `HTTP ${resp.status}` };
    return json as ApiResponse<{ path: string }>;
  } catch (err) {
    return { success: false, error: (err as Error).message || '选择失败' };
  }
}

/** 工作目录内真实存在的 Excel 文件和 sheet */
export async function getSpreadsheetTargets() {
  return request<{
    configured: boolean;
    directory_exists: boolean;
    directory: string;
    files: { name: string; path: string; size: number; updated_at: string; sheets: string[]; error: string }[];
  }>('GET', '/settings/spreadsheets');
}

/** 测试扫描王连接并测速（真实调用一次，消耗额度） */
export async function testScanConnection(apiKey: string, apiBase: string, scene: string) {
  return request<{ latency_ms: number; status: string; message: string }>('POST', '/settings/test-scan', {
    api_key: apiKey, api_base: apiBase, scene,
  });
}

export async function testQwenConnection(apiKey: string, model: string) {
  return request<{ latency_ms: number; status: string }>('POST', '/settings/test-qwen', {
    api_key: apiKey, model,
  });
}

// ---- Agent ----

export async function agentChat(
  message: string,
  history: { role: string; content: string }[],
  selectedIds?: number[],
  uploadedFile?: string,
  sessionId?: string
) {
  return request<{ reply: string; history: { role: string; content: string }[] }>(
    'POST', '/agent/chat', { message, history, selected_ids: selectedIds, uploaded_file: uploadedFile, session_id: sessionId }
  );
}

/** 流式 Agent 聊天：直接返回 fetch Response，由调用方解析 SSE 事件 */
export function agentChatStream(
  message: string,
  history: { role: string; content: string }[],
  selectedIds?: number[],
  uploadedFile?: string,
  sessionId?: string,
  externalSignal?: AbortSignal
): Promise<Response> {
  // 预览模式：URL 带 mock=1 时走后端模拟流程（不调用模型、不消耗额度）
  const mock = window.location.search.includes('mock=1') ? '?mock=1' : '';
  // 流式请求必须有超时保护：后端/模型卡住时不能让输入框被永久禁用
  const ctrl = new AbortController();
  const headerTimeout = window.setTimeout(() => ctrl.abort(), 60000); // 60s 等响应头
  const onExternalAbort = () => ctrl.abort();
  if (externalSignal) {
    if (externalSignal.aborted) ctrl.abort();
    else externalSignal.addEventListener('abort', onExternalAbort, { once: true });
  }
  return fetch('/api/agent/chat/stream' + mock, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    signal: ctrl.signal,
    body: JSON.stringify({
      message,
      history,
      selected_ids: selectedIds,
      uploaded_file: uploadedFile,
      session_id: sessionId,
    }),
  }).finally(() => {
    window.clearTimeout(headerTimeout);
    externalSignal?.removeEventListener('abort', onExternalAbort);
  });
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

export async function getSessions() {
  return request<{ sessions: {
    id: string; title: string; message_count: number; last_at: string | null; created_at: string; updated_at: string;
  }[] }>('GET', '/agent/sessions');
}

export async function createSession(title?: string) {
  return request<{ id: string; title: string }>('POST', '/agent/sessions', { title });
}

export async function deleteSession(sessionId: string) {
  return request<void>('DELETE', `/agent/sessions/${sessionId}`);
}

export async function loadMessages(sessionId?: string) {
  const q = sessionId ? `?session_id=${encodeURIComponent(sessionId)}` : '';
  return request<{ messages: { id: number; role: string; content: string; trace?: string; created_at: string }[] }>(
    'GET', `/agent/messages${q}`
  );
}

export async function saveMessage(role: string, content: string, sessionId?: string, trace?: unknown) {
  return request<void>('POST', '/agent/messages', { role, content, session_id: sessionId, trace });
}

export async function clearMessages(sessionId?: string) {
  const q = sessionId ? `?session_id=${encodeURIComponent(sessionId)}` : '';
  return request<void>('DELETE', `/agent/messages${q}`);
}

// ---- 技能 ----

export async function getSkills() {
  return request<{ skills: { id: number; name: string; description: string; prompt: string; system_instruction: string; triggers: string; enabled: number; created_at: string }[] }>('GET', '/agent/skills');
}

export async function generateSkill(description: string) {
  return request<{ name: string; description: string; prompt: string; system_instruction: string; triggers: string }>('POST', '/agent/skills/generate', { description });
}

export async function createSkill(skill: { name: string; description: string; prompt: string; system_instruction: string; triggers?: string }) {
  return request<{ id: number }>('POST', '/agent/skills', skill);
}

export async function deleteSkillApi(id: number) {
  return request<void>('DELETE', `/agent/skills/${id}`);
}

// ---- 监控 ----

export async function getMonitor() {
  return request<{ total_receipts: number; today_count: number; exported: number; pending: number; verified: number; total_tokens: number; today_tokens: number; uptime_seconds: number }>('GET', '/agent/monitor');
}

// ---- Agent 长期记忆（单一 Prompt） ----

export async function getMemory() {
  return request<{ content: string; chars: number; limit: number; revision: number; capacity: { needs_compaction: boolean; compaction_target: number; remaining: number }; updated_at: string }>('GET', '/memory');
}

export async function saveMemory(content: string, revision: number) {
  return request<{ content: string; chars: number; limit: number; revision: number; capacity: { needs_compaction: boolean; compaction_target: number; remaining: number }; updated_at: string }>('PUT', '/memory', { content, revision });
}

export async function getCorrections(limit = 200) {
  return request<{ corrections: CorrectionRecord[] }>('GET', `/memory/corrections?limit=${limit}`);
}

/** 训练数据聚合：字段错误统计 + 错误名→修正结果配对（线宽 = 次数占比） */
export async function getTrainingAggregate() {
  return request<TrainingAggregate>('GET', '/memory/corrections/aggregate');
}

export async function addCorrections(
  changes: { receipt_no: string; field: string; before_val: string; after_val: string }[],
  observations: { receipt_id: number; field: string; observed_count: number; corrected_count: number }[] = [],
) {
  return request<void>('POST', '/memory/corrections', { changes, observations });
}

export async function deleteCorrection(id: number) {
  return request<void>('DELETE', `/memory/corrections/${id}`);
}

export async function clearCorrections() {
  return request<void>('DELETE', '/memory/corrections');
}

// ---- 校准（纯代码，SSE 流式） ----

export async function calibrateItemsSSE(items: { name: string; spec: string; unit: string; qty: number; price: number; rec_amount?: number }[], receiptNo?: string, date?: string) {
  try {
    const resp = await fetch('/api/recognize/calibrate', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ items, receipt_no: receiptNo, date }),
    });
    if (!resp.ok || !resp.body) throw new Error(`HTTP ${resp.status}`);
    const reader = resp.body.getReader();
    const decoder = new TextDecoder();
    let buf = '';
    let last: { done: boolean; result?: { items: unknown; header_rows: number[] }; error?: string } | null = null;
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buf += decoder.decode(value, { stream: true });
      const events = buf.split('\n\n');
      buf = events.pop() || '';
      for (const evt of events) {
        const line = evt.trim();
        if (!line.startsWith('data: ')) continue;
        const data = JSON.parse(line.slice(6));
        if (data.step === 0) last = data;
      }
    }
    if (last?.done && last.result) {
      return { success: true, data: { items: last.result.items as import('../types').ReceiptItem[], header_rows: last.result.header_rows || [] } };
    }
    return { success: false, error: last?.error || '校准失败' };
  } catch (e) {
    return { success: false, error: (e as Error).message || '校准请求失败' };
  }
}
