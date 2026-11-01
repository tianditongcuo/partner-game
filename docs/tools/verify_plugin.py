# -*- coding: utf-8 -*-
"""
MaiBot 插件识别预检
====================
按官方规范离线校验一个插件目录"能不能被 MaiBot 识别"，不需要启动 MaiBot：
  https://docs.mai-mai.org/plugin/          （目录结构与生命周期）
  https://docs.mai-mai.org/plugin/manifest  （_manifest.json 校验规则）

用法:
    python docs/tools/verify_plugin.py <插件目录> [plugins 目录]

第二个参数给了的话，会额外检查 plugins 目录里是否存在重复插件 ID —— 
这是本地"改了却没被识别"最常见的原因（日志表现为"插件 ID 重复，已阻止加载"）。
"""
from __future__ import annotations

import ast
import io
import json
import os
import re
import sys

ID_RE = re.compile(r"^[a-z0-9]+(?:[.-][a-z0-9]+)+$")
SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+$")

# manifest 允许出现的字段（Pydantic 严格模式：多余字段直接拒绝）
ALLOWED = {
    "manifest_version", "id", "version", "name", "description", "author", "license",
    "urls", "host_application", "sdk", "dependencies", "capabilities", "i18n",
    "plugin_type", "display", "llm_providers", "entry",
}
REQUIRED = ["manifest_version", "id", "version", "name", "description", "author",
            "license", "urls", "host_application", "sdk", "capabilities", "i18n"]

ok_all = True


def ok(msg):
    print("  [ OK ] " + msg)


def bad(msg):
    global ok_all
    ok_all = False
    print("  [FAIL] " + msg)


def warn(msg):
    print("  [WARN] " + msg)


def read(p):
    with io.open(p, "r", encoding="utf-8-sig") as f:
        return f.read()


def check_structure(root):
    print("\n[1] 目录结构")
    if not os.path.isdir(root):
        bad("目录不存在: " + root)
        return None
    names = os.listdir(root)
    for f in ("_manifest.json", "plugin.py"):
        if f in names:
            ok("存在 " + f)
        else:
            bad("缺少必需文件 " + f)

    # 常见错误：多套了一层同样的目录（GitHub 下载压缩包解压后常见）
    nested = [n for n in names if os.path.isdir(os.path.join(root, n))]
    for n in nested:
        if os.path.exists(os.path.join(root, n, "_manifest.json")):
            bad("发现嵌套的插件目录 %s/（里面有 _manifest.json）—— 部署时会因为"
                "根目录没有 manifest 而无法识别，应把该目录的内容直接放到 plugins/<name>/ 下" % n)

    data = os.path.join(root, "data")
    if os.path.isdir(data):
        warn("存在 data/（运行时数据）。确保它没有被提交进 git")
    cfg = os.path.join(root, "config.toml")
    if os.path.exists(cfg):
        warn("存在 config.toml（运行时配置）。官方建议加入 .gitignore")

    # docs/ 等非插件目录里如果有 .py，确认导入期没有副作用
    for sub in ("docs", "tools", "tests"):
        d = os.path.join(root, sub)
        if os.path.isdir(d) and any(n.endswith(".py") for n in os.listdir(d)):
            warn("%s/ 内含 .py；确认这些模块在 import 时不会执行副作用（否则某些加载器会崩）" % sub)
    return names


def check_manifest(root):
    print("\n[2] _manifest.json 校验（官方 ManifestValidator 规则）")
    path = os.path.join(root, "_manifest.json")
    try:
        raw = read(path)
        m = json.loads(raw)
    except Exception as e:
        bad("JSON 解析失败: %s" % e)
        return None
    ok("JSON 可解析")

    missing = [k for k in REQUIRED if k not in m]
    if missing:
        bad("缺少必填字段: %s" % ", ".join(missing))
    else:
        ok("必填字段齐全")

    extra = [k for k in m if k not in ALLOWED]
    if extra:
        bad("存在未声明字段（Pydantic 严格模式会拒绝）: %s" % ", ".join(extra))
    else:
        ok("无多余字段")

    if m.get("manifest_version") != 2:
        bad("manifest_version 必须为 2，当前是 %r" % m.get("manifest_version"))
    else:
        ok("manifest_version = 2")

    pid = m.get("id", "")
    if ID_RE.match(pid):
        ok("id 格式合法: %s" % pid)
    else:
        bad("id 格式非法（需 ^[a-z0-9]+(?:[.-][a-z0-9]+)+$）: %r" % pid)

    if SEMVER_RE.match(m.get("version", "")):
        ok("version 三段式: %s" % m["version"])
    else:
        bad("version 必须是 X.Y.Z: %r" % m.get("version"))

    author = m.get("author") or {}
    if not (isinstance(author, dict) and author.get("name") and author.get("url")):
        bad("author 必须是 {name, url}")
    elif not str(author["url"]).startswith(("http://", "https://")):
        bad("author.url 必须是 http(s) URL")
    else:
        ok("author 合法")

    urls = m.get("urls") or {}
    if not str(urls.get("repository", "")).startswith(("http://", "https://")):
        bad("urls.repository 缺失或不是 http(s) URL")
    else:
        ok("urls.repository 合法")

    for key in ("host_application", "sdk"):
        seg = m.get(key) or {}
        lo, hi = seg.get("min_version", ""), seg.get("max_version", "")
        if not (SEMVER_RE.match(lo) and SEMVER_RE.match(hi)):
            bad("%s 的上下界必须是 X.Y.Z: %r / %r" % (key, lo, hi))
            continue
        tl = tuple(int(x) for x in lo.split("."))
        th = tuple(int(x) for x in hi.split("."))
        if tl > th:
            bad("%s: min_version 大于 max_version" % key)
            continue
        ok("%s = [%s, %s]" % (key, lo, hi))
        if key == "host_application" and hi.endswith(".99.99") and hi.startswith("1.99"):
            warn("host_application.max_version=1.99.99 是官方明确禁止的写法"
                 "（应写成实测过的 主.次.99，如 1.3.99）；当前 Host 1.3.x 仍可加载，"
                 "但升到 2.x 后会被判为不兼容")

    caps = m.get("capabilities") or []
    if not isinstance(caps, list) or not caps:
        bad("capabilities 必须是非空数组")
    elif any(not c for c in caps):
        bad("capabilities 不允许包含空值")
    else:
        ok("capabilities: %s" % ", ".join(caps))

    i18n = m.get("i18n") or {}
    if not i18n.get("default_locale"):
        bad("i18n.default_locale 必填")
    else:
        ok("i18n.default_locale = %s" % i18n["default_locale"])
    lp = i18n.get("locales_path")
    if lp:
        full = os.path.join(root, lp)
        if os.path.isdir(full):
            ok("locales_path 存在: %s/" % lp)
        else:
            warn("声明了 locales_path=%r 但目录不存在（本版本实测不阻塞加载，但属于无效声明）" % lp)

    for dep in m.get("dependencies") or []:
        t = dep.get("type")
        if t not in ("plugin", "python_package"):
            bad("未知依赖类型: %r" % t)
        if t == "plugin" and dep.get("id") == pid:
            bad("不允许依赖自身")
    ok("dependencies 共 %d 条" % len(m.get("dependencies") or []))
    return m


def check_code(root):
    print("\n[3] 插件入口与生命周期")
    path = os.path.join(root, "plugin.py")
    if not os.path.exists(path):
        return
    src = read(path)
    tree = ast.parse(src)

    classes = [n for n in tree.body if isinstance(n, ast.ClassDef)]
    plugin_cls = None
    methods = set()
    for c in classes:
        bases = [getattr(b, "id", getattr(b, "attr", "")) for b in c.bases]
        if "MaiBotPlugin" in bases or any(n.endswith("Plugin") for n in bases):
            plugin_cls = c
            methods = {f.name for f in c.body if isinstance(f, (ast.FunctionDef, ast.AsyncFunctionDef))}
    if not plugin_cls:
        bad("没有找到继承 MaiBotPlugin 的类")
    else:
        ok("找到插件类 %s" % plugin_cls.name)
        for need in ("on_load", "on_unload", "on_config_update"):
            if need in methods:
                ok("实现了 %s()" % need)
            else:
                bad("缺少生命周期方法 %s() —— Runner 会拒绝加载" % need)
        if "config_model" in src:
            ok("声明了 config_model")

    has_factory = any(isinstance(n, ast.FunctionDef) and n.name == "create_plugin"
                      for n in tree.body)
    if has_factory:
        ok("存在 create_plugin()")
    else:
        bad("缺少 create_plugin() —— 这是官方约定的入口")

    n_cmd = len(re.findall(r"@Command\(", src))
    n_tool = len(re.findall(r"@Tool\(", src))
    print("  [ info ] 组件统计: @Command x%d, @Tool x%d" % (n_cmd, n_tool))

    # 语法层面再兜一次
    try:
        compile(src, path, "exec")
        ok("plugin.py 语法通过")
    except SyntaxError as e:
        bad("plugin.py 语法错误: %s" % e)


def scan_duplicates(plugins_dir, current_root, pid):
    print("\n[4] plugins 目录重复 ID 检查（最常见的“改了却不生效”原因）")
    if not os.path.isdir(plugins_dir):
        warn("plugins 目录不存在: " + plugins_dir)
        return
    seen = {}
    for name in sorted(os.listdir(plugins_dir)):
        d = os.path.join(plugins_dir, name)
        if not os.path.isdir(d) or name.startswith("."):
            continue
        mf = os.path.join(d, "_manifest.json")
        if not os.path.exists(mf):
            continue
        try:
            other = json.loads(read(mf))
        except Exception:
            continue
        seen.setdefault(other.get("id"), []).append(name)

    dups = {k: v for k, v in seen.items() if len(v) > 1}
    if dups:
        for k, v in dups.items():
            bad("插件 ID %s 重复出现在: %s" % (k, ", ".join(v)))
        print("       MaiBot 会把这些插件全部阻止加载（日志: 插件 ID 重复，已阻止加载）")
    else:
        ok("plugins 目录下无重复插件 ID")

    if pid:
        dirs = seen.get(pid, [])
        if not dirs:
            warn("当前 plugins 目录里没有 id=%s 的插件（还没安装）" % pid)
        else:
            ok("已安装于: %s" % ", ".join(dirs))


def main():
    if len(sys.argv) < 2:
        print("用法: python verify_plugin.py <插件目录> [plugins 目录]")
        return 2
    root = os.path.abspath(sys.argv[1])
    plugins_dir = os.path.abspath(sys.argv[2]) if len(sys.argv) > 2 else None

    print("=" * 68)
    print("MaiBot 插件识别预检: " + root)
    print("=" * 68)

    check_structure(root)
    m = check_manifest(root)
    check_code(root)
    if plugins_dir:
        scan_duplicates(plugins_dir, root, (m or {}).get("id"))

    print("\n" + "=" * 68)
    if ok_all:
        print("结论: 通过 —— 该目录满足 MaiBot 的识别条件")
    else:
        print("结论: 存在问题 —— 上面 [FAIL] 项需要修复")
    print("=" * 68)
    return 0 if ok_all else 1


if __name__ == "__main__":
    sys.exit(main())
