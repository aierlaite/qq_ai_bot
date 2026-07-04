"""消息发送器实现。

负责 text/at/reply/face/mface/forward/image/voice/poke 等段的拼装与发送。

额外职责：对 text 段做占位符清洗——LLM 偶尔会把群消息里的占位符
（如 [QQ表情:66]、@123456）当文本原样输出，这里解析回真正的消息段。
"""
import re

from ..napcat_client import NapCatClient
from ..utils.logger import get_logger

logger = get_logger("message_sender")

_FACE_PLACEHOLDER_RE = re.compile(r"\[QQ\s*表情\s*[:：]\s*(\d+)\]")
_MFACE_PLACEHOLDER_RE = re.compile(r"\[表情包[:：]\s*([^\]]+)\]")
_AT_PLACEHOLDER_RE = re.compile(r"(?<![0-9a-zA-Z])@(\d{5,11})(?![0-9a-zA-Z])")


class NapCatMessageSender:
    """NapCat 消息发送器，实现 MessageSender 协议。"""

    def __init__(self, client: NapCatClient):
        self.client = client

    def send_group_message(self, group_id: str, segments: list[dict]) -> dict:
        """发送消息段数组到指定群。"""
        return self.client.send_group_msg(segments)

    def build_segments(self, messages: list, history) -> list[list[dict]]:
        """把模型输出的 messages 转换为 OneBot 消息段数组的列表。

        每条消息转换为一段数组（可能含多段），返回多条消息的段数组列表。
        """
        result = []
        for msg in messages:
            segs = self._build_one(msg, history)
            if segs:
                result.append(segs)
        return result

    def _build_one(self, msg, history) -> list[dict]:
        """转换单条消息为段数组。"""
        if isinstance(msg, str):
            return self._parse_text_with_placeholders(msg)

        if not isinstance(msg, dict):
            return []

        msg_type = msg.get("type", "")
        data = msg.get("data", {})

        if msg_type == "text":
            return self._parse_text_with_placeholders(data.get("text", ""))

        if msg_type == "at":
            return [{"type": "at", "data": {"qq": str(data.get("qq", "")), "text": data.get("text", "")}}]

        if msg_type == "reply":
            target_idx = data.get("target_msg_index", 0)
            msg_id = history.get_msg_id_by_index(target_idx) if history else ""
            segs = []
            if msg_id:
                segs.append({"type": "reply", "data": {"id": msg_id}})
            if data.get("text"):
                segs.extend(self._parse_text_with_placeholders(data["text"]))
            return segs

        if msg_type == "face":
            return [{"type": "face", "data": {"id": str(data.get("id", ""))}}]

        if msg_type == "mface":
            mface_data = {}
            for k in ("emoji_package_id", "emoji_id", "key", "summary", "url",
                      "emoji_name", "tip"):
                v = data.get(k)
                if v is not None and v != "":
                    mface_data[k] = str(v) if k in ("emoji_package_id", "emoji_id") else v
            if not mface_data:
                logger.warning("mface 段缺少数据，跳过")
                return []
            return [{"type": "mface", "data": mface_data}]

        if msg_type == "forward":
            return [{"type": "forward", "data": data}]

        if msg_type == "image":
            return [{"type": "image", "data": data}]

        if msg_type == "voice":
            return [{"type": "voice", "data": data}]

        if msg_type == "poke":
            return [{"type": "poke", "data": data}]

        logger.warning(f"未知消息段 type={msg_type}，跳过")
        return []

    def _parse_text_with_placeholders(self, text: str) -> list[dict]:
        """清洗 text 段：把占位符解析回真正的消息段。

        解析的占位符：
        - [QQ表情:66] / [QQ 表情:66] → face 段
        - [表情包:关键词] → mface 段（透传 summary）
        - @123456789（5-11 位数字） → at 段
        """
        if not text:
            return []

        segs = []
        cursor = 0
        matches = []
        for m in _FACE_PLACEHOLDER_RE.finditer(text):
            matches.append((m.start(), m.end(), "face", m.group(1)))
        for m in _MFACE_PLACEHOLDER_RE.finditer(text):
            matches.append((m.start(), m.end(), "mface", m.group(1)))
        for m in _AT_PLACEHOLDER_RE.finditer(text):
            matches.append((m.start(), m.end(), "at", m.group(1)))
        matches.sort(key=lambda x: x[0])

        for start, end, seg_type, value in matches:
            if start < cursor:
                continue
            if start > cursor:
                segs.append({"type": "text", "data": {"text": text[cursor:start]}})
            if seg_type == "face":
                segs.append({"type": "face", "data": {"id": value}})
            elif seg_type == "mface":
                segs.append({"type": "mface", "data": {"summary": value}})
            elif seg_type == "at":
                segs.append({"type": "at", "data": {"qq": value}})
            cursor = end

        if cursor < len(text):
            segs.append({"type": "text", "data": {"text": text[cursor:]}})

        return segs
