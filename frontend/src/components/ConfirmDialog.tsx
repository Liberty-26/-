// SteelDigitize Pro — 确认对话框
interface Props {
  open: boolean;
  title?: string;
  message: string;
  onConfirm: () => void;
  onCancel: () => void;
}

export default function ConfirmDialog({ open, title = '确认', message, onConfirm, onCancel }: Props) {
  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/30">
      <div className="bg-surface-container-lowest rounded-xl p-6 shadow-[0_4px_6px_-1px_rgba(0,0,0,0.1)] max-w-sm w-full mx-4">
        <h3 className="font-headline-md text-headline-md text-on-surface mb-2">{title}</h3>
        <p className="text-body-md text-on-surface-variant mb-6">{message}</p>
        <div className="flex justify-end gap-3">
          <button
            onClick={onCancel}
            className="px-4 py-2 text-label-sm border border-outline-variant rounded-lg text-on-surface-variant hover:bg-surface-container-low transition-colors"
          >
            取消
          </button>
          <button
            onClick={onConfirm}
            className="px-4 py-2 text-label-sm bg-primary text-on-primary rounded-lg hover:bg-primary-container transition-colors"
          >
            确定
          </button>
        </div>
      </div>
    </div>
  );
}
