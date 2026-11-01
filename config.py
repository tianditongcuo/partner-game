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


class BalanceSection(PluginConfigBase):
    """数值平衡覆盖层 —— 所有可调数值的 WebUI 入口。

    使用方式
    --------
    - **留空**：使用 balance.py 里的出厂默认值（说明里会写「默认 xx」）；
    - **填数字**：覆盖默认值，保存后热重载立即生效，不必改代码或重新部署；
    - **次数类字段**：填「不限制」或任意负数 = 不限次；填 0 = 完全禁用。
    """

    __ui_label__: ClassVar[str] = "数值平衡（留空=用默认值）"
    __ui_order__: ClassVar[int] = 2

    # ==================== 周期 ====================
    cycle_hours: Optional[int] = Field(
        default=None,
        description=(
            "一个游戏周期是多少小时。所有「每周期 N 次」的限制、周期低保、"
            "婚姻跨周期好感，都按这个周期结算。\n"
            "默认 24（每天一轮）；填 12 = 半天一轮；填 168 = 一周一轮。"
        ),
        json_schema_extra={"label": "周期时长（小时）", "placeholder": "默认 24", "order": 0, "step": 1},
    )

    # ==================== 每周期次数 ====================
    draw_limit: Optional[Union[int, str]] = Field(
        default=None,
        description="每个周期可以用几次 /今日老婆。默认 1；填「不限制」= 不限次；填 0 = 禁用抽取。",
        json_schema_extra={"label": "抽老婆次数", "placeholder": "默认 1；填「不限制」= 不限次", "order": 10, "step": 1})
    divorce_limit: Optional[Union[int, str]] = Field(
        default=None,
        description="每个周期可以用几次 /离婚。默认 1；填「不限制」= 不限次；填 0 = 禁止离婚。",
        json_schema_extra={"label": "离婚次数", "placeholder": "默认 1；填「不限制」= 不限次", "order": 11, "step": 1})
    dump_limit: Optional[Union[int, str]] = Field(
        default=None,
        description="每个周期可以用几次 /甩掉。默认 1；填「不限制」= 不限次；填 0 = 禁止甩人。",
        json_schema_extra={"label": "甩掉次数", "placeholder": "默认 1；填「不限制」= 不限次", "order": 12, "step": 1})
    work_limit: Optional[Union[int, str]] = Field(
        default=None,
        description="每个周期可以用几次 /打工。默认 3；填「不限制」= 不限次；填 0 = 禁止打工。",
        json_schema_extra={"label": "打工次数", "placeholder": "默认 3；填「不限制」= 不限次", "order": 13, "step": 1})
    date_limit: Optional[Union[int, str]] = Field(
        default=None,
        description="每个周期可以用几次 /约会。默认 3；填「不限制」= 不限次；填 0 = 禁止约会。",
        json_schema_extra={"label": "约会次数", "placeholder": "默认 3；填「不限制」= 不限次", "order": 14, "step": 1})
    cultivate_limit: Optional[Union[int, str]] = Field(
        default=None,
        description="每个周期可以用几次 /修炼。默认 3；填「不限制」= 不限次；填 0 = 禁止修炼。",
        json_schema_extra={"label": "修炼次数", "placeholder": "默认 3；填「不限制」= 不限次", "order": 15, "step": 1})
    rob_money_limit: Optional[Union[int, str]] = Field(
        default=None,
        description="每个周期可以用几次 /打劫。默认 3；填「不限制」= 不限次；填 0 = 禁止打劫。",
        json_schema_extra={"label": "打劫次数", "placeholder": "默认 3；填「不限制」= 不限次", "order": 16, "step": 1})
    mating_limit: Optional[Union[int, str]] = Field(
        default=None,
        description="每个周期夫妻可以交配几次（双方共用这个上限）。默认 3；填「不限制」= 不限次。",
        json_schema_extra={"label": "交配次数", "placeholder": "默认 3；填「不限制」= 不限次", "order": 17, "step": 1})

    # ==================== 打工 ====================
    work_earn_min: Optional[int] = Field(
        default=None,
        description=(
            "打工收益的下限，可以是负数 —— 负数表示这一趟倒贴（亏本）。\n"
            "实际收益在「下限」与「上限」之间随机取。默认 -100。"
        ),
        json_schema_extra={"label": "打工收益下限（可为负）", "placeholder": "默认 -100", "order": 50, "step": 10})
    work_earn_max_per_level: Optional[int] = Field(
        default=None,
        description=(
            "打工收益的上限系数：上限 = 当前境界等级 × 本值。\n"
            "默认 1000，即 20 级的人一趟最多赚 20000；0 级时上限为 0。"
        ),
        json_schema_extra={"label": "打工收益上限系数（×等级）", "placeholder": "默认 1000", "order": 51, "step": 100})

    # ==================== 约会 ====================
    date_cost: Optional[int] = Field(
        default=None,
        description="每次 /约会 消耗的金币。默认 50。",
        json_schema_extra={"label": "约会消耗", "placeholder": "默认 50", "order": 52, "step": 10})
    date_aff_min: Optional[int] = Field(
        default=None,
        description="每次约会增加的好感下限。默认 10。",
        json_schema_extra={"label": "约会好感下限", "placeholder": "默认 10", "order": 53, "step": 1})
    date_aff_max: Optional[int] = Field(
        default=None,
        description="每次约会增加的好感上限。默认 20。",
        json_schema_extra={"label": "约会好感上限", "placeholder": "默认 20", "order": 54, "step": 1})

    # ==================== 交配 ====================
    mating_affection_min: Optional[int] = Field(
        default=None,
        description=(
            "申请交配所需的最低夫妻好感度。没到这个数的夫妻不能申请。\n"
            "好感可以通过 /约会 与每次成功交配增长。默认 100。"
        ),
        json_schema_extra={"label": "交配所需好感", "placeholder": "默认 100", "order": 56, "step": 10})
    mating_affection_gain: Optional[int] = Field(
        default=None,
        description="每次成功交配后，夫妻好感度增加多少。默认 50。",
        json_schema_extra={"label": "交配好感增益", "placeholder": "默认 50", "order": 57, "step": 10})
    mating_timeout_seconds: Optional[int] = Field(
        default=None,
        description="交配申请的有效期（秒）。对方超时未回复则申请作废。默认 120。",
        json_schema_extra={"label": "交配申请有效期（秒）", "placeholder": "默认 120", "order": 58, "step": 10})

    # ==================== 修炼 ====================
    cultivate_cost_base: Optional[int] = Field(
        default=None,
        description=(
            "修炼费用系数。单次费用 = (当前大境界序号 + 1) × 本值。\n"
            "默认 50：凡境每次 50，飞升阶段每次 1250。"
        ),
        json_schema_extra={"label": "修炼费用系数", "placeholder": "默认 50", "order": 40, "step": 10})
    minor_success_rate: Optional[float] = Field(
        default=None,
        description="突破小境界（前期→中期→后期→圆满）的成功率，0~1。默认 0.8，失败无惩罚。",
        json_schema_extra={"label": "小境界成功率", "placeholder": "默认 0.8", "order": 41, "step": 0.05})
    major_success_rate: Optional[float] = Field(
        default=None,
        description="突破大境界的成功率，0~1。默认 0.4，失败有概率掉级。",
        json_schema_extra={"label": "大境界成功率", "placeholder": "默认 0.4", "order": 42, "step": 0.05})
    major_fail_drop_rate: Optional[float] = Field(
        default=None,
        description="大境界突破失败后，走火入魔掉落 1 级的概率，0~1。默认 0.3。",
        json_schema_extra={"label": "走火入魔概率", "placeholder": "默认 0.3", "order": 43, "step": 0.05})

    # ==================== 门槛 ====================
    force_gate: Optional[int] = Field(
        default=None,
        description="发起 /强娶 需要的金币余额，不够就不许发起。默认 300。",
        json_schema_extra={"label": "强娶金币门槛", "placeholder": "默认 300", "order": 20, "step": 50})
    rob_wife_gate: Optional[int] = Field(
        default=None,
        description="发起 /抢老婆 需要的金币余额。默认 500。",
        json_schema_extra={"label": "抢老婆金币门槛", "placeholder": "默认 500", "order": 21, "step": 50})
    rob_money_gate: Optional[int] = Field(
        default=None,
        description="发起 /打劫 需要的金币余额。默认 300。",
        json_schema_extra={"label": "打劫金币门槛", "placeholder": "默认 300", "order": 22, "step": 50})

    # ==================== 打劫金额 ====================
    rob_money_cap_ratio: Optional[float] = Field(
        default=None,
        description=(
            "单次打劫最多抢走受害者当前金币的多少倍。\n"
            "默认 1.5，表示最多把人打成负 50%% 的负债；填 1.0 表示最多抢光、不负债。"
        ),
        json_schema_extra={"label": "打劫上限倍数", "placeholder": "默认 1.5", "order": 23, "step": 0.1})
    rob_money_negative_cap: Optional[int] = Field(
        default=None,
        description="受害者资产小于等于 0 时，单次打劫的金额上限，避免负资产玩家被无限刷。默认 100。",
        json_schema_extra={"label": "负资产打劫上限", "placeholder": "默认 100", "order": 24, "step": 10})

    # ==================== 罚款 ====================
    fine_floor: Optional[int] = Field(
        default=None,
        description="强娶/抢老婆/打劫失败时的罚款下限，无论多穷都至少罚这么多。默认 100。",
        json_schema_extra={"label": "罚款下限", "placeholder": "默认 100", "order": 30, "step": 10})
    fine_cap_ratio: Optional[float] = Field(
        default=None,
        description=(
            "罚款上限 = 行动者现有金币 × 本值。默认 1.0（最多把身上的钱罚光）。\n"
            "实际罚款在下限与上限之间随机；若金币少于下限，则按金币数封顶。"
        ),
        json_schema_extra={"label": "罚款上限比例", "placeholder": "默认 1.0", "order": 31, "step": 0.1})
    fine_compensation_ratio: Optional[float] = Field(
        default=None,
        description=(
            "罚款中赔付给对手的比例，0~1。默认 0.5（一半赔给对方、一半蒸发进回收池）。\n"
            "填 0 = 全部蒸发；填 1 = 全额赔给对方。"
        ),
        json_schema_extra={"label": "罚款赔付比例", "placeholder": "默认 0.5", "order": 32, "step": 0.05})

    # ==================== 贷款 ====================
    loan_repay_multiplier: Optional[float] = Field(
        default=None,
        description="还款倍数：借 100 需要还 100 × 本值。默认 2.0。",
        json_schema_extra={"label": "还款倍数", "placeholder": "默认 2.0", "order": 26, "step": 0.1})
    loan_grace_minutes: Optional[int] = Field(
        default=None,
        description=(
            "贷款时限（分钟）。超时未还清会封禁一切主动行为，"
            "只剩 /打工、/下秘境、/还贷 可用，直到结清为止。默认 15。"
        ),
        json_schema_extra={"label": "贷款时限（分钟）", "placeholder": "默认 15", "order": 27, "step": 5})

    # ==================== 下秘境 ====================
    realm_dive_limit: Optional[Union[int, str]] = Field(
        default=None,
        description="每个周期可以下几次秘境。默认 1；填「不限制」= 不限次。",
        json_schema_extra={"label": "秘境次数", "placeholder": "默认 1；填「不限制」= 不限次", "order": 28, "step": 1})
    realm_dive_money_min_factor: Optional[int] = Field(
        default=None,
        description="秘境金币收益下限 = 境界等级 × 本值。默认 10。",
        json_schema_extra={"label": "秘境金币下限系数", "placeholder": "默认 10", "order": 80, "step": 10})
    realm_dive_money_max_factor: Optional[int] = Field(
        default=None,
        description="秘境金币收益上限 = 境界等级 × 本值。默认 10000。",
        json_schema_extra={"label": "秘境金币上限系数", "placeholder": "默认 10000", "order": 81, "step": 500})
    realm_dive_gold_prob: Optional[float] = Field(
        default=None,
        description="下秘境获得金币的概率。默认 0.70。四种结果合计应约等于 1。",
        json_schema_extra={"label": "秘境·得金币", "placeholder": "默认 0.70", "order": 82, "step": 0.05})
    realm_dive_surge_prob: Optional[float] = Field(
        default=None,
        description="下秘境修为暴涨一个大境界（+4 级）的概率。默认 0.15。",
        json_schema_extra={"label": "秘境·暴涨", "placeholder": "默认 0.15", "order": 83, "step": 0.05})
    realm_dive_fall_prob: Optional[float] = Field(
        default=None,
        description="下秘境修为倒退一个大境界（-4 级）的概率。默认 0.10。",
        json_schema_extra={"label": "秘境·倒退", "placeholder": "默认 0.10", "order": 84, "step": 0.05})
    realm_dive_death_prob: Optional[float] = Field(
        default=None,
        description="下秘境陨落的概率：修为归零、金币保留。默认 0.05。",
        json_schema_extra={"label": "秘境·陨落", "placeholder": "默认 0.05", "order": 85, "step": 0.01})

    # ==================== 概率边界与护盾 ====================
    rob_floor: Optional[float] = Field(
        default=None,
        description="抢夺/打劫的胜率下限，再劣势也不会低于它。默认 0.1（10%%）。",
        json_schema_extra={"label": "胜率下限", "placeholder": "默认 0.1", "order": 60, "step": 0.01})
    rob_cap: Optional[float] = Field(
        default=None,
        description="抢夺/打劫的胜率上限，再优势也不会超过它。默认 0.9（90%%）。",
        json_schema_extra={"label": "胜率上限", "placeholder": "默认 0.9", "order": 61, "step": 0.01})
    affection_per_shield: Optional[int] = Field(
        default=None,
        description="每多少点夫妻好感抵消一档胜率（即防黄毛的护盾）。默认 20。",
        json_schema_extra={"label": "护盾档位", "placeholder": "默认 20", "order": 62, "step": 1})
    affection_shield_rate: Optional[float] = Field(
        default=None,
        description="每档护盾抵消多少胜率。默认 0.01，即每 20 点好感降低 1%% 被抢概率。",
        json_schema_extra={"label": "护盾效率", "placeholder": "默认 0.01", "order": 63, "step": 0.005})

    # ==================== 经济与惩罚 ====================
    initial_money: Optional[int] = Field(
        default=None,
        description="新玩家第一次参与时的初始金币。默认 1000。",
        json_schema_extra={"label": "初始金币", "placeholder": "默认 1000", "order": 70, "step": 100})
    cycle_allowance: Optional[int] = Field(
        default=None,
        description="每个周期首次互动时自动发放的低保。默认 200。",
        json_schema_extra={"label": "周期低保", "placeholder": "默认 200", "order": 71, "step": 50})
    fail_autism_seconds: Optional[int] = Field(
        default=None,
        description=(
            "犯罪失败后的强制自闭时长（秒），期间该指令不可再用。\n"
            "默认 60，与「普通指令冷却」叠加生效。"
        ),
        json_schema_extra={"label": "失败自闭秒数", "placeholder": "默认 60", "order": 72, "step": 10})
    max_penalty_seconds: Optional[int] = Field(
        default=None,
        description="自闭时长的硬上限（秒），防止配置失误把人永久锁死。默认 60。",
        json_schema_extra={"label": "自闭时长硬上限", "placeholder": "默认 60", "order": 73, "step": 10})


class PartnerGameConfig(PluginConfigBase):
    plugin: PluginSection = Field(default_factory=PluginSection)
    partner_game: PartnerGameSection = Field(default_factory=PartnerGameSection)
    balance: BalanceSection = Field(default_factory=BalanceSection)
