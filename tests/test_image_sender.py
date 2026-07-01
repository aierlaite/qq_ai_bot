"""测试 NapCatImageSender：图片段构造和发送。"""
import unittest
from unittest.mock import MagicMock

from tests._path_setup import _  # noqa: F401
from src.senders.image_sender import NapCatImageSender


class TestImageSender(unittest.TestCase):
    def setUp(self):
        self.client = MagicMock()
        self.client.send_group_msg = MagicMock(return_value={"status": "ok"})
        self.sender = NapCatImageSender(self.client)

    def test_send_by_url(self):
        """通过 url 发送：应构造 image 段含 url 字段。"""
        self.sender.send("945024095", {"url": "https://example.com/a.png", "summary": "测试图"})
        args, _ = self.client.send_group_msg.call_args
        segs = args[0]
        self.assertEqual(len(segs), 1)
        self.assertEqual(segs[0]["type"], "image")
        self.assertEqual(segs[0]["data"]["url"], "https://example.com/a.png")
        self.assertEqual(segs[0]["data"]["summary"], "测试图")

    def test_send_by_file(self):
        """通过 file 发送：data 应含 file 字段，不含 url。"""
        self.sender.send("945024095", {"file": "C:/tmp/a.png"})
        args, _ = self.client.send_group_msg.call_args
        segs = args[0]
        self.assertEqual(segs[0]["data"]["file"], "C:/tmp/a.png")
        self.assertNotIn("url", segs[0]["data"])

    def test_send_by_base64_raw(self):
        """base64 不带前缀：应自动加 base64:// 前缀。"""
        self.sender.send("945024095", {"base64": "iVBORw0KGgo="})
        args, _ = self.client.send_group_msg.call_args
        segs = args[0]
        self.assertEqual(segs[0]["data"]["file"], "base64://iVBORw0KGgo=")

    def test_send_by_base64_prefixed(self):
        """base64 已带前缀：不应重复加前缀。"""
        self.sender.send("945024095", {"base64": "base64://iVBORw0KGgo="})
        args, _ = self.client.send_group_msg.call_args
        segs = args[0]
        self.assertEqual(segs[0]["data"]["file"], "base64://iVBORw0KGgo=")

    def test_priority_url_over_file(self):
        """同时有 url 和 file 时，url 优先。"""
        self.sender.send("945024095", {"url": "https://x.com/a.png", "file": "C:/tmp/a.png"})
        args, _ = self.client.send_group_msg.call_args
        segs = args[0]
        self.assertIn("url", segs[0]["data"])
        self.assertNotIn("file", segs[0]["data"])

    def test_empty_data_skipped(self):
        """无 url/file/base64 应跳过，不调用 API。"""
        result = self.sender.send("945024095", {"summary": "无图源"})
        self.client.send_group_msg.assert_not_called()
        self.assertEqual(result, {})

    def test_exception_returns_empty(self):
        """API 异常应捕获。"""
        self.client.send_group_msg.side_effect = RuntimeError("net error")
        result = self.sender.send("945024095", {"url": "https://x.com/a.png"})
        self.assertEqual(result, {})


if __name__ == "__main__":
    unittest.main()
