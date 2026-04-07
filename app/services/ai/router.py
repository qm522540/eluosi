"""AI模型统一调度路由

所有AI调用必须通过此路由，禁止业务代码直接调用模型API。
路由规则：
  - 数据分析/ROI计算 → DeepSeek
  - 长文档/报告生成 → Kimi
  - 俄语文案/SEO标题 → GLM
  - 不确定时 → 默认DeepSeek
"""

import json
from typing import Optional

import httpx
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models.ai import AiDecisionLog
from app.services.ai.deepseek import DeepSeekClient
from app.services.ai.kimi import KimiClient
from app.services.ai.glm import GLMClient
from app.utils.logger import logger

settings = get_settings()

# 任务类型 → 模型映射
TASK_MODEL_MAP = {
    "ad_optimization": "deepseek",
    "roi_analysis": "deepseek",
    "inventory_forecast": "deepseek",
    "report_generation": "kimi",
    "seo_generation": "glm",
}

# 模型 → 客户端实例（懒加载）
_clients: dict = {}


def _get_client(model: str):
    """获取或创建AI客户端实例"""
    if model in _clients:
        return _clients[model]

    if model == "deepseek":
        if not settings.DEEPSEEK_API_KEY:
            raise ValueError("DEEPSEEK_API_KEY 未配置")
        _clients[model] = DeepSeekClient(
            api_key=settings.DEEPSEEK_API_KEY,
            base_url=settings.DEEPSEEK_BASE_URL,
        )
    elif model == "kimi":
        if not settings.KIMI_API_KEY:
            raise ValueError("KIMI_API_KEY 未配置")
        _clients[model] = KimiClient(
            api_key=settings.KIMI_API_KEY,
            base_url=settings.KIMI_BASE_URL,
        )
    elif model == "glm":
        if not settings.GLM_API_KEY:
            raise ValueError("GLM_API_KEY 未配置")
        _clients[model] = GLMClient(
            api_key=settings.GLM_API_KEY,
            base_url=settings.GLM_BASE_URL,
        )
    else:
        raise ValueError(f"未知的AI模型: {model}")

    return _clients[model]


async def execute(
    task_type: str,
    input_data: dict,
    tenant_id: int,
    db: Session,
    user_id: Optional[int] = None,
    triggered_by: str = "scheduled",
    system_prompt: Optional[str] = None,
    temperature: float = 0.7,
    max_tokens: int = 2000,
) -> dict:
    """统一AI调用入口

    Args:
        task_type: 任务类型(ad_optimization/seo_generation/...)
        input_data: 输入数据，须包含 "messages" 字段或 "prompt" 字段
        tenant_id: 租户ID
        db: 数据库会话
        user_id: 触发用户ID
        triggered_by: 触发方式(manual/scheduled/alert)
        system_prompt: 系统提示词
        temperature: 温度
        max_tokens: 最大输出token

    Returns:
        {"model": "deepseek", "content": "...", "tokens": {...}, "decision_id": int}
    """
    model = TASK_MODEL_MAP.get(task_type, "deepseek")
    logger.info(f"AI路由: task={task_type} model={model} tenant={tenant_id}")

    # 创建日志记录（pending状态）
    decision_log = AiDecisionLog(
        tenant_id=tenant_id,
        task_type=task_type,
        ai_model=model,
        input_data=input_data,
        status="pending",
        triggered_by=triggered_by,
        user_id=user_id,
    )
    db.add(decision_log)
    db.flush()

    try:
        client = _get_client(model)

        # 构造messages
        if "messages" in input_data:
            messages = input_data["messages"]
        elif "prompt" in input_data:
            messages = [{"role": "user", "content": input_data["prompt"]}]
        else:
            messages = [{"role": "user", "content": json.dumps(input_data, ensure_ascii=False)}]

        # 调用AI
        result = await client.chat(
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            system_prompt=system_prompt,
        )

        # 更新日志为成功
        decision_log.status = "success"
        decision_log.output_data = {"content": result["content"]}
        decision_log.prompt_tokens = result.get("prompt_tokens")
        decision_log.completion_tokens = result.get("completion_tokens")
        decision_log.duration_ms = result.get("duration_ms")
        db.commit()

        return {
            "model": model,
            "content": result["content"],
            "tokens": {
                "prompt": result.get("prompt_tokens", 0),
                "completion": result.get("completion_tokens", 0),
                "total": result.get("total_tokens", 0),
            },
            "duration_ms": result.get("duration_ms", 0),
            "decision_id": decision_log.id,
        }

    except httpx.TimeoutException:
        decision_log.status = "timeout"
        decision_log.error_message = "AI模型响应超时"
        db.commit()
        logger.error(f"AI超时: task={task_type} model={model}")
        raise

    except ValueError as e:
        decision_log.status = "failed"
        decision_log.error_message = str(e)
        db.commit()
        logger.error(f"AI配置错误: {e}")
        raise

    except Exception as e:
        decision_log.status = "failed"
        decision_log.error_message = str(e)[:500]
        db.commit()
        logger.error(f"AI调用失败: task={task_type} model={model}: {e}")
        raise
