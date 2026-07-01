"""测试 parser：重点测 mface 类型校验和边界情况。"""
import json
import unittest

from tests._path_setup import _  # noqa: F401
from src.parser import parse_and_validate, VALID_MSG_TYPES


class TestParserMface(unittest.TestCase):
    def test_mface_in_valid_types(self):
        """mface 应在 VALID_MSG_TYPES 中。"""
        self.assertIn("mface", VALID_MSG_TYPES)

    def test_mface_passes_validation(self):
        """含 mface 段的 reply 应通过校验。"""
        raw = json.dumps({
            "thought": "想回个表情包",
            "action": "reply",
            "messages": [
                {"type": "mface", "data": {"summary": "偷笑"}}
            ],
        })
        parsed = parse_and_validate(raw)
        self.assertEqual(parsed.action, "reply")
        self.assertEqual(len(parsed.messages), 1)
        self.assertEqual(parsed.messages[0]["type"], "mface")
        self.assertEqual(parsed.messages[0]["data"]["summary"], "偷笑")

    def test_reply_with_mface_and_text(self):
        """mface 和 text 混合：都应保留。"""
        raw = json.dumps({
            "thought": "笑死",
            "action": "reply",
            "messages": [
                "哈哈",
                {"type": "mface", "data": {"summary": "滑稽"}},
            ],
        })
        parsed = parse_and_validate(raw)
        self.assertEqual(len(parsed.messages), 2)
        self.assertEqual(parsed.messages[0], "哈哈")
        self.assertEqual(parsed.messages[1]["type"], "mface")

    def test_invalid_action_falls_back_silent(self):
        """非法 action 应回退 silent。"""
        raw = json.dumps({"action": "invalid", "messages": []})
        parsed = parse_and_validate(raw)
        self.assertEqual(parsed.action, "silent")

    def test_empty_messages_with_reply_falls_back_silent(self):
        """reply 但 messages 为空应回退 silent。"""
        raw = json.dumps({"action": "reply", "messages": []})
        parsed = parse_and_validate(raw)
        self.assertEqual(parsed.action, "silent")

    def test_unknown_msg_type_dropped(self):
        """未知消息段 type 应被丢弃，其他段保留。"""
        raw = json.dumps({
            "action": "reply",
            "messages": [
                "保留我",
                {"type": "fake_type", "data": {}},
                {"type": "mface", "data": {"summary": "无语"}},
            ],
        })
        parsed = parse_and_validate(raw)
        self.assertEqual(len(parsed.messages), 2)

    def test_reply_delay_only_silent(self):
        """reply_delay_minutes 仅在 silent 时有效。"""
        raw = json.dumps({
            "action": "reply",
            "messages": ["hi"],
            "reply_delay_minutes": 30,
        })
        parsed = parse_and_validate(raw)
        self.assertEqual(parsed.reply_delay_minutes, 0)

    def test_reply_delay_silent(self):
        """silent + reply_delay 应保留。"""
        raw = json.dumps({
            "action": "silent",
            "messages": [],
            "reply_delay_minutes": 30,
        })
        parsed = parse_and_validate(raw)
        self.assertEqual(parsed.reply_delay_minutes, 30)

    def test_json_with_markdown_codeblock(self):
        """markdown 代码块包裹的 JSON 应能解析。"""
        raw = '```json\n{"action":"silent","messages":[]}\n```'
        parsed = parse_and_validate(raw)
        self.assertEqual(parsed.action, "silent")

    def test_invalid_json_falls_back_silent(self):
        """非法 JSON 应回退 silent。"""
        parsed = parse_and_validate("not a json")
        self.assertEqual(parsed.action, "silent")


if __name__ == "__main__":
    unittest.main()
