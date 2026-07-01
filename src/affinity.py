"""亲密度管理模块。

存储 {qq: affinity}，由 LLM 输出 affinity_delta 微调。
支持小数（如 0.3, 0.5），用于细粒度厌恶/喜好分析。
对忆雨（protected_qq）有保护：负向 delta 限制为 -1，最低值不低于 60。
非忆雨成员的亲密度不会超过忆雨当前的亲密度。
"""
import json
from datetime import datetime
from pathlib import Path

from .utils.logger import get_logger

logger = get_logger("affinity")

AFFINITY_MIN = 0.0
AFFINITY_MAX = 100.0
DELTA_MIN = -1.0
DELTA_MAX = 1.0
PROTECTED_DELTA_MIN = -0.5  # 受保护成员负向 delta 上限
PROTECTED_FLOOR = 60.0      # 受保护成员亲密度下限


class AffinityManager:
    """亲密度管理器。"""

    def __init__(self, state_dir: str = "state", protected_qq: str = ""):
        self.state_dir = Path(state_dir)
        self.state_dir.mkdir(exist_ok=True)
        self.file = self.state_dir / "affinity.json"
        self.protected_qq = protected_qq
        # {qq: {"value": float, "last_updated": str}}
        self.data: dict[str, dict] = {}
        self._load()

    def _load(self):
        if self.file.exists():
            try:
                self.data = json.loads(self.file.read_text(encoding="utf-8"))
                # 旧数据兼容：int → float
                for qq, info in self.data.items():
                    if isinstance(info.get("value"), int):
                        info["value"] = float(info["value"])
            except Exception as e:
                logger.warning(f"加载亲密度失败: {e}")

    def _save(self):
        self.file.write_text(
            json.dumps(self.data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def get(self, qq: str) -> float:
        """获取亲密度，缺失返回 0.0。"""
        return float(self.data.get(qq, {}).get("value", 0.0))

    def apply_delta(self, delta_map: dict):
        """应用 LLM 输出的 affinity_delta。

        Args:
            delta_map: {qq: delta}，delta 会 clip 到 [-2, +2]，支持小数
                       对 protected_qq（忆雨）负向 delta 限制为 [-1, +2]，最低 60
                       非忆雨成员的亲密度不会超过忆雨当前的亲密度
        """
        now = datetime.now().isoformat()
        # 先取忆雨当前亲密度，作为其他成员的上限
        yukina_value = self.get(self.protected_qq) if self.protected_qq else AFFINITY_MAX
        for qq, delta in delta_map.items():
            is_protected = (qq == self.protected_qq)
            # clip delta
            if is_protected:
                delta = max(PROTECTED_DELTA_MIN, min(DELTA_MAX, float(delta)))
            else:
                delta = max(DELTA_MIN, min(DELTA_MAX, float(delta)))
            old = self.get(qq)
            new = old + delta
            if is_protected:
                new = max(PROTECTED_FLOOR, min(AFFINITY_MAX, new))
            else:
                new = max(AFFINITY_MIN, min(AFFINITY_MAX, new))
                # 非忆雨成员不超过忆雨的亲密度
                if new > yukina_value:
                    new = yukina_value
                    logger.debug(f"亲密度 {qq} 限制为忆雨上限 {yukina_value}")
            # 保留一位小数
            new = round(new, 1)
            self.data[qq] = {"value": new, "last_updated": now}
            tag = " [protected]" if is_protected else ""
            logger.debug(f"亲密度 {qq}: {old} -> {new} (delta={delta}){tag}")
        self._save()
