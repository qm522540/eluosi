"""AI调价执行器（按老林规范 docs/api/bid_management.md §3 + §4）

数据流：
  ai_pricing_configs.is_active=1 触发执行
  → 读取当前 template_name 指向的 JSON 模板配置
  → 遍历 ad_campaigns(status='active', platform='ozon')
    → 拉商品 + 当前出价
    → 简化版 prompt → DeepSeek → 解析建议
    → 写入 ai_pricing_suggestions
    → 若 auto_execute=1，立即调 Ozon API 执行（跳过 user_managed=1 的 group）

注意：
  - 完全不依赖被删的 app/services/ad/ai_pricing.py 和 app/services/ai/pricing_engine.py
  - 复用 app/services/ai/deepseek.DeepSeekClient（仅是 HTTP 客户端）
  - sync session
  - 出价单位：业务层用卢布，调 Ozon API 时再 ×1_000_000
"""

import json
import re
from datetime import date, datetime
from typing import Optional

from sqlalchemy import text

from app.config import get_settings
from app.utils.errors import ErrorCode
from app.utils.logger import setup_logger
from app.utils.moscow_time import moscow_hour, moscow_today, now_moscow

logger = setup_logger("bid.ai_pricing_executor")
settings = get_settings()

MIN_BID = 3.0
MIN_DIFF = 1.0


# ==================== Config 更新 ====================

def update_config(db, tenant_id: int, shop_id: int, data: dict) -> dict:
    """更新 ai_pricing_configs（PUT /ai-pricing/{shop_id}）"""
    # 确保有行
    existing = db.execute(text("""
        SELECT id FROM ai_pricing_configs WHERE shop_id = :shop_id LIMIT 1
    """), {"shop_id": shop_id}).fetchone()

    template_name = data.get("template_name", "default")
    if template_name not in ("conservative", "default", "aggressive"):
        return {"code": ErrorCode.PARAM_ERROR, "msg": "template_name 必须是 conservative/default/aggressive"}

    auto_execute = 1 if data.get("auto_execute") else 0

    fields = {}
    for key in ("conservative_config", "default_config", "aggressive_config"):
        if key in data and isinstance(data[key], dict):
            err = _validate_template_json(data[key])
            if err:
                return {"code": ErrorCode.PARAM_ERROR, "msg": f"{key}: {err}"}
            fields[key] = json.dumps(data[key])

    if existing:
        sets = ["template_name = :template_name", "auto_execute = :auto_execute", "updated_at = NOW()"]
        params = {"id": existing.id, "template_name": template_name, "auto_execute": auto_execute}
        for k, v in fields.items():
            sets.append(f"{k} = :{k}")
            params[k] = v
        db.execute(text(f"UPDATE ai_pricing_configs SET {', '.join(sets)} WHERE id = :id"), params)
    else:
        # 必须给三个模板都填默认（NOT NULL JSON）
        defaults = {
            "conservative_config": json.dumps(_DEFAULT_CONSERVATIVE),
            "default_config": json.dumps(_DEFAULT_DEFAULT),
            "aggressive_config": json.dumps(_DEFAULT_AGGRESSIVE),
        }
        defaults.update(fields)
        db.execute(text("""
            INSERT INTO ai_pricing_configs (
                tenant_id, shop_id, is_active, auto_execute, template_name,
                conservative_config, default_config, aggressive_config
            ) VALUES (
                :tenant_id, :shop_id, 0, :auto_execute, :template_name,
                :conservative_config, :default_config, :aggressive_config
            )
        """), {
            "tenant_id": tenant_id,
            "shop_id": shop_id,
            "auto_execute": auto_execute,
            "template_name": template_name,
            **defaults,
        })

    db.commit()
    return {"code": 0}


# ==================== 启用 / 停用 ====================

def enable(db, tenant_id: int, shop_id: int, auto_execute: bool = False) -> dict:
    """启用 AI 调价（FOR UPDATE 互斥校验 + 数据初始化校验）"""
    # 校验数据初始化
    init_row = db.execute(text("""
        SELECT is_initialized FROM shop_data_init_status WHERE shop_id = :shop_id
    """), {"shop_id": shop_id}).fetchone()
    if not init_row or not init_row.is_initialized:
        return {"code": ErrorCode.BID_DATA_NOT_READY, "msg": "店铺数据未初始化完成"}

    ai_row = db.execute(text("""
        SELECT id FROM ai_pricing_configs WHERE shop_id = :shop_id FOR UPDATE
    """), {"shop_id": shop_id}).fetchone()
    if not ai_row:
        return {"code": ErrorCode.BID_AI_CONFIG_NOT_FOUND, "msg": "AI调价配置不存在"}

    time_row = db.execute(text("""
        SELECT id, is_active FROM time_pricing_rules WHERE shop_id = :shop_id FOR UPDATE
    """), {"shop_id": shop_id}).fetchone()
    if time_row and time_row.is_active:
        return {"code": ErrorCode.BID_CONFLICT_TIME_AI, "msg": "分时调价已启用，请先停用"}

    db.execute(text("""
        UPDATE ai_pricing_configs
        SET is_active = 1, auto_execute = :auto_execute, updated_at = NOW()
        WHERE shop_id = :shop_id
    """), {"shop_id": shop_id, "auto_execute": 1 if auto_execute else 0})
    db.commit()
    return {"code": 0}


def disable(db, shop_id: int) -> dict:
    """停用 AI 调价（pending建议保留）"""
    db.execute(text("""
        UPDATE ai_pricing_configs
        SET is_active = 0, auto_execute = 0, updated_at = NOW()
        WHERE shop_id = :shop_id
    """), {"shop_id": shop_id})
    db.commit()
    return {"code": 0}


# ==================== 主分析流程 ====================

async def execute(db, shop_id: int) -> dict:
    """Celery 触发的 AI 调价主流程

    Returns: {analyzed_count, suggestion_count, auto_executed_count, status, message}
    """
    cfg = db.execute(text("""
        SELECT id, tenant_id, shop_id, is_active, auto_execute, template_name,
               conservative_config, default_config, aggressive_config,
               retry_at
        FROM ai_pricing_configs
        WHERE shop_id = :shop_id AND is_active = 1
        LIMIT 1
    """), {"shop_id": shop_id}).fetchone()

    if not cfg:
        return {"status": "skipped", "message": "AI调价未启用"}

    if cfg.retry_at and now_moscow().replace(tzinfo=None) < cfg.retry_at:
        return {"status": "skipped", "message": "等待失败重试时间"}

    return await analyze_now(db, shop_id, force=False)


async def analyze_now(db, shop_id: int, force: bool = True, campaign_ids: Optional[list] = None) -> dict:
    """立即分析（手动触发或 Celery）

    Returns: {analyzed_count, suggestion_count, auto_executed_count, time_cost_ms}
    """
    start = datetime.now()
    cfg = db.execute(text("""
        SELECT id, tenant_id, shop_id, is_active, auto_execute, template_name,
               conservative_config, default_config, aggressive_config
        FROM ai_pricing_configs WHERE shop_id = :shop_id LIMIT 1
    """), {"shop_id": shop_id}).fetchone()

    if not cfg:
        return {"status": "failed", "message": "AI配置不存在", "analyzed_count": 0, "suggestion_count": 0, "auto_executed_count": 0}

    template = _read_template(cfg)
    if not template:
        _update_status(db, shop_id, "failed", "模板配置缺失", retry=False)
        return {"status": "failed", "message": "模板配置缺失", "analyzed_count": 0, "suggestion_count": 0, "auto_executed_count": 0}

    from app.models.shop import Shop
    shop = db.query(Shop).filter(Shop.id == shop_id).first()
    if not shop or shop.platform != "ozon":
        return {"status": "failed", "message": "非Ozon店铺", "analyzed_count": 0, "suggestion_count": 0, "auto_executed_count": 0}

    from app.models.ad import AdCampaign
    q = db.query(AdCampaign).filter(
        AdCampaign.shop_id == shop_id,
        AdCampaign.platform == "ozon",
        AdCampaign.status == "active",
    )
    if campaign_ids:
        q = q.filter(AdCampaign.id.in_(campaign_ids))
    campaigns = q.all()

    if not campaigns:
        _update_status(db, shop_id, "success", "无活跃活动")
        return {"status": "success", "message": "无活跃活动", "analyzed_count": 0, "suggestion_count": 0, "auto_executed_count": 0}

    # 拉商品出价
    from app.services.platform.ozon import OzonClient
    client = OzonClient(
        shop_id=shop.id, api_key=shop.api_key, client_id=shop.client_id,
        perf_client_id=shop.perf_client_id or "",
        perf_client_secret=shop.perf_client_secret or "",
    )

    products_by_campaign = {}
    try:
        for camp in campaigns:
            try:
                products = await client.fetch_campaign_products(camp.platform_campaign_id)
            except Exception as e:
                logger.warning(f"campaign={camp.id} 拉商品失败: {e}")
                products = []
            products_by_campaign[camp.id] = products
    finally:
        await client.close()

    if not any(products_by_campaign.values()):
        _update_status(db, shop_id, "success", "活跃活动下无商品")
        return {"status": "success", "message": "无商品数据", "analyzed_count": len(campaigns), "suggestion_count": 0, "auto_executed_count": 0}

    # 调 DeepSeek 分析
    suggestions_raw = []
    try:
        suggestions_raw = await _call_ai(template, campaigns, products_by_campaign)
    except Exception as e:
        logger.error(f"DeepSeek 调用失败 shop_id={shop_id}: {e}")
        _update_status(db, shop_id, "failed", f"DeepSeek调用失败: {e}", retry=True)
        return {"status": "failed", "message": str(e), "analyzed_count": len(campaigns), "suggestion_count": 0, "auto_executed_count": 0}

    # 标记昨天及之前的 pending 建议为 rejected（自动过期）
    db.execute(text("""
        UPDATE ai_pricing_suggestions
        SET status = 'rejected'
        WHERE shop_id = :shop_id AND status = 'pending'
          AND DATE(generated_at) < :today
    """), {"shop_id": shop_id, "today": moscow_today()})

    # 写入新建议
    saved = []
    for raw in suggestions_raw:
        camp_id = raw.get("campaign_id")
        sku = str(raw.get("platform_sku_id") or "")
        if not camp_id or not sku:
            continue
        current_bid = float(raw.get("current_bid") or 0)
        suggested_bid = float(raw.get("suggested_bid") or 0)

        # 安全护栏：max_bid 上限 + MIN_BID 下限 + max_adjust_pct
        max_bid = float(template.get("max_bid", 999))
        max_pct = float(template.get("max_adjust_pct", 30))
        suggested_bid = max(suggested_bid, MIN_BID)
        suggested_bid = min(suggested_bid, max_bid)
        if current_bid > 0:
            change_pct = abs(suggested_bid - current_bid) / current_bid * 100
            if change_pct > max_pct:
                # 限幅
                if suggested_bid > current_bid:
                    suggested_bid = round(current_bid * (1 + max_pct / 100))
                else:
                    suggested_bid = round(current_bid * (1 - max_pct / 100))
        suggested_bid = round(suggested_bid)
        if abs(suggested_bid - current_bid) < MIN_DIFF:
            continue

        adjust_pct = round((suggested_bid - current_bid) / current_bid * 100, 2) if current_bid > 0 else 0

        result = db.execute(text("""
            INSERT INTO ai_pricing_suggestions (
                tenant_id, shop_id, campaign_id,
                platform_sku_id, sku_name,
                current_bid, suggested_bid, adjust_pct,
                product_stage, decision_basis,
                current_roas, expected_roas,
                data_days, reason, status, generated_at
            ) VALUES (
                :tenant_id, :shop_id, :campaign_id,
                :sku, :sku_name,
                :current_bid, :suggested_bid, :adjust_pct,
                :stage, :basis,
                :current_roas, :expected_roas,
                :data_days, :reason, 'pending', NOW()
            )
        """), {
            "tenant_id": cfg.tenant_id,
            "shop_id": shop_id,
            "campaign_id": camp_id,
            "sku": sku,
            "sku_name": (raw.get("sku_name") or "")[:300],
            "current_bid": current_bid,
            "suggested_bid": suggested_bid,
            "adjust_pct": adjust_pct,
            "stage": raw.get("product_stage") or "unknown",
            "basis": raw.get("decision_basis") or "shop_benchmark",
            "current_roas": raw.get("current_roas"),
            "expected_roas": raw.get("expected_roas"),
            "data_days": raw.get("data_days") or 0,
            "reason": (raw.get("reason") or "")[:500],
        })
        saved.append({
            "id": result.lastrowid,
            "campaign_id": camp_id,
            "platform_sku_id": sku,
            "current_bid": current_bid,
            "suggested_bid": suggested_bid,
            "adjust_pct": adjust_pct,
            "sku_name": raw.get("sku_name"),
            "product_stage": raw.get("product_stage") or "unknown",
            "reason": raw.get("reason"),
        })

    db.commit()

    auto_executed = 0
    if cfg.auto_execute and saved:
        auto_executed = await _auto_execute(db, shop, saved)

    elapsed = int((datetime.now() - start).total_seconds() * 1000)
    summary = f"分析{len(campaigns)}个活动 生成{len(saved)}条建议"
    if auto_executed:
        summary += f" 自动执行{auto_executed}条"
    _update_status(db, shop_id, "success", summary)

    return {
        "status": "success",
        "analyzed_count": len(campaigns),
        "suggestion_count": len(saved),
        "auto_executed_count": auto_executed,
        "time_cost_ms": elapsed,
        "suggestions": saved,
    }


async def _auto_execute(db, shop, suggestions: list) -> int:
    """auto_execute=1 模式：直接执行所有建议"""
    from app.services.platform.ozon import OzonClient
    from app.models.ad import AdCampaign

    client = OzonClient(
        shop_id=shop.id, api_key=shop.api_key, client_id=shop.client_id,
        perf_client_id=shop.perf_client_id or "",
        perf_client_secret=shop.perf_client_secret or "",
    )

    executed = 0
    try:
        for s in suggestions:
            campaign = db.query(AdCampaign).filter(AdCampaign.id == s["campaign_id"]).first()
            if not campaign:
                continue

            # 跳过 user_managed=1
            ag_row = db.execute(text("""
                SELECT user_managed FROM ad_groups
                WHERE campaign_id = :cid AND platform_group_id = :sku
                LIMIT 1
            """), {"cid": campaign.id, "sku": s["platform_sku_id"]}).fetchone()
            if ag_row and ag_row.user_managed:
                continue

            try:
                api_result = await client.update_campaign_bid(
                    campaign.platform_campaign_id, s["platform_sku_id"],
                    str(int(s["suggested_bid"] * 1_000_000))
                )
                if not api_result.get("ok"):
                    _write_bidlog(db, campaign, s, "ai_auto", success=False, error=api_result.get("error"))
                    continue
                _upsert_group_last_auto(db, campaign, s["platform_sku_id"], s.get("sku_name") or "", s["suggested_bid"])
                db.execute(text("""
                    UPDATE ai_pricing_suggestions
                    SET status = 'approved', executed_at = NOW()
                    WHERE id = :id
                """), {"id": s["id"]})
                _write_bidlog(db, campaign, s, "ai_auto", success=True)
                executed += 1
            except Exception as e:
                logger.error(f"auto execute 异常 sku={s['platform_sku_id']}: {e}")
                _write_bidlog(db, campaign, s, "ai_auto", success=False, error=str(e))
        db.commit()
    finally:
        await client.close()

    return executed


# ==================== 单条 / 批量 approve ====================

async def approve_suggestion(db, suggestion_id: int) -> dict:
    """单条 approve（POST /suggestions/{id}/approve）"""
    row = db.execute(text("""
        SELECT
            s.id, s.tenant_id, s.shop_id, s.campaign_id,
            s.platform_sku_id, s.sku_name, s.product_stage,
            s.current_bid, s.suggested_bid, s.adjust_pct,
            s.status, s.generated_at,
            c.platform_campaign_id, c.name AS campaign_name
        FROM ai_pricing_suggestions s
        JOIN ad_campaigns c ON s.campaign_id = c.id
        WHERE s.id = :id
    """), {"id": suggestion_id}).fetchone()

    if not row:
        return {"code": ErrorCode.BID_SUGGESTION_NOT_FOUND, "msg": "建议不存在"}
    if row.status != "pending":
        return {"code": ErrorCode.BID_INVALID_STATUS, "msg": f"当前状态 {row.status} 不允许执行"}
    if row.generated_at and row.generated_at.date() < moscow_today():
        return {"code": ErrorCode.BID_SUGGESTION_EXPIRED, "msg": "建议已过期"}

    from app.models.shop import Shop
    from app.services.platform.ozon import OzonClient

    shop = db.query(Shop).filter(Shop.id == row.shop_id).first()
    if not shop:
        return {"code": ErrorCode.SHOP_NOT_FOUND, "msg": "店铺不存在"}

    client = OzonClient(
        shop_id=shop.id, api_key=shop.api_key, client_id=shop.client_id,
        perf_client_id=shop.perf_client_id or "",
        perf_client_secret=shop.perf_client_secret or "",
    )
    try:
        api_result = await client.update_campaign_bid(
            row.platform_campaign_id, row.platform_sku_id,
            str(int(float(row.suggested_bid) * 1_000_000))
        )
    finally:
        await client.close()

    if not api_result.get("ok"):
        return {"code": ErrorCode.BID_EXECUTION_FAILED,
                "msg": api_result.get("error") or "Ozon API失败"}

    # 更新建议
    now = datetime.now()
    db.execute(text("""
        UPDATE ai_pricing_suggestions
        SET status = 'approved', executed_at = :now
        WHERE id = :id
    """), {"id": suggestion_id, "now": now})

    # 更新 ad_groups.last_auto_bid（防分时调价误判）
    from app.models.ad import AdCampaign
    campaign = db.query(AdCampaign).filter(AdCampaign.id == row.campaign_id).first()
    _upsert_group_last_auto(db, campaign, row.platform_sku_id, row.sku_name or "", float(row.suggested_bid))

    # 写日志
    _write_bidlog(
        db, campaign,
        {
            "platform_sku_id": row.platform_sku_id,
            "sku_name": row.sku_name,
            "current_bid": float(row.current_bid),
            "suggested_bid": float(row.suggested_bid),
            "adjust_pct": float(row.adjust_pct),
            "product_stage": row.product_stage,
        },
        "ai_manual", success=True
    )
    db.commit()

    return {
        "code": 0,
        "data": {
            "id": suggestion_id,
            "status": "approved",
            "executed_at": now.isoformat(),
            "old_bid": float(row.current_bid),
            "new_bid": float(row.suggested_bid),
        }
    }


async def approve_batch(db, ids: list) -> dict:
    """批量 approve（部分成功语义）"""
    results = []
    success_cnt = 0
    failed_cnt = 0
    for sid in ids:
        try:
            r = await approve_suggestion(db, sid)
            if r.get("code") == 0:
                results.append({"id": sid, "status": "approved"})
                success_cnt += 1
            else:
                results.append({
                    "id": sid, "status": "failed",
                    "error_code": r.get("code"), "error_msg": r.get("msg"),
                })
                failed_cnt += 1
        except Exception as e:
            results.append({
                "id": sid, "status": "failed",
                "error_code": ErrorCode.BID_EXECUTION_FAILED,
                "error_msg": str(e),
            })
            failed_cnt += 1
    return {
        "code": 0,
        "data": {
            "total": len(ids),
            "success": success_cnt,
            "failed": failed_cnt,
            "results": results,
        }
    }


def reject_suggestion(db, suggestion_id: int) -> dict:
    db.execute(text("""
        UPDATE ai_pricing_suggestions
        SET status = 'rejected'
        WHERE id = :id AND status = 'pending'
    """), {"id": suggestion_id})
    db.commit()
    return {"code": 0, "data": {"id": suggestion_id, "status": "rejected"}}


def reject_batch(db, ids: list) -> dict:
    if ids:
        from sqlalchemy import bindparam
        stmt = text("""
            UPDATE ai_pricing_suggestions
            SET status = 'rejected'
            WHERE id IN :ids AND status = 'pending'
        """).bindparams(bindparam("ids", expanding=True))
        db.execute(stmt, {"ids": list(ids)})
        db.commit()
    return {"code": 0, "data": {"total": len(ids)}}


# ==================== 内部工具 ====================

_DEFAULT_CONSERVATIVE = {
    "target_roas": 2.0, "min_roas": 1.5, "max_bid": 100,
    "daily_budget": 500, "max_adjust_pct": 15, "gross_margin": 0.5,
}
_DEFAULT_DEFAULT = {
    "target_roas": 3.0, "min_roas": 1.8, "max_bid": 180,
    "daily_budget": 2000, "max_adjust_pct": 30, "gross_margin": 0.5,
}
_DEFAULT_AGGRESSIVE = {
    "target_roas": 4.0, "min_roas": 2.5, "max_bid": 300,
    "daily_budget": 0, "max_adjust_pct": 25, "gross_margin": 0.5,
}


def _validate_template_json(t: dict) -> Optional[str]:
    """校验模板字段范围"""
    try:
        if not (0 < float(t.get("target_roas", 0)) <= 100):
            return "target_roas 范围 (0, 100]"
        if not (0 < float(t.get("min_roas", 0)) <= 100):
            return "min_roas 范围 (0, 100]"
        if float(t["min_roas"]) >= float(t["target_roas"]):
            return "min_roas 必须 < target_roas"
        if not (3 <= float(t.get("max_bid", 0)) <= 10000):
            return "max_bid 范围 [3, 10000]"
        if not (0 <= float(t.get("daily_budget", 0)) <= 1000000):
            return "daily_budget 范围 [0, 1000000]"
        if not (0 < float(t.get("max_adjust_pct", 0)) <= 100):
            return "max_adjust_pct 范围 (0, 100]"
        if not (0 < float(t.get("gross_margin", 0)) < 1):
            return "gross_margin 范围 (0, 1)"
    except (KeyError, TypeError, ValueError) as e:
        return f"字段缺失或类型错误: {e}"
    return None


def _read_template(cfg) -> dict:
    """从 cfg 读取当前 template_name 指向的 JSON 模板"""
    name = cfg.template_name or "default"
    raw = getattr(cfg, f"{name}_config", None)
    if raw is None:
        return {}
    if isinstance(raw, dict):
        return raw
    try:
        return json.loads(raw)
    except (ValueError, TypeError):
        return {}


async def _call_ai(template: dict, campaigns: list, products_by_campaign: dict) -> list:
    """调 DeepSeek 生成调价建议（简化版 prompt）"""
    from app.services.ai.deepseek import DeepSeekClient

    api_key = getattr(settings, "DEEPSEEK_API_KEY", "")
    if not api_key:
        raise RuntimeError("DEEPSEEK_API_KEY 未配置")

    # 构造 prompt 数据
    prompt_data = []
    for camp in campaigns:
        products = products_by_campaign.get(camp.id) or []
        items = []
        for p in products[:50]:  # 单活动最多50个商品
            sku = str(p.get("sku") or "")
            bid_raw = p.get("bid", "0")
            try:
                bid_rub = float(int(bid_raw)) / 1_000_000
            except (ValueError, TypeError):
                bid_rub = 0
            if bid_rub <= 0:
                continue
            items.append({
                "sku": sku,
                "name": (p.get("title") or "")[:80],
                "bid": round(bid_rub, 2),
            })
        if items:
            prompt_data.append({
                "campaign_id": camp.id,
                "campaign_name": camp.name,
                "products": items,
            })

    if not prompt_data:
        return []

    prompt = f"""你是Ozon广告优化专家。对每个商品给出CPM出价建议。

【策略模板】
- 目标ROAS: {template.get('target_roas')}
- 最低ROAS: {template.get('min_roas')}
- 最高出价: {template.get('max_bid')}卢布
- 单次最大调幅: {template.get('max_adjust_pct')}%
- 毛利率: {template.get('gross_margin')}

【活动和商品当前出价】
{json.dumps(prompt_data, ensure_ascii=False)}

请为有调整空间的商品输出建议。无需调整的商品不要返回。
返回纯JSON：
{{
  "suggestions": [
    {{
      "campaign_id": <活动ID>,
      "platform_sku_id": "<SKU>",
      "sku_name": "<商品名>",
      "current_bid": <当前出价数值>,
      "suggested_bid": <建议出价整数>,
      "product_stage": "growing|testing|cold_start|declining|unknown",
      "decision_basis": "history_data|shop_benchmark|cold_start_baseline",
      "reason": "<简短理由>"
    }}
  ]
}}
"""

    client = DeepSeekClient(api_key=api_key)
    result = await client.chat(
        messages=[{"role": "user", "content": prompt}],
        temperature=0.3,
        max_tokens=4000,
    )
    content = result.get("content", "")

    parsed = _parse_ai_response(content)
    return parsed.get("suggestions") or []


def _parse_ai_response(content: str) -> dict:
    if not content:
        return {}
    try:
        return json.loads(content)
    except (ValueError, TypeError):
        pass
    # 提取 ```json ... ``` 块
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", content, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(1))
        except (ValueError, TypeError):
            pass
    # 提取最外层大括号
    m = re.search(r"\{.*\}", content, re.DOTALL)
    if m:
        try:
            return json.loads(m.group())
        except (ValueError, TypeError):
            pass
    logger.error(f"AI响应解析失败: {content[:200]}")
    return {}


def _upsert_group_last_auto(db, campaign, sku: str, sku_name: str, last_auto: float):
    db.execute(text("""
        INSERT INTO ad_groups (
            tenant_id, campaign_id, platform_group_id, name,
            last_auto_bid, status
        ) VALUES (
            :tenant_id, :campaign_id, :sku, :name,
            :last_auto, 'active'
        )
        ON DUPLICATE KEY UPDATE
            name = VALUES(name),
            last_auto_bid = :last_auto,
            updated_at = NOW()
    """), {
        "tenant_id": campaign.tenant_id,
        "campaign_id": campaign.id,
        "sku": sku,
        "name": sku_name[:200] if sku_name else f"SKU-{sku}",
        "last_auto": last_auto,
    })


def _write_bidlog(db, campaign, suggestion: dict, execute_type: str,
                  success: bool = True, error: str = None):
    """写 bid_adjustment_logs"""
    db.execute(text("""
        INSERT INTO bid_adjustment_logs (
            tenant_id, shop_id, campaign_id, campaign_name,
            platform_sku_id, sku_name,
            old_bid, new_bid, adjust_pct,
            execute_type, product_stage, moscow_hour,
            success, error_msg, created_at
        ) VALUES (
            :tenant_id, :shop_id, :campaign_id, :campaign_name,
            :sku, :sku_name,
            :old_bid, :new_bid, :pct,
            :execute_type, :stage, :hour,
            :success, :error, NOW()
        )
    """), {
        "tenant_id": campaign.tenant_id,
        "shop_id": campaign.shop_id,
        "campaign_id": campaign.id,
        "campaign_name": campaign.name,
        "sku": suggestion["platform_sku_id"],
        "sku_name": (suggestion.get("sku_name") or "")[:300] or None,
        "old_bid": suggestion["current_bid"],
        "new_bid": suggestion["suggested_bid"],
        "pct": suggestion.get("adjust_pct") or 0,
        "execute_type": execute_type,
        "stage": suggestion.get("product_stage") or "unknown",
        "hour": moscow_hour(),
        "success": 1 if success else 0,
        "error": (error or "")[:500] if error else None,
    })


def _update_status(db, shop_id: int, status: str, msg: str, retry: bool = False):
    db.execute(text("""
        UPDATE ai_pricing_configs
        SET last_executed_at = NOW(),
            last_execute_status = :status,
            last_error_msg = :msg,
            retry_at = CASE WHEN :retry = 1 THEN DATE_ADD(NOW(), INTERVAL 30 MINUTE) ELSE NULL END
        WHERE shop_id = :shop_id
    """), {
        "shop_id": shop_id,
        "status": status,
        "msg": msg[:500] if msg else None,
        "retry": 1 if retry else 0,
    })
    db.commit()
