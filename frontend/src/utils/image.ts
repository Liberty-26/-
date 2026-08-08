// SteelDigitize Pro — 图片压缩与读取工具

const MAX_WIDTH = 1024;
const JPEG_QUALITY = 0.65;
const ALLOWED_TYPES = ['image/jpeg', 'image/png', 'image/webp'];

/** 单张图片压缩为 data URL（保留原版设计：宽 1024px、质量 0.65） */
export function compressImage(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    // 从系统相册/拖拽进来时浏览器可能拿不到 type，按扩展名兜底
    const name = (file.name || '').toLowerCase();
    const type =
      file.type ||
      (name.endsWith('.png') ? 'image/png' :
        name.endsWith('.webp') ? 'image/webp' :
        name.endsWith('.jpg') || name.endsWith('.jpeg') ? 'image/jpeg' : '');
    if (!ALLOWED_TYPES.includes(type)) {
      reject(new Error('请上传 jpg/png 格式'));
      return;
    }

    // 防止 FileReader/Image 回调永不触发导致 Promise 悬挂（上传永远卡住）
    const TIMEOUT_MS = 20000;
    let settled = false;
    const timer = window.setTimeout(() => {
      if (!settled) {
        settled = true;
        reject(new Error('图片处理超时，请换一张或转成 JPG 再试'));
      }
    }, TIMEOUT_MS);
    const finish = (err?: Error, data?: string) => {
      if (settled) return;
      settled = true;
      window.clearTimeout(timer);
      if (err) reject(err);
      else resolve(data as string);
    };

    const reader = new FileReader();
    reader.onload = () => {
      const img = new Image();
      img.onload = () => {
        try {
          const canvas = document.createElement('canvas');
          let w = img.width;
          let h = img.height;
          if (!w || !h) throw new Error('图片尺寸无效');
          if (w > MAX_WIDTH) {
            h = Math.round(h * (MAX_WIDTH / w));
            w = MAX_WIDTH;
          }
          canvas.width = w;
          canvas.height = h;
          const ctx = canvas.getContext('2d')!;
          ctx.drawImage(img, 0, 0, w, h);
          finish(undefined, canvas.toDataURL('image/jpeg', JPEG_QUALITY));
        } catch (e) {
          finish(e instanceof Error ? e : new Error('图片压缩失败'));
        }
      };
      img.onerror = () => finish(new Error('图片解析失败，请转成 JPG 再试'));
      img.src = reader.result as string;
    };
    reader.onerror = () => finish(new Error('文件读取失败'));
    reader.readAsDataURL(file);
  });
}

/** 把 /uploads 下的图片文件读成 data URL（用于重新识别） */
export function fetchUploadAsDataUrl(url: string): Promise<string> {
  return new Promise((resolve, reject) => {
    fetch(url)
      .then((r) => (r.ok ? r.blob() : Promise.reject(new Error('HTTP ' + r.status))))
      .then((blob) => {
        const reader = new FileReader();
        reader.onload = () => resolve(reader.result as string);
        reader.onerror = () => reject(new Error('读取失败'));
        reader.readAsDataURL(blob);
      })
      .catch(reject);
  });
}
