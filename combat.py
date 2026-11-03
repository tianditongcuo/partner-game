# -*- coding: utf-8 -*-
"""战斗结算 —— 纯函数，不做 IO、不掷骰、不读配置。

为什么单独拆出来
----------------
以前「/抢老婆」和「/抢老婆胜率」各写了一遍同样的公式，一共四份：
改了一处忘了另一处，就会出现「面板显示的胜率」和「实际掷骰的概率」不一致，
而且这种 bug 极难发现（要对着日志反推）。

现在只有 `resolve()` 一份公式：
  - 结算 handler 用它拿到 `final_prob` 去掷骰
  - 查询 handler 用它的分项字段拼文案

三种玩法只在两处不同：是否吃战力差、是否吃好感护盾。
"""
from __future__ import annotations

from typing import NamedTuple

try:                                      # 作为包的一部分导入（插件运行时）
    from . import balance as B
    from .realms import POWER_RATE_PER_POINT, power
except ImportError:                       # 作为顶层模块导入（docs/tools、单测）
    import balance as B
    from realms import POWER_RATE_PER_POINT, power

#: 强娶：不参与战力、不吃好感护盾
KIND_FORCE = "force"
#: 抢老婆：吃战力差，也吃好感护盾
KIND_ROB_WIFE = "rob_wife"
#: 打劫：吃战力差，不吃好感护盾
KIND_ROB_MONEY = "rob_money"


class CombatResult(NamedTuple):
    """一次胜率计算的完整结果，供结算与文案共同使用。"""

    kind: str
    attack_power: int      # 进攻方底蕴战力
    defend_power: int      # 防守方底蕴战力
    delta_power: int       # 战力差
    power_bonus: float     # 战力差带来的胜率增减（可为负）
    shield_penalty: float  # 好感护盾带来的胜率扣减（非负）
    final_prob: float      # 钳制后的最终胜率
    forced: bool           # 是否命中黑幕名单（强制锁 0）

    # ---- 文案用的小工具：把浮点胜率换算成百分比数字 ----
    @property
    def percent(self) -> float:
        return round(self.final_prob * 100, 2)

    @property
    def power_percent(self) -> float:
        return round(self.power_bonus * 100, 2)

    @property
    def shield_percent(self) -> float:
        return round(self.shield_penalty * 100, 2)


#: 各玩法是否吃战力/护盾。钳制区间不在这里固化 —— 每次计算时现读 balance，
#: 否则 WebUI 改了胜率上下限也不会生效。
_RULES = {
    KIND_FORCE:     {"power": False, "shield": False},
    KIND_ROB_WIFE:  {"power": True,  "shield": True},
    KIND_ROB_MONEY: {"power": True,  "shield": False},
}


def _clamp_range(kind):
    """当前生效的胜率钳制区间（动态取值）。"""
    if kind == KIND_FORCE:
        return B.FORCE_FLOOR, B.FORCE_CAP
    return B.ROB_FLOOR, B.ROB_CAP


def resolve(kind, attack_level, defend_level, affection=0, base_prob=0.0, forced=False, bonus=0.0):
    """计算一次战斗的胜率明细。

    公式（唯一的公式）：
        final = base + Δpower × 系数 − 好感护盾
    其中：
        Δpower = power(进攻等级) − power(防守等级)
        好感护盾 = (好感 // 每档点数) × 每档扣减
    最后按各玩法的区间钳制；命中黑幕则直接锁 0。

    :param kind: KIND_FORCE / KIND_ROB_WIFE / KIND_ROB_MONEY
    :param attack_level: 进攻方等级
    :param defend_level: 防守方等级（抢老婆时传夫妻双方较高者）
    :param affection: 夫妻好感度（只有抢老婆吃这个）
    :param base_prob: 配置里的基础概率
    :param forced: 是否命中 forced_wives 黑幕
    :param bonus: 氪金带来的额外胜率（可突破常规上限，最高到 100%）
    """
    rule = _RULES[kind]
    atk_p = power(attack_level)
    dfd_p = power(defend_level)
    delta = atk_p - dfd_p

    # 黑幕：无论怎么算都锁 0（仍保留分项，方便查询指令展示）
    if forced:
        return CombatResult(kind, atk_p, dfd_p, delta, 0.0, 0.0, 0.0, True)

    power_gain = delta * POWER_RATE_PER_POINT if rule["power"] else 0.0
    shield = B.affection_shield(affection) if rule["shield"] else 0.0

    lo, hi = _clamp_range(kind)
    final = base_prob + power_gain - shield
    final = max(lo, min(hi, final))
    if bonus:                       # 氪金：在常规钳制之后再叠加，可以突破 90% 上限
        final = min(1.0, final + bonus)

    return CombatResult(kind, atk_p, dfd_p, delta, power_gain, shield, final, False)
