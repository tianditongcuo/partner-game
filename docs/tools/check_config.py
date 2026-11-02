# -*- coding: utf-8 -*-
"""配置自检：默认值必须在自身区间内，且 schema 能正常生成。

必须在 **MaiBot 的 Python 环境**里跑（需要 pydantic + maibot_sdk）：

    <MaiBot 自带 Python 的路径> docs/tools/check_config.py

它能抓住一类很隐蔽的错误：给字段加了 ge/le 之后，默认值反而落在区间外，
导致整份配置校验失败、WebUI 保存不了（打劫周期 0.5、打工下限 -100 就是这样翻车的）。
"""
from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)


def main():
    ok = True

    # 1) 模型能否用默认值构造
    try:
        from config import PartnerGameConfig
        model = PartnerGameConfig()
        print("[ OK ] PartnerGameConfig() 用默认值构造成功")
    except Exception as e:
        print("[FAIL] 默认值本身就校验不过：%s" % e)
        return 1

    # 2) 每个默认值是否落在自己的区间内
    try:
        from maibot_sdk.config import generate_plugin_config_schema
        schema = generate_plugin_config_schema(PartnerGameConfig)
    except Exception as e:
        print("[FAIL] schema 生成失败：%s" % e)
        return 1

    checked = 0
    for sec_key, sec in schema["sections"].items():
        for name, f in sec["fields"].items():
            lo, hi, default = f.get("min"), f.get("max"), f.get("default")
            if lo is None and hi is None:
                continue
            checked += 1
            if default is None:
                continue
            if (lo is not None and default < lo) or (hi is not None and default > hi):
                ok = False
                print("[FAIL] %s.%s 默认 %s 不在区间 [%s, %s]"
                      % (sec_key, name, default, lo, hi))

    print("[ OK ] 已检查 %d 个带区间的字段" % checked)

    # 3) 滑块场景：小数应被容错成整数
    try:
        m = PartnerGameConfig(balance_rob_money={"rob_money_cycle_hours": 0.5})
        got = m.balance_rob_money.rob_money_cycle_hours
        if got != 1:
            ok = False
            print("[FAIL] 0.5 小时应被取整为 1，实际 %s" % got)
        else:
            print("[ OK ] 小数 0.5 → 整数 %s" % got)
    except Exception as e:
        ok = False
        print("[FAIL] 小数容错失效：%s" % e)

    print("\n结论: %s" % ("通过 ✓" if ok else "失败 ✗"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
