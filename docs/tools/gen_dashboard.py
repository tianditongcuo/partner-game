# -*- coding: utf-8 -*-
"""
partner-game 可视化面板生成器
==============================
读取 docs/feature_map.json，生成：
  docs/dashboard.html   自包含可视化面板（无 CDN / 无外部 JS，离线可看）
  docs/FEATURES.md      功能分类清单（Markdown，进仓库）

用法：
    python docs/tools/gen_maintenance_map.py    # 先扫描
    python docs/tools/gen_dashboard.py          # 再渲染
"""
from __future__ import annotations

import io
import json
import math
import os
import random
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DOCS = os.path.join(ROOT, "docs")

sys.path.insert(0, ROOT)
try:
    import realms as R
    import balance as B
    MAX_LEVEL = R.MAX_LEVEL
except Exception:                            # 插件损坏时不影响文档渲染
    R = None
    B = None
    MAX_LEVEL = 35

# 指令中文名（人工映射，比 pattern 好读）
CMD_LABEL = {
    "partner_game": "今日老婆",
    "partner_game_divorce": "离婚",
    "proposal_reply": "求婚应答",
    "marry": "娶",
    "force_marry": "强娶",
    "my_partner": "我的伴侣",
    "dump_partner": "甩掉",
    "rob_wife": "抢老婆",
    "rob_chance": "抢老婆胜率",
    "rob_money": "打劫",
    "rob_money_chance": "打劫胜率",
    "partner_game_help": "帮助",
    "work": "打工",
    "date": "约会",
    "cultivate": "修炼",
    "status": "我的状态",
    "transfer": "上交存款",
    "rank_power": "战力榜",
    "rank_money": "财富榜",
    "rank_affection": "好感榜",
    "admin_reset": "重置",
    "admin_compensate": "全服补偿",
    "admin_give_money": "发钱/扣钱",
    "game_info": "游戏机制",
}

DATA_LABEL = {
    "marriages": "marriages 婚姻表",
    "users": "users 用户表",
    "daily_usage": "daily_usage 限次表",
    "last_date": "last_date 日期戳",
}

DOMAIN_ORDER = ["router", "marriage", "economy", "cultivation", "combat",
                "penalty", "presentation", "persistence", "config", "admin"]

# ------------------------------------------------------------------ 领域文案
DOMAIN_DETAIL = {
    "router": [
        ("指令注册", "@Command 装饰器 × 24，pattern 为裸正则，部分未加 `$` 锚点", "plugin.py:397-1873"),
        ("上下文解析", "_extract_ctx 从 kwargs 里挖 group_id / sender_qq；_extract_at_qq 有 4 层兜底（含整串正则）", "plugin.py:44-114"),
        ("消息守卫", "_is_explicit_command 判断是否以 / 开头；_has_quote 判断是否回复消息", "plugin.py:116-146"),
        ("生命周期", "on_load 建 data 目录；on_unload 取消防抖任务并强存", "plugin.py:18-35"),
    ],
    "marriage": [
        ("随机抽取", "/今日老婆：置随机数种子后从群成员池抽人，并【立即绑定】，不经过对方同意", "plugin.py:397-535"),
        ("求婚", "/娶：发 @ 消息 + pending_proposals[msg_id] 内存态，60s 超时", "plugin.py:660-738"),
        ("求婚应答", "收到含「我同意/我拒绝」的消息时比对 pending_proposals", "plugin.py:587-658"),
        ("强制绑定", "/强娶：纯概率 40%，无战力参与", "plugin.py:740-836"),
        ("抢夺", "/抢老婆：带战力差与好感护盾的复合概率", "plugin.py:949-1082"),
        ("解绑", "/离婚（发起方）/甩掉（被绑定方），各自每日 1 次", "plugin.py:538-585, 889-947"),
        ("查询", "/我的伴侣：支持 @ 查他人", "plugin.py:838-887"),
    ],
    "economy": [
        ("初始与低保", "建号 1000；每日首次读取用户数据 +200（副作用藏在 getter 里）", "plugin.py:322-333"),
        ("劳动收入", "/打工：50~100 + 等级×10，每日 3 次", "plugin.py:1402-1429"),
        ("消费", "/约会 50/次（换好感）；/修炼 (大境界+1)×50/次", "plugin.py:1431-1478, 1480-1546"),
        ("转移", "/上交存款：双方余额各改一次，无手续费", "plugin.py:1584-1631"),
        ("罚款与赔偿", "失败罚款的 50% 转给对方，另 50% 凭空蒸发（隐形回收池）", "plugin.py:824-828, 1064-1068, 1272-1276"),
        ("管理员发放", "/发钱、/全服补偿：金额不设上限、不校验溢出", "plugin.py:1763-1835"),
    ],
    "cultivation": [
        ("等级空间", "0~99 共 100 档；25 大境界 × 4 小境界，已收口到 realms.py 单一数据源", "realms.py:29-34"),
        ("修炼消耗", "(大境界序号 + 1) × 50 金币，每日 3 次", "plugin.py:1499-1500"),
        ("突破判定", "小境界 80% 成功；大境界 40% 成功，失败再 30% 掉 1 级", "plugin.py:1512-1540"),
        ("战力换算", "power = level × (level//4 + 1)，非线性阶梯；4 处调用已统一走 realms.power()", "realms.py:112-115"),
        ("战斗掉级", "抢老婆失败且 level>0 时 20% 概率掉 1 级", "plugin.py:1072-1074"),
    ],
    "combat": [
        ("概率公式", "p = base + Δpower×系数 − (affection//20)×0.01，钳制在 10%~90%", "plugin.py:1030-1033"),
        ("强娶", "base 0.40；不参与战力/好感；钳制 0~1", "plugin.py:796-802"),
        ("抢老婆", "base 0.30；防守方取夫妻双方最高战力", "plugin.py:1015-1033"),
        ("打劫", "base 0.35；无好感护盾；附加资金门槛与低保户保护", "plugin.py:1236-1251"),
        ("胜率预测", "/抢老婆胜率、/打劫胜率：把公式拆项展示给玩家", "plugin.py:1084-1180, 1286-1350"),
        ("黑幕锁定", "forced_wives 名单内用户，三类犯罪概率强制归零", "plugin.py:799-800, 1027-1028, 1245-1246"),
    ],
    "penalty": [
        ("通用冷却", "_check_cooldown：key = 群_用户_指令，默认 60s，仅 9 条指令接入", "plugin.py:376-386"),
        ("每日次数", "_check_daily_limit：1 或 3 次/日，白名单可豁免抽取/离婚/甩人", "plugin.py:343-373"),
        ("失败自闭", "_set_penalty：用 last = now + penalty − cooldown 反推，封顶 60s", "plugin.py:388-394"),
        ("罚款", "三处内联：强娶 100~300 / 抢老婆 200~500 / 打劫 100~300", "见各 handler"),
        ("掉级", "修炼反噬、抢老婆被反杀，两处独立随机判定", "plugin.py:1529-1531, 1072-1074"),
    ],
    "presentation": [
        ("直发通道", "_send_napcat 绕过 MaiBot 文本链路直接调适配器发群消息", "plugin.py:177-194"),
        ("合并转发", "_send_forward_msg 发帮助/机制长文本，失败降级为普通消息", "plugin.py:204-227"),
        ("头像", "fetch_avatar_base64 拉 qlogo.cn 头像转 base64 内联，无缓存", "utils.py:16-36"),
        ("榜单", "/战力榜、/财富榜、/好感榜，逐条 _get_member_nick 查昵称", "plugin.py:1633-1717"),
        ("静态文案", "/帮助 与 /游戏机制 两份硬编码长文本，数值靠手写同步", "plugin.py:1362-1397, 1849-1873"),
    ],
    "persistence": [
        ("存储", "单 JSON：{marriages, users, daily_usage, last_date}，按群号分片", "utils.py:50-113"),
        ("写盘", "2 秒防抖 + 临时文件 os.replace 原子替换", "utils.py:81-104"),
        ("跨日", "purge_old 清空 daily_usage，并给所有婚姻 +5 好感", "plugin.py:348-355"),
        ("缺口", "无版本号、无迁移、无备份；data/ 未进 .gitignore", "—"),
    ],
    "config": [
        ("插件开关", "enabled / config_version", "config.py:8-19"),
        ("候选池", "exclude_self / exclude_sender / bot_qq", "config.py:24-38"),
        ("名单", "no_limit_users / admin_users / forced_wives", "config.py:39-48, 94-102"),
        ("概率", "force_marry / rob_wife / rob_money 三个 base", "config.py:74-88"),
        ("节奏", "cooldown_seconds / proposal_timeout_seconds / tz_offset_hours", "config.py:49-93"),
        ("展示", "send_avatar / avatar_size / persist_enabled", "config.py:54-73"),
    ],
    "admin": [
        ("权限模型", "仅 QQ 白名单 admin_users，不识别群主/管理员身份", "plugin.py:1728-1732"),
        ("重置", "/重置 @人：清婚姻 + 清抽取/离婚/甩人次数，保留战力财富", "plugin.py:1719-1761"),
        ("全服补偿", "/全服补偿 N：给本群所有在册用户 +N", "plugin.py:1763-1796"),
        ("定向发钱", "/发钱 /扣钱：支持负数，余额下限钳到 0", "plugin.py:1798-1835"),
    ],
}


# ------------------------------------------------------------------ 计算
def load():
    with io.open(os.path.join(DOCS, "feature_map.json"), "r", encoding="utf-8") as f:
        return json.load(f)


def domain_stats(m):
    st = {}
    for c in m["commands"]:
        d = st.setdefault(c["domain"], {"count": 0, "loc": 0})
        d["count"] += 1
        d["loc"] += c["loc"]
    return st


def config_usage(m):
    cnt = {}
    for c in m["commands"]:
        for k in c["config_keys"]:
            cnt[k] = cnt.get(k, 0) + 1
    return sorted(cnt.items(), key=lambda x: (-x[1], x[0]))


def trigger_of(c):
    names = re.findall(r"/([\u4e00-\u9fff]+)", c["pattern"] or "")
    return "/" + names[0] if names else ""


def simulate_cultivation(runs=20000, seed=7):
    """模拟从 0 级修到满级，统计期望尝试次数与花费。"""
    random.seed(seed)
    attempts, moneys = [], []
    for _ in range(runs):
        level, money, n = 0, 0, 0
        guard = 0
        while level < MAX_LEVEL and guard < 50000:
            guard += 1
            money += R.cultivate_cost(level) if R else (level // 4 + 1) * 50
            n += 1
            if level % 4 == 3:
                if random.random() < 0.4:
                    level += 1
                elif random.random() < 0.3 and level > 0:
                    level -= 1
            else:
                if random.random() < 0.8:
                    level += 1
        attempts.append(n)
        moneys.append(money)
    avg_a = sum(attempts) / float(len(attempts))
    avg_m = sum(moneys) / float(len(moneys))
    return {
        "attempts": avg_a,
        "money": avg_m,
        "days": avg_a / 3.0,
        "min_attempts": min(attempts),
        "max_attempts": max(attempts),
    }


def power(level):
    return R.power(level) if R else level * (level // 4 + 1)


def combat_curve(kind, affection=0):
    cfg = {
        "force_marry": (0.40, False, False),
        "rob_wife": (0.30, True, True),
        "rob_money": (0.35, True, False),
    }[kind]
    base, has_power, has_aff = cfg
    pts = []
    for dp in range(-330, 331, 10):
        p = base
        if has_power:
            p += R.power_win_bonus(dp) if R else dp * 0.005
        if has_aff:
            p -= (affection // 20) * 0.01
        lo, hi = (0.0, 1.0) if kind == "force_marry" else (0.10, 0.90)
        pts.append((dp, max(lo, min(hi, p))))
    return pts


# ------------------------------------------------------------------ SVG 图形
def esc(s):
    return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            .replace('"', "&quot;"))


SVG_STYLE = (
    '<style>'
    '.axis{fill:#64748b;font:11px Consolas,monospace}'
    '.grid{stroke:#1e293b;stroke-width:1}'
    '.grid.faint{stroke:#16233c}'
    '.zero{stroke:#475569;stroke-width:1.2;stroke-dasharray:4 4}'
    '.lg{fill:#cbd5e1;font:11.5px "Microsoft YaHei",sans-serif}'
    '</style>'
)


def render_chart(series, x_min, x_max, y_min, y_max, w=820, h=330,
                 x_label="", y_label="", x_fmt="{:.0f}", y_fmt="{:.0%}",
                 x_ticks=8, y_ticks=5, x_zero=None, embed_legend=False):
    """返回值是完整的、可独立嵌进 Markdown 的 <svg> 元素。"""
    ml, mr, mt, mb = 62, 20, 18, 46
    legend_h = (len(series) * 20 + 8) if embed_legend else 0
    H = h + legend_h
    pw, ph = w - ml - mr, h - mt - mb

    def px(x):
        return ml + (x - x_min) / float(x_max - x_min) * pw

    def py(y):
        return mt + ph - (y - y_min) / float(y_max - y_min) * ph

    out = ['<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 %d %d" width="%d" height="%d" '
           'class="chart" role="img">' % (w, H, w, H)]
    out.append('<rect width="100%" height="100%" fill="#0f172a" rx="10"/>')
    out.append(SVG_STYLE)
    for i in range(y_ticks + 1):
        yv = y_min + (y_max - y_min) * i / float(y_ticks)
        yy = py(yv)
        out.append('<line x1="%d" y1="%.1f" x2="%d" y2="%.1f" class="grid"/>' % (ml, yy, ml + pw, yy))
        out.append('<text x="%d" y="%.1f" class="axis" text-anchor="end">%s</text>'
                   % (ml - 8, yy + 4, esc(y_fmt.format(yv))))
    for i in range(x_ticks + 1):
        xv = x_min + (x_max - x_min) * i / float(x_ticks)
        xx = px(xv)
        out.append('<line x1="%.1f" y1="%d" x2="%.1f" y2="%d" class="grid faint"/>' % (xx, mt, xx, mt + ph))
        out.append('<text x="%.1f" y="%d" class="axis" text-anchor="middle">%s</text>'
                   % (xx, mt + ph + 20, esc(x_fmt.format(xv))))
    if x_zero is not None:
        out.append('<line x1="%.1f" y1="%d" x2="%.1f" y2="%d" class="zero"/>'
                   % (px(x_zero), mt, px(x_zero), mt + ph))
    out.append('<text x="%d" y="%d" class="axis">%s</text>'
               % (ml, h - 8, esc(x_label)))
    out.append('<text x="%d" y="%d" class="axis" text-anchor="end">%s</text>'
               % (w - mr, h - 8, esc(y_label)))
    for s in series:
        pts = " ".join("%.1f,%.1f" % (px(x), py(y)) for x, y in s["points"])
        dash = ' stroke-dasharray="6 4"' if s.get("dash") else ""
        out.append('<polyline points="%s" fill="none" stroke="%s" stroke-width="2.4" '
                   'stroke-linejoin="round"%s/>' % (pts, s["color"], dash))
    if embed_legend:
        for i, s in enumerate(series):
            yy = h + 12 + i * 20
            out.append('<line x1="%d" y1="%d" x2="%d" y2="%d" stroke="%s" stroke-width="2.6"%s/>'
                       % (ml, yy, ml + 20, yy, s["color"],
                          ' stroke-dasharray="6 4"' if s.get("dash") else ""))
            out.append('<text x="%d" y="%d" class="lg">%s</text>' % (ml + 28, yy + 4, esc(s["name"])))
    out.append("</svg>")
    return "".join(out)


def line_chart(series, x_min, x_max, y_min, y_max, **kw):
    """HTML 版：SVG + HTML 图例（图例样式跟随页面）。"""
    labels = kw.pop("x_label", "")
    y_label = kw.pop("y_label", "")
    svg = render_chart(series, x_min, x_max, y_min, y_max, embed_legend=False, **kw)
    leg = "".join('<span class="legend-item"><i style="background:%s"></i>%s</span>'
                  % (s["color"], esc(s["name"])) for s in series)
    return (svg + '<div class="legend">%s</div>'
            '<div class="axis-labels"><span>%s</span><span>%s</span></div>'
            % (leg, esc(labels), esc(y_label)))


def stacked_bar(rows, max_w=760):
    """rows: [(label, value, color, note)] 横向条形。"""
    if not rows:
        return ""
    vmax = max(r[1] for r in rows) or 1
    out = ['<div class="bars">']
    for label, value, color, note in rows:
        pct = value / float(vmax) * 100.0
        out.append(
            '<div class="bar-row"><span class="bar-label" title="%s">%s</span>'
            '<span class="bar-track"><span class="bar-fill" style="width:%.2f%%;background:%s"></span></span>'
            '<span class="bar-value">%s</span></div>' % (esc(note or label), esc(label), pct, color, esc(value)))
    out.append("</div>")
    return "".join(out)


# ------------------------------------------------------------------ 页面片段
def section_domains(m):
    st = domain_stats(m)
    cards = []
    for key in DOMAIN_ORDER:
        d = m["meta"]["domains"][key]
        s = st.get(key, {"count": 0, "loc": 0})
        cards.append(
            '<div class="domain-card" style="border-top:3px solid %s">'
            '<div class="dc-head"><span class="dot" style="background:%s"></span>'
            '<span class="dc-name">%s</span><span class="dc-count">%s</span></div>'
            '<div class="dc-desc">%s</div>'
            '<div class="dc-meta"><span>%s</span><span>%s</span></div></div>'
            % (d["color"], d["color"], esc(d["name"]),
               ("%d 指令" % s["count"]) if s["count"] else "横切关注",
               esc(d["desc"]), ("%d 行" % s["loc"]) if s["loc"] else "—", esc(key)))
    return '<div class="grid-3">%s</div>' % "".join(cards)


def section_matrix(m):
    cols = [k for k, _ in config_usage(m)[:11]]
    head = "".join('<th class="rot"><span>%s</span></th>' % esc(DATA_LABEL[k].split(" ")[0]) for k in m["data_keys"])
    head += "".join('<th class="rot"><span>%s</span></th>' % esc(c) for c in cols)

    rows = []
    for c in m["commands"]:
        cells = []
        for k in m["data_keys"]:
            lvl = 2 if k in c["data_direct"] else (1 if k in c["data_indirect"] else 0)
            cls = ["cell", "cell-%d" % lvl]
            title = "%s：%s" % (k, "直读" if lvl == 2 else ("间接" if lvl == 1 else "无"))
            cells.append('<td class="%s" title="%s"></td>' % (" ".join(cls), esc(title)))
        for k in cols:
            on = k in c["config_keys"]
            cells.append('<td class="cell %s" title="%s%s"></td>'
                         % ("cell-cfg" if on else "cell-0", esc(k), "（已使用）" if on else ""))
        rows.append(
            '<tr><td class="cmd"><span class="cname">%s</span>'
            '<span class="cid">%s</span></td>%s</tr>'
            % (esc(CMD_LABEL.get(c["id"], c["id"])), esc(c["id"]), "".join(cells)))

    return (
        '<div class="heat-wrap"><table class="heat">'
        '<thead><tr><th class="corner">指令 \\ 依赖</th>%s</tr></thead>'
        '<tbody>%s</tbody></table></div>'
        '<p class="note">深色 = 直接读写 <code>_store.data</code>；浅色 = 通过 '
        '<code>_get_user_data / _get_user_marriage / _check_daily_limit</code> 间接读写；'
        '最右一组 = 该指令读取的配置项。这张图就是重构时要 拆掉的耦合面。</p>'
        % (head, "".join(rows)))


def section_commands(m):
    rows = []
    for c in m["commands"]:
        d = m["meta"]["domains"][c["domain"]]
        limits = "、".join("%s×%d" % (a, n) for a, n in c["daily_limits"]) or "—"
        rows.append(
            '<tr data-domain="%s" data-text="%s">'
            '<td><code>%s</code></td><td class="nw">%s</td>'
            '<td><span class="tag" style="background:%s22;color:%s;border-color:%s55">%s</span></td>'
            '<td class="num">%d</td><td class="num">%d</td><td class="num">%d</td>'
            '<td>%s</td><td>%s</td><td class="num">%s</td></tr>'
            % (c["domain"],
               esc("%s %s %s" % (c["id"], CMD_LABEL.get(c["id"], ""), " ".join(c["data_keys"]))),
               esc(c["id"]), esc(CMD_LABEL.get(c["id"], c["id"])),
               d["color"], d["color"], d["color"], esc(d["name"]),
               c["code_lineno"], c["loc"], c["awaits"],
               esc("、".join(c["data_keys"]) or "—"),
               esc("、".join(c["config_keys"][:4]) + ("…" if len(c["config_keys"]) > 4 else "")),
               esc(limits)))
    head = ("<tr><th>指令 ID</th><th>玩法</th><th>功能域</th><th>起始行</th>"
            "<th>行数</th><th>await</th><th>数据表</th><th>配置项</th><th>每日次数</th></tr>")
    return ('<div class="filter-bar"><input id="cmd-filter" placeholder="过滤：输入指令名 / 功能域 / 数据表…" '
            'oninput="filterRows()"><span id="filter-count"></span></div>'
            '<div class="table-wrap"><table class="tbl" id="cmd-table"><thead>%s</thead><tbody>%s</tbody></table></div>'
            % (head, "".join(rows)))


def section_arch(m):
    direct_writers = [c for c in m["commands"] if c["data_direct"]]
    api = m.get("module_api") or sorted(set(a for c in m["commands"] for a in c["api_calls"]))
    n = len(m["commands"])
    W, H = 900, 520

    def box(x, y, ww, hh, label, color, sub="", fs="bx"):
        s = ('<rect x="%d" y="%d" width="%d" height="%d" rx="8" fill="%s22" stroke="%s" stroke-width="1.4"/>'
             % (x, y, ww, hh, color, color))
        if sub:
            s += ('<text x="%d" y="%d" class="%s" text-anchor="middle">%s</text>'
                  '<text x="%d" y="%d" class="bxs" text-anchor="middle">%s</text>'
                  % (x + ww // 2, y + hh // 2 - 4, fs, esc(label),
                     x + ww // 2, y + hh // 2 + 13, esc(sub)))
        else:
            s += ('<text x="%d" y="%d" class="%s" text-anchor="middle">%s</text>'
                  % (x + ww // 2, y + hh // 2 + 4, fs, esc(label)))
        return s

    out = ['<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 %d %d" class="chart arch">' % (W, H)]
    out.append('<rect width="100%" height="100%" fill="#0f172a" rx="10"/>')

    # ① 穿层红线先画（之后被盒子盖住 → 视觉上“从领域层背后穿过”）
    xs = [110, 250, 390, 530, 670, 810]
    for x in xs:
        out.append('<line x1="%d" y1="104" x2="%d" y2="262" stroke="#ef4444" stroke-width="1.5" '
                   'stroke-dasharray="5 5" opacity="0.5"/>' % (x, x))

    out.append('<text x="14" y="24" class="lane">① 命令层 · %d 个 @Command handler</text>' % n)
    out.append(box(14, 40, 872, 62, "handle_* × " + str(n), "#6366f1",
                   "路由 + 业务逻辑 + 文案 + 数值计算，全部挤在 plugin.py 里"))
    out.append('<text x="14" y="142" class="lane">② 领域层 · 仅 6 个零散私有方法，没有真正的服务对象</text>')
    for i, name in enumerate(["_get_user_data", "_get_user_marriage", "_check_daily_limit",
                              "_check_cooldown", "_set_penalty", "_get_member_nick"]):
        out.append(box(14 + i * 146, 158, 136, 40, name, "#8b5cf6"))
    out.append('<text x="14" y="252" class="lane">③ 存储层 · PersistStore.data（4 张表，无事务、无锁、无迁移）</text>')
    for i, k in enumerate(m["data_keys"]):
        out.append(box(14 + i * 220, 268, 204, 44, k, "#64748b"))
    out.append('<text x="14" y="360" class="lane">④ 适配器层 · ctx.api.call（%d 个接口，全部调用点都在发送/查询封装里）</text>' % len(api))
    for i, a in enumerate(api[:6]):
        short = a.replace("adapter.napcat.adapter.", "").replace("adapter.napcat.", "")
        out.append(box(14 + (i % 3) * 296, 376 + (i // 3) * 62, 280, 44, short[:34], "#0ea5e9"))
    out.append('<text x="600" y="232" class="warn">↑ 红线：%d/%d 个指令越过领域层直写存储</text>'
               % (len(direct_writers), n))
    out.append("</svg>")
    return "".join(out) + (
        '<p class="note">这张图就是重构的第一动机：理想分层里，命令层只该「解析参数 → 调领域服务 → 渲染文案」，'
        '而现实中 <b>%d/%d 个指令直接读写 <code>_store.data</code></b>，'
        '于是「改一个数值」必须通读 24 个 handler。红色虚线表示这些穿层调用。</p>'
        % (len(direct_writers), n))


def section_economy(m):
    eco = m["economy"]
    src = [e for e in eco if e[1] in ("source", "transfer")]
    snk = [e for e in eco if e[1] == "sink"]

    def rows(items, color, flow_label):
        out = []
        for name, typ, amount, trigger, loc in items:
            tag = "转移" if typ == "transfer" else flow_label
            out.append(
                '<div class="flow-item"><span class="fi-bar" style="background:%s"></span>'
                '<div><div class="fi-name">%s<em>%s</em></div>'
                '<div class="fi-amt">%s</div><div class="fi-src">%s · <code>%s</code></div></div></div>'
                % (color, esc(name), tag, esc(amount), esc(trigger), esc(loc)))
        return "".join(out)

    return (
        '<div class="flow">'
        '<div class="flow-col"><h4 class="in">▼ 流入 / 转移</h4>%s</div>'
        '<div class="flow-mid"><div class="wallet">users[群][QQ]<br><b>money</b></div>'
        '<div class="flow-hint">所有金币读写都是<br>就地改这一个整数<br>（无流水、无事务）</div></div>'
        '<div class="flow-col"><h4 class="out">▲ 流出 / 回收</h4>%s</div>'
        '</div>'
        '<div class="callout"><b>三个结论：</b><br>'
        '1) 罚款的一半凭空消失，这是当前唯一的“货币回收池”，也是唯一抑制通胀的机制；<br>'
        '2) 打工收入线性增长（<b>+30 金币/级/天</b>），修炼支出是阶梯（每 4 级跳 <b>+150/天</b>）：'
        f'两者从 <b>{_crossover()[0]} 级</b>起交叉，<b>{_crossover()[1]} 级起修炼彻底跑赢收入</b>；<br>'
        '3) 全程没有任何流水记录，出问题只能翻 JSON 猜——这条决定将来「财富体系」必须补一个 ledger。</div>'
        % (rows(src, "#22c55e", "流入"), rows(snk, "#ef4444", "流出")))


def section_probability(m):
    s1 = {"name": "强娶（base 40%，无战力/好感）", "color": "#f59e0b", "points": combat_curve("force_marry")}
    s2 = {"name": "抢老婆（base 30%，好感 0）", "color": "#ec4899", "points": combat_curve("rob_wife", 0)}
    s3 = {"name": "抢老婆（好感 500，护盾 −25%）", "color": "#ec4899", "points": combat_curve("rob_wife", 500), "dash": True}
    s4 = {"name": "打劫（base 35%，无好感护盾）", "color": "#ef4444", "points": combat_curve("rob_money")}
    chart = line_chart([s1, s2, s3, s4], -330, 330, 0.0, 1.0,
                       x_label="战力差 Δpower（进攻方 − 防守方最高战力）",
                       y_label="成功概率", y_fmt="{:.0%}", x_zero=0)
    return chart + (
        '<p class="note">战力量级：满级 ' + str(MAX_LEVEL) + ' 级 power = '
        + str((R.power(MAX_LEVEL) if R else 315)) + '，所以完整战力差全部落在图上。'
        '每 1 点战力差 = ' + (R.rate_percent() if R else "0.5%")
        + ' 胜率（36 档原版为 0.5%，已按境界扩容等比例换算）；好感每 20 点 = −1%。'
        '注意 <b>强娶的钳制区间是 0%~100%</b>（不参与战力），而抢夺/打劫被强制锁在 10%~90%，'
        '这是三条公式里唯一的结构性差异。</p>'
        '<p class="note">注：横轴只画了 ±330 的过渡区；满级最大战力差可达 '
        + str((R.power(MAX_LEVEL) if R else 315)) + '，超过约 ±240 后曲线即被 10%/90% 钳制。'
        '</p>')


def _crossover(first_only=False):
    """修炼日支出 vs 打工日收入 的交叉点。"""
    cost = lambda l: 3 * (R.cultivate_cost(l) if R else (l // 4 + 1) * 50)
    inc = lambda l: 3 * (75 + 10 * l)
    exceed = [l for l in range(MAX_LEVEL + 1) if cost(l) > inc(l)]
    first = exceed[0] if exceed else None
    perm = None
    for l in range(MAX_LEVEL + 1):
        if all(cost(k) > inc(k) for k in range(l, MAX_LEVEL + 1)):
            perm = l
            break
    return first, perm


def section_cultivation(m, sim):
    lv = list(range(0, MAX_LEVEL + 1))
    cost_pts = [(l, 3 * (R.cultivate_cost(l) if R else (l // 4 + 1) * 50)) for l in lv]
    inc_pts = [(l, 3 * (75 + 10 * l)) for l in lv]                  # 3 次/天的打工收入（取期望 75）
    s1 = {"name": "修炼日支出（3 次）", "color": "#ef4444", "points": cost_pts}
    s2 = {"name": "打工日收入（3 次，期望）", "color": "#22c55e", "points": inc_pts}
    ymax = max(p[1] for p in cost_pts + inc_pts) * 1.12
    chart = line_chart([s1, s2], 0, MAX_LEVEL, 0, ymax, x_label="境界等级", y_label="金币 / 天",
                       y_fmt="{:,.0f}", x_fmt="{:.0f}")
    cards = (
        '<div class="stats">'
        '<div class="stat"><span class="sv">%s</span><span class="sl">期望修炼次数（0 → %s）</span></div>'
        '<div class="stat"><span class="sv">%s</span><span class="sl">期望总花费（金币）</span></div>'
        '<div class="stat"><span class="sv">%s</span><span class="sl">纯靠修炼的期望天数（3 次/天）</span></div>'
        '<div class="stat"><span class="sv">%d–%d</span><span class="sl">2 万次模拟的波动区间</span></div>'
        '</div>'
        % ("{:.0f}".format(sim["attempts"]), (R.realm_name(R.MAX_LEVEL) if R else "满级"),
           "{:,.0f}".format(sim["money"]),
           "{:.0f}".format(sim["days"]), sim["min_attempts"], sim["max_attempts"]))
    first, perm = _crossover()
    return chart + (
        '<p class="note">支出是<b>阶梯</b>（每 4 级跳 150 金币/天），收入是<b>直线</b>（+30 金币/级/天），'
        f'两条线从 <b>{first} 级</b>起首次交叉，<b>{perm} 级之后持续入不敷出</b>：'
        '此后每天 3 次修炼已经养不起，必须靠打劫 / 罚款赔偿 / 管理员发钱续命。'
        '做「修炼体系」扩展时，这个交叉点就是数值平衡的基准线。</p>') + cards


def section_penalty(m):
    rows = "".join(
        '<tr><td><b>%s</b></td><td>%s</td><td>%s</td><td>%s</td><td><code>%s</code></td></tr>'
        % (esc(p[0]), esc(p[1]), esc(p[2]), esc(p[3]), esc(p[4]))
        for p in m["penalties"])
    return ('<div class="table-wrap"><table class="tbl"><thead><tr>'
            '<th>惩罚类型</th><th>强度</th><th>触发条件</th><th>覆盖指令</th><th>代码位置</th>'
            '</tr></thead><tbody>%s</tbody></table></div>' % rows)


def section_hotspots(m):
    rows = sorted(m["commands"], key=lambda c: -c["loc"])
    bars = []
    for c in rows:
        d = m["meta"]["domains"][c["domain"]]
        bars.append((CMD_LABEL.get(c["id"], c["id"]), c["loc"], d["color"],
                     "%s / %s（%d 行，%d 个 await）" % (c["id"], CMD_LABEL.get(c["id"], ""), c["loc"], c["awaits"])))
    return stacked_bar(bars) + (
        '<p class="note">行数前 5 的 handler 合计占 plugin.py 的 %.0f%%，'
        '重构时应优先按“单一职责”切开：一个 handler 只做「解析参数 → 调领域服务 → 渲染文案」。</p>'
        % (sum(b[1] for b in bars[:5]) * 100.0 / m["meta"]["plugin_py_loc"]))


def section_newfeatures(m):
    cards = []
    for name, domain, current, advice in m["new_features"]:
        color = m["meta"]["domains"].get(domain, {}).get("color", "#94a3b8") if domain in m["meta"]["domains"] else "#94a3b8"
        dname = m["meta"]["domains"].get(domain, {}).get("name", "全新（无既有代码）") if domain in m["meta"]["domains"] else "全新（无既有代码）"
        cards.append(
            '<div class="nf-card" style="border-left:4px solid %s">'
            '<div class="nf-head">%s<span class="nf-domain" style="color:%s">%s</span></div>'
            '<div class="nf-body"><p class="nf-l"><b>现状</b>%s</p><p class="nf-l"><b>建议</b>%s</p></div></div>'
            % (color, esc(name), color, esc(dname), esc(current), esc(advice)))
    return '<div class="grid-2">%s</div>' % "".join(cards)


def section_config(m):
    rows = "".join(
        '<tr><td><code>partner_game.%s</code></td><td>%s</td><td>%s</td><td class="num">%d</td></tr>'
        % (esc(f["name"]), esc(f["label"] or "—"),
           esc(json.dumps(f["default"], ensure_ascii=False) if not isinstance(f["default"], list) else "[]"),
           dict(config_usage(m)).get(f["name"], 0))
        for f in m["config"])
    return ('<div class="table-wrap"><table class="tbl"><thead><tr>'
            '<th>配置项</th><th>UI 标签</th><th>默认值</th><th>被多少指令读取</th>'
            '</tr></thead><tbody>%s</tbody></table></div>' % rows)


# ------------------------------------------------------------------ 组装
CSS = """
*{box-sizing:border-box}
body{margin:0;background:#0b1120;color:#e2e8f0;font:14px/1.65 "Microsoft YaHei","PingFang SC","Segoe UI",sans-serif}
header{padding:28px 32px 18px;background:linear-gradient(135deg,#111c33,#0b1120 60%);border-bottom:1px solid #1e293b}
h1{margin:0 0 6px;font-size:24px;letter-spacing:.5px}
.sub{color:#94a3b8;font-size:13px}
.chips{margin-top:14px;display:flex;flex-wrap:wrap;gap:8px}
.chip{background:#1e293b;border:1px solid #334155;border-radius:999px;padding:4px 12px;font-size:12px;color:#cbd5e1}
.chip b{color:#fff}
nav{position:sticky;top:0;z-index:9;display:flex;flex-wrap:wrap;gap:4px;padding:10px 24px;background:#0b1120ee;border-bottom:1px solid #1e293b;backdrop-filter:blur(6px)}
nav button{background:transparent;border:1px solid transparent;color:#94a3b8;padding:6px 12px;border-radius:8px;cursor:pointer;font-size:13px}
nav button:hover{background:#1e293b;color:#e2e8f0}
nav button.on{background:#1d4ed8;color:#fff;border-color:#3b82f6}
main{padding:24px 32px 80px;max-width:1180px;margin:0 auto}
section{display:none;animation:fade .25s ease}
section.on{display:block}
@keyframes fade{from{opacity:0;transform:translateY(4px)}to{opacity:1;transform:none}}
h2{font-size:18px;margin:8px 0 4px;padding-left:10px;border-left:4px solid #3b82f6}
.lede{color:#94a3b8;margin:0 0 18px;font-size:13px}
.grid-3{display:grid;grid-template-columns:repeat(auto-fill,minmax(260px,1fr));gap:12px}
.grid-2{display:grid;grid-template-columns:repeat(auto-fill,minmax(380px,1fr));gap:12px}
.domain-card{background:#111c33;border:1px solid #1e293b;border-radius:10px;padding:12px 14px}
.dc-head{display:flex;align-items:center;gap:8px;margin-bottom:6px}
.dot{width:9px;height:9px;border-radius:50%}
.dc-name{font-weight:700;font-size:15px}
.dc-count{margin-left:auto;font-size:11px;color:#94a3b8;background:#1e293b;padding:1px 8px;border-radius:999px}
.dc-desc{color:#94a3b8;font-size:12px;min-height:34px}
.dc-meta{display:flex;gap:12px;margin-top:8px;font-size:11px;color:#64748b}
.heat-wrap{overflow:auto;border:1px solid #1e293b;border-radius:10px;padding:6px;background:#0f172a}
table.heat{border-collapse:separate;border-spacing:2px;font-size:11px}
table.heat th{font-weight:500;color:#94a3b8;padding:2px 4px;white-space:nowrap}
table.heat th.rot{height:96px;vertical-align:bottom;padding:0}
table.heat th.rot span{writing-mode:vertical-rl;transform:rotate(180deg);display:inline-block;white-space:nowrap}
table.heat th.corner{text-align:left;padding-left:8px;min-width:150px}
td.cell{width:17px;height:17px;border-radius:3px;background:#0b1120;border:1px solid #16233c}
td.cell-1{background:rgba(99,102,241,.35);border-color:rgba(99,102,241,.4)}
td.cell-2{background:rgba(99,102,241,.9);border-color:rgba(129,140,248,.9)}
td.cell-cfg{background:rgba(16,185,129,.55);border-color:rgba(16,185,129,.6)}
td.cell-0{background:#0b1120}
td.cmd{white-space:nowrap;padding:0 8px;border-right:1px solid #1e293b}
td.cmd .cname{display:inline-block;min-width:64px;color:#e2e8f0}
td.cmd .cid{color:#475569;font-size:10px;margin-left:6px;font-family:Consolas,monospace}
.table-wrap{overflow:auto;border:1px solid #1e293b;border-radius:10px}
table.tbl{width:100%;border-collapse:collapse;font-size:12.5px}
table.tbl th{background:#111c33;color:#94a3b8;font-weight:600;text-align:left;padding:9px 12px;position:sticky;top:0;border-bottom:1px solid #1e293b;white-space:nowrap}
table.tbl td{padding:8px 12px;border-bottom:1px solid #16233c;vertical-align:top}
table.tbl tr:hover td{background:#111c33}
table.tbl td.num{text-align:right;font-variant-numeric:tabular-nums;color:#cbd5e1}
code{font-family:Consolas,"Courier New",monospace;font-size:11.5px;color:#7dd3fc;background:#0f1a2e;padding:1px 5px;border-radius:4px}
.tag{display:inline-block;border:1px solid;border-radius:999px;padding:1px 9px;font-size:11px;white-space:nowrap}
.filter-bar{display:flex;gap:10px;align-items:center;margin-bottom:10px}
.filter-bar input{flex:1;background:#111c33;border:1px solid #334155;border-radius:8px;padding:8px 12px;color:#e2e8f0;font-size:13px;outline:none}
.filter-bar input:focus{border-color:#3b82f6}
#filter-count{font-size:12px;color:#64748b}
.chart{width:100%;height:auto;background:#0f172a;border:1px solid #1e293b;border-radius:10px}
svg .grid{stroke:#1e293b;stroke-width:1}
svg .grid.faint{stroke:#16233c}
svg .zero{stroke:#475569;stroke-width:1.2;stroke-dasharray:4 4}
svg .axis{fill:#64748b;font-size:11px;font-family:Consolas,monospace}
svg .bx{fill:#e2e8f0;font-size:12px;font-weight:600}
svg .bxs{fill:#94a3b8;font-size:10px}
svg .lane{fill:#64748b;font-size:11.5px;font-weight:600}
svg .warn{fill:#ef4444;font-size:11px;font-weight:600}
.legend{display:flex;flex-wrap:wrap;gap:16px;margin:8px 2px 0;font-size:12px;color:#94a3b8}
.legend-item{display:flex;align-items:center;gap:6px}
.legend-item i{width:14px;height:3px;border-radius:2px;display:inline-block}
.axis-labels{display:flex;justify-content:space-between;font-size:11px;color:#475569;margin-top:2px}
.note{color:#94a3b8;font-size:12.5px;line-height:1.7;margin-top:12px}
.note b{color:#e2e8f0}
.stats{display:grid;grid-template-columns:repeat(auto-fill,minmax(200px,1fr));gap:10px;margin-top:14px}
.stat{background:#111c33;border:1px solid #1e293b;border-radius:10px;padding:12px 14px;display:flex;flex-direction:column;gap:2px}
.sv{font-size:20px;font-weight:700;color:#fff}
.sl{font-size:11.5px;color:#94a3b8}
.flow{display:grid;grid-template-columns:1fr 180px 1fr;gap:14px;align-items:start}
.flow-col{display:flex;flex-direction:column;gap:8px}
.flow-col h4{margin:0 0 4px;font-size:12px;letter-spacing:1px}
.flow-col h4.in{color:#22c55e}
.flow-col h4.out{color:#ef4444}
.flow-item{display:flex;gap:10px;background:#111c33;border:1px solid #1e293b;border-radius:8px;padding:9px 12px}
.fi-bar{width:3px;border-radius:2px;flex:none}
.fi-name{font-size:13px;font-weight:600}
.fi-name em{font-style:normal;font-size:10px;color:#64748b;border:1px solid #334155;border-radius:4px;padding:0 5px;margin-left:6px}
.fi-amt{color:#fbbf24;font-size:12px;font-family:Consolas,monospace}
.fi-src{color:#64748b;font-size:11px}
.flow-mid{display:flex;flex-direction:column;align-items:center;gap:8px;padding-top:26px}
.wallet{width:100%;text-align:center;background:linear-gradient(135deg,#1d4ed8,#6d28d9);border-radius:10px;padding:14px 8px;font-size:11px;color:#dbeafe;box-shadow:0 0 0 1px #3b82f633}
.wallet b{font-size:15px;color:#fff;letter-spacing:1px}
.flow-hint{font-size:10.5px;color:#64748b;text-align:center;line-height:1.5}
.callout{margin-top:16px;background:#111c33;border:1px solid #334155;border-left:4px solid #f59e0b;border-radius:8px;padding:12px 14px;font-size:12.5px;color:#cbd5e1}
.nf-card{background:#111c33;border:1px solid #1e293b;border-radius:10px;padding:14px}
.nf-head{font-size:15px;font-weight:700;margin-bottom:8px;display:flex;gap:10px;align-items:baseline}
.nf-domain{font-size:11px;font-weight:500}
.nf-l{font-size:12.5px;color:#cbd5e1;margin:10px 0 0;line-height:1.6}
.nf-l b{display:block;color:#94a3b8;font-weight:600;font-size:11px;letter-spacing:1px;margin-bottom:2px}
.bars{display:flex;flex-direction:column;gap:6px}
.nw{white-space:nowrap}
.bar-row{display:flex;align-items:center;gap:10px;font-size:12px}
.bar-label{width:110px;text-align:right;color:#cbd5e1;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.bar-track{flex:1;height:14px;background:#111c33;border-radius:4px;overflow:hidden;border:1px solid #1e293b}
.bar-fill{display:block;height:100%;border-radius:3px;opacity:.85}
.bar-value{width:56px;text-align:right;color:#94a3b8;font-variant-numeric:tabular-nums;font-family:Consolas,monospace}
footer{color:#475569;font-size:11.5px;text-align:center;padding:24px}
@media print{section{display:block!important}nav{display:none}}
"""

JS = """
var tabs=document.querySelectorAll('nav button');
var secs=document.querySelectorAll('section');
tabs.forEach(function(b){b.onclick=function(){
  tabs.forEach(function(x){x.classList.remove('on')});
  secs.forEach(function(s){s.classList.remove('on')});
  b.classList.add('on');
  document.getElementById(b.dataset.target).classList.add('on');
  window.scrollTo(0,0);
}});
function filterRows(){
  var q=(document.getElementById('cmd-filter').value||'').toLowerCase();
  var rows=document.querySelectorAll('#cmd-table tbody tr');
  var n=0;
  rows.forEach(function(r){
    var hit=!q||r.dataset.text.toLowerCase().indexOf(q)>=0||r.dataset.domain.indexOf(q)>=0;
    r.style.display=hit?'':'none'; if(hit)n++;
  });
  document.getElementById('filter-count').textContent=q?('命中 '+n+' / '+rows.length):'';
}
"""


# ============================================================ 数值总览
BALANCE_META = [
    ("周期", "CYCLE_HOURS", "一个周期的时长（小时）。改这里 = 所有次数限制、低保、跨周期好感的节奏一起变"),
    ("经济", "INITIAL_MONEY", "新用户初始金币"),
    ("经济", "CYCLE_ALLOWANCE", "每周期首次互动发放的低保"),
    ("经济", "MARRIAGE_AFFECTION_PER_CYCLE", "跨周期时，存续中的婚姻自动增加的好感"),
    ("次数", "DRAW_LIMIT", "/今日老婆 每周期次数"),
    ("次数", "DIVORCE_LIMIT", "/离婚 每周期次数"),
    ("次数", "DUMP_LIMIT", "/甩掉 每周期次数"),
    ("次数", "WORK_LIMIT", "/打工 每周期次数"),
    ("次数", "DATE_LIMIT", "/约会 每周期次数"),
    ("次数", "CULTIVATE_LIMIT", "/修炼 每周期次数"),
    ("次数", "ROB_MONEY_LIMIT", "/打劫 每周期次数"),
    ("打工", "WORK_EARN_MIN", "基础收入下限"),
    ("打工", "WORK_EARN_MAX", "基础收入上限"),
    ("打工", "WORK_LEVEL_BONUS", "每级境界的额外收入"),
    ("约会", "DATE_COST", "每次约会消耗金币"),
    ("约会", "DATE_AFF_MIN", "好感增加下限"),
    ("约会", "DATE_AFF_MAX", "好感增加上限"),
    ("修炼", "CULTIVATE_COST_BASE", "费用系数：(大境界序号+1) × 本值"),
    ("修炼", "MINOR_SUCCESS_RATE", "小境界突破成功率"),
    ("修炼", "MAJOR_SUCCESS_RATE", "大境界突破成功率"),
    ("修炼", "MAJOR_FAIL_DROP_RATE", "大境界失败后走火入魔（掉 1 级）的概率"),
    ("好感", "AFFECTION_PER_SHIELD", "每多少点好感抵消一档胜率"),
    ("好感", "AFFECTION_SHIELD_RATE", "每档抵消的胜率"),
    ("强娶", "FORCE_GATE", "发起所需金币门槛"),
    ("强娶", "FORCE_FINE_MIN", "失败罚款下限"),
    ("强娶", "FORCE_FINE_MAX", "失败罚款上限"),
    ("强娶", "FORCE_FLOOR", "胜率钳制下限（强娶不参与战力）"),
    ("强娶", "FORCE_CAP", "胜率钳制上限"),
    ("抢老婆", "ROB_WIFE_GATE", "发起所需金币门槛"),
    ("抢老婆", "ROB_WIFE_FINE_MIN", "失败罚款下限"),
    ("抢老婆", "ROB_WIFE_FINE_MAX", "失败罚款上限"),
    ("抢老婆", "ROB_WIFE_DROP_CHANCE", "失败后被反杀掉级的概率"),
    ("打劫", "ROB_MONEY_GATE", "发起所需金币门槛"),
    ("打劫", "ROB_MONEY_FINE_MIN", "失败罚款下限"),
    ("打劫", "ROB_MONEY_FINE_MAX", "失败罚款上限"),
    ("打劫", "ROB_MONEY_POOR_PROTECT", "目标资产低于此值不可被打劫"),
    ("打劫", "ROB_MONEY_RATIO_MIN", "抢走目标资产的比例下限"),
    ("打劫", "ROB_MONEY_RATIO_MAX", "抢走目标资产的比例上限"),
    ("打劫", "ROB_MONEY_STEAL_MIN", "单次劫掠金额下限"),
    ("打劫", "ROB_MONEY_STEAL_CAP", "单次劫掠金额上限"),
    ("共用", "ROB_FLOOR", "抢夺/打劫的胜率钳制下限"),
    ("共用", "ROB_CAP", "抢夺/打劫的胜率钳制上限"),
    ("共用", "FINE_COMPENSATION_RATIO", "罚款中赔付给对手的比例（其余蒸发）"),
    ("共用", "FAIL_AUTISM_SECONDS", "失败后的强制自闭时长（秒）"),
    ("共用", "MAX_PENALTY_SECONDS", "自闭时长硬上限（秒）"),
]


def _fmt_value(v):
    if isinstance(v, bool):
        return "开" if v else "关"
    if isinstance(v, float):
        if 0 < abs(v) <= 1:
            return "%s（%s%%）" % (v, ("%.4g" % (v * 100)))
        return str(v)
    return str(v)


def section_balance(m):
    if not B:
        return "<p>未能导入 balance.py</p>"
    rows = []
    last_group = None
    for group, name, desc in BALANCE_META:
        if not hasattr(B, name):
            continue
        val = getattr(B, name)
        g = '<b style="color:#e2e8f0">%s</b>' % esc(group) if group != last_group else ""
        last_group = group
        rows.append(
            "<tr><td>%s</td><td><code>%s</code></td><td class=\"num\">%s</td><td>%s</td></tr>"
            % (g, esc(name), esc(_fmt_value(val)), esc(desc)))
    head = "<tr><th>分组</th><th>常量</th><th>当前值</th><th>说明</th></tr>"
    cycle_hint = ""
    if B:
        cycle_hint = ('<div class="callout"><b>周期时长</b>：当前 <code>CYCLE_HOURS = %s</code> 小时。'
                      '改成 12 就是半天一轮、168 就是一周一轮；所有「每周期次数」、低保、'
                      '跨周期好感都自动跟随，无需改别处。</div>' % B.CYCLE_HOURS)
    return ('<div class="table-wrap"><table class="tbl">%s<tbody>%s</tbody></table></div>%s'
            % (head, "".join(rows), cycle_hint))


# ============================================================ 概率热力图
def _prob(kind, atk, dfd, affection=0, base=0.0):
    p = base
    if kind != "force":
        p += (R.power(atk) - R.power(dfd)) * R.POWER_RATE_PER_POINT
        p -= B.affection_shield(affection)
    if kind == "force":
        return max(B.FORCE_FLOOR, min(B.FORCE_CAP, p))
    return max(B.ROB_FLOOR, min(B.ROB_CAP, p))


def heatmap_svg(matrix, row_labels, col_labels, title, w=880, h=460):
    """matrix[row][col]，行=防守方起点，列=进攻方。"""
    n_r, n_c = len(matrix), len(matrix[0])
    ml, mr, mt, mb = 96, 18, 34, 52
    pw, ph = w - ml - mr, h - mt - mb
    cw, ch = pw / float(n_c), ph / float(n_r)
    out = ['<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 %d %d" class="chart" role="img">' % (w, h)]
    out.append('<rect width="100%" height="100%" fill="#0f172a" rx="10"/>')
    out.append('<text x="%d" y="20" class="bxs" text-anchor="middle">%s</text>' % (ml + pw // 2, esc(title)))
    for r in range(n_r):
        for c in range(n_c):
            v = matrix[r][c]
            hue = int(0 + 140 * v)
            out.append('<rect x="%.1f" y="%.1f" width="%.1f" height="%.1f" fill="hsl(%d,62%%,%d%%)" opacity="0.92"/>'
                       % (ml + c * cw, mt + r * ch, cw + 0.5, ch + 0.5, hue, 38 + int(14 * (1 - v))))
    # 坐标轴刻度
    for c in range(0, n_c, max(1, n_c // 10)):
        out.append('<text x="%.1f" y="%d" class="axis" text-anchor="middle">%s</text>'
                   % (ml + c * cw + cw / 2, mt + ph + 16, esc(col_labels[c])))
    for r in range(0, n_r, max(1, n_r // 10)):
        out.append('<text x="%d" y="%.1f" class="axis" text-anchor="end">%s</text>'
                   % (ml - 8, mt + r * ch + ch / 2 + 4, esc(row_labels[r])))
    out.append('<text x="%d" y="%d" class="axis">进攻方境界 →</text>' % (ml, h - 12))
    out.append('<text x="%d" y="%d" class="axis">↑ 防守方境界</text>' % (6, mt - 8))
    out.append("</svg>")
    return "".join(out)


def _grid(kind, base, affection=0, step=5):
    levels = list(range(0, MAX_LEVEL + 1, step))
    if levels[-1] != MAX_LEVEL:
        levels.append(MAX_LEVEL)
    matrix = []
    for d in levels:
        row = []
        for a in levels:
            row.append(_prob(kind, a, d, affection, base))
        matrix.append(row)
    labels = [(R.realm_name(l) if R else str(l)) for l in levels]
    short = [n[:2] for n in labels]
    return levels, matrix, short


def section_probability_grid(m):
    if not (R and B):
        return "<p>缺少 realms/balance，无法绘制</p>"
    cfg = {c["name"]: c["default"] for c in m["config"]}
    p_force = float(cfg.get("force_marry_probability") or 0.4)
    p_wife = float(cfg.get("rob_wife_probability") or 0.3)
    p_money = float(cfg.get("rob_money_probability") or 0.35)

    lv, g1, g2, g3, g4 = [], [], [], [], []
    lv, g1, lab = _grid("force", p_force)
    _, g2, _ = _grid("rob_wife", p_wife, 0)
    _, g3, _ = _grid("rob_wife", p_wife, 200)
    _, g4, _ = _grid("rob_money", p_money, 0)

    html = ['<div class="grid-2">']
    html.append('<div>' + heatmap_svg(g1, lab, lab, "强娶成功率（%.0f%% 基础，不参与战力）" % (p_force * 100)) + '</div>')
    html.append('<div>' + heatmap_svg(g2, lab, lab, "抢老婆成功率（好感 0）") + '</div>')
    html.append('<div>' + heatmap_svg(g3, lab, lab, "抢老婆成功率（好感 200，护盾 −10%）") + '</div>')
    html.append('<div>' + heatmap_svg(g4, lab, lab, "打劫成功率（无好感护盾）") + '</div>')
    html.append('</div>')
    html.append('<p class="note">颜色由红（低胜率）到绿（高胜率）。注意强娶那张是<b>纯色</b>——'
                '它不参与战力计算，所以任何等级对任何人都是同一个概率；'
                '其余三张的对角线是"同境界 ≈ 基础概率"，越远离对角线越快撞上钳制边界。</p>')

    # 好感护盾曲线
    affs = list(range(0, 1001, 50))
    series = []
    mid = 60  # 取中段作为基准，攻击/防守各偏移一个大境界
    for gap, color, label in ((4, "#22c55e", "进攻方高 1 个大境界"),
                              (0, "#eab308", "双方同境界"),
                              (-4, "#ef4444", "进攻方低 1 个大境界")):
        pts = []
        for aff in affs:
            lvl_a = min(MAX_LEVEL, max(0, mid + gap))
            pts.append((aff, _prob("rob_wife", lvl_a, mid, aff, p_wife)))
        series.append({"name": label, "color": color, "points": pts})
    html.append(line_chart(series, 0, 1000, 0, 1, w=880, h=300,
                           x_label="夫妻好感度", y_label="抢老婆成功率", y_fmt="{:.0%}", x_fmt="{:.0f}"))
    html.append('<p class="note">好感护盾是<b>线性递减</b>但被 10%% 兜底卡住：'
                '每 %d 点好感减 %s，理论上 1000 好感可减 %.0f%%，'
                '但底部保底 %s%% 让它最多只能把优势方压回下限。</p>'
                % (B.AFFECTION_PER_SHIELD, B.AFFECTION_SHIELD_RATE,
                   B.affection_shield(1000) * 100, B.ROB_FLOOR * 100))
    return "".join(html)


# ============================================================ 周期与次数
def section_cycle(m):
    if not B:
        return "<p>缺少 balance.py</p>"
    actions = [
        ("/今日老婆", B.DRAW_LIMIT, "#ec4899"),
        ("/离婚", B.DIVORCE_LIMIT, "#ec4899"),
        ("/甩掉", B.DUMP_LIMIT, "#ec4899"),
        ("/打工", B.WORK_LIMIT, "#f59e0b"),
        ("/约会", B.DATE_LIMIT, "#f59e0b"),
        ("/修炼", B.CULTIVATE_LIMIT, "#10b981"),
        ("/打劫", B.ROB_MONEY_LIMIT, "#ef4444"),
    ]
    maxv = max(a[1] for a in actions) or 1
    bars = []
    for name, v, color in actions:
        bars.append(
            '<div class="bar-row"><span class="bar-label">%s</span>'
            '<span class="bar-track"><span class="bar-fill" style="width:%.1f%%;background:%s"></span></span>'
            '<span class="bar-value">%d 次</span></div>'
            % (esc(name), v / float(maxv) * 100, color, v))
    return ('<div class="stats"><div class="stat"><span class="sv">%s 小时</span>'
            '<span class="sl">一个周期（CYCLE_HOURS）</span></div>'
            '<div class="stat"><span class="sv">%d</span><span class="sl">受周期影响的指令数</span></div>'
            '<div class="stat"><span class="sv">%d</span><span class="sl">每周期可执行的总次数上限</span></div>'
            '</div>' % (B.CYCLE_HOURS, len(actions), sum(a[1] for a in actions))
            + '<div class="bars" style="margin-top:18px">' + "".join(bars) + '</div>'
            + '<p class="note">次数记录存在 <code>daily_usage</code>，跨周期时整体清空。'
              '当前周期标识由 <code>balance.period_key()</code> 生成：'
              '周期为 24 小时时沿用日期字符串（与旧存档兼容），其它周期用 <code>P序号</code>。</p>')


def build_html(m, sim):
    st = domain_stats(m)
    total_loc = m["meta"]["plugin_py_loc"]
    tabs = [
        ("s-overview", "① 功能域总览"),
        ("s-matrix", "② 依赖矩阵"),
        ("s-commands", "③ 指令清单"),
        ("s-arch", "④ 分层架构"),
        ("s-econ", "⑤ 经济流量"),
        ("s-prob", "⑥ 战斗概率"),
        ("s-cult", "⑦ 修炼曲线"),
        ("s-penalty", "⑧ 惩罚机制"),
        ("s-hot", "⑨ 维护热点"),
        ("s-new", "⑩ 新功能落点"),
        ("s-cfg", "⑪ 配置项"),
        ("s-bal", "⑫ 数值总览"),
        ("s-grid", "⑬ 概率矩阵"),
        ("s-cycle", "⑭ 周期次数"),
    ]
    nav = "".join('<button data-target="%s"%s>%s</button>'
                  % (t[0], ' class="on"' if i == 0 else "", esc(t[1])) for i, t in enumerate(tabs))

    def sec(sid, title, lede, body, on=False):
        return ('<section id="%s"%s><h2>%s</h2><p class="lede">%s</p>%s</section>'
                % (sid, ' class="on"' if on else "", esc(title), esc(lede), body))

    chips = "".join('<span class="chip">%s <b>%s</b></span>' % (esc(k), esc(v)) for k, v in [
        ("插件", m["meta"]["plugin"] + " v" + m["meta"]["version"]),
        ("指令", m["meta"]["commands"]),
        ("plugin.py", "%d 行" % total_loc),
        ("配置项", m["meta"]["config_fields"]),
        ("数据表", len(m["data_keys"])),
        ("功能域", len(m["meta"]["domains"])),
        ("测试覆盖", "0"),
    ])
    body = "".join([
        sec("s-overview", "功能域总览",
            "10 个功能域 = 6 个业务域（婚姻/经济/修仙/战斗/展示/管理）+ 4 个横切关注点（入口路由/惩罚限次/数据存储/配置）。每个域标注了它实际拥有的指令数、代码行数与职责边界。",
            section_domains(m), on=True),
        sec("s-matrix", "指令 × 数据 / 配置 依赖矩阵",
            "一行一个指令，一列一张表或一个配置项。这是重构时「该往哪切」的直接依据。",
            section_matrix(m)),
        sec("s-commands", "指令清单（24 个 handler）",
            "按功能域分组标色；点数、行数、await 数、触及的数据表与每日次数均来自静态扫描。",
            section_commands(m)),
        sec("s-arch", "分层架构与穿层调用",
            "理想分层 vs 当前实现的差距：命令层没有领域服务可依赖，只能自己动手改存储。",
            section_arch(m)),
        sec("s-econ", "经济流量",
            "金币从哪里来、到哪里去。做「财富体系」时，这张图就是设计货币回收的起点。",
            section_economy(m)),
        sec("s-prob", "战斗概率曲线",
            "把所有概率公式画出来，比读代码更容易发现数值设计的不一致。",
            section_probability(m)),
        sec("s-cult", "修炼曲线与期望成本",
            "按当前公式跑 2 万次蒙特卡洛，量化「练到满级」到底有多贵。",
            section_cultivation(m, sim)),
        sec("s-penalty", "惩罚机制矩阵",
            "当前 6 类惩罚分别散落在哪些位置、由谁触发。",
            section_penalty(m)),
        sec("s-hot", "维护热点（代码行数）",
            "越长的 handler 改动风险越大，优先按职责切分。",
            section_hotspots(m)),
        sec("s-new", "四大新功能的挂载点",
            "财富 / 修炼体系与方式 / 惩罚机制 / 物品获取 —— 每个新功能应该长在哪、现有代码能复用多少。",
            section_newfeatures(m)),
        sec("s-cfg", "配置项清单",
            "17 个配置项及其被读取的次数；次数为 0 说明是死配置或只在模块外使用。",
            section_config(m)),
        sec("s-bal", "数值总览（balance.py）",
            "所有可调数值集中在此；改 balance.py 一处，插件、面板、曲线同时生效。",
            section_balance(m)),
        sec("s-grid", "成功率矩阵",
            "按等级网格算出的真实胜率，直接看概率面长什么样。",
            section_probability_grid(m)),
        sec("s-cycle", "周期与次数",
            "每个周期各行为可用次数；周期时长由 CYCLE_HOURS 单点控制。",
            section_cycle(m)),
    ])

    title = esc(m["meta"]["plugin"]) + " · 维护地图"
    return ("<!doctype html><html lang=\"zh-CN\"><head><meta charset=\"utf-8\">"
            "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
            "<title>" + title + "</title><style>" + CSS + "</style></head><body>"
            "<header><h1>" + title + "</h1>"
            "<div class=\"sub\">partner-game v" + esc(m["meta"]["version"]) +
            " ｜ 由 <code>docs/tools/</code> 静态扫描生成，重构后重新运行即可刷新"
            "</div><div class=\"chips\">" + chips + "</div></header>"
            "<nav>" + nav + "</nav><main>" + body + "</main>"
            "<footer>数据来源：AST 静态扫描 + 源码数值提取 + 蒙特卡洛模拟（2 万次）</footer>"
            "<script>" + JS + "</script></body></html>")


# ------------------------------------------------------------------ Markdown
def build_md(m, sim):
    L = []
    A = L.append
    A("# partner-game 功能分类与维护地图\n")
    A("> 由 `docs/tools/gen_maintenance_map.py` + `gen_dashboard.py` 从源码静态生成，"
      "重构后重新运行即可刷新。可视化版本见 `docs/dashboard.html`。\n")
    A("## 0. 概览\n")
    A("| 指标 | 值 |\n|---|---|")
    A("| 插件 | %s (%s) |" % (m["meta"]["plugin"], m["meta"]["id"]))
    A("| 版本 | %s |" % m["meta"]["version"])
    A("| 指令数 | %d |" % m["meta"]["commands"])
    A("| plugin.py | %d 行 |" % m["meta"]["plugin_py_loc"])
    for f, n in sorted(m["meta"]["files"].items(), key=lambda x: -x[1]):
        if f == "plugin.py":
            continue
        A("| %s | %d 行 |" % (f, n))
    A("| 配置项 | %d |" % m["meta"]["config_fields"])
    A("| 持久化表 | %s |" % "、".join(m["data_keys"]))
    A("| 测试 | 0 |\n")

    A("## 1. 功能域分类\n")
    st = domain_stats(m)
    A("| 域 | 职责 | 指令数 | 代码行 | 关键位置 |\n|---|---|---:|---:|---|")
    for k in DOMAIN_ORDER:
        d = m["meta"]["domains"][k]
        s = st.get(k, {"count": 0, "loc": 0})
        loc = DOMAIN_DETAIL.get(k, [("", "", "")])
        where = "；".join("`%s`" % x[2] for x in loc[:3])
        A("| **%s** | %s | %s | %d | %s |"
          % (d["name"], d["desc"], ("—" if s["count"] == 0 else str(s["count"])), s["loc"], where))
    A("")
    A("> 「入口与路由 / 惩罚与限次 / 数据与持久化 / 配置」是**横切关注点**："
      "它们没有专属指令，而是被其它域共享，因此指令数为 0。")

    A("### 1.1 各域明细\n")
    for k in DOMAIN_ORDER:
        d = m["meta"]["domains"][k]
        A("#### %s `%s`\n" % (d["name"], k))
        A("| 功能点 | 说明 | 位置 |\n|---|---|---|")
        for item in DOMAIN_DETAIL.get(k, []):
            A("| %s | %s | `%s` |" % (item[0], item[1], item[2]))
        A("")

    A("## 2. 指令总表\n")
    A("| 指令 ID | 玩法 | 域 | 起始行 | 行数 | await | 数据表 | 配置项 | 每日次数 |")
    A("|---|---|---|---:|---:|---:|---|---|---|")
    for c in m["commands"]:
        d = m["meta"]["domains"][c["domain"]]
        A("| `%s` | %s | %s | %d | %d | %d | %s | %s | %s |" % (
            c["id"], CMD_LABEL.get(c["id"], ""), d["name"], c["code_lineno"], c["loc"], c["awaits"],
            "、".join(c["data_keys"]) or "—",
            "、".join(c["config_keys"]) or "—",
            "、".join("%s×%d" % (a, n) for a, n in c["daily_limits"]) or "—"))
    A("")

    A("## 3. 数据模型\n")
    A("单一 JSON 文件 `data/partner_game_seen.json`，全部以**群号**为一级键：\n")
    A("```jsonc\n{\n  \"marriages\": {            // 婚姻表：以老公 QQ 为主键（老婆没有独立记录）")
    A("    \"<群号>\": {\"<老公QQ>\": {\"date\":\"2026-11-01\",\"wife_uid\":\"...\",\"wife_nick\":\"...\",")
    A("                             \"wife_card\":\"...\",\"affection\":0}}")
    A("  },\n  \"users\": {                // 经济与修炼表")
    A("    \"<群号>\": {\"<QQ>\": {\"money\":1000,\"level\":0,\"last_allowance\":\"2026-11-01\"}}")
    A("  },\n  \"daily_usage\": {          // 每日次数表，跨日整体清空")
    A("    \"<群号>\": {\"<QQ>\": {\"work\":2,\"cultivate\":1,\"date\":0,\"rob_money\":1}}")
    A("  },\n  \"last_date\": \"2026-11-01\"  // 全局日期戳，驱动跨日重置")
    A("}\n```\n")
    A("关系：`users` 与 `marriages` 之间**没有外键**，靠 QQ 号字符串隐式关联；"
      "老婆一侧的数据只能通过反向遍历 `marriages` 推导（O(n)）。"
      "新增「物品」时，最小侵入做法是在 `users[群][QQ]` 下加 `items: {}`。\n")

    A("## 4. 经济流水\n")
    A("| 名称 | 方向 | 金额 / 公式 | 触发 | 位置 |\n|---|---|---|---|---|")
    for name, typ, amount, trigger, loc in m["economy"]:
        A("| %s | %s | %s | %s | `%s` |" % (name, typ, amount, trigger, loc))
    A("")
    A("**结论**：流入以「打工 + 低保」为主，流出以「修炼」为主；罚款的 50% 会凭空蒸发，"
      "是当前唯一的货币回收池。没有任何流水记录，资产负债无法审计。\n")

    A("## 5. 战斗概率\n")
    A("| 玩法 | 基础 | 战力参与 | 好感护盾 | 钳制区间 | 资金门槛 | 失败罚款 |")
    A("|---|---:|---|---|---|---:|---|")
    for k, v in m["combat"].items():
        A("| %s | %.0f%% | %s | %s | %.0f%%~%.0f%% | %d | %d~%d |" % (
            CMD_LABEL.get(k, k), v["base"] * 100,
            "是" if v["power"] else "否", "是" if v["affection"] else "否",
            v["floor"] * 100, v["cap"] * 100, v["gate"], v["fine"][0], v["fine"][1]))
    A("")
    A("统一公式：`p = base + Δpower×%s − (affection//20)×0.01`，"
      % (R.rate_percent() if R else "0.5%") +
      "其中 `power = level × (level//4 + 1)`。强娶是唯一的例外（不参与战力、钳制 0~1）。\n")

    A("![战斗概率曲线](charts/probability.svg)\n")

    A("## 6. 修炼体系\n")
    A("| 等级 | 境界 | 战力 | 单次修炼花费 | 3 次/天支出 |")
    A("|---:|---|---:|---:|---:|")
    sample = [0, 3] + list(range(4, MAX_LEVEL, 16)) + [MAX_LEVEL]
    for lv in sample:
        r = "%s%s" % (m["realms"][lv // 4], m["sub_realms"][lv % 4]) if lv < 36 else "仙人"
        cost = (lv // 4 + 1) * 50
        A("| %d | %s | %d | %d | %d |" % (lv, r, power(lv), cost, cost * 3))
    A("")
    A("2 万次蒙特卡洛（每次 3 次/天）：期望 **%.0f 次**修炼、**%s 金币**、"
      "**%.0f 天**练到渡劫圆满；波动区间 %d~%d 次。\n" % (
          sim["attempts"], "{:,.0f}".format(sim["money"]), sim["days"],
          sim["min_attempts"], sim["max_attempts"]))

    A("![修炼收支曲线](charts/cultivation.svg)\n")

    A("## 7. 惩罚机制\n")
    A("| 类型 | 强度 | 触发 | 覆盖 | 位置 |\n|---|---|---|---|---|")
    for p in m["penalties"]:
        A("| %s | %s | %s | %s | `%s` |" % (p[0], p[1], p[2], p[3], p[4]))
    A("")

    A("## 8. 与新功能的对接点\n")
    for name, domain, current, advice in m["new_features"]:
        A("### %s\n" % name)
        A("- **现状**：%s" % current)
        A("- **建议**：%s\n" % advice)

    A("## 9. 重构目录建议\n")
    A("```\npartner_game/\n"
      "├── __init__.py            # create_plugin\n"
      "├── _manifest.json\n"
      "├── config.py              # 现有 17 项 + 新增（物品/惩罚/功法）\n"
      "├── plugin.py              # 只保留：注册命令 + 调用服务 + 渲染文案\n"
      "├── domain/\n"
      "│   ├── wallet.py          # 金币：唯一入口 debit/credit，带流水\n"
      "│   ├── realm.py           # 境界表、战力换算、修炼策略\n"
      "│   ├── marriage.py        # 婚姻 CRUD、好感度\n"
      "│   ├── combat.py          # 概率结算（纯函数，可单测）\n"
      "│   ├── penalty.py         # 冷却/次数/罚款/掉级 统一策略\n"
      "│   └── items.py           # 物品与掉落（全新）\n"
      "├── storage/\n"
      "│   └── store.py           # 持久化 + 迁移 + 备份\n"
      "├── ui/\n"
      "│   ├── render.py          # 文案模板集中管理\n"
      "│   └── send.py            # NapCat 直发封装\n"
      "└── data/\n"
      "```\n")
    A("> 关键原则：**handler 不再直接改 `_store.data`**。当前 24 个指令里有 %d 个直接写存储，"
      "这是耦合的根源；把它们全部收口到 `domain/*` 的少数几个方法后，"
      "概率、经济、惩罚的数值调整才能变成单点修改。\n" % len([c for c in m["commands"] if c["data_direct"]]))

    return "\n".join(L)


# ------------------------------------------------------------------ 静态 SVG 图（供 Markdown 内嵌）
def export_svgs(m, sim):
    d = os.path.join(DOCS, "charts")
    os.makedirs(d, exist_ok=True)

    # 1) 战斗概率曲线
    series = [
        {"name": "强娶 40%（不参与战力）", "color": "#f59e0b", "points": combat_curve("force_marry")},
        {"name": "抢老婆 30%（好感 0）", "color": "#ec4899", "points": combat_curve("rob_wife", 0)},
        {"name": "抢老婆 30%（好感 500，护盾 −25%）", "color": "#a855f7",
         "points": combat_curve("rob_wife", 500), "dash": True},
        {"name": "打劫 35%（无好感护盾）", "color": "#ef4444", "points": combat_curve("rob_money")},
    ]
    svg = render_chart(series, -330, 330, 0, 1, w=900, h=340,
                       x_label="战力差 Δpower（进攻方 − 防守方最高战力）",
                       y_label="成功概率", x_zero=0, embed_legend=True)
    with io.open(os.path.join(d, "probability.svg"), "w", encoding="utf-8") as f:
        f.write(svg)

    # 2) 修炼收支曲线
    s1 = {"name": "修炼日支出（3 次）", "color": "#ef4444",
          "points": [(l, 3 * ((l // 4 + 1) * 50)) for l in range(MAX_LEVEL + 1)]}
    s2 = {"name": "打工日收入（3 次，期望 75/次）", "color": "#22c55e",
          "points": [(l, 3 * (75 + 10 * l)) for l in range(MAX_LEVEL + 1)]}
    svg = render_chart([s1, s2], 0, 35, 0, 1500, w=900, h=340,
                       x_label="境界等级", y_label="金币 / 天", y_fmt="{:,.0f}",
                       embed_legend=True)
    with io.open(os.path.join(d, "cultivation.svg"), "w", encoding="utf-8") as f:
        f.write(svg)


def main():
    m = load()
    sim = simulate_cultivation()
    html = build_html(m, sim)
    with io.open(os.path.join(DOCS, "dashboard.html"), "w", encoding="utf-8") as f:
        f.write(html)
    with io.open(os.path.join(DOCS, "FEATURES.md"), "w", encoding="utf-8") as f:
        f.write(build_md(m, sim))
    export_svgs(m, sim)
    print("[ok] dashboard.html  %.1f KB" % (len(html.encode("utf-8")) / 1024.0))
    print("[ok] FEATURES.md")
    print("[ok] charts/probability.svg, charts/cultivation.svg")
    print("[sim] attempts=%.1f money=%.0f days=%.1f range=%d-%d"
          % (sim["attempts"], sim["money"], sim["days"], sim["min_attempts"], sim["max_attempts"]))
    return 0


if __name__ == "__main__":
    sys_exit = main()
