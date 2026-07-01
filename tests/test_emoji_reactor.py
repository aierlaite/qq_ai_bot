"""测试 NapCatEmojiReactor：emoji 反应是否正确调用 set_msg_emoji_like。"""
import unittest
from unittest.mock import MagicMock

from tests._path_setup import _  # noqa: F401  加载路径设置
from src.senders.emoji_reactor import NapCatEmojiReactor


class TestEmojiReactor(unittest.TestCase):
    def setUp(self):
        self.client = MagicMock()
        self.client.set_msg_emoji_like = MagicMock(return_value={"status": "ok"})
        self.reactor = NapCatEmojiReactor(self.client)

    def test_normal_react_calls_api(self):
        """正常 emoji 反应：应调用 client.set_msg_emoji_like 一次，参数正确。"""
        result = self.reactor.react("945024095", "msg123", "66")
        self.client.set_msg_emoji_like.assert_called_once_with("msg123", "66")
        self.assertEqual(result, {"status": "ok"})

    def test_empty_msg_id_skipped(self):
        """msg_id 为空应跳过，不调用 API。"""
        result = self.reactor.react("945024095", "", "66")
        self.client.set_msg_emoji_like.assert_not_called()
        self.assertEqual(result, {})

    def test_empty_emoji_id_skipped(self):
        """emoji_id 为空应跳过。"""
        result = self.reactor.react("945024095", "msg123", "")
        self.client.set_msg_emoji_like.assert_not_called()
        self.assertEqual(result, {})

    def test_int_emoji_id_converted_to_str(self):
        """int 类型 emoji_id 应转为 str。"""
        self.reactor.react("945024095", "msg123", 66)
        self.client.set_msg_emoji_like.assert_called_once_with("msg123", "66")

    def test_exception_returns_empty(self):
        """API 异常时应捕获，返回空 dict，不抛出。"""
        self.client.set_msg_emoji_like.side_effect = RuntimeError("network error")
        result = self.reactor.react("945024095", "msg123", "66")
        self.assertEqual(result, {})


if __name__ == "__main__":
    unittest.main()
