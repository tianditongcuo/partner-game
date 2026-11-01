# -*- coding: utf-8 -*-
"""
partner-game 维护地图生成器
============================
静态扫描插件源码，产出：
  docs/feature_map.json     机器可读的功能/依赖地图（重构时可直接消费）
  docs/handler_stats.csv    指令级统计（复杂度、依赖、数据写入）
  docs/FEATURES.md          功能分类清单（Markdown）
  docs/dashboard.html       自包含可视化面板（无 CDN）

重构后重新运行本脚本即可刷新全部文档：
    python docs/tools/gen_maintenance_map.py
"""
from __future__ import annotations

import ast
import csv
import io
import json
import os
import re
import sys
from collections import OrderedDict

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DOCS = os.path.join(ROOT, "docs")
PLUGIN_DIR = ROOT

# ---------------------------------------------------------------- 功能域定义
# key: 内部标识; name: 展示名; color: 图表配色; desc: 职责
DOMAINS = OrderedDict([
    ("router", ("入口与路由", "#6366f1", "指令注册、消息守卫、@目标解析、切片上下文")),
    ("marriage", ("婚姻关系", "#ec4899", "抽取/求婚/强绑/抢夺/解绑/查询，marriages 表的唯一所有者")),
    ("economy", ("经济财富", "#f59e0b", "金币产出与消耗、罚款与赔偿、转账")),
    ("cultivation", ("修仙成长", "#10b981", "境界等级、修炼消耗与突破、战力换算")),
    ("combat", ("战斗结算", "#ef4444", "概率公式、战力压制、好感护盾、胜率预测")),
    ("penalty", ("惩罚与限次", "#8b5cf6", "冷却、每日次数、失败自闭、罚款、掉级")),
    ("presentation", ("展示与输出", "#0ea5e9", "NapCat 直发、合并转发、头像、榜单、帮助文案")),
    ("persistence", ("数据与持久化", "#64748b", "JSON 存档、防抖写盘、跨日重置")),
    ("config", ("配置", "#84cc16", "17 个可调参数与管理员/白名单")),
    ("admin", ("管理运维", "#a855f7", "重置、全服补偿、定向发钱")),
])

# 指令 -> 功能域归属（人工分类，AST 提供事实，分类提供语义）
COMMAND_DOMAIN = {
    "partner_game": "marriage",
    "marry": "marriage",
    "proposal_reply": "marriage",
    "force_marry": "marriage",
    "rob_wife": "combat",
    "my_partner": "marriage",
    "dump_partner": "marriage",
    "partner_game_divorce": "marriage",
    "rob_chance": "combat",
    "rob_money": "combat",
    "rob_money_chance": "combat",
    "loan": "economy",
    "repay": "economy",
    "give_money": "economy",
    "realm_dive": "cultivation",
    "mating_request": "marriage",
    "mating_reply": "marriage",
    "work": "economy",
    "date": "economy",
    "transfer": "economy",
    "cultivate": "cultivation",
    "status": "presentation",
    "rank_power": "presentation",
    "rank_money": "presentation",
    "rank_affection": "presentation",
    "partner_game_help": "presentation",
    "game_info": "presentation",
    "admin_reset": "admin",
    "admin_compensate": "admin",
    "admin_give_money": "admin",
}

DATA_KEYS = ["marriages", "users", "daily_usage", "last_date"]

RE_API = re.compile(r'api\.call\(\s*[\'"]([a-zA-Z0-9_.]+)[\'"]')
RE_CFG = re.compile(r'config\.partner_game\.([a-z_]+)')
RE_DATA = re.compile(r'_store\.data(?:\.get\(|\.setdefault\(|\[)\s*[\'"]?([a-z_]+)')
RE_LIMIT = re.compile(r'_check_daily_limit\([^)]*?["\']([a-z_]+)["\']\s*,\s*(\d+)')
RE_COOLDOWN = re.compile(r'_check_cooldown\([^)]*?["\']([a-zA-Z_]+)["\']')
RE_PENALTY = re.compile(r'_set_penalty\([^)]*?["\']([a-zA-Z_]+)["\']\s*,\s*(\d+)')
RE_MONEY_UP = re.compile(r'\["money"\]\s*\+?=')
RE_LEVEL_UP = re.compile(r'\["level"\]\s*\+?=')
RE_AWAIT = re.compile(r'\bawait\b')


def read(path):
    with io.open(path, "r", encoding="utf-8") as f:
        return f.read()


def _const(node, default=None):
    """兼容 py3.7 的 ast.Str/Num 与 py3.8 的 ast.Constant。"""
    if isinstance(node, ast.Constant):
        return node.value
    for attr in ("s", "n"):
        if hasattr(node, attr):
            return getattr(node, attr)
    return default


def _find_def(lines, from_line, name):
    """从装饰器行向后找到真正的 `def` 行（1-based）。"""
    pat = re.compile(r"\s*(?:async\s+)?def\s+%s\b" % re.escape(name))
    for k in range(from_line - 1, min(from_line + 8, len(lines))):
        if pat.match(lines[k]):
            return k + 1
    return from_line


def _extent(lines, start):
    """从 def 行向后推断函数体结束行（py3.7 无 end_lineno）。"""
    n = len(lines)
    end = start - 1
    j = start  # 0-based index of line after def
    while j < n:
        raw = lines[j]
        if raw.strip() == "":
            j += 1
            continue
        indent = len(raw) - len(raw.lstrip())
        if indent == 0:
            break
        stripped = raw.lstrip()
        if indent == 4 and (stripped.startswith("@Command") or re.match(r"(async )?def ", stripped)):
            break
        end = j
        j += 1
    return end + 1


# ---------------------------------------------------------------- AST 扫描
def parse_commands(src):
    tree = ast.parse(src)
    lines = src.splitlines()
    out = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for dec in node.decorator_list:
            if not (isinstance(dec, ast.Call) and getattr(dec.func, "id", "") == "Command"):
                continue
            cmd_id = _const(dec.args[0]) if dec.args else None
            kw = {k.arg: k.value for k in dec.keywords}
            pattern = _const(kw.get("pattern"), "") or ""
            desc = _const(kw.get("description"), "") or ""
            aliases = []
            if isinstance(kw.get("aliases"), ast.List):
                aliases = [_const(e) for e in kw["aliases"].elts if _const(e) is not None]
            out.append({
                "id": cmd_id,
                "handler": node.name,
                "pattern": pattern,
                "description": desc,
                "aliases": aliases,
                "lineno": node.lineno,          # py3.7: 装饰器所在行
                "decorator_lineno": node.lineno,
                "code_lineno": _find_def(lines, node.lineno, node.name),
                "end_lineno": 0,
            })
    out.sort(key=lambda x: x["lineno"])
    for c in out:
        c["end_lineno"] = _extent(lines, c["code_lineno"])
    return out, lines


def analyse_handlers(cmds, lines, cfg_names):
    """统计每个 handler 的依赖。

    数据表访问分两层：
      direct   —— 直接读写 self._store.data[...]
      indirect —— 通过 _get_user_data / _get_user_marriage / _check_daily_limit 间接触达
    二者合并才是真实的耦合面。
    """
    for c in cmds:
        body = "\n".join(lines[c["code_lineno"] - 1:c["end_lineno"]])
        c["loc"] = c["end_lineno"] - c["code_lineno"] + 1
        c["awaits"] = len(RE_AWAIT.findall(body))
        c["api_calls"] = sorted(set(RE_API.findall(body)))

        cfg_keys = set(RE_CFG.findall(body))
        if re.search(r"=\s*self\.config\.partner_game\b", body):
            cfg_keys |= set(re.findall(r"\bcfg\.([a-z_]+)", body))
        c["config_keys"] = sorted(k for k in cfg_keys if k in cfg_names)

        direct = [k for k in RE_DATA.findall(body) if k in DATA_KEYS]
        inferred = []
        if re.search(r"_get_user_data|_save_user_data|\[\"money\"\]|\[\"level\"\]", body):
            inferred.append("users")
        if re.search(r"_get_user_marriage|marriages|affection", body):
            inferred.append("marriages")
        if re.search(r"_check_daily_limit|daily_usage|purge_old", body):
            inferred.append("daily_usage")
        if re.search(r"purge_old|last_date", body):
            inferred.append("last_date")
        c["data_direct"] = sorted(set(direct))
        c["data_indirect"] = sorted(set(inferred))
        c["data_keys"] = sorted(set(direct) | set(inferred))

        c["daily_limits"] = [[m[0], int(m[1])] for m in RE_LIMIT.findall(body)]
        c["cooldowns"] = sorted(set(RE_COOLDOWN.findall(body)))
        c["penalties"] = [[m[0], int(m[1])] for m in RE_PENALTY.findall(body)]
        c["mutates_money"] = bool(RE_MONEY_UP.search(body))
        c["mutates_level"] = bool(RE_LEVEL_UP.search(body))
        c["domain"] = COMMAND_DOMAIN.get(c["id"], "router")
    return cmds


def parse_config(src):
    tree = ast.parse(src)
    fields = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.ClassDef) and node.name.endswith("Section")):
            continue
        for stmt in node.body:
            if not (isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name)):
                continue
            if not (isinstance(stmt.value, ast.Call)):
                continue
            default = None
            for kw in stmt.value.keywords:
                if kw.arg == "default":
                    default = _const(kw.value, None)
            label = ""
            for kw in stmt.value.keywords:
                if kw.arg == "json_schema_extra" and isinstance(kw.value, ast.Dict):
                    for k, v in zip(kw.value.keys, kw.value.values):
                        if _const(k) == "label":
                            label = _const(v, "") or ""
            fields.append({
                "section": node.name,
                "name": stmt.target.id,
                "default": default,
                "label": label,
                "annotation": "",
            })
    return fields


def scan_module_calls(src):
    """模块级（非 handler）的适配器调用与数据访问，用于依赖图。"""
    api = sorted(set(RE_API.findall(src)))
    return api


# ---------------------------------------------------------------- 领域知识（数值）
# 境界数据直接从插件源码 realms.py 导入，避免文档与代码出现第二份真相
sys.path.insert(0, ROOT)
try:
    import realms as _realms
    REALMS = list(_realms.REALMS)
    SUB = list(_realms.SUB_REALMS)
    MAX_LEVEL = _realms.MAX_LEVEL
except Exception as _e:                      # 文档生成不应因插件损坏而崩溃
    print("[warn] 无法从 realms.py 读取境界表，回退到内置默认值:", _e)
    REALMS = ["凡境", "炼体", "凝气", "炼气", "筑基"]
    SUB = ["前期", "中期", "后期", "圆满"]
    MAX_LEVEL = len(REALMS) * len(SUB) - 1

ECONOMY = [
    # (名称, 类型, 金额/公式, 触发, 代码位置)
    ("初始资金", "source", "1000", "用户记录首次创建", "plugin.py:322"),
    ("每日低保", "source", "200 / 天", "当日首次读取用户数据", "plugin.py:330-333"),
    ("打工收入", "source", "50~100 + 等级×10，3 次/天", "/打工", "plugin.py:1421-1423"),
    ("打劫成功", "transfer", "目标资产 10%~25%（夹在 50~1500）", "/打劫", "plugin.py:1258-1265"),
    ("失败罚款赔偿", "source", "罚款金额的 50%", "强娶/抢老婆/打劫失败", "plugin.py:824-827"),
    ("上交存款", "transfer", "用户指定金额", "/上交存款", "plugin.py:1623-1624"),
    ("修炼消耗", "sink", "(大境界序号+1)×50，3 次/天", "/修炼", "plugin.py:1499-1500"),
    ("约会消耗", "sink", "50 / 次，3 次/天", "/约会", "plugin.py:1457"),
    ("失败罚款蒸发", "sink", "罚款的 50%（另一半赔付对方）", "同上三处", "plugin.py:828"),
    ("管理员发放", "source", "任意（无上限校验）", "/发钱、/全服补偿", "plugin.py:1789, 1827"),
]

PENALTIES = [
    ("通用冷却", "cooldown_seconds（默认 60s）", "同一用户同一指令", "9 条指令", "_check_cooldown"),
    ("每日次数", "1~3 次/天/用户", "抽取/离婚/甩人 1；打工/修炼/约会/打劫 3", "daily_usage", "_check_daily_limit"),
    ("失败自闭", "60s（硬编码上限）", "强娶/抢老婆/打劫 失败", "3 条指令", "_set_penalty"),
    ("金钱罚款", "强娶 100~300；抢老婆 200~500；打劫 100~300", "失败时，50% 赔给对方", "3 条指令", "各 handler 内联"),
    ("境界跌落", "1 级（20% 概率）", "抢老婆失败且等级>0", "rob_wife", "plugin.py:1072-1074"),
    ("修炼反噬", "1 级（30% 概率）", "大境界突破失败", "cultivate", "plugin.py:1529-1531"),
]

COMBAT = {
    "force_marry": {"base": 0.40, "power": False, "affection": False, "floor": 0.0, "cap": 1.0,
                    "gate": 300, "fine": (100, 300)},
    "rob_wife": {"base": 0.30, "power": True, "affection": True, "floor": 0.10, "cap": 0.90,
                 "gate": 500, "fine": (200, 500)},
    "rob_money": {"base": 0.35, "power": True, "affection": False, "floor": 0.10, "cap": 0.90,
                  "gate": 300, "fine": (100, 300)},
}

NEW_FEATURES = [
    ("财富体系", "economy", "既有 3 类入账 + 3 类出账全部内联在各 handler；无统一钱包服务、无流水账、无通胀调控",
     "抽 Wallet 领域服务 + 金币流水表（每笔变动带 reason）"),
    ("修炼体系和方式", "cultivation", "境界表已抽到 realms.py（25 大境界 × 4 小境界）；仍只有单一 /修炼 线性突破",
     "抽 Realm 表 + 可插拔功法（CultivationMethod 策略）"),
    ("惩罚机制", "penalty", "冷却/次数/罚款/掉级 4 类惩罚分散在 9 个 handler，各自内联，无法统一调整",
     "抽 PenaltyPolicy：声明式规则表 + 统一结算入口"),
    ("物品获取", "—（空白）", "代码中不存在任何 item/inventory/drop 概念，需从零设计",
     "新增 items 表 + DropTable，挂到 打工/打劫/修炼/约会 产出点"),
]


# ---------------------------------------------------------------- 主流程
def main():
    plugin_src = read(os.path.join(PLUGIN_DIR, "plugin.py"))
    config_src = read(os.path.join(PLUGIN_DIR, "config.py"))

    cmds, lines = parse_commands(plugin_src)
    cfg = parse_config(config_src)
    cfg_names = set(f["name"] for f in cfg)
    analyse_handlers(cmds, lines, cfg_names)

    total_loc = len(lines)
    model = {
        "meta": {
            "plugin": "今日老婆 Pro+",
            "id": "tianditongcuo.partner-game-pro",
            "version": "2.0.2",
            "files": {f: len(read(os.path.join(PLUGIN_DIR, f)).splitlines())
                      for f in ["plugin.py", "config.py", "utils.py", "__init__.py"]},
            "plugin_py_loc": total_loc,
            "commands": len(cmds),
            "config_fields": len(cfg),
            "domains": {k: {"name": v[0], "color": v[1], "desc": v[2]} for k, v in DOMAINS.items()},
        },
        "commands": cmds,
        "config": cfg,
        "data_keys": DATA_KEYS,
        "economy": ECONOMY,
        "penalties": PENALTIES,
        "combat": COMBAT,
        "realms": REALMS,
        "sub_realms": SUB,
        "max_level": MAX_LEVEL,
        "new_features": NEW_FEATURES,
        "module_api": scan_module_calls(plugin_src),
    }

    os.makedirs(DOCS, exist_ok=True)
    with io.open(os.path.join(DOCS, "feature_map.json"), "w", encoding="utf-8") as f:
        json.dump(model, f, ensure_ascii=False, indent=2)

    with io.open(os.path.join(DOCS, "handler_stats.csv"), "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["指令ID", "handler", "功能域", "起始行", "行数", "await数",
                    "适配器调用", "涉及数据表", "配置项", "每日次数", "冷却", "改钱", "改级"])
        for c in cmds:
            w.writerow([
                c["id"], c["handler"], DOMAINS[c["domain"]][0], c["lineno"], c["loc"], c["awaits"],
                "|".join(c["api_calls"]), "|".join(c["data_keys"]),
                "|".join(c["config_keys"]),
                ";".join("%s×%d" % (a, n) for a, n in c["daily_limits"]),
                "|".join(c["cooldowns"]),
                "Y" if c["mutates_money"] else "", "Y" if c["mutates_level"] else "",
            ])

    print("[ok] commands: %d, config fields: %d, plugin.py loc: %d" % (len(cmds), len(cfg), total_loc))
    for c in cmds:
        print("  %-22s %-24s %-12s L%-5d loc=%-4d aw=%-3d data=%s cfg=%s limit=%s" % (
            c["id"], c["handler"], c["domain"], c["lineno"], c["loc"], c["awaits"],
            ",".join(c["data_keys"]), ",".join(c["config_keys"]),
            ";".join("%s*%d" % (a, n) for a, n in c["daily_limits"])))
    print("[ok] wrote feature_map.json, handler_stats.csv")
    return model


if __name__ == "__main__":
    main()
