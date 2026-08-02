// SteelDigitize Pro — 拖拽上传组件
import { useCallback, useRef, useState } from 'react';
import type { ChangeEvent, DragEvent } from 'react';

interface Props {
  onImageReady: (base64: string, filename: string) => void;
  disabled?: boolean;
}

const MAX_WIDTH = 1024;
const JPEG_QUALITY = 0.65;
const ALLOWED_TYPES = ['image/jpeg', 'image/png', 'image/webp'];

export default function UploadZone({ onImageReady, disabled }: Props) {
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [dragOver, setDragOver] = useState(false);

  const processFile = useCallback((file: File) => {
    if (!ALLOWED_TYPES.includes(file.type)) {
      alert('请上传 jpg/png 格式');
      return;
    }

    const reader = new FileReader();
    reader.onload = () => {
      const img = new Image();
      img.onload = () => {
        // Canvas 缩放至 1920px 宽以内
        const canvas = document.createElement('canvas');
        let w = img.width;
        let h = img.height;
        if (w > MAX_WIDTH) {
          h = Math.round(h * (MAX_WIDTH / w));
          w = MAX_WIDTH;
        }
        canvas.width = w;
        canvas.height = h;
        const ctx = canvas.getContext('2d')!;
        ctx.drawImage(img, 0, 0, w, h);
        const dataUrl = canvas.toDataURL('image/jpeg', JPEG_QUALITY);
        onImageReady(dataUrl, file.name);
      };
      img.src = reader.result as string;
    };
    reader.readAsDataURL(file);
  }, [onImageReady]);

  const handleDrop = useCallback((e: DragEvent) => {
    e.preventDefault();
    setDragOver(false);
    if (disabled) return;
    const file = e.dataTransfer.files[0];
    if (file) processFile(file);
  }, [disabled, processFile]);

  const handleChange = useCallback((e: ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file) processFile(file);
    // 重置 input，允许重新选择同一文件
    e.target.value = '';
  }, [processFile]);

  return (
    <div
      className={`border-2 border-dashed rounded-xl flex flex-col items-center justify-center p-6 gap-3 transition-colors cursor-pointer bg-white/5 ${
        dragOver ? 'border-primary/70 bg-primary/5' : 'border-outline-variant/30 hover:border-primary/50'
      }`}
      onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
      onDragLeave={() => setDragOver(false)}
      onDrop={handleDrop}
      onClick={() => !disabled && fileInputRef.current?.click()}
    >
      <span className="material-symbols-outlined text-4xl text-outline-variant/40">photo_camera</span>
      <span className="text-label-sm text-outline-variant">上传单据照片</span>
      <input
        ref={fileInputRef}
        type="file"
        accept="image/*"
        className="hidden"
        onChange={handleChange}
        disabled={disabled}
      />
      <button
        type="button"
        className="bg-primary text-white px-4 py-1.5 rounded-lg font-medium text-label-sm hover:bg-primary-container transition-colors"
        onClick={(e) => { e.stopPropagation(); fileInputRef.current?.click(); }}
      >
        选择文件
      </button>
    </div>
  );
}
