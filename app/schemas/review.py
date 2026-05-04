"""评价管理模块 Pydantic 请求/响应模型"""

from typing import Optional
from pydantic import BaseModel, Field


# ==================== 同步 / 列表 ====================

class ReviewSyncRequest(BaseModel):
    only_unanswered: bool = Field(True, description="只拉未回评价 (默认 True, 增量同步)")
    max_pages: int = Field(10, ge=1, le=50, description="最大分页数, 防超量")


# ==================== 翻译 (用户编辑俄语后实时刷新中文) ====================

class TranslateRequest(BaseModel):
    text_ru: str = Field(..., max_length=2000, description="待翻译俄语原文")


# ==================== 生成回复 ====================

class GenerateReplyRequest(BaseModel):
    custom_hint: Optional[str] = Field(
        "", max_length=500,
        description="自定义重点 (例如 '提一下 30 天无理由退换'); 重新生成必填"
    )


# ==================== 发送回复 ====================

class SendReplyRequest(BaseModel):
    reply_id: int = Field(..., description="shop_review_replies.id")
    final_content_ru: Optional[str] = Field(
        None, max_length=2000,
        description="用户编辑后的最终俄语 (None=用 draft 原版)"
    )


# ==================== 店铺级设置 ====================

class ReviewSettingsUpdate(BaseModel):
    auto_reply_enabled: Optional[bool] = Field(
        None,
        description="自动回复开关 (用户拍: 4-5 星才自动, 1-3 星仍人工)"
    )
    auto_reply_rating_floor: Optional[int] = Field(
        None, ge=1, le=5,
        description="自动回复评分下限 (默认 4 即 4-5 星)"
    )
    reply_tone: Optional[str] = Field(
        None, pattern="^(formal|friendly|warm)$",
        description="回复语气 — 默认 friendly (友好+温暖)"
    )
    brand_signature: Optional[str] = Field(
        None, max_length=200,
        description="结尾签名 (С любовью, Sharino 等)"
    )
    custom_prompt_extra: Optional[str] = Field(
        None, max_length=1000,
        description="自定义 prompt 补充 (品牌特殊调性)"
    )
