from fastapi import APIRouter

from app.utils.response import success

router = APIRouter()


@router.get("/health")
async def health_check():
    """健康检查（无需认证）"""
    return success(data={"status": "ok", "service": "ecommerce-ai"})
