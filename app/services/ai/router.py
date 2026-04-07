"""AI模型统一调度路由

所有AI调用必须通过此路由，禁止业务代码直接调用模型API。
路由规则：
  - 数据分析/ROI计算 → DeepSeek
  - 长文档/报告生成 → Kimi
  - 俄语文案/SEO标题 → GLM
  - 不确定时 → 默认DeepSeek
"""

from app.utils.logger import logger

# 任务类型 → 模型映射
TASK_MODEL_MAP = {
    "ad_optimization": "deepseek",
    "roi_analysis": "deepseek",
    "inventory_forecast": "deepseek",
    "report_generation": "kimi",
    "seo_generation": "glm",
}


async def execute(task_type: str, input_data: dict, tenant_id: int) -> dict:
    """统一AI调用入口

    Args:
        task_type: 任务类型(ad_optimization/seo_generation/...)
        input_data: 输入数据
        tenant_id: 租户ID

    Returns:
        {"model": "deepseek", "output": {...}, "tokens": {...}}
    """
    model = TASK_MODEL_MAP.get(task_type, "deepseek")
    logger.info(f"AI路由: task={task_type} model={model} tenant={tenant_id}")

    # TODO: 实现各模型调用，记录到ai_decision_logs
    raise NotImplementedError(f"AI模型 {model} 调用待实现")
