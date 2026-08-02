import sys, os, time, base64, io, asyncio, json
sys.path.insert(0, 'G:/SteelDigitize/backend')
from PIL import Image
from ocr import call_qwen

DATA_DIR = r"C:\Users\DIY\Pictures\数据集"
IMGS = [
    "微信图片_20260731134045_132_6.jpg",
    "微信图片_20260731134110_141_6.jpg",
    "微信图片_20260731134129_148_6.jpg",
]

def compress(path, max_w=1280, quality=80):
    img = Image.open(path)
    w, h = img.size
    if w > max_w:
        img = img.resize((max_w, int(h * max_w / w)), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=quality)
    return base64.b64encode(buf.getvalue()).decode()

async def main():
    for name in IMGS:
        b64 = compress(os.path.join(DATA_DIR, name))
        r = await call_qwen("data:image/jpeg;base64," + b64, model="qwen-vl-max")
        if r.get("success"):
            print("%s → 单号: %s | 日期: %s | %d 行" % (
                name.split("_")[2], r.get("receipt_no", "?"), r.get("date", "?"), len(r.get("items", []))))
        else:
            print("%s → 识别失败: %s" % (name, r.get("error", "?")))

asyncio.run(main())
