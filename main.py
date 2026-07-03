"""QQ 群聊机器人主入口。

流程：
- 被动触发：群聊消息 -> 入 fast_buffer -> 评分 -> 触发决策（硬因子短冷却立即 / 软因子静默窗口兜底）
              -> LLM 调用（_llm_lock 串行）-> drain buffer 到 pending -> 结果处理
- 主动触发：定时器唤醒 -> LLM 调用（无新消息，让 LLM 自主决定要不要主动开口）
- 延迟回复：LLM 输出 reply_delay_minutes -> 消息暂存 -> 下次触发时重新加入 pending

并发模型：
- 接收线程（webhook）只写 fast_buffer（HistoryManager 内 _buffer_lock 保护，持锁极短）
- LLM 工作线程持 _llm_lock，串行执行 drain -> LLM -> 发送
- 静默窗口定时器：每条新消息重置，7s 无新消息则触发兜底 LLM 调用
"""
import time
import random
import threading
import json
from typing import Optional

from src.config import load_config
from src.napcat_client import NapCatClient, NapCatWebhookServer
from src.llm_client import LLMClient
from src.history import HistoryManager
from src.trigger import TriggerEvaluator
from src.attribution import AttributionManager
from src.affinity import AffinityManager
from src.persona import PersonaRenderer
from src.parser import parse_and_validate
from src.scheduler import ActiveScheduler
from src.senders.message_sender import NapCatMessageSender
from src.senders.voice_sender import AIRecordVoiceSender, LocalFileVoiceSender
from src.senders.image_sender import NapCatImageSender
from src.senders.emoji_reactor import NapCatEmojiReactor
from src.utils.logger import get_logger

logger = get_logger("main")

# 冷却配置
HARD_COOLDOWN_SECONDS = 4       # 硬因子（@/提问）触发冷却，距上次回复 <2s 推迟
SOFT_COOLDOWN_MIN = 12          # 软因子触发冷却下限（上次回复后至少 12 秒才能再回复）
SOFT_COOLDOWN_MAX = 90          # 软因子触发冷却上限
QUIET_WINDOW_SECONDS = 20       # 静默窗口：N 秒无新消息后兜底触发


class GroupBot:
    """单个群的机器人控制器。"""

    def __init__(self, group_id: str, config, llm: LLMClient, persona_renderer: PersonaRenderer):
        self.group_id = group_id
        self.config = config

        # 按群号隔离状态目录
        self.state_dir = f"state/{group_id}"

        # 核心组件（群独立）
        self.napcat = NapCatClient(config.napcat.base_url, group_id)
        self.llm = llm
        self.history = HistoryManager(config.trigger, state_dir=self.state_dir)
        self.attribution = AttributionManager(config, state_dir=self.state_dir)
        protected_qq = (self.config.special_members.target_qq
                        if self.config.special_members else "")
        self.affinity = AffinityManager(state_dir=self.state_dir, protected_qq=protected_qq)
        self.persona_renderer = persona_renderer
        self.scheduler = ActiveScheduler(config, state_dir=self.state_dir)

        # Sender 实现
        self.message_sender = NapCatMessageSender(self.napcat)
        self.ai_voice_sender = AIRecordVoiceSender(
            self.napcat, self.config.voice.ai_record_character, self.config.voice.fallback_to_text
        )
        self.local_voice_sender = LocalFileVoiceSender(self.napcat)
        self.image_sender = NapCatImageSender(self.napcat)
        self.emoji_reactor = NapCatEmojiReactor(self.napcat)

        # 运行时状态
        self.self_qq: str = ""
        self.self_nickname: str = ""
        self.trigger_evaluator: Optional[TriggerEvaluator] = None
        self.last_reply_time: float = 0.0
        # LLM 调用串行锁：保证同一时刻只有一个 LLM 调用（替代原 _msg_lock 在 LLM 部分的作用）
        # 接收线程不再持此锁，只写 fast_buffer
        self._llm_lock = threading.Lock()
        # 静默窗口定时器：每条新消息重置，N 秒无新消息后兜底触发 LLM
        self._quiet_timer: Optional[threading.Timer] = None
        self._quiet_timer_lock = threading.Lock()
        # 标记：自上次 LLM 调用以来是否有消息达到 peek 阈值（静默窗口兜底时检查）
        self._peek_qualified = False
        # 注入 LLM 摘要器，对话压缩时生成真实摘要而非朴素截断
        self.history.set_summarizer(self._summarize_history)

    def _summarize_history(self, old_messages: list[dict], prev_summary: str) -> str:
        """用 LLM 对早期对话做真实摘要，保留关键信息。

        Args:
            old_messages: 即将被丢弃的早期 user/assistant 消息对
            prev_summary: 之前的摘要（要承接）
        Returns:
            新摘要字符串
        """
        parts = []
        for i in range(0, len(old_messages), 2):
            u = old_messages[i]["content"][:600] if i < len(old_messages) else ""
            a = old_messages[i + 1]["content"][:400] if i + 1 < len(old_messages) else ""
            parts.append(f"## 第{i // 2 + 1}轮\n用户看到的消息:\n{u}\n雪菜的回复(JSON):\n{a}")
        conversation_text = "\n\n".join(parts[-12:])

        system = (
            "你是对话摘要器。把以下早期对话压缩成简短摘要（800字以内），"
            "保留关键信息：涉及的人物（QQ/昵称）、讨论的话题、雪菜的情绪变化、"
            "关系变化（亲密度升降）、重要约定或承诺、未解决的话题。"
            "用简洁的叙述写，不要列点。只输出摘要文本，不要其他内容。"
        )
        user_content = f"之前的摘要：\n{prev_summary}\n\n需要压缩的早期对话：\n{conversation_text}"
        try:
            resp = self.llm.chat(system, [], user_content)
            return resp.strip()
        except Exception as e:
            logger.warning(f"摘要 LLM 调用失败: {e}")
            return ""

    def warmup(self):
        """启动预热。"""
        self.napcat.warmup()
        self.self_qq = str(self.napcat.self_info.get("user_id", ""))
        self.self_nickname = self.napcat.self_info.get("nickname", "")
        self.trigger_evaluator = TriggerEvaluator(
            self.config, self.history, self.self_qq, self.config.persona.name,
            affinity_manager=self.affinity,
        )
        logger.info(f"预热完成，机器人 {self.self_nickname}({self.self_qq})")

    def on_group_message(self, msg: dict):
        """处理收到的群消息（接收线程，无 _llm_lock）。

        职责：
        1. 入 fast_buffer（HistoryManager 内 _buffer_lock 保护，持锁极短）
        2. 评分（只读配置/亲密度，无锁）
        3. 触发决策：
           - 硬因子（@/提问）且距上次回复 ≥ HARD_COOLDOWN_SECONDS → 立即尝试触发
           - 其他 → 只入 buffer，由静默窗口兜底
        4. 无论如何重置静默定时器（每条新消息都推迟兜底触发）
        """
        try:
            sender_qq = str(msg.get("user_id", ""))
            sender_nick = self.napcat.get_nickname(sender_qq)
            content = _extract_text_from_msg(msg) or msg.get("raw_message", "")
            images = _extract_images_from_msg(msg)
            msg_id = str(msg.get("message_id", ""))

            # 1. 入 fast_buffer（无 _llm_lock，仅 HistoryManager 内 _buffer_lock）
            self.history.append_group_message(sender_qq, sender_nick, content, msg_id, images=images)

            # 2. 评分（接收线程，只读）
            score, soft_factors = self.trigger_evaluator.evaluate(msg)
            is_hard = self._is_hard_trigger(msg, content)
            if self.trigger_evaluator.should_peek(score):
                self._peek_qualified = True
            logger.debug(f"消息评分={score} hard={is_hard} soft_factors={[f.name for f in soft_factors]}")

            # 3. 触发决策
            if is_hard:
                self._try_trigger_immediate(hard=True)
            # 软因子不立即触发，等静默窗口兜底

            # 4. 重置静默定时器（无论硬软，新消息都推迟兜底触发）
            self._reschedule_quiet_trigger()

        except Exception as e:
            logger.error(f"处理消息异常: {e}", exc_info=True)

    def _is_hard_trigger(self, msg: dict, content: str) -> bool:
        """判断是否硬因子触发（@bot 或提问语气）。"""
        if self.trigger_evaluator._check_at_me(msg):
            return True
        if self.trigger_evaluator._check_question_to_me(content):
            return True
        return False

    def _try_trigger_immediate(self, hard: bool = False):
        """立即尝试触发 LLM（硬因子路径）。

        冷却检查：距上次回复 < HARD_COOLDOWN_SECONDS 则跳过（让静默窗口兜底）。
        非阻塞抢 _llm_lock：抢不到说明已有 LLM 调用在进行，让静默窗口兜底。
        """
        now = time.time()
        elapsed = now - self.last_reply_time
        cooldown = HARD_COOLDOWN_SECONDS if hard else SOFT_COOLDOWN_MIN
        if elapsed < cooldown:
            logger.debug(f"硬因子触发但冷却中（elapsed={elapsed:.1f}s < {cooldown}s），等静默窗口兜底")
            return

        # 非阻塞尝试拿 LLM 锁
        if not self._llm_lock.acquire(blocking=False):
            logger.debug("硬因子触发但 LLM 锁被占用，等静默窗口兜底")
            return

        try:
            self._peek_qualified = False
            self._run_llm_cycle(soft_factors=None, is_active=False)
        finally:
            self._llm_lock.release()

    def _reschedule_quiet_trigger(self, delay: float = QUIET_WINDOW_SECONDS):
        """重置静默窗口定时器：N 秒后若仍无新消息则兜底触发。

        每条新消息都调用此方法，cancel 旧定时器并重设。
        """
        with self._quiet_timer_lock:
            if self._quiet_timer is not None:
                self._quiet_timer.cancel()
            timer = threading.Timer(delay, self._on_quiet_timeout)
            timer.daemon = True
            timer.start()
            self._quiet_timer = timer

    def _on_quiet_timeout(self):
        """静默窗口到期：兜底触发 LLM。

        冷却检查：距上次回复 < SOFT_COOLDOWN_MIN 则重调度到冷却到期。
        评分检查：自上次 LLM 调用以来无消息达到 peek 阈值则跳过 LLM 调用，
                  但仍 drain 群消息到历史（让 bot 以后能看到完整的群聊上下文）。
        阻塞拿 _llm_lock（此时已静默 N 秒，可等待）。
        """
        try:
            now = time.time()
            elapsed = now - self.last_reply_time
            if elapsed < SOFT_COOLDOWN_MIN:
                # 还在软冷却内，重调度到冷却到期
                remaining = SOFT_COOLDOWN_MIN - elapsed
                logger.debug(f"静默窗口到期但软冷却中（elapsed={elapsed:.1f}s），{remaining:.1f}s 后再触发")
                self._reschedule_quiet_trigger(delay=remaining)
                return

            # 评分检查：没有达到 peek 阈值的消息
            if not self._peek_qualified:
                # 仍 drain 群消息到历史，让 bot 以后能看到完整的群聊上下文（不只是自己参与过的对话）
                with self._llm_lock:
                    self._peek_qualified = False
                    drained = self.history.drain_buffer_to_pending()
                    if drained > 0:
                        user_content = self.history.consume_pending_into_user()
                        self.history.append_turn(
                            user_content,
                            '{"thought":"(只是看了看，没什么想说的)","action":"silent","messages":[]}'
                        )
                        logger.debug(f"静默窗口到期，{drained} 条群消息已记录到历史（未触发 LLM）")
                return

            # 阻塞拿 LLM 锁
            with self._llm_lock:
                self._peek_qualified = False
                self._run_llm_cycle(soft_factors=None, is_active=False)
        except Exception as e:
            logger.error(f"静默窗口兜底触发异常: {e}", exc_info=True)

    def on_active_trigger(self):
        """主动触发回调（由调度器调用）。

        阻塞拿 _llm_lock 后调用 LLM，标记 is_active=True 让 LLM 知道这是主动检查。
        """
        try:
            logger.info("主动触发：执行 LLM 调用")
            with self._llm_lock:
                self._peek_qualified = False
                self._run_llm_cycle(soft_factors=None, is_active=True)
        except Exception as e:
            logger.error(f"主动触发异常: {e}", exc_info=True)

    def _run_llm_cycle(self, soft_factors, is_active: bool):
        """LLM 工作循环（调用方已持 _llm_lock）。

        流程：
        1. drain fast_buffer → pending（原子，本次 LLM 看到的所有新消息）
        2. 检查延迟回复到期 → 加入 pending
        3. 若 pending 空（且非主动触发）→ 跳过
        4. 调用 LLM → 解析 → 处理结果
        """
        # 1. drain fast_buffer
        drained = self.history.drain_buffer_to_pending()
        if drained > 0:
            logger.debug(f"drain {drained} 条消息到 pending")

        # 2. 延迟回复到期
        due_count = self.history.pop_due_delayed_into_pending()
        if due_count > 0:
            logger.info(f"延迟回复到期，{due_count} 条消息已加入 pending")

        # 3. pending 空检查（主动触发允许空 pending，让 LLM 决定是否主动开口）
        if not self.history.pending_group_msgs and not is_active:
            logger.debug("pending 为空，跳过 LLM 调用")
            return

        # 4. 调用 LLM（原 _invoke_llm 逻辑）
        self._invoke_llm(soft_factors, is_active)

    def _invoke_llm(self, soft_factors, is_active: bool = False):
        """调用 LLM 并处理结果。使用多轮对话格式。

        Args:
            soft_factors: 触发评分软因子（新架构下接收线程评分结果不再透传，恒为 None）
            is_active: 是否为主动触发（影响 user content 渲染）
        """
        # 构建 system prompt（含早期摘要）
        summary = self.history.get_summary()
        system_prompt = self.persona_renderer.render_system_prompt(summary)

        # 取历史 messages（user/assistant 交替，不含 system）
        history_messages = self.history.get_messages_for_llm()

        # 构建本轮 user content：群成员列表 + pending 群消息
        member_list = self._build_member_list()
        pending_text = self.history.build_user_content()
        pending_images = self.history.get_pending_images()
        new_user_content = self.persona_renderer.render_user_content(
            pending_text, member_list, self.self_nickname, self.self_qq,
            is_active=is_active,
        )

        # 调用 LLM（传入完整历史 + 本轮新 user + 图片）
        if pending_images:
            logger.info(f"本轮含 {len(pending_images)} 张图片，使用多模态输入")
        raw_result = self.llm.chat(system_prompt, history_messages, new_user_content,
                                   images=pending_images)
        if raw_result is None:
            logger.warning("LLM 调用失败，本轮跳过")
            # pending 留待下次触发再拼入（消息不丢失）
            return

        # 解析校验（在 consume 之前解析，以便根据 reply_delay 决定是否存到 delayed_replies）
        parsed = parse_and_validate(raw_result)

        logger.info(f"LLM 返回 action={parsed.action} thought={parsed.thought}"
                    f"{' reply_delay=' + str(parsed.reply_delay_minutes) + 'min' if parsed.reply_delay_minutes > 0 else ''}"
                    f"{' [主动触发]' if is_active else ''}")

        # 延迟回复处理：LLM 觉得"等会再回"，把这批消息存到 delayed_replies
        # 注意：主动触发时 pending 可能为空，stash_pending_as_delayed 内部会检查
        if parsed.reply_delay_minutes > 0 and parsed.action == "silent":
            self.history.stash_pending_as_delayed(parsed.reply_delay_minutes)

        # 落地本轮 user/assistant 对话到历史
        # consume pending（清空 buffer，内容已进入 messages）
        # 注：consume 的返回值是渲染前 pending 文本，但落地用 render 后的 new_user_content
        self.history.consume_pending_into_user()
        # 校验 raw_result 是否为合法 JSON：推理模型偶尔会把推理文本泄漏到 content，
        # 直接存入会污染多轮上下文，导致后续调用持续 content=None。非法时存入占位 silent。
        assistant_to_store = raw_result
        try:
            json.loads(raw_result.strip() if isinstance(raw_result, str) else "")
        except (json.JSONDecodeError, TypeError, ValueError):
            assistant_to_store = '{"thought":"(本轮返回格式异常，已忽略)","action":"silent"}'
            logger.warning("LLM 返回非 JSON，历史存入占位 silent，避免污染多轮上下文")
        self.history.append_turn(new_user_content, assistant_to_store)

        # 结果处理（新架构下 soft_factors 恒为 None，归因跳过）
        self._handle_result(parsed, soft_factors)

    def _handle_result(self, parsed, soft_factors):
        """处理 LLM 结果：执行动作 -> 写回历史 -> 亲密度 -> 归因。

        Args:
            soft_factors: 触发评分软因子（主动触发时为 None，归因跳过）
        """
        # 延迟：delay_seconds 叠加 0.3-1.2 秒/字的随机抖动（模拟"打字中"）
        if parsed.delay_seconds > 0 or parsed.messages:
            total_text_len = sum(len(_msg_to_text(m)) for m in parsed.messages)
            jitter = random.uniform(0.3, 1.2) * max(1, total_text_len // 5)  # 每5字一抖动段
            total_delay = parsed.delay_seconds + min(jitter, 8.0)  # 抖动上限 8 秒
            if total_delay > 0:
                logger.debug(f"延迟发送 {total_delay:.1f}s (delay={parsed.delay_seconds} jitter={jitter:.1f})")
                time.sleep(total_delay)

        if parsed.action == "silent":
            # 不发送，但仍更新归因（主动触发时 soft_factors=None，跳过）
            if soft_factors is not None:
                self.attribution.update(soft_factors, "silent")
            self.affinity.apply_delta(parsed.affinity_delta)
            return

        if parsed.action == "react":
            # 预留接口
            msg_id = self.history.get_msg_id_by_index(parsed.react_target_msg_index)
            self.emoji_reactor.react(self.config.napcat.group_id, msg_id, parsed.react_emoji_id)
            if soft_factors is not None:
                self.attribution.update(soft_factors, "react")
            self.affinity.apply_delta(parsed.affinity_delta)
            return

        # reply / multi_reply
        # 强制合并：messages 超过 2 条时，将多条纯文本合并为 1-2 条
        merged_messages = self._merge_messages(parsed.messages)
        # _send_messages 内部每条发送完成后会逐条 append 到 fast_buffer（is_bot=True），
        # 与此期间群成员的新消息按真实 append 顺序混合，下一轮 drain 时进入 pending。
        self._send_messages(merged_messages)
        self.last_reply_time = time.time()

        # 亲密度更新
        self.affinity.apply_delta(parsed.affinity_delta)

        # 归因更新（主动触发时 soft_factors=None，跳过）
        if soft_factors is not None:
            self.attribution.update(soft_factors, parsed.action)

    def _merge_messages(self, messages: list) -> list:
        """强制合并消息：超过 2 条时，将纯文本消息合并为最多 2 条，内容不删减。"""
        if len(messages) <= 2:
            return messages

        # 分离纯文本和非文本消息
        text_parts = []
        non_text = []
        for msg in messages:
            if isinstance(msg, str):
                text_parts.append(msg)
            elif isinstance(msg, dict) and msg.get("type") == "text":
                text_parts.append(msg["data"].get("text", ""))
            else:
                non_text.append(msg)

        # 合并所有纯文本为一条，非文本段保留（但总量仍限制 2 条）
        merged = []
        if text_parts:
            merged_text = "\n".join(text_parts)
            merged.append(merged_text)
        if non_text:
            merged.append(non_text[0])  # 只保留第一个非文本段

        # 如果合并后仍超过 2 条，截断到 2 条
        return merged[:2]

    def _send_messages(self, messages: list):
        """发送消息列表，带间隔。

        每条消息发送完成后立即 append 到 fast_buffer（is_bot=True），
        与此期间接收线程写入的群消息按真实 append 顺序混合，
        保证下一轮 LLM 看到的发言顺序 = 真实群聊发言顺序。
        multi_reply 逐条 append，中间间隔期间群成员插话会自然夹在 bot 消息之间。
        """
        segments_list = self.message_sender.build_segments(messages, self.history)
        if not segments_list:
            logger.warning(f"build_segments 返回空列表，messages={messages}，无内容发送")
            return
        for i, segs in enumerate(segments_list):
            # 处理特殊段
            handled = False
            for seg in segs:
                if seg.get("type") == "forward":
                    data = seg.get("data", {})
                    self.napcat.send_group_forward_msg(data.get("messages", []), data.get("title", ""))
                    logger.info(f"发送 forward 段")
                    handled = True
                    break
                if seg.get("type") == "image":
                    self.image_sender.send(self.config.napcat.group_id, seg.get("data", {}))
                    logger.info(f"发送 image 段")
                    handled = True
                    break
                if seg.get("type") == "voice":
                    data = seg.get("data", {})
                    channel = data.get("channel", "ai_record")
                    logger.info(f"发送 voice 段: channel={channel}, text={data.get('text', '')[:30]}")
                    if channel == "ai_record":
                        self.ai_voice_sender.send(self.config.napcat.group_id, data)
                    elif channel == "local_file":
                        self.local_voice_sender.send(self.config.napcat.group_id, data)
                    handled = True
                    break
                if seg.get("type") == "poke":
                    qq = seg.get("data", {}).get("qq", "")
                    if qq:
                        self.napcat.send_poke(qq)
                        logger.info(f"发送 poke 段: qq={qq}")
                    handled = True
                    break
            if handled:
                # 特殊段也记入 fast_buffer（语音/图片/转发都算一条 bot 发言）
                self._append_bot_reply_to_buffer(messages[i])
                continue

            # 普通消息段
            normal_segs = [s for s in segs if s.get("type") not in ("forward", "image", "voice", "poke")]
            if normal_segs:
                seg_types = [s.get("type") for s in normal_segs]
                text_preview = ""
                for s in normal_segs:
                    if s.get("type") == "text":
                        text_preview = s.get("data", {}).get("text", "")[:50]
                        break
                logger.info(f"发送消息: types={seg_types}, text={text_preview}")
                self.message_sender.send_group_message(self.config.napcat.group_id, normal_segs)
            else:
                logger.warning(f"消息 {i} 无可发送的普通段，segs={segs}")

            # 逐条 append 到 fast_buffer（与群消息按真实时间顺序混合）
            self._append_bot_reply_to_buffer(messages[i])

            # 多条消息间隔
            if i < len(segments_list) - 1:
                time.sleep(random.uniform(0.8, 2.5))

    def _append_bot_reply_to_buffer(self, msg):
        """把单条 bot 发言追加到 fast_buffer（is_bot=True）。

        在 _send_messages 每条发送完成后调用，确保发言顺序与真实群聊一致。
        文本摘要复用 _msg_to_text，特殊段（image/voice/forward）也能得到合理摘要。
        """
        msg_text = _msg_to_text(msg)
        self.history.append_group_message(
            self.self_qq, self.self_nickname, msg_text, "", is_bot=True
        )

    def _build_member_list(self) -> list:
        """构建传给 LLM 的群成员列表（含亲密度）。"""
        result = []
        for qq, info in self.napcat.member_cache.items():
            result.append({
                "qq": qq,
                "nickname": info.get("card") or info.get("nickname") or qq,
                "role": info.get("role", "member"),
                "affinity": self.affinity.get(qq),
            })
        return result

    def start_scheduler(self):
        """启动主动触发调度器。"""
        if self.config.active_trigger and self.config.active_trigger.enabled:
            self.scheduler.start(self.on_active_trigger)
            logger.info(f"[群{self.group_id}] 主动触发调度器已启动：{self.config.active_trigger.min_interval_minutes}-"
                        f"{self.config.active_trigger.max_interval_minutes} 分钟随机，"
                        f"深夜 {self.config.active_trigger.night_start_hour}:00-"
                        f"{self.config.active_trigger.night_end_hour}:00 禁用")


class MultiGroupBot:
    """多群机器人协调器。"""

    def __init__(self, config_path: str = "config.yaml"):
        self.config = load_config(config_path)

        # 共享组件（跨群共用）
        self.llm = LLMClient(self.config)
        self.persona_renderer = PersonaRenderer(self.config)

        # 为每个群创建独立的 GroupBot
        self.group_bots: dict[str, GroupBot] = {}
        for group_id in self.config.napcat.group_ids:
            bot = GroupBot(group_id, self.config, self.llm, self.persona_renderer)
            self.group_bots[group_id] = bot

    def on_message(self, group_id: str, msg: dict):
        """Webhook 回调：按 group_id 分发到对应 GroupBot。"""
        bot = self.group_bots.get(group_id)
        if bot is None:
            logger.debug(f"收到非目标群消息：{group_id}，丢弃")
            return
        bot.on_group_message(msg)

    def run(self, webhook_host: str = "0.0.0.0", webhook_port: int = 8081):
        """启动机器人。"""
        # 预热所有群
        for group_id, bot in self.group_bots.items():
            bot.warmup()
            bot.start_scheduler()
            logger.info(f"[群{group_id}] 机器人就绪")

        # 启动共享 webhook 服务器
        server = NapCatWebhookServer(
            webhook_host, webhook_port, self.on_message,
            target_group_ids=list(self.group_bots.keys()),
        )
        group_ids_str = ", ".join(self.group_bots.keys())
        logger.info(f"机器人启动（监听群：{group_ids_str}）")
        server.start()


def _extract_text_from_msg(msg: dict) -> str:
    """从消息段提取纯文本（图片/语音/表情等转为占位标记）。"""
    parts = []
    for seg in msg.get("message", []):
        seg_type = seg.get("type", "")
        data = seg.get("data", {})
        if seg_type == "text":
            parts.append(data.get("text", ""))
        elif seg_type == "at":
            qq = data.get("qq", "")
            # at 段保留 @昵称 形式，让 LLM 看到谁被 @
            name = data.get("name", "") or qq
            parts.append(f"@{name}")
        elif seg_type == "face":
            # QQ 经典表情，标注 ID 让 LLM 知道用了哪个
            face_id = data.get("id", "")
            parts.append(f"[QQ表情:{face_id}]")
        elif seg_type == "mface":
            # QQ 商城表情包
            keyword = data.get("emoji_name") or data.get("summary") or "表情包"
            parts.append(f"[表情包:{keyword}]")
        elif seg_type == "image":
            # 图片：url 可能为空（NapCat 部分场景），有 summary 时附带
            summary = data.get("summary", "")
            if summary and summary != "[图片]":
                parts.append(f"[图片:{summary}]")
            else:
                parts.append("[图片]")
        elif seg_type == "record":
            # 语音消息：转写文本可能存在 data.text 字段
            text = data.get("text", "")
            if text:
                parts.append(f"[语音转写:{text}]")
            else:
                parts.append("[语音]")
        elif seg_type == "reply":
            # 引用回复段，跳过（不重复显示被引用内容）
            pass
        elif seg_type == "forward":
            parts.append("[合并转发]")
        elif seg_type == "json":
            parts.append("[JSON卡片]")
        elif seg_type == "xml":
            parts.append("[XML卡片]")
        elif seg_type == "poke":
            # 戳一戳
            parts.append("[戳一戳]")
        else:
            parts.append(f"[{seg_type}]")
    return "".join(parts)


def _extract_images_from_msg(msg: dict) -> list:
    """从消息段提取图片 URL 列表（用于多模态输入）。

    同时提取 image 段和 mface 段（商城表情包）的 url，
    让 LLM 在多模态模式下能"看到"群里发的图片和表情包。
    """
    images = []
    for seg in msg.get("message", []):
        seg_type = seg.get("type", "")
        data = seg.get("data", {})
        if seg_type == "image":
            url = data.get("url", "")
            if url:
                images.append(url)
        elif seg_type == "mface":
            # 商城表情包也有 url
            url = data.get("url", "")
            if url:
                images.append(url)
    return images


def _msg_to_text(msg) -> str:
    """消息转文本摘要（写回历史用）。"""
    if isinstance(msg, str):
        return msg
    if isinstance(msg, dict):
        t = msg.get("type", "")
        d = msg.get("data", {})
        if t == "text":
            return d.get("text", "")
        if t == "at":
            return f"@{d.get('qq', '')}"
        if t == "face":
            return f"[QQ表情:{d.get('id', '')}]"
        if t == "mface":
            keyword = d.get("emoji_name") or d.get("summary") or "表情包"
            return f"[表情包:{keyword}]"
        if t == "image":
            return "[图片]"
        if t == "voice":
            return f"[语音:{d.get('text', '')}]"
        if t == "poke":
            return "[戳一戳]"
        return f"[{t}]"
    return ""


if __name__ == "__main__":
    bot = MultiGroupBot()
    bot.run()
