"""活动级自动屏蔽托管任务

每日凌晨 04:30 莫斯科时间运行：
- 遍历所有 enabled=1 的活动
- 用租户 efficiency_rules 跑 waste 判定
- 把 waste 词加到 WB minus（按 nm_id），跳过白名单 + 已屏蔽
- 写日志：每个被屏蔽词一条，含节省金额估算（前 7 天日均花费）
- 更新活动级 last_run_at / last_run_excluded / last_run_saved 快照
"""

import asyncio
import uuid
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import text

from app.tasks.celery_app import celery_app
from app.database import SessionLocal
from app.models.shop import Shop
from app.models.ad import (
    AdCampaign, AdCampaignAutoExclude, AdAutoExcludeLog, AdKeywordProtected,
)
from app.services.keyword_stats.rules import get_rules, classify
from app.utils.logger import setup_logger

logger = setup_logger("tasks.auto_exclude")


def _run_async(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


async def _exclude_one_campaign(db, shop, camp, run_id):
    """对单个活动跑自动屏蔽

    Returns:
        (excluded_count, total_saved_per_day, error_msg)
    """
    from app.services.platform.wb import WBClient

    rules = get_rules(db, shop.tenant_id)
    waste_min_days = rules.get("waste_min_days", 5)

    client = WBClient(shop_id=shop.id, api_key=shop.api_key)
    excluded_count = 0
    total_saved = 0.0

    try:
        today = date.today()
        date_to = today.strftime("%Y-%m-%d")
        date_from = (today - timedelta(days=6)).strftime("%Y-%m-%d")

        # 1. 拉关键词 + 活动商品（nm_id 列表）
        kws = await client.fetch_campaign_keywords(
            advert_id=camp.platform_campaign_id,
            date_from=date_from, date_to=date_to,
        )
        try:
            prods = await client.fetch_campaign_products(camp.platform_campaign_id)
            nm_ids = [int(p.get("sku", 0)) for p in prods if p.get("sku")]
        except Exception:
            nm_ids = []

        if not nm_ids or not kws:
            return 0, 0.0, "无关键词或活动商品"

        # 2. 全局平均（参与 classify）
        total_clicks = sum(int(k.get("clicks", 0)) for k in kws)
        total_imp = sum(int(k.get("views", 0)) for k in kws)
        total_spend = sum(float(k.get("sum", 0)) for k in kws)
        n = max(len(kws), 1)
        avg_imp = total_imp / n
        avg_spend = total_spend / n
        avg_cpc = total_spend / total_clicks if total_clicks > 0 else 0

        # 3. waste 判定（带 active_days 门槛）
        waste_kws = []
        for kw in kws:
            ctr = float(kw.get("ctr", 0))
            clicks = int(kw.get("clicks", 0))
            sp = float(kw.get("sum", 0))
            imp = int(kw.get("views", 0))
            cpc_val = sp / clicks if clicks > 0 else 0
            active_days = int(kw.get("active_days", 0))

            if active_days < waste_min_days:
                continue
            eff = classify(
                ctr=ctr, cpc=cpc_val, impressions=imp, spend=sp,
                avg_cpc=avg_cpc, avg_impressions=avg_imp, avg_spend=avg_spend,
                rules=rules,
            )
            if eff != "waste":
                continue
            waste_kws.append({
                "keyword": kw["keyword"], "ctr": ctr,
                "spend": sp, "active_days": active_days,
            })

        if not waste_kws:
            return 0, 0.0, None

        # 4. 拉每 nm_id 现有屏蔽 + 白名单
        excluded_map = await client.fetch_excluded_keywords(
            advert_id=camp.platform_campaign_id, nm_ids=nm_ids,
        )
        protected_rows = db.query(AdKeywordProtected).filter(
            AdKeywordProtected.tenant_id == shop.tenant_id,
            AdKeywordProtected.campaign_id == camp.id,
            AdKeywordProtected.nm_id.in_(nm_ids),
        ).all()
        protected_by_nm = {}
        for r in protected_rows:
            protected_by_nm.setdefault(r.nm_id, set()).add(r.keyword.lower().strip())

        # 5. 按 nm_id 应用屏蔽
        for nm_id in nm_ids:
            existing = set(excluded_map.get(int(nm_id), []))
            existing_lower = {w.lower().strip() for w in existing}
            protected_lower = protected_by_nm.get(int(nm_id), set())

            new_kws_meta = []
            for wk in waste_kws:
                kw_lower = wk["keyword"].lower().strip()
                if kw_lower in existing_lower:
                    continue
                if kw_lower in protected_lower:
                    continue
                new_kws_meta.append(wk)

            if not new_kws_meta:
                continue

            merged = list(existing | {wk["keyword"] for wk in new_kws_meta})
            result = await client.set_excluded_keywords(
                advert_id=camp.platform_campaign_id,
                nm_id=int(nm_id), words=merged,
            )
            if not result.get("ok"):
                logger.warning(
                    f"自动屏蔽写入失败 advert={camp.platform_campaign_id} "
                    f"nm={nm_id}: {result.get('error')}"
                )
                continue

            since = (today - timedelta(days=6)).isoformat()
            for wk in new_kws_meta:
                kw_text = wk["keyword"]
                # 节省估算：keyword_daily_stats 该词最近 7 天日均花费
                avg_daily = db.execute(text("""
                    SELECT AVG(spend) FROM keyword_daily_stats
                    WHERE tenant_id=:tid AND shop_id=:sid AND campaign_id=:cid
                      AND keyword=:kw AND stat_date >= :since
                """), {
                    "tid": shop.tenant_id, "sid": shop.id, "cid": camp.id,
                    "kw": kw_text, "since": since,
                }).scalar() or 0
                # 兜底：库里无数据时用 wk["spend"]/active_days
                if not avg_daily and wk["active_days"] > 0:
                    avg_daily = wk["spend"] / wk["active_days"]

                db.add(AdAutoExcludeLog(
                    tenant_id=shop.tenant_id, shop_id=shop.id,
                    campaign_id=camp.id, nm_id=int(nm_id),
                    keyword=kw_text, run_id=run_id,
                    saved_per_day=float(avg_daily),
                    reason=(
                        f"CTR {wk['ctr']:.2f}≤{rules.get('waste_ctr_max', 1.0):.1f}"
                        f" 且 花费 ¥{wk['spend']:.0f}"
                    ),
                ))
                excluded_count += 1
                total_saved += float(avg_daily)

        db.commit()
        return excluded_count, total_saved, None
    except Exception as e:
        logger.error(f"自动屏蔽 camp={camp.id} 异常: {e}", exc_info=True)
        db.rollback()
        return 0, 0.0, str(e)[:300]
    finally:
        await client.close()


@celery_app.task(
    name="app.tasks.ad_auto_exclude_task.auto_exclude_keywords",
    bind=True, max_retries=1, default_retry_delay=300,
)
def auto_exclude_keywords(self):
    """每日扫所有开了自动屏蔽的活动 → 跑屏蔽 → 写日志"""
    db = SessionLocal()
    try:
        configs = db.query(AdCampaignAutoExclude).filter(
            AdCampaignAutoExclude.enabled == 1,
        ).all()
        results = []
        for cfg in configs:
            shop = db.query(Shop).filter(Shop.id == cfg.shop_id).first()
            camp = db.query(AdCampaign).filter(AdCampaign.id == cfg.campaign_id).first()
            if not shop or not camp or shop.platform != "wb":
                continue
            run_id = uuid.uuid4().hex[:16]
            excluded, saved, err = _run_async(
                _exclude_one_campaign(db, shop, camp, run_id)
            )
            cfg.last_run_at = datetime.now(timezone.utc)
            cfg.last_run_excluded = excluded
            cfg.last_run_saved = round(saved * 30, 2)  # 月省 = 日省 ×30
            db.commit()
            results.append({
                "campaign_id": cfg.campaign_id, "excluded": excluded,
                "saved_per_day": saved, "error": err,
            })
            logger.info(
                f"自动屏蔽 camp={cfg.campaign_id}: 屏蔽 {excluded} 词，"
                f"日省 ¥{saved:.2f}, 月省估算 ¥{saved*30:.2f}, error={err}"
            )
        return {"campaigns": len(configs), "results": results}
    except Exception as e:
        logger.error(f"自动屏蔽全局任务异常: {e}", exc_info=True)
        db.rollback()
        raise self.retry(exc=e)
    finally:
        db.close()


@celery_app.task(
    name="app.tasks.ad_auto_exclude_task.auto_exclude_for_campaign",
    bind=True,
)
def auto_exclude_for_campaign(self, campaign_id: int, tenant_id: int):
    """单活动手动触发（"立即跑一次"按钮专用）"""
    db = SessionLocal()
    try:
        cfg = db.query(AdCampaignAutoExclude).filter(
            AdCampaignAutoExclude.tenant_id == tenant_id,
            AdCampaignAutoExclude.campaign_id == campaign_id,
        ).first()
        if not cfg:
            return {"error": "自动屏蔽未配置"}
        shop = db.query(Shop).filter(Shop.id == cfg.shop_id).first()
        camp = db.query(AdCampaign).filter(
            AdCampaign.id == campaign_id, AdCampaign.tenant_id == tenant_id,
        ).first()
        if not shop or not camp:
            return {"error": "活动不存在"}
        if shop.platform != "wb":
            return {"error": "仅支持 WB 平台"}
        run_id = uuid.uuid4().hex[:16]
        excluded, saved, err = _run_async(
            _exclude_one_campaign(db, shop, camp, run_id)
        )
        cfg.last_run_at = datetime.now(timezone.utc)
        cfg.last_run_excluded = excluded
        cfg.last_run_saved = round(saved * 30, 2)
        db.commit()
        return {
            "campaign_id": campaign_id, "excluded": excluded,
            "saved_per_day": saved,
            "estimated_saved_per_month": round(saved * 30, 2),
            "error": err,
        }
    finally:
        db.close()
