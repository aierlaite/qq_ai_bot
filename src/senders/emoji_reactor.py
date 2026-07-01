"""emoji 反应器实现。

调用 NapCat /set_msg_emoji_like 对群消息添加 QQ 自带 emoji 反应。
"""
from ..napcat_client import NapCatClient
from ..utils.logger import get_logger

logger = get_logger("emoji_reactor")


class NapCatEmojiReactor:
    """NapCat emoji 反应器，调用 set_msg_emoji_like。"""

    def __init__(self, client: NapCatClient):
        self.client = client

    def react(self, group_id: str, msg_id: str, emoji_id: str) -> dict:
        """对群消息添加 emoji 反应。

        Args:
            group_id: 目标群号（当前实现由 client 内部持有，参数保留兼容）
            msg_id: 要反应的消息 ID
            emoji_id: QQ 表情 ID（如 "66""99" 等）
        """
        if not msg_id:
            logger.warning("emoji 反应跳过：msg_id 为空")
            return {}
        if not emoji_id:
            logger.warning("emoji 反应跳过：emoji_id 为空")
            return {}
        try:
            result = self.client.set_msg_emoji_like(msg_id, str(emoji_id))
            logger.info(f"emoji 反应已发送：msg_id={msg_id} emoji_id={emoji_id}")
            return result
        except Exception as e:
            logger.error(f"emoji 反应发送失败: {e}")
            return {}


# 向后兼容：保留 EmptyEmojiReactor 别名
EmptyEmojiReactor = NapCatEmojiReactor
