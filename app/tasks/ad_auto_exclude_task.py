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

from app.utils.moscow_time import moscow_today, utc_now_naive

from sqlalchemy import text

from app.tasks.celery_app import celery_app
from app.database import SessionLocal
from app.models.shop import Shop
from app.models.ad import (
    AdCampaign, AdCampaignAutoExclude, AdAutoExcludeLog, AdKeywordProtected,
)
from app.services.data_source.service import is_data_source_enabled, record_sync_run
from app.services.keyword_stats.rules import get_rules, classify
from app.utils.logger import setup_logger

logger = setup_logger("tasks.auto_exclude")


def _run_async(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _tokenize(s: str) -> set:
    """极简 tokenizer：小写 + 按空格/-/标点切 + 去短词"""
    import re
    tokens = re.split(r"[\s\-_,.;:/\\()\[\]]+", (s or "").lower())
    return {t for t in tokens if len(t) >= 3}


def _kw_sku_affinity(keyword: str, title: str) -> float:
    """关键词与 SKU 标题的亲和度 0~1

    用"关键词 token 在 SKU 标题里能前缀匹配到的比例"做代理。
    俄语形态丰富（серьги/сережки/сердечки），前缀匹配比精确 token 相等更稳。
    """
    kw_tokens = _tokenize(keyword)
    if not kw_tokens:
        return 0.0
    title_lower = (title or "").lower()
    hit = 0
    for t in kw_tokens:
        # 前 4 字符作为词根（俄语词尾变化多，前 4 字基本稳定）
        stem = t[:4] if len(t) > 4 else t
        if stem in title_lower:
            hit += 1
    return hit / len(kw_tokens)


async def _fetch_per_sku_snapshot(client, advert_id: str, date_from: str, date_to: str):
    """从 WB fullstats 拿每个 SKU 的 views / title（按活动内聚合）

    Returns:
        {
            nm_id: {"views": int, "clicks": int, "title": str, "share": float}
        }
    """
    from app.services.platform.wb import WB_ADVERT_API
    url = f"{WB_ADVERT_API}/adv/v3/fullstats"
    try:
        # 用 WBClient._request 走统一限速
        data = await client._request(
            "GET", url,
            params={"ids": str(advert_id), "beginDate": date_from, "endDate": date_to},
        )
    except Exception:
        return {}
    if not data:
        return {}
    camp = data[0] if isinstance(data, list) and data else data
    if not isinstance(camp, dict):
        return {}
    # 遍历 days[].apps[].nms[] 累加
    per_sku = {}
    for day in camp.get("days") or []:
        for app in day.get("apps") or []:
            for nm in app.get("nms") or []:
                nm_id = int(nm.get("nmId") or 0)
                if not nm_id:
                    continue
                if nm_id not in per_sku:
                    per_sku[nm_id] = {
                        "views": 0, "clicks": 0,
                        "title": nm.get("name") or "",
                    }
                per_sku[nm_id]["views"] += int(nm.get("views") or 0)
                per_sku[nm_id]["clicks"] += int(nm.get("clicks") or 0)
    total_views = sum(v["views"] for v in per_sku.values()) or 1
    for nm_id, v in per_sku.items():
        v["share"] = v["views"] / total_views
    return per_sku


async def _exclude_one_campaign(db, shop, camp, run_id):
    """对单个活动跑自动屏蔽

    Returns:
        (excluded_count, total_saved_per_day, error_msg)
    """
    from app.services.platform.wb import WBClient

    rules = get_rules(db, shop.tenant_id)
    waste_min_days = rules.get("waste_min_days", 5)
    # per-SKU 亲和度门控（0.5 = 关键词至少一半 token 能在 SKU 标题里前缀命中）
    min_affinity = float(rules.get("per_sku_min_affinity", 0.5))
    # SKU 在活动里展示占比最低阈值（低于此不进屏蔽列表，避免低流量 SKU 被瞎堆）
    min_share = float(rules.get("per_sku_min_share", 0.03))

    client = WBClient(shop_id=shop.id, api_key=shop.api_key)
    excluded_count = 0
    total_saved = 0.0

    try:
        today = moscow_today()
        date_to = today.strftime("%Y-%m-%d")
        date_from = (today - timedelta(days=6)).strftime("%Y-%m-%d")

        # 1. 拉关键词 + 活动商品（nm_id 列表） + per-SKU 快照
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

        # per-SKU 曝光占比 + 标题（用于亲和度判定）
        per_sku = await _fetch_per_sku_snapshot(
            client, camp.platform_campaign_id, date_from, date_to,
        )

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

        # 5. 按 nm_id 应用屏蔽（加 per-SKU 门控：亲和度 + 占比）
        for nm_id in nm_ids:
            existing = set(excluded_map.get(int(nm_id), []))
            existing_lower = {w.lower().strip() for w in existing}
            protected_lower = protected_by_nm.get(int(nm_id), set())

            # 低占比 SKU 跳过 —— 活动里几乎不展示它，没必要给它加屏蔽词
            sku_info = per_sku.get(int(nm_id), {})
            sku_share = sku_info.get("share", 0)
            sku_title = sku_info.get("title", "")
            if per_sku and sku_share < min_share:
                logger.info(
                    f"auto-exclude 跳过低占比 SKU: camp={camp.id} nm={nm_id} "
                    f"share={sku_share:.1%} < {min_share:.1%}"
                )
                continue

            new_kws_meta = []
            for wk in waste_kws:
                kw_lower = wk["keyword"].lower().strip()
                if kw_lower in existing_lower:
                    continue
                if kw_lower in protected_lower:
                    continue
                # 亲和度门控：关键词与 SKU 标题文本无明显重叠则跳过
                # （WB 拍卖引擎基于商品属性/标题匹配搜索词，无重叠的词几乎不会触发该 SKU）
                if sku_title:
                    affinity = _kw_sku_affinity(wk["keyword"], sku_title)
                    if affinity < min_affinity:
                        continue
                    wk = {**wk, "_affinity": affinity, "_sku_share": sku_share}
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

            # 写后失效：屏蔽词列表已变化，前端 /campaign-keywords 缓存失效
            try:
                from app.api.v1.ads import _invalidate_excluded
                _invalidate_excluded(camp.platform_campaign_id, int(nm_id))
            except Exception:
                pass

            # 剔除 WB 拒绝的无效词，不计入"已屏蔽"账本，避免污染节省统计
            dropped_lower = {w.lower().strip() for w in (result.get("dropped_invalid") or [])}
            new_kws_meta = [
                wk for wk in new_kws_meta
                if wk["keyword"].lower().strip() not in dropped_lower
            ]
            if not new_kws_meta:
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

                reason_parts = [
                    f"CTR {wk['ctr']:.2f}≤{rules.get('waste_ctr_max', 1.0):.1f}",
                    f"花费 ¥{wk['spend']:.0f}",
                ]
                aff = wk.get("_affinity")
                if aff is not None:
                    reason_parts.append(f"亲和度 {aff:.0%}")
                share = wk.get("_sku_share")
                if share is not None:
                    reason_parts.append(f"SKU占比 {share:.0%}")
                db.add(AdAutoExcludeLog(
                    tenant_id=shop.tenant_id, shop_id=shop.id,
                    campaign_id=camp.id, nm_id=int(nm_id),
                    keyword=kw_text, run_id=run_id,
                    saved_per_day=float(avg_daily),
                    reason=" · ".join(reason_parts),
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
        # 数据源开关 hook 缓存 (一个 shop 多个 campaign 共享一次检查)
        shop_gate = {}
        for cfg in configs:
            shop = db.query(Shop).filter(
                Shop.id == cfg.shop_id, Shop.tenant_id == cfg.tenant_id,
            ).first()
            camp = db.query(AdCampaign).filter(
                AdCampaign.id == cfg.campaign_id, AdCampaign.tenant_id == cfg.tenant_id,
            ).first()
            if not shop or not camp or shop.platform != "wb":
                continue
            # Per-shop hook gate
            if shop.id not in shop_gate:
                enabled, skip_reason = is_data_source_enabled(
                    db, shop.tenant_id, shop.id, "wb_ad_auto_exclude",
                )
                shop_gate[shop.id] = (enabled, skip_reason)
                if not enabled:
                    record_sync_run(db, shop.tenant_id, shop.id, "wb_ad_auto_exclude",
                                   status="skipped", msg=skip_reason or "")
            enabled, skip_reason = shop_gate[shop.id]
            if not enabled:
                logger.info(f"shop={shop.id} wb_ad_auto_exclude 跳过: {skip_reason}")
                results.append({"campaign_id": cfg.campaign_id, "skipped": skip_reason})
                continue

            run_id = uuid.uuid4().hex[:16]
            t0 = utc_now_naive()
            try:
                excluded, saved, err = _run_async(
                    _exclude_one_campaign(db, shop, camp, run_id)
                )
                cfg.last_run_at = utc_now_naive()
                cfg.last_run_excluded = excluded
                cfg.last_run_saved = round(saved * 30, 2)  # 月省 = 日省 ×30
                db.commit()
                dur_ms = int((utc_now_naive() - t0).total_seconds() * 1000)
                rec_status = "failed" if err else "success"
                record_sync_run(db, shop.tenant_id, shop.id, "wb_ad_auto_exclude",
                               status=rec_status, rows=excluded, duration_ms=dur_ms,
                               msg=str(err)[:500] if err else f"saved/day={saved:.2f}")
                results.append({
                    "campaign_id": cfg.campaign_id, "excluded": excluded,
                    "saved_per_day": saved, "error": err,
                })
                logger.info(
                    f"自动屏蔽 camp={cfg.campaign_id}: 屏蔽 {excluded} 词，"
                    f"日省 ¥{saved:.2f}, 月省估算 ¥{saved*30:.2f}, error={err}"
                )
            except Exception as e:
                dur_ms = int((utc_now_naive() - t0).total_seconds() * 1000)
                record_sync_run(db, shop.tenant_id, shop.id, "wb_ad_auto_exclude",
                               status="failed", msg=str(e)[:500], duration_ms=dur_ms)
                logger.error(f"自动屏蔽 camp={cfg.campaign_id} 异常: {e}")
                results.append({"campaign_id": cfg.campaign_id, "error": str(e)[:200]})
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
        shop = db.query(Shop).filter(
            Shop.id == cfg.shop_id, Shop.tenant_id == tenant_id,
        ).first()
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
        cfg.last_run_at = utc_now_naive()
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
