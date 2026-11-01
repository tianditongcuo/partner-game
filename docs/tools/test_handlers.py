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
