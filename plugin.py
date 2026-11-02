"""今日老婆插件主体。"""
from __future__ import annotations

import os
import re
import time
import random
from typing import Optional

from maibot_sdk import MaiBotPlugin, Command, CONFIG_RELOAD_SCOPE_SELF

from .config import PartnerGameConfig
from . import combat
from . import balance as B
from .realms import (
    MAX_LEVEL,
    REALMS,
    SUB_REALMS,
    cultivate_cost,
    is_major_boundary,
    is_max_level,
    rate_percent,
    realm_name,
)
from .utils import PersistStore, fetch_avatar_base64, format_user_display

#: balance 模块的出厂默认值快照。
#: WebUI 的「数值平衡」留空时，用它把被覆盖过的值还原回去 ——
#: 没有这份快照，改过一次就再也找不到原值了。
#: 数值平衡的各个配置分组（顺序无关，只用于遍历）
_BALANCE_SECTIONS = (
    "balance_cycle", "balance_economy", "balance_cultivation", "balance_marriage",
    "balance_force", "balance_rob_wife", "balance_rob_money", "balance_social",
    "balance_explore", "balance_loan", "balance_heaven", "balance_beast",
    "balance_bully", "balance_suppress",
)

_BALANCE_DEFAULTS = {
    name: getattr(B, name)
    for name in dir(B)
    if name.isupper() and isinstance(getattr(B, name), (int, float))
}


def parse_forced_rules(rules):
    """把 forced_wives 配置解析成 `{发起人QQ: 目标QQ}`。

    配置里每条是 `"发起人:目标"`，同时容忍中文冒号和等号，
    手滑写了个格式不对的条目就整条忽略（返回 False），不会抛异常。
    抽取（指定老婆）和犯罪（锁 0 胜率）都走这一份解析。
    """
    out = {}
    for rule in rules or []:
        parts = str(rule).replace("：", ":").replace("=", ":").split(":")
        if len(parts) == 2 and parts[0].strip() and parts[1].strip():
            out[parts[0].strip()] = parts[1].strip()
    return out

class PartnerGamePlugin(MaiBotPlugin):
    config_model = PartnerGameConfig

    # 生命周期
    async def on_load(self) -> None:
        data_dir = os.path.join(os.path.dirname(__file__), "data")
        os.makedirs(data_dir, exist_ok=True)
        self._store = PersistStore(os.path.join(data_dir, "partner_game_seen.json"))
        self._last_action: dict = {}
        self.pending_proposals: dict = {}
        self.pending_mating: dict = {}      # (群号, 被申请人QQ) → 交配申请
        self._member_cache: dict = {}       # 群号 → (时间戳, {QQ: 昵称})
        self._bot_qq_cache: Optional[str] = None
        try:
            self._apply_balance_overrides()   # WebUI 里改过的数值优先于 balance.py
        except Exception as e:
            self.ctx.logger.warning("应用数值平衡覆盖失败（将使用默认值）: %s" % e)
        self.ctx.logger.info("✅ partner_game 已加载")

    async def on_unload(self) -> None:
        store = getattr(self, "_store", None)
        if store is not None:
            if hasattr(store, "_save_task") and store._save_task and not store._save_task.done():
                store._save_task.cancel()
            if hasattr(store, "force_save"):
                await store.force_save()
            else:
                await store.save()

    async def on_config_update(self, scope: str, config_data: dict, version: str) -> None:
        if scope == CONFIG_RELOAD_SCOPE_SELF:
            self.ctx.logger.info(f"partner_game 配置已更新: {version}")
            # 配置 bot_qq 改了，清缓存让下次重新解析
            self._bot_qq_cache = None
            self._apply_balance_overrides()

    def _apply_balance_overrides(self) -> None:
        """把 WebUI「数值平衡」里的非空项写回 balance 模块。

        为什么不逐个改成 self.config 调用：数值散落在 47 处 B.XXX，
        改调用点既容易漏、又要改 47 次。把模块属性改掉，所有调用点自动生效。
        """
        # 数值分散在多个分组里：收集所有字段的当前值，统一写回 balance
        effective = {}
        for sec_name in _BALANCE_SECTIONS:
            section = getattr(self.config, sec_name, None)
            if section is None:
                continue
            for name in _BALANCE_DEFAULTS:
                if hasattr(section, name.lower()):
                    effective[name.lower()] = getattr(section, name.lower())

        changed = []
        for name, default in _BALANCE_DEFAULTS.items():
            target = effective.get(name.lower(), default)
            # 次数类允许填字符串：数字字符串转 int，"不限制" 原样保留
            if isinstance(target, str):
                text = target.strip()
                if text.isdigit():
                    target = int(text)
                elif text == "":
                    target = default
            if getattr(B, name) != target:
                setattr(B, name, target)
                changed.append("%s=%s" % (name, target))

        if changed:
            self.ctx.logger.info("数值平衡覆盖已生效: " + ", ".join(changed))

    # 上下文解析
    def _extract_ctx(self, kwargs: dict):
        """从命令回调 kwargs 中提取 group_id / sender_qq / sender_name。"""
        msg = kwargs.get("message", {})
        base_info = msg.get("message_base_info", {}) or kwargs.get("message_base_info", {}) or {}
        user_info = base_info.get("user_info", {}) or {}
        group_info = base_info.get("group_info", {}) or {}

        group_id = kwargs.get("group_id") or msg.get("group_id") or group_info.get("group_id")
        sender_qq = kwargs.get("user_id") or msg.get("user_id") or user_info.get("user_id")

        # raw_event 兜底
        raw_event = kwargs.get("raw_event") or msg.get("raw_event")
        if raw_event:
            if not group_id:
                if isinstance(raw_event, dict):
                    group_id = raw_event.get("group_id")
                else:
                    group_id = getattr(raw_event, "group_id", None)
            if not sender_qq:
                if isinstance(raw_event, dict):
                    sender_qq = raw_event.get("user_id")
                else:
                    sender_qq = getattr(raw_event, "user_id", None)

        sender_name = (
            user_info.get("user_cardname")
            or user_info.get("user_nickname")
            or ""
        )
        return (
            str(group_id) if group_id else None,
            str(sender_qq) if sender_qq else None,
            sender_name,
        )

    def _extract_at_qq(self, kwargs: dict) -> Optional[str]:
        """从消息里取出被 @ 的 QQ 号。

        为什么有 4 层兜底：不同适配器（NapCat / SnowLuma / 其它）给的结构不一样，
        有的把 @ 放在 `message.raw_message` 的段里，有的放在 `raw_event.message`，
        还有的只留一段 `[CQ:at,qq=...]` 文本。按"最可靠 → 最兜底"的顺序试，
        都拿不到才返回 None（调用方会提示用户「未识别到 @ 目标」）。

        代价：第 3/4 层是对整个 kwargs 做正则，极端情况下可能误判；
        所以它只在前两层失败后才执行，正常消息走不到那里。
        """
        # 1. Parse MaiBot's message['raw_message'] list
        msg_obj = kwargs.get("message")
        if isinstance(msg_obj, dict):
            raw_msg_list = msg_obj.get("raw_message")
            if isinstance(raw_msg_list, list):
                for seg in raw_msg_list:
                    if isinstance(seg, dict) and seg.get("type") == "at":
                        data = seg.get("data", {})
                        val = data.get("target_user_id") or data.get("qq") or data.get("target")
                        if val: return str(val)
        
        # 2. Try raw_event message chain (for other adapters)
        raw_event = kwargs.get("raw_event") or kwargs.get("message", {}).get("raw_event") or {}
        msg_chain = raw_event.get("message")
        if isinstance(msg_chain, list):
            for seg in msg_chain:
                if isinstance(seg, dict) and seg.get("type") == "at":
                    data = seg.get("data", {})
                    val = data.get("target_user_id") or data.get("qq") or data.get("target")
                    if val: return str(val)
        
        # 3. Super fallback: Regex on the entire kwargs string!
        import re
        kw_str = str(kwargs)
        m = re.search(r"\[CQ:at,qq=(\d+)\]", kw_str)
        if m: return m.group(1)
        m2 = re.search(r"['\"](?:target_user_id|qq|target)['\"]:\s*['\"]?(\d+)['\"]?", kw_str)
        if m2: return m2.group(1)
        
        # 4. Fallback: direct QQ number after command in any text
        m4 = re.search(r"(?:/娶|娶|/强娶|强娶|/甩掉|甩掉)\s*@?\s*(\d+)", kw_str)
        if m4:
            return m4.group(1)
            
        return None

    def _is_explicit_command(self, kwargs: dict) -> bool:
        msg_text = ""
        msg_obj = kwargs.get("message")
        if isinstance(msg_obj, dict):
            msg_text = str(msg_obj.get("processed_plain_text") or "")
            if not msg_text:
                raw_list = msg_obj.get("raw_message")
                if isinstance(raw_list, list):
                    msg_text = "".join([str(seg.get("data", {}).get("text", "")) for seg in raw_list if isinstance(seg, dict) and seg.get("type") == "text"])
        if not msg_text:
            msg_text = str(kwargs.get("raw_message", ""))
        return msg_text.strip().startswith("/")

    def _has_quote(self, kwargs: dict) -> bool:
        """检查消息是否包含引用（回复），如果是则返回 True"""
        msg_obj = kwargs.get("message")
        if isinstance(msg_obj, dict):
            raw_msg_list = msg_obj.get("raw_message")
            if isinstance(raw_msg_list, list):
                for seg in raw_msg_list:
                    if isinstance(seg, dict) and seg.get("type") == "reply":
                        return True
                        
        raw_event = kwargs.get("raw_event") or kwargs.get("message", {}).get("raw_event") or {}
        msg_chain = raw_event.get("message")
        if isinstance(msg_chain, list):
            for seg in msg_chain:
                if isinstance(seg, dict) and seg.get("type") == "reply":
                    return True
                    
        return False

    def _is_forced_user(self, sender_qq: str) -> bool:
        """是否命中 forced_wives 黑幕名单（命中后所有犯罪胜率锁 0）。"""
        return str(sender_qq) in parse_forced_rules(self.config.partner_game.forced_wives)

    async def _resolve_bot_qq(self) -> Optional[str]:
        if self._bot_qq_cache:
            return self._bot_qq_cache
        cfg_qq = (self.config.partner_game.bot_qq or "").strip()
        if cfg_qq:
            self._bot_qq_cache = cfg_qq
            return cfg_qq
        try:
            info = await self.ctx.api.call("adapter.napcat.system.get_login_info")
            if isinstance(info, dict):
                uid = info.get("user_id") or (info.get("data") or {}).get("user_id")
                if uid:
                    self._bot_qq_cache = str(uid)
                    return self._bot_qq_cache
        except Exception as e:
            self.ctx.logger.warning(f"无法自动获取机器人 QQ: {e}")
        return None

    # 通过适配器 API 直接发送，绕过 VLM 识图
    async def _send_napcat(self, group_id: int, message_chain: list) -> Optional[str]:
        try:
            res = await self.ctx.api.call(
                "adapter.napcat.message.send_msg",
                params={
                    "message_type": "group",
                    "group_id": int(group_id),
                    "message": message_chain,
                },
            )
            if isinstance(res, dict):
                data = res.get("data", res)
                msg_id = data.get("message_id")
                if msg_id:
                    return str(msg_id)
        except Exception as e:
            self.ctx.logger.error(f"napcat 发送失败: {e}")
        return None

    async def _send_text_at(self, group_id: str, sender_qq: str, text: str) -> Optional[str]:
        chain = []
        if sender_qq and sender_qq.isdigit():
            chain.append({"type": "at", "data": {"qq": str(sender_qq)}})
            chain.append({"type": "text", "data": {"text": " "}})
        chain.append({"type": "text", "data": {"text": text}})
        return await self._send_napcat(int(group_id), chain)

    async def _send_forward_msg(self, group_id: str, sender_qq: str, title: str, text: str) -> bool:
        """发送合并转发消息，减少刷屏"""
        bot_qq = await self._resolve_bot_qq() or "10000"
        messages = [{
            "type": "node",
            "data": {
                "name": title,
                "uin": str(bot_qq),
                "content": [{"type": "text", "data": {"text": text}}]
            }
        }]
        try:
            await self.ctx.api.call(
                "adapter.napcat.message.send_group_forward_msg",
                params={
                    "group_id": int(group_id),
                    "messages": messages
                }
            )
            return True
        except Exception as e:
            self.ctx.logger.warning(f"发送合并转发失败，降级为普通消息: {e}")
            await self._send_text_at(group_id, sender_qq, f"【{title}】\n{text}")
            return False

    async def _send_wife_message(
        self,
        group_id: str,
        sender_qq: str,
        wife_uid: str,
        wife_nick: str,
        wife_card: str,
        prefix: str,
        suffix: str = "",
    ) -> Optional[str]:
        display = format_user_display(wife_uid, wife_nick, wife_card)
        text = f"{prefix}【{display}】～❤"
        if suffix:
            text += f" {suffix}"

        chain: list = []
        if sender_qq and sender_qq.isdigit():
            chain.append({"type": "at", "data": {"qq": str(sender_qq)}})
            chain.append({"type": "text", "data": {"text": " "}})
        chain.append({"type": "text", "data": {"text": text}})

        if self.config.partner_game.send_avatar:
            size = int(self.config.partner_game.avatar_size or 640)
            b64 = await fetch_avatar_base64(wife_uid, size=size)
            if b64:
                chain.append({"type": "text", "data": {"text": "\n"}})
                chain.append({"type": "image", "data": {"file": f"base64://{b64}"}})

        return await self._send_napcat(int(group_id), chain)


    async def _member_map(self, group_id: str) -> dict:
        """取「QQ → 昵称」映射，带 TTL 缓存。

        之前每个昵称查询都要拉一次整份群成员列表（榜单一条指令就是 10 次网络请求），
        这是插件"跑得慢"的主要原因。现在一个群一分钟内只拉一次。
        """
        key = str(group_id)
        ttl = max(0, int(B.MEMBER_CACHE_SECONDS))
        now = time.time()
        cached = self._member_cache.get(key)
        if cached and ttl and now - cached[0] < ttl:
            return cached[1]

        mapping = {}
        try:
            gid = int(group_id) if str(group_id).isdigit() else group_id
            members = await self.ctx.api.call(
                "adapter.napcat.group.get_group_member_list",
                group_id=gid, no_cache=True)
            if isinstance(members, list):
                for mem in members:
                    uid = str(mem.get("user_id", ""))
                    if uid:
                        mapping[uid] = mem.get("card") or mem.get("nickname") or uid
        except Exception:
            pass

        if mapping:                     # 拉取失败时不要把空表写进缓存
            self._member_cache[key] = (now, mapping)
        return mapping

    async def _get_member_nick(self, group_id: str, qq: str) -> str:
        if not qq:
            return "未知"
        mapping = await self._member_map(group_id)
        return mapping.get(str(qq), str(qq))

    async def _send_avatar_msg(self, group_id: str, text: str, qq_to_at: str, qq_for_avatar: str) -> Optional[str]:
        chain = []
        if qq_to_at:
            chain.append({"type": "at", "data": {"qq": str(qq_to_at)}})
            chain.append({"type": "text", "data": {"text": " "}})
        chain.append({"type": "text", "data": {"text": text}})
        if self.config.partner_game.send_avatar and qq_for_avatar:
            size = int(self.config.partner_game.avatar_size or 640)
            from .utils import fetch_avatar_base64
            b64 = await fetch_avatar_base64(qq_for_avatar, size=size)
            if b64:
                chain.append({"type": "text", "data": {"text": "\n"}})
                chain.append({"type": "image", "data": {"file": f"base64://{b64}"}})
        return await self._send_napcat(int(group_id), chain)

    async def _get_partner_nick(self, group_id: str, marriage: dict) -> str:
        """解析伴侣昵称，解决老数据或妻子视角的神秘发起人问题。"""
        nick = marriage.get("partner_nick", "神秘发起人")
        if nick == "神秘发起人":
            nick = await self._get_member_nick(group_id, marriage["partner_uid"])
        return nick

    def _get_user_marriage(self, group_id: str, qq: str) -> dict | None:
        marriages = self._store.data.get("marriages", {})
        grp = marriages.get(group_id, {})
        # check if husband
        if qq in grp:
            return {
                "role": "husband", 
                "partner_uid": grp[qq].get("wife_uid"), 
                "partner_nick": grp[qq].get("wife_nick"),
                "affection": grp[qq].get("affection", 0)
            }
        # check if wife
        for h_qq, w_info in grp.items():
            if str(w_info.get("wife_uid")) == qq:
                return {
                    "role": "wife", 
                    "partner_uid": h_qq, 
                    "partner_nick": "神秘发起人",
                    "affection": w_info.get("affection", 0)
                }
        return None

    def _get_user_data(self, group_id: str, qq: str) -> dict:
        """取（必要时创建）用户记录，顺带发放跨周期低保。

        注意这是**带副作用**的 getter：首次访问会自动建号并发低保，
        所以"读一下数据"也会改钱。改造成纯查询时要一并改所有调用点。
        """
        users = self._store.data.setdefault("users", {})
        grp = users.setdefault(group_id, {})
        today = B.period_key(self.config.partner_game.tz_offset_hours)
        
        user = grp.setdefault(qq, {"money": B.INITIAL_MONEY, "level": 0, "last_allowance": today})
        # 兼容补全
        if "money" not in user:
            user["money"] = B.INITIAL_MONEY
        if "level" not in user:
            user["level"] = 0
            
        # 每日低保
        if user.get("last_allowance") != today:
            user["money"] += B.CYCLE_ALLOWANCE
            user["last_allowance"] = today
            
        return user

    def _save_user_data(self, group_id: str, qq: str, money: int = None, level: int = None):
        user = self._get_user_data(group_id, qq)
        if money is not None:
            user["money"] = money
        if level is not None:
            user["level"] = level
            
    def _check_daily_limit(self, group_id: str, qq: str, action: str, limit,
                           cycle_hours=None) -> bool:
        """检查本周期次数：未超限就直接 +1 并返回 True。

        注意它是"检查并占用"的合并操作 —— 返回 True 表示这次已经计数了。
        所以调用点必须先做完所有前置校验，否则会出现"命令失败了但次数被消耗"。

        limit 支持三种取值：
          - 正整数：每周期最多这么多次
          - 0：完全禁用
          - 字符串（如「不限制」）或负数：不限次，但仍然计入 daily_usage 供统计

        cycle_hours：该行动自己的周期时长。传 None 表示跟随全局 CYCLE_HOURS。
        每个 action 在 daily_usage 里存一个 "__<action>_period" 标记，
        周期一变就把该 action 的计数清零 —— 所以打劫和秘境可以有各自的重置节奏。
        """
        import asyncio
        today = B.period_key(self.config.partner_game.tz_offset_hours)
        if self._store.purge_old(today):
            # 跨日自动增加好感度
            marriages = self._store.data.setdefault("marriages", {})
            for g_id, g_m in marriages.items():
                for h_qq, m_info in g_m.items():
                    m_info["affection"] = m_info.get("affection", 0) + B.MARRIAGE_AFFECTION_PER_CYCLE
            if self.config.partner_game.persist_enabled:
                asyncio.create_task(self._store.save())

        usage = self._store.data.setdefault("daily_usage", {}).setdefault(group_id, {}).setdefault(qq, {})

        # 按该行动自己的周期判断是否需要清零
        hours = B.CYCLE_HOURS if cycle_hours is None else cycle_hours
        slot_key = B.period_key(self.config.partner_game.tz_offset_hours, hours)
        marker = action + "__period"
        if usage.get(marker) != slot_key:
            usage[action] = 0
            usage[marker] = slot_key

        # 「不限制」：字符串或负数都视为无限次（0 表示禁用，不能算无限）
        if isinstance(limit, str) or (isinstance(limit, int) and limit < 0):
            usage[action] = usage.get(action, 0) + 1     # 仍计数，/我的状态 能看到用了多少次
            return True

        # 某些操作如果是白名单则豁免
        if action in ["partner_game", "divorce", "dump"]:
            cfg = self.config.partner_game
            no_limit_users = [str(x) for x in (cfg.no_limit_users or [])]
            if str(qq) in no_limit_users:
                return True
                
        usage = self._store.data.setdefault("daily_usage", {})
        group_usage = usage.setdefault(group_id, {})
        user_usage = group_usage.setdefault(qq, {})
        count = user_usage.get(action, 0)
        
        if count >= limit:
            return False
            
        user_usage[action] = count + 1
        return True

    # 冷却
    def _cooldown_of(self, seconds=None) -> int:
        """取某条指令的冷却秒数。传 None 时回落到全局配置，便于老配置兼容。"""
        if seconds is not None:
            return max(0, int(seconds))
        return max(0, int(self.config.partner_game.cooldown_seconds or 0))

    def _check_cooldown(self, group_id: str, sender_qq: str, command: str,
                        seconds=None) -> tuple[bool, int]:
        """返回 (是否命中冷却, 剩余秒数)。

        每条指令传自己的冷却值（balance.COOLDOWN_*），实现"每个行动独立冷却"。
        """
        key = f"{group_id}_{sender_qq}_{command}"
        now = time.time()
        last_time = self._last_action.get(key, 0.0)
        cooldown = self._cooldown_of(seconds)
        remaining = int(cooldown - (now - last_time))
        if remaining > 0:
            return True, remaining
        self._last_action[key] = now
        return False, 0

    def _calc_steal_amount(self, victim_money: int) -> int:
        """算出一次成功打劫能抢走多少金币（允许把对方打成负债）。

        规则：
          1. 正常有存款：按比例抢，且不超过「现有金币 × 上限倍数」；
          2. 抢掠下限在封顶之后再兜底 —— 所以只剩 10 金币的人也会被抢走 50；
          3. 资产 ≤ 0 的人：只按负资产保护上限抢，避免被无限刷。
        """
        if victim_money <= 0:
            return B.ROB_MONEY_NEGATIVE_CAP

        ratio = random.uniform(B.ROB_MONEY_RATIO_MIN, B.ROB_MONEY_RATIO_MAX)
        amount = int(victim_money * ratio)
        cap = int(victim_money * B.ROB_MONEY_CAP_RATIO)
        amount = min(amount, cap)
        return max(B.ROB_MONEY_STEAL_MIN, amount)

    # ---------------- 封禁（霸凌 / 镇压）----------------
    def _guard(self, group_id: str, qq: str, action: str = ""):
        """统一的行动前置检查：返回 (是否拦下, 提示文案)。

        依次检查：
          1. 是否被霸凌/镇压封禁（/还贷 与 /重生 始终放行，避免死锁）
          2. 是否有逾期贷款（只放行 打工 / 下秘境 / 还贷）
        """
        if not group_id or not qq:      # 私聊/解析失败时不拦，交给后面的分支处理
            return False, ""
        user = self._get_user_data(group_id, qq)

        ban_until = float(user.get("banned_until", 0) or 0)
        if ban_until > time.time() and action not in ("repay", "rebirth"):
            left = int(ban_until - time.time())
            reason = user.get("ban_reason") or "被人压制"
            return True, ("你正被【%s】封禁，%d 秒内无法行动（剩 %d 秒）。"
                          % (reason, int(ban_until - time.time()) + 0, left))

        if self._loan_overdue(user) and action not in ("work", "realm_dive", "repay", "rebirth"):
            return True, "你身上还背着逾期的贷款，天道封禁了你的行动！先去【/还贷】吧。"
        return False, ""

    def _ban(self, group_id: str, qq: str, seconds: int, reason: str) -> int:
        """封禁某人的主动行动，返回封禁结束时间戳。"""
        user = self._get_user_data(group_id, qq)
        until = time.time() + max(0, int(seconds))
        user["banned_until"] = until
        user["ban_reason"] = reason
        return until

    # ---------------- 贷款 ----------------
    def _loan_of(self, user: dict):
        """取出未还清的贷款记录；没有则返回 None。"""
        loan = user.get("loan")
        return loan if isinstance(loan, dict) and loan.get("principal") else None

    def _loan_owed(self, user: dict) -> int:
        """需要偿还的总额（本金 × 还款倍数）。"""
        loan = self._loan_of(user)
        if not loan:
            return 0
        return int(loan["principal"] * B.LOAN_REPAY_MULTIPLIER)

    def _loan_overdue(self, user: dict) -> bool:
        """是否已经逾期（超过 grace 分钟未还）。"""
        loan = self._loan_of(user)
        if not loan:
            return False
        age = time.time() - float(loan.get("borrowed_at", 0))
        return age > B.LOAN_GRACE_MINUTES * 60

    def _loan_block(self, group_id: str, qq: str, action: str = "") -> bool:
        """逾期期间的限制：只允许打工 / 下秘境 / 还贷。

        返回 True 表示这次操作应当被拦下（调用方负责发提示）。
        """
        if action in ("work", "realm_dive", "repay"):
            return False
        user = self._get_user_data(group_id, qq)
        return self._loan_overdue(user)

    # ---------------- 消息解析 ----------------
    def _message_text(self, kwargs) -> str:
        """取出消息纯文本（兼容 processed_plain_text / raw_message 段 / 兜底字段）。"""
        msg = kwargs.get("message")
        if isinstance(msg, dict):
            text = str(msg.get("processed_plain_text") or "")
            if text:
                return text
            raw = msg.get("raw_message")
            if isinstance(raw, list):
                joined = "".join(
                    str(seg.get("data", {}).get("text", ""))
                    for seg in raw
                    if isinstance(seg, dict) and seg.get("type") == "text"
                )
                if joined:
                    return joined
        return str(kwargs.get("raw_message", ""))

    def _parse_amount(self, kwargs):
        """取消息里的最后一个整数，用作金额。取不到返回 None。"""
        nums = re.findall(r"-?\d+", self._message_text(kwargs))
        return int(nums[-1]) if nums else None

    # ---------------- 氪金 ----------------
    def _add_recharge(self, user: dict, amount: int) -> float:
        """把金币换成「下次行动加成」，返回累加后的总加成比例。

        换算：每 RECHARGE_COINS_PER_PERCENT 金币 = 1%，总加成不超过 RECHARGE_CAP。
        """
        gain = amount / float(B.RECHARGE_COINS_PER_PERCENT) / 100.0
        total = min(B.RECHARGE_CAP, float(user.get("recharge", 0) or 0) + gain)
        user["recharge"] = total
        return total

    def _take_recharge(self, user: dict) -> float:
        """取出并清空待用的氪金加成（一次性）。"""
        bonus = float(user.get("recharge", 0) or 0)
        if bonus:
            user.pop("recharge", None)
        return bonus

    # ---------------- 天妒 / 天罚计数器 ----------------
    def _bump_counter(self, group_id: str, qq: str, key: str) -> int:
        """给本周期计数器 +1 并返回新值（存于 daily_usage，跨周期自动清零）。"""
        usage = self._store.data.setdefault("daily_usage", {}).setdefault(group_id, {}).setdefault(qq, {})
        usage[key] = usage.get(key, 0) + 1
        return usage[key]

    def _flag(self, group_id: str, qq: str, key: str) -> bool:
        usage = self._store.data.setdefault("daily_usage", {}).setdefault(group_id, {}).setdefault(qq, {})
        return bool(usage.get(key))

    def _set_flag(self, group_id: str, qq: str, key: str) -> None:
        usage = self._store.data.setdefault("daily_usage", {}).setdefault(group_id, {}).setdefault(qq, {})
        usage[key] = True

    def _check_tian_du(self, group_id: str, qq: str, user: dict):
        """修炼成功后调用：本周期突破达到阈值则「天妒」，修为倒退若干大境界。

        返回提示文案，未触发返回 None。每周期仅一次。
        """
        threshold = B.TIAN_DU_SUCCESS_THRESHOLD
        if threshold <= 0 or self._flag(group_id, qq, "tian_du_fired"):
            return None
        count = self._bump_counter(group_id, qq, "cultivate_success")
        if count < threshold:
            return None
        # 达到门槛后再掷一次"是否真的降罚"，未命中则下次继续有机会
        if B.TIAN_DU_TRIGGER_PROB < 1.0 and random.random() >= B.TIAN_DU_TRIGGER_PROB:
            return None

        self._set_flag(group_id, qq, "tian_du_fired")
        before = user["level"]
        drop = int(B.TIAN_DU_DROP_REALMS) * 4
        user["level"] = max(0, before - drop)
        return ("\n\n⚡ 天妒降下！你今日连破 %d 境，天道不容，"
                "修为倒退 %d 个大境界（【%s】→【%s】）。" %
                (count, B.TIAN_DU_DROP_REALMS, realm_name(before), realm_name(user["level"])))

    def _check_tian_fa(self, group_id: str, qq: str, user: dict):
        """每次犯罪后调用：本周期犯罪次数超过阈值则「天罚」，扣现有金币。"""
        threshold = B.TIAN_FA_CRIME_THRESHOLD
        if threshold <= 0 or self._flag(group_id, qq, "tian_fa_fired"):
            return None
        count = self._bump_counter(group_id, qq, "crime_count")
        if count <= threshold:
            return None
        if B.TIAN_FA_TRIGGER_PROB < 1.0 and random.random() >= B.TIAN_FA_TRIGGER_PROB:
            return None

        self._set_flag(group_id, qq, "tian_fa_fired")
        before = user["money"]
        lost = int(max(0, before) * B.TIAN_FA_MONEY_RATIO)
        user["money"] = before - lost
        return ("\n\n⚡ 天罚降临！你今日作恶 %d 次，天道不容，"
                "扣除现有金币的 %d%%（-%d，余额 %d）。" %
                (count, int(B.TIAN_FA_MONEY_RATIO * 100), lost, user["money"]))

    def _rebirth(self, group_id: str, qq: str, why: str = ""):
        """重生：只保留 REBIRTH_KEEP_RATIO 比例的修为，其余全部重置。

        用于：主动 /重生、秘境陨落、打怪陨落。
        返回 (原等级, 重生后等级)，供文案使用。
        """
        user = self._get_user_data(group_id, qq)
        before_level = user["level"]
        kept_level = int(before_level * B.REBIRTH_KEEP_RATIO)

        user["level"] = kept_level
        user["money"] = B.INITIAL_MONEY
        user.pop("loan", None)
        user.pop("recharge", None)
        user.pop("last_allowance", None)

        # 解除婚姻关系（自己作为老公 / 老婆两种位置都要摘掉）
        marriages = self._store.data.setdefault("marriages", {}).setdefault(group_id, {})
        marriages.pop(qq, None)
        for h_qq, info in list(marriages.items()):
            if str(info.get("wife_uid")) == qq:
                marriages.pop(h_qq, None)

        # 清空本周期全部次数与冷却
        self._store.data.setdefault("daily_usage", {}).setdefault(group_id, {}).pop(qq, None)
        prefix = "%s_%s_" % (group_id, qq)
        for key in [k for k in self._last_action if k.startswith(prefix)]:
            self._last_action.pop(key, None)

        for pid, proposal in list(self.pending_proposals.items()):
            if str(proposal.get("target_qq")) == qq or str(proposal.get("sender_qq")) == qq:
                self.pending_proposals.pop(pid, None)
        for key in [k for k in self.pending_mating if str(k[1]) == qq]:
            self.pending_mating.pop(key, None)

        self.ctx.logger.info("重生: %s（%s）%s → %s" % (qq, why, before_level, kept_level))
        return before_level, kept_level

    def _apply_divorce_penalty(self, group_id: str, initiator: str, partner_qq: str) -> str:
        """离婚惩罚：发起方按比例把财富与修为分给对方（开关关闭时什么都不做）。

        返回要附加到提示消息里的文案。
        """
        if not B.DIVORCE_PENALTY_ENABLED:
            return ""

        a = self._get_user_data(group_id, initiator)
        b = self._get_user_data(group_id, partner_qq)
        money = int(max(0, a["money"]) * B.DIVORCE_PENALTY_MONEY_RATIO)
        levels = int(a["level"] * B.DIVORCE_PENALTY_LEVEL_RATIO)
        if money <= 0 and levels <= 0:
            return ""

        a["money"] -= money
        b["money"] += money
        a["level"] = max(0, a["level"] - levels)
        b["level"] = min(MAX_LEVEL, b["level"] + levels)
        return ("\n\n💔 离婚惩罚生效：你分给对方 %d 金币与 %d 级修为"
                "（对方现有 %d 金币、%s）。" % (money, levels, b["money"], realm_name(b["level"])))

    def _calc_fine(self, payer_money: int, floor: int, cap_ratio: float) -> int:
        """按「该行动专属」的罚款规则算金额。

        每种犯罪有自己的下限与上限比例（强娶/抢老婆/打劫互不影响）；
        上限 = 行动者现有金币 × 比例，所以默认最多把钱罚光。
        赔给对手的部分由 `_settle_fine` 按全局赔付比例拆分，其余蒸发。
        """
        floor = int(floor)
        cap = max(floor, int(max(0, payer_money) * cap_ratio))
        return random.randint(floor, cap)

    def _settle_fine(self, payer: dict, receiver: dict, fine: int) -> int:
        """罚款结算：从 payer 扣 fine，按比例赔给 receiver，返回赔偿额。

        剩下那部分直接蒸发 —— 这是本插件唯一的"货币回收池"。
        扣款不会让余额变负（下限 0），所以门槛检查要在调用前做。
        """
        comp = int(fine * B.FINE_COMPENSATION_RATIO)
        receiver["money"] += comp
        payer["money"] = max(0, payer["money"] - fine)
        return comp

    # /今日老婆
    @Command(
        "partner_game",
        description="随机抽取今日老婆",
        pattern=r"^\s*(?:/今日老婆|今日老婆|/抽老婆|抽老婆|/老婆|老婆)$"
    )
    async def handle_partner_game(self, stream_id: str = "", **kwargs):
        if not self.config.plugin.enabled:
            return False, "Plugin Disabled", 0

        group_id, sender_qq, _ = self._extract_ctx(kwargs)
        blocked, why = self._guard(group_id, sender_qq, "draw")
        if blocked:
            await self._send_avatar_msg(group_id, why, sender_qq, "")
            return True, "blocked", 2

        if not group_id or not sender_qq:
            await self.ctx.send.text("好像是私聊呢，去群聊里找你的老婆吧。", stream_id)
            return True, "好像是私聊呢，去群聊里找你的老婆吧。", 2

        is_cd, rem = self._check_cooldown(group_id, sender_qq, "partner_game", B.COOLDOWN_DRAW)
        if is_cd:
            await self._send_text_at(group_id, sender_qq, f"稍微休息一下再来吧~ (冷却中: {rem}秒)")
            return True, "cooldown", 2

        cfg = self.config.partner_game
        today = B.period_key(cfg.tz_offset_hours)

        # 首先不论是否白名单，强制校验不能开后宫
        marriage = self._get_user_marriage(group_id, sender_qq)
        if marriage:
            role = marriage["role"]
            partner_nick = await self._get_partner_nick(group_id, marriage)
            rel_str = "老婆" if role == "husband" else "老公"
            await self._send_text_at(group_id, sender_qq, f"你已经是【{partner_nick}】的伴侣啦，请好好陪陪你的{rel_str}吧！(可以使用 /约会 增加好感度)")
            return True, "already_wife", 2

        # 检查抽取限次
        if not self._check_daily_limit(group_id, sender_qq, "partner_game", B.DRAW_LIMIT):
            await self._send_text_at(group_id, sender_qq, "你今天已经抽取过伴侣了，请明天再来吧！")
            return True, "daily_limit", 2

        # 拉群成员
        try:
            members = await self.ctx.api.call(
                "adapter.napcat.group.get_group_member_list",
                group_id=int(group_id),
                no_cache=True,
            )
        except Exception as e:
            self.ctx.logger.error(f"获取群成员失败: {e}")
            await self._send_text_at(group_id, sender_qq, f"无法获取群成员列表：{e}")
            return True, "api_error", 2

        if not isinstance(members, list) or not members:
            await self._send_text_at(group_id, sender_qq, "群成员列表数据异常。")
            return True, "api_error", 2

        bot_qq = await self._resolve_bot_qq()
        exclude_bot = cfg.exclude_self

        # 筛选候选
        candidates = []
        for m in members:
            uid = str(m.get("user_id", ""))
            if not uid:
                continue
            if cfg.exclude_sender and uid == sender_qq:
                continue
            if exclude_bot and bot_qq and uid == str(bot_qq):
                continue
            if not self._get_user_marriage(group_id, uid):
                candidates.append(m)

        # 黑幕名单：命中的人抽老婆时直接指定对象，跳过随机
        forced_wife_uid = parse_forced_rules(cfg.forced_wives).get(str(sender_qq))
        
        if forced_wife_uid:
            wife_uid = str(forced_wife_uid)
            wife_card = ""
            wife_nick = "未知昵称"
            found_in_group = False
            # 尝试在群成员中找名字
            for m in members:
                if str(m.get("user_id", "")) == wife_uid:
                    wife_card = str(m.get("card") or "")
                    wife_nick = str(m.get("nickname") or "")
                    found_in_group = True
                    break
            
            # 如果不在群里，尝试通过API获取其QQ昵称
            if not found_in_group:
                try:
                    for api_name in ["adapter.napcat.account.get_stranger_info", "adapter.napcat.get_stranger_info"]:
                        info = await self.ctx.api.call(api_name, user_id=int(wife_uid))
                        self.ctx.logger.info(f"DEBUG: api={api_name} info={info}")
                        if isinstance(info, dict):
                            # 有的返回结构包了一层 data，有的是直接铺平的
                            data = info.get("data") or info
                            nick = data.get("nickname")
                            if nick:
                                wife_nick = str(nick)
                                break
                except Exception as e:
                    self.ctx.logger.error(f"DEBUG API exception: {e}")
        else:
            if not candidates:
                await self._send_text_at(
                    group_id, sender_qq, "群里好像没人了（或者只有你和我啦）..."
                )
                return True, "no_candidates", 2
            chosen = random.choice(candidates)
            wife_uid = str(chosen.get("user_id"))
            wife_card = str(chosen.get("card") or "")
            wife_nick = str(chosen.get("nickname") or "")

        is_bot = (bot_qq and str(wife_uid) == str(bot_qq))
        if is_bot:
            prefix = "你今天的群老婆是我哦~"
        else:
            prefix = "今天你的老婆是"

        await self._send_wife_message(
            group_id, sender_qq, wife_uid, wife_nick, wife_card,
            prefix=prefix,
        )

        marriages = self._store.data.setdefault("marriages", {})
        marriages.setdefault(group_id, {})[sender_qq] = {
            "date": today,
            "wife_uid": wife_uid,
            "wife_nick": wife_nick,
            "wife_card": wife_card,
            "affection": 0
        }
        if cfg.persist_enabled:
            await self._store.save()

        return True, f"wife picked: {wife_card or wife_nick}", 2

    # /离婚
    @Command(
        "partner_game_divorce",
        description="清空今日老婆记录，可重新抽取（每日限一次）",
        pattern=r"^\s*(?:/离婚|离婚)(?:\s+|\[CQ:at|@|\d|$).*"
    )
    async def handle_wife_draw(self, stream_id: str = "", **kwargs):
        if self._has_quote(kwargs):
            return False, "Quote ignored", 0
        if not self.config.plugin.enabled:
            return False, "Plugin Disabled", 0

        group_id, sender_qq, _ = self._extract_ctx(kwargs)
        blocked, why = self._guard(group_id, sender_qq, "divorce")
        if blocked:
            await self._send_avatar_msg(group_id, why, sender_qq, "")
            return True, "blocked", 2

        if not group_id or not sender_qq:
            await self.ctx.send.text("只能在群里离婚喔～", stream_id)
            return True, "只能在群里离婚喔～", 2

        is_cd, rem = self._check_cooldown(group_id, sender_qq, "divorce", B.COOLDOWN_DIVORCE)
        if is_cd:
            await self._send_text_at(group_id, sender_qq, f"技能冷却中，请等待 {rem} 秒后再试~")
            return True, "cooldown", 2

        cfg = self.config.partner_game
        today = B.period_key(cfg.tz_offset_hours)

        # 每日限一次
        if not self._check_daily_limit(group_id, sender_qq, "divorce", B.DIVORCE_LIMIT):
            await self._send_text_at(group_id, sender_qq, "每日仅限一次离婚哦，明天再来吧~")
            return True, "limit_reached", 2

        marriage = self._get_user_marriage(group_id, sender_qq)
        if not marriage:
            await self._send_text_at(group_id, sender_qq, "你今天还没有老婆呢，不需要离婚～")
            return True, "no_record", 2
            
        if marriage["role"] == "wife":
            await self._send_text_at(group_id, sender_qq, "你是被绑定方，解除关系请使用【/甩掉@对方】命令。")
            return True, "wrong_role", 2
            
        target_qq = marriage["partner_uid"]
        marriages = self._store.data.setdefault("marriages", {})
        grp = marriages.get(group_id, {})
        if sender_qq in grp:
            grp.pop(sender_qq, None)
            if cfg.persist_enabled:
                await self._store.save()
            target_nick = await self._get_member_nick(group_id, target_qq)
            penalty = self._apply_divorce_penalty(group_id, sender_qq, target_qq)
            if penalty:
                await self._store.save()
            await self._send_avatar_msg(
                group_id,
                f"你已成功和【{target_nick}({target_qq})】离婚，现在可以重新抽你的新老婆啦～{penalty}",
                sender_qq, target_qq)
            return True, "divorced", 2

    @Command("proposal_reply", pattern=r".*(?:我同意|我拒绝).*")
    async def handle_proposal_reply(self, stream_id: str = "", **kwargs):
        group_id, sender_qq, _ = self._extract_ctx(kwargs)
        if not group_id or not sender_qq:
            return False, "Not in group", 0

        # Find matching proposal for this user in this group
        reply_id = None
        for pid, proposal in list(self.pending_proposals.items()):
            if str(proposal.get("group_id")) == str(group_id) and str(proposal.get("target_qq")) == str(sender_qq):
                reply_id = pid
                break
                
        if not reply_id:
            return False, "No valid pending proposal", 0
            
        proposal = self.pending_proposals[reply_id]
            
        # Check timeout
        import time
        timeout = int(self.config.partner_game.proposal_timeout_seconds or 60)
        if time.time() - proposal["timestamp"] > timeout:
            del self.pending_proposals[reply_id]
            await self._send_avatar_msg(group_id, "求婚已经超时失效啦~", sender_qq, "")
            return True, "Timeout", 2
            
        # Extract actual user text
        plain_text = ""
        msg_obj = kwargs.get("message")
        if isinstance(msg_obj, dict):
            plain_text = str(msg_obj.get("processed_plain_text") or "")
            if not plain_text:
                raw_list = msg_obj.get("raw_message")
                if isinstance(raw_list, list):
                    plain_text = "".join([str(seg.get("data", {}).get("text", "")) for seg in raw_list if isinstance(seg, dict) and seg.get("type") == "text"])
        if not plain_text:
            plain_text = str(kwargs.get("raw_message", ""))
            
        idx_agree = plain_text.rfind("我同意")
        idx_reject = plain_text.rfind("我拒绝")
        
        if idx_reject > idx_agree:
            del self.pending_proposals[reply_id]
            target_nick = await self._get_member_nick(group_id, sender_qq)
            await self._send_avatar_msg(group_id, f"很遗憾，对方【{target_nick}({sender_qq})】拒绝了你的求婚...", proposal["sender_qq"], sender_qq)
            return True, "Rejected", 2
            
        if idx_agree > idx_reject:
            del self.pending_proposals[reply_id]
                
            cfg = self.config.partner_game
            today = B.period_key(cfg.tz_offset_hours)
            
            if self._get_user_marriage(group_id, proposal["sender_qq"]) or self._get_user_marriage(group_id, sender_qq):
                await self._send_avatar_msg(group_id, "发生变故，你们中有人已经有伴侣了！", sender_qq, "")
                return True, "Already married", 2

            marriages = self._store.data.setdefault("marriages", {})
            marriages.setdefault(group_id, {})[proposal["sender_qq"]] = {
                "date": today,
                "wife_uid": sender_qq,
                "wife_nick": proposal["target_nick"],
                "wife_card": "",
                "affection": 0
            }
            if cfg.persist_enabled:
                await self._store.save()
                
            await self._send_avatar_msg(group_id, "恭喜！对方同意了你的求婚，你们现在是伴侣啦~❤", proposal["sender_qq"], sender_qq)
            return True, "Accepted", 2

        return False, "No match", 0

    @Command("marry", pattern=r"^\s*(?:/娶|娶)(?:\s+|\[CQ:at|@|\d|$).*")
    async def handle_marry(self, stream_id: str = "", **kwargs):
        if self._has_quote(kwargs):
            return False, "Quote ignored", 0
        if not self.config.plugin.enabled:
            return False, "Plugin Disabled", 0
            
        group_id, sender_qq, sender_nick = self._extract_ctx(kwargs)
        blocked, why = self._guard(group_id, sender_qq, "marry")
        if blocked:
            await self._send_avatar_msg(group_id, why, sender_qq, "")
            return True, "blocked", 2

        if not group_id or not sender_qq:
            await self.ctx.send.text("请在群聊中使用该命令喔～", stream_id)
            return True, "Not in group", 2

        is_cd, rem = self._check_cooldown(group_id, sender_qq, "marry", B.COOLDOWN_MARRY)
        if is_cd:
            await self._send_avatar_msg(group_id, f"技能冷却中，请等待 {rem} 秒后再试~", sender_qq, "")
            return True, "cooldown", 2

        target_qq = self._extract_at_qq(kwargs)
        if not target_qq:
            if not self._is_explicit_command(kwargs):
                return False, "Not a command", 0
            self.ctx.logger.warning(f"marry command could not extract QQ. kwargs: {kwargs}")
            await self._send_avatar_msg(group_id, "未识别到有效的 @ 目标！请确保使用真实的 @ 功能，或者直接输入对方的 QQ 号。", sender_qq, "")
            return True, "No target error", 2
            
        if target_qq == sender_qq:
            await self._send_avatar_msg(group_id, "你不能娶自己哦~", sender_qq, "")
            return True, "Self marry", 2
            
        cfg = self.config.partner_game
        
        sender_marriage = self._get_user_marriage(group_id, sender_qq)
        if sender_marriage and str(sender_marriage.get("partner_uid")) == target_qq:
            await self._send_avatar_msg(group_id, "你们已经是伴侣了哦，不需要再重复绑定啦~", sender_qq, "")
            return True, "Already partners", 2
            
        if sender_marriage:
            await self._send_avatar_msg(group_id, "你今天已经有伴侣了，不能再娶别人啦！", sender_qq, "")
            return True, "Has wife", 2

        if self._get_user_marriage(group_id, target_qq):
            await self._send_avatar_msg(group_id, "对方今天已经名花有主啦！如果你非要硬来，可以尝试使用【/抢老婆 @对方】！", sender_qq, "")
            return True, "Target taken", 2
            
        # Get target info
        target_nick = await self._get_member_nick(group_id, target_qq)
        if not sender_nick:
            sender_nick = await self._get_member_nick(group_id, sender_qq)
            
        msg_text = f"【{sender_nick}({sender_qq})】向你发起了求婚~\n请回复本条消息并发送“我同意”或“我拒绝”。"
        
        # We manually build the chain to ensure it behaves exactly like a proposal
        chain = []
        chain.append({"type": "at", "data": {"qq": str(target_qq)}})
        chain.append({"type": "text", "data": {"text": "\n" + msg_text}})
        if self.config.partner_game.send_avatar:
            size = int(self.config.partner_game.avatar_size or 640)
            from .utils import fetch_avatar_base64
            b64 = await fetch_avatar_base64(sender_qq, size=size)
            if b64:
                chain.append({"type": "text", "data": {"text": "\n"}})
                chain.append({"type": "image", "data": {"file": f"base64://{b64}"}})

        msg_id = await self._send_napcat(int(group_id), chain)
        
        if msg_id:
            import time
            self.pending_proposals[msg_id] = {
                "group_id": group_id,
                "sender_qq": sender_qq,
                "target_qq": target_qq,
                "target_nick": target_nick,
                "timestamp": time.time()
            }
        
        return True, "Proposed", 2

    @Command("force_marry", pattern=r"^\s*(?:/强娶|强娶)(?:\s+|\[CQ:at|@|\d|$).*")
    async def handle_force_marry(self, stream_id: str = "", **kwargs):
        if self._has_quote(kwargs):
            return False, "Quote ignored", 0
        if not self.config.plugin.enabled:
            return False, "Plugin Disabled", 0
            
        group_id, sender_qq, sender_nick = self._extract_ctx(kwargs)
        blocked, why = self._guard(group_id, sender_qq, "force_marry")
        if blocked:
            await self._send_avatar_msg(group_id, why, sender_qq, "")
            return True, "blocked", 2

        if not group_id or not sender_qq:
            await self.ctx.send.text("请在群聊中使用该命令喔～", stream_id)
            return True, "Not in group", 2

        is_cd, rem = self._check_cooldown(group_id, sender_qq, "force_marry", B.COOLDOWN_FORCE)
        if is_cd:
            cd_cfg = int(self.config.partner_game.cooldown_seconds or 60)
            msg = "刚刚遭遇了挫折，还在自闭受罚中" if rem > cd_cfg else "强娶技能冷却中"
            await self._send_avatar_msg(group_id, f"{msg}，请等待 {rem} 秒后再试~", sender_qq, "")
            return True, "cooldown", 2

        import random, time
        target_qq = self._extract_at_qq(kwargs)
        if not target_qq:
            if not self._is_explicit_command(kwargs):
                return False, "Not a command", 0
            self.ctx.logger.warning(f"force_marry command could not extract QQ. kwargs: {kwargs}")
            await self._send_avatar_msg(group_id, "未识别到有效的 @ 目标！请确保使用真实的 @ 功能，或者直接输入对方的 QQ 号。", sender_qq, "")
            return True, "No target error", 2
            
        if target_qq == sender_qq:
            await self._send_avatar_msg(group_id, "你不能强娶自己哦~", sender_qq, "")
            return True, "Self marry", 2
            
        cfg = self.config.partner_game
        
        sender_marriage = self._get_user_marriage(group_id, sender_qq)
        if sender_marriage and str(sender_marriage.get("partner_uid")) == target_qq:
            await self._send_avatar_msg(group_id, "你们已经是伴侣了哦，不需要再重复绑定啦~", sender_qq, "")
            return True, "Already partners", 2
            
        if sender_marriage:
            await self._send_avatar_msg(group_id, "你今天已经有伴侣了，休想开后宫！", sender_qq, "")
            return True, "Has wife", 2

        if self._get_user_marriage(group_id, target_qq):
            await self._send_avatar_msg(group_id, "对方今天已经名花有主啦，强娶失败！想硬来的话，可以尝试使用【/抢老婆 @对方】！", sender_qq, "")
            return True, "Target taken", 2
            
        # 确保有足够的罚款金币
        sender_data = self._get_user_data(group_id, sender_qq)
        if sender_data["money"] < B.FORCE_GATE:
            await self._send_avatar_msg(group_id, "你的存款不足 300 金币，连治安罚款都交不起，还是先去【/打工】吧！", sender_qq, "")
            return True, "No money", 2
            
        prob = cfg.force_marry_probability
        is_forced = self._is_forced_user(sender_qq)
        
        if is_forced:
            prob = 0.0
            
        prob = max(B.FORCE_FLOOR, min(B.FORCE_CAP, prob))
        recharge = self._take_recharge(sender_data)      # 氪金加成（用于失败免罚判断）
        prob = min(B.RECHARGE_CAP, prob + recharge)

        if random.random() < prob:
            target_nick = await self._get_member_nick(group_id, target_qq)
            today = B.period_key(cfg.tz_offset_hours)
            marriages = self._store.data.setdefault("marriages", {})
            marriages.setdefault(group_id, {})[sender_qq] = {
                "date": today,
                "wife_uid": target_qq,
                "wife_nick": target_nick,
                "wife_card": "",
                "affection": 0
            }
            if cfg.persist_enabled:
                await self._store.save()
            
            if not sender_nick:
                sender_nick = await self._get_member_nick(group_id, sender_qq)
            await self._send_avatar_msg(group_id, f"霸道强娶成功！恭喜【{sender_nick}({sender_qq})】凭实力得到了【{target_nick}({target_qq})】！", sender_qq, target_qq)
        else:
            fine = 0 if recharge > 0 else self._calc_fine(sender_data["money"], B.FORCE_FINE_FLOOR, B.FORCE_FINE_CAP_RATIO)
            target_data = self._get_user_data(group_id, target_qq)
            comp = self._settle_fine(sender_data, target_data, fine)
            
            if cfg.persist_enabled:
                await self._store.save()
                
            await self._send_avatar_msg(group_id, f"强娶失败！你强扭瓜的行为有违风纪，被治安处当场制服并罚款 {fine} 金币，冷却结束后才能再次行动！\n（其中 {comp} 金币已作为精神损失费赔偿给对方）", sender_qq, target_qq)
            
        tian_fa = self._check_tian_fa(group_id, sender_qq, sender_data)
        if tian_fa:
            await self._send_avatar_msg(group_id, tian_fa, sender_qq, "")
        return True, "Force Marry Done", 2

    @Command("my_partner", pattern=r"^\s*(?:/我的伴侣|我的伴侣)(?:\s+|\[CQ:at|@|\d|$).*")
    async def handle_my_partner(self, stream_id: str = "", **kwargs):
        if self._has_quote(kwargs):
            return False, "Quote ignored", 0
        if not self.config.plugin.enabled:
            return False, "Plugin Disabled", 0

        group_id, sender_qq, _ = self._extract_ctx(kwargs)
        if not group_id or not sender_qq:
            await self.ctx.send.text("请在群聊中使用该命令喔～", stream_id)
            return True, "Not in group", 2

        is_cd, rem = self._check_cooldown(group_id, sender_qq, "my_partner", B.COOLDOWN_MY_PARTNER)
        if is_cd:
            await self._send_avatar_msg(group_id, f"技能冷却中，请等待 {rem} 秒后再试~", sender_qq, "")
            return True, "cooldown", 2

        target_qq = self._extract_at_qq(kwargs)
        query_qq = target_qq if target_qq else sender_qq

        marriage = self._get_user_marriage(group_id, query_qq)
        
        if query_qq == sender_qq:
            if not marriage:
                await self._send_avatar_msg(group_id, "你目前还是单身贵族哦~", sender_qq, "")
                return True, "Single", 2
                
            partner_uid = marriage["partner_uid"]
            partner_nick = await self._get_member_nick(group_id, partner_uid)
                
            if marriage["role"] == "husband":
                text = f"你当前的老婆是：【{partner_nick}({partner_uid})】"
            else:
                text = f"你当前属于：【{partner_nick}({partner_uid})】"
        else:
            target_nick = await self._get_member_nick(group_id, query_qq)
            if not marriage:
                await self._send_avatar_msg(group_id, f"【{target_nick}】目前还是单身贵族哦~", sender_qq, "")
                return True, "Single", 2
                
            partner_uid = marriage["partner_uid"]
            partner_nick = await self._get_member_nick(group_id, partner_uid)
                
            if marriage["role"] == "husband":
                text = f"【{target_nick}】当前的老婆是：【{partner_nick}({partner_uid})】"
            else:
                text = f"【{target_nick}】当前的老公是：【{partner_nick}({partner_uid})】"
                
        await self._send_avatar_msg(group_id, text, sender_qq, partner_uid if marriage else "")
        return True, "Has partner", 2

    @Command("dump_partner", pattern=r"^\s*(?:/甩掉|甩掉)(?:\s+|\[CQ:at|@|\d|$).*")
    async def handle_dump(self, stream_id: str = "", **kwargs):
        if self._has_quote(kwargs):
            return False, "Quote ignored", 0
        if not self.config.plugin.enabled:
            return False, "Plugin Disabled", 0
            
        group_id, sender_qq, _ = self._extract_ctx(kwargs)
        blocked, why = self._guard(group_id, sender_qq, "dump")
        if blocked:
            await self._send_avatar_msg(group_id, why, sender_qq, "")
            return True, "blocked", 2

        if not group_id or not sender_qq:
            await self.ctx.send.text("请在群聊中使用该命令喔～", stream_id)
            return True, "Not in group", 2

        is_cd, rem = self._check_cooldown(group_id, sender_qq, "dump_partner", B.COOLDOWN_DUMP)
        if is_cd:
            await self._send_avatar_msg(group_id, f"技能冷却中，请等待 {rem} 秒后再试~", sender_qq, "")
            return True, "cooldown", 2

        target_qq = self._extract_at_qq(kwargs)
        if not target_qq:
            if not self._is_explicit_command(kwargs):
                return False, "Not a command", 0
            self.ctx.logger.warning(f"dump_partner command could not extract QQ. kwargs: {kwargs}")
            await self._send_avatar_msg(group_id, "未识别到有效的 @ 目标！请确保使用真实的 @ 功能，或者直接输入对方的 QQ 号。", sender_qq, "")
            return True, "No target error", 2
        
        cfg = self.config.partner_game
        today = B.period_key(cfg.tz_offset_hours)
        
        if not self._check_daily_limit(group_id, sender_qq, "dump", B.DUMP_LIMIT):
            await self._send_avatar_msg(group_id, "每日仅限一次甩掉操作哦~", sender_qq, "")
            return True, "limit_reached", 2
                
        marriage = self._get_user_marriage(group_id, sender_qq)
        if not marriage:
            await self._send_avatar_msg(group_id, "你连伴侣都没有，甩掉空气吗？", sender_qq, "")
            return True, "Single", 2
            
        if marriage["role"] == "husband":
            await self._send_avatar_msg(group_id, "你是主动发起方，解除关系请使用【/离婚】命令。", sender_qq, "")
            return True, "Wrong role", 2
            
        if str(marriage["partner_uid"]) != str(target_qq):
            await self._send_avatar_msg(group_id, "TA不是你的伴侣哦！", sender_qq, "")
            return True, "Wrong target", 2
            
        # Execute dump
        marriages = self._store.data.get("marriages", {})
        if group_id in marriages and target_qq in marriages[group_id]:
            marriages[group_id].pop(target_qq, None)
            if cfg.persist_enabled:
                await self._store.save()
            target_nick = await self._get_member_nick(group_id, target_qq)
            # 甩掉 ≠ 主动离婚：双方都不受离婚惩罚
            await self._send_avatar_msg(
                group_id,
                f"你已成功甩掉了【{target_nick}({target_qq})】，现在恢复自由身了~",
                sender_qq, target_qq)
            
        return True, "Dumped", 2

    @Command("rob_wife", pattern=r"^\s*(?:/抢老婆|抢老婆)(?:\s+|\[CQ:at|@|\d|$).*")
    async def handle_rob_wife(self, stream_id: str = "", **kwargs):
        if self._has_quote(kwargs):
            return False, "Quote ignored", 0
        if not self.config.plugin.enabled:
            return False, "Plugin Disabled", 0
            
        group_id, sender_qq, sender_nick = self._extract_ctx(kwargs)
        blocked, why = self._guard(group_id, sender_qq, "rob_wife")
        if blocked:
            await self._send_avatar_msg(group_id, why, sender_qq, "")
            return True, "blocked", 2

        if not group_id or not sender_qq:
            await self.ctx.send.text("请在群聊中使用该命令喔～", stream_id)
            return True, "Not in group", 2

        is_cd, rem = self._check_cooldown(group_id, sender_qq, "rob_wife", B.COOLDOWN_ROB_WIFE)
        if is_cd:
            cd_cfg = int(self.config.partner_game.cooldown_seconds or 60)
            msg = "刚刚遭遇了挫折，还在自闭受罚中" if rem > cd_cfg else "抢夺技能冷却中"
            await self._send_avatar_msg(group_id, f"{msg}，请等待 {rem} 秒后再试~", sender_qq, "")
            return True, "cooldown", 2

        target_qq = self._extract_at_qq(kwargs)
        if not target_qq:
            if not self._is_explicit_command(kwargs):
                return False, "Not a command", 0
            await self._send_avatar_msg(group_id, "未识别到有效的 @ 目标！请确保使用了真实的 @ 或输入了QQ号。", sender_qq, "")
            return True, "No target error", 2
            
        if target_qq == sender_qq:
            await self._send_avatar_msg(group_id, "你连自己都不放过吗？无法抢自己的老婆！", sender_qq, "")
            return True, "Self rob", 2
            
        cfg = self.config.partner_game
        
        sender_marriage = self._get_user_marriage(group_id, sender_qq)
        if sender_marriage and str(sender_marriage.get("partner_uid")) == target_qq:
            await self._send_avatar_msg(group_id, "连自己的伴侣都不放过吗？你们早就在一起啦！", sender_qq, "")
            return True, "Rob own partner", 2
            
        if sender_marriage:
            await self._send_avatar_msg(group_id, "你已经有伴侣了，休想当黄毛！", sender_qq, "")
            return True, "Has wife", 2

        target_marriage = self._get_user_marriage(group_id, target_qq)
        if not target_marriage:
            await self._send_avatar_msg(group_id, "对方还是个单身狗，你抢个寂寞啊！", sender_qq, "")
            return True, "Target single", 2
            
        if target_marriage["role"] == "husband":
            husband_qq = target_qq
            wife_qq = str(target_marriage["partner_uid"])
            wife_nick = str(target_marriage["partner_nick"])
        else:
            wife_qq = target_qq
            husband_qq = str(target_marriage["partner_uid"])
            wife_nick = await self._get_member_nick(group_id, wife_qq)
            
        husband_nick = await self._get_member_nick(group_id, husband_qq)
            
        # 门槛：掏不起罚款就不许抢
        sender_data = self._get_user_data(group_id, sender_qq)
        if sender_data["money"] < B.ROB_WIFE_GATE:
            await self._send_avatar_msg(group_id, "你的存款不足 500 金币，连治安罚款都交不起，还是先去【/打工】吧！", sender_qq, "")
            return True, "No money", 2

        # 防守方战力取夫妻双方较高者 —— 老婆也可能是战力大佬
        husband_data = self._get_user_data(group_id, husband_qq)
        wife_data = self._get_user_data(group_id, wife_qq)
        defend_level = max(husband_data["level"], wife_data["level"])

        # 唯一一份胜率公式：结算与「/抢老婆胜率」共用
        is_forced = self._is_forced_user(sender_qq)
        recharge = self._take_recharge(sender_data)      # 氪金：用掉即清零
        battle = combat.resolve(
            combat.KIND_ROB_WIFE,
            attack_level=sender_data["level"],
            defend_level=defend_level,
            affection=target_marriage.get("affection", 0),
            base_prob=cfg.rob_wife_probability,
            forced=is_forced,
            bonus=recharge,
        )

        if random.random() < battle.final_prob:
            today = B.period_key(cfg.tz_offset_hours)
            marriages = self._store.data.setdefault("marriages", {})
            
            # 删除原老公的老婆记录
            if husband_qq in marriages.get(group_id, {}):
                wife_card = marriages[group_id][husband_qq].get("wife_card", "")
                del marriages[group_id][husband_qq]
            else:
                wife_card = ""
                
            # 挂载到抢夺者头上
            marriages.setdefault(group_id, {})[sender_qq] = {
                "date": today,
                "wife_uid": wife_qq,
                "wife_nick": wife_nick,
                "wife_card": wife_card,
                "affection": 0
            }
            if cfg.persist_enabled:
                await self._store.save()
            
            if not sender_nick:
                sender_nick = await self._get_member_nick(group_id, sender_qq)
            await self._send_avatar_msg(group_id, f"黄毛出现！【{sender_nick}({sender_qq})】拔剑而出，成功从【{husband_nick}({husband_qq})】手中抢走了TA的伴侣【{wife_nick}({wife_qq})】！", sender_qq, wife_qq)
        else:
            fine = 0 if recharge > 0 else self._calc_fine(sender_data["money"], B.ROB_WIFE_FINE_FLOOR, B.ROB_WIFE_FINE_CAP_RATIO)
            comp = self._settle_fine(sender_data, husband_data, fine)
            
            injury_msg = ""
            # Random chance to get injured if picking a fight and failing
            if recharge <= 0 and not is_forced and random.random() < B.ROB_WIFE_DROP_CHANCE and sender_data["level"] > 0:
                sender_data["level"] -= 1
                injury_msg = "\n并且你被反杀成重伤，境界跌落了1层！"
                
            if cfg.persist_enabled:
                await self._store.save()
                
            await self._send_avatar_msg(group_id, f"抢夺失败！你强扭瓜的行为有违风纪，被治安处当场制服并罚款 {fine} 金币，冷却结束后才能再次行动！{injury_msg}\n（其中 {comp} 金币已作为正当防卫奖励赔偿给原配老公）", sender_qq, husband_qq)
            
        tian_fa = self._check_tian_fa(group_id, sender_qq, sender_data)
        if tian_fa:
            await self._send_avatar_msg(group_id, tian_fa, sender_qq, "")
        return True, "Rob Wife Done", 2

    @Command("rob_chance", pattern=r"^\s*(?:/抢老婆胜率|/抢夺胜率|抢老婆胜率|抢夺胜率|/抢老婆概率|/抢夺概率|抢老婆概率|抢夺概率).*")
    async def handle_rob_chance(self, stream_id: str = "", **kwargs):
        if self._has_quote(kwargs):
            return False, "Quote ignored", 0
        if not self.config.plugin.enabled:
            return False, "Plugin Disabled", 0

        group_id, sender_qq, sender_nick = self._extract_ctx(kwargs)
        if not group_id or not sender_qq:
            await self.ctx.send.text("请在群聊中使用该命令喔～", stream_id)
            return True, "Not in group", 2

        target_qq = self._extract_at_qq(kwargs)
        if not target_qq:
            if not self._is_explicit_command(kwargs):
                return False, "Not a command", 0
            await self._send_avatar_msg(group_id, "未识别到有效的 @ 目标！请确保护指明了目标QQ，例如【/抢老婆胜率 @张三】。", sender_qq, "")
            return True, "No target error", 2
            
        if target_qq == sender_qq:
            await self._send_avatar_msg(group_id, "你无法抢自己老婆，因此胜率为0%！", sender_qq, "")
            return True, "Self rob", 2
            
        sender_marriage = self._get_user_marriage(group_id, sender_qq)
        if sender_marriage and str(sender_marriage.get("partner_uid")) == target_qq:
            await self._send_avatar_msg(group_id, "你们已经是伴侣了！不需要抢！", sender_qq, "")
            return True, "Rob own partner", 2

        target_marriage = self._get_user_marriage(group_id, target_qq)
        if not target_marriage:
            await self._send_avatar_msg(group_id, "对方目前还是单身狗，无法使用【抢老婆】机制，胜率无从计算（你可以试试【/强娶】）。", sender_qq, "")
            return True, "Target single", 2
            
        if target_marriage["role"] == "husband":
            husband_qq = target_qq
            wife_qq = str(target_marriage["partner_uid"])
        else:
            wife_qq = target_qq
            husband_qq = str(target_marriage["partner_uid"])
            
        husband_data = self._get_user_data(group_id, husband_qq)
        wife_data = self._get_user_data(group_id, wife_qq)
        sender_data = self._get_user_data(group_id, sender_qq)
        affection = target_marriage.get("affection", 0)
        
        cfg = self.config.partner_game
        base_prob = cfg.rob_wife_probability
        is_forced = self._is_forced_user(sender_qq)
        
        # 与结算走同一个公式；氪金加成单独列出，但查询不消耗它
        pending = float(sender_data.get("recharge", 0) or 0)
        battle = combat.resolve(
            combat.KIND_ROB_WIFE,
            attack_level=sender_data["level"],
            defend_level=max(husband_data["level"], wife_data["level"]),
            affection=affection,
            base_prob=base_prob,
            forced=is_forced,
        )
            
        battle = battle._replace(final_prob=min(B.RECHARGE_CAP, battle.final_prob + pending)) \
            if pending else battle
        target_nick = await self._get_member_nick(group_id, target_qq)

        msg = (
            f"📊 【抢夺胜率精算 - 目标：{target_nick}】 📊\n"
            f"1. 基础胜率：{round(base_prob * 100, 2)}%\n"
            f"2. 底蕴压制：{battle.power_percent:+.2f}%"
            f"（你战力 {battle.attack_power} vs 夫妻最高 {battle.defend_power}）\n"
            f"3. 恩爱护盾：-{battle.shield_percent:.2f}%（当前好感度 {affection} 点）\n"
            + ("4. 特殊机制：黑幕强制锁定！\n" if battle.forced
               else f"4. 综合结算保底：锁定在 {B.ROB_FLOOR:.0%} ~ {B.ROB_CAP:.0%} 之间\n")
            + "---\n"
            f"🔥 最终抢夺成功率：【{battle.percent}%】！"
        )

        await self._send_avatar_msg(group_id, msg, sender_qq, target_qq)
        return True, "Rob Chance Done", 2

    @Command("rob_money", pattern=r"^\s*(?:/打劫|打劫)(?:\s+|\[CQ:at|@|\d|$).*")
    async def handle_rob_money(self, stream_id: str = "", **kwargs):
        if self._has_quote(kwargs):
            return False, "Quote ignored", 0
        if not self.config.plugin.enabled:
            return False, "Plugin Disabled", 0

        group_id, sender_qq, sender_nick = self._extract_ctx(kwargs)
        blocked, why = self._guard(group_id, sender_qq, "rob_money")
        if blocked:
            await self._send_avatar_msg(group_id, why, sender_qq, "")
            return True, "blocked", 2

        if not group_id or not sender_qq:
            await self.ctx.send.text("请在群聊中使用该命令喔～", stream_id)
            return True, "Not in group", 2

        is_cd, rem = self._check_cooldown(group_id, sender_qq, "rob_money", B.COOLDOWN_ROB_MONEY)
        if is_cd:
            await self._send_avatar_msg(group_id, f"技能冷却中，请等待 {rem} 秒后再试~", sender_qq, "")
            return True, "cooldown", 2

        target_qq = self._extract_at_qq(kwargs)
        if not target_qq:
            if not self._is_explicit_command(kwargs):
                return False, "Not a command", 0
            await self._send_avatar_msg(group_id, "你想打劫谁？请 @ 目标！", sender_qq, "")
            return True, "No target error", 2
            
        if target_qq == sender_qq:
            await self._send_avatar_msg(group_id, "你不能打劫自己！", sender_qq, "")
            return True, "Self rob", 2
            
        sender_marriage = self._get_user_marriage(group_id, sender_qq)
        if sender_marriage and str(sender_marriage.get("partner_uid")) == target_qq:
            await self._send_avatar_msg(group_id, "连自己的伴侣都打劫，你还是人吗？", sender_qq, "")
            return True, "Rob own partner", 2
            
        sender_data = self._get_user_data(group_id, sender_qq)
        target_data = self._get_user_data(group_id, target_qq)
        
        # 确保有足够的罚款金币
        if sender_data["money"] < B.ROB_MONEY_GATE:
            await self._send_avatar_msg(group_id, "你的存款不足 300 金币，连治安罚款都交不起，还是先去【/打工】吧！", sender_qq, "")
            return True, "No money", 2

        # 每日限制 3 次
        cfg = self.config.partner_game
        no_limit_users = [str(x) for x in (cfg.no_limit_users or [])]
        if sender_qq not in no_limit_users:
            if not self._check_daily_limit(group_id, sender_qq, "rob_money", B.ROB_MONEY_LIMIT,
                               cycle_hours=B.ROB_MONEY_CYCLE_HOURS):
                await self._send_avatar_msg(group_id, "你今天已经打劫太多次了，官府正在通缉你，明天再来吧！", sender_qq, "")
                return True, "Daily limit", 2
            
        recharge = self._take_recharge(sender_data)
        battle = combat.resolve(
            combat.KIND_ROB_MONEY,
            attack_level=sender_data["level"],
            defend_level=target_data["level"],
            base_prob=cfg.rob_money_probability,
            forced=self._is_forced_user(sender_qq),
            bonus=recharge,
        )
        target_nick = await self._get_member_nick(group_id, target_qq)

        if random.random() < battle.final_prob:
            stolen = self._calc_steal_amount(target_data["money"])

            target_data["money"] -= stolen
            sender_data["money"] += stolen
            
            if cfg.persist_enabled:
                await self._store.save()
                
            await self._send_avatar_msg(group_id, f"打劫成功！【{sender_nick}({sender_qq})】凭借强大的战力威压，从【{target_nick}({target_qq})】身上强行搜刮了 {stolen} 金币！", sender_qq, target_qq)
        else:
            fine = 0 if recharge > 0 else self._calc_fine(sender_data["money"], B.ROB_MONEY_FINE_FLOOR, B.ROB_MONEY_FINE_CAP_RATIO)
            comp = self._settle_fine(sender_data, target_data, fine)
            
            if cfg.persist_enabled:
                await self._store.save()
                
            await self._send_avatar_msg(group_id, f"打劫失败！【{target_nick}({target_qq})】战力爆发奋起反抗，不仅将你击退，官府还对你罚款了 {fine} 金币，冷却结束后才能再次行动！\n（其中 {comp} 金币已作为正当防卫精神损失费赔偿给对方）", sender_qq, target_qq)
            
        tian_fa = self._check_tian_fa(group_id, sender_qq, sender_data)
        if tian_fa:
            await self._send_avatar_msg(group_id, tian_fa, sender_qq, "")
        return True, "Rob Money Done", 2

    @Command("rob_money_chance", pattern=r"^\s*(?:/打劫胜率|/打劫概率|打劫胜率|打劫概率).*")
    async def handle_rob_money_chance(self, stream_id: str = "", **kwargs):
        if self._has_quote(kwargs): return False, "Quote ignored", 0
        if not self.config.plugin.enabled: return False, "Plugin Disabled", 0

        group_id, sender_qq, sender_nick = self._extract_ctx(kwargs)
        if not group_id or not sender_qq: return True, "Not in group", 2

        target_qq = self._extract_at_qq(kwargs)
        if not target_qq:
            await self._send_avatar_msg(group_id, "未识别到有效的 @ 目标！", sender_qq, "")
            return True, "No target error", 2
            
        if target_qq == sender_qq:
            await self._send_avatar_msg(group_id, "你无法打劫自己，因此胜率为0%！", sender_qq, "")
            return True, "Self rob", 2
            
        sender_data = self._get_user_data(group_id, sender_qq)
        target_data = self._get_user_data(group_id, target_qq)
        
        cfg = self.config.partner_game
        base_prob = getattr(cfg, "rob_money_probability", 0.35)
        is_forced = self._is_forced_user(sender_qq)
        
        pending = float(sender_data.get("recharge", 0) or 0)
        battle = combat.resolve(
            combat.KIND_ROB_MONEY,
            attack_level=sender_data["level"],
            defend_level=target_data["level"],
            base_prob=base_prob,
            forced=is_forced,
        )
        if pending:
            battle = battle._replace(final_prob=min(B.RECHARGE_CAP, battle.final_prob + pending))
            
        target_nick = await self._get_member_nick(group_id, target_qq)

        msg = (
            f"📊 【打劫胜率精算 - 目标：{target_nick}】 📊\n"
            f"1. 基础胜率：{round(base_prob * 100, 2)}%\n"
            f"2. 底蕴压制：{battle.power_percent:+.2f}%"
            f"（你战力 {battle.attack_power} vs 对方战力 {battle.defend_power}）\n"
            + ("3. 特殊机制：黑幕强制锁定！\n" if battle.forced
               else f"3. 综合结算保底：锁定在 {B.ROB_FLOOR:.0%} ~ {B.ROB_CAP:.0%} 之间\n")
            + "---\n"
            f"🔥 最终打劫成功率：【{battle.percent}%】！"
        )

        await self._send_avatar_msg(group_id, msg, sender_qq, target_qq)
        return True, "Rob Money Chance Done", 2

    @Command("partner_game_help", pattern=r"^(?:/抽老婆帮助|/今日老婆帮助|/老婆帮助|抽老婆帮助)$", aliases=["/今日老婆帮助", "/抽老婆帮助"])
    async def handle_help(self, stream_id: str = "", **kwargs):
        if self._has_quote(kwargs):
            return False, "Quote ignored", 0
        if not self.config.plugin.enabled: return False, "Plugin Disabled", 0
        group_id, sender_qq, _ = self._extract_ctx(kwargs)
        if not group_id or not sender_qq: return False, "Not in group", 0

        prob_force = int(self.config.partner_game.force_marry_probability * 100)
        prob_rob = int(self.config.partner_game.rob_wife_probability * 100)
        date_cost_text = "免费" if B.DATE_COST <= 0 else "每次 %d 金币" % B.DATE_COST
        repay_text = "%g" % B.LOAN_REPAY_MULTIPLIER
        help_text = (
            "💖 今日老婆 Pro+ · 指令总览 💖\n"
            "经济 · 修仙 · 犯罪 · 天道 · 夫妻 · 榜单\n"
            "=========================\n"
            "【💞 互动】\n"
            f"1. /今日老婆 —— 随机抽一位伴侣（每周期 {B.DRAW_LIMIT} 次）\n"
            f"2. /娶 @某人 —— 求婚，对方 {self.config.partner_game.proposal_timeout_seconds} 秒内回「我同意」或「我拒绝」\n"
            "3. /我的伴侣 —— 查看当前伴侣与头像\n"
            f"4. /离婚 —— 主动解除关系（发起方，每周期 {B.DIVORCE_LIMIT} 次）\n"
            f"5. /甩掉 @某人 —— 甩掉老公（被绑定方，每周期 {B.DUMP_LIMIT} 次）\n"
            f"6. /约会 —— 见面提升好感（每周期 {B.DATE_LIMIT} 次，{date_cost_text}）\n"
            "\n"
            "【⚔️ 犯罪】\n"
            f"7. /强娶 @某人 —— 概率硬绑单身者，失败罚款（门槛 {B.FORCE_GATE}）\n"
            f"8. /抢老婆 @某人 —— 抢别人的伴侣，受战力差与好感护盾影响（门槛 {B.ROB_WIFE_GATE}）\n"
            f"9. /打劫 @某人 —— 抢金币，可把对方打成负债（每周期 {B.ROB_MONEY_LIMIT} 次，门槛 {B.ROB_MONEY_GATE}）\n"
            f"10. /霸凌 @某人 —— 需高 {B.BULLY_LEVEL_GAP} 级（2 个大境界）：抢钱并封禁对方 {B.BULLY_BAN_SECONDS} 秒\n"
            f"11. /镇压 @某人 —— 需高 {B.SUPPRESS_LEVEL_GAP} 级（4 个大境界）：封禁对方与伴侣，并打落修为\n"
            "12. /打劫胜率 @某人 ｜ /抢老婆胜率 @某人 —— 精算成功率，含氪金加成\n"
            "\n"
            "【💰 经济】\n"
            f"13. /打工 —— 赚金币，收益区间 {B.WORK_EARN_MIN} ~ 等级×{B.WORK_EARN_MAX_PER_LEVEL}（可为负 = 亏本）\n"
            f"14. /修炼 —— 花金币突破境界（每周期 {B.CULTIVATE_LIMIT} 次）\n"
            "15. /我的状态 —— 境界 / 金币 / 次数 / 债务 / 封禁\n"
            "16. /上交存款 <金额> —— 把金币交给伴侣\n"
            "17. /送钱 @某人 <金额> —— 直接转给任何人\n"
            f"18. /氪金<金额> —— 买下一次行动的成功率：每 {B.RECHARGE_COINS_PER_PERCENT} 金币 +1%，上限 {round(B.RECHARGE_CAP*100)}%\n"
            "     作用于下一次 /打劫、/强娶、/下秘境、/修炼；用了氪金的这次失败不罚款\n"
            "\n"
            "【🌌 天道】\n"
            f"19. /贷款 <金额> —— 借多少都行，{B.LOAN_GRACE_MINUTES} 分钟内要还 {repay_text} 倍，逾期封禁行动\n"
            "20. /还贷 —— 一次性结清，不支持分期\n"
            f"21. /下秘境 —— 金币 / 修为暴涨 {B.REALM_DIVE_SURGE_LEVELS} 级 / 倒退 {B.REALM_DIVE_FALL_LEVELS} 级 / 陨落（每周期 {B.REALM_DIVE_LIMIT} 次）\n"
            f"22. /打怪 —— 金币 / 修为 +{B.BEAST_GAIN_LEVELS} 级 / 修为 -{B.BEAST_LOSE_LEVELS} 级 / 陨落（每周期 {B.BEAST_LIMIT} 次）\n"
            f"23. /重生 —— 保留 {round(B.REBIRTH_KEEP_RATIO*100)}% 修为，其余全部重置（陨落时自动触发）\n"
            "\n"
            "【💕 夫妻】\n"
            f"24. /申请交配 —— 好感满 {B.MATING_AFFECTION_MIN} 后可申请，对方回复「同意」或「拒绝」\n"
            f"     每次成功 +{B.MATING_AFFECTION_GAIN} 好感（每周期 {B.MATING_LIMIT} 次）\n"
            "\n"
            "【🏆 榜单与查询】\n"
            "25. /战力榜   26. /财富榜   27. /好感榜\n"
            "28. /游戏机制 —— 查看当前全部数值与公式\n"
            "29. /抽老婆帮助 —— 本页\n"
            "\n"
            "【🛠 管理员】\n"
            "30. /重置 @某人 —— 只保留修为与金币，其余全部重置\n"
            "31. /全服补偿 <金额> —— 给本群所有玩家发钱\n"
            "32. /发钱 @某人 <金额> —— 定向加减金币（支持负数）\n"
            "=========================\n"
            f"🎯 基础成功率：强娶 {prob_force}% ｜ 抢夺 {prob_rob}%\n"
            f"⚔️ 底蕴战力 = 等级 × (大境界序号+1)；每 1 点战力差 = {rate_percent()} 胜率\n"
            f"🛡 好感护盾：每 {B.AFFECTION_PER_SHIELD} 点好感 −{round(B.AFFECTION_SHIELD_RATE*100)}%，"
            f"最多抵 {round(B.AFFECTION_SHIELD_MAX*100)}%\n"
            f"💸 失败罚款：下限 {B.FORCE_FINE_FLOOR} 起（各行动可分别配置），最多罚光现有金币；其中 "
            f"{round(B.FINE_COMPENSATION_RATIO*100)}% 赔给对手\n"
            f"⚡ 天妒：一周期修炼成功 {B.TIAN_DU_SUCCESS_THRESHOLD} 次 → 倒退 {B.TIAN_DU_DROP_REALMS} 个大境界\n"
            f"⚡ 天罚：一周期犯罪超过 {B.TIAN_FA_CRIME_THRESHOLD} 次 → 扣 {round(B.TIAN_FA_MONEY_RATIO*100)}% 金币\n"
            "🔒 贷款逾期或被霸凌/镇压封禁时，只能 /打工、/下秘境、/还贷、/重生"
        )
        await self._send_forward_msg(group_id, sender_qq, "伴侣系统操作指南", help_text)
        return True, "help", 2

    # ---------------- RPG 指令 ---------------- #

    @Command("work", pattern=r"^\s*(?:/打工|打工)$")
    async def handle_work(self, stream_id: str = "", **kwargs):
        if not self.config.plugin.enabled:
            return False, "Disabled", 0
            
        if self._has_quote(kwargs):
            return False, "Quote ignored", 0

        group_id, sender_qq, _ = self._extract_ctx(kwargs)
        blocked, why = self._guard(group_id, sender_qq, "work")
        if blocked:
            await self._send_avatar_msg(group_id, why, sender_qq, "")
            return True, "blocked", 2

        if not group_id or not sender_qq:
            return True, "Not in group", 2

        if not self._check_daily_limit(group_id, sender_qq, "work", B.WORK_LIMIT):
            await self._send_avatar_msg(group_id, "你今天打工太累了，身体吃不消啦，明天再来吧！", sender_qq, "")
            return True, "limit", 2

        import random
        user_data = self._get_user_data(group_id, sender_qq)
        level = user_data.get("level", 0)
        # 收益区间：下限可配（可为负 = 亏本），上限 = 等级 × 系数
        lower = int(B.WORK_EARN_MIN)
        upper = max(lower, int(level * B.WORK_EARN_MAX_PER_LEVEL))
        earn = random.randint(lower, upper)
        user_data["money"] += earn
        
        if self.config.partner_game.persist_enabled:
            await self._store.save()
            
        if earn >= 0:
            msg = f"打工成功！凭 Level {level} 的境界，你赚到 {earn} 金币，当前余额 {user_data['money']}。"
        else:
            msg = f"这趟活儿干亏了……倒贴 {-earn} 金币（境界 Level {level}），当前余额 {user_data['money']}。"
        await self._send_avatar_msg(group_id, msg, sender_qq, "")
        return True, "Work done", 2

    @Command("date", pattern=r"^\s*(?:/约会|约会)$")
    async def handle_date(self, stream_id: str = "", **kwargs):
        if not self.config.plugin.enabled:
            return False, "Disabled", 0
            
        if self._has_quote(kwargs):
            return False, "Quote ignored", 0

        group_id, sender_qq, _ = self._extract_ctx(kwargs)
        blocked, why = self._guard(group_id, sender_qq, "date")
        if blocked:
            await self._send_avatar_msg(group_id, why, sender_qq, "")
            return True, "blocked", 2

        if not group_id or not sender_qq:
            return True, "Not in group", 2

        marriage = self._get_user_marriage(group_id, sender_qq)
        if not marriage:
            await self._send_avatar_msg(group_id, "你连伴侣都没有，一个人约会多可怜啊！", sender_qq, "")
            return True, "Single", 2

        user_data = self._get_user_data(group_id, sender_qq)
        if B.DATE_COST > 0 and user_data["money"] < B.DATE_COST:
            await self._send_avatar_msg(group_id, "你的存款连 50 金币都没有，拿什么给伴侣买礼物？快去【/打工】吧！", sender_qq, "")
            return True, "No money", 2

        if not self._check_daily_limit(group_id, sender_qq, "date", B.DATE_LIMIT):
            await self._send_avatar_msg(group_id, "伴侣今天约会累了，不想再出去了，明天再来吧！", sender_qq, "")
            return True, "limit", 2

        user_data["money"] -= B.DATE_COST
        import random
        add_aff = random.randint(B.DATE_AFF_MIN, B.DATE_AFF_MAX)
        
        marriages = self._store.data.setdefault("marriages", {})
        grp_m = marriages.setdefault(group_id, {})
        # Find the actual record to update affection
        if marriage["role"] == "husband":
            rec = grp_m.get(sender_qq)
        else:
            rec = grp_m.get(marriage["partner_uid"])
            
        if rec:
            rec["affection"] = rec.get("affection", 0) + add_aff
            
        if self.config.partner_game.persist_enabled:
            await self._store.save()
            
        partner_nick = await self._get_partner_nick(group_id, marriage)
        total_aff = rec["affection"] if rec else add_aff
        cost_text = f"花费 {B.DATE_COST} 金币" if B.DATE_COST > 0 else "分文未花"
        await self._send_avatar_msg(
            group_id,
            f"你{cost_text}与【{partner_nick}】约会，感情升温了！\n好感度 +{add_aff}，当前总好感度：{total_aff}",
            sender_qq, "")
        return True, "Date done", 2

    @Command("cultivate", pattern=r"^\s*(?:/修炼|修炼)$")
    async def handle_cultivate(self, stream_id: str = "", **kwargs):
        if not self.config.plugin.enabled:
            return False, "Disabled", 0
            
        if self._has_quote(kwargs):
            return False, "Quote ignored", 0

        group_id, sender_qq, _ = self._extract_ctx(kwargs)
        blocked, why = self._guard(group_id, sender_qq, "cultivate")
        if blocked:
            await self._send_avatar_msg(group_id, why, sender_qq, "")
            return True, "blocked", 2

        if not group_id or not sender_qq:
            return True, "Not in group", 2
            
        user_data = self._get_user_data(group_id, sender_qq)
        level = user_data["level"]
        
        if is_max_level(level):
            await self._send_avatar_msg(group_id, f"你已达【{realm_name(MAX_LEVEL)}】，此界再无你可修炼之物！", sender_qq, "")
            return True, "Max level", 2
            
        cost = cultivate_cost(level)
        
        if user_data["money"] < cost:
            await self._send_avatar_msg(group_id, f"修炼需要购买丹药，当前境界单次修炼需消耗 {cost} 金币，你的存款不足！", sender_qq, "")
            return True, "No money", 2

        if not self._check_daily_limit(group_id, sender_qq, "cultivate", B.CULTIVATE_LIMIT):
            await self._send_avatar_msg(group_id, "你今天修炼过度，经脉胀痛，请明日再来！", sender_qq, "")
            return True, "limit", 2

        user_data["money"] -= cost
        
        is_major_breakthrough = is_major_boundary(level)
        import random

        recharge = self._take_recharge(user_data)     # 氪金加成（一次性）
        tian_du_msg = ""
        
        if is_major_breakthrough:
            # 40% success
            if random.random() < min(B.RECHARGE_CAP, B.MAJOR_SUCCESS_RATE + recharge):
                user_data["level"] += 1
                msg = f"突破成功！天降祥瑞，你成功迈入了【{realm_name(user_data['level'])}】！"
                tian_du_msg = self._check_tian_du(group_id, sender_qq, user_data) or ""
            else:
                # Failed, 30% chance drop
                if random.random() < B.MAJOR_FAIL_DROP_RATE and user_data["level"] > 0:
                    user_data["level"] -= 1
                    msg = "突破失败！你急于求成导致走火入魔，根基受损，境界跌落了 1 层！"
                else:
                    msg = "突破失败！瓶颈太过坚固，你气血翻涌，未能突破。"
        else:
            # 80% success
            if random.random() < min(B.RECHARGE_CAP, B.MINOR_SUCCESS_RATE + recharge):
                user_data["level"] += 1
                msg = f"修炼顺利！你稳扎稳打，达到了【{realm_name(user_data['level'])}】。"
                tian_du_msg = self._check_tian_du(group_id, sender_qq, user_data) or ""
            else:
                msg = "修炼未果。你今日心神不宁，灵气流失，只白白消耗了丹药。"
                
        if self.config.partner_game.persist_enabled:
            await self._store.save()
            
        await self._send_avatar_msg(group_id, f"消耗 {cost} 金币修炼。\n{msg}{tian_du_msg}", sender_qq, "")
        return True, "Cultivate done", 2

    @Command("status", pattern=r"^\s*(?:/我的状态|我的状态)$")
    async def handle_status(self, stream_id: str = "", **kwargs):
        if not self.config.plugin.enabled:
            return False, "Disabled", 0

        group_id, sender_qq, _ = self._extract_ctx(kwargs)
        if not group_id:
            return True, "Not in group", 2

        user_data = self._get_user_data(group_id, sender_qq)
        marriage = self._get_user_marriage(group_id, sender_qq)
        
        level = user_data["level"]
        current_realm = realm_name(level)
        
        msg = f"【个人状态板】\n境界：{current_realm}\n金币：{user_data['money']}\n"
        
        if marriage:
            rel = "老公" if marriage["role"] == "wife" else "老婆"
            aff = marriage.get("affection", 0)
            real_nick = await self._get_member_nick(group_id, marriage['partner_uid'])
            msg += f"伴侣：{real_nick} ({rel})\n"
            msg += f"好感：{aff} 点 (可抵消 {B.shield_steps(aff)}% 抢夺风险)\n"
        else:
            msg += "伴侣：单身贵族\n"
            
        loan = self._loan_of(user_data)
        if loan:
            owed = self._loan_owed(user_data)
            left = B.LOAN_GRACE_MINUTES * 60 - (time.time() - float(loan.get("borrowed_at", 0)))
            state = "已逾期（行动被封禁）" if left <= 0 else "剩余 %d 分钟" % int(left // 60)
            msg += f"\n天道债务：本金 {loan['principal']}，需还 {owed}（{state}）\n"

        ban_until = float(user_data.get("banned_until", 0) or 0)
        if ban_until > time.time():
            msg += "\n状态：被【%s】封禁中，剩余 %d 秒\n" % (
                user_data.get("ban_reason") or "压制", int(ban_until - time.time()))

        usage = self._store.data.get("daily_usage", {}).get(group_id, {}).get(sender_qq, {})
        msg += f"\n本周期已打工：{usage.get('work', 0)}/{B.WORK_LIMIT}\n"
        msg += f"本周期已修炼：{usage.get('cultivate', 0)}/{B.CULTIVATE_LIMIT}\n"
        msg += f"本周期已约会：{usage.get('date', 0)}/{B.DATE_LIMIT}\n"
        
        await self._send_avatar_msg(group_id, msg, sender_qq, sender_qq)
        return True, "Status done", 2

    @Command("transfer", pattern=r"^\s*(?:/上交存款|上交存款)\s+(\d+)$")
    async def handle_transfer(self, stream_id: str = "", **kwargs):
        if not self.config.plugin.enabled:
            return False, "Disabled", 0
            
        if self._has_quote(kwargs):
            return False, "Quote ignored", 0

        group_id, sender_qq, _ = self._extract_ctx(kwargs)
        blocked, why = self._guard(group_id, sender_qq, "transfer")
        if blocked:
            await self._send_avatar_msg(group_id, why, sender_qq, "")
            return True, "blocked", 2

        if not group_id or not sender_qq:
            return True, "Not in group", 2

        import re
        msg_text = str(kwargs.get("message", {}).get("processed_plain_text", ""))
        if not msg_text:
            msg_text = str(kwargs.get("raw_message", ""))
        
        match = re.match(r"^\s*(?:/上交存款|上交存款)\s+(\d+)$", msg_text)
        if not match:
            return True, "Invalid amount format", 2
            
        amount = int(match.group(1))
        if amount <= 0:
            await self._send_avatar_msg(group_id, "上交金额必须大于 0！", sender_qq, "")
            return True, "Invalid amount", 2

        marriage = self._get_user_marriage(group_id, sender_qq)
        if not marriage:
            await self._send_avatar_msg(group_id, "你都没有伴侣，想把钱上交给自己吗？", sender_qq, "")
            return True, "Single", 2

        user_data = self._get_user_data(group_id, sender_qq)
        if user_data["money"] < amount:
            await self._send_avatar_msg(group_id, f"你只有 {user_data['money']} 金币，不够上交 {amount} 金币哦！", sender_qq, "")
            return True, "No money", 2

        partner_uid = marriage["partner_uid"]
        partner_data = self._get_user_data(group_id, partner_uid)
        
        user_data["money"] -= amount
        partner_data["money"] += amount
        
        if self.config.partner_game.persist_enabled:
            await self._store.save()
            
        partner_nick = await self._get_partner_nick(group_id, marriage)
        await self._send_avatar_msg(group_id, f"转账成功！你向【{partner_nick}】上交了 {amount} 金币，对方一定感受到了你的深情厚谊~\n当前余额：{user_data['money']} 金币", sender_qq, partner_uid)
        return True, "Transfer done", 2

    @Command("rank_power", pattern=r"^\s*(?:/战力榜|战力榜)$")
    async def handle_rank_power(self, stream_id: str = "", **kwargs):
        if not self.config.plugin.enabled: return False, "Disabled", 0
        
        if self._has_quote(kwargs):
            return False, "Quote ignored", 0
            
        group_id, sender_qq, _ = self._extract_ctx(kwargs)
        if not group_id: return True, "Not in group", 2
        
        users = self._store.data.get("users", {}).get(group_id, {})
        if not users:
            await self._send_avatar_msg(group_id, "当前群聊暂无修仙者记录。", sender_qq, "")
            return True, "No data", 2
            
        sorted_users = sorted(users.items(), key=lambda x: x[1].get("level", 0), reverse=True)[:10]
        
        msg = "🏆 【修仙战力榜】 🏆\n"
        for i, (qq, data) in enumerate(sorted_users, 1):
            nick = await self._get_member_nick(group_id, qq)
            l = data.get("level", 0)
            r_name = realm_name(l)
            msg += f"{i}. {nick} ({r_name})\n"
            
        await self._send_avatar_msg(group_id, msg.strip(), sender_qq, "")
        return True, "Rank Power", 2

    @Command("rank_money", pattern=r"^\s*(?:/财富榜|财富榜)$")
    async def handle_rank_money(self, stream_id: str = "", **kwargs):
        if not self.config.plugin.enabled: return False, "Disabled", 0
        
        if self._has_quote(kwargs):
            return False, "Quote ignored", 0
            
        group_id, sender_qq, _ = self._extract_ctx(kwargs)
        if not group_id: return True, "Not in group", 2
        
        users = self._store.data.get("users", {}).get(group_id, {})
        if not users:
            await self._send_avatar_msg(group_id, "当前群聊暂无财富记录。", sender_qq, "")
            return True, "No data", 2
            
        sorted_users = sorted(users.items(), key=lambda x: x[1].get("money", 0), reverse=True)[:10]
        msg = "💰 【群聊财富榜】 💰\n"
        for i, (qq, data) in enumerate(sorted_users, 1):
            nick = await self._get_member_nick(group_id, qq)
            msg += f"{i}. {nick} ({data.get('money', 0)} 金币)\n"
            
        await self._send_avatar_msg(group_id, msg.strip(), sender_qq, "")
        return True, "Rank Money", 2

    @Command("rank_affection", pattern=r"^\s*(?:/好感榜|好感榜)$")
    async def handle_rank_affection(self, stream_id: str = "", **kwargs):
        if not self.config.plugin.enabled: return False, "Disabled", 0
        
        if self._has_quote(kwargs):
            return False, "Quote ignored", 0
            
        group_id, sender_qq, _ = self._extract_ctx(kwargs)
        if not group_id: return True, "Not in group", 2
        
        marriages = self._store.data.get("marriages", {}).get(group_id, {})
        if not marriages:
            await self._send_avatar_msg(group_id, "当前群聊暂无伴侣记录。", sender_qq, "")
            return True, "No data", 2
            
        # Each marriage is stored under the husband's qq.
        # We want to display both names.
        sorted_m = sorted(marriages.items(), key=lambda x: x[1].get("affection", 0), reverse=True)[:10]
        msg = "💕 【模范夫妻好感榜】 💕\n"
        for i, (h_qq, data) in enumerate(sorted_m, 1):
            w_qq = data.get("wife_uid")
            if not w_qq: continue
            h_nick = await self._get_member_nick(group_id, h_qq)
            w_nick = await self._get_member_nick(group_id, w_qq)
            aff = data.get("affection", 0)
            msg += f"{i}. {h_nick} & {w_nick} ({aff} 点)\n"
            
        if msg == "💕 【模范夫妻好感榜】 💕\n":
            msg += "暂无有效数据。"
            
        await self._send_avatar_msg(group_id, msg.strip(), sender_qq, "")
        return True, "Rank Affection", 2

    @Command("admin_reset", pattern=r"^\s*(?:/重置|重置).*")
    async def handle_admin_reset(self, stream_id: str = "", **kwargs):
        if not self.config.plugin.enabled: return False, "Disabled", 0
        if self._has_quote(kwargs):
            return False, "Quote ignored", 0
            
        group_id, sender_qq, _ = self._extract_ctx(kwargs)
        if not group_id or not sender_qq: return True, "Not in group", 2
        
        cfg = self.config.partner_game
        admin_users = [str(x) for x in (cfg.admin_users or [])]
        if str(sender_qq) not in admin_users:
            await self._send_avatar_msg(group_id, "你没有权限使用该指令！此操作仅限专属管理员使用。", sender_qq, "")
            return True, "No auth", 2
            
        target_qq = self._extract_at_qq(kwargs)
        if not target_qq:
            await self._send_avatar_msg(group_id, "请通过 @ 提及你想重置的用户！", sender_qq, "")
            return True, "No target", 2
            
        # ---- 只保留「修为」与「现有金币」，其余全部清空 ----
        marriages = self._store.data.setdefault("marriages", {})
        grp = marriages.get(group_id, {})

        # 1) 解除婚姻：本人作为老公的记录
        grp.pop(target_qq, None)
        # 2) 解除婚姻：本人作为老婆的记录（从别人名下摘掉）
        for h_qq, w_info in list(grp.items()):
            if str(w_info.get("wife_uid")) == target_qq:
                grp.pop(h_qq, None)

        # 3) 清空本周期所有行动次数（打工/修炼/约会/打劫/抽取/离婚/甩掉/交配/秘境）
        usage_map = self._store.data.setdefault("daily_usage", {}).setdefault(group_id, {})
        usage_map.pop(target_qq, None)

        # 4) 清掉该用户身上的临时状态：贷款、氪金加成
        user = self._get_user_data(group_id, target_qq)
        user.pop("loan", None)
        user.pop("recharge", None)

        # 5) 清掉该用户尚未处理的申请与冷却
        for pid, proposal in list(self.pending_proposals.items()):
            if str(proposal.get("target_qq")) == target_qq or str(proposal.get("sender_qq")) == target_qq:
                self.pending_proposals.pop(pid, None)
        for key in [k for k in self.pending_mating if str(k[1]) == target_qq]:
            self.pending_mating.pop(key, None)
        for key in [k for k in self._last_action if k.split("_")[1:2] == [target_qq]]:
            self._last_action.pop(key, None)

        if cfg.persist_enabled:
            await self._store.save()

        target_nick = await self._get_member_nick(group_id, target_qq)
        await self._send_avatar_msg(
            group_id,
            f"管理员操作成功！已重置【{target_nick}({target_qq})】：\n"
            f"解除伴侣关系、清空本周期全部行动次数、清除贷款与氪金加成。\n"
            f"仅保留：修为（{realm_name(user['level'])}）与现有金币（{user['money']}）。",
            sender_qq, target_qq)
        return True, "Admin reset done", 2

    @Command("admin_compensate", pattern=r"^\s*(?:/全服补偿|全服补偿)\s+(\d+)$")
    async def handle_admin_compensate(self, stream_id: str = "", **kwargs):
        if not self.config.plugin.enabled: return False, "Disabled", 0
        if self._has_quote(kwargs):
            return False, "Quote ignored", 0
            
        group_id, sender_qq, _ = self._extract_ctx(kwargs)
        if not group_id or not sender_qq: return True, "Not in group", 2
        
        cfg = self.config.partner_game
        admin_users = [str(x) for x in (cfg.admin_users or [])]
        if str(sender_qq) not in admin_users:
            await self._send_avatar_msg(group_id, "你没有权限使用该指令！此操作仅限专属管理员使用。", sender_qq, "")
            return True, "No auth", 2
            
        msg_text = str(kwargs.get("message", {}).get("processed_plain_text", kwargs.get("raw_message", "")))
        import re
        match = re.search(r"(?:/全服补偿|全服补偿)\s+(\d+)", msg_text)
        if not match:
            return True, "No amount", 2
            
        amount = int(match.group(1))
        
        users = self._store.data.get("users", {}).get(group_id, {})
        count = 0
        for uid, udata in users.items():
            udata["money"] = udata.get("money", 0) + amount
            count += 1
            
        if cfg.persist_enabled:
            await self._store.save()
            
        await self._send_avatar_msg(group_id, f"管理员操作成功！已为本群 {count} 位已知玩家发放补偿金 {amount} 金币！", sender_qq, "")
        return True, "Compensate done", 2

    @Command("admin_give_money", pattern=r"^\s*(?:/发钱|/扣钱|发钱|扣钱)\s+.*?(\-?\d+)$")
    async def handle_admin_give_money(self, stream_id: str = "", **kwargs):
        if not self.config.plugin.enabled: return False, "Disabled", 0
        if self._has_quote(kwargs):
            return False, "Quote ignored", 0
            
        group_id, sender_qq, _ = self._extract_ctx(kwargs)
        if not group_id or not sender_qq: return True, "Not in group", 2
        
        cfg = self.config.partner_game
        admin_users = [str(x) for x in (cfg.admin_users or [])]
        if str(sender_qq) not in admin_users:
            await self._send_avatar_msg(group_id, "你没有权限使用该指令！此操作仅限专属管理员使用。", sender_qq, "")
            return True, "No auth", 2
            
        target_qq = self._extract_at_qq(kwargs)
        if not target_qq:
            await self._send_avatar_msg(group_id, "请通过 @ 提及你想修改资金的用户！", sender_qq, "")
            return True, "No target", 2
            
        msg_text = str(kwargs.get("message", {}).get("processed_plain_text", kwargs.get("raw_message", "")))
        import re
        match = re.search(r"(?:/发钱|/扣钱|发钱|扣钱)\s+.*?(\-?\d+)", msg_text)
        if not match:
            return True, "No amount", 2
            
        amount = int(match.group(1))
        
        target_data = self._get_user_data(group_id, target_qq)
        target_data["money"] = max(0, target_data["money"] + amount)
        
        if cfg.persist_enabled:
            await self._store.save()
            
        target_nick = await self._get_member_nick(group_id, target_qq)
        action = "增加" if amount >= 0 else "扣除"
        await self._send_avatar_msg(group_id, f"管理员操作成功！已为【{target_nick}({target_qq})】{action}了 {abs(amount)} 金币！其当前余额为 {target_data['money']} 金币。", sender_qq, target_qq)
        return True, "Give money done", 2

    @Command("game_info", pattern=r"^\s*(?:/游戏机制|游戏机制)$")
    async def handle_game_info(self, stream_id: str = "", **kwargs):
        if not self.config.plugin.enabled: return False, "Disabled", 0
        if self._has_quote(kwargs):
            return False, "Quote ignored", 0
            
        group_id, sender_qq, _ = self._extract_ctx(kwargs)
        if not group_id: return True, "Not in group", 2
        
        prob_force = int(self.config.partner_game.force_marry_probability * 100)
        prob_rob = int(self.config.partner_game.rob_wife_probability * 100)
        
        info_text = (
            "📜 【伴侣大乱斗·核心机制说明】 📜\n"
            "---\n"
            "⚔️【修仙战力系统】\n"
            f"• 境界体系：{len(REALMS)} 个大境界 × 4 小境界（{'/'.join(SUB_REALMS)}），"
            f"共 {MAX_LEVEL + 1} 档，从 {REALMS[0]} 到 {REALMS[-1]}。\n"
            f"• 修炼消耗：每周期限 {B.CULTIVATE_LIMIT} 次，每次消耗 (当前大境界序号 + 1) × {B.CULTIVATE_COST_BASE} 金币。\n"
            f"• 修炼突破：小境界成功率 {B.MINOR_SUCCESS_RATE:.0%}（失败无惩罚）；大境界成功率 {B.MAJOR_SUCCESS_RATE:.0%}，"
            f"失败后有 {B.MAJOR_FAIL_DROP_RATE:.0%} 概率走火入魔掉落 1 级。\n"
            f"• 战斗掉级：进行【/抢老婆】失败时，若境界>0，有 {B.ROB_WIFE_DROP_CHANCE:.0%} 概率被反杀掉落 1 级。\n"
            "---\n"
            "💰【经济财富系统】\n"
            f"• 初始资金：{B.INITIAL_MONEY} 金币。每周期首次互动发放 {B.CYCLE_ALLOWANCE} 金币低保。\n"
            f"• 打工收入：基础 {B.WORK_EARN_MIN}~{B.WORK_EARN_MAX} 金币 + (当前等级 × {B.WORK_LEVEL_BONUS}) 金币加成，"
            f"每周期限 {B.WORK_LIMIT} 次。\n"
            f"• 约会消耗：每次 {B.DATE_COST} 金币，增加 {B.DATE_AFF_MIN}~{B.DATE_AFF_MAX} 点好感度，"
            f"每周期限 {B.DATE_LIMIT} 次。\n"
            "---\n"
            "😈【互动犯罪机制】\n"
            f"• 强娶：基础概率 {prob_force}%。资金门槛 {B.FORCE_GATE}，"
            f"失败罚款 {B.FORCE_FINE_MIN}~{B.FORCE_FINE_MAX} 金币（{B.FINE_COMPENSATION_RATIO:.0%} 赔给防守方）。\n"
            f"• 抢老婆：基础概率 {prob_rob}%。资金门槛 {B.ROB_WIFE_GATE}，"
            f"失败罚款 {B.ROB_WIFE_FINE_MIN}~{B.ROB_WIFE_FINE_MAX} 金币"
            f"（{B.FINE_COMPENSATION_RATIO:.0%} 赔给防守方原配），并有 {B.ROB_WIFE_DROP_CHANCE:.0%} 概率掉级。\n"
            f"• 打劫金币：基础概率 {getattr(self.config.partner_game, 'rob_money_probability', 0.35)*100}%。"
            f"资金门槛 {B.ROB_MONEY_GATE}，成功抢走目标 {B.ROB_MONEY_RATIO_MIN:.0%}~{B.ROB_MONEY_RATIO_MAX:.0%} 资产"
            f"（{B.ROB_MONEY_STEAL_MIN}~{B.ROB_MONEY_STEAL_CAP} 金币），每周期限 {B.ROB_MONEY_LIMIT} 次。"
            f"失败罚款 {B.ROB_MONEY_FINE_MIN}~{B.ROB_MONEY_FINE_MAX} 金币（{B.FINE_COMPENSATION_RATIO:.0%} 赔给防守方）。"
            f"资产低于 {B.ROB_MONEY_POOR_PROTECT} 的玩家受保护。\n"
            "• 犯罪概率浮动公式：\n"
            "  1. 战力压制：采用【底蕴战力=等级×(大境界数+1)】，(进攻方战力 - 防守方最高战力) × " + rate_percent() + "。\n"
            f"  2. 好感抵消（仅限抢老婆）：夫妻好感度每 {B.AFFECTION_PER_SHIELD} 点，"
            f"减免 {B.AFFECTION_SHIELD_RATE:.0%} 成功率。\n"
            f"  3. 绝对保底：所有加成计算后，成功率强制锁定在 {B.ROB_FLOOR:.0%} ~ {B.ROB_CAP:.0%} 之间。"
            f"（强娶不参与战力，区间 {B.FORCE_FLOOR:.0%} ~ {B.FORCE_CAP:.0%}）"
        )
        await self._send_forward_msg(group_id, sender_qq, "游戏机制详细说明", info_text)
        return True, "Game info", 2


    # ---------------- 贷款 / 还贷 ----------------
    @Command("loan", pattern=r"^\s*(?:/贷款|贷款)\s+\d+$")
    async def handle_loan(self, stream_id: str = "", **kwargs):
        """向天道贷款：金额自定、不设上限，但必须按倍数一次性还清。"""
        if not self.config.plugin.enabled:
            return False, "Disabled", 0
        group_id, sender_qq, _ = self._extract_ctx(kwargs)
        if not group_id or not sender_qq:
            return True, "Not in group", 2

        amount = self._parse_amount(kwargs)
        if not amount or amount <= 0:
            await self._send_avatar_msg(group_id, "贷款金额需要是正整数，例如【/贷款 800】。", sender_qq, "")
            return True, "Invalid amount", 2

        user = self._get_user_data(group_id, sender_qq)
        loan = self._loan_of(user)
        if loan:
            awaited = self._loan_owed(user)
            await self._send_avatar_msg(
                group_id,
                f"你还有一笔贷款没还清（本金 {loan['principal']}，需还 {awaited}），天道不批新的贷款。",
                sender_qq, "")
            return True, "Has loan", 2

        user["money"] += amount
        user["loan"] = {"principal": amount, "borrowed_at": time.time()}
        if self.config.partner_game.persist_enabled:
            await self._store.save()

        owed = int(amount * B.LOAN_REPAY_MULTIPLIER)
        await self._send_avatar_msg(
            group_id,
            f"天道垂怜，你借得 {amount} 金币，当前余额 {user['money']}。\n"
            f"须在 {B.LOAN_GRACE_MINUTES} 分钟内一次性偿还 {owed} 金币（{B.LOAN_REPAY_MULTIPLIER} 倍），"
            f"逾期将被封禁一切行动，只能打工、下秘境、还贷。",
            sender_qq, "")
        return True, "Loan granted", 2

    @Command("repay", pattern=r"^\s*(?:/还贷|还贷)$")
    async def handle_repay(self, stream_id: str = "", **kwargs):
        """全额还贷：不分期，一次还清。"""
        if not self.config.plugin.enabled:
            return False, "Disabled", 0
        group_id, sender_qq, _ = self._extract_ctx(kwargs)
        if not group_id or not sender_qq:
            return True, "Not in group", 2

        user = self._get_user_data(group_id, sender_qq)
        loan = self._loan_of(user)
        if not loan:
            await self._send_avatar_msg(group_id, "你并不欠天道什么。", sender_qq, "")
            return True, "No loan", 2

        owed = self._loan_owed(user)
        if user["money"] < owed:
            await self._send_avatar_msg(
                group_id,
                f"还贷需要一次性结清 {owed} 金币，你只有 {user['money']}，"
                f"还差 {owed - user['money']}。天道不接受分期。",
                sender_qq, "")
            return True, "Not enough", 2

        user["money"] -= owed
        user.pop("loan", None)
        if self.config.partner_game.persist_enabled:
            await self._store.save()

        await self._send_avatar_msg(
            group_id,
            f"你向天道结清了 {owed} 金币，债务两清，行动解封。当前余额 {user['money']}。",
            sender_qq, "")
        return True, "Repaid", 2

    # ---------------- 送钱 ----------------
    @Command("give_money", pattern=r"^\s*(?:/送钱|送钱)(?:\s+|\[CQ:at|@|\d|$).*")
    async def handle_give_money(self, stream_id: str = "", **kwargs):
        """/送钱 @某人 金额：点对点转账，不需要是伴侣关系。"""
        if not self.config.plugin.enabled:
            return False, "Disabled", 0
        if self._has_quote(kwargs):
            return False, "Quote ignored", 0

        group_id, sender_qq, _ = self._extract_ctx(kwargs)
        if not group_id or not sender_qq:
            return True, "Not in group", 2

        blocked, why = self._guard(group_id, sender_qq, "give_money")
        if blocked:
            await self._send_avatar_msg(group_id, why, sender_qq, "")
            return True, "blocked", 2


        is_cd, remaining = self._check_cooldown(group_id, sender_qq, "give_money", B.COOLDOWN_GIVE)
        if is_cd:
            await self._send_avatar_msg(group_id, f"技能冷却中，请等待 {remaining} 秒后再试~", sender_qq, "")
            return True, "cooldown", 2

        target_qq = self._extract_at_qq(kwargs)
        amount = self._parse_amount(kwargs)
        if not target_qq:
            await self._send_avatar_msg(group_id, "你想送给谁？请 @ 对方，例如【/送钱 @张三 100】。", sender_qq, "")
            return True, "No target", 2
        if target_qq == sender_qq:
            await self._send_avatar_msg(group_id, "给自己送钱并不能凭空生钱。", sender_qq, "")
            return True, "Self", 2
        if not amount or amount <= 0:
            await self._send_avatar_msg(group_id, "金额需要是正整数，例如【/送钱 @张三 100】。", sender_qq, "")
            return True, "Invalid amount", 2

        sender = self._get_user_data(group_id, sender_qq)
        if sender["money"] < amount:
            await self._send_avatar_msg(group_id, f"你只有 {sender['money']} 金币，送不出 {amount}。", sender_qq, "")
            return True, "Not enough", 2

        receiver = self._get_user_data(group_id, target_qq)
        sender["money"] -= amount
        receiver["money"] += amount
        if self.config.partner_game.persist_enabled:
            await self._store.save()

        nick = await self._get_member_nick(group_id, target_qq)
        await self._send_avatar_msg(
            group_id,
            f"你向【{nick}({target_qq})】赠送了 {amount} 金币，当前余额 {sender['money']}。",
            sender_qq, target_qq)
        return True, "Given", 2

    # ---------------- 下秘境 ----------------
    @Command("realm_dive", pattern=r"^\s*(?:/下秘境|下秘境)$")
    async def handle_realm_dive(self, stream_id: str = "", **kwargs):
        """下秘境：按概率产出金币 / 暴涨 / 倒退 / 陨落。"""
        if not self.config.plugin.enabled:
            return False, "Disabled", 0
        if self._has_quote(kwargs):
            return False, "Quote ignored", 0

        group_id, sender_qq, _ = self._extract_ctx(kwargs)
        if not group_id or not sender_qq:
            return True, "Not in group", 2

        user = self._get_user_data(group_id, sender_qq)
        if not self._check_daily_limit(group_id, sender_qq, "realm_dive", B.REALM_DIVE_LIMIT,
                               cycle_hours=B.REALM_DIVE_CYCLE_HOURS):
            await self._send_avatar_msg(group_id, "你本周期已经下过秘境，调息一阵再来吧。", sender_qq, "")
            return True, "limit", 2

        level = user["level"]
        p_gold = B.REALM_DIVE_GOLD_PROB
        p_surge = B.REALM_DIVE_SURGE_PROB
        p_fall = B.REALM_DIVE_FALL_PROB
        p_death = B.REALM_DIVE_DEATH_PROB
        total = p_gold + p_surge + p_fall + p_death
        if total <= 0:                      # 配置写坏时兜底，避免 ZeroDivision
            total = 1.0
        recharge = self._take_recharge(user)     # 氪金：把结果推向更好的分支
        roll = random.random() * total
        roll = max(0.0, roll - recharge)

        if roll < p_gold:
            lo = max(1, level * B.REALM_DIVE_MONEY_MIN_FACTOR)
            hi = max(lo, level * B.REALM_DIVE_MONEY_MAX_FACTOR)
            gain = random.randint(lo, hi)
            user["money"] += gain
            msg = f"你在秘境深处寻得一处灵石矿脉，收获 {gain} 金币！当前余额 {user['money']}。"
        elif roll < p_gold + p_surge:
            before = level
            user["level"] = min(MAX_LEVEL, level + B.REALM_DIVE_SURGE_LEVELS)
            msg = (f"秘境中偶得大能遗蜕，你吸收其道韵，修为暴涨一个大境界！"
                   f"【{realm_name(before)}】→【{realm_name(user['level'])}】")
        elif roll < p_gold + p_surge + p_fall:
            before = level
            user["level"] = max(0, level - B.REALM_DIVE_FALL_LEVELS)
            msg = (f"秘境中遭遇凶兽，你仓皇逃遁、道基受创，修为倒退一个大境界！"
                   f"【{realm_name(before)}】→【{realm_name(user['level'])}】")
        else:
            before, after = self._rebirth(group_id, sender_qq, "秘境陨落")
            msg = (f"秘境中天雷降下，你未能抵御、就此陨落……\n"
                   f"只能保留 {round(B.REBIRTH_KEEP_RATIO * 100)}% 的修为重入轮回："
                   f"【{realm_name(before)}】→【{realm_name(after)}】，其余一切重置。")

        if self.config.partner_game.persist_enabled:
            await self._store.save()
        await self._send_avatar_msg(group_id, msg, sender_qq, "")
        return True, "Dive done", 2



    # ---------------- 交配 ----------------
    @Command("mating_request", pattern=r"^\s*(?:/申请交配|申请交配)$")
    async def handle_mating_request(self, stream_id: str = "", **kwargs):
        """向伴侣发起交配申请，需要对方回复「同意」。"""
        if not self.config.plugin.enabled:
            return False, "Disabled", 0
        if self._has_quote(kwargs):
            return False, "Quote ignored", 0

        group_id, sender_qq, _ = self._extract_ctx(kwargs)
        if not group_id or not sender_qq:
            return True, "Not in group", 2

        blocked, why = self._guard(group_id, sender_qq, "other")
        if blocked:
            await self._send_avatar_msg(group_id, why, sender_qq, "")
            return True, "blocked", 2


        marriage = self._get_user_marriage(group_id, sender_qq)
        if not marriage:
            await self._send_avatar_msg(group_id, "你还没有伴侣，交配个寂寞啊……", sender_qq, "")
            return True, "Single", 2

        affection = marriage.get("affection", 0)
        need = B.MATING_AFFECTION_MIN
        if affection < need:
            await self._send_avatar_msg(
                group_id,
                f"你们的感情还不够深（当前好感 {affection}，需要 {need}），先用【/约会】培养一下吧。",
                sender_qq, "")
            return True, "Low affection", 2

        if not self._check_daily_limit(group_id, sender_qq, "mating", B.MATING_LIMIT):
            await self._send_avatar_msg(group_id, "本周期你们已经折腾太多次了，歇一歇吧。", sender_qq, "")
            return True, "limit", 2

        partner_qq = str(marriage["partner_uid"])
        husband_qq = sender_qq if marriage["role"] == "husband" else partner_qq
        self.pending_mating[(group_id, partner_qq)] = {
            "proposer": sender_qq,
            "partner": partner_qq,
            "husband_qq": husband_qq,          # 好感记在老公那条记录上
            "group_id": group_id,
            "timestamp": time.time(),
        }

        nick = await self._get_member_nick(group_id, partner_qq)
        await self._send_avatar_msg(
            group_id,
            f"【{sender_qq}】向伴侣【{nick}({partner_qq})】发起了交配申请……\n"
            f"请对方在 {B.MATING_TIMEOUT_SECONDS} 秒内回复「同意」或「拒绝」。",
            sender_qq, partner_qq)
        return True, "Mating requested", 2

    @Command("mating_reply", pattern=r"^\s*(?:/)?(?:我)?(?:同意|拒绝)\s*$")
    async def handle_mating_reply(self, stream_id: str = "", **kwargs):
        """处理交配申请：只在存在待处理申请时才接管消息，否则放行给 AI。"""
        group_id, sender_qq, _ = self._extract_ctx(kwargs)
        if not group_id or not sender_qq:
            return False, "Not in group", 0

        key = (group_id, sender_qq)
        req = self.pending_mating.get(key)
        if not req:
            return False, "No pending mating", 0      # 普通聊天里的「同意」不拦截

        if time.time() - req["timestamp"] > B.MATING_TIMEOUT_SECONDS:
            del self.pending_mating[key]
            await self._send_avatar_msg(group_id, "交配申请已经超时作废了。", sender_qq, "")
            return True, "Timeout", 2

        text = self._message_text(kwargs)
        if "拒绝" in text:
            del self.pending_mating[key]
            await self._send_avatar_msg(group_id, "对方拒绝了你的交配申请……", req["proposer"], sender_qq)
            return True, "Rejected", 2

        # 同意：先确认关系还在（可能刚被抢/离婚）
        marriage = self._get_user_marriage(group_id, req["proposer"])
        if not marriage or str(marriage.get("partner_uid")) != str(sender_qq):
            del self.pending_mating[key]
            await self._send_avatar_msg(group_id, "你们已经不是伴侣了，申请作废。", sender_qq, "")
            return True, "No longer partners", 2

        del self.pending_mating[key]

        marriages = self._store.data.setdefault("marriages", {}).setdefault(group_id, {})
        rec = marriages.get(req["husband_qq"])
        if rec is not None:
            rec["affection"] = rec.get("affection", 0) + B.MATING_AFFECTION_GAIN
        if self.config.partner_game.persist_enabled:
            await self._store.save()

        total = rec.get("affection", 0) if rec else B.MATING_AFFECTION_GAIN
        await self._send_avatar_msg(
            group_id,
            f"两情相悦，缠绵一场~\n好感度 +{B.MATING_AFFECTION_GAIN}，当前总好感 {total}。",
            sender_qq, req["proposer"])
        return True, "Mating accepted", 2



    # ---------------- 氪金 ----------------
    @Command("recharge", pattern=r"^\s*(?:/氪金|氪金)\s*\d+$")
    async def handle_recharge(self, stream_id: str = "", **kwargs):
        """花金币给「下一次」行动买成功率：打劫 / 强娶 / 下秘境 / 修炼。"""
        if not self.config.plugin.enabled:
            return False, "Disabled", 0
        if self._has_quote(kwargs):
            return False, "Quote ignored", 0

        group_id, sender_qq, _ = self._extract_ctx(kwargs)
        if not group_id or not sender_qq:
            return True, "Not in group", 2

        amount = self._parse_amount(kwargs)
        if not amount or amount < B.RECHARGE_MIN_AMOUNT:
            await self._send_avatar_msg(
                group_id, f"单次氪金至少 {B.RECHARGE_MIN_AMOUNT} 金币，例如【/氪金 {B.RECHARGE_MIN_AMOUNT}】。",
                sender_qq, "")
            return True, "Invalid amount", 2

        user = self._get_user_data(group_id, sender_qq)
        if user["money"] < amount:
            await self._send_avatar_msg(group_id, f"你只有 {user['money']} 金币，氪不起 {amount}。", sender_qq, "")
            return True, "Not enough", 2

        current = float(user.get("recharge", 0) or 0)
        if current >= B.RECHARGE_CAP:
            await self._send_avatar_msg(group_id, "你的加成已经到顶了，先用掉再说吧。", sender_qq, "")
            return True, "Maxed", 2

        user["money"] -= amount
        total = self._add_recharge(user, amount)
        if self.config.partner_game.persist_enabled:
            await self._store.save()

        await self._send_avatar_msg(
            group_id,
            f"氪金 {amount} 成功！当前待用加成 【{round(total * 100, 2)}%】（上限 {round(B.RECHARGE_CAP * 100)}%），"
            f"剩余金币 {user['money']}。\n"
            f"该加成作用于下一次 /打劫、/强娶、/下秘境 或 /修炼，用掉即清零。",
            sender_qq, "")
        return True, "Recharged", 2



    # ---------------- 打怪 ----------------
    @Command("beast", pattern=r"^\s*(?:/打怪|打怪)$")
    async def handle_beast(self, stream_id: str = "", **kwargs):
        """挑战怪物：金币 / 修为提升 / 境界跌落 / 陨落。"""
        if not self.config.plugin.enabled:
            return False, "Disabled", 0
        if self._has_quote(kwargs):
            return False, "Quote ignored", 0

        group_id, sender_qq, _ = self._extract_ctx(kwargs)
        if not group_id or not sender_qq:
            return True, "Not in group", 2

        blocked, why = self._guard(group_id, sender_qq, "beast")
        if blocked:
            await self._send_avatar_msg(group_id, why, sender_qq, "")
            return True, "blocked", 2


        is_cd, rem = self._check_cooldown(group_id, sender_qq, "beast", B.COOLDOWN_BEAST)
        if is_cd:
            await self._send_avatar_msg(group_id, f"技能冷却中，请等待 {rem} 秒后再试~", sender_qq, "")
            return True, "cooldown", 2

        user = self._get_user_data(group_id, sender_qq)
        if not self._check_daily_limit(group_id, sender_qq, "beast", B.BEAST_LIMIT,
                                       cycle_hours=B.BEAST_CYCLE_HOURS):
            await self._send_avatar_msg(group_id, "你本周期已经打够了，怪物们也需要休息。", sender_qq, "")
            return True, "limit", 2

        level = user["level"]
        p_gold, p_gain = B.BEAST_GOLD_PROB, B.BEAST_GAIN_PROB
        p_lose, p_death = B.BEAST_LOSE_PROB, B.BEAST_DEATH_PROB
        total = p_gold + p_gain + p_lose + p_death
        if total <= 0:
            total = 1.0
        roll = random.random() * total

        if roll < p_gold:
            lo = max(1, level * B.BEAST_MONEY_MIN_FACTOR)
            hi = max(lo, level * B.BEAST_MONEY_MAX_FACTOR)
            gain = random.randint(lo, hi)
            user["money"] += gain
            msg = f"你斩杀了一头妖兽，从其巢穴中搜刮出 {gain} 金币！当前余额 {user['money']}。"
        elif roll < p_gold + p_gain:
            before = user["level"]
            user["level"] = min(MAX_LEVEL, before + B.BEAST_GAIN_LEVELS)
            msg = (f"激战中你顿悟了一丝道韵，修为提升 {B.BEAST_GAIN_LEVELS} 级！"
                   f"【{realm_name(before)}】→【{realm_name(user['level'])}】")
        elif roll < p_gold + p_gain + p_lose:
            before = user["level"]
            user["level"] = max(0, before - B.BEAST_LOSE_LEVELS)
            msg = (f"你被怪物重创，狼狈逃回，修为跌落 {B.BEAST_LOSE_LEVELS} 级！"
                   f"【{realm_name(before)}】→【{realm_name(user['level'])}】")
        else:
            before, after = self._rebirth(group_id, sender_qq, "打怪陨落")
            msg = (f"你遇上了一头远古凶兽，力竭身陨……\n"
                   f"只能保留 {round(B.REBIRTH_KEEP_RATIO * 100)}% 的修为重入轮回："
                   f"【{realm_name(before)}】→【{realm_name(after)}】，其余一切重置。")

        if self.config.partner_game.persist_enabled:
            await self._store.save()
        await self._send_avatar_msg(group_id, msg, sender_qq, "")
        return True, "Beast done", 2

    # ---------------- 重生 ----------------
    @Command("rebirth", pattern=r"^\s*(?:/重生|重生)$")
    async def handle_rebirth(self, stream_id: str = "", **kwargs):
        """主动重生：保留约定比例的修为，其余一切重置。"""
        if not self.config.plugin.enabled:
            return False, "Disabled", 0
        if self._has_quote(kwargs):
            return False, "Quote ignored", 0

        group_id, sender_qq, _ = self._extract_ctx(kwargs)
        if not group_id or not sender_qq:
            return True, "Not in group", 2

        before, after = self._rebirth(group_id, sender_qq, "主动重生")
        if self.config.partner_game.persist_enabled:
            await self._store.save()

        await self._send_avatar_msg(
            group_id,
            f"你散去一身因果，重入轮回。\n"
            f"仅保留 {round(B.REBIRTH_KEEP_RATIO * 100)}% 的修为："
            f"【{realm_name(before)}】→【{realm_name(after)}】；金币重置为 {B.INITIAL_MONEY}，"
            f"伴侣、贷款、氪金加成与本周期次数全部清空。",
            sender_qq, "")
        return True, "Rebirth done", 2



    # ---------------- 霸凌 ----------------
    @Command("bully", pattern=r"^\s*(?:/霸凌|霸凌)(?:\s+|\[CQ:at|@|\d|$).*")
    async def handle_bully(self, stream_id: str = "", **kwargs):
        """境界高 2 个大境界才能霸凌：抢钱 + 短期封禁对方行动。"""
        if not self.config.plugin.enabled:
            return False, "Disabled", 0
        if self._has_quote(kwargs):
            return False, "Quote ignored", 0

        group_id, sender_qq, _ = self._extract_ctx(kwargs)
        if not group_id or not sender_qq:
            return True, "Not in group", 2

        blocked, why = self._guard(group_id, sender_qq, "bully")
        if blocked:
            await self._send_avatar_msg(group_id, why, sender_qq, "")
            return True, "blocked", 2

        target_qq = self._extract_at_qq(kwargs)
        if not target_qq:
            await self._send_avatar_msg(group_id, "你想霸凌谁？请 @ 对方。", sender_qq, "")
            return True, "No target", 2
        if target_qq == sender_qq:
            await self._send_avatar_msg(group_id, "自虐不叫霸凌。", sender_qq, "")
            return True, "Self", 2

        is_cd, rem = self._check_cooldown(group_id, sender_qq, "bully", B.COOLDOWN_BULLY)
        if is_cd:
            await self._send_avatar_msg(group_id, f"技能冷却中，请等待 {rem} 秒后再试~", sender_qq, "")
            return True, "cooldown", 2

        attacker = self._get_user_data(group_id, sender_qq)
        victim = self._get_user_data(group_id, target_qq)
        gap = attacker["level"] - victim["level"]
        if gap < B.BULLY_LEVEL_GAP:
            await self._send_avatar_msg(
                group_id,
                f"境界压制不足（你的 {realm_name(attacker['level'])} vs 对方 {realm_name(victim['level'])}，"
                f"相差 {gap} 级，需要 {B.BULLY_LEVEL_GAP} 级 = 2 个大境界）。",
                sender_qq, "")
            return True, "Gap too small", 2

        if not self._check_daily_limit(group_id, sender_qq, "bully", B.BULLY_LIMIT,
                                       cycle_hours=B.BULLY_CYCLE_HOURS):
            await self._send_avatar_msg(group_id, "本周期霸凌次数已用完。", sender_qq, "")
            return True, "limit", 2

        nick = await self._get_member_nick(group_id, target_qq)

        if random.random() < B.BULLY_SUCCESS_PROB:
            stolen = random.randint(B.BULLY_STEAL_MIN, B.BULLY_STEAL_MAX)
            victim["money"] -= stolen
            attacker["money"] += stolen
            self._ban(group_id, target_qq, B.BULLY_BAN_SECONDS, "霸凌")
            msg = (f"【{sender_qq}】以境界压制霸凌了【{nick}({target_qq})】，"
                   f"抢走 {stolen} 金币，并将对方封禁 {B.BULLY_BAN_SECONDS} 秒！")
        else:
            ratio = random.uniform(B.BULLY_PAY_RATIO_MIN, B.BULLY_PAY_RATIO_MAX)
            pay = int(max(0, attacker["money"]) * ratio)
            attacker["money"] -= pay
            victim["money"] += pay
            msg = (f"【{sender_qq}】的霸凌被【{nick}({target_qq})】挡下，"
                   f"反被索赔 {pay} 金币（{round(ratio * 100, 1)}%）。")

        if self.config.partner_game.persist_enabled:
            await self._store.save()
        await self._send_avatar_msg(group_id, msg, sender_qq, target_qq)
        return True, "Bully done", 2

    # ---------------- 镇压 ----------------
    @Command("suppress", pattern=r"^\s*(?:/镇压|镇压)(?:\s+|\[CQ:at|@|\d|$).*")
    async def handle_suppress(self, stream_id: str = "", **kwargs):
        """境界高 4 个大境界才能镇压：封禁对方与其伴侣，并打落双方修为。"""
        if not self.config.plugin.enabled:
            return False, "Disabled", 0
        if self._has_quote(kwargs):
            return False, "Quote ignored", 0

        group_id, sender_qq, _ = self._extract_ctx(kwargs)
        if not group_id or not sender_qq:
            return True, "Not in group", 2

        blocked, why = self._guard(group_id, sender_qq, "suppress")
        if blocked:
            await self._send_avatar_msg(group_id, why, sender_qq, "")
            return True, "blocked", 2

        target_qq = self._extract_at_qq(kwargs)
        if not target_qq:
            await self._send_avatar_msg(group_id, "你想镇压谁？请 @ 对方。", sender_qq, "")
            return True, "No target", 2
        if target_qq == sender_qq:
            await self._send_avatar_msg(group_id, "镇压自己并不能证明什么。", sender_qq, "")
            return True, "Self", 2

        is_cd, rem = self._check_cooldown(group_id, sender_qq, "suppress", B.COOLDOWN_SUPPRESS)
        if is_cd:
            await self._send_avatar_msg(group_id, f"技能冷却中，请等待 {rem} 秒后再试~", sender_qq, "")
            return True, "cooldown", 2

        attacker = self._get_user_data(group_id, sender_qq)
        victim = self._get_user_data(group_id, target_qq)
        gap = attacker["level"] - victim["level"]
        if gap < B.SUPPRESS_LEVEL_GAP:
            await self._send_avatar_msg(
                group_id,
                f"境界不足以镇压（你 {realm_name(attacker['level'])} vs 对方 {realm_name(victim['level'])}，"
                f"相差 {gap} 级，需要 {B.SUPPRESS_LEVEL_GAP} 级 = 4 个大境界）。",
                sender_qq, "")
            return True, "Gap too small", 2

        if not self._check_daily_limit(group_id, sender_qq, "suppress", B.SUPPRESS_LIMIT,
                                       cycle_hours=B.SUPPRESS_CYCLE_HOURS):
            await self._send_avatar_msg(group_id, "本周期镇压次数已用完。", sender_qq, "")
            return True, "limit", 2

        nick = await self._get_member_nick(group_id, target_qq)
        marriage = self._get_user_marriage(group_id, target_qq)
        partner_qq = str(marriage["partner_uid"]) if marriage else None

        if random.random() < B.SUPPRESS_SUCCESS_PROB:
            self._ban(group_id, target_qq, B.SUPPRESS_BAN_SECONDS, "镇压")
            if partner_qq:
                self._ban(group_id, partner_qq, B.SUPPRESS_PARTNER_BAN_SECONDS, "镇压")

            victim["level"] = max(0, victim["level"] - B.SUPPRESS_DROP_LEVELS)
            if partner_qq:
                partner = self._get_user_data(group_id, partner_qq)
                partner["level"] = max(0, partner["level"] - B.SUPPRESS_DROP_LEVELS)

            msg = (f"【{sender_qq}】悍然镇压了【{nick}({target_qq})】！\n"
                   f"对方被封禁 {B.SUPPRESS_BAN_SECONDS} 秒"
                   + (f"，其伴侣也被一并封禁 {B.SUPPRESS_PARTNER_BAN_SECONDS} 秒" if partner_qq else "")
                   + f"；夫妻二人修为各跌落 {B.SUPPRESS_DROP_LEVELS} 级。")
        else:
            ratio = random.uniform(B.SUPPRESS_PAY_RATIO_MIN, B.SUPPRESS_PAY_RATIO_MAX)
            pay = int(max(0, attacker["money"]) * ratio)
            attacker["money"] -= pay
            victim["money"] += pay
            attacker["level"] = max(0, attacker["level"] - B.SUPPRESS_FAIL_SELF_DROP)
            msg = (f"【{sender_qq}】的镇压被【{nick}({target_qq})】反制！\n"
                   f"赔付 {pay} 金币（{round(ratio * 100, 1)}%），自身境界跌落 {B.SUPPRESS_FAIL_SELF_DROP} 级。")

        if self.config.partner_game.persist_enabled:
            await self._store.save()
        await self._send_avatar_msg(group_id, msg, sender_qq, target_qq)
        return True, "Suppress done", 2


def create_plugin():
    return PartnerGamePlugin()
