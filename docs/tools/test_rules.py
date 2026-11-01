# -*- coding: utf-8 -*-
"""业务规则测试：打劫金额、贷款、逾期封禁、不限次。

复用 smoke_test 的桩环境，直接对插件实例调用方法，不启动 MaiBot。
"""
from __future__ import annotations

import asyncio
import os
import sys
import tempfile
import time
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import smoke_test as ST   # 复用建桩逻辑


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


class FakeLog(object):
    def info(self, *a, **k):
        pass

    def warning(self, *a, **k):
        pass


def make_plugin(mod, balance):
    p = mod.create_plugin()
    p.ctx = SimpleNamespace(logger=FakeLog())
    p._store = FakeStore()
    p._last_action = {}
    p.pending_proposals = {}
    p.config = SimpleNamespace(
        plugin=SimpleNamespace(enabled=True),
        partner_game=SimpleNamespace(tz_offset_hours=8, persist_enabled=False,
                                     no_limit_users=[], admin_users=[],
                                     cooldown_seconds=0, forced_wives=[]),
        balance=SimpleNamespace(),
    )
    return p


def main():
    work = tempfile.mkdtemp(prefix="maibot_rules_")
    ok = True
    try:
        ST.build_workspace(work)
        sys.path.insert(0, work)
        mod = __import__(ST.PKG)
        pkg = __import__(ST.PKG, fromlist=["balance", "realms"])
        B = pkg.balance
        p = make_plugin(mod, B)

        print("\n[打劫金额]")
        for money, expect in ((1000, "100~250"), (10, "50（被打成负债）"),
                              (0, "100（负资产保护上限）"), (-500, "100")):
            got = p._calc_steal_amount(money)
            print("  受害者 %6s 金币 → 抢走 %s   （预期 %s）" % (money, got, expect))
        assert p._calc_steal_amount(10) == 50, "小额应触发下限 50"
        assert p._calc_steal_amount(0) == B.ROB_MONEY_NEGATIVE_CAP
        assert p._calc_steal_amount(-500) == B.ROB_MONEY_NEGATIVE_CAP
        hi = p._calc_steal_amount(100000)
        assert hi <= 25000, "不应超过 150%% 上限"
        print("  [ OK ] 小额负债、负资产封顶、比例上限都符合预期")

        print("\n[贷款]")
        user = p._get_user_data("g1", "u1")
        base = user["money"]
        assert p._loan_owed(user) == 0
        user["money"] += 800
        user["loan"] = {"principal": 800, "borrowed_at": time.time()}
        assert p._loan_owed(user) == 1600, p._loan_owed(user)
        assert p._loan_overdue(user) is False
        user["loan"]["borrowed_at"] = time.time() - (B.LOAN_GRACE_MINUTES * 60 + 5)
        assert p._loan_overdue(user) is True
        assert p._loan_block("g1", "u1", "rob_money") is True, "逾期应封禁打劫"
        assert p._loan_block("g1", "u1", "work") is False, "逾期仍可打工"
        assert p._loan_block("g1", "u1", "realm_dive") is False, "逾期仍可下秘境"
        assert p._loan_block("g1", "u1", "repay") is False, "必须允许还贷"
        print("  [ OK ] 2 倍还款、15 分钟逾期、封禁范围正确（打工/秘境/还贷放行）")

        print("\n[次数限制]")
        assert p._check_daily_limit("g1", "u2", "dump", 1) is True
        assert p._check_daily_limit("g1", "u2", "dump", 1) is False, "第 2 次应被拒"
        assert p._check_daily_limit("g1", "u3", "dump", "不限制") is True
        assert p._check_daily_limit("g1", "u3", "dump", "不限制") is True
        assert p._check_daily_limit("g1", "u3", "dump", "不限制") is True
        assert p._check_daily_limit("g1", "u4", "dump", 0) is False, "0 表示禁用"
        print("  [ OK ] 正常计数、「不限制」无限次、0 禁用三种语义都对")

        print("\n[下秘境概率]")
        probs = [B.REALM_DIVE_GOLD_PROB, B.REALM_DIVE_SURGE_PROB,
                 B.REALM_DIVE_FALL_PROB, B.REALM_DIVE_DEATH_PROB]
        print("  金币 %.0f%% / 暴涨 %.0f%% / 倒退 %.0f%% / 陨落 %.0f%%  合计 %.0f%%"
              % (probs[0] * 100, probs[1] * 100, probs[2] * 100, probs[3] * 100, sum(probs) * 100))
        assert abs(sum(probs) - 1.0) < 1e-9, "概率和应为 1"
        print("  [ OK ] 概率归一")

    except AssertionError as e:
        ok = False
        print("  [FAIL]", e)
    except Exception as e:
        ok = False
        print("  [FAIL] %s: %s" % (type(e).__name__, e))
    finally:
        import shutil
        shutil.rmtree(work, ignore_errors=True)

    print("\n结论: %s" % ("通过 ✓" if ok else "失败 ✗"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
