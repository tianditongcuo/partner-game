# -*- coding: utf-8 -*-
"""开发者预览图生成（可选工具）。

只在手工执行时运行：
    python docs/tools/_preview.py docs s-overview s-arch

模块被 import 时不做任何事 —— 插件目录里的 .py 有可能被加载器扫描或导入，
导入期副作用会导致整个插件加载失败。
"""
from __future__ import annotations

import io
import os
import subprocess
import sys
import tempfile

#: 无头浏览器路径，可用环境变量 EDGE_PATH 覆盖
EDGE = os.environ.get("EDGE_PATH",
                      r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe")

SECTIONS = [
    ("s-overview", 900),
    ("s-matrix", 1150),
    ("s-commands", 1500),
    ("s-arch", 1000),
    ("s-econ", 1200),
    ("s-prob", 900),
    ("s-cult", 950),
    ("s-penalty", 700),
    ("s-hot", 1000),
    ("s-new", 700),
    ("s-cfg", 1100),
    ("s-bal", 1200),
    ("s-grid", 1500),
    ("s-cycle", 700),
]


def shoot(docs_dir, only=None):
    html_path = os.path.join(docs_dir, "dashboard.html")
    if not os.path.exists(html_path):
        raise SystemExit("找不到 %s，先运行 gen_dashboard.py" % html_path)
    src = io.open(html_path, encoding="utf-8").read()

    for sid, h in SECTIONS:
        if only and sid not in only:
            continue
        html = src.replace('<button data-target="s-overview" class="on">',
                           '<button data-target="s-overview">')
        html = html.replace('<section id="s-overview" class="on">',
                            '<section id="s-overview">')
        html = html.replace('<button data-target="%s">' % sid,
                            '<button data-target="%s" class="on">' % sid)
        html = html.replace('<section id="%s">' % sid,
                            '<section id="%s" class="on">' % sid)

        tmp = os.path.join(docs_dir, "_t_%s.html" % sid)
        io.open(tmp, "w", encoding="utf-8").write(html)
        out = os.path.abspath(os.path.join(docs_dir, "_p_%s.png" % sid))
        if os.path.exists(out):
            os.remove(out)

        subprocess.call(
            [EDGE, "--headless=new", "--disable-gpu", "--hide-scrollbars",
             "--user-data-dir=" + tempfile.mkdtemp(prefix="edgeshot_"),
             "--no-first-run", "--virtual-time-budget=2500",
             "--window-size=1360,%d" % h, "--screenshot=" + out,
             "file:///" + os.path.abspath(tmp).replace("\\", "/")],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        print(sid, os.path.getsize(out) if os.path.exists(out) else "FAIL")
        os.remove(tmp)


def main(argv):
    docs_dir = argv[1] if len(argv) > 1 else os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    shoot(docs_dir, argv[2:] or None)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
