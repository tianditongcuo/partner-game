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
#: 打工收益下限。**允许为负**：负数表示这一趟倒贴（亏本）。
WORK_EARN_MIN = -100
#: 打工收益上限 = 当前境界等级 × 本值（等级越高，能赚的越多）
WORK_EARN_MAX_PER_LEVEL = 1000

# ============================================================ 约会
DATE_COST = 0             # 每次约会消耗（默认 0 = 免费，填正数才收费）
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
#: 护盾的硬上限：再高的好感也只能抵消这么多，防止夫妻完全免疫抢夺
AFFECTION_SHIELD_MAX = 0.50

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

# ============================================================ 氪金
#: 每多少金币换 1% 的下次行动成功率（100 → 氪 1000 得 10%）
RECHARGE_COINS_PER_PERCENT = 100
#: 氪金加成的总上限（0.99 = 最高 99%）
RECHARGE_CAP = 0.99
#: 单次氪金的最低金额
RECHARGE_MIN_AMOUNT = 100

# ============================================================ 天妒 / 天罚
#: 每周期成功突破多少次后触发「天妒」
TIAN_DU_SUCCESS_THRESHOLD = 6
#: 天妒惩罚：修为倒退几个大境界
TIAN_DU_DROP_REALMS = 3
#: 每周期犯罪（打劫/强娶/抢老婆）总次数超过多少后触发「天罚」
TIAN_FA_CRIME_THRESHOLD = 8
#: 天罚惩罚：扣除现有金币的比例
TIAN_FA_MONEY_RATIO = 0.6

# ============================================================ 打怪
BEAST_LIMIT = 3                  # 每周期可打几次怪
COOLDOWN_BEAST = 60              # 打怪冷却（秒）
BEAST_MONEY_MIN_FACTOR = 100     # 金币收益下限 = 等级 × 本值
BEAST_MONEY_MAX_FACTOR = 5000    # 金币收益上限 = 等级 × 本值
BEAST_GAIN_LEVELS = 4            # 击杀成功时提升的等级（4 级 = 1 个大境界）
BEAST_LOSE_LEVELS = 4            # 落败时跌落的等级
BEAST_GOLD_PROB = 0.55           # 获得大量金币
BEAST_GAIN_PROB = 0.25           # 修为提升
BEAST_LOSE_PROB = 0.15           # 境界跌落
BEAST_DEATH_PROB = 0.05          # 陨落

# ============================================================ 重生
#: 重生（主动 / 陨落）后保留的修为比例
REBIRTH_KEEP_RATIO = 0.7

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

# ---- 罚款：每种犯罪独立配置，互不影响 ----
# 注：失败后的等待时间统一由下方「冷却」控制，不再单设"失败自闭"。
#: 强娶失败罚款下限
FORCE_FINE_FLOOR = 100
#: 强娶失败罚款上限 = 行动者现有金币 × 本值
FORCE_FINE_CAP_RATIO = 1.0
#: 抢老婆失败罚款下限
ROB_WIFE_FINE_FLOOR = 100
#: 抢老婆失败罚款上限 = 行动者现有金币 × 本值
ROB_WIFE_FINE_CAP_RATIO = 1.0
#: 打劫失败罚款下限
ROB_MONEY_FINE_FLOOR = 100
#: 打劫失败罚款上限 = 行动者现有金币 × 本值
ROB_MONEY_FINE_CAP_RATIO = 1.0
# ---- 冷却：每条指令独立，0 表示无冷却 ----
COOLDOWN_DRAW = 60         # /今日老婆
COOLDOWN_DIVORCE = 60      # /离婚
COOLDOWN_MARRY = 60        # /娶
COOLDOWN_DUMP = 60         # /甩掉
COOLDOWN_MY_PARTNER = 10   # /我的伴侣（查询类，默认短）
COOLDOWN_FORCE = 60        # /强娶
COOLDOWN_ROB_WIFE = 60     # /抢老婆
COOLDOWN_ROB_MONEY = 60    # /打劫
COOLDOWN_GIVE = 30         # /送钱
COOLDOWN_RECHARGE = 30     # /氪金
COOLDOWN_MATING = 30       # /申请交配

# ---- 离婚惩罚（默认关闭）----
#: 开关：开启后，主动解除关系时要把一半身家分给对方
DIVORCE_PENALTY_ENABLED = False
#: 分走的金币比例
DIVORCE_PENALTY_MONEY_RATIO = 0.5
#: 分走的修为比例（按等级折算）
DIVORCE_PENALTY_LEVEL_RATIO = 0.5

# ============================================================ 交配
MATING_AFFECTION_MIN = 100     # 允许申请交配所需的最低好感
MATING_AFFECTION_GAIN = 50     # 每次成功交配提升的好感
MATING_LIMIT = 3               # 每周期可交配的次数
MATING_TIMEOUT_SECONDS = 120   # 交配申请的有效期（秒）


def affection_shield(affection: int) -> float:
    """好感度提供的胜率减免（正值，调用方自行相减）。

    受 AFFECTION_SHIELD_MAX 硬上限约束 —— 好感堆到天上去，也最多抵掉这么多。
    """
    raw = (int(affection or 0) // AFFECTION_PER_SHIELD) * AFFECTION_SHIELD_RATE
    return min(raw, AFFECTION_SHIELD_MAX)


def shield_steps(affection: int) -> int:
    """好感走到第几档（用于文案：`可抵消 N%`）。"""
    return int(affection or 0) // AFFECTION_PER_SHIELD
