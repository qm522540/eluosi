"""日报生成任务

每天08:00生成前一天的运营日报，
汇总各平台的广告数据、销售数据、ROI指标，
并推送到企业微信。

日报内容：
1. 各平台广告花费/展示/点击/订单汇总
2. 整体销售额/退货/净收入
3. ROI/ROAS指标
4. 异常告警汇总
"""

from datetime import date, timedelta

from app.utils.moscow_time import moscow_today, utc_now_naive
from decimal import Decimal

from sqlalchemy import func

from app.tasks.celery_app import celery_app
from app.database import SessionLocal
from app.models.shop import Shop
from app.models.ad import AdStat
from app.models.finance import FinanceCost, FinanceRevenue, FinanceRoiSnapshot
from app.models.notification import Notification
from app.models.task_log import TaskLog
from app.utils.logger import setup_logger

logger = setup_logger("tasks.report")


@celery_app.task(
    name="app.tasks.report_tasks.generate_daily_report",
    bind=True,
    max_retries=2,
    default_retry_delay=300,
)
def generate_daily_report(self):
    """生成昨日运营日报并保存ROI快照"""
    db = SessionLocal()
    log_id = None
    yesterday = moscow_today() - timedelta(days=1)

    try:
        # 保存 Python 内存变量供 duration 计算用：MySQL DATETIME(0) round 到秒，
        # refresh 后 task_log.started_at 会损失毫秒，导致 finished - started 出现负数
        started_at_local = utc_now_naive()
        task_log = TaskLog(
            task_name="generate_daily_report",
            celery_task_id=self.request.id,
            status="running",
            started_at=started_at_local,
        )
        db.add(task_log)
        db.commit()
        db.refresh(task_log)
        log_id = task_log.id

        # 获取所有active店铺（按租户分组）
        shops = db.query(Shop).filter(Shop.status == "active").all()
        tenant_shops = {}
        for shop in shops:
            tenant_shops.setdefault(shop.tenant_id, []).append(shop)

        reports_generated = 0

        for tenant_id, t_shops in tenant_shops.items():
            try:
                report = _build_tenant_report(db, tenant_id, t_shops, yesterday)
                if report:
                    # 保存ROI快照
                    _save_roi_snapshots(db, tenant_id, t_shops, yesterday, report)

                    # 生成通知
                    notification = Notification(
                        tenant_id=tenant_id,
                        notification_type="daily_report",
                        title=f"运营日报 {yesterday.isoformat()}",
                        content=_format_report_text(report, yesterday),
                        channel="both",
                        sent_at=utc_now_naive(),
                    )
                    db.add(notification)
                    reports_generated += 1

                db.commit()

            except Exception as e:
                logger.error(f"租户 {tenant_id} 日报生成失败: {e}")
                db.rollback()

        result = {
            "date": yesterday.isoformat(),
            "tenants": len(tenant_shops),
            "reports_generated": reports_generated,
        }

        task_log.status = "success"
        task_log.result = result
        task_log.finished_at = utc_now_naive()
        # 用 Python 局部 started_at_local 算 duration（不走 DB round 损失精度）
        task_log.duration_ms = max(0, int(
            (task_log.finished_at - started_at_local).total_seconds() * 1000
        ))
        db.commit()

        logger.info(f"日报生成完成: {result}")
        return result

    except Exception as e:
        logger.error(f"日报生成任务失败: {e}")
        if log_id:
            tl = db.query(TaskLog).filter(TaskLog.id == log_id).first()
            if tl:
                tl.status = "failed"
                tl.error_message = str(e)[:2000]
                tl.finished_at = utc_now_naive()
                db.commit()
        db.rollback()
        raise self.retry(exc=e)

    finally:
        db.close()


def _build_tenant_report(db, tenant_id: int, shops: list, report_date: date) -> dict:
    """构建某租户的日报数据"""
    shop_ids = [s.id for s in shops]

    # 1. 广告数据汇总
    ad_summary = db.query(
        func.sum(AdStat.impressions).label("impressions"),
        func.sum(AdStat.clicks).label("clicks"),
        func.sum(AdStat.spend).label("spend"),
        func.sum(AdStat.orders).label("orders"),
        func.sum(AdStat.revenue).label("revenue"),
    ).filter(
        AdStat.tenant_id == tenant_id,
        AdStat.stat_date == report_date,
    ).first()

    # 2. 营收数据
    revenue_summary = db.query(
        func.sum(FinanceRevenue.revenue).label("total_revenue"),
        func.sum(FinanceRevenue.returns_amount).label("returns"),
        func.sum(FinanceRevenue.net_revenue).label("net_revenue"),
        func.sum(FinanceRevenue.orders_count).label("total_orders"),
    ).filter(
        FinanceRevenue.tenant_id == tenant_id,
        FinanceRevenue.revenue_date == report_date,
    ).first()

    # 3. 费用数据
    cost_summary = db.query(
        func.sum(FinanceCost.amount).label("total_cost"),
    ).filter(
        FinanceCost.tenant_id == tenant_id,
        FinanceCost.cost_date == report_date,
    ).first()

    ad_spend = float(ad_summary.spend or 0)
    ad_revenue = float(ad_summary.revenue or 0)
    total_revenue = float(revenue_summary.total_revenue or 0) if revenue_summary else 0
    total_cost = float(cost_summary.total_cost or 0) if cost_summary else 0

    report = {
        "ad": {
            "impressions": int(ad_summary.impressions or 0),
            "clicks": int(ad_summary.clicks or 0),
            "spend": round(ad_spend, 2),
            "orders": int(ad_summary.orders or 0),
            "revenue": round(ad_revenue, 2),
            "ctr": round(
                (int(ad_summary.clicks or 0) / int(ad_summary.impressions or 1)) * 100, 2
            ),
            "acos": round((ad_spend / ad_revenue * 100) if ad_revenue > 0 else 0, 2),
            "roas": round((ad_revenue / ad_spend) if ad_spend > 0 else 0, 2),
        },
        "revenue": {
            "total": round(total_revenue, 2),
            "returns": round(
                float(revenue_summary.returns or 0) if revenue_summary else 0, 2
            ),
            "net": round(
                float(revenue_summary.net_revenue or 0) if revenue_summary else 0, 2
            ),
            "orders": int(revenue_summary.total_orders or 0) if revenue_summary else 0,
        },
        "cost": {
            "total": round(total_cost, 2),
        },
        "profit": {
            "gross": round(total_revenue - total_cost, 2),
            "roi": round(
                ((total_revenue - total_cost) / total_cost * 100) if total_cost > 0 else 0, 2
            ),
        },
    }

    return report


def _save_roi_snapshots(
    db, tenant_id: int, shops: list, snapshot_date: date, report: dict
):
    """保存ROI日快照到 finance_roi_snapshots"""
    for shop in shops:
        existing = db.query(FinanceRoiSnapshot).filter(
            FinanceRoiSnapshot.tenant_id == tenant_id,
            FinanceRoiSnapshot.shop_id == shop.id,
            FinanceRoiSnapshot.snapshot_date == snapshot_date,
            FinanceRoiSnapshot.period == "daily",
        ).first()

        if not existing:
            snapshot = FinanceRoiSnapshot(
                tenant_id=tenant_id,
                shop_id=shop.id,
                snapshot_date=snapshot_date,
                period="daily",
                total_revenue=report["revenue"]["total"],
                total_cost=report["cost"]["total"],
                ad_spend=report["ad"]["spend"],
                gross_profit=report["profit"]["gross"],
                roi=report["profit"]["roi"],
                roas=report["ad"]["roas"],
            )
            db.add(snapshot)


def _format_report_text(report: dict, report_date: date) -> str:
    """格式化日报为文本（用于通知推送）"""
    ad = report["ad"]
    rev = report["revenue"]
    profit = report["profit"]

    text = f"""📊 运营日报 {report_date.isoformat()}

【广告数据】
  展示: {ad['impressions']:,}  点击: {ad['clicks']:,}  CTR: {ad['ctr']}%
  花费: {ad['spend']:,.2f} RUB
  广告订单: {ad['orders']}  广告收入: {ad['revenue']:,.2f} RUB
  ACOS: {ad['acos']}%  ROAS: {ad['roas']}

【销售数据】
  总营收: {rev['total']:,.2f} RUB
  退货: {rev['returns']:,.2f} RUB
  净收入: {rev['net']:,.2f} RUB
  订单数: {rev['orders']}

【利润指标】
  毛利: {profit['gross']:,.2f} RUB
  ROI: {profit['roi']}%
"""
    return text
