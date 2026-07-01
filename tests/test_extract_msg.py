"""测试 main.py 中的消息段解析函数：_extract_text_from_msg / _extract_images_from_msg / _msg_to_text。"""
import unittest

from tests._path_setup import _  # noqa: F401
import main


def _msg(segments):
    """构造含 message 字段的消息 dict。"""
    return {"message": segments, "raw_message": ""}


class TestExtractText(unittest.TestCase):
    def test_text_segment(self):
        self.assertEqual(main._extract_text_from_msg(_msg([
            {"type": "text", "data": {"text": "你好"}},
        ])), "你好")

    def test_at_segment_uses_name(self):
        """at 段应输出 @昵称。"""
        result = main._extract_text_from_msg(_msg([
            {"type": "at", "data": {"qq": "123", "name": "忆雨"}},
        ]))
        self.assertEqual(result, "@忆雨")

    def test_at_segment_fallback_qq(self):
        """at 段无 name 时回退到 @qq。"""
        result = main._extract_text_from_msg(_msg([
            {"type": "at", "data": {"qq": "123"}},
        ]))
        self.assertEqual(result, "@123")

    def test_face_segment(self):
        """face 段应输出 [QQ表情:id]。"""
        result = main._extract_text_from_msg(_msg([
            {"type": "face", "data": {"id": "66"}},
        ]))
        self.assertEqual(result, "[QQ表情:66]")

    def test_mface_uses_emoji_name(self):
        """mface 段优先用 emoji_name。"""
        result = main._extract_text_from_msg(_msg([
            {"type": "mface", "data": {"emoji_name": "偷笑", "summary": "fallback"}},
        ]))
        self.assertEqual(result, "[表情包:偷笑]")

    def test_mface_fallback_summary(self):
        """mface 无 emoji_name 时用 summary。"""
        result = main._extract_text_from_msg(_msg([
            {"type": "mface", "data": {"summary": "滑稽"}},
        ]))
        self.assertEqual(result, "[表情包:滑稽]")

    def test_mface_no_keyword(self):
        """mface 无任何关键词时显示 [表情包:表情包]。"""
        result = main._extract_text_from_msg(_msg([
            {"type": "mface", "data": {}},
        ]))
        self.assertEqual(result, "[表情包:表情包]")

    def test_image_with_summary(self):
        """image 段有 summary（非默认值）应附带。"""
        result = main._extract_text_from_msg(_msg([
            {"type": "image", "data": {"url": "http://x.com/a.png", "summary": "猫咪"}},
        ]))
        self.assertEqual(result, "[图片:猫咪]")

    def test_image_default_placeholder(self):
        """image 段 summary 为 [图片] 或空时只显示 [图片]。"""
        result = main._extract_text_from_msg(_msg([
            {"type": "image", "data": {"summary": "[图片]"}},
        ]))
        self.assertEqual(result, "[图片]")

    def test_record_with_transcription(self):
        """record 段有 text 字段应显示 [语音转写:文本]。"""
        result = main._extract_text_from_msg(_msg([
            {"type": "record", "data": {"text": "你好啊"}},
        ]))
        self.assertEqual(result, "[语音转写:你好啊]")

    def test_record_no_transcription(self):
        """record 段无 text 只显示 [语音]。"""
        result = main._extract_text_from_msg(_msg([
            {"type": "record", "data": {}},
        ]))
        self.assertEqual(result, "[语音]")

    def test_reply_segment_skipped(self):
        """reply 段不应出现在文本中。"""
        result = main._extract_text_from_msg(_msg([
            {"type": "reply", "data": {"id": "msg123"}},
            {"type": "text", "data": {"text": "回复内容"}},
        ]))
        self.assertEqual(result, "回复内容")

    def test_mixed_segments(self):
        """混合段：text + at + face + mface。"""
        result = main._extract_text_from_msg(_msg([
            {"type": "text", "data": {"text": "嗨 "}},
            {"type": "at", "data": {"qq": "111", "name": "小春"}},
            {"type": "face", "data": {"id": "99"}},
            {"type": "mface", "data": {"emoji_name": "偷笑"}},
        ]))
        self.assertEqual(result, "嗨 @小春[QQ表情:99][表情包:偷笑]")

    def test_poke_segment(self):
        """poke 段应显示 [戳一戳]。"""
        result = main._extract_text_from_msg(_msg([
            {"type": "poke", "data": {}},
        ]))
        self.assertEqual(result, "[戳一戳]")

    def test_unknown_segment(self):
        """未知段应显示 [type]。"""
        result = main._extract_text_from_msg(_msg([
            {"type": "weird_thing", "data": {}},
        ]))
        self.assertEqual(result, "[weird_thing]")


class TestExtractImages(unittest.TestCase):
    def test_extract_image_url(self):
        urls = main._extract_images_from_msg(_msg([
            {"type": "image", "data": {"url": "http://x.com/a.png"}},
        ]))
        self.assertEqual(urls, ["http://x.com/a.png"])

    def test_extract_mface_url(self):
        """mface 段的 url 也应被提取（多模态识别）。"""
        urls = main._extract_images_from_msg(_msg([
            {"type": "mface", "data": {"url": "http://x.com/mface.png"}},
        ]))
        self.assertEqual(urls, ["http://x.com/mface.png"])

    def test_skip_empty_url(self):
        """url 为空应跳过。"""
        urls = main._extract_images_from_msg(_msg([
            {"type": "image", "data": {"url": ""}},
            {"type": "image", "data": {"url": "http://x.com/b.png"}},
        ]))
        self.assertEqual(urls, ["http://x.com/b.png"])

    def test_no_image_returns_empty(self):
        urls = main._extract_images_from_msg(_msg([
            {"type": "text", "data": {"text": "无图"}},
        ]))
        self.assertEqual(urls, [])


class TestMsgToText(unittest.TestCase):
    def test_string(self):
        self.assertEqual(main._msg_to_text("你好"), "你好")

    def test_text_dict(self):
        self.assertEqual(main._msg_to_text(
            {"type": "text", "data": {"text": "hi"}}
        ), "hi")

    def test_face_dict(self):
        """face 段摘要应包含 id。"""
        self.assertEqual(main._msg_to_text(
            {"type": "face", "data": {"id": "66"}}
        ), "[QQ表情:66]")

    def test_mface_dict(self):
        """mface 段摘要应包含关键词。"""
        result = main._msg_to_text(
            {"type": "mface", "data": {"emoji_name": "偷笑"}}
        )
        self.assertEqual(result, "[表情包:偷笑]")

    def test_image_dict(self):
        self.assertEqual(main._msg_to_text(
            {"type": "image", "data": {}}
        ), "[图片]")

    def test_at_dict(self):
        self.assertEqual(main._msg_to_text(
            {"type": "at", "data": {"qq": "123"}}
        ), "@123")

    def test_voice_dict(self):
        self.assertEqual(main._msg_to_text(
            {"type": "voice", "data": {"text": "你好"}}
        ), "[语音:你好]")

    def test_unknown_dict(self):
        self.assertEqual(main._msg_to_text(
            {"type": "unknown", "data": {}}
        ), "[unknown]")

    def test_non_dict_non_str(self):
        """None 等非 dict/str 应返回空字符串。"""
        self.assertEqual(main._msg_to_text(None), "")


if __name__ == "__main__":
    unittest.main()
