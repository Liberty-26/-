"""
SteelDigitize Pro — Pydantic 数据模型
"""
from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import date


# ---- 请求模型 ----

class RecognizeRequest(BaseModel):
    image_base64: str = Field(..., description="图片 base64 编码，不含 data:image 前缀亦可")
    receipt_no: Optional[str] = Field(None, description="单据单号")
    date: Optional[str] = Field(None, description="单据日期 YYYY-MM-DD")
    model: Optional[str] = Field(None, description="识图模型名，前端可选传入；不传则用后端默认")


class CalibrateItem(BaseModel):
    """待校准的识别条目"""
    name: str = ""
    spec: str = ""
    unit: str = ""
    qty: float = 0
    price: float = 0


class CalibrateRequest(BaseModel):
    items: List[CalibrateItem]
    receipt_no: Optional[str] = None
    date: Optional[str] = None


class ReceiptItemIn(BaseModel):
    """单条物品明细（请求）"""
    name: str = ""
    spec: str = ""
    unit: str = ""
    qty: float = 0
    price: float = 0


class SaveReceiptRequest(BaseModel):
    receipt_no: str = ""
    date: str = ""  # YYYY-MM-DD
    items: List[ReceiptItemIn] = []
    image_path: Optional[str] = None


class UpdateReceiptRequest(BaseModel):
    receipt_no: str = ""
    date: str = ""
    items: List[ReceiptItemIn] = []


class TestQwenRequest(BaseModel):
    api_key: str
    model: str = "qwen-vl-flash"


class AgentChatRequest(BaseModel):
    message: str
    history: List[dict] = []
    selected_ids: Optional[List[int]] = None  # 前端勾选要操作的单据 ID
    uploaded_file: Optional[str] = None       # 前端上传的已有 Excel 文件路径


class SaveSettingsRequest(BaseModel):
    qwen_api_key: Optional[str] = None
    qwen_model: Optional[str] = None
    deepseek_api_key: Optional[str] = None
    spreadsheet_path: Optional[str] = None


# ---- 响应模型 ----

class ReceiptItemOut(BaseModel):
    id: Optional[int] = None
    row_num: int = 0
    name: str = ""
    spec: str = ""
    unit: str = ""
    qty: float = 0
    price: float = 0
    amount: float = 0


class ReceiptOut(BaseModel):
    id: Optional[int] = None
    receipt_no: str = ""
    date: str = ""
    total_amount: float = 0
    status: str = "pending"
    image_path: Optional[str] = None
    operator: str = "本地用户"
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    items: List[ReceiptItemOut] = []


class ReceiptSummary(BaseModel):
    """历史列表摘要（不含完整 items）"""
    id: int
    receipt_no: str
    date: str
    total_amount: float
    status: str
    operator: str
    image_path: Optional[str] = None
    summary: str = ""  # 前3条品名拼接
    item_count: int = 0
    created_at: Optional[str] = None


class PaginatedResponse(BaseModel):
    items: List[ReceiptSummary] = []
    total: int = 0
    page: int = 1
    page_size: int = 10


class ApiResponse(BaseModel):
    success: bool = True
    error: Optional[str] = None
    data: Optional[dict] = None
