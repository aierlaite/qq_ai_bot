"""图片发送器实现。

通过 send_group_msg + image 段发送图片，支持 url/file/base64 三种来源。
"""
from ..napcat_client import NapCatClient
from ..utils.logger import get_logger

logger = get_logger("image_sender")


class NapCatImageSender:
    """NapCat 图片发送器，构造 image 段通过 send_group_msg 发送。"""

    def __init__(self, client: NapCatClient):
        self.client = client

    def send(self, group_id: str, image_data: dict) -> dict:
        """发送图片到群。

        Args:
            group_id: 目标群号（当前实现由 client 内部持有，参数保留兼容）
            image_data: 含 url / file / base64 / summary 字段
                - url: 网络图片 URL
                - file: 本地图片绝对路径或 file:// 协议
                - base64: base64 编码的图片数据（不带 data: 前缀）
                - summary: 图片描述（可选，NapCat 部分版本支持）

        Returns:
            NapCat API 响应
        """
        url = image_data.get("url", "")
        file = image_data.get("file", "")
        base64 = image_data.get("base64", "")
        summary = image_data.get("summary", "")

        # 构造 image 段，优先级：url > file > base64
        data = {}
        if url:
            data["url"] = url
        elif file:
            data["file"] = file
        elif base64:
            # NapCat 接受 base64:// 前缀
            if not base64.startswith("base64://"):
                data["file"] = f"base64://{base64}"
            else:
                data["file"] = base64
        else:
            logger.warning("image 段缺少 url/file/base64，跳过")
            return {}

        # summary 可选（部分 NapCat 版本支持，作为图片的 fallback 文字描述）
        if summary:
            data["summary"] = summary

        try:
            result = self.client.send_group_msg([{"type": "image", "data": data}])
            logger.info(f"图片已发送：summary={summary[:30] if summary else '(无)'}")
            return result
        except Exception as e:
            logger.error(f"图片发送失败: {e}")
            return {}


# 向后兼容
EmptyImageSender = NapCatImageSender
