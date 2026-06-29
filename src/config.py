"""配置加载模块。"""
from dataclasses import dataclass, field
from typing import Any
import yaml


@dataclass
class NapCatConfig:
    base_url: str
    group_ids: list[str]       # 支持多群同时运行
    group_id: str = ""         # 兼容旧逻辑，运行时自动取 group_ids[0]


@dataclass
class LLMConfig:
    api_url: str
    api_key: str
    model: str


@dataclass
class PersonaConfig:
    name: str
    gender: str
    age: str
    location: str
    job: str
    traits: list
    interests: list
    catchphrases: list = field(default_factory=list)  # 已废弃：不再注入 prompt，口头禅融入 background/style
    style: str = ""
    forbidden: list = field(default_factory=list)
    background: str = ""   # 角色过往经历/背景故事，注入到系统提示词（塑造人格的根源）
    relationships: str = ""  # 与群成员的特殊关系/情感倾向，注入系统提示词
    persona_file: str = ""   # LLM Persona MD 文件路径（运行时由 persona.py 读取注入）
    bible_file: str = ""      # Character Bible MD 文件路径（设定文档，可作参考）


@dataclass
class VoiceConfig:
    ai_record_character: str
    fallback_to_text: bool


@dataclass
class TriggerConfig:
    peek_threshold: float
    silent_buffer_limit: int
    history_limit: int
    history_keep_recent: int
    attribution_step: float
    cold_start_rounds: int


@dataclass
class ActiveTriggerConfig:
    """主动触发配置。"""
    enabled: bool = True
    min_interval_minutes: int = 120   # 主动触发最小间隔（分钟）
    max_interval_minutes: int = 360   # 主动触发最大间隔（分钟）
    night_start_hour: int = 23        # 深夜起始小时（禁用主动触发）
    night_end_hour: int = 3           # 深夜结束小时


@dataclass
class SpecialMembersConfig:
    """特殊成员权重配置。"""
    target_qq: str = ""
    friend_speak_weight: float = 1.0


@dataclass
class Config:
    napcat: NapCatConfig
    llm: LLMConfig
    persona: PersonaConfig
    voice: VoiceConfig
    trigger: TriggerConfig
    trigger_factors: dict      # 软因子 base_value
    trigger_hard_factors: dict # 硬因子 base_value（不参与归因）
    active_trigger: ActiveTriggerConfig = None  # 主动触发配置
    special_members: SpecialMembersConfig = None  # 特殊成员权重配置


def load_config(path: str = "config.yaml") -> Config:
    """从 YAML 文件加载配置。"""
    with open(path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f)

    active_raw = raw.get("active_trigger", {})
    active = ActiveTriggerConfig(
        enabled=active_raw.get("enabled", True),
        min_interval_minutes=active_raw.get("min_interval_minutes", 120),
        max_interval_minutes=active_raw.get("max_interval_minutes", 360),
        night_start_hour=active_raw.get("night_start_hour", 23),
        night_end_hour=active_raw.get("night_end_hour", 3),
    )

    # 特殊成员配置
    special_raw = raw.get("special_members", {})
    special = SpecialMembersConfig(
        target_qq=special_raw.get("target_qq", ""),
        friend_speak_weight=special_raw.get("friend_speak_weight", 1.0),
    ) if special_raw else None

    # 解析 napcat 配置，兼容 group_id（旧）和 group_ids（新）
    napcat_raw = raw["napcat"]
    if "group_ids" in napcat_raw:
        group_ids = napcat_raw["group_ids"]
    elif "group_id" in napcat_raw:
        group_ids = [napcat_raw["group_id"]]
    else:
        group_ids = []

    return Config(
        napcat=NapCatConfig(base_url=napcat_raw["base_url"], group_ids=group_ids, group_id=group_ids[0] if group_ids else ""),
        llm=LLMConfig(**raw["llm"]),
        persona=PersonaConfig(**raw["persona"]),
        voice=VoiceConfig(**raw["voice"]),
        trigger=TriggerConfig(**raw["trigger"]),
        trigger_factors=raw.get("trigger_factors", {}),
        trigger_hard_factors=raw.get("trigger_hard_factors", {}),
        active_trigger=active,
        special_members=special,
    )
