"""今日老婆插件配置模型。"""
from __future__ import annotations
from typing import ClassVar, List, Dict, Optional

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
    """数值平衡覆盖层。

    **留空 = 使用 `balance.py` 里的默认值**（界面上会显示默认值提示）。
    填了就覆盖默认值，立即生效（热重载即可，不需要改代码/重新部署）。

    这一层存在的意义：`balance.py` 是"出厂默认值 + 文档生成器的数据源"，
    而这里让部署者能在 WebUI 里现场微调，不用碰代码。
    """

    __ui_label__: ClassVar[str] = "数值平衡（留空=用默认值）"
    __ui_order__: ClassVar[int] = 2

    # ---------------- 周期 ----------------
    cycle_hours: Optional[int] = Field(
        default=None,
        description="一个游戏周期的小时数（默认 24）。改成 12 就是半天一轮，168 就是一周一轮。",
        json_schema_extra={"label": "周期时长（小时）", "placeholder": "默认 24", "order": 0, "step": 1},
    )

    # ---------------- 每周期次数 ----------------
    draw_limit: Optional[int] = Field(
        default=None, description="每周期可用的 /今日老婆 次数（默认 1）",
        json_schema_extra={"label": "抽老婆次数", "placeholder": "默认 1", "order": 10, "step": 1})
    divorce_limit: Optional[int] = Field(
        default=None, description="每周期可用的 /离婚 次数（默认 1）",
        json_schema_extra={"label": "离婚次数", "placeholder": "默认 1", "order": 11, "step": 1})
    dump_limit: Optional[int] = Field(
        default=None, description="每周期可用的 /甩掉 次数（默认 1）",
        json_schema_extra={"label": "甩掉次数", "placeholder": "默认 1", "order": 12, "step": 1})
    work_limit: Optional[int] = Field(
        default=None, description="每周期可用的 /打工 次数（默认 3）",
        json_schema_extra={"label": "打工次数", "placeholder": "默认 3", "order": 13, "step": 1})
    date_limit: Optional[int] = Field(
        default=None, description="每周期可用的 /约会 次数（默认 3）",
        json_schema_extra={"label": "约会次数", "placeholder": "默认 3", "order": 14, "step": 1})
    cultivate_limit: Optional[int] = Field(
        default=None, description="每周期可用的 /修炼 次数（默认 3）",
        json_schema_extra={"label": "修炼次数", "placeholder": "默认 3", "order": 15, "step": 1})
    rob_money_limit: Optional[int] = Field(
        default=None, description="每周期可用的 /打劫 次数（默认 3）",
        json_schema_extra={"label": "打劫次数", "placeholder": "默认 3", "order": 16, "step": 1})

    # ---------------- 门槛 ----------------
    force_gate: Optional[int] = Field(
        default=None, description="发起 /强娶 所需金币（默认 300）",
        json_schema_extra={"label": "强娶金币门槛", "placeholder": "默认 300", "order": 20, "step": 50})
    rob_wife_gate: Optional[int] = Field(
        default=None, description="发起 /抢老婆 所需金币（默认 500）",
        json_schema_extra={"label": "抢老婆金币门槛", "placeholder": "默认 500", "order": 21, "step": 50})
    rob_money_gate: Optional[int] = Field(
        default=None, description="发起 /打劫 所需金币（默认 300）",
        json_schema_extra={"label": "打劫金币门槛", "placeholder": "默认 300", "order": 22, "step": 50})
    rob_money_poor_protect: Optional[int] = Field(
        default=None, description="资产低于此值不可被打劫（默认 100）",
        json_schema_extra={"label": "打劫保护线", "placeholder": "默认 100", "order": 23, "step": 10})

    # ---------------- 罚款 ----------------
    force_fine_min: Optional[int] = Field(
        default=None, description="强娶失败罚款下限（默认 100）",
        json_schema_extra={"label": "强娶罚款下限", "placeholder": "默认 100", "order": 30, "step": 10})
    force_fine_max: Optional[int] = Field(
        default=None, description="强娶失败罚款上限（默认 300）",
        json_schema_extra={"label": "强娶罚款上限", "placeholder": "默认 300", "order": 31, "step": 10})
    rob_wife_fine_min: Optional[int] = Field(
        default=None, description="抢老婆失败罚款下限（默认 200）",
        json_schema_extra={"label": "抢老婆罚款下限", "placeholder": "默认 200", "order": 32, "step": 10})
    rob_wife_fine_max: Optional[int] = Field(
        default=None, description="抢老婆失败罚款上限（默认 500）",
        json_schema_extra={"label": "抢老婆罚款上限", "placeholder": "默认 500", "order": 33, "step": 10})
    rob_money_fine_min: Optional[int] = Field(
        default=None, description="打劫失败罚款下限（默认 100）",
        json_schema_extra={"label": "打劫罚款下限", "placeholder": "默认 100", "order": 34, "step": 10})
    rob_money_fine_max: Optional[int] = Field(
        default=None, description="打劫失败罚款上限（默认 300）",
        json_schema_extra={"label": "打劫罚款上限", "placeholder": "默认 300", "order": 35, "step": 10})

    # ---------------- 修炼 ----------------
    cultivate_cost_base: Optional[int] = Field(
        default=None, description="修炼费用系数：费用 = (大境界序号+1) × 本值（默认 50）",
        json_schema_extra={"label": "修炼费用系数", "placeholder": "默认 50", "order": 40, "step": 10})
    minor_success_rate: Optional[float] = Field(
        default=None, description="小境界突破成功率（默认 0.8）",
        json_schema_extra={"label": "小境界成功率", "placeholder": "默认 0.8", "order": 41, "step": 0.05})
    major_success_rate: Optional[float] = Field(
        default=None, description="大境界突破成功率（默认 0.4）",
        json_schema_extra={"label": "大境界成功率", "placeholder": "默认 0.4", "order": 42, "step": 0.05})
    major_fail_drop_rate: Optional[float] = Field(
        default=None, description="大境界失败后走火入魔掉级的概率（默认 0.3）",
        json_schema_extra={"label": "走火入魔概率", "placeholder": "默认 0.3", "order": 43, "step": 0.05})

    # ---------------- 打工 / 约会 ----------------
    work_earn_min: Optional[int] = Field(
        default=None, description="打工基础收入下限（默认 50）",
        json_schema_extra={"label": "打工收入下限", "placeholder": "默认 50", "order": 50, "step": 10})
    work_earn_max: Optional[int] = Field(
        default=None, description="打工基础收入上限（默认 100）",
        json_schema_extra={"label": "打工收入上限", "placeholder": "默认 100", "order": 51, "step": 10})
    work_level_bonus: Optional[int] = Field(
        default=None, description="每级境界带来的额外收入（默认 10）",
        json_schema_extra={"label": "打工等级加成", "placeholder": "默认 10", "order": 52, "step": 1})
    date_cost: Optional[int] = Field(
        default=None, description="每次约会消耗（默认 50）",
        json_schema_extra={"label": "约会消耗", "placeholder": "默认 50", "order": 53, "step": 10})
    date_aff_min: Optional[int] = Field(
        default=None, description="约会好感增加下限（默认 10）",
        json_schema_extra={"label": "约会好感下限", "placeholder": "默认 10", "order": 54, "step": 1})
    date_aff_max: Optional[int] = Field(
        default=None, description="约会好感增加上限（默认 20）",
        json_schema_extra={"label": "约会好感上限", "placeholder": "默认 20", "order": 55, "step": 1})

    # ---------------- 概率边界与护盾 ----------------
    rob_floor: Optional[float] = Field(
        default=None, description="抢夺/打劫胜率下限（默认 0.1）",
        json_schema_extra={"label": "胜率下限", "placeholder": "默认 0.1", "order": 60, "step": 0.01})
    rob_cap: Optional[float] = Field(
        default=None, description="抢夺/打劫胜率上限（默认 0.9）",
        json_schema_extra={"label": "胜率上限", "placeholder": "默认 0.9", "order": 61, "step": 0.01})
    affection_per_shield: Optional[int] = Field(
        default=None, description="每多少点好感抵消一档护盾（默认 20）",
        json_schema_extra={"label": "护盾档位", "placeholder": "默认 20", "order": 62, "step": 1})
    affection_shield_rate: Optional[float] = Field(
        default=None, description="每档护盾抵消的胜率（默认 0.01）",
        json_schema_extra={"label": "护盾效率", "placeholder": "默认 0.01", "order": 63, "step": 0.005})

    # ---------------- 经济与惩罚 ----------------
    initial_money: Optional[int] = Field(
        default=None, description="新用户初始金币（默认 1000）",
        json_schema_extra={"label": "初始金币", "placeholder": "默认 1000", "order": 70, "step": 100})
    cycle_allowance: Optional[int] = Field(
        default=None, description="每周期首个互动的低保（默认 200）",
        json_schema_extra={"label": "周期低保", "placeholder": "默认 200", "order": 71, "step": 50})
    fine_compensation_ratio: Optional[float] = Field(
        default=None, description="罚款中赔付给对手的比例（默认 0.5）",
        json_schema_extra={"label": "罚款赔付比例", "placeholder": "默认 0.5", "order": 72, "step": 0.05})
    fail_autism_seconds: Optional[int] = Field(
        default=None, description="犯罪失败后的自闭秒数（默认 60）",
        json_schema_extra={"label": "失败自闭秒数", "placeholder": "默认 60", "order": 73, "step": 10})


class PartnerGameConfig(PluginConfigBase):
    plugin: PluginSection = Field(default_factory=PluginSection)
    partner_game: PartnerGameSection = Field(default_factory=PartnerGameSection)
    balance: BalanceSection = Field(default_factory=BalanceSection)
