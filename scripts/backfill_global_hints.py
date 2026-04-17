"""一次性回填 global_*_hints：从现有 is_confirmed=1 的映射灌种子数据

使用：
    ssh ... "cd /data/ecommerce-ai && source venv/bin/activate && python scripts/backfill_global_hints.py"

幂等性：**不**幂等（每跑一次都会叠加计票）。建议只跑一次。
如需重跑，先 TRUNCATE 3 张 hints 表。
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.database import SessionLocal
from app.models.category import CategoryPlatformMapping, AttributeMapping
from app.services.global_hints.service import (
    record_category_confirmation, record_attribute_confirmation,
)


def main():
    db = SessionLocal()
    try:
        # 1. 品类映射回填（按租户分组处理，record_* 里需要 tenant_id 查同本地分类的 siblings）
        cat_mappings = db.query(CategoryPlatformMapping).filter(
            CategoryPlatformMapping.is_confirmed == 1,
        ).all()
        print(f"[1/2] 品类映射 is_confirmed=1: {len(cat_mappings)} 条")
        cat_ok = 0
        for m in cat_mappings:
            try:
                record_category_confirmation(db, m.tenant_id, m)
                cat_ok += 1
            except Exception as e:
                print(f"  跳过 cat_mapping id={m.id}: {e}")
        print(f"      成功: {cat_ok}")

        # 2. 属性映射回填
        attr_mappings = db.query(AttributeMapping).filter(
            AttributeMapping.is_confirmed == 1,
        ).all()
        print(f"[2/2] 属性映射 is_confirmed=1: {len(attr_mappings)} 条")
        attr_ok = 0
        for m in attr_mappings:
            try:
                record_attribute_confirmation(db, m.tenant_id, m)
                attr_ok += 1
            except Exception as e:
                print(f"  跳过 attr_mapping id={m.id}: {e}")
        print(f"      成功: {attr_ok}")

        # 3. 汇总
        from app.models.global_hints import (
            GlobalCategoryHint, GlobalCrossPlatformCategoryHint, GlobalAttributeHint,
        )
        n_cat = db.query(GlobalCategoryHint).count()
        n_cross = db.query(GlobalCrossPlatformCategoryHint).count()
        n_attr = db.query(GlobalAttributeHint).count()
        print("")
        print("==== hints 表现状 ====")
        print(f"  global_category_hints                : {n_cat} 行")
        print(f"  global_cross_platform_category_hints : {n_cross} 行")
        print(f"  global_attribute_hints               : {n_attr} 行")
    finally:
        db.close()


if __name__ == "__main__":
    main()
