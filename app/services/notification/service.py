"""企业微信通知服务"""

import httpx
from datetime import datetime
from sqlalchemy.orm import Session

from app.models.notification import Notification
from app.config import get_settings
from app.utils.logger import logger

settings = get_settings()


async def send_wechat_work_bot(content: str, msg_type: str = "text") -> bool:
    """通过群机器人Webhook发送消息"""
    webhook_url = settings.WECHAT_WORK_BOT_WEBHOOK
    if not webhook_url:
        logger.warning("企业微信群机器人Webhook未配置，跳过发送")
        return False

    try:
        if msg_type == "markdown":
            payload = {"msgtype": "markdown", "markdown": {"content": content}}
        else:
            payload = {"msgtype": "text", "text": {"content": content}}

        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(webhook_url, json=payload)
            data = resp.json()

        if data.get("errcode") == 0:
            logger.info("企业微信群机器人消息发送成功")
            return True
        else:
            logger.error(f"企业微信群机器人发送失败: {data}")
            return False
    except Exception as e:
        logger.error(f"企业微信群机器人发送异常: {e}")
        return False


async def send_wechat_work_app_message(user_ids: list, content: str) -> bool:
    """通过企业微信应用消息推送给指定用户"""
    corp_id = settings.WECHAT_WORK_CORP_ID
    secret = settings.WECHAT_WORK_SECRET
    agent_id = settings.WECHAT_WORK_AGENT_ID

    if not all([corp_id, secret, agent_id]):
        logger.warning("企业微信应用消息配置不完整，跳过发送")
        return False

    try:
        # 获取access_token
        async with httpx.AsyncClient(timeout=10) as client:
            token_resp = await client.get(
                "https://qyapi.weixin.qq.com/cgi-bin/gettoken",
                params={"corpid": corp_id, "corpsecret": secret},
            )
            token_data = token_resp.json()

        if token_data.get("errcode") != 0:
            logger.error(f"获取企业微信access_token失败: {token_data}")
            return False

        access_token = token_data["access_token"]

        # 发送应用消息
        payload = {
            "touser": "|".join(user_ids),
            "msgtype": "text",
            "agentid": int(agent_id),
            "text": {"content": content},
        }

        async with httpx.AsyncClient(timeout=10) as client:
            send_resp = await client.post(
                f"https://qyapi.weixin.qq.com/cgi-bin/message/send?access_token={access_token}",
                json=payload,
            )
            send_data = send_resp.json()

        if send_data.get("errcode") == 0:
            logger.info(f"企业微信应用消息发送成功, users={user_ids}")
            return True
        else:
            logger.error(f"企业微信应用消息发送失败: {send_data}")
            return False
    except Exception as e:
        logger.error(f"企业微信应用消息发送异常: {e}")
        return False


async def process_pending_notifications(db: Session) -> dict:
    """处理待发送的通知（从notifications表读取并推送）"""
    try:
        # 查询未发送的通知
        pending = db.query(Notification).filter(
            Notification.sent_at.is_(None),
            Notification.channel.in_(["wechat_work", "both"]),
        ).limit(50).all()

        if not pending:
            return {"processed": 0, "success": 0, "failed": 0}

        success_count = 0
        failed_count = 0

        for notif in pending:
            # 格式化消息
            msg = f"**{notif.title}**\n{notif.content}"

            # 通过群机器人发送
            sent = await send_wechat_work_bot(msg, msg_type="markdown")

            if sent:
                notif.sent_at = datetime.utcnow()
                success_count += 1
            else:
                failed_count += 1

        db.commit()

        result = {
            "processed": len(pending),
            "success": success_count,
            "failed": failed_count,
        }
        logger.info(f"通知处理完成: {result}")
        return result
    except Exception as e:
        db.rollback()
        logger.error(f"处理通知失败: {e}")
        return {"processed": 0, "success": 0, "failed": 0, "error": str(e)}


def get_notifications(db: Session, tenant_id: int, is_read: int = None,
                      page: int = 1, page_size: int = 20) -> dict:
    """获取通知列表"""
    try:
        from app.utils.errors import ErrorCode
        query = db.query(Notification).filter(Notification.tenant_id == tenant_id)
        if is_read is not None:
            query = query.filter(Notification.is_read == is_read)

        total = query.count()
        items = query.order_by(Notification.created_at.desc()).offset(
            (page - 1) * page_size
        ).limit(page_size).all()

        return {
            "code": ErrorCode.SUCCESS,
            "data": {
                "items": [{
                    "id": n.id,
                    "notification_type": n.notification_type,
                    "title": n.title,
                    "content": n.content,
                    "channel": n.channel,
                    "is_read": n.is_read,
                    "sent_at": n.sent_at.isoformat() if n.sent_at else None,
                    "created_at": n.created_at.isoformat() if n.created_at else None,
                } for n in items],
                "total": total,
                "page": page,
                "page_size": page_size,
                "pages": (total + page_size - 1) // page_size,
            },
        }
    except Exception as e:
        from app.utils.errors import ErrorCode
        logger.error(f"获取通知列表失败: {e}")
        return {"code": ErrorCode.UNKNOWN_ERROR, "msg": "获取通知列表失败"}


def mark_notification_read(db: Session, notification_id: int, tenant_id: int) -> dict:
    """标记通知为已读"""
    try:
        from app.utils.errors import ErrorCode
        notif = db.query(Notification).filter(
            Notification.id == notification_id,
            Notification.tenant_id == tenant_id,
        ).first()

        if not notif:
            return {"code": ErrorCode.NOT_FOUND, "msg": "通知不存在"}

        notif.is_read = 1
        notif.read_at = datetime.utcnow()
        db.commit()

        return {"code": ErrorCode.SUCCESS, "data": None}
    except Exception as e:
        db.rollback()
        logger.error(f"标记通知已读失败: {e}")
        from app.utils.errors import ErrorCode
        return {"code": ErrorCode.UNKNOWN_ERROR, "msg": "操作失败"}
