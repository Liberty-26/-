import { AlertTriangle, FileSpreadsheet, ShieldCheck } from 'lucide-react';

export interface PendingApproval {
  approval_id: string;
  thread_id: string;
  task_id: string;
  tool_name: string;
  risk: string;
  parameter_summary: {
    filename?: string;
    receipt_count?: number;
    expected_revision?: number | null;
    content_redacted?: boolean;
  };
}

interface Props {
  approval: PendingApproval | null;
  busy?: boolean;
  onApprove: () => void;
  onReject: () => void;
}

const TOOL_LABELS: Record<string, string> = {
  spreadsheet_export_receipts: '导出对账单',
  memory_replace: '修改长期记忆',
};

export default function ApprovalDialog({ approval, busy = false, onApprove, onReject }: Props) {
  if (!approval) return null;
  const summary = approval.parameter_summary;
  const action = TOOL_LABELS[approval.tool_name] || '执行受保护操作';
  const isExport = approval.tool_name === 'spreadsheet_export_receipts';

  return (
    <div className="modal-mask show" role="presentation">
      <section className="modal approval-dialog" role="dialog" aria-modal="true" aria-labelledby="approval-title">
        <div className="modal-head">
          <div className="approval-title-wrap">
            <span className="approval-alert"><AlertTriangle size={18} /></span>
            <div className="modal-title" id="approval-title">
              <span className="modal-kicker">需要你的批准</span>
              {action}
            </div>
          </div>
          <span className="tool-risk write">写入</span>
        </div>
        <div className="modal-body approval-body">
          <p>此操作尚未执行。批准后将仅执行本次已暂停的工具调用。</p>
          <div className="approval-summary">
            {isExport ? <FileSpreadsheet size={17} /> : <ShieldCheck size={17} />}
            <div>
              {isExport ? (
                <>
                  <strong>{summary.filename || '未命名对账单.xlsx'}</strong>
                  <span>将导出 {summary.receipt_count ?? 0} 张单据</span>
                </>
              ) : (
                <>
                  <strong>长期记忆内容已隐藏</strong>
                  <span>基于版本 {summary.expected_revision ?? '当前'} 修改</span>
                </>
              )}
            </div>
          </div>
        </div>
        <div className="modal-foot">
          <button className="btn ghost" disabled={busy} onClick={onReject}>拒绝</button>
          <button className="btn" disabled={busy} onClick={onApprove}>{busy ? '处理中…' : '批准执行'}</button>
        </div>
      </section>
    </div>
  );
}
