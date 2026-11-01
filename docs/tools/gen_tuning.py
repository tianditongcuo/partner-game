# -*- coding: utf-8 -*-
"""生成可交互的数值调参面板 docs/tuning.html。

与 dashboard.html 的区别：
  dashboard 是"看"（读取 balance.py 渲染成静态图）；
  tuning 是"改"（滑块拖动 → 实时重算曲线 → 导出可直接覆盖的配置片段）。

纯前端实现：拖完点「导出」拿到文本，粘贴回 balance.py / config.toml，
不涉及任何写文件的操作，避免手滑改坏代码。
"""
from __future__ import annotations

import io
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DOCS = os.path.join(ROOT, "docs")

sys.path.insert(0, ROOT)
import balance as B          # noqa: E402
import realms as R           # noqa: E402

# (键, 分组, 滑块最小值, 最大值, 步长, 类型, 说明)
SPEC = [
    ("CYCLE_HOURS", "周期", 1, 168, 1, "int", "一个周期的小时数"),
    ("INITIAL_MONEY", "经济", 0, 10000, 100, "int", "新用户初始金币"),
    ("CYCLE_ALLOWANCE", "经济", 0, 2000, 50, "int", "每周期低保"),
    ("MARRIAGE_AFFECTION_PER_CYCLE", "经济", 0, 50, 1, "int", "跨周期婚姻自动加的好感"),
    ("DRAW_LIMIT", "次数", 0, 10, 1, "int", "/今日老婆 每周期次数"),
    ("DIVORCE_LIMIT", "次数", 0, 10, 1, "int", "/离婚 每周期次数"),
    ("DUMP_LIMIT", "次数", 0, 10, 1, "int", "/甩掉 每周期次数"),
    ("WORK_LIMIT", "次数", 0, 10, 1, "int", "/打工 每周期次数"),
    ("DATE_LIMIT", "次数", 0, 10, 1, "int", "/约会 每周期次数"),
    ("CULTIVATE_LIMIT", "次数", 0, 10, 1, "int", "/修炼 每周期次数"),
    ("ROB_MONEY_LIMIT", "次数", 0, 10, 1, "int", "/打劫 每周期次数"),
    ("WORK_EARN_MIN", "打工", 0, 1000, 10, "int", "基础收入下限"),
    ("WORK_EARN_MAX", "打工", 0, 2000, 10, "int", "基础收入上限"),
    ("WORK_LEVEL_BONUS", "打工", 0, 100, 1, "int", "每级境界额外收入"),
    ("DATE_COST", "约会", 0, 1000, 10, "int", "每次约会消耗"),
    ("DATE_AFF_MIN", "约会", 0, 100, 1, "int", "好感增加下限"),
    ("DATE_AFF_MAX", "约会", 0, 200, 1, "int", "好感增加上限"),
    ("CULTIVATE_COST_BASE", "修炼", 0, 500, 10, "int", "费用系数（(境界+1)×本值）"),
    ("MINOR_SUCCESS_RATE", "修炼", 0, 1, 0.01, "ratio", "小境界成功率"),
    ("MAJOR_SUCCESS_RATE", "修炼", 0, 1, 0.01, "ratio", "大境界成功率"),
    ("MAJOR_FAIL_DROP_RATE", "修炼", 0, 1, 0.01, "ratio", "大境界失败掉级率"),
    ("AFFECTION_PER_SHIELD", "好感", 1, 100, 1, "int", "每多少好感抵消一档"),
    ("AFFECTION_SHIELD_RATE", "好感", 0, 0.1, 0.001, "ratio", "每档抵消胜率"),
    ("FORCE_GATE", "强娶", 0, 5000, 50, "int", "金币门槛"),
    ("FORCE_FINE_MIN", "强娶", 0, 2000, 10, "int", "罚款下限"),
    ("FORCE_FINE_MAX", "强娶", 0, 5000, 10, "int", "罚款上限"),
    ("FORCE_FLOOR", "强娶", 0, 1, 0.01, "ratio", "胜率下限"),
    ("FORCE_CAP", "强娶", 0, 1, 0.01, "ratio", "胜率上限"),
    ("ROB_WIFE_GATE", "抢老婆", 0, 5000, 50, "int", "金币门槛"),
    ("ROB_WIFE_FINE_MIN", "抢老婆", 0, 2000, 10, "int", "罚款下限"),
    ("ROB_WIFE_FINE_MAX", "抢老婆", 0, 8000, 10, "int", "罚款上限"),
    ("ROB_WIFE_DROP_CHANCE", "抢老婆", 0, 1, 0.01, "ratio", "失败掉级率"),
    ("ROB_MONEY_GATE", "打劫", 0, 5000, 50, "int", "金币门槛"),
    ("ROB_MONEY_FINE_MIN", "打劫", 0, 2000, 10, "int", "罚款下限"),
    ("ROB_MONEY_FINE_MAX", "打劫", 0, 5000, 10, "int", "罚款上限"),
    ("ROB_MONEY_POOR_PROTECT", "打劫", 0, 2000, 10, "int", "低保保护线"),
    ("ROB_MONEY_RATIO_MIN", "打劫", 0, 0.5, 0.01, "ratio", "劫掠比例下限"),
    ("ROB_MONEY_RATIO_MAX", "打劫", 0, 1, 0.01, "ratio", "劫掠比例上限"),
    ("ROB_MONEY_STEAL_MIN", "打劫", 0, 1000, 10, "int", "单次劫掠下限"),
    ("ROB_MONEY_STEAL_CAP", "打劫", 0, 10000, 100, "int", "单次劫掠上限"),
    ("ROB_FLOOR", "共用", 0, 1, 0.01, "ratio", "抢夺/打劫胜率下限"),
    ("ROB_CAP", "共用", 0, 1, 0.01, "ratio", "抢夺/打劫胜率上限"),
    ("FINE_COMPENSATION_RATIO", "共用", 0, 1, 0.01, "ratio", "罚款赔付比例"),
    ("MAX_PENALTY_SECONDS", "共用", 0, 600, 10, "int", "自闭硬上限"),
]

# 概率来自 config.py（不在 balance.py 里），单独一组
CONFIG_SPEC = [
    ("force_marry_probability", "强娶基础概率", 0.4),
    ("rob_wife_probability", "抢老婆基础概率", 0.3),
    ("rob_money_probability", "打劫基础概率", 0.35),
    ("cooldown_seconds", "指令冷却（秒）", 60),
    ("proposal_timeout_seconds", "求婚超时（秒）", 60),
]

CSS = """
*{box-sizing:border-box}
body{margin:0;background:#0b1120;color:#e2e8f0;font:14px/1.6 "Microsoft YaHei","PingFang SC",sans-serif}
header{padding:22px 28px;background:linear-gradient(135deg,#111c33,#0b1120 60%);border-bottom:1px solid #1e293b}
h1{margin:0 0 4px;font-size:21px}
.sub{color:#94a3b8;font-size:12.5px}
main{max-width:1280px;margin:0 auto;padding:20px 24px 120px;display:grid;grid-template-columns:1fr 420px;gap:18px;align-items:start}
.panel{background:#111c33;border:1px solid #1e293b;border-radius:10px;padding:14px 16px}
.panel h2{font-size:13px;margin:0 0 10px;color:#94a3b8;letter-spacing:1px;font-weight:600}
.group{margin-bottom:14px}
.group h3{font-size:12.5px;color:#7dd3fc;margin:0 0 6px;padding-bottom:4px;border-bottom:1px solid #1e293b}
.row{display:flex;align-items:center;gap:8px;margin:5px 0}
.row label{flex:0 0 200px;font-size:12px;color:#cbd5e1;font-family:Consolas,monospace;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.row input[type=range]{flex:1;accent-color:#3b82f6;height:4px}
.row input[type=number]{width:78px;background:#0b1120;border:1px solid #334155;border-radius:6px;color:#e2e8f0;padding:3px 6px;font-size:12px;text-align:right}
.hint{font-size:10.5px;color:#64748b;margin:-2px 0 6px 208px}
.sticky{position:sticky;top:14px;max-height:calc(100vh - 40px);overflow:auto}
.chart{width:100%;height:auto;background:#0f172a;border:1px solid #1e293b;border-radius:8px}
.axis{fill:#64748b;font-size:10px;font-family:Consolas,monospace}
.grid{stroke:#1e293b}
.btns{display:flex;gap:8px;flex-wrap:wrap;margin-top:12px}
button{background:#1d4ed8;border:1px solid #3b82f6;color:#fff;border-radius:7px;padding:7px 14px;font-size:12.5px;cursor:pointer}
button.ghost{background:transparent;color:#94a3b8;border-color:#334155}
button:hover{filter:brightness(1.12)}
pre{background:#0b1120;border:1px solid #1e293b;border-radius:8px;padding:10px;font-size:11px;line-height:1.5;overflow:auto;max-height:260px;color:#a5b4fc;white-space:pre-wrap}
.warn{color:#f59e0b;font-size:11.5px;margin-top:6px}
.stats{display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-top:10px}
.stat{background:#0f172a;border:1px solid #1e293b;border-radius:8px;padding:8px 10px}
.sv{display:block;font-size:17px;font-weight:700;color:#fff}
.sl{font-size:10.5px;color:#94a3b8}
"""

JS = r"""
const META = __META__;
const CONFIG = __CONFIG__;
const MAXLEVEL = __MAXLEVEL__;
const state = {};
META.forEach(m => state[m.key] = m.value);
const conf = {};
CONFIG.forEach(c => conf[c.key] = c.value);

const $ = s => document.querySelector(s);
const power = l => l * (Math.floor(l / 4) + 1);
const clamp = (v, a, b) => Math.max(a, Math.min(b, v));
const shield = aff => Math.floor(aff / state.AFFECTION_PER_SHIELD) * state.AFFECTION_SHIELD_RATE;

function prob(kind, atk, dfd, aff) {
  let base = kind === 'force' ? conf.force_marry_probability
           : kind === 'wife' ? conf.rob_wife_probability
           : conf.rob_money_probability;
  let p = base + (power(atk) - power(dfd)) * 0.0025;
  if (kind === 'wife') p -= shield(aff);
  if (kind === 'force') return clamp(p, state.FORCE_FLOOR, state.FORCE_CAP);
  return clamp(p, state.ROB_FLOOR, state.ROB_CAP);
}

function svgLine(series, xmax, ymax, w, h) {
  const ml = 46, mr = 12, mt = 14, mb = 28;
  const pw = w - ml - mr, ph = h - mt - mb;
  const X = x => ml + x / xmax * pw;
  const Y = v => mt + ph - clamp(v, 0, ymax) / ymax * ph;
  let s = `<svg viewBox="0 0 ${w} ${h}" class="chart">`;
  for (let i = 0; i <= 4; i++) {
    const y = mt + ph * i / 4;
    s += `<line class="grid" x1="${ml}" y1="${y}" x2="${ml + pw}" y2="${y}"/>`;
    s += `<text class="axis" x="${ml - 6}" y="${y + 3}" text-anchor="end">${Math.round(ymax * (1 - i / 4))}</text>`;
  }
  for (let i = 0; i <= 5; i++) {
    const x = ml + pw * i / 5;
    s += `<text class="axis" x="${x}" y="${mt + ph + 14}" text-anchor="middle">${Math.round(xmax * i / 5)}</text>`;
  }
  series.forEach(se => {
    const pts = se.pts.map(([x, y]) => `${X(x).toFixed(1)},${Y(y).toFixed(1)}`).join(' ');
    s += `<polyline points="${pts}" fill="none" stroke="${se.color}" stroke-width="2"/>`;
  });
  s += '</svg>';
  // 图例放在图下方，避免压在曲线上
  s += '<div style="display:flex;gap:14px;flex-wrap:wrap;margin:6px 2px 0;font-size:11px;color:#94a3b8">';
  series.forEach(se => {
    s += `<span style="display:flex;align-items:center;gap:5px"><i style="width:12px;height:3px;border-radius:2px;background:${se.color};display:inline-block"></i>${se.name}</span>`;
  });
  return s + '</div>';
}

function renderCharts() {
  const lv = [];
  for (let i = 0; i <= MAXLEVEL; i += 1) lv.push(i);
  const s1 = { name: '修炼日支出', color: '#ef4444', pts: lv.map(l => [l, state.CULTIVATE_COST_BASE * (Math.floor(l / 4) + 1) * 3]) };
  const avg = (state.WORK_EARN_MIN + state.WORK_EARN_MAX) / 2;
  const s2 = { name: '打工日收入', color: '#22c55e', pts: lv.map(l => [l, (avg + state.WORK_LEVEL_BONUS * l) * 3]) };
  const ymax = Math.max(...s1.pts.map(p => p[1]), ...s2.pts.map(p => p[1])) * 1.1;
  $('#chart-econ').innerHTML = svgLine([s1, s2], MAXLEVEL, ymax, 640, 240);

  const affs = [];
  for (let a = 0; a <= 1000; a += 25) affs.push(a);
  const series = [
    { name: '高 1 境界', color: '#22c55e', pts: affs.map(a => [a, prob('wife', 64, 60, a) * 100]) },
    { name: '同境界', color: '#eab308', pts: affs.map(a => [a, prob('wife', 60, 60, a) * 100]) },
    { name: '低 1 境界', color: '#ef4444', pts: affs.map(a => [a, prob('wife', 56, 60, a) * 100]) }
  ];
  $('#chart-prob').innerHTML = svgLine(series, 1000, 100, 640, 240);

  const gap = prob('wife', 64, 60, 0) - prob('wife', 60, 60, 0);
  $('#stat-gap').textContent = (gap * 100).toFixed(1) + '%';
  $('#stat-capdays').textContent = state.CULTIVATE_LIMIT + ' 次';
}

function buildUI() {
  const groups = {};
  META.forEach(m => (groups[m.group] = groups[m.group] || []).push(m));
  let html = '';
  Object.keys(groups).forEach(g => {
    html += `<div class="group"><h3>${g}</h3>`;
    groups[g].forEach(m => {
      const step = m.kind === 'ratio' ? 0.001 : m.step;
      html += `<div class="row">
        <label title="${m.desc}">${m.key}</label>
        <input type="range" data-key="${m.key}" min="${m.min}" max="${m.max}" step="${step}" value="${m.value}">
        <input type="number" data-num="${m.key}" min="${m.min}" max="${m.max}" step="${step}" value="${m.value}">
      </div><div class="hint">${m.desc}</div>`;
    });
    html += '</div>';
  });
  html += `<div class="group"><h3>config.toml（概率与节奏）</h3>`;
  CONFIG.forEach(c => {
    html += `<div class="row">
      <label>${c.key}</label>
      <input type="range" data-conf="${c.key}" min="0" max="${c.key.indexOf('seconds') > 0 ? 300 : 1}" step="${c.key.indexOf('seconds') > 0 ? 5 : 0.01}" value="${c.value}">
      <input type="number" data-confnum="${c.key}" step="0.01" value="${c.value}">
    </div><div class="hint">${c.label}</div>`;
  });
  html += '</div>';
  $('#controls').innerHTML = html;

  document.querySelectorAll('[data-key]').forEach(el => {
    el.addEventListener('input', () => {
      const k = el.dataset.key;
      const v = parseFloat(el.value);
      state[k] = v;
      document.querySelector(`[data-num="${k}"]`).value = v;
      renderCharts();
    });
  });
  document.querySelectorAll('[data-num]').forEach(el => {
    el.addEventListener('input', () => {
      const k = el.dataset.num;
      const v = parseFloat(el.value);
      if (isNaN(v)) return;
      state[k] = v;
      document.querySelector(`[data-key="${k}"]`).value = v;
      renderCharts();
    });
  });
  document.querySelectorAll('[data-conf]').forEach(el => {
    el.addEventListener('input', () => {
      conf[el.dataset.conf] = parseFloat(el.value);
      document.querySelector(`[data-confnum="${el.dataset.conf}"]`).value = el.value;
      renderCharts();
    });
  });
  document.querySelectorAll('[data-confnum]').forEach(el => {
    el.addEventListener('input', () => {
      conf[el.dataset.confnum] = parseFloat(el.value);
      document.querySelector(`[data-conf="${el.dataset.confnum}"]`).value = el.value;
      renderCharts();
    });
  });
}

function exportBalance() {
  let out = '# 由 docs/tuning.html 导出\n';
  let lastGroup = null;
  META.forEach(m => {
    if (m.group !== lastGroup) { out += `\n# ===== ${m.group} =====\n`; lastGroup = m.group; }
    let v = state[m.key];
    if (m.kind === 'ratio') v = Math.round(v * 1000) / 1000;
    out += `${m.key} = ${v}\n`;
  });
  $('#output').textContent = out;
}

function exportConfig() {
  let out = '';
  CONFIG.forEach(c => { out += `${c.key} = ${conf[c.key]}\n`; });
  $('#output').textContent = out;
}

function resetAll() {
  META.forEach(m => state[m.key] = m.value);
  CONFIG.forEach(c => conf[c.key] = c.value);
  buildUI(); renderCharts();
}

buildUI();
renderCharts();
$('#btn-bal').onclick = exportBalance;
$('#btn-cfg').onclick = exportConfig;
$('#btn-reset').onclick = resetAll;
$('#btn-copy').onclick = () => navigator.clipboard && navigator.clipboard.writeText($('#output').textContent || '');
"""


def main():
    meta = []
    for key, group, lo, hi, step, kind, desc in SPEC:
        if not hasattr(B, key):
            print("[warn] balance 里没有", key)
            continue
        meta.append({"key": key, "group": group, "min": lo, "max": hi, "step": step,
                     "kind": kind, "desc": desc, "value": getattr(B, key)})

    # config 默认值直接从 config.py 源码里取，避免手抄
    import re
    cfg_src = io.open(os.path.join(ROOT, "config.py"), encoding="utf-8").read()
    conf_meta = []
    for key, label, fallback in CONFIG_SPEC:
        m = re.search(r"%s:\s*\w+\s*=\s*Field\(\s*default=([0-9.]+)" % key, cfg_src)
        val = float(m.group(1)) if m else float(fallback)
        conf_meta.append({"key": key, "label": label, "value": val})

    js = (JS.replace("__META__", json.dumps(meta, ensure_ascii=False))
            .replace("__CONFIG__", json.dumps(conf_meta, ensure_ascii=False))
            .replace("__MAXLEVEL__", str(R.MAX_LEVEL)))

    html = ("<!doctype html><html lang=\"zh-CN\"><head><meta charset=\"utf-8\">"
            "<title>数值调参面板 · 今日老婆 Pro+</title><style>%s</style></head><body>"
            "<header><h1>数值调参面板</h1>"
            "<div class=\"sub\">拖动滑块实时重算曲线 → 导出片段粘回 balance.py / config.toml。"
            "本页只读文件，不会自动改写仓库。</div></header>"
            "<main><div class=\"panel\"><h2>参数</h2><div id=\"controls\"></div></div>"
            "<div class=\"sticky\">"
            "<div class=\"panel\"><h2>经济曲线</h2><div id=\"chart-econ\"></div></div>"
            "<div class=\"panel\" style=\"margin-top:14px\"><h2>抢老婆胜率 vs 好感</h2>"
            "<div id=\"chart-prob\"></div>"
            "<div class=\"stats\">"
            "<div class=\"stat\"><span class=\"sv\" id=\"stat-gap\">-</span><span class=\"sl\">1 个境界的胜率优势</span></div>"
            "<div class=\"stat\"><span class=\"sv\" id=\"stat-capdays\">-</span><span class=\"sl\">周期内修炼次数</span></div>"
            "</div></div>"
            "<div class=\"panel\" style=\"margin-top:14px\"><h2>导出</h2>"
            "<div class=\"btns\">"
            "<button id=\"btn-bal\">生成 balance.py</button>"
            "<button id=\"btn-cfg\">生成 config 片段</button>"
            "<button class=\"ghost\" id=\"btn-copy\">复制</button>"
            "<button class=\"ghost\" id=\"btn-reset\">重置</button></div>"
            "<pre id=\"output\">点上面的按钮生成片段</pre></div>"
            "</div></main><script>%s</script></body></html>" % (CSS, js))

    out = os.path.join(DOCS, "tuning.html")
    io.open(out, "w", encoding="utf-8").write(html)
    print("[ok] tuning.html  %.1f KB  | 参数 %d 个 + config %d 个"
          % (len(html.encode("utf-8")) / 1024.0, len(meta), len(conf_meta)))


if __name__ == "__main__":
    main()
