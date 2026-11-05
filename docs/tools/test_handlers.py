# -*- coding: utf-8 -*-
"""Handler 级测试：真正执行各指令的成功/失败分支，抓 NameError 这类运行期错误。

之前靠"导入+编译"是查不出失败的 —— 失败的 handler 里引用了已被删除的变量，
只有真的跑一遍才会炸。所以这里把 ctx / 存档 / 随机数全部打桩，直接调用 handler。
"""
from __future__ import annotations

import asyncio
import os
import random
import sys
import tempfile
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import smoke_test as ST


class FakeStore(object):
    def __init__(self):
        self.data = {"marriages": {}, "users": {}, "daily_usage": {}, "last_date": ""}

    def purge_old(self, today):
        if self.data.get("last_date") != today:
            self.data["last_date"] = today
            self.data["daily_usage"] = {}
            return True
        return False

    async def save(self):
        pass


class Recorder(object):
    """记录插件发出去的所有消息，便于断言。"""

    def __init__(self):
        self.msgs = []


async def _noop(*a, **k):
    return None


def make_plugin(mod, store, rec):
    p = mod.create_plugin()
    p.ctx = SimpleNamespace(logger=SimpleNamespace(info=lambda *a, **k: None,
                                                   warning=lambda *a, **k: None,
                                                   error=lambda *a, **k: None))
    p._store = store
    p._last_action = {}
    p.pending_proposals = {}
    p.pending_mating = {}      # on_load 里初始化，测试里手动补
    p.config = SimpleNamespace(
        plugin=SimpleNamespace(enabled=True),
        partner_game=SimpleNamespace(tz_offset_hours=8, persist_enabled=False,
                                     no_limit_users=[], admin_users=[],
                                     cooldown_seconds=0, forced_wives=[],
                                     force_marry_probability=0.4,
                                     rob_wife_probability=0.3,
                                     rob_money_probability=0.35,
                                     send_avatar=False, avatar_size=64),
        balance=SimpleNamespace(),
    )

    async def send(group_id, text, qq="", avatar=""):
        rec.msgs.append(text)

    p._send_avatar_msg = send
    p._send_text_at = send
    return p


async def run(mod, pkg):
    B = pkg.balance
    store = FakeStore()
    rec = Recorder()
    p = make_plugin(mod, store, rec)

    G = "g1"
    today = B.period_key(8)          # 与插件同一套周期判定，避免误触发低保
    users = store.data["users"].setdefault(G, {})
    for qq, money, level in (("u1", 2000, 20), ("u2", 3000, 40), ("u3", 5000, 10), ("u4", 500, 0)):
        users[qq] = {"money": money, "level": level, "last_allowance": today}
    store.data["marriages"][G] = {"u2": {"date": "x", "wife_uid": "u1", "wife_nick": "u1",
                                         "wife_card": "", "affection": 100}}

    def ctx(sender):
        p._extract_ctx = lambda kwargs: (G, sender, "nick")

    async def nick(group_id, qq):
        return "nick_" + str(qq)

    p._get_member_nick = nick

    results = []
    ok = True

    def reset():
        """清冷却与限次，让每个场景从干净状态开始。"""
        p._last_action = {}
        store.data["daily_usage"] = {}
        for qq in users:
            users[qq]["last_allowance"] = today

    # ---- 强娶失败（曾因 target_data 未定义崩溃）----
    reset()
    ctx("u3")
    p._extract_at_qq = lambda kwargs: "u4"
    with patch.object(random, "random", return_value=0.99), \
         patch.object(random, "randint", return_value=150):
        r = await p.handle_force_marry(stream_id="", message={"processed_plain_text": "/强娶 @u4"})
    ok &= (r[1] == "Force Marry Done")
    results.append(("强娶失败分支", r[1], rec.msgs[-1][:40]))

    # ---- 抢老婆失败（曾因 is_forced 未定义崩溃）----
    reset()
    ctx("u3")
    p._extract_at_qq = lambda kwargs: "u2"
    with patch.object(random, "random", return_value=0.99), \
         patch.object(random, "randint", return_value=300):
        r = await p.handle_rob_wife(stream_id="", message={"processed_plain_text": "/抢老婆 @u2"})
    ok &= (r[1] == "Rob Wife Done")
    results.append(("抢老婆失败分支", r[1], rec.msgs[-1][:40]))

    # ---- 抢老婆成功：会把老婆挂到抢夺者名下 ----
    reset()
    reset()
    ctx("u3")
    store.data["marriages"][G] = {"u2": {"date": "x", "wife_uid": "u1", "wife_nick": "u1",
                                         "wife_card": "", "affection": 100}}
    with patch.object(random, "random", return_value=0.0):
        r = await p.handle_rob_wife(stream_id="", message={"processed_plain_text": "/抢老婆 @u2"})
    moved = "u3" in store.data["marriages"][G] and "u2" not in store.data["marriages"][G]
    ok &= bool(moved)
    results.append(("抢老婆成功分支", "婚姻转移" if moved else "转移失败", ""))

    # ---- 打劫失败分支 ----
    reset()
    store.data["marriages"][G] = {}   # 清掉上一用例留下的婚姻关系
    reset()
    ctx("u3")
    p._extract_at_qq = lambda kwargs: "u1"
    with patch.object(random, "random", return_value=0.99), \
         patch.object(random, "randint", return_value=200):
        r = await p.handle_rob_money(stream_id="", message={"processed_plain_text": "/打劫 @u1"})
    ok &= (r[1] == "Rob Money Done")
    results.append(("打劫失败分支", r[1], rec.msgs[-1][:40]))

    # ---- 打劫成功：受害者可被打成负资产 ----
    reset()
    reset()
    ctx("u3")
    users["u4"]["money"] = 10
    p._extract_at_qq = lambda kwargs: "u4"
    with patch.object(random, "random", return_value=0.0), \
         patch.object(random, "randint", return_value=50):
        r = await p.handle_rob_money(stream_id="", message={"processed_plain_text": "/打劫 @u4"})
    results.append(("打劫成功(负债)", "受害者余额=%s" % users["u4"]["money"],
                    "应 ≤ -40"))
    ok &= users["u4"]["money"] < 0

    # ---- 贷款 / 还贷 ----
    reset()
    reset()
    ctx("u1")
    users["u1"] = {"money": 1000, "level": 20, "last_allowance": today}
    r = await p.handle_loan(stream_id="", message={"processed_plain_text": "/贷款 800"})
    loan_ok = users["u1"].get("loan", {}).get("principal") == 800 and users["u1"]["money"] == 1000 + 800
    ok &= bool(loan_ok)
    results.append(("贷款 800", "余额=%s 债务=%s" % (users["u1"]["money"],
                                                    users["u1"].get("loan", {}).get("principal")), ""))

    r = await p.handle_repay(stream_id="", message={"processed_plain_text": "/还贷"})
    repaid = "loan" not in users["u1"] and users["u1"]["money"] == 1000 + 800 - 1600
    ok &= bool(repaid)
    results.append(("还贷 1600", "余额=%s 债务=%s" % (users["u1"]["money"],
                                                    users["u1"].get("loan")), ""))

    # ---- 送钱 ----
    reset()
    ctx("u1")
    p._extract_at_qq = lambda kwargs: "u3"
    before_u3 = users["u3"]["money"]
    r = await p.handle_give_money(stream_id="", message={"processed_plain_text": "/送钱 @u3 100"})
    ok &= (users["u3"]["money"] == before_u3 + 100 and users["u1"]["money"] == 200 - 100)
    results.append(("送钱 100", "u3=%s u1=%s" % (users["u3"]["money"], users["u1"]["money"]), ""))

    # ---- 下秘境：四种结果都能跑通 ----
    reset()
    ctx("u2")
    users["u2"] = {"money": 1000, "level": 40, "last_allowance": today}
    for forced_roll, label in ((0.01, "金币"), (0.75, "暴涨"), (0.88, "倒退"), (0.99, "陨落")):
        p._store.data["daily_usage"] = {}
        with patch.object(random, "random", return_value=forced_roll), \
             patch.object(random, "randint", return_value=500):
            r = await p.handle_realm_dive(stream_id="", message={"processed_plain_text": "/下秘境"})
        results.append(("下秘境·" + label, r[1], "等级=%s 金币=%s" % (users["u2"]["level"], users["u2"]["money"])))
        ok &= (r[1] == "Dive done")
        users["u2"]["level"] = 40
        users["u2"]["money"] = 1000

    # ---- 打工：负收益（亏本）----
    reset()
    ctx("u1")
    users["u1"] = {"money": 1000, "level": 20, "last_allowance": today}
    with patch.object(random, "randint", return_value=-50):
        r = await p.handle_work(stream_id="", message={"processed_plain_text": "/打工"})
    ok &= (users["u1"]["money"] == 950)
    results.append(("打工亏本", "余额=%s" % users["u1"]["money"], "应 950"))

    # ---- 打工：上限 = 等级 × 系数 ----
    reset()
    ctx("u1")
    users["u1"] = {"money": 0, "level": 20, "last_allowance": today}
    with patch.object(random, "randint", return_value=20000):
        r = await p.handle_work(stream_id="", message={"processed_plain_text": "/打工"})
    results.append(("打工上限", "余额=%s" % users["u1"]["money"], "20 级上限 20000"))
    ok &= (users["u1"]["money"] == 20000)

    # ---- 动态罚款：下限 100，上限 = 现有金币 ----
    fines = [p._calc_fine(m, B.FORCE_FINE_FLOOR, B.FORCE_FINE_CAP_RATIO)
             for m in (300, 800, 5000) for _ in range(200)]
    in_range = all(100 <= f <= 5000 for f in fines)
    results.append(("罚款区间", "min=%d max=%d" % (min(fines), max(fines)), "应落在 100~5000"))
    ok &= in_range

    # ---- 交配流程 ----
    reset()
    store.data["marriages"][G] = {"u1": {"date": today, "wife_uid": "u2", "wife_nick": "u2",
                                         "wife_card": "", "affection": 100}}
    users["u1"] = {"money": 1000, "level": 20, "last_allowance": today}
    users["u2"] = {"money": 1000, "level": 20, "last_allowance": today}
    ctx("u1")
    r1 = await p.handle_mating_request(stream_id="", message={"processed_plain_text": "/申请交配"})
    pending = (G, "u2") in p.pending_mating
    ctx("u2")
    r2 = await p.handle_mating_reply(stream_id="", message={"processed_plain_text": "同意"})
    aff = store.data["marriages"][G]["u1"]["affection"]
    ok &= bool(pending) and aff == 150
    results.append(("交配成功", "好感 %s" % aff, "100 → 150"))

    # ---- 没有待处理申请时，「同意」不应被拦截 ----
    r3 = await p.handle_mating_reply(stream_id="", message={"processed_plain_text": "同意"})
    ok &= (r3[0] is False)
    results.append(("普通「同意」放行", str(r3[1]), "应返回 False 交给 AI"))

    # ---- 氪金：1000 金币 = +10% ----
    reset()
    ctx("u1")
    users["u1"] = {"money": 2000, "level": 20, "last_allowance": today}
    r = await p.handle_recharge(stream_id="", message={"processed_plain_text": "/氪金 1000"})
    got = users["u1"].get("recharge", 0)
    ok &= (users["u1"]["money"] == 1000 and abs(got - 0.10) < 1e-9)
    results.append(("氪金 1000", "余额=%s 加成=%.0f%%" % (users["u1"]["money"], got * 100), "应 +10%"))

    # ---- 氪金上限：99% ----
    users["u1"]["recharge"] = 0.95
    users["u1"]["money"] = 1000
    r = await p.handle_recharge(stream_id="", message={"processed_plain_text": "/氪金 1000"})
    cap = users["u1"]["recharge"]
    ok &= abs(cap - B.RECHARGE_CAP) < 1e-9
    results.append(("氪金封顶", "加成=%.0f%%" % (cap * 100), "应为 99%%"))

    # ---- 氪金可突破常规胜率上限（90%% → 最高 99%%）----
    low = pkg.combat.resolve(pkg.combat.KIND_ROB_MONEY, 0, 99, base_prob=0.35).final_prob
    high = pkg.combat.resolve(pkg.combat.KIND_ROB_MONEY, 0, 99, base_prob=0.35, bonus=0.5).final_prob
    ok &= abs(low - B.ROB_FLOOR) < 1e-9 and abs(high - 0.6) < 1e-9
    results.append(("氪金生效", "%.0f%% → %.0f%%" % (low * 100, high * 100), "下限 10%% + 50%% = 60%%"))

    # ---- 天妒：一周期成功 6 次 → 倒退 3 个大境界 ----
    reset()
    u = {"money": 0, "level": 40, "last_allowance": today}
    hits = [p._check_tian_du(G, "u9", u) for _ in range(7)]
    fired = [h for h in hits if h]
    ok &= (len(fired) == 1 and u["level"] == 28)
    results.append(("天妒", "触发 %d 次，40 → %d" % (len(fired), u["level"]), "应触发 1 次，-3 境界"))

    # ---- 天罚：一周期犯罪 9 次 → 扣 60% 金币 ----
    reset()
    u2 = {"money": 1000, "level": 0, "last_allowance": today}
    hits = [p._check_tian_fa(G, "u8", u2) for _ in range(9)]
    fired = [h for h in hits if h]
    ok &= (len(fired) == 1 and u2["money"] == 400)
    results.append(("天罚", "触发 %d 次，1000 → %d" % (len(fired), u2["money"]), "应触发 1 次，-60%"))

    # ---- 好感护盾硬上限 ----
    ok &= abs(B.affection_shield(10000) - B.AFFECTION_SHIELD_MAX) < 1e-9
    results.append(("护盾上限", "%.0f%%" % (B.affection_shield(10000) * 100), "应为 50%%"))

    # ---- 管理员重置：只保留修为与金币 ----
    reset()
    p.config.partner_game.admin_users = ["admin9"]
    store.data["marriages"][G] = {"u1": {"date": today, "wife_uid": "u2", "wife_nick": "u2",
                                         "wife_card": "", "affection": 300}}
    users["u1"] = {"money": 777, "level": 33, "last_allowance": today,
                   "loan": {"principal": 100, "borrowed_at": 0}, "recharge": 0.3}
    store.data["daily_usage"].setdefault(G, {})["u1"] = {"work": 3, "cultivate": 2, "mating": 3}
    ctx("admin9")
    p._extract_at_qq = lambda kwargs: "u1"
    r = await p.handle_admin_reset(stream_id="", message={"processed_plain_text": "/重置 @u1"})
    kept = (users["u1"]["money"] == 777 and users["u1"]["level"] == 33)
    cleared = ("loan" not in users["u1"] and "recharge" not in users["u1"]
               and "u1" not in store.data["marriages"][G]
               and "u1" not in store.data["daily_usage"].get(G, {}))
    ok &= bool(kept and cleared)
    results.append(("管理员重置", "保留 修为33/金币777" if kept else "保留了不该保留的",
                    "清空 %s" % ("成功" if cleared else "失败")))

    # ---- 约会免费：0 金币也能约会 ----
    reset()
    store.data["marriages"][G] = {"u1": {"date": today, "wife_uid": "u2", "wife_nick": "u2",
                                         "wife_card": "", "affection": 0}}
    users["u1"] = {"money": 0, "level": 0, "last_allowance": today}
    ctx("u1")
    with patch.object(random, "randint", return_value=15):
        r = await p.handle_date(stream_id="", message={"processed_plain_text": "/约会"})
    ok &= (users["u1"]["money"] == 0 and r[1] == "Date done")
    results.append(("约会免费", "余额=%s" % users["u1"]["money"], "应为 0（不扣钱）"))

    # ---- 离婚惩罚：开启后分走一半财富与修为 ----
    reset()
    B.DIVORCE_PENALTY_ENABLED = True
    store.data["marriages"][G] = {"u1": {"date": today, "wife_uid": "u2", "wife_nick": "u2",
                                         "wife_card": "", "affection": 0}}
    users["u1"] = {"money": 1000, "level": 20, "last_allowance": today}
    users["u2"] = {"money": 0, "level": 0, "last_allowance": today}
    ctx("u1")
    with patch.object(random, "randint", return_value=500):
        r = await p.handle_wife_draw(stream_id="", message={"processed_plain_text": "/离婚"})
    moved = (users["u1"]["money"] == 500 and users["u2"]["money"] == 500
             and users["u1"]["level"] == 10 and users["u2"]["level"] == 10)
    ok &= moved
    results.append(("离婚惩罚", "u1 %s/%s  u2 %s/%s" % (users["u1"]["money"], users["u1"]["level"],
                                                     users["u2"]["money"], users["u2"]["level"]),
                    "应各 500 金币 / 10 级"))
    B.DIVORCE_PENALTY_ENABLED = False

    # ---- 按行动独立冷却 ----
    reset()
    _, first = p._check_cooldown(G, "u7", "rob_money", 5)
    hit2, rem2 = p._check_cooldown(G, "u7", "rob_money", 5)
    hit3, _ = p._check_cooldown(G, "u7", "rob_wife", 5)
    ok &= (first == 0 and hit2 and not hit3)
    results.append(("独立冷却", "第二次 rob_money 剩余 %ds，rob_wife 不受影响" % rem2, "互不干扰"))

    # ---- 失败后只剩该行动的冷却（不再有独立"失败自闭"）----
    reset()
    ctx("u3")
    p._extract_at_qq = lambda kwargs: "u4"
    with patch.object(random, "random", return_value=0.99),          patch.object(random, "randint", return_value=150):
        await p.handle_force_marry(stream_id="", message={"processed_plain_text": "/强娶 @u4"})
    is_cd, rem = p._check_cooldown(G, "u3", "force_marry", B.COOLDOWN_FORCE)
    ok &= bool(is_cd) and rem <= B.COOLDOWN_FORCE
    results.append(("失败只剩冷却", "剩余 %ds（上限 %ds）" % (rem, B.COOLDOWN_FORCE), "不应超过冷却值"))

    # ---- 打怪：四种结果 ----
    for forced, label, expect_desc in (
        (0.05, "打怪·金币", "金币增加"),
        (0.65, "打怪·提升", "+4 级"),
        (0.88, "打怪·跌落", "-4 级"),
        (0.99, "打怪·陨落", "重生 70%"),
    ):
        reset()
        ctx("u1")
        users["u1"] = {"money": 1000, "level": 40, "last_allowance": today}
        with patch.object(random, "random", return_value=forced), \
             patch.object(random, "randint", return_value=5000):
            r = await p.handle_beast(stream_id="", message={"processed_plain_text": "/打怪"})
        u = users["u1"]
        results.append((label, "Lv=%s 金币=%s" % (u["level"], u["money"]), expect_desc))
        ok &= (r[1] == "Beast done")
    # 陨落后应为 40 * 0.7 = 28 级、金币重置为初始值
    ok &= (users["u1"]["level"] == 28 and users["u1"]["money"] == B.INITIAL_MONEY)

    # ---- 主动重生：保留 70% 修为，其余重置 ----
    reset()
    ctx("u1")
    store.data["marriages"][G] = {"u1": {"date": today, "wife_uid": "u2", "wife_nick": "u2",
                                         "wife_card": "", "affection": 500}}
    users["u1"] = {"money": 8888, "level": 50, "last_allowance": today,
                   "loan": {"principal": 100, "borrowed_at": 0}, "recharge": 0.4}
    r = await p.handle_rebirth(stream_id="", message={"processed_plain_text": "/重生"})
    u = users["u1"]
    kept = (u["level"] == 35 and u["money"] == B.INITIAL_MONEY
            and "loan" not in u and "recharge" not in u
            and "u1" not in store.data["marriages"][G])
    ok &= bool(kept)
    results.append(("主动重生", "Lv 50→%s 金币=%s" % (u["level"], u["money"]), "应 35 级 / 初始金币"))

    # ---- 配置分组迁移：打劫/秘境的次数应在各自分组里 ----
    cfg = pkg.config
    in_money = hasattr(cfg.BalanceRobMoneySection(), "rob_money_limit")
    in_dive = hasattr(cfg.BalanceExploreSection(), "realm_dive_limit")
    in_cycle = hasattr(cfg.BalanceCycleSection(), "rob_money_limit") or \
               hasattr(cfg.BalanceCycleSection(), "realm_dive_limit")
    ok &= bool(in_money and in_dive and not in_cycle)
    results.append(("分组迁移", "打劫=%s 秘境=%s 旧组残留=%s" % (in_money, in_dive, in_cycle),
                    "应在各自分组、① 不再包含"))

    # ---- 每个行动独立的周期时长 ----
    reset()
    B.ROB_MONEY_CYCLE_HOURS = 1
    B.REALM_DIVE_CYCLE_HOURS = 168

    first = p._check_daily_limit(G, "uc", "rob_money", 1, cycle_hours=B.ROB_MONEY_CYCLE_HOURS)
    second = p._check_daily_limit(G, "uc", "rob_money", 1, cycle_hours=B.ROB_MONEY_CYCLE_HOURS)
    # 模拟"打劫周期已过去"：把该行动的周期标记改成旧值
    store.data["daily_usage"][G]["uc"]["rob_money__period"] = "OLD"
    third = p._check_daily_limit(G, "uc", "rob_money", 1, cycle_hours=B.ROB_MONEY_CYCLE_HOURS)

    # 同一用户：打劫额度用完后，秘境（168h 周期）不受影响
    dive_ok = p._check_daily_limit(G, "uc", "realm_dive", 1, cycle_hours=B.REALM_DIVE_CYCLE_HOURS)

    ok &= bool(first and not second and third and dive_ok)
    results.append(("独立周期", "打劫 1h：%s/%s→%s，秘境 168h：%s" % (first, second, third, dive_ok),
                    "应 True/False/True，且秘境不受影响"))

    # ---- 氪金失败免罚 ----
    reset()
    ctx("u3")
    p._extract_at_qq = lambda kwargs: "u1"
    users["u3"] = {"money": 1000, "level": 10, "last_allowance": today, "recharge": 0.5}
    users["u1"] = {"money": 1000, "level": 10, "last_allowance": today}
    with patch.object(random, "random", return_value=0.99), \
         patch.object(random, "randint", return_value=200):
        await p.handle_rob_money(stream_id="", message={"processed_plain_text": "/打劫 @u1"})
    no_fine = (users["u3"]["money"] == 1000)
    results.append(("氪金免罚", "失败后余额=%s" % users["u3"]["money"], "应仍为 1000（不罚款）"))
    ok &= bool(no_fine)

    # ---- 霸凌：境界差不足应被拒绝 ----
    reset()
    ctx("u1")
    p._extract_at_qq = lambda kwargs: "u2"
    users["u1"] = {"money": 1000, "level": 30, "last_allowance": today}
    users["u2"] = {"money": 1000, "level": 26, "last_allowance": today}   # 差 4 级 < 8
    r = await p.handle_bully(stream_id="", message={"processed_plain_text": "/霸凌 @u2"})
    ok &= (r[1] == "Gap too small")
    results.append(("霸凌·境界不足", r[1], "差 4 级应被拒"))

    # ---- 霸凌：成功的抢钱与封禁 ----
    reset()
    ctx("u1")
    p._extract_at_qq = lambda kwargs: "u2"
    users["u1"] = {"money": 1000, "level": 40, "last_allowance": today}
    users["u2"] = {"money": 1000, "level": 20, "last_allowance": today}
    with patch.object(random, "random", return_value=0.1), \
         patch.object(random, "randint", return_value=100):
        r = await p.handle_bully(stream_id="", message={"processed_plain_text": "/霸凌 @u2"})
    ban_ok = users["u2"].get("banned_until", 0) > __import__("time").time()
    ok &= (users["u2"]["money"] == 900 and users["u1"]["money"] == 1100 and ban_ok)
    results.append(("霸凌·成功", "u2 金币=%s 封禁=%s" % (users["u2"]["money"], ban_ok), "应 -100 且被封禁"))

    # ---- 被封禁者无法打工 ----
    ctx("u2")
    r = await p.handle_work(stream_id="", message={"processed_plain_text": "/打工"})
    ok &= (r[1] == "blocked")
    results.append(("封禁拦截", r[1], "被封禁者应被拦下"))

    # ---- 镇压：双方封禁 + 修为跌落 ----
    reset()
    ctx("u1")
    p._extract_at_qq = lambda kwargs: "u2"
    store.data["marriages"][G] = {"u2": {"date": today, "wife_uid": "u5", "wife_nick": "u5",
                                         "wife_card": "", "affection": 0}}
    users["u1"] = {"money": 5000, "level": 60, "last_allowance": today}
    users["u2"] = {"money": 1000, "level": 40, "last_allowance": today}
    users["u5"] = {"money": 1000, "level": 30, "last_allowance": today}
    with patch.object(random, "random", return_value=0.1):
        r = await p.handle_suppress(stream_id="", message={"processed_plain_text": "/镇压 @u2"})
    both_banned = (users["u2"].get("banned_until", 0) > 0 and users["u5"].get("banned_until", 0) > 0)
    dropped = (users["u2"]["level"] == 36 and users["u5"]["level"] == 26)
    ok &= bool(both_banned and dropped)
    results.append(("镇压·成功", "u2=%s级 u5=%s级 双双封禁=%s" % (users["u2"]["level"], users["u5"]["level"], both_banned),
                    "各 -4 级且伴侣也封禁"))

    # ---- 天罚触发概率为 0 时永不触发 ----
    reset()
    B.TIAN_FA_TRIGGER_PROB = 0.0
    u = {"money": 1000, "level": 0, "last_allowance": today}
    for _ in range(12):
        p._check_tian_fa(G, "x1", u)
    ok &= (u["money"] == 1000)
    results.append(("天罚概率=0", "余额=%s" % u["money"], "应保持 1000（永不触发）"))
    B.TIAN_FA_TRIGGER_PROB = 1.0

    # ---- 天妒触发概率为 0 时永不触发 ----
    reset()
    B.TIAN_DU_TRIGGER_PROB = 0.0
    u2 = {"money": 0, "level": 40, "last_allowance": today}
    for _ in range(10):
        p._check_tian_du(G, "x2", u2)
    ok &= (u2["level"] == 40)
    results.append(("天妒概率=0", "等级=%s" % u2["level"], "应保持 40（永不触发）"))
    B.TIAN_DU_TRIGGER_PROB = 1.0

    # ---- 秘境会消耗氪金加成 ----
    reset()
    ctx("u1")
    users["u1"] = {"money": 1000, "level": 40, "last_allowance": today, "recharge": 0.3}
    with patch.object(random, "random", return_value=0.0), \
         patch.object(random, "randint", return_value=500):
        await p.handle_realm_dive(stream_id="", message={"processed_plain_text": "/下秘境"})
    consumed = "recharge" not in users["u1"]
    ok &= bool(consumed)
    results.append(("秘境吃氪金", "加成已消耗=%s" % consumed, "应被用掉"))

    # ---- 成员昵称缓存：两次查询只拉一次群成员 ----
    reset()
    calls = {"n": 0}

    async def fake_call(api_name, **kw):
        calls["n"] += 1
        return [{"user_id": "u1", "card": "卡片1", "nickname": "昵称1"}]

    p.ctx.api = SimpleNamespace(call=fake_call)
    p._member_cache = {}
    m1 = await p._member_map(G)
    m2 = await p._member_map(G)
    ok &= (calls["n"] == 1 and m1.get("u1") == "卡片1" and m2 is m1)
    results.append(("成员缓存", "API 调用 %d 次" % calls["n"], "两次查询应只调 1 次"))
    p.ctx.api = None

    # ---- 甩掉：双方都不受离婚惩罚 ----
    reset()
    B.DIVORCE_PENALTY_ENABLED = True
    store.data["marriages"][G] = {"u1": {"date": today, "wife_uid": "u2", "wife_nick": "u2",
                                         "wife_card": "", "affection": 0}}
    users["u1"] = {"money": 1000, "level": 20, "last_allowance": today}
    users["u2"] = {"money": 1000, "level": 20, "last_allowance": today}
    ctx("u2")                                    # 老婆主动甩掉老公
    p._extract_at_qq = lambda kwargs: "u1"
    with patch.object(random, "randint", return_value=500):
        r = await p.handle_dump(stream_id="", message={"processed_plain_text": "/甩掉 @u1"})
    untouched = (users["u1"]["money"] == 1000 and users["u1"]["level"] == 20
                 and users["u2"]["money"] == 1000 and users["u2"]["level"] == 20)
    ok &= bool(untouched)
    results.append(("甩掉不惩罚", "u1 %s/%s  u2 %s/%s" % (users["u1"]["money"], users["u1"]["level"],
                                                     users["u2"]["money"], users["u2"]["level"]),
                    "双方都应保持 1000/20"))
    B.DIVORCE_PENALTY_ENABLED = False

    # ---- 镇压文案：夫妻版 ----
    reset()
    ctx("u1")
    p._extract_at_qq = lambda kwargs: "u2"
    store.data["marriages"][G] = {"u2": {"date": today, "wife_uid": "u5", "wife_nick": "u5",
                                         "wife_card": "", "affection": 0}}
    users["u1"] = {"money": 5000, "level": 60, "last_allowance": today}
    users["u2"] = {"money": 1000, "level": 40, "last_allowance": today}
    users["u5"] = {"money": 1000, "level": 30, "last_allowance": today}
    with patch.object(random, "random", return_value=0.1):
        await p.handle_suppress(stream_id="", message={"processed_plain_text": "/镇压 @u2"})
    couple_msg = rec.msgs[-1]
    ok &= ("伴侣" in couple_msg and "夫妻二人" in couple_msg and "孤身" not in couple_msg)
    results.append(("镇压文案·夫妻", couple_msg.splitlines()[-1][:26], "应出现「伴侣/夫妻二人」"))

    # ---- 镇压文案：单身版 ----
    reset()
    ctx("u1")
    p._extract_at_qq = lambda kwargs: "u3"
    users["u1"] = {"money": 5000, "level": 60, "last_allowance": today}
    users["u3"] = {"money": 1000, "level": 40, "last_allowance": today}
    with patch.object(random, "random", return_value=0.1):
        await p.handle_suppress(stream_id="", message={"processed_plain_text": "/镇压 @u3"})
    single_msg = rec.msgs[-1]
    ok &= ("孤身" in single_msg and "夫妻" not in single_msg and "伴侣" not in single_msg)
    results.append(("镇压文案·单身", single_msg.splitlines()[-1][:26], "不应出现「夫妻/伴侣」"))

    # ---- 雷劫：元婴期大境界突破必遇 ----
    reset()
    ctx("u1")
    users["u1"] = {"money": 99999, "level": 39, "last_allowance": today}   # 元婴圆满
    with patch.object(random, "random", return_value=0.0):
        await p.handle_cultivate(stream_id="", message={"processed_plain_text": "/修炼"})
    trib_ok = (users["u1"]["level"] == 39 - B.TRIBULATION_DROP_LEVELS
               and "雷劫" in rec.msgs[-1])
    ok &= bool(trib_ok)
    results.append(("雷劫·元婴", "39→%s，文案含雷劫" % users["u1"]["level"], "应触发并跌落"))

    # ---- 雷劫不波及别的大境界（婴变圆满 43）----
    reset()
    ctx("u1")
    users["u1"] = {"money": 99999, "level": 43, "last_allowance": today}
    with patch.object(random, "random", return_value=0.0):
        await p.handle_cultivate(stream_id="", message={"processed_plain_text": "/修炼"})
    ok &= (users["u1"]["level"] == 44 and "雷劫" not in rec.msgs[-1])
    results.append(("雷劫·范围", "43→%s" % users["u1"]["level"], "婴变期不应遇雷劫"))

    # ---- 小境界突破不触发雷劫（元婴后期 38）----
    reset()
    ctx("u1")
    users["u1"] = {"money": 99999, "level": 38, "last_allowance": today}
    with patch.object(random, "random", return_value=0.0):
        await p.handle_cultivate(stream_id="", message={"processed_plain_text": "/修炼"})
    ok &= (users["u1"]["level"] == 39 and "雷劫" not in rec.msgs[-1])
    results.append(("雷劫·小境界", "38→%s" % users["u1"]["level"], "小境界不应遇雷劫"))

    # ---- 氪金可降低雷劫概率 ----
    reset()
    ctx("u1")
    users["u1"] = {"money": 99999, "level": 39, "last_allowance": today, "recharge": 0.5}
    with patch.object(random, "random", return_value=0.7):
        await p.handle_cultivate(stream_id="", message={"processed_plain_text": "/修炼"})
    ok &= (users["u1"]["level"] == 40 and "雷劫" not in rec.msgs[-1])
    results.append(("氪金续命", "39→%s" % users["u1"]["level"], "0.5 加成应挡掉雷劫并突破"))

    # ---- 氪金满额：强娶必定成功（random 0.999 也过）----
    reset()
    store.data["marriages"] = {}  # 清掉前面用例留下的婚姻关系
    ctx("u1")
    p._extract_at_qq = lambda kwargs: "u2"
    users["u1"] = {"money": 99999, "level": 10, "last_allowance": today, "recharge": 0.99}
    users["u2"] = {"money": 100, "level": 0, "last_allowance": today}
    with patch.object(random, "random", return_value=0.999), \
         patch.object(random, "randint", return_value=100):
        await p.handle_force_marry(stream_id="", message={"processed_plain_text": "/强娶 @u2"})
    married = str(store.data.get("marriages", {}).get(G, {}).get("u1", {}).get("wife_uid")) == "u2"
    ok &= bool(married)
    results.append(("氪金满额·强娶", "已绑定=%s" % married, "0.99 加成应必定成功"))

    # ---- 氪金满额：打怪不会跌落 ----
    reset()
    ctx("u1")
    users["u1"] = {"money": 1000, "level": 40, "last_allowance": today, "recharge": 0.99}
    with patch.object(random, "random", return_value=0.999), \
         patch.object(random, "randint", return_value=500):
        await p.handle_beast(stream_id="", message={"processed_plain_text": "/打怪"})
    beast_safe = (users["u1"]["level"] == 40 and "recharge" not in users["u1"])
    ok &= bool(beast_safe)
    results.append(("氪金满额·打怪", "等级=%s 加成已消耗=%s" % (users["u1"]["level"], "recharge" not in users["u1"]),
                    "不应跌落且加成用掉"))

    # ---- 氪金满额：秘境不会跌落 ----
    reset()
    ctx("u1")
    users["u1"] = {"money": 1000, "level": 40, "last_allowance": today, "recharge": 0.99}
    with patch.object(random, "random", return_value=0.999), \
         patch.object(random, "randint", return_value=500):
        await p.handle_realm_dive(stream_id="", message={"processed_plain_text": "/下秘境"})
    dive_safe = (users["u1"]["level"] == 40 and "recharge" not in users["u1"])
    ok &= bool(dive_safe)
    results.append(("氪金满额·秘境", "等级=%s" % users["u1"]["level"], "不应跌落"))

    # ---- 氪金文案不含百分比 ----
    reset()
    ctx("u1")
    users["u1"] = {"money": 99999, "level": 10, "last_allowance": today}
    await p.handle_recharge(stream_id="", message={"processed_plain_text": "/氪金 1000"})
    txt = rec.msgs[-1]
    ok &= ("%" not in txt and "氪金" in txt)
    results.append(("氪金文案", txt.splitlines()[0][:22], "不应出现百分比"))

    # ---- 成圣：成功升一层，按等级扣费 ----
    reset()
    store.data["marriages"] = {}
    ctx("u1")
    cost10 = B.SAINT_COST_BASE + 10 * B.SAINT_COST_PER_LEVEL
    users["u1"] = {"money": 10 ** 7, "level": 10, "last_allowance": today}
    with patch.object(random, "random", return_value=0.9):
        r = await p.handle_saint(stream_id="", message={"processed_plain_text": "/成圣"})
    ok &= (users["u1"]["level"] == 11 and users["u1"]["money"] == 10 ** 7 - cost10)
    results.append(("成圣·成功", "Lv 10→%s 余额=%s" % (users["u1"]["level"], users["u1"]["money"]), "应升一层并扣费"))

    # ---- 成圣：周期限次（第一次成功，第二次被拒）----
    reset()
    ctx("u1")
    with patch.object(random, "random", return_value=0.9):
        await p.handle_saint(stream_id="", message={"processed_plain_text": "/成圣"})
        r = await p.handle_saint(stream_id="", message={"processed_plain_text": "/成圣"})
    ok &= (r[1] == "limit")
    results.append(("成圣·限次", r[1], "同周期第二次应被拒"))

    # ---- 成圣：天谴跌落 ----
    reset()
    ctx("u1")
    users["u1"] = {"money": 10 ** 7, "level": 20, "last_allowance": today}
    with patch.object(random, "random", return_value=0.0):
        r = await p.handle_saint(stream_id="", message={"processed_plain_text": "/成圣"})
    dropped = users["u1"]["level"] == 20 - B.SAINT_PUNISH_DROP
    ok &= bool(dropped)
    results.append(("成圣·天谴", "Lv 20→%s" % users["u1"]["level"], "应跌落且不升级"))

    # ---- 成圣：费用随等级上涨 ----
    reset()
    ctx("u1")
    cost40 = B.SAINT_COST_BASE + 40 * B.SAINT_COST_PER_LEVEL
    users["u1"] = {"money": cost40 - 1, "level": 40, "last_allowance": today}
    r = await p.handle_saint(stream_id="", message={"processed_plain_text": "/成圣"})
    ok &= (r[1] == "No money" and cost40 > cost10)
    results.append(("成圣·费用", "40级需 %s（10级 %s）" % (cost40, cost10), "等级越高越贵且钱不够被拒"))

    # ---- 成圣：满级不可用 ----
    reset()
    ctx("u1")
    users["u1"] = {"money": 10 ** 9, "level": 99, "last_allowance": today}
    r = await p.handle_saint(stream_id="", message={"processed_plain_text": "/成圣"})
    ok &= (r[1] == "Max level")
    results.append(("成圣·满级", r[1], "99 级应拒绝"))

    # ---- 天妒：同周期内只触发一次 ----
    reset()
    store.data["daily_usage"] = {}
    u_td = {"money": 0, "level": 40, "last_allowance": today}
    with patch.object(pkg.balance, "period_key", return_value="P1"):
        hits = [p._check_tian_du(G, "td1", u_td) for _ in range(8)]
    fired = len([h for h in hits if h])
    ok &= (fired == 1)
    results.append(("天妒·同周期一次", "连修 8 次触发 %d 次" % fired, "阈值 6，只应触发 1 次"))

    # ---- 天妒：跨周期归零（昨天 4 次 + 今天 2 次不应触发）----
    reset()
    store.data["daily_usage"] = {}
    u_td2 = {"money": 0, "level": 40, "last_allowance": today}
    with patch.object(pkg.balance, "period_key", return_value="P1"):
        for _ in range(4):
            p._check_tian_du(G, "td2", u_td2)
    with patch.object(pkg.balance, "period_key", return_value="P2"):
        hits2 = [p._check_tian_du(G, "td2", u_td2) for _ in range(2)]
    ok &= all(h is None for h in hits2)
    results.append(("天妒·跨周期", "今天 2 次触发 %d 次" % len([h for h in hits2 if h]), "不应触发"))

    # ---- 天妒：新周期仍可再次触发 ----
    with patch.object(pkg.balance, "period_key", return_value="P2"):
        hits3 = [p._check_tian_du(G, "td2", u_td2) for _ in range(4)]
    ok &= any(hit3 is not None for hit3 in hits3)
    results.append(("天妒·新周期", "继续 4 次后触发=%s" % bool(any(hits3)), "累计 6 次应再次触发"))

    # ---- 天罚：跨周期不会把旧次数算进来 ----
    reset()
    store.data["daily_usage"] = {}
    u_tf = {"money": 1000, "level": 0, "last_allowance": today}
    with patch.object(pkg.balance, "period_key", return_value="P1"):
        for _ in range(7):
            p._check_tian_fa(G, "tf1", u_tf)
    with patch.object(pkg.balance, "period_key", return_value="P2"):
        hit_tf = p._check_tian_fa(G, "tf1", u_tf)
    ok &= (hit_tf is None and u_tf["money"] == 1000)
    results.append(("天罚·跨周期", "新周期首犯不触发（余额 %s）" % u_tf["money"], "旧计数不应累计"))

    print("%-16s %-18s %s" % ("场景", "返回", "详情"))
    print("-" * 78)
    for a, b, c in results:
        print("%-16s %-18s %s" % (a, b, c))
    return ok


def main():
    work = tempfile.mkdtemp(prefix="maibot_handlers_")
    ok = True
    try:
        ST.build_workspace(work)
        sys.path.insert(0, work)
        mod = __import__(ST.PKG)
        pkg = __import__(ST.PKG, fromlist=["balance", "realms"])
        ok = asyncio.get_event_loop().run_until_complete(run(mod, pkg))
    except Exception as e:
        ok = False
        import traceback
        traceback.print_exc()
    finally:
        import shutil
        shutil.rmtree(work, ignore_errors=True)

    print("\n结论: %s" % ("通过 ✓" if ok else "失败 ✗"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
