# 发布到 MaiBot 插件市场

本仓库以 **`tianditongcuo.partner-game-pro`** 登记到
[Mai-with-u/plugin-repo](https://github.com/Mai-with-u/plugin-repo)，
市场按「插件 ID → 仓库地址」索引，**不看 GitHub 分支**。

---

## 一、前置检查（提 PR 前必须全部满足）

| 要求 | 状态 |
|---|---|
| 仓库根目录有 `_manifest.json`（v2） | ✅ |
| 根目录**不能**有 `config.toml` | ✅ 已 gitignore |
| 必须有 `LICENSE`、`README.md`、`plugin.py` | ✅ |
| `urls.repository` 是公开 GitHub HTTPS 地址 | ✅ |
| `version` / `host_application` 三段式，前两位不能是 `99` | ✅ `1.3.99` |
| 必须已发布至少一个 **GitHub Release**（仅 tag 不算） | ⬜ 待办 |
| manifest 不能有未定义字段（`categories`、`keywords` 等） | ✅ |

> 校验脚本：`python docs/tools/verify_plugin.py . "<你的 MaiBot 目录>/plugins"`

---

## 二、发布流程

### 1. 推送代码

```bat
git push origin main
```

### 2. 打 Tag + 建 Release

```bat
git tag v2.0.2
git push origin v2.0.2
```

然后在 GitHub 网页 → Releases → **Draft a new release** → 选 `v2.0.2` →
标题填 `v2.0.2`，说明填下面这段：

```markdown
## 今日老婆 Pro+ v2.0.2

基于 [onelxzy/partner-game](https://github.com/onelxzy/partner-game) 的维护分支首个版本。

### 与原版的差异
- 插件 ID 改为 `tianditongcuo.partner-game-pro`，可与原版并存区分
- `host_application.max_version` 由 `1.99.99` 修正为 `1.3.99`（按实测版本声明）
- 移除指向不存在目录的 `i18n.locales_path`
- 新增 `docs/`：功能依赖地图、可视化维护面板、插件识别预检脚本

### 玩法
与原版 v2.0.2 完全一致（24 条指令：抽取/求婚/强娶/抢老婆/打劫/打工/修炼/约会/榜单等）。
后续版本将扩展财富、修炼体系、惩罚机制、物品系统。
```

> ⚠️ 不要勾「This is a pre-release」，预发布版本市场不收录。

### 3. 提交登记 PR

1. Fork [Mai-with-u/plugin-repo](https://github.com/Mai-with-u/plugin-repo)
2. 编辑 `plugins.json`，在数组里**按 id 排序的位置**插入：

```json
    {
      "id": "tianditongcuo.partner-game-pro",
      "repositoryUrl": "https://github.com/tianditongcuo/partner-game"
    },
```

3. 提交 PR，标题：`[Plugin] 新增 今日老婆 Pro+ (tianditongcuo.partner-game-pro)`
4. PR 描述：

```markdown
## 插件信息
- 插件 ID：`tianditongcuo.partner-game-pro`
- 插件名称：今日老婆 Pro+
- 仓库：https://github.com/tianditongcuo/partner-game
- 首个 Release：v2.0.2
- 类别：game（群聊互动游戏）

## 说明
`onelxzy/partner-game` 的维护分支，插件 ID 与原版不同，可与原版区分安装
（两者指令集重叠，不建议同时启用）。当前玩法与原版一致，改动集中在工程层面：
修正 manifest 兼容声明、补充维护文档。

后续计划扩展财富 / 修炼体系 / 惩罚机制 / 物品四大系统。
```

---

## 三、以后每次更新

市场同步任务在北京时间每天 **02:00 / 15:00** 扫描已登记仓库的 Release：

1. 改代码 → 修改 `_manifest.json` 的 `version`（如 `2.1.0`）
2. `git tag v2.1.0 && git push origin v2.1.0`
3. 在 GitHub 建对应 Release（正式版）
4. 等同步任务自动建审核单 → AI 静态审核 → 通过后市场出现新版本

> - 每个插件每次同步**只取最新 1 个**合规版本，跳过的版本不会补审。
> - 已收录的版本若被撤回或 Tag 被改写，会标记 `yanked`。
> - 审核未过会转人工，维护者用 `/approve` 批准、`/reject` 拒绝。

---

## 四、常见坑

| 现象 | 原因 |
|---|---|
| 市场里搜不到 | PR 未合并；或 Release 未发布（只有 tag） |
| 安装时报 `Remote branch ... not found` | 在「分支」输入框里填了仓库地址；市场安装只认分支名 |
| 装完是原版功能 | 装成了 `onelxzy.partner-game`，注意市场里两个条目的名字 |
| 更新不生效 | 版本号没递增，市场按 version 判断 |
