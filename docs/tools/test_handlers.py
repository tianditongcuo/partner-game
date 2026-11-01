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
