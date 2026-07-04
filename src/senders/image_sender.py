"""图片发送器。

通过 NapCat send_group_msg 发送 image 段。
优先级：url > file > base64（base64 自动加 base64:// 前缀存到 file 字段）。
"""
from ..napcat_client import NapCatClient
from ..utils.logger import get_logger

logger = get_logger("image_sender")


class NapCatImageSender:
    """NapCat 图片发送器，实现 ImageSender 协议。"""

    def __init__(self, client: NapCatClient):
        self.client = client

    def send(self, group_id: str, image_data: dict) -> dict:
        """发送图片到指定群。

        Args:
            group_id: 群号（client 已绑定，此处仅日志用）
            image_data: 图片数据，支持 url/file/base64/summary 字段
        """
        seg_data = {}

        url = image_data.get("url")
        file = image_data.get("file")
        base64 = image_data.get("base64")

        if url:
            seg_data["url"] = str(url)
        elif file:
            seg_data["file"] = str(file)
        elif base64:
            b64_str = str(base64)
            if not b64_str.startswith("base64://"):
                b64_str = "base64://" + b64_str
            seg_data["file"] = b64_str
        else:
            logger.warning("image 段缺少 url/file/base64，跳过")
            return {}

        summary = image_data.get("summary")
        if summary is not None and summary != "":
            seg_data["summary"] = str(summary)

        logger.info(f"发送图片 summary={image_data.get('summary', '')}")
        try:
            return self.client.send_group_msg([{"type": "image", "data": seg_data}])
        except Exception as e:
            logger.warning(f"图片发送异常: {e}")
            return {}
