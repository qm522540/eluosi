"""SEO 健康诊断 — 商品级 0-100 分评分引擎

回答用户的核心问题："店铺里 79 个商品，该优先优化哪几个？为什么？怎么改？"

评分维度（一期 MVP）：
- 关键词覆盖率 60%：候选池 in_title OR in_attrs 的比例 × 60
- 标题长度 20%：30-180 字符满分，< 30 扣 0，180-200 扣 15，> 200 违规
- 评分 20%：listing.rating / 5 × 20

数据源：
- products                核心信息
- platform_listings       标题 / rating
- seo_keyword_candidates  候选池（必须先跑引擎才有数据）

规则合规：
- 规则 1 tenant_id：三表 JOIN 全带 tenant_id 条件
- 规则 4 shop_id：products/listings/candidates 全 WHERE shop_id（调用方 API 层已 get_owned_shop 守卫）

不新建表 / 不持久化评分 / 不写后端缓存 — 一期商品量 < 500 即时算跑得快。
若扩到 > 2000 商品再加 Redis 缓存 + 后台每日重算。
"""

from __future__ import annotations

import json
from collections import defaultdict
from typing import Optional

from sqlalchemy import bindparam, text
from sqlalchemy.orm import Session

from app.utils.errors import ErrorCode


# ==================== 评分函数 ====================

def _score_coverage(total: int, covered: int) -> tuple[float, dict]:
    """候选词覆盖率得分，上限 60。"""
    if total == 0:
        return 0.0, {"weight": 60, "covered": 0, "total": 0, "data_insufficient": True}
    rate = covered / total
    return round(rate * 60, 1), {
        "weight": 60, "covered": covered, "total": total,
        "rate_pct": round(rate * 100, 1),
        "data_insufficient": False,
    }


def _score_title_length(title: Optional[str]) -> tuple[float, dict]:
    """俄语标题长度得分，上限 20。
    < 30:         0（过短）
    30-50:       递增
    50-180:      满分 20
    180-200:     扣到 15（接近平台上限）
    > 200:       0（违规）
    空/None:      0
    """
    if not title:
        return 0.0, {"weight": 20, "length": 0, "hint": "标题为空，请先同步商品或手动填写"}
    n = len(title)
    if n < 30:
        return 0.0, {"weight": 20, "length": n, "hint": "标题过短（< 30 字符），可融合反哺词扩展"}
    if n <= 50:
        sc = (n - 30) / 20 * 20
        return round(sc, 1), {"weight": 20, "length": n, "hint": f"标题偏短（{n} / 建议 50-180）"}
    if n <= 180:
        return 20.0, {"weight": 20, "length": n, "hint": "标题长度理想"}
    if n <= 200:
        sc = 20 - (n - 180) / 20 * 5
        return round(sc, 1), {"weight": 20, "length": n, "hint": f"标题偏长（{n} / 接近平台上限 200）"}
    return 0.0, {"weight": 20, "length": n, "hint": f"标题超长（{n} > 200），违反平台规则"}


def _score_rating(rating: Optional[float]) -> tuple[float, dict]:
    """评分得分，上限 20（若维度无数据会在 _finalize_score 被重分权）。

    Ozon Seller API /v3/product/info/list 不返 rating 字段，Ozon 商品此维度
    会标 data_insufficient=True，由 _finalize_score 把权重重分配到其他维度。
    WB listing.rating 同步正常，走 1-5 打分路径。
    """
    if rating is None:
        return 0.0, {
            "weight": 20, "rating": None,
            "data_insufficient": True,
            "hint": "该平台 API 不返回评分（已从评分中豁免，权重已重分配到其他维度）",
        }
    if rating <= 0:
        return 0.0, {"weight": 20, "rating": 0, "hint": "0 分或无评价（可能是新品）"}
    r = max(0.0, min(5.0, float(rating)))
    sc = round(r / 5 * 20, 1)
    hint = "好评" if r >= 4 else ("中评" if r >= 3 else "差评需处理")
    return sc, {"weight": 20, "rating": round(r, 2), "hint": hint}


def _finalize_score(dims: list[dict]) -> float:
    """按可用维度动态重分权得出 0-100 总分。

    规则：
    - 维度 data_insufficient=True → 权重 = 0，不参与计分
    - 其他维度的总得分按 (sum_score / sum_available_weight) * 100 放大
    - 例：Ozon 商品 rating 无数据 → available_weight = 60+20 = 80 → 总分 = raw × 100/80
    - 所有维度都无数据（极罕见）→ 0
    """
    avail = [d for d in dims if not d.get("data_insufficient")]
    if not avail:
        return 0.0
    avail_weight = sum(d["weight"] for d in avail)
    raw = sum(d["score"] for d in avail)
    if avail_weight <= 0:
        return 0.0
    return round(raw / avail_weight * 100, 1)


def _classify(score: float) -> str:
    """> 70 优 / 40-70 中 / < 40 差"""
    if score >= 70:
        return "good"
    if score >= 40:
        return "fair"
    return "poor"


# ==================== 主入口 ====================

def compute_shop_health(
    db: Session,
    tenant_id: int,
    shop,  # Shop ORM 对象（API 层 get_owned_shop 已守卫）
    score_range: str = "all",
    sort: str = "score_asc",
    keyword: str = "",
    page: int = 1,
    size: int = 20,
) -> dict:
    """计算店铺所有商品的 SEO 健康分。

    Returns:
        {"code": 0, "data": {totals, items, page, size}}
    """
    shop_id = shop.id

    # ---------- SQL 1: 商品主表 + 候选统计 + listing 字段 ----------
    main_sql = text("""
        SELECT
            p.id AS pid,
            p.sku AS sku,
            p.name_zh,
            p.image_url,
            ANY_VALUE(pl.id) AS listing_id,
            ANY_VALUE(pl.title_ru) AS title_ru,
            ANY_VALUE(pl.rating) AS rating,
            ANY_VALUE(pl.review_count) AS review_count,
            ANY_VALUE(pl.platform) AS platform,
            COUNT(DISTINCT c.id) AS total_candidates,
            SUM(CASE WHEN c.in_title = 1 OR c.in_attrs = 1 THEN 1 ELSE 0 END) AS covered
        FROM products p
        LEFT JOIN platform_listings pl
            ON pl.product_id = p.id
           AND pl.tenant_id = p.tenant_id
           AND pl.shop_id = p.shop_id
           AND pl.status NOT IN ('deleted', 'archived')
        LEFT JOIN seo_keyword_candidates c
            ON c.product_id = p.id
           AND c.tenant_id = p.tenant_id
           AND c.shop_id = p.shop_id
           AND c.status = 'pending'
        WHERE p.tenant_id = :tid
          AND p.shop_id = :sid
          AND p.status = 'active'
        GROUP BY p.id
    """)
    rows = db.execute(main_sql, {"tid": tenant_id, "sid": shop_id}).fetchall()

    # ---------- 过滤关键词（Python 层，商品量少）----------
    if keyword and keyword.strip():
        kw_low = keyword.strip().lower()
        rows = [r for r in rows
                if (r.name_zh or "").lower().find(kw_low) >= 0
                or (r.title_ru or "").lower().find(kw_low) >= 0]

    # ---------- Python 算分 ----------
    items = []
    totals = {"poor": 0, "fair": 0, "good": 0, "sum_score": 0.0}
    for r in rows:
        total_cand = int(r.total_candidates or 0)
        covered = int(r.covered or 0)

        cov_score, cov_detail = _score_coverage(total_cand, covered)
        tit_score, tit_detail = _score_title_length(r.title_ru)
        rat_score, rat_detail = _score_rating(r.rating)

        dims_for_final = [
            {"score": cov_score, **cov_detail},
            {"score": tit_score, **tit_detail},
            {"score": rat_score, **rat_detail},
        ]
        total_score = _finalize_score(dims_for_final)
        grade = _classify(total_score)
        totals[grade] += 1
        totals["sum_score"] += total_score

        items.append({
            "product_id": int(r.pid),
            "sku": r.sku or "",
            "product_name": r.name_zh or "",
            "image_url": r.image_url,
            "listing_id": int(r.listing_id) if r.listing_id else None,
            "platform": r.platform,
            "current_title": r.title_ru or "",
            "rating": float(r.rating) if r.rating is not None else None,
            "review_count": int(r.review_count or 0),
            "candidate_count": total_cand,
            "covered_count": covered,
            "score": total_score,
            "grade": grade,
            "dimensions": {
                "coverage": {"score": cov_score, **cov_detail},
                "title_length": {"score": tit_score, **tit_detail},
                "rating": {"score": rat_score, **rat_detail},
            },
            "missing_top_keywords": [],   # Step 2 填充
        })

    # ---------- score_range 过滤 ----------
    if score_range == "poor":
        items = [i for i in items if i["grade"] == "poor"]
    elif score_range == "fair":
        items = [i for i in items if i["grade"] == "fair"]
    elif score_range == "good":
        items = [i for i in items if i["grade"] == "good"]
    elif score_range == "data_insufficient":
        items = [i for i in items if i["dimensions"]["coverage"]["data_insufficient"]]

    # ---------- 排序 ----------
    if sort == "score_desc":
        items.sort(key=lambda x: -x["score"])
    elif sort == "gaps_desc":
        # 缺词数（覆盖率的反面 × 候选数）越大越优先，先让数据多的往前
        items.sort(key=lambda x: -(x["candidate_count"] - x["covered_count"]))
    else:  # score_asc 默认：最差的排在最前
        items.sort(key=lambda x: (x["score"], -x["candidate_count"]))

    # ---------- 分页 ----------
    total_count = len(items)
    offset = (page - 1) * size
    page_items = items[offset:offset + size]
    page_pids = [i["product_id"] for i in page_items]

    # ---------- SQL 2: 当前页商品的"缺词 Top 3"（in_title=0 AND in_attrs=0）----------
    # 取 sources 字段供分类（cross_shop 词来自他店同 sku 召回，需要拿 source_shop_name）
    if page_pids:
        miss_stmt = text("""
            SELECT product_id, keyword, score, sources,
                   paid_orders, paid_roas,
                   organic_impressions, organic_orders
            FROM seo_keyword_candidates
            WHERE tenant_id = :tid
              AND shop_id = :sid
              AND status = 'pending'
              AND in_title = 0 AND in_attrs = 0
              AND product_id IN :pids
            ORDER BY product_id, score DESC
        """).bindparams(bindparam("pids", expanding=True))
        miss_rows = db.execute(miss_stmt, {
            "tid": tenant_id, "sid": shop_id, "pids": page_pids,
        }).fetchall()

        miss_by_pid: dict[int, list] = defaultdict(list)
        for mr in miss_rows:
            if len(miss_by_pid[mr.product_id]) >= 3:
                continue
            srcs = mr.sources if isinstance(mr.sources, list) else (
                json.loads(mr.sources) if mr.sources else []
            )
            # source_type 取主类（优先级：paid > organic > cross_shop）
            # 让前端分色 Tag 用，但 cross_shop 词的 metric 走专属分支显示来源店名
            has_paid = any(s.get("type") == "paid" for s in srcs)
            has_organic = any(s.get("type") == "organic" for s in srcs)
            has_cross = any(s.get("type") == "cross_shop" for s in srcs)
            cross_entry = next((s for s in srcs if s.get("type") == "cross_shop"), None)

            if has_paid:
                source_type = "paid"
            elif has_organic:
                source_type = "organic"
            elif has_cross:
                source_type = "cross_shop"
            else:
                source_type = "unknown"

            # metric: 跨店词显示来源店 + 曝光/订单；本店词按原优先级
            metric = None
            if source_type == "cross_shop" and cross_entry:
                shop_name = cross_entry.get("source_shop_name") or "其他店"
                freq = int(cross_entry.get("frequency") or 0)
                orders = int(cross_entry.get("orders") or 0)
                if orders > 0:
                    metric = f"{shop_name} {freq}曝光/{orders}订单"
                else:
                    metric = f"{shop_name} {freq}曝光"
            elif mr.paid_orders:
                metric = f"付费订单 {mr.paid_orders}"
            elif mr.organic_orders:
                metric = f"自然订单 {mr.organic_orders}"
            elif mr.organic_impressions:
                metric = f"自然曝光 {mr.organic_impressions}"
            elif mr.paid_roas:
                metric = f"ROAS {float(mr.paid_roas):.2f}"

            miss_by_pid[mr.product_id].append({
                "keyword": mr.keyword,
                "score": float(mr.score or 0),
                "source_type": source_type,
                "source_shop_name": cross_entry.get("source_shop_name") if cross_entry else None,
                "metric": metric,
            })

        for item in page_items:
            item["missing_top_keywords"] = miss_by_pid.get(item["product_id"], [])

    # ---------- 汇总 ----------
    n_all = len(rows)
    avg_score = round(totals["sum_score"] / n_all, 1) if n_all else 0.0

    return {
        "code": ErrorCode.SUCCESS,
        "data": {
            "totals": {
                "total": total_count,     # 过滤/筛选后
                "all": n_all,             # 原始商品总数（未筛）
                "poor": totals["poor"],
                "fair": totals["fair"],
                "good": totals["good"],
                "avg_score": avg_score,
            },
            "items": page_items,
            "page": page,
            "size": size,
        },
    }


def list_missing_candidates_for_product(
    db: Session,
    tenant_id: int,
    shop,
    product_id: int,
) -> dict:
    """单商品全部未覆盖候选词（健康诊断行展开用）。

    与 compute_shop_health.missing_top_keywords 相比：
    - 不限 Top 3，返回全部 in_title=0 AND in_attrs=0 的 pending 候选
    - 每条字段更全：本店付费/自然指标 + 跨店 source_shop/曝光/订单
    - 前端展开抽屉用：分类筛选 / 多选生成新标题
    """
    sql = text("""
        SELECT id AS candidate_id,
               keyword, score, sources,
               paid_orders, paid_revenue, paid_roas, paid_spend,
               organic_orders, organic_impressions, organic_add_to_cart,
               in_title, in_attrs
        FROM seo_keyword_candidates
        WHERE tenant_id = :tid
          AND shop_id = :sid
          AND product_id = :pid
          AND status = 'pending'
          AND in_title = 0 AND in_attrs = 0
        ORDER BY score DESC
    """)
    rows = db.execute(sql, {
        "tid": tenant_id, "sid": shop.id, "pid": product_id,
    }).fetchall()

    items = []
    for r in rows:
        srcs = r.sources if isinstance(r.sources, list) else (
            json.loads(r.sources) if r.sources else []
        )
        has_paid = any(s.get("type") == "paid" for s in srcs)
        has_organic = any(s.get("type") == "organic" for s in srcs)
        cross_entry = next((s for s in srcs if s.get("type") == "cross_shop"), None)

        if has_paid:
            source_type = "paid"
        elif has_organic:
            source_type = "organic"
        elif cross_entry:
            source_type = "cross_shop"
        else:
            source_type = "unknown"

        items.append({
            "candidate_id": int(r.candidate_id),
            "keyword": r.keyword,
            "score": float(r.score or 0),
            "source_type": source_type,
            "sources": srcs,
            # 本店指标（paid/organic 来源时填）
            "paid_orders": int(r.paid_orders) if r.paid_orders is not None else None,
            "paid_revenue": float(r.paid_revenue) if r.paid_revenue is not None else None,
            "paid_roas": float(r.paid_roas) if r.paid_roas is not None else None,
            "organic_orders": int(r.organic_orders) if r.organic_orders is not None else None,
            "organic_impressions": int(r.organic_impressions) if r.organic_impressions is not None else None,
            "organic_add_to_cart": int(r.organic_add_to_cart) if r.organic_add_to_cart is not None else None,
            # 跨店指标（cross_shop 来源时填，他店真实数据）
            "cross_shop_name": cross_entry.get("source_shop_name") if cross_entry else None,
            "cross_shop_id": cross_entry.get("source_shop_id") if cross_entry else None,
            "cross_frequency": int(cross_entry.get("frequency") or 0) if cross_entry else None,
            "cross_orders": int(cross_entry.get("orders") or 0) if cross_entry else None,
            "cross_impressions": int(cross_entry.get("impressions") or 0) if cross_entry else None,
            "cross_add_to_cart": int(cross_entry.get("add_to_cart") or 0) if cross_entry else None,
        })

    return {
        "code": ErrorCode.SUCCESS,
        "data": {
            "product_id": product_id,
            "items": items,
            "total": len(items),
        },
    }
