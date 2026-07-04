"""emoji 反应器。

通过 NapCat set_msg_emoji_like 对消息添加表情反应。
"""
from ..napcat_client import NapCatClient
from ..utils.logger import get_logger

logger = get_logger("emoji_reactor")


class NapCatEmojiReactor:
    """NapCat emoji 反应器。"""

    def __init__(self, client: NapCatClient):
        self.client = client

    def react(self, group_id: str, msg_id: str, emoji_id: str) -> dict:
        """对指定消息添加表情反应。

        Args:
            group_id: 群号（set_msg_emoji_like 按 msg_id 定位，group_id 仅日志用）
            msg_id: 目标消息 ID
            emoji_id: face ID（如 "66" 点赞）
        """
        if not msg_id or not emoji_id:
            logger.warning(f"emoji 反应缺少参数 msg_id={msg_id} emoji_id={emoji_id}，跳过")
            return {}
        logger.info(f"emoji 反应 msg_id={msg_id} emoji_id={emoji_id}")
        try:
            return self.client.set_msg_emoji_like(msg_id, str(emoji_id))
        except Exception as e:
            logger.warning(f"emoji 反应异常: {e}")
            return {}
