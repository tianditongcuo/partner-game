# -*- coding: utf-8 -*-
"""全局数值表 —— 所有可调参数集中在这里。

**改数值只改这个文件。** 插件的实际行为、`docs/dashboard.html` 的
参数面板与概率曲线都从这里取值，不存在第二份真相。

命名约定
--------
- `*_LIMIT`      每个周期内允许的次数
- `*_GATE`       发起该行为所需的金币门槛
- `*_FINE_MIN/MAX` 失败罚款区间（随机整数）
- `*_MIN/MAX`    其它区间
"""
from __future__ import annotations

import time
from typing import Optional

# ============================================================ 周期
#: 一个「游戏周期」的小时数。默认 24（一天）。
#: 改成 12 就是半天一轮，改成 168 就是一周一轮 —— 所有次数限制、
#: 每日低保、跨周期好感都会自动跟随，无需改别处。
CYCLE_HOURS = 24


def period_key(tz_offset_hours: int = 8, cycle_hours: Optional[int] = None) -> str:
    """当前周期的标识字符串（写入存档，用于判断是否跨周期）。

    - `CYCLE_HOURS == 24` 时返回日期 `YYYY-MM-DD`，与旧存档完全兼容。
    - 其它周期返回 `P<序号>`，序号按 epoch 整除得到。
    """
    hours = CYCLE_HOURS if cycle_hours is None else cycle_hours
    if not hours or hours <= 0:
        hours = 24
    offset = max(-12, min(14, int(tz_offset_hours or 0)))
    ts = time.time() + offset * 3600
    if int(hours) == 24:
        return time.strftime("%Y-%m-%d", time.gmtime(ts))
    return "P%d" % int(ts // (hours * 3600))


# ============================================================ 经济：基础
INITIAL_MONEY = 1000              # 新用户初始金币
CYCLE_ALLOWANCE = 200             # 每个周期首次互动发放的低保
MARRIAGE_AFFECTION_PER_CYCLE = 5  # 跨周期时，存续中的婚姻自动增加的好感

# ============================================================ 次数限制（每周期）
DRAW_LIMIT = 1        # /今日老婆
DIVORCE_LIMIT = 1     # /离婚
DUMP_LIMIT = 1        # /甩掉
WORK_LIMIT = 3        # /打工
DATE_LIMIT = 3        # /约会
CULTIVATE_LIMIT = 3   # /修炼
ROB_MONEY_LIMIT = 3   # /打劫

# ============================================================ 打工
WORK_EARN_MIN = 50        # 基础收入下限
WORK_EARN_MAX = 100       # 基础收入上限
WORK_LEVEL_BONUS = 10     # 每级境界的额外收入

# ============================================================ 约会
DATE_COST = 50            # 每次约会消耗
DATE_AFF_MIN = 10         # 好感增加下限
DATE_AFF_MAX = 20         # 好感增加上限

# ============================================================ 修炼（费用公式在 realms.cultivate_cost）
CULTIVATE_COST_BASE = 50  # 每个大境界的系数：费用 = (境界序号+1) × 该值
MINOR_SUCCESS_RATE = 0.80 # 小境界突破成功率
MAJOR_SUCCESS_RATE = 0.40 # 大境界突破成功率
MAJOR_FAIL_DROP_RATE = 0.30  # 大境界突破失败后，再判定「走火入魔掉级」的概率

# ============================================================ 好感护盾
AFFECTION_PER_SHIELD = 20     # 每多少点好感抵消一档
AFFECTION_SHIELD_RATE = 0.01  # 每档抵消的胜率（1%）

# ============================================================ 强娶
FORCE_GATE = 300              # 发起所需金币门槛
FORCE_FINE_MIN = 100          # 失败罚款下限
FORCE_FINE_MAX = 300          # 失败罚款上限
FORCE_FLOOR = 0.0             # 胜率钳制下限（强娶不受战力影响）
FORCE_CAP = 1.0               # 胜率钳制上限

# ============================================================ 抢老婆
ROB_WIFE_GATE = 500
ROB_WIFE_FINE_MIN = 200
ROB_WIFE_FINE_MAX = 500
ROB_WIFE_DROP_CHANCE = 0.20   # 失败后被反杀掉级的概率
ROB_FLOOR = 0.10              # 抢夺/打劫的胜率钳制下限
ROB_CAP = 0.90                # 抢夺/打劫的胜率钳制上限

# ============================================================ 打劫
ROB_MONEY_GATE = 300
ROB_MONEY_FINE_MIN = 100
ROB_MONEY_FINE_MAX = 300
ROB_MONEY_RATIO_MIN = 0.10    # 抢走目标资产的比例下限
ROB_MONEY_RATIO_MAX = 0.25    # 比例上限
ROB_MONEY_STEAL_MIN = 50      # 单次劫掠金额下限
#: 单次劫掠不得超过受害者当前金币的这个倍数（>1 表示允许把人打成负债）
ROB_MONEY_CAP_RATIO = 1.5
#: 受害者资产 ≤ 0 时，单次劫掠的硬上限（保护负资产玩家不再被无限刷）
ROB_MONEY_NEGATIVE_CAP = 100

# ============================================================ 贷款
LOAN_REPAY_MULTIPLIER = 2.0   # 还款倍数：借 100 还 200
LOAN_GRACE_MINUTES = 15       # 逾期时限（分钟），超时后限制活动

# ============================================================ 下秘境
REALM_DIVE_LIMIT = 1             # 每周期可下秘境的次数
REALM_DIVE_MONEY_MIN_FACTOR = 10     # 金币收益下限 = 等级 × 本值
REALM_DIVE_MONEY_MAX_FACTOR = 10000  # 金币收益上限 = 等级 × 本值
REALM_DIVE_GOLD_PROB = 0.70      # 获得金币
REALM_DIVE_SURGE_PROB = 0.15     # 修为暴涨一个大境界
REALM_DIVE_FALL_PROB = 0.10      # 修为倒退一个境界
REALM_DIVE_DEATH_PROB = 0.05     # 陨落（修为归零、金币保留）

# ============================================================ 罚款与惩罚
FINE_COMPENSATION_RATIO = 0.5  # 罚款中赔付给对手的比例（其余蒸发）
FAIL_AUTISM_SECONDS = 60       # 失败后的强制自闭时长（秒）
MAX_PENALTY_SECONDS = 60       # 自闭时长硬上限


def affection_shield(affection: int) -> float:
    """好感度提供的胜率减免（正值，调用方自行相减）。"""
    return (int(affection or 0) // AFFECTION_PER_SHIELD) * AFFECTION_SHIELD_RATE


def shield_steps(affection: int) -> int:
    """好感走到第几档（用于文案：`可抵消 N%`）。"""
    return int(affection or 0) // AFFECTION_PER_SHIELD
