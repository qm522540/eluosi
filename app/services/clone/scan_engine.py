"""店铺克隆扫描引擎 — _run_scan 核心

详细规范: docs/api/store_clone.md §4.1

流程:
1. factory.get_provider 拿 B 店 Provider
2. since = task.last_check_at or (task.created_at - 7 days)
3. provider.list_products 分页拉
4. 对每个 snapshot: 查重 → 类目映射 → 价格规则 → 创建草稿 product+listing →
   下载图片 → 暂存 source 原文 (AI 延后)
5. AI 改写批处理 (sem=5 + 失败 fallback)
6. 写 clone_logs (含 skipped_skus 明细)
7. 更新 task.last_*

强制约定 (规范 §11):
- providers 走 *Client 不绕路
- AI 改写复用 SEO 接口 (optimize_title / generate_description), 不重复实现
"""

import asyncio
import json
import uuid
from dataclasses import asdict
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Optional

from sqlalchemy.orm import Session

from app.models.clone import CloneTask, ClonePendingProduct, CloneLog
from app.models.product import Product, PlatformListing
from app.models.shop import Shop
from app.models.category import CategoryPlatformMapping
from app.utils.logger import setup_logger
from app.utils.moscow_time import utc_now_naive

from .providers import get_provider, ProductSnapshot

logger = setup_logger("clone.scan_engine")

DEFAULT_FIRST_SCAN_WINDOW_DAYS = 7
LIST_PAGE_SIZE = 100
AI_REWRITE_SEMAPHORE = 5


# ==================== SKU 后缀对比 (老板拍) ====================

def _sku_suffix(sku: str) -> str:
    """提取 SKU 后缀用于跨平台冲突检测.

    老板举例: WB-E0022 / OZ-E0022 / SS-E0022 都视为同一商品的不同平台版本.
    rsplit('-', 1) — 多 '-' 取最后一段; 无 '-' 的整体作后缀.
    """
    if not sku:
        return ""
    return sku.rsplit("-", 1)[-1].strip()

# 11.2 优化: scan-preview 把拉到的候选 snapshot 缓存到 Redis,
# scan-now / 后续 preview 命中缓存可跳过整段 list_products 分页(28~30 秒 → 1 秒级).
# TTL 老板拍 15 分钟 — 同 task 反复操作期内秒回, 过期后才重新拉 API
PREVIEW_CACHE_TTL = 900  # 15 分钟


# ==================== 11.2 Preview 快照缓存 ====================

def _preview_cache_key(tenant_id: int, task_id: int) -> str:
    return f"clone:preview:{tenant_id}:{task_id}"


def _snapshot_to_jsonable(snap: ProductSnapshot) -> dict:
    """ProductSnapshot dataclass → JSON 可序列化 dict.

    Decimal → str (反序列化时还原为 Decimal); datetime → isoformat;
    raw 字段直接透传(provider 已保证是 dict).
    新加 barcode/dimensions/weight (老板 2026-05-03 报 BUG) 通过 asdict() 自然带上.
    """
    d = asdict(snap)
    d["price_rub"] = str(snap.price_rub)
    d["old_price_rub"] = str(snap.old_price_rub) if snap.old_price_rub is not None else None
    d["detected_at"] = snap.detected_at.isoformat() if snap.detected_at else None
    return d


def _jsonable_to_snapshot(d: dict) -> ProductSnapshot:
    """反序列化, 跟 _snapshot_to_jsonable 对称."""
    detected = d.get("detected_at")
    if isinstance(detected, str):
        try:
            detected = datetime.fromisoformat(detected)
        except Exception:
            detected = None
    old_p = d.get("old_price_rub")
    return ProductSnapshot(
        source_platform=d.get("source_platform", ""),
        source_sku_id=d.get("source_sku_id", ""),
        title_ru=d.get("title_ru", ""),
        description_ru=d.get("description_ru", ""),
        price_rub=Decimal(str(d.get("price_rub") or "0")),
        old_price_rub=Decimal(str(old_p)) if old_p not in (None, "", "0", 0) else None,
        stock=int(d.get("stock") or 0),
        images=list(d.get("images") or []),
        platform_category_id=d.get("platform_category_id") or "",
        platform_category_name=d.get("platform_category_name") or "",
        type_id=d.get("type_id") or "",
        attributes=list(d.get("attributes") or []),
        barcode=d.get("barcode") or "",
        depth_mm=int(d.get("depth_mm") or 0),
        width_mm=int(d.get("width_mm") or 0),
        height_mm=int(d.get("height_mm") or 0),
        weight_g=int(d.get("weight_g") or 0),
        videos=list(d.get("videos") or []),
        video_cover=d.get("video_cover") or "",
        raw=d.get("raw") or {},
        detected_at=detected,
    )


def _save_preview_cache(tenant_id: int, task_id: int,
                        snapshots: list[ProductSnapshot]) -> None:
    """把 preview 拉到的全量候选 snapshot 存 Redis (key=tenant+task, TTL=5min).

    存 dict[source_sku_id → snapshot_dict] 方便 scan-now 按 SKU O(1) 取.
    Redis 故障时 try/except 吞掉 — 缓存失败不阻断 preview 业务.
    """
    if not snapshots:
        return
    try:
        from app.services.platform.wb import _get_redis_client
        r = _get_redis_client()
        payload = {snap.source_sku_id: _snapshot_to_jsonable(snap) for snap in snapshots}
        r.setex(
            _preview_cache_key(tenant_id, task_id),
            PREVIEW_CACHE_TTL,
            json.dumps(payload, ensure_ascii=False),
        )
        logger.info(
            f"_save_preview_cache task={task_id} cached {len(payload)} snapshots, "
            f"TTL={PREVIEW_CACHE_TTL}s"
        )
    except Exception as e:
        logger.warning(f"_save_preview_cache 写 Redis 失败 task={task_id}: {e}")


def _load_all_cached_snapshots(tenant_id: int, task_id: int) -> Optional[tuple[list[ProductSnapshot], int]]:
    """取 preview 缓存的全部候选 snapshot, 给 _scan_preview 自身复用.

    Returns:
        - (snapshots, cached_age_seconds) 命中时
        - None 缓存不存在或读 Redis 失败

    跟 _load_preview_cache 区别: 这个不按 selected_skus 过滤, 返回全部.
    """
    try:
        from app.services.platform.wb import _get_redis_client
        r = _get_redis_client()
        key = _preview_cache_key(tenant_id, task_id)
        raw = r.get(key)
        if not raw:
            return None
        ttl = r.ttl(key)
        age = max(0, PREVIEW_CACHE_TTL - (ttl if ttl and ttl > 0 else 0))
        payload = json.loads(raw)
        snaps = [_jsonable_to_snapshot(d) for d in payload.values()]
        logger.info(
            f"_load_all_cached_snapshots task={task_id} 命中 {len(snaps)} 件 "
            f"(缓存年龄 {age}s)"
        )
        return snaps, age
    except Exception as e:
        logger.warning(f"_load_all_cached_snapshots 读 Redis 失败 task={task_id}: {e}")
        return None


def _load_preview_cache(tenant_id: int, task_id: int,
                        selected_skus: set) -> Optional[list[ProductSnapshot]]:
    """取 preview 缓存中 selected_skus 对应的 snapshot list.

    Returns:
        - 命中且全部 SKU 都在缓存里 → list[ProductSnapshot]
        - 缓存不存在 / 任一 SKU 缺失 → None (调用方降级 list_products)

    全或无策略: 如果用户勾的 SKU 有任何一个不在缓存(可能是 5 分钟外或缓存被
    其它操作覆盖), 整体降级现拉, 避免拼接半套数据.
    """
    if not selected_skus:
        return None
    try:
        from app.services.platform.wb import _get_redis_client
        r = _get_redis_client()
        raw = r.get(_preview_cache_key(tenant_id, task_id))
        if not raw:
            return None
        payload = json.loads(raw)
        snaps = []
        for sku in selected_skus:
            d = payload.get(sku)
            if d is None:
                logger.info(
                    f"_load_preview_cache task={task_id} sku={sku} 缓存缺失, 降级现拉"
                )
                return None
            snaps.append(_jsonable_to_snapshot(d))
        logger.info(
            f"_load_preview_cache task={task_id} 命中 {len(snaps)}/{len(selected_skus)} 件"
        )
        return snaps
    except Exception as e:
        logger.warning(f"_load_preview_cache 读 Redis 失败 task={task_id}: {e}")
        return None


# ==================== 类目映射 ====================

def _resolve_target_category(
    db: Session, tenant_id: int,
    source_platform: str, source_cat_id: str,
    target_platform: str, strategy: str,
) -> tuple[Optional[str], str]:
    """跨平台/同平台类目映射

    Returns: (target_platform_category_id, mapping_status)
        mapping_status: 'ok' / 'missing'
    """
    # 同平台直接复用
    if source_platform == target_platform:
        return source_cat_id, "ok"

    if not source_cat_id:
        return None, "missing"

    # 跨平台 use_local_map / reject_if_missing 都走 028 反查
    # 步骤 1: source_cat_id → local_category_id
    src_mapping = db.query(CategoryPlatformMapping).filter(
        CategoryPlatformMapping.tenant_id == tenant_id,
        CategoryPlatformMapping.platform == source_platform,
        CategoryPlatformMapping.platform_category_id == source_cat_id,
    ).first()
    if not src_mapping:
        return None, "missing"

    # 步骤 2: local_category_id → target_platform_category_id
    tgt_mapping = db.query(CategoryPlatformMapping).filter(
        CategoryPlatformMapping.tenant_id == tenant_id,
        CategoryPlatformMapping.local_category_id == src_mapping.local_category_id,
        CategoryPlatformMapping.platform == target_platform,
    ).first()
    if not tgt_mapping:
        return None, "missing"

    return str(tgt_mapping.platform_category_id), "ok"


# ==================== 价格规则 ====================

def _apply_price_rule(source_price: Decimal, mode: str,
                      adjust_pct: Optional[Decimal]) -> Decimal:
    """同价 / 涨跌 % 规则"""
    if mode == "same" or not adjust_pct:
        return source_price
    factor = Decimal("1") + Decimal(str(adjust_pct)) / Decimal("100")
    return (source_price * factor).quantize(Decimal("0.01"))


# ==================== 草稿创建 ====================

def _create_drafts(
    db: Session, task: CloneTask, snap: ProductSnapshot,
    target_cat_id: str,
) -> tuple[Optional[int], Optional[int], Optional[str]]:
    """新建占位 products + platform_listings 草稿 (规范 §3.3 状态机)

    Returns: (product_id, listing_id, error_msg) — 失败返 (None, None, "...")

    用 savepoint 包裹: 单 SKU 失败只回滚自己, 不污染同页其他草稿
    (避免历史教训: ORM 字段缺失时 product 已 flush 但 listing 抛错,
     外层 commit 把孤儿 product 一并写库)。
    """
    sp = db.begin_nested()
    try:
        sku_placeholder = f"clone-pending-{task.id}-{snap.source_sku_id}"
        product = Product(
            tenant_id=task.tenant_id,
            shop_id=task.target_shop_id,
            sku=sku_placeholder,
            name_zh=(snap.title_ru or "")[:200],
            name_ru=snap.title_ru or "",
            brand=None,
            local_category_id=None,  # scan_engine 不强行回填; 用户在映射管理统一处理
            status="inactive",
            created_at=utc_now_naive(),
        )
        db.add(product)
        db.flush()

        # 推断 target_platform
        target_shop = db.query(Shop).filter(Shop.id == task.target_shop_id).first()
        target_platform = target_shop.platform if target_shop else snap.source_platform

        # platform_product_id / platform_sku_id 在草稿期都用占位串
        # publish 成功后由 publish_engine 回填真实 offer_id
        draft_token = uuid.uuid4().hex[:8]
        listing = PlatformListing(
            tenant_id=task.tenant_id,
            shop_id=task.target_shop_id,
            product_id=product.id,
            platform=target_platform,
            platform_sku_id=f"clone-draft-{draft_token}",
            platform_product_id=f"clone-draft-{draft_token}",
            title_ru=snap.title_ru,
            description_ru=snap.description_ru,
            platform_category_id=target_cat_id or None,
            status="inactive",
            publish_status="draft",
            clone_task_id=task.id,
            created_at=utc_now_naive(),
        )
        db.add(listing)
        db.flush()
        sp.commit()
        return product.id, listing.id, None
    except Exception as e:
        sp.rollback()
        msg = str(e)[:200]
        logger.error(f"_create_drafts 失败 task={task.id} sku={snap.source_sku_id}: {e}")
        return None, None, msg


# ==================== 图片处理 ====================
#
# 草稿期不下载图片到 OSS, 只暂存 B 店原图 URL。
# OSS 下载延后到 _publish_pending(publish_engine) 执行。
#
# 原因:
# - 串行下图 25 秒/SKU × 385 件 = 2.5h, 同步触发 scan-now 必撞 nginx 60s timeout
# - 被拒的商品下载也是浪费 OSS 流量
# - review 阶段用 B 店原图预览完全可用 (审核期内 B 店改图/删图是小概率)
#
# proposed_payload.images_oss 字段语义:
#   草稿期 = B 店原图 URL 列表
#   publish 后 = OSS URL 列表 (publish_engine 在 dispatch 前下载并写回)


# ==================== AI 改写批处理 ====================

async def _ai_rewrite_one(
    db: Session, tenant_id: int, listing_id: int,
    target_platform: str,
    title_mode: str, desc_mode: str,
    proposed: dict,
):
    """单条 AI 改写, sem 外层控制并发"""
    from app.services.product.service import optimize_title, generate_description

    if title_mode == "ai_rewrite":
        try:
            r = await optimize_title(db, listing_id, tenant_id)
            if r and r.get("code") == 0:
                # optimize_title 返 data.suggestions (3 候选, 按"①高流量词堆叠 ②自然语感
                # ③差异化卖点" 排序). 自动克隆场景取第 1 个 — SEO 流量优先.
                # (老板 2026-05-04 拍方案 A; 之前取 .new_title 是 BUG, 永远 None 标题不换)
                suggestions = (r.get("data") or {}).get("suggestions") or []
                new_title = suggestions[0] if suggestions else None
                if new_title:
                    proposed["title_ru"] = new_title
                else:
                    proposed["_ai_rewrite_failed_title"] = True
                    logger.warning(f"AI 标题改写返回空 suggestions listing={listing_id}")
            else:
                proposed["_ai_rewrite_failed_title"] = True
                logger.warning(f"AI 标题改写失败 listing={listing_id}: {r.get('msg') if r else 'none'}")
        except Exception as e:
            proposed["_ai_rewrite_failed_title"] = True
            proposed["_ai_rewrite_error"] = str(e)[:200]
            logger.error(f"AI 标题改写异常 listing={listing_id}: {e}")

    if desc_mode == "ai_rewrite":
        try:
            r = await generate_description(db, listing_id, tenant_id, target_platform)
            if r and r.get("code") == 0:
                new_desc = (r.get("data") or {}).get("description")
                if new_desc:
                    proposed["description_ru"] = new_desc
            else:
                proposed["_ai_rewrite_failed_desc"] = True
                logger.warning(f"AI 描述改写失败 listing={listing_id}: {r.get('msg') if r else 'none'}")
        except Exception as e:
            proposed["_ai_rewrite_failed_desc"] = True
            proposed["_ai_rewrite_error"] = str(e)[:200]
            logger.error(f"AI 描述改写异常 listing={listing_id}: {e}")


# ==================== 主入口 ====================

async def _run_scan(
    db: Session, task_id: int, tenant_id: int,
    selected_skus: Optional[set] = None,
    local_sku_overrides: Optional[dict] = None,
) -> dict:
    """扫描入口 — 同步触发 (scan-now) + Celery beat 共用

    Args:
        selected_skus: None = 全量立项 (兼容旧逻辑); set = 只立项指定的 source_sku_id
        local_sku_overrides: dict[source_sku_id → 自定义 A 店 SKU];
            None / 缺省 = A 店 SKU 跟 B 店 source_sku_id 一致 (老板"本地编码默认一样")

    Returns: {code, data: {found, new, skip_*, duration_ms, log_id}, msg?}
    """
    t0 = utc_now_naive()

    task = db.query(CloneTask).filter(
        CloneTask.id == task_id, CloneTask.tenant_id == tenant_id,
    ).first()
    if not task:
        from app.utils.errors import ErrorCode
        return {"code": ErrorCode.CLONE_TASK_NOT_FOUND, "msg": "克隆任务不存在"}

    source_shop = db.query(Shop).filter(Shop.id == task.source_shop_id).first()
    target_shop = db.query(Shop).filter(Shop.id == task.target_shop_id).first()
    if not source_shop or not target_shop:
        from app.utils.errors import ErrorCode
        return {"code": ErrorCode.CLONE_TASK_SOURCE_INVALID, "msg": "源/目标店铺已不存在"}

    target_platform = target_shop.platform
    source_platform = source_shop.platform

    # 计数器
    found = new = 0
    skip_published = skip_rejected = skip_pending = skip_category_missing = 0
    skip_a_shop_sku_exists = 0  # 11.1: A 店本地 SKU 已存在跳过
    skipped_skus: list[dict] = []
    ai_rewrite_targets: list[tuple[ClonePendingProduct, int, str, dict]] = []

    # 11.1 真 BUG 修复: 预拉 A 店所有真实 sku 集合 (排除占位 'clone-*')
    # 用于跨店去重 — 老板老板手工录的本地 sku, A 店已有就跳过
    a_existing_skus = set()
    rows = db.query(Product.sku).filter(
        Product.shop_id == task.target_shop_id,
        Product.tenant_id == tenant_id,
        Product.status != 'deleted',
        Product.sku.isnot(None),
    ).all()
    for (s,) in rows:
        if s and not s.startswith(('clone-pending-', 'clone-draft-')):
            a_existing_skus.add(s)
    logger.info(f"task={task_id} A 店预拉 {len(a_existing_skus)} 个真实 sku 用于跨店去重")

    # 老板拍 v2: 自动扫描分流 — 无冲突自动 approved + 触发 publish, 有冲突留 pending
    # 跟 _scan_preview 同步算 suffix → existing_sku 反向索引
    a_suffix_to_sku_run: dict[str, str] = {}
    for s in a_existing_skus:
        suf = _sku_suffix(s)
        if suf:
            a_suffix_to_sku_run.setdefault(suf, s)

    # 是否走"自动模式"分流: selected_skus is None 说明是 beat 调用 (无前端勾选)
    # 手动 scan-now 不分流, 仍写 pending 让用户决定
    auto_mode = selected_skus is None

    # 11.2 优化: scan-now 带 selected_skus 时优先吃 preview 缓存,
    # 命中可完全跳过 list_products 分页(原本固定耗时 ~28-30 秒)
    cache_snapshots: Optional[list[ProductSnapshot]] = None
    if selected_skus is not None:
        cache_snapshots = _load_preview_cache(tenant_id, task_id, selected_skus)

    # 拿 provider (规则: factory dispatch + *Client 不绕路)
    # 注: 缓存命中时也 init provider, 因为 _ai_rewrite_one 等下游可能用到; cheap.
    try:
        provider = get_provider(db, source_shop)
    except Exception as e:
        logger.error(f"get_provider 失败 task={task_id}: {e}")
        from app.utils.errors import ErrorCode
        task.last_error_msg = str(e)[:500]
        db.commit()
        return {"code": ErrorCode.CLONE_SOURCE_API_FAILED, "msg": str(e)[:200]}

    # 11.2 优化: 命中缓存走快速路径 — 直接处理勾选的 snapshot, 不分页
    # 未命中时走原 list_products 路径(全量分页 + selected_skus filter)
    fast_snapshots = cache_snapshots  # None = miss, list = hit

    # 分页 list_products (cache miss 时走这里)
    cursor: Optional[str] = None
    while True:
        if fast_snapshots is not None:
            # 缓存命中: 一次性塞所有命中的 snap, 跳出分页循环
            snapshots = fast_snapshots
            cursor = None
        else:
            try:
                snapshots, cursor = await provider.list_products(cursor=cursor, limit=LIST_PAGE_SIZE)
            except NotImplementedError as e:
                logger.warning(f"Provider 未实现 task={task_id}: {e}")
                from app.utils.errors import ErrorCode
                task.last_error_msg = str(e)[:500]
                db.commit()
                return {"code": ErrorCode.CLONE_SOURCE_API_FAILED, "msg": str(e)[:200]}
            except Exception as e:
                logger.error(f"list_products 失败 task={task_id}: {e}")
                from app.utils.errors import ErrorCode
                task.last_error_msg = str(e)[:500]
                db.commit()
                return {"code": ErrorCode.CLONE_SOURCE_API_FAILED, "msg": str(e)[:200]}

        if not snapshots:
            break

        for snap in snapshots:
            found += 1
            # 11.2: 用户在 preview 后没勾的 sku 直接跳过, 不立项也不计 skip
            if selected_skus is not None and snap.source_sku_id not in selected_skus:
                continue
            # a. 查重 (UNIQUE 约束 + 显式查避免 INSERT 抛异常)
            existing = db.query(ClonePendingProduct).filter(
                ClonePendingProduct.task_id == task_id,
                ClonePendingProduct.source_sku_id == snap.source_sku_id,
            ).first()
            if existing:
                if existing.status == "published":
                    skip_published += 1
                    skipped_skus.append({"sku": snap.source_sku_id, "reason": "published"})
                elif existing.status == "rejected":
                    skip_rejected += 1
                    skipped_skus.append({"sku": snap.source_sku_id, "reason": "rejected"})
                else:
                    skip_pending += 1
                    skipped_skus.append({"sku": snap.source_sku_id, "reason": "in_queue"})
                continue

            # a2. 11.1: 跨店本地 SKU 去重 — 反查 B 店 listing → product.sku, 看 A 店是否已有同 sku
            #     场景: 老板手工在 A 店建过该 sku, 不该重复立项 pending
            #     B 店 sku 不规则/为空时此层跳过, 走原 (task_id, source_sku_id) UNIQUE 兜底
            b_listing = db.query(PlatformListing).filter(
                PlatformListing.shop_id == task.source_shop_id,
                PlatformListing.tenant_id == tenant_id,
                PlatformListing.platform_sku_id == snap.source_sku_id,
                PlatformListing.status != 'deleted',
            ).first()
            b_local_sku = None
            if b_listing and b_listing.product_id:
                b_product = db.query(Product).filter(
                    Product.id == b_listing.product_id,
                    Product.tenant_id == tenant_id,
                ).first()
                if b_product and b_product.sku and not b_product.sku.startswith(('clone-pending-', 'clone-draft-')):
                    b_local_sku = b_product.sku
            if b_local_sku and b_local_sku in a_existing_skus:
                skip_a_shop_sku_exists += 1
                skipped_skus.append({
                    "sku": snap.source_sku_id, "reason": "a_shop_sku_exists",
                    "detail": f"A 店已有本地 sku={b_local_sku}",
                })
                continue

            # b. 类目映射
            target_cat_id, mapping_status = _resolve_target_category(
                db, tenant_id,
                source_platform, snap.platform_category_id,
                target_platform, task.category_strategy,
            )
            if mapping_status == "missing" and task.category_strategy in ("use_local_map", "reject_if_missing"):
                skip_category_missing += 1
                skipped_skus.append({
                    "sku": snap.source_sku_id, "reason": "category_missing",
                    "detail": f"{source_platform} cat={snap.platform_category_id} 未映射到 {target_platform}",
                })
                continue

            # c. 价格规则
            target_price = _apply_price_rule(
                snap.price_rub, task.price_mode, task.price_adjust_pct,
            )

            # d/e. 创建草稿 product + listing
            draft_product_id, draft_listing_id, draft_err = _create_drafts(
                db, task, snap, target_cat_id or "",
            )
            if not draft_listing_id:
                skipped_skus.append({
                    "sku": snap.source_sku_id, "reason": "draft_create_failed",
                    "detail": draft_err or "",
                })
                continue

            # f. 草稿期不下载图片到 OSS, 只暂存 B 店原图 URL
            #    OSS 下载延后到 publish_engine._publish_pending 执行
            oss_urls = list(snap.images or [])

            # g. 老板拍: 用户在 preview 行可改"本地 SKU"; 默认 = source_sku_id
            target_sku = (
                (local_sku_overrides or {}).get(snap.source_sku_id)
                or snap.source_sku_id
            ).strip() or snap.source_sku_id

            # g2. B 店折扣识别 (跟 product/service.py:920-921 一致):
            # has_discount = old_price 存在且 != price → A 店平台价 = old_price (× adjust),
            # 折扣价 = price (× adjust); 否则平台价 = price (× adjust), 折扣价 None
            b_old = snap.old_price_rub
            has_b_discount = (
                b_old is not None and b_old > 0
                and snap.price_rub > 0 and b_old != snap.price_rub
            )
            if has_b_discount:
                a_platform_price = _apply_price_rule(b_old, task.price_mode, task.price_adjust_pct)
                a_discount_price = _apply_price_rule(snap.price_rub, task.price_mode, task.price_adjust_pct)
            else:
                a_platform_price = target_price  # 已在前面调用过 _apply_price_rule(snap.price_rub, ...)
                a_discount_price = None

            # h. proposed_payload 骨架 (AI 改写延后)
            proposed = {
                "title_ru": snap.title_ru,
                "description_ru": snap.description_ru,
                "price_rub": float(a_platform_price),
                "discount_price_rub": float(a_discount_price) if a_discount_price else None,
                "stock": task.default_stock,
                "images_oss": oss_urls,
                "platform_category_id": target_cat_id or "",
                "platform_category_name": snap.platform_category_name,
                "type_id": snap.type_id,  # Ozon /v3/product/import 必填
                "attributes": snap.attributes,
                # publish_engine 优先用这个作 A 店 offer_id; 缺省回退 source_sku_id
                "target_sku": target_sku,
                # 物流字段 (修 BUG 1, 2 — 之前 publish 时全是占位)
                "barcode": snap.barcode,
                "depth_mm": snap.depth_mm,
                "width_mm": snap.width_mm,
                "height_mm": snap.height_mm,
                "weight_g": snap.weight_g,
                # 视频 (BUG 7) — 暂存; publish 后接力 pictures/import 上传
                "videos": list(snap.videos or []),
                "video_cover": snap.video_cover,
            }

            # h. 老板拍 v2: 自动模式 + 无后缀冲突 → status='approved' 自动发布;
            # 自动模式 + 有冲突 / 手动模式 → status='pending' 留人工确认.
            run_suffix = _sku_suffix(snap.source_sku_id)
            run_collision = a_suffix_to_sku_run.get(run_suffix) if run_suffix else None
            initial_status = "pending"
            if auto_mode and not run_collision:
                initial_status = "approved"

            # i. INSERT pending
            try:
                pending = ClonePendingProduct(
                    tenant_id=tenant_id,
                    task_id=task.id,
                    source_shop_id=task.source_shop_id,
                    source_platform=snap.source_platform,
                    source_sku_id=snap.source_sku_id,
                    source_snapshot={
                        "platform": snap.source_platform,
                        "sku_id": snap.source_sku_id,
                        "title_ru": snap.title_ru,
                        "description_ru": snap.description_ru,
                        "price_rub": float(snap.price_rub),
                        "old_price_rub": float(snap.old_price_rub) if snap.old_price_rub else None,
                        "stock": snap.stock,
                        "images": snap.images,
                        "platform_category_id": snap.platform_category_id,
                        "platform_category_name": snap.platform_category_name,
                        "type_id": snap.type_id,  # Ozon /v3/product/import 必填
                        "attributes": snap.attributes,
                        # 留痕给前端展示 + 调试
                        "suffix_collision": bool(run_collision),
                        "collision_with_sku": run_collision or "",
                    },
                    proposed_payload=proposed,
                    draft_listing_id=draft_listing_id,
                    status=initial_status,
                    category_mapping_status=mapping_status,
                    detected_at=utc_now_naive(),
                    reviewed_at=utc_now_naive() if initial_status == "approved" else None,
                )
                db.add(pending)
                db.flush()
                new += 1

                # j. 收集 AI 候选
                if task.title_mode == "ai_rewrite" or task.desc_mode == "ai_rewrite":
                    ai_rewrite_targets.append((pending, draft_listing_id, target_platform, proposed))
            except Exception as e:
                logger.error(
                    f"INSERT pending 失败 task={task.id} sku={snap.source_sku_id}: {e}"
                )
                skipped_skus.append({"sku": snap.source_sku_id, "reason": "insert_failed",
                                     "detail": str(e)[:120]})

        db.commit()
        if not cursor:
            break

    # 老板拍 v2: 自动模式扫完后, 如有自动 approved 的, 触发一次 Celery 立即上架
    # (publish-pending beat 兜底也会跑, 但触发一次能秒级开始)
    if auto_mode:
        from sqlalchemy import func as sa_func
        approved_now = db.query(sa_func.count(ClonePendingProduct.id)).filter(
            ClonePendingProduct.task_id == task.id,
            ClonePendingProduct.status == "approved",
        ).scalar() or 0
        if approved_now > 0:
            try:
                from app.tasks.clone_tasks import publish_approved_pending
                publish_approved_pending.delay()
                logger.info(f"task={task.id} 自动模式扫完 approved={approved_now}, 已触发 publish")
            except Exception as e:
                logger.warning(f"task={task.id} 自动模式 publish 触发失败: {e}, 等 beat 兜底")

    # 5. AI 改写批处理 (sem=5, 失败 fallback 不阻断)
    ai_rewrite_total = len(ai_rewrite_targets)
    ai_rewrite_failed = 0
    if ai_rewrite_targets:
        sem = asyncio.Semaphore(AI_REWRITE_SEMAPHORE)

        async def _wrap(p, lid, plat, prop):
            async with sem:
                await _ai_rewrite_one(
                    db, tenant_id, lid, plat,
                    task.title_mode, task.desc_mode, prop,
                )

        await asyncio.gather(
            *(_wrap(p, lid, plat, prop) for (p, lid, plat, prop) in ai_rewrite_targets),
            return_exceptions=True,
        )

        # 把改写后的 proposed 同步回 DB + listing
        for (pending, lid, _plat, prop) in ai_rewrite_targets:
            if prop.get("_ai_rewrite_failed_title") or prop.get("_ai_rewrite_failed_desc"):
                ai_rewrite_failed += 1
            pending.proposed_payload = prop
            listing = db.query(PlatformListing).filter(PlatformListing.id == lid).first()
            if listing:
                if "title_ru" in prop:
                    listing.title_ru = prop["title_ru"]
                if "description_ru" in prop:
                    listing.description_ru = prop["description_ru"]
        db.commit()

    # 6. 写日志 + 7. 更新 task
    duration_ms = int((utc_now_naive() - t0).total_seconds() * 1000)
    detail = {
        "found": found, "new": new,
        "skip_published": skip_published,
        "skip_rejected": skip_rejected,
        "skip_pending": skip_pending,
        "skip_category_missing": skip_category_missing,
        "skip_a_shop_sku_exists": skip_a_shop_sku_exists,  # 11.1
        "ai_rewrite_total": ai_rewrite_total,
        "ai_rewrite_failed": ai_rewrite_failed,
        "skipped_skus": skipped_skus[:200],  # 截断防 JSON 过大
    }
    log = CloneLog(
        tenant_id=tenant_id, task_id=task.id,
        log_type="scan",
        status="success" if new > 0 or found == 0 else (
            "partial" if skip_category_missing > 0 else "success"
        ),
        rows_affected=new,
        duration_ms=duration_ms,
        detail=detail,
    )
    db.add(log)

    task.last_check_at = utc_now_naive()
    task.last_found_count = found
    task.last_publish_count = new
    task.last_skip_count = (
        skip_published + skip_rejected + skip_category_missing
        + skip_pending + skip_a_shop_sku_exists
    )
    task.last_error_msg = None
    db.commit()
    db.refresh(log)

    return {"code": 0, "data": {
        "found": found, "new": new,
        "skip_published": skip_published,
        "skip_rejected": skip_rejected,
        "skip_pending": skip_pending,
        "skip_category_missing": skip_category_missing,
        "skip_a_shop_sku_exists": skip_a_shop_sku_exists,  # 11.1
        "ai_rewrite_total": ai_rewrite_total,
        "ai_rewrite_failed": ai_rewrite_failed,
        "duration_ms": duration_ms,
        "log_id": log.id,
    }}


# ==================== 11.2 干跑预览 ====================

async def _scan_preview(db: Session, task_id: int, tenant_id: int) -> dict:
    """干跑扫描 — 拉 B 店全量, 过滤后返候选清单, 不写库

    跟 _run_scan 共享同样的过滤逻辑 (同 task 去重 + 跨店 sku 去重 + 类目映射),
    但跳过 _create_drafts / INSERT pending / AI 改写 — 让用户预览后再确认.

    Returns: {code, data: {
        found, skip_*, candidates: [...], skipped_skus_sample: [...], duration_ms
    }}
    """
    t0 = utc_now_naive()

    task = db.query(CloneTask).filter(
        CloneTask.id == task_id, CloneTask.tenant_id == tenant_id,
    ).first()
    if not task:
        from app.utils.errors import ErrorCode
        return {"code": ErrorCode.CLONE_TASK_NOT_FOUND, "msg": "克隆任务不存在"}

    source_shop = db.query(Shop).filter(Shop.id == task.source_shop_id).first()
    target_shop = db.query(Shop).filter(Shop.id == task.target_shop_id).first()
    if not source_shop or not target_shop:
        from app.utils.errors import ErrorCode
        return {"code": ErrorCode.CLONE_TASK_SOURCE_INVALID, "msg": "源/目标店铺已不存在"}

    target_platform = target_shop.platform
    source_platform = source_shop.platform

    found = 0
    skip_published = skip_rejected = skip_pending = skip_category_missing = 0
    skip_a_shop_sku_exists = 0
    skipped_skus: list[dict] = []
    candidates: list[dict] = []
    # 11.2 优化: 收集候选 snapshot 完整体, 末尾批量 setex 给 scan-now 复用
    candidate_snapshots: list[ProductSnapshot] = []

    # 预拉 A 店真实 sku 集合
    a_existing_skus = set()
    rows = db.query(Product.sku).filter(
        Product.shop_id == task.target_shop_id,
        Product.tenant_id == tenant_id,
        Product.status != 'deleted',
        Product.sku.isnot(None),
    ).all()
    for (s,) in rows:
        if s and not s.startswith(('clone-pending-', 'clone-draft-')):
            a_existing_skus.add(s)

    # 老板拍: 后缀冲突检测 — A 店 WB-E0022 vs B 店 OZ-E0022 视为可能同款
    # 建 suffix → existing_sku 反向索引, 候选清单标红 + 默认不勾
    a_suffix_to_sku: dict[str, str] = {}
    for s in a_existing_skus:
        suf = _sku_suffix(s)
        if suf:
            a_suffix_to_sku.setdefault(suf, s)

    # 11.2 优化: 先查缓存, 命中则跳过整段 list_products (28~30 秒 → 1-3 秒)
    from_cache = False
    cache_age_seconds = 0
    cached_result = _load_all_cached_snapshots(tenant_id, task_id)
    if cached_result is not None:
        cached_snaps_list, cache_age_seconds = cached_result
        from_cache = True
    else:
        cached_snaps_list = None

    if not from_cache:
        try:
            provider = get_provider(db, source_shop)
        except Exception as e:
            logger.error(f"_scan_preview get_provider 失败 task={task_id}: {e}")
            from app.utils.errors import ErrorCode
            return {"code": ErrorCode.CLONE_SOURCE_API_FAILED, "msg": str(e)[:200]}

    cursor: Optional[str] = None
    while True:
        if from_cache:
            # 命中缓存: 一次性塞所有 snap, 跳出分页循环
            snapshots = cached_snaps_list
            cursor = None
        else:
            try:
                snapshots, cursor = await provider.list_products(cursor=cursor, limit=LIST_PAGE_SIZE)
            except NotImplementedError as e:
                from app.utils.errors import ErrorCode
                return {"code": ErrorCode.CLONE_SOURCE_API_FAILED, "msg": str(e)[:200]}
            except Exception as e:
                logger.error(f"_scan_preview list_products 失败 task={task_id}: {e}")
                from app.utils.errors import ErrorCode
                return {"code": ErrorCode.CLONE_SOURCE_API_FAILED, "msg": str(e)[:200]}

        if not snapshots:
            break

        for snap in snapshots:
            found += 1

            # 1. 同 task 去重
            existing = db.query(ClonePendingProduct).filter(
                ClonePendingProduct.task_id == task_id,
                ClonePendingProduct.source_sku_id == snap.source_sku_id,
            ).first()
            if existing:
                if existing.status == "published":
                    skip_published += 1
                    skipped_skus.append({"sku": snap.source_sku_id, "reason": "published"})
                elif existing.status == "rejected":
                    skip_rejected += 1
                    skipped_skus.append({"sku": snap.source_sku_id, "reason": "rejected"})
                else:
                    skip_pending += 1
                    skipped_skus.append({"sku": snap.source_sku_id, "reason": "in_queue"})
                continue

            # 2. 跨店本地 sku 去重 (11.1)
            b_listing = db.query(PlatformListing).filter(
                PlatformListing.shop_id == task.source_shop_id,
                PlatformListing.tenant_id == tenant_id,
                PlatformListing.platform_sku_id == snap.source_sku_id,
                PlatformListing.status != 'deleted',
            ).first()
            b_local_sku = None
            if b_listing and b_listing.product_id:
                b_product = db.query(Product).filter(
                    Product.id == b_listing.product_id,
                    Product.tenant_id == tenant_id,
                ).first()
                if b_product and b_product.sku and not b_product.sku.startswith(('clone-pending-', 'clone-draft-')):
                    b_local_sku = b_product.sku
            if b_local_sku and b_local_sku in a_existing_skus:
                skip_a_shop_sku_exists += 1
                skipped_skus.append({
                    "sku": snap.source_sku_id, "reason": "a_shop_sku_exists",
                    "detail": f"A 店已有本地 sku={b_local_sku}",
                })
                continue

            # 3. 类目映射
            target_cat_id, mapping_status = _resolve_target_category(
                db, tenant_id,
                source_platform, snap.platform_category_id,
                target_platform, task.category_strategy,
            )
            if mapping_status == "missing" and task.category_strategy in ("use_local_map", "reject_if_missing"):
                skip_category_missing += 1
                skipped_skus.append({
                    "sku": snap.source_sku_id, "reason": "category_missing",
                    "detail": f"{source_platform} cat={snap.platform_category_id} 未映射到 {target_platform}",
                })
                continue

            # 4. 价格规则
            target_price = _apply_price_rule(
                snap.price_rub, task.price_mode, task.price_adjust_pct,
            )

            # 5. 老板拍: 后缀冲突检测
            suffix = _sku_suffix(snap.source_sku_id)
            collision_with = a_suffix_to_sku.get(suffix) if suffix else None

            # 5b. B 店折扣识别 (跟 _run_scan 同步)
            b_old = snap.old_price_rub
            has_b_discount = (
                b_old is not None and b_old > 0
                and snap.price_rub > 0 and b_old != snap.price_rub
            )
            if has_b_discount:
                preview_a_platform = float(_apply_price_rule(b_old, task.price_mode, task.price_adjust_pct))
                preview_a_discount = float(_apply_price_rule(snap.price_rub, task.price_mode, task.price_adjust_pct))
            else:
                preview_a_platform = float(target_price)
                preview_a_discount = None

            # 6. 收集候选 (不写库)
            candidates.append({
                "source_sku_id": snap.source_sku_id,
                "title_ru": snap.title_ru,
                "description_ru": (snap.description_ru or "")[:300],
                "price_b": float(snap.price_rub),
                "old_price_b": float(b_old) if b_old else None,
                "price_a_proposed": preview_a_platform,
                "discount_price_a_proposed": preview_a_discount,
                "stock": snap.stock,
                "images": list(snap.images or [])[:5],  # 缩略图最多 5 张
                "category_status": mapping_status,
                "target_category_id": target_cat_id,
                "type_id": snap.type_id,
                "source_platform": snap.source_platform,
                "local_sku_b": b_local_sku,
                # 后缀冲突 — 前端标红 + 默认不勾
                "suffix_collision": bool(collision_with),
                "collision_with_sku": collision_with or "",
            })
            # 11.2 优化: 候选 snapshot 完整体存起来, 末尾批量给 Redis
            candidate_snapshots.append(snap)

        if not cursor:
            break

    # 11.2 优化: 现拉到的候选写 Redis 给 scan-now / 后续 preview 复用;
    # 命中缓存的本次 preview 不重写, 让原 TTL 倒计时正常推进
    if not from_cache:
        _save_preview_cache(tenant_id, task_id, candidate_snapshots)

    duration_ms = int((utc_now_naive() - t0).total_seconds() * 1000)
    return {"code": 0, "data": {
        "found": found,
        "skip_published": skip_published,
        "skip_rejected": skip_rejected,
        "skip_pending": skip_pending,
        "skip_category_missing": skip_category_missing,
        "skip_a_shop_sku_exists": skip_a_shop_sku_exists,
        "candidates": candidates,
        "skipped_skus_sample": skipped_skus[:50],
        "duration_ms": duration_ms,
        # 11.2 优化: 给前端展示"是否走缓存"
        "from_cache": from_cache,
        "cache_age_seconds": cache_age_seconds if from_cache else 0,
        "cache_ttl_seconds": PREVIEW_CACHE_TTL,
    }}
