"""语音发送器。

AIRecordVoiceSender: 通过 NapCat send_group_ai_record 发送 AI 合成语音。
LocalFileVoiceSender: 通过 send_group_msg 发送本地音频文件（record 段）。
"""
from ..napcat_client import NapCatClient
from ..utils.logger import get_logger

logger = get_logger("voice_sender")


class AIRecordVoiceSender:
    """AI 语音发送器。

    调用 NapCat 的 send_group_ai_record 接口，由 NapCat 端合成语音并发送。
    """

    def __init__(self, client: NapCatClient, character: str, fallback_to_text: bool = True):
        self.client = client
        self.character = character
        self.fallback_to_text = fallback_to_text

    def send(self, group_id: str, data: dict) -> dict:
        """发送 AI 语音。

        Args:
            group_id: 群号（client 已绑定，此处仅日志用）
            data: 语音数据，需含 text 字段
        """
        text = data.get("text", "").strip()
        if not text:
            logger.warning("AI 语音缺少 text，跳过")
            return {}
        logger.info(f"发送 AI 语音 character={self.character} text={text[:30]}")
        result = self.client.send_group_ai_record(self.character, text)
        if not result.get("ok") and self.fallback_to_text:
            logger.info("AI 语音发送失败，回退为文字")
            return self.client.send_group_msg([{"type": "text", "data": {"text": text}}])
        return result


class LocalFileVoiceSender:
    """本地音频文件发送器。

    通过 send_group_msg 发送 record 段。
    """

    def __init__(self, client: NapCatClient):
        self.client = client

    def send(self, group_id: str, data: dict) -> dict:
        """发送本地音频文件。

        Args:
            group_id: 群号（client 已绑定，此处仅日志用）
            data: 语音数据，需含 file 字段（文件路径或 file:// URL）
        """
        file = data.get("file", "").strip()
        if not file:
            logger.warning("本地语音缺少 file，跳过")
            return {}
        logger.info(f"发送本地语音 file={file}")
        return self.client.send_group_msg([{"type": "record", "data": {"file": file}}])
