"""测试 NapCatClient 新增的媒体 API：get_image / get_record / get_msg / send_poke / send_group_sign。

用 mock 拦截 requests.post，验证 endpoint 和 payload 构造是否正确。
"""
import unittest
from unittest.mock import patch, MagicMock

from tests._path_setup import _  # noqa: F401
from src.napcat_client import NapCatClient


class TestNapCatClientNewApi(unittest.TestCase):
    def setUp(self):
        self.client = NapCatClient("http://127.0.0.1:8080", "945024095")

    @patch("src.napcat_client.requests.post")
    def test_get_image_payload(self, mock_post):
        """get_image 应调用 /get_image，payload 含 file。"""
        mock_post.return_value = MagicMock(
            json=MagicMock(return_value={"status": "ok", "data": {"url": "http://x.com/a.png"}}),
            raise_for_status=MagicMock(),
        )
        result = self.client.get_image("abc.jpg")
        mock_post.assert_called_once()
        args, kwargs = mock_post.call_args
        self.assertEqual(args[0], "http://127.0.0.1:8080/get_image")
        self.assertEqual(kwargs["json"], {"file": "abc.jpg"})
        self.assertEqual(result["url"], "http://x.com/a.png")

    @patch("src.napcat_client.requests.post")
    def test_get_record_payload(self, mock_post):
        """get_record 应调用 /get_record，payload 含 file 和 out_format。"""
        mock_post.return_value = MagicMock(
            json=MagicMock(return_value={"status": "ok", "data": {"file": "/tmp/a.mp3"}}),
            raise_for_status=MagicMock(),
        )
        result = self.client.get_record("rec.amr", out_format="wav")
        args, kwargs = mock_post.call_args
        self.assertEqual(args[0], "http://127.0.0.1:8080/get_record")
        self.assertEqual(kwargs["json"], {"file": "rec.amr", "out_format": "wav"})
        self.assertEqual(result["file"], "/tmp/a.mp3")

    @patch("src.napcat_client.requests.post")
    def test_get_msg_payload(self, mock_post):
        """get_msg 应调用 /get_msg，payload 含 message_id。"""
        mock_post.return_value = MagicMock(
            json=MagicMock(return_value={"status": "ok", "data": {"message_id": "msg123"}}),
            raise_for_status=MagicMock(),
        )
        result = self.client.get_msg("msg123")
        args, kwargs = mock_post.call_args
        self.assertEqual(args[0], "http://127.0.0.1:8080/get_msg")
        self.assertEqual(kwargs["json"], {"message_id": "msg123"})

    @patch("src.napcat_client.requests.post")
    def test_send_poke_payload(self, mock_post):
        """send_poke 应调用 /group_poke，payload 含 group_id 和 user_id。"""
        mock_post.return_value = MagicMock(
            json=MagicMock(return_value={"status": "ok", "data": {}}),
            raise_for_status=MagicMock(),
        )
        self.client.send_poke("169372827")
        args, kwargs = mock_post.call_args
        self.assertEqual(args[0], "http://127.0.0.1:8080/group_poke")
        self.assertEqual(kwargs["json"], {
            "group_id": "945024095",
            "user_id": "169372827",
        })

    @patch("src.napcat_client.requests.post")
    def test_send_group_sign_payload(self, mock_post):
        """send_group_sign 应调用 /send_group_sign，payload 含 group_id。"""
        mock_post.return_value = MagicMock(
            json=MagicMock(return_value={"status": "ok", "data": {}}),
            raise_for_status=MagicMock(),
        )
        self.client.send_group_sign("anyone")
        args, kwargs = mock_post.call_args
        self.assertEqual(args[0], "http://127.0.0.1:8080/send_group_sign")
        self.assertEqual(kwargs["json"], {"group_id": "945024095"})

    @patch("src.napcat_client.requests.post")
    def test_existing_send_group_ai_record_still_works(self, mock_post):
        """原有 send_group_ai_record 接口不应被破坏。"""
        mock_post.return_value = MagicMock(
            json=MagicMock(return_value={"status": "ok"}),
            raise_for_status=MagicMock(),
        )
        self.client.send_group_ai_record("lucy-voice-f34", "你好")
        args, kwargs = mock_post.call_args
        self.assertEqual(args[0], "http://127.0.0.1:8080/send_group_ai_record")
        self.assertEqual(kwargs["json"], {
            "group_id": "945024095",
            "character": "lucy-voice-f34",
            "text": "你好",
        })

    @patch("src.napcat_client.requests.post")
    def test_set_msg_emoji_like_payload(self, mock_post):
        """set_msg_emoji_like payload 应含 message_id 和 emoji_id。"""
        mock_post.return_value = MagicMock(
            json=MagicMock(return_value={"status": "ok"}),
            raise_for_status=MagicMock(),
        )
        self.client.set_msg_emoji_like("msg123", "66")
        args, kwargs = mock_post.call_args
        self.assertEqual(args[0], "http://127.0.0.1:8080/set_msg_emoji_like")
        self.assertEqual(kwargs["json"], {"message_id": "msg123", "emoji_id": "66"})

    @patch("src.napcat_client.requests.post")
    def test_api_error_returns_empty(self, mock_post):
        """API 异常应返回空 dict 不抛出。"""
        mock_post.side_effect = RuntimeError("net error")
        result = self.client.get_image("abc.jpg")
        self.assertEqual(result, {})


if __name__ == "__main__":
    unittest.main()
