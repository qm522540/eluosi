"""每日统计数据采集任务

每天凌晨从三平台拉取前一天的完整销售/订单数据，
写入 finance_revenues + finance_costs 表。

调度时间（见 celery_app.py）：
- WB: 00:10
- Ozon: 01:00
- Yandex: 02:00
"""

import asyncio
from datetime import datetime, date, timedelta

from app.tasks.celery_app import celery_app
from app.database import SessionLocal
from app.models.shop import Shop
from app.models.finance import FinanceCost, FinanceRevenue
from app.models.ad import AdStat
from app.models.task_log import TaskLog
from app.services.platform.wb import WBClient
from app.utils.logger import setup_logger

logger = setup_logger("tasks.daily_stats")


def _run_async(coro):
    """在同步Celery任务中执行异步代码"""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _log_task(db, task_name: str, celery_id: str) -> int:
    task_log = TaskLog(
        task_name=task_name,
        celery_task_id=celery_id,
        status="running",
        started_at=datetime.utcnow(),
    )
    db.add(task_log)
    db.commit()
    db.refresh(task_log)
    return task_log.id


def _finish_task(db, log_id: int, status: str, result: dict = None, error: str = None):
    task_log = db.query(TaskLog).filter(TaskLog.id == log_id).first()
    if task_log:
        task_log.status = status
        task_log.result = result
        task_log.error_message = error[:2000] if error else None
        task_log.finished_at = datetime.utcnow()
        if task_log.started_at:
            delta = task_log.finished_at - task_log.started_at
            task_log.duration_ms = int(delta.total_seconds() * 1000)
        db.commit()


# ==================== WB 每日统计 ====================

@celery_app.task(
    name="app.tasks.daily_stats.fetch_wb_daily",
    bind=True,
    max_retries=3,
    default_retry_delay=600,
)
def fetch_wb_daily(self):
    """每天00:10拉取WB前一天的完整统计数据

    采集内容：
    1. 销售订单数据 → finance_revenues
    2. 广告花费汇总 → finance_costs (ad_spend类型)
    """
    db = SessionLocal()
    log_id = None
    yesterday = (date.today() - timedelta(days=1)).isoformat()

    try:
        log_id = _log_task(db, "fetch_wb_daily", self.request.id)

        shops = db.query(Shop).filter(
            Shop.platform == "wb",
            Shop.status == "active",
            Shop.api_key.isnot(None),
        ).all()

        if not shops:
            logger.info("无active的WB店铺，跳过每日统计")
            _finish_task(db, log_id, "success", {"message": "无WB店铺"})
            return {"status": "skip"}

        total_revenue_records = 0
        total_cost_records = 0
        errors = []

        for shop in shops:
            try:
                rev, cost = _run_async(
                    _fetch_wb_daily_for_shop(db, shop, yesterday)
                )
                total_revenue_records += rev
                total_cost_records += cost
            except Exception as e:
                error_msg = f"shop_id={shop.id}: {str(e)}"
                logger.error(f"WB每日统计失败 {error_msg}")
                errors.append(error_msg)
                db.rollback()

        result = {
            "date": yesterday,
            "shops": len(shops),
            "revenue_records": total_revenue_records,
            "cost_records": total_cost_records,
            "errors": errors,
        }
        _finish_task(db, log_id, "success" if not errors else "failed", result)

        logger.info(f"WB每日统计完成: {yesterday}, {result}")
        return result

    except Exception as e:
        logger.error(f"WB每日统计任务异常: {e}")
        if log_id:
            _finish_task(db, log_id, "failed", error=str(e))
        db.rollback()
        raise self.retry(exc=e)
    finally:
        db.close()


async def _fetch_wb_daily_for_shop(db, shop: Shop, date_str: str) -> tuple:
    """采集单个WB店铺的每日统计，返回 (revenue_count, cost_count)"""
    client = WBClient(shop_id=shop.id, api_key=shop.api_key)
    revenue_count = 0
    cost_count = 0

    try:
        # 1. 拉取订单数据，汇总为当日营收
        orders = await client.fetch_orders(date_str, date_str)

        # 过滤出目标日期的订单
        day_orders = [
            o for o in orders
            if o.get("date", "")[:10] == date_str
        ]

        if day_orders:
            total_revenue = sum(
                float(o.get("totalPrice", 0)) * (1 - float(o.get("discountPercent", 0)) / 100)
                for o in day_orders
            )
            returns = [o for o in day_orders if o.get("isCancel", False)]
            returns_amount = sum(
                float(o.get("totalPrice", 0))
                for o in returns
            )

            # 检查是否已有记录
            existing = db.query(FinanceRevenue).filter(
                FinanceRevenue.shop_id == shop.id,
                FinanceRevenue.tenant_id == shop.tenant_id,
                FinanceRevenue.revenue_date == date.fromisoformat(date_str),
            ).first()

            if not existing:
                revenue_record = FinanceRevenue(
                    tenant_id=shop.tenant_id,
                    shop_id=shop.id,
                    revenue_date=date.fromisoformat(date_str),
                    orders_count=len(day_orders) - len(returns),
                    revenue=round(total_revenue, 2),
                    returns_count=len(returns),
                    returns_amount=round(returns_amount, 2),
                    net_revenue=round(total_revenue - returns_amount, 2),
                )
                db.add(revenue_record)
                revenue_count = 1
            else:
                # 更新已有记录
                existing.orders_count = len(day_orders) - len(returns)
                existing.revenue = round(total_revenue, 2)
                existing.returns_count = len(returns)
                existing.returns_amount = round(returns_amount, 2)
                existing.net_revenue = round(total_revenue - returns_amount, 2)

        # 2. 汇总当日广告花费 → finance_costs
        ad_spend = db.query(AdStat).filter(
            AdStat.tenant_id == shop.tenant_id,
            AdStat.platform == "wb",
            AdStat.stat_date == date.fromisoformat(date_str),
        ).all()

        total_ad_spend = sum(float(s.spend) for s in ad_spend)

        if total_ad_spend > 0:
            existing_cost = db.query(FinanceCost).filter(
                FinanceCost.shop_id == shop.id,
                FinanceCost.tenant_id == shop.tenant_id,
                FinanceCost.cost_date == date.fromisoformat(date_str),
                FinanceCost.cost_type == "ad_spend",
            ).first()

            if not existing_cost:
                cost_record = FinanceCost(
                    tenant_id=shop.tenant_id,
                    shop_id=shop.id,
                    cost_date=date.fromisoformat(date_str),
                    cost_type="ad_spend",
                    amount=round(total_ad_spend, 2),
                    currency="RUB",
                    notes=f"WB广告花费自动汇总({len(ad_spend)}条记录)",
                )
                db.add(cost_record)
                cost_count = 1
            else:
                existing_cost.amount = round(total_ad_spend, 2)

        db.commit()
        logger.info(
            f"WB shop_id={shop.id} {date_str}: "
            f"营收{revenue_count}条, 费用{cost_count}条"
        )
        return revenue_count, cost_count

    finally:
        await client.close()


# ==================== Ozon 每日统计（骨架） ====================

@celery_app.task(
    name="app.tasks.daily_stats.fetch_ozon_daily",
    bind=True,
    max_retries=3,
    default_retry_delay=600,
)
def fetch_ozon_daily(self):
    """每天01:00拉取Ozon前一天统计 — 待Ozon客户端实现后补全"""
    db = SessionLocal()
    log_id = None
    try:
        log_id = _log_task(db, "fetch_ozon_daily", self.request.id)
        logger.info("Ozon每日统计任务触发（平台客户端待实现）")
        _finish_task(db, log_id, "success", {"message": "Ozon客户端待实现"})
        return {"status": "skip", "reason": "ozon_client_not_implemented"}
    except Exception as e:
        logger.error(f"Ozon每日统计异常: {e}")
        if log_id:
            _finish_task(db, log_id, "failed", error=str(e))
        raise self.retry(exc=e)
    finally:
        db.close()


# ==================== Yandex 每日统计（骨架） ====================

@celery_app.task(
    name="app.tasks.daily_stats.fetch_yandex_daily",
    bind=True,
    max_retries=3,
    default_retry_delay=600,
)
def fetch_yandex_daily(self):
    """每天02:00拉取Yandex前一天统计 — 待Yandex客户端实现后补全"""
    db = SessionLocal()
    log_id = None
    try:
        log_id = _log_task(db, "fetch_yandex_daily", self.request.id)
        logger.info("Yandex每日统计任务触发（平台客户端待实现）")
        _finish_task(db, log_id, "success", {"message": "Yandex客户端待实现"})
        return {"status": "skip", "reason": "yandex_client_not_implemented"}
    except Exception as e:
        logger.error(f"Yandex每日统计异常: {e}")
        if log_id:
            _finish_task(db, log_id, "failed", error=str(e))
        raise self.retry(exc=e)
    finally:
        db.close()
