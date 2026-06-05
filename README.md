# 🎨 astrbot_pixiv-plugins

> AstrBot Pixiv 图片检索插件 — 支持指令和自然语言，LLM 驱动的智能搜图

[![Python](https://img.shields.io/badge/Python-3.10+-blue.svg)](https://www.python.org/)
[![AstrBot](https://img.shields.io/badge/AstrBot-4.0+-green.svg)](https://github.com/AstrBotDevs/AstrBot)
[![License](https://img.shields.io/badge/License-AGPL--3.0-orange.svg)](LICENSE)

---

## ✨ 功能特性

### 核心搜图
- 🔍 **按 ID 精确查找** — `/pixiv id 12345678`
- 🏷️ **按标签搜索** — `/pixiv tag 猫耳少女`
- 🔢 **智能多张发送** — 说「来两张」发 2 张，「来多张」发默认数量，上限可配
- 📖 **多图作品支持** — 漫画/图集自动发送全部页面，超出上限时提示前往官网
- ⏱️ **定时撤回** — 图片发送后 N 秒自动撤回，可配置时间或关闭

### 安全审核
- 🛡️ **视觉模型内容审核** — 可选开启，用视觉 LLM 二次检测暴露程度（0~10 分），超阈值自动撤回并道歉

### LLM 智能驱动
- 🧠 **自然语言理解** — 说「找一张 pixiv 图」自动搜图，无需指令
- 🔄 **智能标签富化** — 输入"灰姑娘"，LLM 自动转为 Pixiv 日文标签搜索
- 💬 **拟人化回复** — 搜索提示融入 AstrBot 人格设定，回复自然不生硬
- 🤔 **智能反问** — 意图不明反问 1 次，仍不理解则终止并提示指令

### 质量保障
- ⭐ **质量筛选 + 软回退** — 优先高收藏，无高质量时自动降级找最佳
- 🎲 **加权随机选图** — 去重后从新鲜池按收藏权重随机，非简单取前N，增加多样性
- 🚫 **标签黑名单** — 自动屏蔽指定标签（默认 futa），可自定义添加
- 🔄 **双层去重** — 全局 100 + 每会话 20，避免重复发送
- 🎯 **热度排序** — 按收藏数降序（需 Pixiv Premium，否则回退为时间排序）

### 灵活配置（均在 WebUI 设置页面）
- 🔞 **R18 三模式** — 过滤 / 关闭 / 只看 R18，可设管理员保护
- 🖼️ 图片信息 5 个独立开关（标题/作者/收藏/标签/链接）
- 📐 画质三档可选
- 📄 翻页深度 3~20 可调
- 🤖 独立 LLM 选择（下拉框）

---

## 📦 安装

### 1. 放入插件目录

**首先找到 AstrBot 的插件目录**。不同安装方式路径不同：

| 安装方式 | 插件目录 |
|---------|---------|
| AstrBot 桌面版 / 启动器 | `AstrBot安装目录/data/plugins/` |
| pip install | `~/.astrbot/data/plugins/`（Linux）或 `C:\Users\<用户名>\.astrbot\data\plugins\`（Windows） |
| Docker | 挂载卷中的 `data/plugins/` |

**然后将插件文件夹整个复制进去**：

```
AstrBot安装目录/
└── data/
    └── plugins/                       ← 插件根目录
        └── astrbot_pixiv-plugins/     ← 复制这个文件夹到这里
            ├── main.py                ← 插件入口
            ├── metadata.yaml          ← 插件信息
            ├── _conf_schema.json      ← 设置表单定义
            ├── requirements.txt       ← 依赖列表
            └── src/                   ← 核心代码
```

> 💡 **也可以通过 WebUI 安装**：WebUI → 插件管理 → 安装插件 → 输入插件文件夹的路径或 ZIP 文件。

### 2. 安装依赖

```bash
pip install pixivpy3 httpx Pillow
```

### 3. 重启 AstrBot

启动日志出现 `[pixiv] ✅ 插件初始化完成` 即成功。

---

## ⚙️ 配置

**WebUI → 插件管理 → astrbot_pixiv-plugins → 设置**

### 必填

| 配置项 | 说明 |
|--------|------|
| Pixiv Refresh Token | Pixiv 认证令牌，获取方式见下方 ⬇️ |

#### 🔑 如何获取 Pixiv Refresh Token？

Refresh Token 是 Pixiv OAuth 登录后颁发的一个长期凭证，pixivpy3 依赖它来调用 API。以下提供三种获取方式：

---

**方法一：gppt（推荐命令行工具）**

> [gppt](https://github.com/eggplants/get-pixivpy-token) 是基于 Selenium 的命令行工具，操作简单，是目前主流选择。

```bash
# 1. 安装
pip install gppt

# 2. 获取 Token
gppt login
```

运行后会打开浏览器窗口，正常登录 Pixiv 账号即可。登录成功后 `refresh_token` 会直接打印在终端。

> 💡 进阶：也支持无头模式 `gppt login-headless -u <用户名> -p <密码>`。

---

**方法二：pixiv_auth.py 脚本**

> pixivpy3 官方提供的登录脚本，无需安装浏览器驱动。

```bash
# 下载并运行
wget https://gist.githubusercontent.com/ZipFile/c9ebedb224406f4f11845ab700124362/raw/pixiv_auth.py
python pixiv_auth.py login
```

按提示输入 Pixiv 账号密码，登录成功后终端会打印 `refresh_token`。

> 📎 Gist 地址：https://gist.github.com/ZipFile/c9ebedb224406f4f11845ab700124362

---

**方法三：pixiv-token（备选）**

> 基于 Playwright 的同类工具，适合遇到兼容性问题时使用。

```bash
pip install pixiv-token
# 按命令行提示操作获取 Token
```

---

> 📌 **安全提醒**：Refresh Token 等同于你的 Pixiv 账号密码，**切勿分享给他人**！

### 完整配置项

| 配置项 | 类型 | 默认 | 说明 |
|--------|------|------|------|
| `pixiv_refresh_token` | str | — | **必需**，Pixiv 认证 |
| `r18_mode` | 下拉 | safe | R18 模式：过滤/关闭/只看R18 |
| `r18_admin_id` | str | — | R18 切换管理员QQ号，留空则任何人可切 |
| `tag_blacklist` | str | futa | 标签黑名单，逗号分隔，含此标签的作品不发送 |
| `llm_provider_id` | 下拉 | 默认 | 插件专用 LLM |
| `tag_enrichment_enabled` | bool | ✅ | 中文→日/英标签转换 |
| `humanized_reply_enabled` | bool | ✅ | 拟人化回复 |
| `show_image_info` | 嵌套开关 | 全部✅ | 5 信息独立开关 |
| `image_quality` | 下拉 | 大图 | 原图/大图/中等 |
| `search_sort` | 下拉 | 热度↓ | 排序方式（热度需 Premium） |
| `min_bookmarks` | int | 50 | 最低收藏阈值 |
| `search_max_pages` | 下拉 | 10 | 翻页数 |
| `max_images_per_request` | 下拉 | 3 | 单次最多张数 |
| `max_pages_per_illust` | 下拉 | 3 | 多图作品最多发送页数 |
| `session_dedup_limit` | int | 20 | 会话去重数 |
| `recall_after_seconds` | 下拉 | 60 | 定时撤回秒数（0=关闭） |
| `content_moderation_enabled` | bool | ❌ | 启用图片内容审核 |
| `content_moderation_provider` | 下拉 | 默认 | 审核用视觉模型 |
| `nsfw_threshold` | 下拉 | 9 | NSFW 阈值（超过则撤回） |

---

## 📖 使用方法

### 指令

| 指令 | 说明 |
|------|------|
| `/pixiv id <ID>` | 按 ID 搜索 |
| `/pixiv tag <标签>` | 按标签搜索 |
| `/pixiv r18 <safe/off/r18_only>` | R18 模式切换（可设管理员） |
| `/pixiv r18` | 查看当前 R18 模式 |
| `/pixiv help` | 帮助 |
| `/pixiv config` | 查看配置 |
| `/pixiv test` | API 诊断 |

### 自然语言

| 你说 | 效果 |
|------|------|
| 「找一张猫娘的 pixiv 图」 | 搜 1 张 |
| 「来两张原神的图」 | 搜 2 张 |
| 「来多张风景画」 | 搜默认数量张 |
| 「关掉 R18 过滤」 | 切换 R18 模式（需管理员） |
| 「今天天气怎么样」 | 透传 AstrBot |

### 触发条件

- **私聊**：所有消息直接处理
- **群聊**：需 @机器人

---

## ❓ 常见问题

**Q: 提示 "Pixiv 未登录"？**
WebUI → 插件设置 → 填入 Pixiv Refresh Token

**Q: 中文标签搜不到？**
开启标签富化自动转换。也可直接用日文标签。

**Q: 图片质量不佳？**
调整「最低收藏数阈值」和「搜索结果排序」。

**Q: 非图片消息被拦截？**
不会。LLM 判断无关的消息原样透传 AstrBot。

**Q: 为什么偶尔会搜不到图，过一会儿又正常了？**

可能的原因及排查顺序：

| 优先级 | 原因 | 说明 |
|:--:|------|------|
| ① | **Token 过期** | 插件通过你填的 Refresh Token 自动换取 Access Token（约 1 小时有效），后者过期后 Pixiv API 会静默返回空。插件已内置**即时自愈**（搜索空时自动刷新重试）+ 每 50 分钟定时刷新，并会按连续失败次数给出分级的修复建议。 |
| ② | **标签不存在** | LLM 富化后的标签在 Pixiv 上无结果（如冷门音译）。尝试换用更通用的标签重试。 |
| ③ | **网络波动** | 跨境链路偶发超时或丢包，Pixiv API 可能临时不可达。通常几分钟后自愈。 |
| ④ | **质量过滤过严** | `min_bookmarks` 设太高导致合格作品被过滤。插件会自动回退找最佳，但如果首页本就为空则跳过。可尝试调低阈值。 |

> 🔍 查看 AstrBot 日志中的 `[pixiv:client]` 前缀消息可辅助定位原因。连续出现 `🔴 连续 N 个标签首页无结果` 提示时，请重新填写 Refresh Token。

**Q: 为什么 /pixiv r18 切换后又被改回去了？**
可能是其他用户通过自然语言触发了模式切换。在设置中配置 `r18_admin_id` 可限制只有管理员能切换。

**Q: 为什么一个作品发了好几张图？**
该作品是漫画或图集（多页作品）。插件默认最多发送前 3 页，超出部分会提示前往 Pixiv 官网查看完整版。可在设置中调整「多图作品最多发送页数」。

**Q: 图片为什么会自动撤回？**
可能开启了「定时撤回」或「内容审核」。定时撤回按设定秒数自动执行；内容审核由视觉模型评分，超过阈值立即撤回并道歉。均可在设置中关闭或调整。

---

## 📄 许可

AGPL-3.0 License © 2026
