"""今日老婆插件配置模型。"""
from __future__ import annotations
from typing import ClassVar, List, Dict, Optional, Union

from pydantic import field_validator
from maibot_sdk import Field, PluginConfigBase

try:                                    # 作为包的一部分导入（插件运行时）
    from . import balance as B
except ImportError:                     # 作为顶层模块导入（docs/tools、单测）
    import balance as B

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

    次数类字段的三种填法：留空=默认值；「不限制」或负数=不限次；0=禁用。
    """

    __ui_label__: ClassVar[str] = "① 周期与次数"
    __ui_order__: ClassVar[int] = 2

    cycle_hours: int = Field(
        default=B.CYCLE_HOURS,
        description=(
            "一个游戏周期是多少小时。所有「每周期 N 次」、周期低保、"
            "婚姻跨周期好感、天妒/天罚的「每天一次」判定都按它结算。\n"
            "默认 24（每天一轮）；12 = 半天一轮；168 = 一周一轮。"
        ),
        json_schema_extra={"label": "周期时长（小时）", "placeholder": "默认 24", "order": 0, "step": 1})
    draw_limit: Union[int, str] = Field(
        default=B.DRAW_LIMIT, description="每周期可用几次 /今日老婆。默认 1；「不限制」= 不限次；0 = 禁用。",
        json_schema_extra={"label": "抽老婆次数", "placeholder": "默认 1", "order": 10, "step": 1})
    divorce_limit: Union[int, str] = Field(
        default=B.DIVORCE_LIMIT, description="每周期可用几次 /离婚。默认 1；「不限制」= 不限次；0 = 禁用。",
        json_schema_extra={"label": "离婚次数", "placeholder": "默认 1", "order": 11, "step": 1})
    dump_limit: Union[int, str] = Field(
        default=B.DUMP_LIMIT, description="每周期可用几次 /甩掉。默认 1；「不限制」= 不限次；0 = 禁用。",
        json_schema_extra={"label": "甩掉次数", "placeholder": "默认 1", "order": 12, "step": 1})
    work_limit: Union[int, str] = Field(
        default=B.WORK_LIMIT, description="每周期可用几次 /打工。默认 3；「不限制」= 不限次；0 = 禁用。",
        json_schema_extra={"label": "打工次数", "placeholder": "默认 3", "order": 13, "step": 1})
    date_limit: Union[int, str] = Field(
        default=B.DATE_LIMIT, description="每周期可用几次 /约会。默认 3；「不限制」= 不限次；0 = 禁用。",
        json_schema_extra={"label": "约会次数", "placeholder": "默认 3", "order": 14, "step": 1})
    cultivate_limit: Union[int, str] = Field(
        default=B.CULTIVATE_LIMIT, description="每周期可用几次 /修炼。默认 3；「不限制」= 不限次；0 = 禁用。",
        json_schema_extra={"label": "修炼次数", "placeholder": "默认 3", "order": 15, "step": 1})
    mating_limit: Union[int, str] = Field(
        default=B.MATING_LIMIT, description="每周期夫妻可交配几次（双方共用）。默认 3；「不限制」= 不限次。",
        json_schema_extra={"label": "交配次数", "placeholder": "默认 3", "order": 17, "step": 1})


class BalanceEconomySection(PluginConfigBase):
    """② 金币与打工 —— 钱从哪来、花到哪去。"""

    __ui_label__: ClassVar[str] = "② 金币与打工"
    __ui_order__: ClassVar[int] = 3

    initial_money: int = Field(
        default=B.INITIAL_MONEY, description="新玩家第一次参与时的初始金币。默认 1000。",
        json_schema_extra={"label": "初始金币", "placeholder": "默认 1000", "order": 20, "step": 100})
    cycle_allowance: int = Field(
        default=B.CYCLE_ALLOWANCE, description="每周期首次互动时自动发放的低保。默认 200。",
        json_schema_extra={"label": "周期低保", "placeholder": "默认 200", "order": 21, "step": 50})
    work_earn_min: int = Field(
        default=B.WORK_EARN_MIN,
        description="打工收益下限，**可以为负**（负数=亏本倒贴）。实际收益在上限之间随机。默认 -100。",
        json_schema_extra={"label": "打工收益下限（可为负）", "placeholder": "默认 -100", "order": 22, "step": 10})
    work_earn_max_per_level: int = Field(
        default=B.WORK_EARN_MAX_PER_LEVEL,
        description="打工收益上限 = 当前境界等级 × 本值。默认 1000（20 级最多赚 20000）。",
        json_schema_extra={"label": "打工收益上限系数", "placeholder": "默认 1000", "order": 23, "step": 100})
    date_cost: int = Field(
        default=B.DATE_COST,
        description="每次 /约会 消耗的金币。**默认 0 = 免费**；填正数才会扣钱。",
        json_schema_extra={"label": "约会消耗（0=免费）", "placeholder": "默认 0", "order": 24, "step": 10})
    date_aff_min: int = Field(
        default=B.DATE_AFF_MIN, description="每次约会增加的好感下限。默认 10。",
        json_schema_extra={"label": "约会好感下限", "placeholder": "默认 10", "order": 25, "step": 1})
    date_aff_max: int = Field(
        default=B.DATE_AFF_MAX, description="每次约会增加的好感上限。默认 20。",
        json_schema_extra={"label": "约会好感上限", "placeholder": "默认 20", "order": 26, "step": 1})


class BalanceCultivationSection(PluginConfigBase):
    """③ 修炼与氪金 —— 境界怎么涨、钱怎么买概率。"""

    __ui_label__: ClassVar[str] = "③ 修炼与氪金"
    __ui_order__: ClassVar[int] = 4

    cultivate_cost_base: int = Field(
        default=B.CULTIVATE_COST_BASE,
        description="修炼费用系数：单次费用 = (大境界序号 + 1) × 本值。默认 50（凡境 50，飞升 1250）。",
        json_schema_extra={"label": "修炼费用系数", "placeholder": "默认 50", "order": 30, "step": 10})
    minor_success_rate: float = Field(
        default=B.MINOR_SUCCESS_RATE, description="小境界突破成功率，0~1。默认 0.8，失败无惩罚。",
        json_schema_extra={"label": "小境界成功率", "placeholder": "默认 0.8", "order": 31, "step": 0.05})
    major_success_rate: float = Field(
        default=B.MAJOR_SUCCESS_RATE, description="大境界突破成功率，0~1。默认 0.4，失败有概率掉级。",
        json_schema_extra={"label": "大境界成功率", "placeholder": "默认 0.4", "order": 32, "step": 0.05})
    major_fail_drop_rate: float = Field(
        default=B.MAJOR_FAIL_DROP_RATE, description="大境界失败后走火入魔（掉 1 级）的概率。默认 0.3。",
        json_schema_extra={"label": "走火入魔概率", "placeholder": "默认 0.3", "order": 33, "step": 0.05})
    recharge_coins_per_percent: int = Field(
        default=B.RECHARGE_COINS_PER_PERCENT,
        description=(
            "氪金换算：每多少金币换 1% 下次行动成功率。默认 100（氪 1000 = +10%）。\n"
            "作用于下一次 /打劫 /强娶 /下秘境 /修炼，用掉即清零。"
        ),
        json_schema_extra={"label": "氪金换算（金币/1%）", "placeholder": "默认 100", "order": 34, "step": 50})
    recharge_cap: float = Field(
        default=B.RECHARGE_CAP, description="氪金加成总上限，0~1。默认 0.99（最高 99%）。",
        json_schema_extra={"label": "氪金加成上限", "placeholder": "默认 0.99", "order": 35, "step": 0.01})
    recharge_min_amount: int = Field(
        default=B.RECHARGE_MIN_AMOUNT, description="单次 /氪金 的最低金额。默认 100。",
        json_schema_extra={"label": "单次氪金下限", "placeholder": "默认 100", "order": 36, "step": 50})


class BalanceMarriageSection(PluginConfigBase):
    """④ 婚姻与冷却 —— 抽取/离婚/求婚/甩人/查询 各自的冷却，以及离婚惩罚开关。"""

    __ui_label__: ClassVar[str] = "④ 婚姻与冷却"
    __ui_order__: ClassVar[int] = 5

    cooldown_draw: int = Field(
        default=B.COOLDOWN_DRAW, description="/今日老婆 的冷却秒数。默认 60；填 0 = 无冷却。",
        json_schema_extra={"label": "抽老婆冷却（秒）", "placeholder": "默认 60", "order": 40, "step": 10})
    cooldown_divorce: int = Field(
        default=B.COOLDOWN_DIVORCE, description="/离婚 的冷却秒数。默认 60；填 0 = 无冷却。",
        json_schema_extra={"label": "离婚冷却（秒）", "placeholder": "默认 60", "order": 41, "step": 10})
    cooldown_marry: int = Field(
        default=B.COOLDOWN_MARRY, description="/娶 的冷却秒数。默认 60；填 0 = 无冷却。",
        json_schema_extra={"label": "求婚冷却（秒）", "placeholder": "默认 60", "order": 42, "step": 10})
    cooldown_dump: int = Field(
        default=B.COOLDOWN_DUMP, description="/甩掉 的冷却秒数。默认 60；填 0 = 无冷却。",
        json_schema_extra={"label": "甩掉冷却（秒）", "placeholder": "默认 60", "order": 43, "step": 10})
    cooldown_my_partner: int = Field(
        default=B.COOLDOWN_MY_PARTNER, description="/我的伴侣 的冷却秒数，查询类可以设短些。默认 10。",
        json_schema_extra={"label": "查询伴侣冷却（秒）", "placeholder": "默认 10", "order": 44, "step": 5})
    cooldown_mating: int = Field(
        default=B.COOLDOWN_MATING, description="/申请交配 的冷却秒数。默认 30。",
        json_schema_extra={"label": "交配冷却（秒）", "placeholder": "默认 30", "order": 45, "step": 10})

    divorce_penalty_enabled: bool = Field(
        default=B.DIVORCE_PENALTY_ENABLED,
        description=(
            "**离婚惩罚开关**。开启后，主动解除关系（/离婚、/甩掉）时，"
            "发起方要把约定比例的财富与修为分给对方。默认关闭。"
        ),
        json_schema_extra={"label": "启用离婚惩罚", "placeholder": "默认关闭", "order": 46})
    divorce_penalty_money_ratio: float = Field(
        default=B.DIVORCE_PENALTY_MONEY_RATIO, description="离婚惩罚：分走对方「现有金币」的比例。默认 0.5（一半）。",
        json_schema_extra={"label": "离婚分走金币比例", "placeholder": "默认 0.5", "order": 47, "step": 0.1})
    divorce_penalty_level_ratio: float = Field(
        default=B.DIVORCE_PENALTY_LEVEL_RATIO, description="离婚惩罚：分走对方「境界等级」的比例。默认 0.5（一半）。",
        json_schema_extra={"label": "离婚分走修为比例", "placeholder": "默认 0.5", "order": 48, "step": 0.1})


class BalanceForceSection(PluginConfigBase):
    """⑤ 强娶 —— 本行动专属的门槛、罚款与冷却。"""

    __ui_label__: ClassVar[str] = "⑤ 强娶"
    __ui_order__: ClassVar[int] = 6

    force_gate: int = Field(
        default=B.FORCE_GATE, description="/强娶 需要的金币余额（不够则无法发起）。默认 300。",
        json_schema_extra={"label": "金币门槛", "placeholder": "默认 300", "order": 50, "step": 50})
    force_fine_floor: int = Field(
        default=B.FORCE_FINE_FLOOR, description="强娶失败的罚款下限。默认 100。",
        json_schema_extra={"label": "失败罚款下限", "placeholder": "默认 100", "order": 51, "step": 10})
    force_fine_cap_ratio: float = Field(
        default=B.FORCE_FINE_CAP_RATIO,
        description="强娶失败的罚款上限 = 行动者现有金币 × 本值。默认 1.0（最多罚光）。",
        json_schema_extra={"label": "罚款上限比例", "placeholder": "默认 1.0", "order": 52, "step": 0.1})
    cooldown_force: int = Field(
        default=B.COOLDOWN_FORCE, description="/强娶 的冷却秒数。默认 60；填 0 = 无冷却。",
        json_schema_extra={"label": "冷却（秒）", "placeholder": "默认 60", "order": 54, "step": 10})


class BalanceRobWifeSection(PluginConfigBase):
    """⑥ 抢老婆 —— 本行动专属的门槛、罚款、掉级与冷却。"""

    __ui_label__: ClassVar[str] = "⑥ 抢老婆"
    __ui_order__: ClassVar[int] = 7

    rob_wife_gate: int = Field(
        default=B.ROB_WIFE_GATE, description="/抢老婆 需要的金币余额。默认 500。",
        json_schema_extra={"label": "金币门槛", "placeholder": "默认 500", "order": 60, "step": 50})
    rob_wife_fine_floor: int = Field(
        default=B.ROB_WIFE_FINE_FLOOR, description="抢老婆失败的罚款下限。默认 100。",
        json_schema_extra={"label": "失败罚款下限", "placeholder": "默认 100", "order": 61, "step": 10})
    rob_wife_fine_cap_ratio: float = Field(
        default=B.ROB_WIFE_FINE_CAP_RATIO, description="抢老婆失败的罚款上限 = 行动者现有金币 × 本值。默认 1.0。",
        json_schema_extra={"label": "罚款上限比例", "placeholder": "默认 1.0", "order": 62, "step": 0.1})
    rob_wife_drop_chance: float = Field(
        default=B.ROB_WIFE_DROP_CHANCE, description="抢老婆失败后被反杀掉 1 级的概率。默认 0.2。",
        json_schema_extra={"label": "失败掉级概率", "placeholder": "默认 0.2", "order": 63, "step": 0.05})
    cooldown_rob_wife: int = Field(
        default=B.COOLDOWN_ROB_WIFE, description="/抢老婆 的冷却秒数。默认 60；填 0 = 无冷却。",
        json_schema_extra={"label": "冷却（秒）", "placeholder": "默认 60", "order": 65, "step": 10})


class BalanceRobMoneySection(PluginConfigBase):
    """⑦ 打劫 —— 本行动专属的门槛、金额、罚款与冷却。"""

    __ui_label__: ClassVar[str] = "⑦ 打劫"
    __ui_order__: ClassVar[int] = 8

    rob_money_cycle_hours: int = Field(
        default=B.ROB_MONEY_CYCLE_HOURS,
        description=(
            "/打劫 自己的周期时长（小时）。到点后「本周期打劫次数」自动清零。\n"
            "默认 24（每天一轮）。改成 12 就是半天一刷新，改成 168 就是一周一刷新；\n"
            "只影响打劫，不影响打工、秘境等其他行动。"
        ),
        json_schema_extra={"label": "打劫周期（小时）", "placeholder": "默认 24", "order": 68, "step": 1})
    rob_money_limit: Union[int, str] = Field(
        default=B.ROB_MONEY_LIMIT,
        description=(
            "/打劫 每个周期可用几次（这是打劫自己的周期次数，与其他行动互不影响）。\n"
            "默认 3；填「不限制」= 不限次；填 0 = 禁止打劫。"
        ),
        json_schema_extra={"label": "每周期打劫次数", "placeholder": "默认 3", "order": 69, "step": 1})
    rob_money_gate: int = Field(
        default=B.ROB_MONEY_GATE, description="/打劫 需要的金币余额。默认 300。",
        json_schema_extra={"label": "金币门槛", "placeholder": "默认 300", "order": 70, "step": 50})
    rob_money_cap_ratio: float = Field(
        default=B.ROB_MONEY_CAP_RATIO,
        description="单次最多抢走受害者金币的倍数。默认 1.5（最多打成 -50% 负债）；1.0 = 最多抢光。",
        json_schema_extra={"label": "劫掠上限倍数", "placeholder": "默认 1.5", "order": 71, "step": 0.1})
    rob_money_negative_cap: int = Field(
        default=B.ROB_MONEY_NEGATIVE_CAP, description="受害者资产 ≤ 0 时单次打劫的金额上限。默认 100。",
        json_schema_extra={"label": "负资产打劫上限", "placeholder": "默认 100", "order": 72, "step": 10})
    rob_money_fine_floor: int = Field(
        default=B.ROB_MONEY_FINE_FLOOR, description="打劫失败的罚款下限。默认 100。",
        json_schema_extra={"label": "失败罚款下限", "placeholder": "默认 100", "order": 73, "step": 10})
    rob_money_fine_cap_ratio: float = Field(
        default=B.ROB_MONEY_FINE_CAP_RATIO, description="打劫失败的罚款上限 = 行动者现有金币 × 本值。默认 1.0。",
        json_schema_extra={"label": "罚款上限比例", "placeholder": "默认 1.0", "order": 74, "step": 0.1})
    cooldown_rob_money: int = Field(
        default=B.COOLDOWN_ROB_MONEY, description="/打劫 的冷却秒数。默认 60；填 0 = 无冷却。",
        json_schema_extra={"label": "冷却（秒）", "placeholder": "默认 60", "order": 76, "step": 10})
    rob_floor: float = Field(
        default=B.ROB_FLOOR,
        description="抢夺/打劫的胜率下限，再劣势也不会低于它。默认 0.1（10%）。",
        json_schema_extra={"label": "胜率下限（共用）", "placeholder": "默认 0.1", "order": 77, "step": 0.01})
    rob_cap: float = Field(
        default=B.ROB_CAP,
        description="抢夺/打劫的胜率上限，再优势也不会超过它。默认 0.9（90%）。氪金可突破到氪金上限。",
        json_schema_extra={"label": "胜率上限（共用）", "placeholder": "默认 0.9", "order": 78, "step": 0.01})


class BalanceSocialSection(PluginConfigBase):
    """⑧ 好感与交配 —— 好感度怎么保护夫妻、夫妻怎么互动。

    好感护盾是什么（直白版）：
      夫妻一起约会、交配会积累「好感度」。
      当别人来 /抢老婆 时，好感度会直接抵扣对方的成功率 ——
      每 X 点好感抵扣 1%，但最多只抵扣到上限（默认 50%）。
      也就是说：好感越高越安全，但永远无法完全免疫被抢。
    """

    __ui_label__: ClassVar[str] = "⑧ 好感与交配"
    __ui_order__: ClassVar[int] = 9

    affection_per_shield: int = Field(
        default=B.AFFECTION_PER_SHIELD,
        description="每多少点好感抵扣 1% 被抢成功率。默认 20（即 100 好感 = -5%）。",
        json_schema_extra={"label": "好感抵扣档位", "placeholder": "默认 20", "order": 80, "step": 1})
    affection_shield_rate: float = Field(
        default=B.AFFECTION_SHIELD_RATE, description="每档抵扣多少成功率。默认 0.01（1%）。一般只改上面那个档位即可。",
        json_schema_extra={"label": "每档抵扣比例", "placeholder": "默认 0.01", "order": 81, "step": 0.005})
    affection_shield_max: float = Field(
        default=B.AFFECTION_SHIELD_MAX,
        description="抵扣的**硬上限**：好感堆再高，也最多抵扣这么多。默认 0.5（50%）。",
        json_schema_extra={"label": "抵扣硬上限", "placeholder": "默认 0.5", "order": 82, "step": 0.05})
    mating_affection_min: int = Field(
        default=B.MATING_AFFECTION_MIN, description="申请交配所需的最低好感。默认 100。",
        json_schema_extra={"label": "交配所需好感", "placeholder": "默认 100", "order": 83, "step": 10})
    mating_affection_gain: int = Field(
        default=B.MATING_AFFECTION_GAIN, description="每次成功交配增加的好感。默认 50。",
        json_schema_extra={"label": "交配好感增益", "placeholder": "默认 50", "order": 84, "step": 10})
    mating_timeout_seconds: int = Field(
        default=B.MATING_TIMEOUT_SECONDS, description="交配申请的有效期（秒），超时作废。默认 120。",
        json_schema_extra={"label": "交配申请有效期", "placeholder": "默认 120", "order": 85, "step": 10})


class BalanceExploreSection(PluginConfigBase):
    """⑨ 下秘境 —— 只有收益与好/坏结果的概率（陨落属于天道惩戒）。"""

    __ui_label__: ClassVar[str] = "⑨ 下秘境"
    __ui_order__: ClassVar[int] = 10

    realm_dive_cycle_hours: int = Field(
        default=B.REALM_DIVE_CYCLE_HOURS,
        description=(
            "/下秘境 自己的周期时长（小时）。到点后「本周期秘境次数」自动清零。\n"
            "默认 24。只影响下秘境，不影响打劫、打工等其他行动。"
        ),
        json_schema_extra={"label": "秘境周期（小时）", "placeholder": "默认 24", "order": 88, "step": 1})
    realm_dive_limit: Union[int, str] = Field(
        default=B.REALM_DIVE_LIMIT,
        description=(
            "/下秘境 每个周期可用几次（这是秘境自己的周期次数，与打劫等其他行动无关）。\n"
            "默认 1；填「不限制」= 不限次；填 0 = 禁止下秘境。"
        ),
        json_schema_extra={"label": "每周期秘境次数", "placeholder": "默认 1", "order": 89, "step": 1})
    realm_dive_money_min_factor: int = Field(
        default=B.REALM_DIVE_MONEY_MIN_FACTOR, description="金币收益下限 = 境界等级 × 本值。默认 10。",
        json_schema_extra={"label": "金币下限系数", "placeholder": "默认 10", "order": 90, "step": 10})
    realm_dive_money_max_factor: int = Field(
        default=B.REALM_DIVE_MONEY_MAX_FACTOR, description="金币收益上限 = 境界等级 × 本值。默认 10000。",
        json_schema_extra={"label": "金币上限系数", "placeholder": "默认 10000", "order": 91, "step": 500})
    realm_dive_gold_prob: float = Field(
        default=B.REALM_DIVE_GOLD_PROB, description="获得金币的概率。默认 0.70。与其他结果合计应≈1。",
        json_schema_extra={"label": "得金币概率", "placeholder": "默认 0.70", "order": 92, "step": 0.05})
    realm_dive_surge_prob: float = Field(
        default=B.REALM_DIVE_SURGE_PROB, description="修为暴涨一个大境界（+4 级）的概率。默认 0.15。",
        json_schema_extra={"label": "暴涨概率", "placeholder": "默认 0.15", "order": 93, "step": 0.05})
    realm_dive_surge_levels: int = Field(
        default=B.REALM_DIVE_SURGE_LEVELS,
        description="「修为暴涨」时提升几级（4 级 = 1 个大境界）。默认 4。",
        json_schema_extra={"label": "暴涨提升等级数", "placeholder": "默认 4", "order": 95, "step": 1})
    realm_dive_fall_levels: int = Field(
        default=B.REALM_DIVE_FALL_LEVELS,
        description="「修为倒退」时跌落几级（4 级 = 1 个大境界）。默认 4。",
        json_schema_extra={"label": "倒退跌落等级数", "placeholder": "默认 4", "order": 96, "step": 1})
    realm_dive_fall_prob: float = Field(
        default=B.REALM_DIVE_FALL_PROB, description="修为倒退一个大境界（-4 级）的概率。默认 0.10。",
        json_schema_extra={"label": "倒退概率", "placeholder": "默认 0.10", "order": 94, "step": 0.05})


class BalanceLoanSection(PluginConfigBase):
    """⑩ 贷款 —— 向天道借钱与逾期惩罚。"""

    __ui_label__: ClassVar[str] = "⑩ 贷款"
    __ui_order__: ClassVar[int] = 11

    loan_repay_multiplier: float = Field(
        default=B.LOAN_REPAY_MULTIPLIER, description="还款倍数：借 100 需还 100 × 本值。默认 2.0。",
        json_schema_extra={"label": "还款倍数", "placeholder": "默认 2.0", "order": 100, "step": 0.1})
    loan_grace_minutes: int = Field(
        default=B.LOAN_GRACE_MINUTES,
        description="贷款时限（分钟）。超时未还清只能 /打工 /下秘境 /还贷，直到结清。默认 15。",
        json_schema_extra={"label": "贷款时限（分钟）", "placeholder": "默认 15", "order": 101, "step": 5})


class BalanceHeavenSection(PluginConfigBase):
    """⑪ 天道惩戒 —— 天妒、天罚、秘境陨落这类全局惩罚。"""

    __ui_label__: ClassVar[str] = "⑪ 天道惩戒"
    __ui_order__: ClassVar[int] = 12

    tian_du_success_threshold: int = Field(
        default=B.TIAN_DU_SUCCESS_THRESHOLD,
        description=(
            "天妒：每周期内「修炼成功」达到此次数即触发，修为倒退若干大境界，每周期一次。\n"
            "默认 6。填 0 或负数 = 关闭天妒。"
        ),
        json_schema_extra={"label": "天妒触发次数", "placeholder": "默认 6", "order": 110, "step": 1})
    tian_du_drop_realms: int = Field(
        default=B.TIAN_DU_DROP_REALMS, description="天妒惩罚：修为倒退几个大境界（1 个 = 4 级）。默认 3。",
        json_schema_extra={"label": "天妒倒退境界数", "placeholder": "默认 3", "order": 111, "step": 1})
    tian_fa_crime_threshold: int = Field(
        default=B.TIAN_FA_CRIME_THRESHOLD,
        description=(
            "天罚：每周期内「打劫+强娶+抢老婆」总次数超过此值即触发，扣金币，每周期一次。\n"
            "默认 8。填 0 或负数 = 关闭天罚。"
        ),
        json_schema_extra={"label": "天罚触发次数", "placeholder": "默认 8", "order": 112, "step": 1})
    tian_fa_money_ratio: float = Field(
        default=B.TIAN_FA_MONEY_RATIO, description="天罚惩罚：扣除现有金币的比例。默认 0.6（60%）。",
        json_schema_extra={"label": "天罚扣钱比例", "placeholder": "默认 0.6", "order": 113, "step": 0.1})
    rebirth_keep_ratio: float = Field(
        default=B.REBIRTH_KEEP_RATIO,
        description=(
            "重生（主动 /重生 或陨落时自动触发）后保留的修为比例。默认 0.7 = 保留 70% 等级。\n"
            "其余一切（金币、伴侣、贷款、氪金加成、本周期次数与冷却）全部重置。"
        ),
        json_schema_extra={"label": "重生保留修为比例", "placeholder": "默认 0.7", "order": 109, "step": 0.05})
    realm_dive_death_prob: float = Field(
        default=B.REALM_DIVE_DEATH_PROB, description="下秘境陨落的概率：修为归零、金币保留。默认 0.05。",
        json_schema_extra={"label": "秘境·陨落概率", "placeholder": "默认 0.05", "order": 114, "step": 0.01})
    fine_compensation_ratio: float = Field(
        default=B.FINE_COMPENSATION_RATIO,
        description="所有罚款中赔付给对手的比例，0~1。默认 0.5（一半赔对方、一半蒸发）。",
        json_schema_extra={"label": "罚款赔付比例", "placeholder": "默认 0.5", "order": 115, "step": 0.05})


class BalanceBeastSection(PluginConfigBase):
    """⑫ 打怪 —— 主动挑战怪物，赌金币 / 涨修为 / 掉境界 / 陨落。

    这是独立于「秘境」的另一条高风险收益线：秘境偏金币，打怪偏修为。
    """

    __ui_label__: ClassVar[str] = "⑫ 打怪"
    __ui_order__: ClassVar[int] = 13

    beast_limit: Union[int, str] = Field(
        default=B.BEAST_LIMIT,
        description="每周期可以打几次怪。默认 3；填「不限制」= 不限次；填 0 = 禁止打怪。",
        json_schema_extra={"label": "每周期打怪次数", "placeholder": "默认 3", "order": 120, "step": 1})
    cooldown_beast: int = Field(
        default=B.COOLDOWN_BEAST,
        description="打怪的冷却秒数。默认 60；填 0 = 无冷却。",
        json_schema_extra={"label": "冷却（秒）", "placeholder": "默认 60", "order": 121, "step": 10})
    beast_money_min_factor: int = Field(
        default=B.BEAST_MONEY_MIN_FACTOR,
        description="获得金币时的下限 = 当前境界等级 × 本值。默认 100。",
        json_schema_extra={"label": "金币下限系数", "placeholder": "默认 100", "order": 122, "step": 50})
    beast_money_max_factor: int = Field(
        default=B.BEAST_MONEY_MAX_FACTOR,
        description="获得金币时的上限 = 当前境界等级 × 本值。默认 5000。",
        json_schema_extra={"label": "金币上限系数", "placeholder": "默认 5000", "order": 123, "step": 500})
    beast_gain_levels: int = Field(
        default=B.BEAST_GAIN_LEVELS,
        description="修为提升时增加几级（4 级 = 1 个大境界）。默认 4。",
        json_schema_extra={"label": "提升等级数", "placeholder": "默认 4", "order": 124, "step": 1})
    beast_lose_levels: int = Field(
        default=B.BEAST_LOSE_LEVELS,
        description="境界跌落时减少几级（4 级 = 1 个大境界）。默认 4。",
        json_schema_extra={"label": "跌落等级数", "placeholder": "默认 4", "order": 125, "step": 1})
    beast_gold_prob: float = Field(
        default=B.BEAST_GOLD_PROB,
        description="打怪获得大量金币的概率。默认 0.55。四种结果合计应约等于 1。",
        json_schema_extra={"label": "得金币概率", "placeholder": "默认 0.55", "order": 126, "step": 0.05})
    beast_gain_prob: float = Field(
        default=B.BEAST_GAIN_PROB,
        description="打怪修为提升的概率。默认 0.25。",
        json_schema_extra={"label": "修为提升概率", "placeholder": "默认 0.25", "order": 127, "step": 0.05})
    beast_lose_prob: float = Field(
        default=B.BEAST_LOSE_PROB,
        description="打怪境界跌落的概率。默认 0.15。",
        json_schema_extra={"label": "境界跌落概率", "placeholder": "默认 0.15", "order": 128, "step": 0.05})
    beast_death_prob: float = Field(
        default=B.BEAST_DEATH_PROB,
        description="打怪陨落的概率。默认 0.05。陨落会自动触发重生。",
        json_schema_extra={"label": "陨落概率", "placeholder": "默认 0.05", "order": 129, "step": 0.01})


class BalanceBullySection(PluginConfigBase):
    """⑬ 霸凌 —— 高境界者对低境界者的压制，抢点钱并封锁对方行动。

    发起条件：自己的境界必须比对方高 BULLY_LEVEL_GAP 级（默认 8 级 = 2 个大境界）。
    """

    __ui_label__: ClassVar[str] = "⑬ 霸凌"
    __ui_order__: ClassVar[int] = 14

    bully_cycle_hours: int = Field(
        default=B.BULLY_CYCLE_HOURS,
        description="/霸凌 自己的周期时长（小时），到点后本周期次数清零。默认 24。",
        json_schema_extra={"label": "霸凌周期（小时）", "placeholder": "默认 24", "order": 130, "step": 1})
    cooldown_bully: int = Field(
        default=B.COOLDOWN_BULLY,
        description="两次 /霸凌 之间的冷却秒数。默认 60。",
        json_schema_extra={"label": "冷却（秒）", "placeholder": "默认 60", "order": 131, "step": 10})
    bully_limit: Union[int, str] = Field(
        default=B.BULLY_LIMIT,
        description="每周期可霸凌几次。默认 3；填「不限制」= 不限次；0 = 禁用。",
        json_schema_extra={"label": "周期内霸凌次数", "placeholder": "默认 3", "order": 132, "step": 1})
    bully_level_gap: int = Field(
        default=B.BULLY_LEVEL_GAP,
        description="发起霸凌所需的最小境界差（级）。默认 8（= 2 个大境界）。",
        json_schema_extra={"label": "所需境界差（级）", "placeholder": "默认 8", "order": 133, "step": 4})
    bully_ban_seconds: int = Field(
        default=B.BULLY_BAN_SECONDS,
        description="霸凌成功后，受害者被封锁行动的时长（秒）。默认 600（10 分钟）。",
        json_schema_extra={"label": "被封禁时长（秒）", "placeholder": "默认 600", "order": 134, "step": 60})
    bully_success_prob: float = Field(
        default=B.BULLY_SUCCESS_PROB,
        description="霸凌成功率，0~1。默认 0.6。",
        json_schema_extra={"label": "霸凌成功率", "placeholder": "默认 0.6", "order": 135, "step": 0.05})
    bully_steal_min: int = Field(
        default=B.BULLY_STEAL_MIN,
        description="霸凌成功时抢走金币的下限。默认 50。",
        json_schema_extra={"label": "抢夺金币下限", "placeholder": "默认 50", "order": 136, "step": 10})
    bully_steal_max: int = Field(
        default=B.BULLY_STEAL_MAX,
        description="霸凌成功时抢走金币的上限。默认 300。",
        json_schema_extra={"label": "抢夺金币上限", "placeholder": "默认 300", "order": 137, "step": 10})
    bully_pay_ratio_min: float = Field(
        default=B.BULLY_PAY_RATIO_MIN,
        description="霸凌失败时，赔给对方「自己现有金币」的比例下限。默认 0.05。",
        json_schema_extra={"label": "失败赔付比例下限", "placeholder": "默认 0.05", "order": 138, "step": 0.01})
    bully_pay_ratio_max: float = Field(
        default=B.BULLY_PAY_RATIO_MAX,
        description="霸凌失败时，赔给对方「自己现有金币」的比例上限。默认 0.15。",
        json_schema_extra={"label": "失败赔付比例上限", "placeholder": "默认 0.15", "order": 139, "step": 0.01})


class BalanceSuppressSection(PluginConfigBase):
    """⑭ 镇压 —— 压倒性境界差才能发动，连对方伴侣一起封禁并打落修为。

    发起条件：自己的境界必须比对方高 SUPPRESS_LEVEL_GAP 级（默认 16 级 = 4 个大境界）。
    周期按自然日结算（24 小时且与零点对齐）。
    """

    __ui_label__: ClassVar[str] = "⑭ 镇压"
    __ui_order__: ClassVar[int] = 15

    suppress_cycle_hours: int = Field(
        default=B.SUPPRESS_CYCLE_HOURS,
        description=(
            "/镇压 的周期时长（小时）。默认 24，且与自然日零点对齐（每日零点重置次数）。\n"
            "填其它值则按该小时数滚动重置。"
        ),
        json_schema_extra={"label": "镇压周期（小时，24=每日零点）", "placeholder": "默认 24", "order": 140, "step": 1})
    cooldown_suppress: int = Field(
        default=B.COOLDOWN_SUPPRESS,
        description="两次 /镇压 之间的冷却秒数。默认 600（10 分钟）。",
        json_schema_extra={"label": "冷却（秒）", "placeholder": "默认 600", "order": 141, "step": 60})
    suppress_limit: Union[int, str] = Field(
        default=B.SUPPRESS_LIMIT,
        description="每周期可镇压几次。默认 1；填「不限制」= 不限次；0 = 禁用。",
        json_schema_extra={"label": "周期内镇压次数", "placeholder": "默认 1", "order": 142, "step": 1})
    suppress_level_gap: int = Field(
        default=B.SUPPRESS_LEVEL_GAP,
        description="发起镇压所需的最小境界差（级）。默认 16（= 4 个大境界）。",
        json_schema_extra={"label": "所需境界差（级）", "placeholder": "默认 16", "order": 143, "step": 4})
    suppress_ban_seconds: int = Field(
        default=B.SUPPRESS_BAN_SECONDS,
        description="镇压成功后，被镇压者被封禁的时长（秒）。默认 1800（30 分钟）。",
        json_schema_extra={"label": "被镇压者封禁时长（秒）", "placeholder": "默认 1800", "order": 144, "step": 300})
    suppress_partner_ban_seconds: int = Field(
        default=B.SUPPRESS_PARTNER_BAN_SECONDS,
        description="镇压成功后，被镇压者「伴侣」被封禁的时长（秒）。默认 1800。",
        json_schema_extra={"label": "伴侣封禁时长（秒）", "placeholder": "默认 1800", "order": 145, "step": 300})
    suppress_success_prob: float = Field(
        default=B.SUPPRESS_SUCCESS_PROB,
        description="镇压成功率，0~1。默认 0.5。",
        json_schema_extra={"label": "镇压成功率", "placeholder": "默认 0.5", "order": 146, "step": 0.05})
    suppress_drop_levels: int = Field(
        default=B.SUPPRESS_DROP_LEVELS,
        description="镇压成功时，让对方夫妻各自跌落的等级数。默认 4（= 1 个大境界）。",
        json_schema_extra={"label": "成功时对方跌落等级", "placeholder": "默认 4", "order": 147, "step": 1})
    suppress_fail_self_drop: int = Field(
        default=B.SUPPRESS_FAIL_SELF_DROP,
        description="镇压失败时，自己跌落的等级数。默认 1。",
        json_schema_extra={"label": "失败时自己跌落等级", "placeholder": "默认 1", "order": 148, "step": 1})
    suppress_pay_ratio_min: float = Field(
        default=B.SUPPRESS_PAY_RATIO_MIN,
        description="镇压失败时，赔给对方「自己现有金币」的比例下限。默认 0.10。",
        json_schema_extra={"label": "失败赔付比例下限", "placeholder": "默认 0.10", "order": 149, "step": 0.01})
    suppress_pay_ratio_max: float = Field(
        default=B.SUPPRESS_PAY_RATIO_MAX,
        description="镇压失败时，赔给对方「自己现有金币」的比例上限。默认 0.30。",
        json_schema_extra={"label": "失败赔付比例上限", "placeholder": "默认 0.30", "order": 150, "step": 0.01})


class PartnerGameConfig(PluginConfigBase):
    plugin: PluginSection = Field(default_factory=PluginSection)
    partner_game: PartnerGameSection = Field(default_factory=PartnerGameSection)

    balance_cycle: BalanceCycleSection = Field(default_factory=BalanceCycleSection)
    balance_economy: BalanceEconomySection = Field(default_factory=BalanceEconomySection)
    balance_cultivation: BalanceCultivationSection = Field(default_factory=BalanceCultivationSection)
    balance_marriage: BalanceMarriageSection = Field(default_factory=BalanceMarriageSection)
    balance_force: BalanceForceSection = Field(default_factory=BalanceForceSection)
    balance_rob_wife: BalanceRobWifeSection = Field(default_factory=BalanceRobWifeSection)
    balance_rob_money: BalanceRobMoneySection = Field(default_factory=BalanceRobMoneySection)
    balance_social: BalanceSocialSection = Field(default_factory=BalanceSocialSection)
    balance_explore: BalanceExploreSection = Field(default_factory=BalanceExploreSection)
    balance_loan: BalanceLoanSection = Field(default_factory=BalanceLoanSection)
    balance_heaven: BalanceHeavenSection = Field(default_factory=BalanceHeavenSection)
    balance_beast: BalanceBeastSection = Field(default_factory=BalanceBeastSection)
    balance_bully: BalanceBullySection = Field(default_factory=BalanceBullySection)
    balance_suppress: BalanceSuppressSection = Field(default_factory=BalanceSuppressSection)


