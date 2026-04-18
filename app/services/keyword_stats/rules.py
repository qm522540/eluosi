"""关键词效能评级规则：默认值 + 读/写 + 分类器

业务上 5 档优先级：new → star → potential → waste → normal（命中即返，不会重复）。

- new 新词/观察中：曝光 < min_impressions（数据不足，所有指标都不可信，先观察）
- star 高效：CTR ≥ star_ctr_min 且 CPC ≤ 平均CPC × star_cpc_max_ratio
- potential 潜力：CTR ≥ potential_ctr_min 且 曝光 ≤ 平均曝光 × potential_impressions_max_ratio
- waste 浪费：CTR ≤ waste_ctr_max 且 花费 ≥ 平均花费 × waste_spend_min_ratio
- normal 普通：以上都不符合

"平均"指当前查询集全局平均（非历史），由 summary() 已算好传入。
"""
from typing import Optional
from sqlalchemy.orm import Session

from app.models.keyword_stat import KeywordEfficiencyRule


DEFAULT_RULES = {
    "min_impressions": 20,
    "star_ctr_min": 5.0,
    "star_cpc_max_ratio": 1.0,
    "potential_ctr_min": 3.0,
    "potential_impressions_max_ratio": 2.0,
    "waste_ctr_max": 1.0,
    "waste_spend_min_ratio": 1.0,
}

# Pydantic 校验用的字段范围（防用户输入离谱值）
FIELD_BOUNDS = {
    "min_impressions": (0, 1000000),
    "star_ctr_min": (0.0, 100.0),
    "star_cpc_max_ratio": (0.0, 10.0),
    "potential_ctr_min": (0.0, 100.0),
    "potential_impressions_max_ratio": (0.0, 10.0),
    "waste_ctr_max": (0.0, 100.0),
    "waste_spend_min_ratio": (0.0, 10.0),
}


def get_rules(db: Session, tenant_id: int) -> dict:
    """返回租户规则，无记录则返回 DEFAULT_RULES 的拷贝"""
    row = db.query(KeywordEfficiencyRule).filter(
        KeywordEfficiencyRule.tenant_id == tenant_id,
    ).first()
    if not row:
        return dict(DEFAULT_RULES)
    # 合并 default 以防历史记录缺字段（forward-compat）
    merged = dict(DEFAULT_RULES)
    if isinstance(row.rules_json, dict):
        merged.update(row.rules_json)
    return merged


def set_rules(db: Session, tenant_id: int, rules: dict) -> dict:
    """upsert 租户规则，返回最终写入内容"""
    # 只保留已知字段，丢弃多余 key 防污染
    clean = {k: rules[k] for k in DEFAULT_RULES if k in rules}
    # 用 DEFAULT 填补缺字段（PUT 必须整份提交，但容错）
    final = dict(DEFAULT_RULES)
    final.update(clean)

    row = db.query(KeywordEfficiencyRule).filter(
        KeywordEfficiencyRule.tenant_id == tenant_id,
    ).first()
    if row:
        row.rules_json = final
    else:
        row = KeywordEfficiencyRule(tenant_id=tenant_id, rules_json=final)
        db.add(row)
    db.commit()
    return final


def reset_rules(db: Session, tenant_id: int) -> dict:
    """删掉租户规则行 → 后续 get_rules 返回 DEFAULT_RULES"""
    db.query(KeywordEfficiencyRule).filter(
        KeywordEfficiencyRule.tenant_id == tenant_id,
    ).delete()
    db.commit()
    return dict(DEFAULT_RULES)


def classify(
    ctr: float, cpc: float, impressions: int, spend: float,
    avg_cpc: float, avg_impressions: float, avg_spend: float,
    rules: Optional[dict] = None,
) -> str:
    """返回 "new" | "star" | "potential" | "waste" | "normal"

    avg_* 传 0 表示数据集为空，阈值比较降级（不触发依赖平均的分支）
    """
    r = rules or DEFAULT_RULES
    # new: 曝光不足，数据不可信，先观察
    if impressions < r.get("min_impressions", DEFAULT_RULES["min_impressions"]):
        return "new"
    # star: 高效
    if ctr >= r["star_ctr_min"] and (
        avg_cpc <= 0 or cpc <= avg_cpc * r["star_cpc_max_ratio"]
    ):
        return "star"
    # potential: 潜力
    if ctr >= r["potential_ctr_min"] and (
        avg_impressions <= 0 or impressions <= avg_impressions * r["potential_impressions_max_ratio"]
    ):
        return "potential"
    # waste: 浪费
    if ctr <= r["waste_ctr_max"] and (
        avg_spend > 0 and spend >= avg_spend * r["waste_spend_min_ratio"]
    ):
        return "waste"
    return "normal"
