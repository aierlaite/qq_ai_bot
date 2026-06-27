"""大模型 API 调用客户端。"""
import json
import time
import requests
from typing import Optional

from .config import Config
from .utils.logger import get_logger

logger = get_logger("llm_client")


def _extract_json(content: str) -> Optional[str]:
    """从 LLM 返回的 content 中提取合法 JSON 字符串。

    - 非推理模型：content 直接就是 JSON，原样返回。
    - 推理模型（如 gpt-oss）：偶尔会把推理过程泄漏进 content（思考文本 + 末尾 JSON），
      此时扫描所有顶层 {...} 块，取最后一个能成功 json.loads 的（推理模型通常在末尾给出最终答案）。
    - 自动修复中文引号问题：将"和"替换为"（LLM 偶尔会在中文语境中误用）
    """
    if not isinstance(content, str):
        return None
    s = content.strip()
    if not s:
        return None

    # 1. 整体就是合法 JSON
    try:
        json.loads(s)
        return s
    except Exception:
        pass

    # 2. 尝试修复中文引号
    fixed = s.replace('"', '"').replace('"', '"')
    try:
        json.loads(fixed)
        return fixed
    except Exception:
        pass

    # 3. 去除可能的 markdown 代码块包裹后再试
    if s.startswith("```"):
        lines = s.split("\n")
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        inner = "\n".join(lines).strip()
        try:
            json.loads(inner)
            return inner
        except Exception:
            pass
        # 修复中文引号后再试
        fixed_inner = inner.replace('"', '"').replace('"', '"')
        try:
            json.loads(fixed_inner)
            return fixed_inner
        except Exception:
            s = inner

    # 4. 扫描所有顶层 {...} 块，取最后一个能解析成功的
    last_obj = None
    depth = 0
    start = -1
    in_string = False
    escape = False
    for i, ch in enumerate(s):
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}":
            if depth > 0 and start >= 0:
                depth -= 1
                if depth == 0:
                    candidate = s[start:i + 1]
                    # 尝试直接解析
                    try:
                        json.loads(candidate)
                        last_obj = candidate
                    except Exception:
                        pass
                    # 尝试修复中文引号后解析
                    fixed_candidate = candidate.replace('"', '"').replace('"', '"')
                    try:
                        json.loads(fixed_candidate)
                        last_obj = fixed_candidate
                    except Exception:
                        pass
                    start = -1
    return last_obj


class LLMClient:
    """大模型 API 调用封装。

    使用标准多轮对话格式：
    messages = [
        {"role": "system", "content": "人格+协议+早期摘要"},
        {"role": "user", "content": "群消息批次1"},
        {"role": "assistant", "content": "LLM 返回的完整 JSON（含 thought，无论 silent 还是 reply）"},
        {"role": "user", "content": "群消息批次2"},
        {"role": "assistant", "content": "..."},
        ...
    ]
    """

    def __init__(self, config: Config):
        self.api_url = config.llm.api_url
        self.api_key = config.llm.api_key
        self.model = config.llm.model

    def chat(self, system_prompt: str, history_messages: list[dict], new_user_content: str,
             images: list = None) -> Optional[str]:
        """调用大模型，返回 assistant 的原始字符串内容。

        保证返回值要么是合法 JSON 字符串，要么是 None（失败）。
        单次调用失败、content 为 None、或 content 无法解析为 JSON 时，重试 1 次（间隔 2 秒）。
        适配推理模型（如 gpt-oss）：会把推理过程泄漏进 content，本方法会从中提取最终 JSON。

        Args:
            system_prompt: 系统提示词（人格 + 协议 + 早期摘要）
            history_messages: 历史多轮对话（user/assistant 交替，不含 system）
            new_user_content: 本轮新增的 user 内容（群消息批次）
            images: 图片 URL 列表（用于多模态输入，可选）

        Returns:
            合法 JSON 字符串（可直接 json.loads），失败返回 None
        """
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }

        # 拼装完整 messages：system + 历史 + 本轮新 user
        messages = [{"role": "system", "content": system_prompt}]
        messages.extend(history_messages)

        # 多模态：如果有图片，user content 用 OpenAI 多模态格式
        if images:
            user_content = [{"type": "text", "text": new_user_content}]
            for url in images:
                user_content.append({"type": "image_url", "image_url": {"url": url}})
            messages.append({"role": "user", "content": user_content})
        else:
            messages.append({"role": "user", "content": new_user_content})

        payload = {
            "model": self.model,
            "messages": messages,
            "max_tokens": 4096,
            "temperature": 0.55,
        }
        # 注：曾用 response_format json_object 强制 JSON，但 NVIDIA integrate API 的
        # gpt-oss-120b 在带多轮历史（含 assistant）时与此参数冲突，会返回 content=None（实测 0/3）。
        # 去掉后 3/3 正常。改为不设 response_format，靠 system prompt 强调"严格返回 JSON" +
        # _extract_json 容错提取 + parser 的 fallback silent 保证健壮性（符合任务描述的容错要求）。

        # 最多重试 2 次（共 2 次请求）
        for attempt in range(2):
            try:
                resp = requests.post(self.api_url, headers=headers, json=payload, timeout=300)
                resp.raise_for_status()
                data = resp.json()
                msg = data["choices"][0]["message"]
                content = msg.get("content")
                finish = data["choices"][0].get("finish_reason")
                has_reasoning = bool(msg.get("reasoning") or msg.get("reasoning_content"))

                if content is None:
                    # 推理模型偶尔 content 为 None：推理耗尽预算或被过滤
                    logger.warning(
                        f"LLM 返回 content 为 None（finish={finish}, "
                        f"reasoning={'有' if has_reasoning else '无'}），"
                        f"{'2 秒后重试' if attempt == 0 else '已达最大重试'}"
                    )
                    if attempt == 0:
                        time.sleep(2)
                        continue
                    return None

                # 从 content 提取合法 JSON（适配推理模型把推理泄漏进 content 的情况）
                extracted = _extract_json(content)
                if extracted is not None:
                    if extracted != content.strip():
                        logger.info(
                            f"已从 content 中提取 JSON（原长 {len(content)}, "
                            f"reasoning={'有' if has_reasoning else '无'}）"
                        )
                    else:
                        logger.debug(f"LLM 返回: {content[:200]}")
                    return extracted

                # content 非空但无法提取 JSON
                # 记录完整长度和实际内容以便调试
                logger.warning(
                    f"LLM 返回内容无法解析为 JSON（finish={finish}, "
                    f"reasoning={'有' if has_reasoning else '无'}），"
                    f"总长度={len(content)}，"
                    f"完整 raw: {content!r}，"
                    f"{'2 秒后重试' if attempt == 0 else '已达最大重试'}"
                )
                if attempt == 0:
                    time.sleep(2)
                    continue
                return None
            except requests.RequestException as e:
                if attempt == 0:
                    logger.warning(f"LLM 第 1 次请求失败: {e}，2 秒后重试")
                    time.sleep(2)
                else:
                    logger.error(f"LLM 第 2 次请求仍失败: {e}")
            except (KeyError, IndexError) as e:
                logger.error(f"LLM 响应解析失败: {e}")
                return None
        return None
