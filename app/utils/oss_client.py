"""阿里云 OSS 客户端封装

用途：商品图片归档（下载平台图 → 上传 OSS）、铺货时复用图片、
CDN 加速分发。
"""

import io
import hashlib
from typing import Optional
from urllib.parse import urlparse

import httpx
import oss2

from app.config import get_settings
from app.utils.logger import setup_logger

logger = setup_logger("utils.oss")


class OSSNotConfiguredError(Exception):
    """OSS 未配置时抛出"""


def _get_bucket():
    settings = get_settings()
    if not all([
        settings.OSS_ENDPOINT, settings.OSS_ACCESS_KEY_ID,
        settings.OSS_ACCESS_KEY_SECRET, settings.OSS_BUCKET,
    ]):
        raise OSSNotConfiguredError(
            "OSS 凭证未配置，请在 .env 设置 OSS_ENDPOINT / OSS_ACCESS_KEY_ID / "
            "OSS_ACCESS_KEY_SECRET / OSS_BUCKET"
        )
    auth = oss2.Auth(settings.OSS_ACCESS_KEY_ID, settings.OSS_ACCESS_KEY_SECRET)
    return oss2.Bucket(auth, f"https://{settings.OSS_ENDPOINT}", settings.OSS_BUCKET)


def is_configured() -> bool:
    """检查 OSS 是否已配置（不抛异常，用于前端可用性检测）"""
    settings = get_settings()
    return all([
        settings.OSS_ENDPOINT, settings.OSS_ACCESS_KEY_ID,
        settings.OSS_ACCESS_KEY_SECRET, settings.OSS_BUCKET,
    ])


def _build_public_url(object_key: str) -> str:
    """拼 OSS 公网访问 URL（优先走 CDN，否则用 OSS 默认域名）"""
    settings = get_settings()
    if settings.OSS_CDN_DOMAIN:
        base = settings.OSS_CDN_DOMAIN.rstrip("/")
        if not base.startswith("http"):
            base = f"https://{base}"
        return f"{base}/{object_key}"
    return f"https://{settings.OSS_BUCKET}.{settings.OSS_ENDPOINT}/{object_key}"


def _infer_ext(url: str, content_type: Optional[str] = None) -> str:
    """从 URL 或 Content-Type 推断扩展名（不带点）"""
    path = urlparse(url).path.lower()
    for ext in ("webp", "jpeg", "jpg", "png", "gif", "bmp"):
        if path.endswith(f".{ext}"):
            return "jpg" if ext == "jpeg" else ext
    if content_type:
        ct = content_type.lower()
        if "webp" in ct: return "webp"
        if "png" in ct: return "png"
        if "gif" in ct: return "gif"
        if "jpeg" in ct or "jpg" in ct: return "jpg"
    return "jpg"  # 兜底


async def download_and_upload_image(
    source_url: str, object_key_prefix: str, index: int = 0,
    timeout: float = 30.0,
) -> Optional[str]:
    """下载平台图片 → 上传 OSS → 返回公网 URL

    Args:
        source_url: 平台图片原始 URL
        object_key_prefix: OSS 对象路径前缀，如 'products/4/1/963342619'
        index: 图片序号（同商品多图区分）
        timeout: HTTP 下载超时

    Returns:
        成功：OSS 公网 URL
        失败：None（错误已 log，不抛）
    """
    if not source_url:
        return None
    try:
        bucket = _get_bucket()
    except OSSNotConfiguredError as e:
        logger.warning(f"OSS 未配置，跳过图片下载: {e}")
        return None

    try:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            resp = await client.get(source_url)
            resp.raise_for_status()
            content = resp.content
            content_type = resp.headers.get("Content-Type", "")
    except Exception as e:
        logger.error(f"下载图片失败 url={source_url}: {e}")
        return None

    if not content:
        return None

    # 用内容 hash + 序号 做文件名（去重、可复跑）
    ext = _infer_ext(source_url, content_type)
    digest = hashlib.md5(content).hexdigest()[:10]
    object_key = f"{object_key_prefix.strip('/')}/{index:02d}-{digest}.{ext}"

    try:
        # 幂等：已存在就不重复传
        if bucket.object_exists(object_key):
            logger.info(f"OSS 对象已存在，跳过上传: {object_key}")
            return _build_public_url(object_key)
        bucket.put_object(
            object_key, io.BytesIO(content),
            headers={"Content-Type": content_type or f"image/{ext}"},
        )
        logger.info(f"图片已上传 OSS: {object_key} ({len(content)} bytes)")
        return _build_public_url(object_key)
    except Exception as e:
        logger.error(f"上传 OSS 失败 key={object_key}: {e}")
        return None


async def download_images_batch(
    source_urls: list, object_key_prefix: str,
) -> list:
    """批量下载图片（串行，避免平台限速）

    Returns: OSS URL 列表（失败的跳过）
    """
    results = []
    for i, url in enumerate(source_urls or []):
        if not url:
            continue
        oss_url = await download_and_upload_image(url, object_key_prefix, index=i)
        if oss_url:
            results.append(oss_url)
    return results
