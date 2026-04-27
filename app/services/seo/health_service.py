"""SEO 健康诊断 — 商品级 0-100 分评分引擎

回答用户的核心问题："店铺里 79 个商品，该优先优化哪几个？为什么？怎么改？"

评分维度（一期 MVP）：
- 关键词覆盖率 60%：候选池 in_title OR in_attrs 的比例 × 60
- 标题长度 20%：30-180 字符满分，< 30 扣 0，180-200 扣 15，> 200 违规
- 描述长度 20%：100-300 0→20 递增、300-2000 满分、2000-3000 衰减、> 3000 违规

数据源：
- products                核心信息
- platform_listings       标题 / 描述
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

def _score_coverage(self_total: int, self_covered: int,
                    cat_total: int = 0, cat_covered: int = 0) -> tuple[float, dict]:
    """候选词覆盖率得分，上限 60。

    评分口径：**只算本商品自己的候选词**（与右侧"缺词 Top 3"列表完全一致）。
    类目热门 Top 30 仅作 reference 显示在 detail，不参与扣分 —
      多词短语很难在 30-50 字符标题里子串命中，硬扣会冤枉短标题商品。
    self_total=0 → data_insufficient=True 走豁免，总分按剩余维度重分权。
    """
    if self_total == 0:
        return 0.0, {
            "weight": 60, "covered": 0, "total": 0,
            "self_total": 0, "category_top_total": cat_total,
            "category_top_covered": cat_covered,
            "data_insufficient": True,
            "hint": "本商品暂无自然搜索/付费候选词，类目热门作参考"
                    + (f"（命中 {cat_covered}/{cat_total}）" if cat_total else ""),
        }
    rate = self_covered / self_total
    return round(rate * 60, 1), {
        "weight": 60, "covered": self_covered, "total": self_total,
        "self_total": self_total, "category_top_total": cat_total,
        "category_top_covered": cat_covered,
        "rate_pct": round(rate * 100, 1),
        "data_insufficient": False,
    }


def _score_title_length(title: Optional[str]) -> tuple[float, dict]:
    """俄语标题长度得分，上限 20。
    空/None:      0
    < 20:         0（极短）
    20-50:       8→20 平滑递增（避免 30 字符正好踩边界 = 0）
    50-180:      满分 20
    180-200:     20→15
    > 200:       0（违规）
    """
    if not title:
        return 0.0, {"weight": 20, "length": 0, "hint": "标题为空，请先同步商品或手动填写"}
    n = len(title)
    if n < 20:
        return 0.0, {"weight": 20, "length": n, "hint": f"标题过短（{n} < 20 字符），融合反哺词扩展"}
    if n <= 50:
        sc = 8 + (n - 20) / 30 * 12
        return round(sc, 1), {"weight": 20, "length": n, "hint": f"标题偏短（{n} / 建议 50-180）"}
    if n <= 180:
        return 20.0, {"weight": 20, "length": n, "hint": "标题长度理想"}
    if n <= 200:
        sc = 20 - (n - 180) / 20 * 5
        return round(sc, 1), {"weight": 20, "length": n, "hint": f"标题偏长（{n} / 接近平台上限 200）"}
    return 0.0, {"weight": 20, "length": n, "hint": f"标题超长（{n} > 200），违反平台规则"}


def _score_description_length(description: Optional[str]) -> tuple[float, dict]:
    """俄语商品描述长度得分，上限 20。

    < 100:        0（描述过短或为空，几乎无 SEO 价值）
    100-300:     0→20 递增
    300-2000:    满分 20
    2000-3000:   20→10 衰减（接近平台上限）
    > 3000:      0（违规，Ozon ~6000 / WB ~5000，统一保守取 3000）

    商家可控字段，与"AI 优化描述"按钮形成行动闭环。
    """
    if not description:
        return 0.0, {
            "weight": 20, "length": 0,
            "hint": "描述为空，建议用「AI 优化描述」生成",
        }
    n = len(description)
    if n < 100:
        return 0.0, {"weight": 20, "length": n, "hint": f"描述过短（{n} < 100）几乎无 SEO 价值"}
    if n < 300:
        sc = (n - 100) / 200 * 20
        return round(sc, 1), {"weight": 20, "length": n, "hint": f"描述偏短（{n} / 建议 300-2000）"}
    if n <= 2000:
        return 20.0, {"weight": 20, "length": n, "hint": "描述长度理想"}
    if n <= 3000:
        sc = 20 - (n - 2000) / 1000 * 10
        return round(sc, 1), {"weight": 20, "length": n, "hint": f"描述偏长（{n} / 接近平台上限）"}
    return 0.0, {"weight": 20, "length": n, "hint": f"描述超长（{n} > 3000），违反平台规则"}


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

    # ---------- SQL 1: 商品主表 + listing 字段 + type_id (覆盖率算分需要) ----------
    main_sql = text("""
        SELECT
            p.id AS pid,
            p.sku AS sku,
            p.name_zh,
            p.image_url,
            ANY_VALUE(pl.id) AS listing_id,
            ANY_VALUE(pl.title_ru) AS title_ru,
            ANY_VALUE(pl.description_ru) AS description_ru,
            ANY_VALUE(pl.variant_attrs) AS variant_attrs,
            ANY_VALUE(pl.platform_category_extra_id) AS type_id,
            ANY_VALUE(pl.rating) AS rating,
            ANY_VALUE(pl.review_count) AS review_count,
            ANY_VALUE(pl.platform) AS platform
        FROM products p
        LEFT JOIN platform_listings pl
            ON pl.product_id = p.id
           AND pl.tenant_id = p.tenant_id
           AND pl.shop_id = p.shop_id
           AND pl.status NOT IN ('deleted', 'archived')
        WHERE p.tenant_id = :tid
          AND p.shop_id = :sid
          AND p.status = 'active'
        GROUP BY p.id
    """)
    rows = db.execute(main_sql, {"tid": tenant_id, "sid": shop_id}).fetchall()

    # ---------- SQL 2: 拉本店所有商品候选词 (keyword + 已覆盖标记) ----------
    cand_rows = db.execute(text("""
        SELECT product_id, keyword,
               (CASE WHEN in_title = 1 OR in_attrs = 1 THEN 1 ELSE 0 END) AS is_covered
        FROM seo_keyword_candidates
        WHERE tenant_id = :tid AND shop_id = :sid AND status = 'pending'
    """), {"tid": tenant_id, "sid": shop_id}).fetchall()
    self_kws_by_pid: dict = {}     # {pid: set(keyword)}
    self_covered_by_pid: dict = {} # {pid: set(keyword)}
    for c in cand_rows:
        self_kws_by_pid.setdefault(c.product_id, set()).add(c.keyword)
        if c.is_covered:
            self_covered_by_pid.setdefault(c.product_id, set()).add(c.keyword)

    # ---------- SQL 3: 跨店本类目热门 Top 30 (按 type_id 聚合, 跨店共享) ----------
    type_ids = {str(r.type_id) for r in rows if r.type_id}
    cat_top_by_type: dict = {}     # {type_id_str: set(keyword)}
    if type_ids:
        agg_stmt = text("""
            SELECT pl.platform_category_extra_id AS type_id, c.keyword,
                   SUM(COALESCE(c.organic_orders,0)+COALESCE(c.paid_orders,0)) AS total_orders,
                   SUM(COALESCE(c.organic_impressions,0)) AS total_imps,
                   MAX(c.score) AS max_score
            FROM seo_keyword_candidates c
            JOIN platform_listings pl
              ON pl.product_id=c.product_id AND pl.tenant_id=c.tenant_id
              AND pl.shop_id=c.shop_id AND pl.status NOT IN ('deleted','archived')
            WHERE c.tenant_id=:tid AND c.status='pending'
              AND pl.platform_category_extra_id IN :tids
            GROUP BY pl.platform_category_extra_id, c.keyword
            HAVING total_orders > 0 OR total_imps >= 10
        """).bindparams(bindparam("tids", expanding=True))
        agg_rows = db.execute(agg_stmt, {"tid": tenant_id, "tids": list(type_ids)}).fetchall()
        # Python 分组排序取 Top 30
        tmp: dict = {}
        for x in agg_rows:
            tmp.setdefault(str(x.type_id), []).append((
                x.keyword, int(x.total_orders or 0), int(x.total_imps or 0), float(x.max_score or 0),
            ))
        for tid, kws in tmp.items():
            kws.sort(key=lambda k: (k[1], k[2], k[3]), reverse=True)
            cat_top_by_type[tid] = {kw[0] for kw in kws[:30]}

    # ---------- 过滤关键词（Python 层，商品量少）----------
    # 支持搜：商品中文名 / 俄语标题 / 本地编码 sku（用户输 QQ-B0062 类编码也能匹配）
    if keyword and keyword.strip():
        kw_low = keyword.strip().lower()
        rows = [r for r in rows
                if (r.name_zh or "").lower().find(kw_low) >= 0
                or (r.title_ru or "").lower().find(kw_low) >= 0
                or (r.sku or "").lower().find(kw_low) >= 0]

    # ---------- Python 算分 ----------
    import json as _json
    items = []
    totals = {"poor": 0, "fair": 0, "good": 0, "sum_score": 0.0}
    for r in rows:
        # 1. 本商品候选词集合
        self_kws = self_kws_by_pid.get(r.pid, set())
        self_covered = self_covered_by_pid.get(r.pid, set())

        # 2. 跨店本类目 Top 30
        cat_top = cat_top_by_type.get(str(r.type_id), set()) if r.type_id else set()

        # 3. 类目热门词在本商品 title/attrs 字符串里出现的, 算 covered
        title_low = (r.title_ru or "").lower()
        attrs_low = ""
        if r.variant_attrs:
            try:
                va = r.variant_attrs if isinstance(r.variant_attrs, (list, dict)) else _json.loads(r.variant_attrs)
                attrs_low = _json.dumps(va, ensure_ascii=False).lower()
            except (TypeError, ValueError):
                attrs_low = str(r.variant_attrs).lower()
        cat_in_text = {kw for kw in cat_top if kw.lower() in title_low or kw.lower() in attrs_low}

        # 4. 评分只用 self,类目热门作 reference (不进 total 不扣分)
        cov_score, cov_detail = _score_coverage(
            self_total=len(self_kws),
            self_covered=len(self_covered),
            cat_total=len(cat_top),
            cat_covered=len(cat_in_text),
        )
        # 兼容字段(旧前端展示用):
        total_cand = len(self_kws)
        covered = len(self_covered)
        tit_score, tit_detail = _score_title_length(r.title_ru)
        desc_score, desc_detail = _score_description_length(r.description_ru)

        dims_for_final = [
            {"score": cov_score, **cov_detail},
            {"score": tit_score, **tit_detail},
            {"score": desc_score, **desc_detail},
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
            "current_description": r.description_ru or "",
            "rating": float(r.rating) if r.rating is not None else None,
            "review_count": int(r.review_count or 0),
            "candidate_count": total_cand,
            "covered_count": covered,
            "score": total_score,
            "grade": grade,
            "dimensions": {
                "coverage": {"score": cov_score, **cov_detail},
                "title_length": {"score": tit_score, **tit_detail},
                "description_length": {"score": desc_score, **desc_detail},
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

            # metric 文案统一规则: "搜:N · 曝:M [· 订单:K]"
            # 跨店词前缀来源店名"<店名> 搜:N · 曝:M"
            # 数字优先从 sources entry 拿 (新逻辑),fallback 顶层字段 (兼容旧候选词)
            metric = None
            organic_self_entry = next(
                (s for s in srcs if s.get("type") == "organic" and s.get("scope") == "self"),
                None,
            )
            if source_type == "cross_shop" and cross_entry:
                shop_name = cross_entry.get("source_shop_name") or "其他店"
                freq = int(cross_entry.get("frequency") or 0)
                imps = int(cross_entry.get("impressions") or 0)
                orders = int(cross_entry.get("orders") or 0)
                parts = [f"搜:{freq}", f"曝:{imps}"]
                if orders > 0:
                    parts.append(f"订单:{orders}")
                metric = f"{shop_name} " + " · ".join(parts)
            elif source_type == "organic" and organic_self_entry:
                freq = int(organic_self_entry.get("frequency") or 0)
                imps = int(organic_self_entry.get("impressions") or 0)
                orders = int(organic_self_entry.get("orders") or mr.organic_orders or 0)
                parts = [f"搜:{freq}", f"曝:{imps}"]
                if orders > 0:
                    parts.append(f"订单:{orders}")
                metric = " · ".join(parts)
            elif mr.organic_impressions or mr.organic_orders:
                # 兼容旧候选词 (sources entry 没附数字),只能取顶层
                parts = [f"曝:{int(mr.organic_impressions or 0)}"]
                if mr.organic_orders:
                    parts.append(f"订单:{mr.organic_orders}")
                metric = " · ".join(parts)
            elif mr.paid_orders:
                metric = f"付费订单 {mr.paid_orders}"
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

    # ---------- SQL 3: 当前页商品的自然流量聚合（来自 product_search_queries）----------
    # 数据源：WB Jam 订阅 / Ozon Premium 订阅。窗口固定近 30 天。
    # 没订阅或还没同步的店该表为空，items 自然流量字段全 None。
    if page_pids:
        organic_stmt = text("""
            SELECT product_id,
                   COUNT(DISTINCT query_text) AS keyword_count,
                   SUM(frequency)             AS searches,
                   SUM(impressions)           AS views,
                   SUM(clicks)                AS clicks,
                   SUM(add_to_cart)           AS atc,
                   SUM(orders)                AS orders,
                   SUM(revenue)               AS revenue
            FROM product_search_queries
            WHERE tenant_id = :tid
              AND shop_id = :sid
              AND product_id IN :pids
              AND stat_date >= CURDATE() - INTERVAL 30 DAY
            GROUP BY product_id
        """).bindparams(bindparam("pids", expanding=True))
        organic_rows = db.execute(organic_stmt, {
            "tid": tenant_id, "sid": shop_id, "pids": page_pids,
        }).fetchall()
        organic_by_pid = {r.product_id: r for r in organic_rows}

        for item in page_items:
            o = organic_by_pid.get(item["product_id"])
            item["organic_traffic"] = {
                "keyword_count": int(o.keyword_count or 0) if o else 0,
                "searches":      int(o.searches or 0)      if o else 0,
                "views":         int(o.views or 0)         if o else 0,
                "clicks":        int(o.clicks or 0)        if o else 0,
                "atc":           int(o.atc or 0)           if o else 0,
                "orders":        int(o.orders or 0)        if o else 0,
                "revenue":       float(o.revenue or 0)     if o else 0.0,
                "has_data":      o is not None,
            }
    else:
        for item in page_items:
            item["organic_traffic"] = None

    # ---------- SQL 4: 自然流量数据源时间窗口（店级）----------
    # 数据为什么必须告诉用户范围：Ozon Premium 普通版只能看 30 天但 1-2 天前
    # 有保护期；Premium Plus 全 30 天；订阅刚开通的店可能只有几天数据；
    # WB Jam 订阅状态多样。前端必须显示真实窗口避免误导用户。
    range_row = db.execute(text("""
        SELECT MIN(stat_date)             AS earliest,
               MAX(stat_date)             AS latest,
               COUNT(DISTINCT stat_date)  AS days_with_data,
               COUNT(*)                   AS total_rows
        FROM product_search_queries
        WHERE tenant_id = :tid AND shop_id = :sid
          AND stat_date >= CURDATE() - INTERVAL 30 DAY
    """), {"tid": tenant_id, "sid": shop_id}).first()

    organic_data_range = {
        "earliest": range_row.earliest.isoformat() if range_row and range_row.earliest else None,
        "latest":   range_row.latest.isoformat()   if range_row and range_row.latest   else None,
        "days_with_data": int(range_row.days_with_data or 0) if range_row else 0,
        "window_days": 30,
        "total_rows":  int(range_row.total_rows or 0) if range_row else 0,
        "has_data":    bool(range_row and range_row.total_rows and range_row.total_rows > 0),
    }

    # ---------- 汇总 ----------
    n_all = len(rows)
    avg_score = round(totals["sum_score"] / n_all, 1) if n_all else 0.0

    return {
        "code": ErrorCode.SUCCESS,
        "data": {
            "organic_data_range": organic_data_range,
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
        organic_self_entry = next(
            (s for s in srcs if s.get("type") == "organic" and s.get("scope") == "self"),
            None,
        )

        if has_paid:
            source_type = "paid"
        elif has_organic:
            source_type = "organic"
        elif cross_entry:
            source_type = "cross_shop"
        else:
            source_type = "unknown"

        # 本店 organic 的搜索量/曝光/订单/加购:
        # 优先从 sources entry 取(新逻辑分别存了 frequency 和 impressions),
        # fallback 顶层字段(兼容旧候选词,只有 organic_impressions 顶层)
        org_freq = (
            int(organic_self_entry.get("frequency") or 0) if organic_self_entry
            else None
        )
        org_imps = (
            int(organic_self_entry.get("impressions") or 0) if organic_self_entry
            else (int(r.organic_impressions) if r.organic_impressions is not None else None)
        )

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
            "organic_frequency": org_freq,        # 本店搜索量(新增,旧候选 None)
            "organic_impressions": org_imps,      # 本店曝光
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
