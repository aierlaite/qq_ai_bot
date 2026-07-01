"""测试 NapCatMessageSender：重点测 mface 段构造。"""
import unittest
from unittest.mock import MagicMock

from tests._path_setup import _  # noqa: F401
from src.senders.message_sender import NapCatMessageSender


class TestMessageSenderMface(unittest.TestCase):
    def setUp(self):
        self.client = MagicMock()
        self.sender = NapCatMessageSender(self.client)

    def test_mface_summary_only(self):
        """LLM 只填 summary：应透传 summary 字段。"""
        segs_list = self.sender.build_segments(
            [{"type": "mface", "data": {"summary": "偷笑"}}], history=None
        )
        self.assertEqual(len(segs_list), 1)
        self.assertEqual(segs_list[0][0]["type"], "mface")
        self.assertEqual(segs_list[0][0]["data"]["summary"], "偷笑")

    def test_mface_full_fields(self):
        """完整字段：emoji_package_id/emoji_id 应转为 str。"""
        segs_list = self.sender.build_segments(
            [{"type": "mface", "data": {
                "emoji_package_id": 1234,
                "emoji_id": 5678,
                "key": "abc",
                "summary": "滑稽",
                "url": "https://x.com/mface.png",
            }}], history=None
        )
        data = segs_list[0][0]["data"]
        self.assertEqual(data["emoji_package_id"], "1234")
        self.assertEqual(data["emoji_id"], "5678")
        self.assertEqual(data["key"], "abc")
        self.assertEqual(data["summary"], "滑稽")
        self.assertEqual(data["url"], "https://x.com/mface.png")

    def test_mface_empty_data_skipped(self):
        """mface 无任何字段应跳过。"""
        segs_list = self.sender.build_segments(
            [{"type": "mface", "data": {}}], history=None
        )
        self.assertEqual(len(segs_list), 0)

    def test_mface_strips_empty_fields(self):
        """空字符串字段不应进入 data。"""
        segs_list = self.sender.build_segments(
            [{"type": "mface", "data": {"summary": "无语", "url": "", "key": ""}}], history=None
        )
        data = segs_list[0][0]["data"]
        self.assertEqual(data, {"summary": "无语"})

    def test_text_string_msg(self):
        """字符串消息转 text 段。"""
        segs_list = self.sender.build_segments(["你好"], history=None)
        self.assertEqual(segs_list[0][0], {"type": "text", "data": {"text": "你好"}})

    def test_face_segment(self):
        """face 段构造。"""
        segs_list = self.sender.build_segments(
            [{"type": "face", "data": {"id": 66}}], history=None
        )
        self.assertEqual(segs_list[0][0], {"type": "face", "data": {"id": "66"}})

    def test_unknown_type_skipped(self):
        """未知 type 应跳过。"""
        segs_list = self.sender.build_segments(
            [{"type": "unknown_seg", "data": {}}], history=None
        )
        self.assertEqual(len(segs_list), 0)


class TestPlaceholderSanitizer(unittest.TestCase):
    """占位符清洗：LLM 误把 [QQ表情:xx]/@QQ号 当文本输出时应解析回消息段。"""

    def setUp(self):
        self.client = MagicMock()
        self.sender = NapCatMessageSender(self.client)

    def test_face_placeholder_in_text(self):
        """[QQ表情:66] 应被解析为 face 段，前后文本保留。"""
        segs_list = self.sender.build_segments(["你好[QQ表情:66]再见"], history=None)
        segs = segs_list[0]
        types = [s["type"] for s in segs]
        self.assertEqual(types, ["text", "face", "text"])
        self.assertEqual(segs[0]["data"]["text"], "你好")
        self.assertEqual(segs[1]["data"]["id"], "66")
        self.assertEqual(segs[2]["data"]["text"], "再见")

    def test_face_placeholder_with_space_variant(self):
        """[QQ 表情: 66] 变体也应解析。"""
        segs_list = self.sender.build_segments(["[QQ 表情: 99]"], history=None)
        segs = segs_list[0]
        self.assertEqual(segs[0]["type"], "face")
        self.assertEqual(segs[0]["data"]["id"], "99")

    def test_face_placeholder_fullwidth_colon(self):
        """中文冒号 [QQ表情：66] 也应解析。"""
        segs_list = self.sender.build_segments(["[QQ表情：332]"], history=None)
        segs = segs_list[0]
        self.assertEqual(segs[0]["type"], "face")
        self.assertEqual(segs[0]["data"]["id"], "332")

    def test_at_placeholder_qq_number(self):
        """@1173075735 应被解析为 at 段。"""
        segs_list = self.sender.build_segments(["@1173075735 你好"], history=None)
        segs = segs_list[0]
        types = [s["type"] for s in segs]
        self.assertEqual(types, ["at", "text"])
        self.assertEqual(segs[0]["data"]["qq"], "1173075735")

    def test_at_not_triggered_for_short_number(self):
        """@1234（4 位）不应被识别为 at（太短不像 QQ 号）。"""
        segs_list = self.sender.build_segments(["@1234"], history=None)
        segs = segs_list[0]
        self.assertEqual(len(segs), 1)
        self.assertEqual(segs[0]["type"], "text")

    def test_at_not_triggered_for_nickname(self):
        """@忆雨（非纯数字）不应被识别为 at 段，保留为文本。"""
        segs_list = self.sender.build_segments(["@忆雨 你好"], history=None)
        segs = segs_list[0]
        self.assertEqual(len(segs), 1)
        self.assertEqual(segs[0]["type"], "text")
        self.assertIn("忆雨", segs[0]["data"]["text"])

    def test_mface_placeholder(self):
        """[表情包:偷笑] 应被解析为 mface 段。"""
        segs_list = self.sender.build_segments(["[表情包:偷笑]"], history=None)
        segs = segs_list[0]
        self.assertEqual(segs[0]["type"], "mface")
        self.assertEqual(segs[0]["data"]["summary"], "偷笑")

    def test_regression_user_reported_bug(self):
        """回归：用户报告 LLM 输出 '你好，[QQ 表情:332]@1173075735' 应被正确解析。

        期望输出：text("你好，") + face(332) + at(1173075735)
        """
        segs_list = self.sender.build_segments(["你好，[QQ 表情:332]@1173075735"], history=None)
        segs = segs_list[0]
        types = [s["type"] for s in segs]
        self.assertEqual(types, ["text", "face", "at"])
        self.assertEqual(segs[0]["data"]["text"], "你好，")
        self.assertEqual(segs[1]["data"]["id"], "332")
        self.assertEqual(segs[2]["data"]["qq"], "1173075735")

    def test_text_dict_with_placeholder(self):
        """dict 形式的 text 段含占位符也应被解析。"""
        segs_list = self.sender.build_segments(
            [{"type": "text", "data": {"text": "[QQ表情:14]"}}], history=None
        )
        segs = segs_list[0]
        self.assertEqual(segs[0]["type"], "face")
        self.assertEqual(segs[0]["data"]["id"], "14")

    def test_normal_text_not_affected(self):
        """无占位符的纯文本应原样输出为单个 text 段。"""
        segs_list = self.sender.build_segments(["晚安呐"], history=None)
        segs = segs_list[0]
        self.assertEqual(len(segs), 1)
        self.assertEqual(segs[0]["type"], "text")
        self.assertEqual(segs[0]["data"]["text"], "晚安呐")

    def test_empty_text_returns_empty(self):
        """空字符串不应产生任何段。"""
        segs_list = self.sender.build_segments([""], history=None)
        self.assertEqual(len(segs_list), 0)


if __name__ == "__main__":
    unittest.main()
