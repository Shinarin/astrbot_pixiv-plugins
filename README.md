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

Refresh Token 是 Pixiv OAuth 登录后颁发的一个长期凭证，pixivpy3 依赖它来调用 API。以下提供两种获取方式：

---

**方法一：浏览器 DevTools 提取（推荐，无需装额外工具）**

> 适用于 Chrome / Edge / Firefox，操作完全一致。

| 步骤 | 操作 |
|:--:|------|
| **①** | 打开浏览器，访问 **https://www.pixiv.net** 并**登录**你的 Pixiv 账号 |
| **②** | 按 **F12** 打开开发者工具，切换到 **Application**（应用程序）标签 |
| **③** | 左侧栏：**Storage → Local Storage → https://www.pixiv.net** |
| **④** | 在右侧表格中找到 Key 为 `refresh_token` 的行（或包含 `token` 字样的 key） |
| **⑤** | **双击**该行的 Value 列，全选复制——这就是你的 Refresh Token ✅ |

> ⚠️ 如果在 Local Storage 中找不到，尝试在 **Cookies** 中查找 `refresh_token`，或切换到 **Network** 标签，刷新页面后搜索 `token`，在 `/auth/token` 请求的响应体中也能找到。

---

**方法二：官方脚本获取**

> pixivpy3 官方提供了登录脚本，适合无法从浏览器提取的情况。

```bash
# 1. 下载官方登录脚本
wget https://gist.githubusercontent.com/ZipFile/c9ebedb224406f4f11845ab700124362/raw/pixiv_auth.py

# 2. 运行登录（需要 pip install requests）
python pixiv_auth.py login

# 3. 按提示输入 Pixiv 账号密码（可能需要代理）
# 4. 登录成功后终端会打印 refresh_token，复制即可
```

> ⚠️ 如果 Pixiv 开启了二次验证，方法二可能失败，建议用方法一。

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
| `global_dedup_limit` | int | 100 | 全局去重数 |
| `session_dedup_limit` | int | 20 | 会话去重数 |

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

**Q: 为什么 /pixiv r18 切换后又被改回去了？**
可能是其他用户通过自然语言触发了模式切换。在设置中配置 `r18_admin_id` 可限制只有管理员能切换。

---

## 📄 许可

AGPL-3.0 License © 2026
