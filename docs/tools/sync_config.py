# -*- coding: utf-8 -*-
"""安全合并配置：只补新增字段，绝不覆盖用户已改的值。

用法（需 MaiBot 的 Python，因为要读 pydantic 模型）：

    python docs/tools/sync_config.py --config <插件目录>/config.toml
    python docs/tools/sync_config.py --config ... --dry-run   # 只看会加什么

为什么需要它：MaiBot 的 Runner 不会把新版本新增的配置段写进已有的 config.toml，
而直接"按默认值重写"会清掉用户在 WebUI 里调过的所有数值。
本脚本的做法是：读出旧文件 → 以模型默认值打底 → 用旧值覆盖同名键 → 写回。
"""
from __future__ import annotations

import argparse
import io
import os
import sys

try:
    import tomllib
except ImportError:  # pragma: no cover - Python < 3.11
    tomllib = None

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)


def fmt(value):
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, str):
        return '"%s"' % value.replace("\\", "\\\\").replace('"', '\\"')
    return repr(value) if isinstance(value, float) else str(value)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True, help="目标 config.toml 路径")
    ap.add_argument("--dry-run", action="store_true", help="只报告不写入")
    args = ap.parse_args()

    if tomllib is None:
        print("需要 Python 3.11+ 来读取 TOML")
        return 1

    from config import PartnerGameConfig

    defaults = PartnerGameConfig().model_dump(mode="python")

    existing = {}
    if os.path.isfile(args.config):
        with io.open(args.config, "rb") as f:
            existing = tomllib.load(f)

    # 迁移：陨落概率从 ⑪ 天道惩戒 挪到了 ⑨ 下秘境
    old_heaven = existing.get("balance_heaven", {})
    if "realm_dive_death_prob" in old_heaven:
        dive = existing.setdefault("balance_explore", {})
        dive.setdefault("realm_dive_death_prob", old_heaven.pop("realm_dive_death_prob"))

    added, kept, dropped = [], 0, []

    out = []
    for section, fields in defaults.items():
        out.append("")
        out.append("[%s]" % section)
        old_section = existing.get(section, {})
        for key, default in fields.items():
            if key in old_section:
                value = old_section[key]
                kept += 1
            else:
                value = default
                added.append("%s.%s = %s" % (section, key, fmt(value)))
            out.append("%s = %s" % (key, fmt(value)))

        for key in old_section:
            if key not in fields:
                dropped.append("%s.%s" % (section, key))

    for section in existing:
        if section not in defaults:
            dropped.append("[%s] 整段" % section)

    while out and out[0] == "":
        out.pop(0)

    print("保留旧值 %d 项" % kept)
    if added:
        print("新增 %d 项：" % len(added))
        for item in added:
            print("  +", item)
    else:
        print("没有需要新增的字段")
    if dropped:
        print("清理 %d 项已废弃字段：" % len(dropped))
        for item in dropped:
            print("  -", item)

    if args.dry_run:
        print("\n[dry-run] 未写入")
        return 0

    with io.open(args.config, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(out) + "\n")
    print("\n已写入 %s" % args.config)
    return 0


if __name__ == "__main__":
    sys.exit(main())
