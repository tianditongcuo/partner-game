# -*- coding: utf-8 -*-
"""插件冒烟测试：不启动 MaiBot，用桩模块验证「这份代码 import 得进来」。

用途
----
重构后最怕的不是算错，而是某个函数里引用了已被删除的名字 —— 那种错误
`py_compile` 查不出来（Python 到调用时才解析名字），但一上线就炸。
本脚本用假的 maibot_sdk / pydantic / aiohttp 把插件包导入一遍，
再实例化并调用几个纯函数，能覆盖住"模块级 + 导入级"的破坏。

用法：
    python docs/tools/smoke_test.py
"""
from __future__ import annotations

import io
import os
import shutil
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PKG = "plugin_under_test"
SKIP = {"docs", "data", "__pycache__", ".git", ".github", "config.toml"}

STUB_SDK = '''
CONFIG_RELOAD_SCOPE_SELF = "self"


class PluginConfigBase(object):
    pass


def Field(default=None, description=None, default_factory=None, json_schema_extra=None):
    if default_factory is not None:
        return default_factory()
    return default


class MaiBotPlugin(object):
    config_model = None
    config_reload_subscriptions = ()

    def __init__(self):
        self.ctx = None


def Command(*args, **kwargs):
    def deco(fn):
        return fn
    return deco


def Tool(*args, **kwargs):
    def deco(fn):
        return fn
    return deco
'''

STUB_PYDANTIC = '''
def field_validator(*args, **kwargs):
    def deco(fn):
        return fn
    return deco


def Field(*args, **kwargs):
    return None
'''

STUB_AIOHTTP = '''
class ClientTimeout(object):
    def __init__(self, total=None):
        self.total = total


class ClientSession(object):
    def __init__(self, *a, **kw):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False
'''


def build_workspace(work):
    for name, body in (("maibot_sdk", STUB_SDK), ("pydantic", STUB_PYDANTIC), ("aiohttp", STUB_AIOHTTP)):
        os.makedirs(os.path.join(work, name), exist_ok=True)
        with io.open(os.path.join(work, name, "__init__.py"), "w", encoding="utf-8") as f:
            f.write(body)

    dst = os.path.join(work, PKG)
    os.makedirs(dst, exist_ok=True)
    for name in os.listdir(ROOT):
        if name in SKIP:
            continue
        src = os.path.join(ROOT, name)
        target = os.path.join(dst, name)
        if os.path.isdir(src):
            shutil.copytree(src, target, ignore=shutil.ignore_patterns("__pycache__"))
        else:
            shutil.copy2(src, target)


def main():
    work = tempfile.mkdtemp(prefix="maibot_smoke_")
    ok = True
    try:
        build_workspace(work)
        sys.path.insert(0, work)

        try:
            mod = __import__(PKG)
            print("[ OK ] 包导入成功")
        except Exception as e:
            print("[FAIL] 包导入失败: %s: %s" % (type(e).__name__, e))
            return 1

        try:
            plugin = mod.create_plugin()
            print("[ OK ] create_plugin() → %s" % type(plugin).__name__)
        except Exception as e:
            print("[FAIL] 实例化失败: %s: %s" % (type(e).__name__, e))
            ok = False

        try:
            pkg = __import__(PKG, fromlist=["combat", "balance", "realms"])
            r = pkg.combat.resolve(pkg.combat.KIND_ROB_WIFE, 60, 56, 100, 0.3)
            print("[ OK ] combat.resolve(60 vs 56, 好感100) = %.2f%%" % r.percent)
            print("[ OK ] balance.CYCLE_HOURS = %s" % pkg.balance.CYCLE_HOURS)
            print("[ OK ] realms.MAX_LEVEL = %s（%s）" % (pkg.realms.MAX_LEVEL, pkg.realms.realm_name(pkg.realms.MAX_LEVEL)))
        except Exception as e:
            print("[FAIL] 子模块调用失败: %s: %s" % (type(e).__name__, e))
            ok = False
    finally:
        shutil.rmtree(work, ignore_errors=True)

    print("\n结论: %s" % ("通过 ✓" if ok else "失败 ✗"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
