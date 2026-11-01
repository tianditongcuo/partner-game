# -*- coding: utf-8 -*-
"""境界体系 —— 全局唯一数据源。

设计约定
--------
1. **等级 (`level`) 是唯一进度量**：0 ~ `MAX_LEVEL`。
2. 每个大境界含 4 个小境界，因此
   `level = 大境界序号 * 4 + 小境界序号`。
3. 想改境界表，只改 `REALMS` 一处；等级上限、显示名、战力、修炼费用
   全部由它推导，不再散落在各 handler 里。

数值说明
--------
- 战力 `power(level) = level × (大境界序号 + 1)`：保留原版设计，
  大境界越高，同样 4 个小境界的收益越大，形成非线性成长。
- 修炼费用 `cultivate_cost(level) = (大境界序号 + 1) × 50`：
  与战力同源，避免"战力涨了费用没涨"的脱节。
"""
from __future__ import annotations

from typing import List, Tuple

#: 大境界，顺序即强度顺序（索引 0 为最低）
REALMS: List[str] = [
    "凡境", "炼体", "凝气", "炼气", "筑基",
    "凝元", "虚丹", "结丹", "金丹", "元婴",
    "婴变", "出壳", "元神", "化神", "分神",
    "炼神", "反虚", "炼虚", "洞虚", "分体",
    "合体", "洞天", "渡劫", "大乘", "飞升",
]

#: 小境界，固定四档
SUB_REALMS: List[str] = ["前期", "中期", "后期", "圆满"]

#: 每个大境界包含的小境界数量
PER_REALM = len(SUB_REALMS)

#: 等级上限（最高境界的最后一个台阶）
MAX_LEVEL = len(REALMS) * PER_REALM - 1


def clamp_level(level: int) -> int:
    """把外部传入的等级收进合法区间，防止脏数据把索引打穿。"""
    try:
        level = int(level)
    except (TypeError, ValueError):
        return 0
    return max(0, min(MAX_LEVEL, level))


def split_level(level: int) -> Tuple[int, int]:
    """等级 → (大境界序号, 小境界序号)。"""
    level = clamp_level(level)
    return level // PER_REALM, level % PER_REALM


def realm_index(level: int) -> int:
    return split_level(level)[0]


def sub_index(level: int) -> int:
    return split_level(level)[1]


def realm_name(level: int) -> str:
    """等级 → 完整境界名，例如 0 → 凡境前期，99 → 飞升圆满。"""
    major, minor = split_level(level)
    return REALMS[major] + SUB_REALMS[minor]


def realm_only(level: int) -> str:
    """只取大境界名，例如 5 → 凝元。"""
    return REALMS[split_level(level)[0]]


def is_major_boundary(level: int) -> bool:
    """当前等级是否是「大境界的最后一阶」——突破它即跨越大境界。

    在大境界边界上突破难度更高、失败可能跌境。
    """
    return split_level(level)[1] == PER_REALM - 1


def is_max_level(level: int) -> bool:
    return clamp_level(level) >= MAX_LEVEL


def power(level: int) -> int:
    """底蕴战力 = 等级 × (大境界序号 + 1)。"""
    level = clamp_level(level)
    return level * (level // PER_REALM + 1)


def cultivate_cost(level: int) -> int:
    """在 level 处突破一次的丹药费用。"""
    return (realm_index(level) + 1) * 50


def level_span() -> str:
    """用于文案：`凡境前期 ~ 飞升圆满（共 100 档）`。"""
    return "%s ~ %s（共 %d 档）" % (realm_name(0), realm_name(MAX_LEVEL), MAX_LEVEL + 1)
