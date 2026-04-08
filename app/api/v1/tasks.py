"""数据采集任务手动触发接口"""

from fastapi import APIRouter, Depends
from app.dependencies import get_current_user, get_tenant_id
from app.utils.response import success, error

router = APIRouter()


@router.post("/sync-ads")
def trigger_sync_ads(
    current_user=Depends(get_current_user),
):
    """手动触发三平台广告数据同步"""
    from app.tasks.ad_tasks import fetch_wb_ad_stats, fetch_ozon_ad_stats, fetch_yandex_ad_stats

    wb_task = fetch_wb_ad_stats.delay()
    ozon_task = fetch_ozon_ad_stats.delay()
    yandex_task = fetch_yandex_ad_stats.delay()

    return success({
        "message": "广告同步任务已提交",
        "tasks": {
            "wb": wb_task.id,
            "ozon": ozon_task.id,
            "yandex": yandex_task.id,
        },
    })


@router.post("/sync-ads/{platform}")
def trigger_sync_ads_by_platform(
    platform: str,
    current_user=Depends(get_current_user),
):
    """手动触发指定平台广告数据同步"""
    from app.tasks.ad_tasks import fetch_wb_ad_stats, fetch_ozon_ad_stats, fetch_yandex_ad_stats

    task_map = {
        "wb": fetch_wb_ad_stats,
        "ozon": fetch_ozon_ad_stats,
        "yandex": fetch_yandex_ad_stats,
    }

    task_func = task_map.get(platform)
    if not task_func:
        return error(40000, f"不支持的平台: {platform}，可选: wb/ozon/yandex")

    task = task_func.delay()
    return success({
        "message": f"{platform}广告同步任务已提交",
        "task_id": task.id,
    })
