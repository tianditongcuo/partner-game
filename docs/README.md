# docs/ — 维护地图与部署校验

本目录除 `README.md` 外全部**由脚本从源码生成**，不是手写文档。改了代码就跑一遍：

```bash
python docs/tools/gen_maintenance_map.py   # ① 静态扫描 → feature_map.json / handler_stats.csv
python docs/tools/gen_dashboard.py         # ② 渲染 → dashboard.html / FEATURES.md / charts/*.svg
```

插件装到 MaiBot 之前，先自检一遍能不能被识别：

```bash
python docs/tools/verify_plugin.py . "D:/Maimaibot/my-maibot/plugins"
```

## 文件说明

| 文件 | 内容 | 谁该看 |
|---|---|---|
| `dashboard.html` | 11 个分页的可视化面板（依赖矩阵、分层图、经济流量、概率曲线…），单文件、离线可开 | 想快速理解全局的人 |
| `FEATURES.md` | 同一批数据的 Markdown 版，可进 Git diff / PR 评审 | 写代码的人 |
| `feature_map.json` | 机器可读的功能/依赖地图（指令、配置、数据表、耦合关系） | 写工具/做迁移脚本 |
| `handler_stats.csv` | 24 条指令的复杂度与依赖统计，可直接丢进 Excel | 排重构优先级 |
| `charts/probability.svg` | 三条犯罪公式的概率曲线 | 调数值 |
| `charts/cultivation.svg` | 修炼支出 vs 打工收入 | 调经济 |
| `preview-*.png` | 面板截图，供 README / 群聊分享 | — |
| `tuning.html` | **可交互调参面板**：拖滑块实时看曲线，导出可直接粘回的常量片段 | 调数值的人 |
| `tools/` | 生成器与预检脚本 | 维护文档本身 |

## tools/

| 脚本 | 作用 |
|---|---|
| `gen_maintenance_map.py` | `ast` 解析 `plugin.py`，产出功能/依赖地图 |
| `gen_dashboard.py` | 读 `feature_map.json` 渲染 HTML / Markdown / SVG |
| `verify_plugin.py` | 按官方 Manifest 规范离线预检「能否被 MaiBot 识别」 |
| `_preview.py` | 用无头 Edge 给面板各分页截图（开发期自用） |
| `gen_tuning.py` | 生成 `tuning.html` 交互调参面板 |
| `deploy.py` | 一键同步到 MaiBot 的 plugins 目录（含重复 ID 检查、启用开关） |
| `check_config.py` | 配置自检：默认值必须在区间内、schema 可生成（用 MaiBot 的 Python 跑） |
| `smoke_test.py` | 用桩模块导入插件，抓 `py_compile` 抓不到的名字错误 |
| `test_rules.py` | 业务规则：劫掠金额、贷款倍数、逾期封禁、不限次语义 |
| `test_handlers.py` | 真正执行各 handler 的成败分支，抓运行期 NameError |

## 安装到 MaiBot（重要）

1. **目录 = 插件根目录**：`plugins/<任意名>/` 下必须**直接**是 `_manifest.json` 和 `plugin.py`。
   从 GitHub 下载的 zip 解压后常多一层目录（`partner-game-main/partner-game-main/`），
   必须把那层的内容平铺上来，否则根目录没有 manifest，插件不会被发现。
2. **同一 ID 只能装一份**：MaiBot 用 `_manifest.json` 里的 `id` 去重，**不是目录名**。
   同时存在两个 id 相同的目录时，日志会报
   `插件 ID 重复，已阻止加载；冲突目录: A, B`，两个都会被拦下。
3. **目录名不重要，但市场约定是 `作者_插件名`**，所以本插件安装目录用 `onelxzy_partner-game`。
4. 装好后 Runner 会生成 `config.toml` 和 `data/`，这两个不进 git（见根目录 `.gitignore`）。

## 生成器怎么工作

`gen_maintenance_map.py` 用 `ast` 解析 `plugin.py`：

- 抓 `@Command` 装饰器 → 指令 ID、正则、行号；`_extent()` 推断函数体范围（兼容 py3.7 无 `end_lineno`）
- 正则统计每个 handler 的 `await` 数、`ctx.api.call` 接口、`cfg.*` 配置项
- 数据表访问分两层：`data_direct`（直接读写 `_store.data`）与 `data_indirect`
  （经 `_get_user_data` / `_get_user_marriage` / `_check_daily_limit`）
- 功能域归属在 `COMMAND_DOMAIN` 里人工声明，改分类只需改那张表

`gen_dashboard.py` 只消费 JSON，不碰源码，所以可以随便改样式和图表。

## 维护约定

1. **改数值**：只改仓库根目录的 `balance.py`。插件行为、面板参数表、
   概率热力图、周期次数图全部从它读取，改完重启（或等热重载）再跑一次生成器即可。
   ⚠️ 例外：`gen_maintenance_map.py` 里的 `ECONOMY / PENALTIES / COMBAT`
   三张说明性表格仍是手写常量，仅用于文档叙述，不影响插件。
2. **调周期**：`balance.py` 的 `CYCLE_HOURS` 一处控制（24 = 一天）。
3. **新增指令**：在 `COMMAND_DOMAIN` 里登记它的域，否则会落到 `router`。
4. **拆分模块后**：把 `gen_maintenance_map.py` 里的文件列表指到新路径，
   或按新结构重写 `parse_commands()` 的输入——其余逻辑与文件结构无关。
5. 本目录下的 `.py` 必须保证 **import 期无副作用**：插件目录里的脚本有可能被加载器扫描，
   导入时执行逻辑会导致整个插件加载失败。所有入口都写在 `if __name__ == "__main__"` 里。
