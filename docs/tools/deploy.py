# -*- coding: utf-8 -*-
"""一键把仓库代码部署到 MaiBot 的 plugins 目录。

为什么不用手动复制粘贴：
  - 文件内容没变时资源管理器会"跳过相同文件"，看起来像替换失败；
  - 容易多套一层目录或复制出第二份同名插件 ID，导致两者都被阻止加载；
  - 复制完无法确认到底有没有生效。

本脚本做三件事：按插件 ID 定位目录 → 逐文件同步（内容相同则跳过）→ 校验结果。

用法：
    python docs/tools/deploy.py                     # 同步代码与文档
    python docs/tools/deploy.py --no-docs           # 只同步代码
    python docs/tools/deploy.py --enable            # 同步并启用插件
    python docs/tools/deploy.py --enable --restart  # 同步 + 启用 + 提示重启
"""
from __future__ import annotations

import argparse
import io
import json
import os
import shutil
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DEFAULT_PLUGINS = r"D:/Maimaibot/my-maibot/plugins"

CODE_FILES = ["plugin.py", "config.py", "utils.py", "__init__.py",
              "realms.py", "balance.py", "combat.py", "_manifest.json",
              "README.md", "LICENSE", ".gitignore"]
FORBIDDEN_TOP = {"config.toml", "data"}


def read_manifest(root):
    path = os.path.join(root, "_manifest.json")
    if not os.path.exists(path):
        raise SystemExit("仓库根目录没有 _manifest.json，路径不对？")
    with io.open(path, encoding="utf-8-sig") as f:
        return json.load(f)


def normalize(path):
    """读文件并统一换行，用于"内容是否一致"的判断（CRLF/LF 不算差异）。"""
    with io.open(path, "rb") as f:
        data = f.read()
    return data.replace(b"\r\n", b"\n")


def find_conflicts(plugins_dir, plugin_id, target_name):
    """找 plugins 下所有 manifest.id 相同的目录 —— 重复 ID 会让插件全部被拒载。"""
    hits = []
    for name in sorted(os.listdir(plugins_dir)):
        d = os.path.join(plugins_dir, name)
        if not os.path.isdir(d) or name.startswith("."):
            continue
        mf = os.path.join(d, "_manifest.json")
        if not os.path.exists(mf):
            continue
        try:
            with io.open(mf, encoding="utf-8-sig") as f:
                other = json.load(f)
        except Exception:
            continue
        if other.get("id") == plugin_id:
            hits.append(name)
    return hits


def sync_file(src, dst):
    """返回 'new' / 'updated' / 'same'。"""
    if not os.path.exists(dst):
        shutil.copy2(src, dst)
        return "new"
    if normalize(src) == normalize(dst):
        # 内容一致，仍刷新时间戳，方便判断"这份是什么时候部署的"
        os.utime(dst, None)
        return "same"
    shutil.copy2(src, dst)
    return "updated"


def set_enabled(target, enabled):
    cfg = os.path.join(target, "config.toml")
    flag = "true" if enabled else "false"
    if not os.path.exists(cfg):
        return "缺少 config.toml（插件至少加载过一次才会生成），跳过开关设置"
    with io.open(cfg, encoding="utf-8") as f:
        text = f.read()
    lines = text.splitlines()
    out, in_plugin, done = [], False, False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            in_plugin = (stripped == "[plugin]")
        if in_plugin and stripped.startswith("enabled") and not done:
            out.append("enabled = %s" % flag)
            done = True
            continue
        out.append(line)
    if not done:
        out = ["[plugin]", "enabled = %s" % flag] + out
    with io.open(cfg, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(out) + "\n")
    return "已设置 enabled = %s" % flag


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--plugins-dir", default=DEFAULT_PLUGINS)
    ap.add_argument("--no-docs", action="store_true", help="不同步 docs/")
    ap.add_argument("--enable", action="store_true", help="把 config.toml 里的 enabled 设为 true")
    ap.add_argument("--disable", action="store_true", help="把 enabled 设为 false")
    args = ap.parse_args()

    manifest = read_manifest(ROOT)
    plugin_id = manifest["id"]
    target_name = plugin_id.replace(".", "_")
    target = os.path.join(args.plugins_dir, target_name)

    print("插件 ID : %s" % plugin_id)
    print("目标目录: %s" % target)
    print("-" * 60)

    if not os.path.isdir(args.plugins_dir):
        raise SystemExit("插件目录不存在: %s" % args.plugins_dir)

    conflicts = find_conflicts(args.plugins_dir, plugin_id, target_name)
    if len(conflicts) > 1:
        print("[!] 检测到重复插件 ID，MaiBot 会全部拒载：")
        for c in conflicts:
            print("      -", c)
        raise SystemExit("请先手动删除多余目录，只保留 %s" % target_name)

    os.makedirs(target, exist_ok=True)

    stats = {"new": 0, "updated": 0, "same": 0}
    for name in CODE_FILES:
        src = os.path.join(ROOT, name)
        if not os.path.exists(src):
            print("  [跳过] 仓库里没有", name)
            continue
        state = sync_file(src, os.path.join(target, name))
        stats[state] += 1
        mark = {"new": "新增", "updated": "更新", "same": "相同"}[state]
        print("  %-4s %s" % (mark, name))

    if not args.no_docs and os.path.isdir(os.path.join(ROOT, "docs")):
        dst_docs = os.path.join(target, "docs")
        if os.path.isdir(dst_docs):
            shutil.rmtree(dst_docs)
        shutil.copytree(os.path.join(ROOT, "docs"), dst_docs,
                        ignore=shutil.ignore_patterns("__pycache__"))
        print("  同步  docs/")

    for bad in FORBIDDEN_TOP:
        if os.path.exists(os.path.join(target, bad)):
            print("  [注意] 目标目录存在 %s（运行时产物，不会被覆盖）" % bad)

    print("-" * 60)
    print("结果: 新增 %(new)d / 更新 %(updated)d / 未变 %(same)d" % stats)

    if args.enable or args.disable:
        print(set_enabled(target, args.enable))

    if stats["updated"] or stats["new"]:
        print("\nMaiBot 的 file_watcher 通常几秒内自动热重载；没有反应就重启一次。")
    elif not (args.enable or args.disable):
        print("\n代码已是最新，无需操作（这也是复制粘贴看起来“没反应”的原因）。")

    return 0


if __name__ == "__main__":
    sys.exit(main())
