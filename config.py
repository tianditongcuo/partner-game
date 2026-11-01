"""今日老婆插件配置模型。"""
from __future__ import annotations
from typing import ClassVar, List, Dict, Optional, Union

from pydantic import field_validator
from maibot_sdk import Field, PluginConfigBase

class PluginSection(PluginConfigBase):
    __ui_label__: ClassVar[str] = "插件开关"
    __ui_order__: ClassVar[int] = 0
    enabled: bool = Field(
        default=True,
        description="是否启用本插件。",
        json_schema_extra={"label": "启用插件", "order": 0},
    )
    config_version: str = Field(
        default="2.0.2",
        json_schema_extra={"disabled": True, "hidden": True, "label": "配置版本", "order": 99},
    )

class PartnerGameSection(PluginConfigBase):
    __ui_label__: ClassVar[str] = "今日老婆 Pro 游戏设置"
    __ui_order__: ClassVar[int] = 1
    exclude_self: bool = Field(
        default=True,
        description="是否将机器人自身排除出候选池。",
        json_schema_extra={"label": "排除机器人自身", "order": 0},
    )
    exclude_sender: bool = Field(
        default=True,
        description="是否将指令发起者排除出候选池。",
        json_schema_extra={"label": "排除指令发起者", "order": 1},
    )
    bot_qq: str = Field(
        default="",
        description="（可选）机器人 QQ。留空时自动通过 napcat 获取。",
        json_schema_extra={"label": "机器人 QQ（可选）", "placeholder": "留空自动获取", "order": 2},
    )
    no_limit_users: List[str] = Field(
        default_factory=list,
        description="不受每日一次限制的白名单 QQ 列表。",
        json_schema_extra={"label": "白名单 QQ", "order": 3},
    )
    admin_users: List[str] = Field(
        default_factory=list,
        description="拥有最高权限的管理员 QQ 列表（可使用 /重置、/全服补偿 等高危指令）。",
        json_schema_extra={"label": "管理员 QQ", "order": 4},
    )
    tz_offset_hours: int = Field(
        default=8,
        description="时区偏移（小时），用于确定 “今日” 的边界。",
        json_schema_extra={"label": "时区偏移", "order": 4, "step": 1},
    )
    send_avatar: bool = Field(
        default=True,
        description="是否额外发送对方的 QQ 头像。",
        json_schema_extra={"label": "发送头像", "order": 5},
    )
    avatar_size: int = Field(
        default=640,
        description="头像尺寸（像素）。",
        json_schema_extra={"label": "头像尺寸", "order": 6, "step": 1},
    )
    cooldown_seconds: int = Field(
        default=60,
        description="同一指令连续触发的冷却秒数。",
        json_schema_extra={"label": "冷却秒数", "order": 7, "step": 1},
    )
    persist_enabled: bool = Field(
        default=True,
        description="是否启用本地持久化（保存今日抽取与离婚记录）。",
        json_schema_extra={"label": "启用持久化", "order": 8},
    )
    force_marry_probability: float = Field(
        default=0.4,
        description="强娶成功的概率 (0.0 ~ 1.0)。",
        json_schema_extra={"label": "强娶成功概率", "order": 9},
    )
    rob_wife_probability: float = Field(
        default=0.3,
        description="抢老婆成功的基础概率 (0.0 ~ 1.0)。",
        json_schema_extra={"label": "抢老婆基础成功率", "order": 10},
    )
    rob_money_probability: float = Field(
        default=0.35,
        description="打劫金币的基础成功率 (0.0 ~ 1.0)。",
        json_schema_extra={"label": "打劫金币基础成功率", "order": 11},
    )
    proposal_timeout_seconds: int = Field(
        default=60,
        description="娶老婆等待同意的超时秒数。",
        json_schema_extra={"label": "求婚超时秒数", "order": 10, "step": 1},
    )
    forced_wives: List[str] = Field(
        default_factory=list,
        description="强制指定的黑幕列表，每条规则格式为 发起者QQ:强制老婆QQ",
        json_schema_extra={
            "label": "强制黑幕名单", 
            "hint": "神秘开关：指定某个QQ永远抽到另外一个特定的QQ（例如指定抽到机器人自己）。\n格式为：【发起人QQ号:老婆QQ号】。例如 12345678:87654321。\n如果有多个黑幕，添加多条即可。",
            "order": 9
        },
    )

    @field_validator("forced_wives", mode="before")
    def _parse_forced_wives(cls, v):
        if isinstance(v, dict):
            # 兼容旧版本保存的字典配置
            return [f"{k}:{val}" for k, val in v.items()]
        return v


class BalanceCycleSection(PluginConfigBase):
    """① 周期与次数 —— 多久结算一次、每周期各项能做几次。

    次数类字段的三种填法：
      - 留空：用 balance.py 的默认值；
      - 填「不限制」或负数：不限次；
      - 填 0：完全禁用该功能。
    """

    __ui_label__: ClassVar[str] = "① 周期与次数"
    __ui_order__: ClassVar[int] = 2

    cycle_hours: Optional[int] = Field(
        default=None,
        description=(
            "一个游戏周期是多少小时。所有「每周期 N 次」、周期低保、"
            "婚姻跨周期好感、天妒/天罚的「每天一次」判定都按它结算。\n"
            "默认 24（每天一轮）；12 = 半天一轮；168 = 一周一轮。"
        ),
        json_schema_extra={"label": "周期时长（小时）", "placeholder": "默认 24", "order": 0, "step": 1})
    draw_limit: Optional[Union[int, str]] = Field(
        default=None, description="每周期可用几次 /今日老婆。默认 1；「不限制」= 不限次；0 = 禁用。",
        json_schema_extra={"label": "抽老婆次数", "placeholder": "默认 1", "order": 10, "step": 1})
    divorce_limit: Optional[Union[int, str]] = Field(
        default=None, description="每周期可用几次 /离婚。默认 1；「不限制」= 不限次；0 = 禁用。",
        json_schema_extra={"label": "离婚次数", "placeholder": "默认 1", "order": 11, "step": 1})
    dump_limit: Optional[Union[int, str]] = Field(
        default=None, description="每周期可用几次 /甩掉。默认 1；「不限制」= 不限次；0 = 禁用。",
        json_schema_extra={"label": "甩掉次数", "placeholder": "默认 1", "order": 12, "step": 1})
    work_limit: Optional[Union[int, str]] = Field(
        default=None, description="每周期可用几次 /打工。默认 3；「不限制」= 不限次；0 = 禁用。",
        json_schema_extra={"label": "打工次数", "placeholder": "默认 3", "order": 13, "step": 1})
    date_limit: Optional[Union[int, str]] = Field(
        default=None, description="每周期可用几次 /约会。默认 3；「不限制」= 不限次；0 = 禁用。",
        json_schema_extra={"label": "约会次数", "placeholder": "默认 3", "order": 14, "step": 1})
    cultivate_limit: Optional[Union[int, str]] = Field(
        default=None, description="每周期可用几次 /修炼。默认 3；「不限制」= 不限次；0 = 禁用。",
        json_schema_extra={"label": "修炼次数", "placeholder": "默认 3", "order": 15, "step": 1})
    rob_money_limit: Optional[Union[int, str]] = Field(
        default=None, description="每周期可用几次 /打劫。默认 3；「不限制」= 不限次；0 = 禁用。",
        json_schema_extra={"label": "打劫次数", "placeholder": "默认 3", "order": 16, "step": 1})
    mating_limit: Optional[Union[int, str]] = Field(
        default=None, description="每周期夫妻可交配几次（双方共用）。默认 3；「不限制」= 不限次。",
        json_schema_extra={"label": "交配次数", "placeholder": "默认 3", "order": 17, "step": 1})
    realm_dive_limit: Optional[Union[int, str]] = Field(
        default=None, description="每周期可下几次秘境。默认 1；「不限制」= 不限次。",
        json_schema_extra={"label": "秘境次数", "placeholder": "默认 1", "order": 18, "step": 1})


class BalanceEconomySection(PluginConfigBase):
    """② 金币与打工 —— 钱从哪来、花到哪去。"""

    __ui_label__: ClassVar[str] = "② 金币与打工"
    __ui_order__: ClassVar[int] = 3

    initial_money: Optional[int] = Field(
        default=None, description="新玩家第一次参与时的初始金币。默认 1000。",
        json_schema_extra={"label": "初始金币", "placeholder": "默认 1000", "order": 20, "step": 100})
    cycle_allowance: Optional[int] = Field(
        default=None, description="每周期首次互动时自动发放的低保。默认 200。",
        json_schema_extra={"label": "周期低保", "placeholder": "默认 200", "order": 21, "step": 50})
    work_earn_min: Optional[int] = Field(
        default=None,
        description=(
            "打工收益下限，**可以为负** —— 负数代表这一趟倒贴（亏本）。\n"
            "实际收益在「下限」与「上限」之间随机。默认 -100。"
        ),
        json_schema_extra={"label": "打工收益下限（可为负）", "placeholder": "默认 -100", "order": 22, "step": 10})
    work_earn_max_per_level: Optional[int] = Field(
        default=None,
        description="打工收益上限 = 当前境界等级 × 本值。默认 1000（20 级最多赚 20000）。",
        json_schema_extra={"label": "打工收益上限系数", "placeholder": "默认 1000", "order": 23, "step": 100})
    date_cost: Optional[int] = Field(
        default=None, description="每次 /约会 消耗的金币。默认 50。",
        json_schema_extra={"label": "约会消耗", "placeholder": "默认 50", "order": 24, "step": 10})
    date_aff_min: Optional[int] = Field(
        default=None, description="每次约会增加的好感下限。默认 10。",
        json_schema_extra={"label": "约会好感下限", "placeholder": "默认 10", "order": 25, "step": 1})
    date_aff_max: Optional[int] = Field(
        default=None, description="每次约会增加的好感上限。默认 20。",
        json_schema_extra={"label": "约会好感上限", "placeholder": "默认 20", "order": 26, "step": 1})


class BalanceCultivationSection(PluginConfigBase):
    """③ 修炼与氪金 —— 境界怎么涨、钱怎么买概率。"""

    __ui_label__: ClassVar[str] = "③ 修炼与氪金"
    __ui_order__: ClassVar[int] = 4

    cultivate_cost_base: Optional[int] = Field(
        default=None,
        description="修炼费用系数：单次费用 = (大境界序号 + 1) × 本值。默认 50（凡境 50，飞升 1250）。",
        json_schema_extra={"label": "修炼费用系数", "placeholder": "默认 50", "order": 30, "step": 10})
    minor_success_rate: Optional[float] = Field(
        default=None, description="小境界突破成功率，0~1。默认 0.8，失败无惩罚。",
        json_schema_extra={"label": "小境界成功率", "placeholder": "默认 0.8", "order": 31, "step": 0.05})
    major_success_rate: Optional[float] = Field(
        default=None, description="大境界突破成功率，0~1。默认 0.4，失败有概率掉级。",
        json_schema_extra={"label": "大境界成功率", "placeholder": "默认 0.4", "order": 32, "step": 0.05})
    major_fail_drop_rate: Optional[float] = Field(
        default=None, description="大境界失败后走火入魔（掉 1 级）的概率。默认 0.3。",
        json_schema_extra={"label": "走火入魔概率", "placeholder": "默认 0.3", "order": 33, "step": 0.05})
    recharge_coins_per_percent: Optional[int] = Field(
        default=None,
        description=(
            "氪金换算：每多少金币换 1% 的下次行动成功率。默认 100。\n"
            "/氪金 1000 就是 +10%，作用于 /打劫 /强娶 /下秘境 /修炼 的下一次行动，用掉即清零。"
        ),
        json_schema_extra={"label": "氪金换算（金币/1%）", "placeholder": "默认 100", "order": 34, "step": 50})
    recharge_cap: Optional[float] = Field(
        default=None,
        description="氪金加成的总上限，0~1。默认 0.99（最高 99%）。",
        json_schema_extra={"label": "氪金加成上限", "placeholder": "默认 0.99", "order": 35, "step": 0.01})
    recharge_min_amount: Optional[int] = Field(
        default=None, description="单次 /氪金 的最低金额。默认 100。",
        json_schema_extra={"label": "单次氪金下限", "placeholder": "默认 100", "order": 36, "step": 50})


class BalanceCrimeSection(PluginConfigBase):
    """④ 犯罪与胜率 —— 强娶 / 抢老婆 / 打劫 的门槛、概率与金额。"""

    __ui_label__: ClassVar[str] = "④ 犯罪与胜率"
    __ui_order__: ClassVar[int] = 5

    force_gate: Optional[int] = Field(
        default=None, description="发起 /强娶 需要的金币余额。默认 300。",
        json_schema_extra={"label": "强娶金币门槛", "placeholder": "默认 300", "order": 40, "step": 50})
    rob_wife_gate: Optional[int] = Field(
        default=None, description="发起 /抢老婆 需要的金币余额。默认 500。",
        json_schema_extra={"label": "抢老婆金币门槛", "placeholder": "默认 500", "order": 41, "step": 50})
    rob_money_gate: Optional[int] = Field(
        default=None, description="发起 /打劫 需要的金币余额。默认 300。",
        json_schema_extra={"label": "打劫金币门槛", "placeholder": "默认 300", "order": 42, "step": 50})
    rob_floor: Optional[float] = Field(
        default=None, description="抢夺/打劫的胜率下限。默认 0.1（10%）。",
        json_schema_extra={"label": "胜率下限", "placeholder": "默认 0.1", "order": 43, "step": 0.01})
    rob_cap: Optional[float] = Field(
        default=None, description="抢夺/打劫的胜率上限。默认 0.9（90%）。氪金可突破到氪金上限。",
        json_schema_extra={"label": "胜率上限", "placeholder": "默认 0.9", "order": 44, "step": 0.01})
    rob_money_cap_ratio: Optional[float] = Field(
        default=None,
        description=(
            "单次打劫最多抢走受害者当前金币的多少倍。默认 1.5（最多打成 -50% 负债）。\n"
            "填 1.0 表示最多抢光、不负债。"
        ),
        json_schema_extra={"label": "打劫上限倍数", "placeholder": "默认 1.5", "order": 45, "step": 0.1})
    rob_money_negative_cap: Optional[int] = Field(
        default=None, description="受害者资产 ≤ 0 时单次打劫的金额上限。默认 100。",
        json_schema_extra={"label": "负资产打劫上限", "placeholder": "默认 100", "order": 46, "step": 10})


class BalancePenaltySection(PluginConfigBase):
    """⑤ 罚款与惩罚 —— 失败要付出什么，以及天罚。"""

    __ui_label__: ClassVar[str] = "⑤ 罚款与惩罚"
    __ui_order__: ClassVar[int] = 6

    fine_floor: Optional[int] = Field(
        default=None, description="强娶/抢老婆/打劫失败的罚款下限，无论多穷都至少罚这么多。默认 100。",
        json_schema_extra={"label": "罚款下限", "placeholder": "默认 100", "order": 50, "step": 10})
    fine_cap_ratio: Optional[float] = Field(
        default=None,
        description="罚款上限 = 行动者现有金币 × 本值。默认 1.0（最多罚光）。实际罚款在上下限之间随机。",
        json_schema_extra={"label": "罚款上限比例", "placeholder": "默认 1.0", "order": 51, "step": 0.1})
    fine_compensation_ratio: Optional[float] = Field(
        default=None,
        description="罚款中赔付给对手的比例，0~1。默认 0.5（一半赔对方、一半蒸发）。",
        json_schema_extra={"label": "罚款赔付比例", "placeholder": "默认 0.5", "order": 52, "step": 0.05})
    fail_autism_seconds: Optional[int] = Field(
        default=None,
        description="犯罪失败后的强制自闭时长（秒），期间该指令不可再用。默认 60，与普通冷却叠加。",
        json_schema_extra={"label": "失败自闭秒数", "placeholder": "默认 60", "order": 53, "step": 10})
    max_penalty_seconds: Optional[int] = Field(
        default=None, description="自闭时长的硬上限（秒），防止配置失误把人永久锁死。默认 60。",
        json_schema_extra={"label": "自闭时长硬上限", "placeholder": "默认 60", "order": 54, "step": 10})
    tian_fa_crime_threshold: Optional[int] = Field(
        default=None,
        description=(
            "天罚：每周期内「打劫 + 强娶 + 抢老婆」的总次数超过此值即触发，每周期只触发一次。\n"
            "默认 8。填 0 或负数 = 关闭天罚。"
        ),
        json_schema_extra={"label": "天罚触发次数", "placeholder": "默认 8", "order": 55, "step": 1})
    tian_fa_money_ratio: Optional[float] = Field(
        default=None, description="天罚惩罚：扣除现有金币的比例。默认 0.6（扣 60%）。",
        json_schema_extra={"label": "天罚扣钱比例", "placeholder": "默认 0.6", "order": 56, "step": 0.1})
    realm_dive_death_prob: Optional[float] = Field(
        default=None,
        description="下秘境陨落的概率：修为归零、金币保留。默认 0.05。属于惩罚类结果。",
        json_schema_extra={"label": "秘境·陨落概率", "placeholder": "默认 0.05", "order": 57, "step": 0.01})
    tian_du_success_threshold: Optional[int] = Field(
        default=None,
        description=(
            "天妒：每周期内「修炼成功」达到此次数即触发，修为倒退若干大境界，每周期只触发一次。\n"
            "默认 6。填 0 或负数 = 关闭天妒。"
        ),
        json_schema_extra={"label": "天妒触发次数", "placeholder": "默认 6", "order": 58, "step": 1})
    tian_du_drop_realms: Optional[int] = Field(
        default=None, description="天妒惩罚：修为倒退几个大境界（1 个大境界 = 4 级）。默认 3。",
        json_schema_extra={"label": "天妒倒退境界数", "placeholder": "默认 3", "order": 59, "step": 1})


class BalanceSocialSection(PluginConfigBase):
    """⑥ 好感与交配 —— 护盾强度与夫妻互动。"""

    __ui_label__: ClassVar[str] = "⑥ 好感与交配"
    __ui_order__: ClassVar[int] = 7

    affection_per_shield: Optional[int] = Field(
        default=None, description="每多少点夫妻好感抵消一档胜率（防黄毛的护盾）。默认 20。",
        json_schema_extra={"label": "护盾档位", "placeholder": "默认 20", "order": 60, "step": 1})
    affection_shield_rate: Optional[float] = Field(
        default=None, description="每档护盾抵消多少胜率。默认 0.01（每 20 好感减 1%）。",
        json_schema_extra={"label": "护盾效率", "placeholder": "默认 0.01", "order": 61, "step": 0.005})
    affection_shield_max: Optional[float] = Field(
        default=None,
        description="护盾的**硬上限**：好感再高，也最多抵消这么多胜率。默认 0.50（50%）。",
        json_schema_extra={"label": "护盾硬上限", "placeholder": "默认 0.5", "order": 62, "step": 0.05})
    mating_affection_min: Optional[int] = Field(
        default=None, description="申请交配所需的最低夫妻好感。默认 100。",
        json_schema_extra={"label": "交配所需好感", "placeholder": "默认 100", "order": 63, "step": 10})
    mating_affection_gain: Optional[int] = Field(
        default=None, description="每次成功交配增加的好感。默认 50。",
        json_schema_extra={"label": "交配好感增益", "placeholder": "默认 50", "order": 64, "step": 10})
    mating_timeout_seconds: Optional[int] = Field(
        default=None, description="交配申请的有效期（秒），超时作废。默认 120。",
        json_schema_extra={"label": "交配申请有效期", "placeholder": "默认 120", "order": 65, "step": 10})


class BalanceExploreSection(PluginConfigBase):
    """⑦ 下秘境 —— 只有收益与好/坏结果的概率（陨落属于惩罚，见 ⑤）。"""

    __ui_label__: ClassVar[str] = "⑦ 下秘境"
    __ui_order__: ClassVar[int] = 8

    realm_dive_money_min_factor: Optional[int] = Field(
        default=None, description="金币收益下限 = 境界等级 × 本值。默认 10。",
        json_schema_extra={"label": "金币下限系数", "placeholder": "默认 10", "order": 70, "step": 10})
    realm_dive_money_max_factor: Optional[int] = Field(
        default=None, description="金币收益上限 = 境界等级 × 本值。默认 10000。",
        json_schema_extra={"label": "金币上限系数", "placeholder": "默认 10000", "order": 71, "step": 500})
    realm_dive_gold_prob: Optional[float] = Field(
        default=None, description="获得金币的概率。默认 0.70。与暴涨/倒退/陨落合计应≈1。",
        json_schema_extra={"label": "得金币概率", "placeholder": "默认 0.70", "order": 72, "step": 0.05})
    realm_dive_surge_prob: Optional[float] = Field(
        default=None, description="修为暴涨一个大境界（+4 级）的概率。默认 0.15。",
        json_schema_extra={"label": "暴涨概率", "placeholder": "默认 0.15", "order": 73, "step": 0.05})
    realm_dive_fall_prob: Optional[float] = Field(
        default=None, description="修为倒退一个大境界（-4 级）的概率。默认 0.10。",
        json_schema_extra={"label": "倒退概率", "placeholder": "默认 0.10", "order": 74, "step": 0.05})


class BalanceLoanSection(PluginConfigBase):
    """⑧ 贷款 —— 向天道借钱与逾期惩罚。"""

    __ui_label__: ClassVar[str] = "⑧ 贷款"
    __ui_order__: ClassVar[int] = 9

    loan_repay_multiplier: Optional[float] = Field(
        default=None, description="还款倍数：借 100 需还 100 × 本值。默认 2.0。",
        json_schema_extra={"label": "还款倍数", "placeholder": "默认 2.0", "order": 80, "step": 0.1})
    loan_grace_minutes: Optional[int] = Field(
        default=None,
        description="贷款时限（分钟）。超时未还清只能 /打工 /下秘境 /还贷，直到结清。默认 15。",
        json_schema_extra={"label": "贷款时限（分钟）", "placeholder": "默认 15", "order": 81, "step": 5})


class PartnerGameConfig(PluginConfigBase):
    plugin: PluginSection = Field(default_factory=PluginSection)
    partner_game: PartnerGameSection = Field(default_factory=PartnerGameSection)

    balance_cycle: BalanceCycleSection = Field(default_factory=BalanceCycleSection)
    balance_economy: BalanceEconomySection = Field(default_factory=BalanceEconomySection)
    balance_cultivation: BalanceCultivationSection = Field(default_factory=BalanceCultivationSection)
    balance_crime: BalanceCrimeSection = Field(default_factory=BalanceCrimeSection)
    balance_penalty: BalancePenaltySection = Field(default_factory=BalancePenaltySection)
    balance_social: BalanceSocialSection = Field(default_factory=BalanceSocialSection)
    balance_explore: BalanceExploreSection = Field(default_factory=BalanceExploreSection)
    balance_loan: BalanceLoanSection = Field(default_factory=BalanceLoanSection)


