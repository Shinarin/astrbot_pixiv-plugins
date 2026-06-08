---
name: pixiv-plugin-dev
description: 'Development workflow for astrbot_plugin_search_pixiv_pic. Use when: starting fresh in a new environment, making code changes, preparing git commits, or updating documentation. Enforces: read AstrBot docs first before any development, NEVER git push without explicit user approval, always sync CHANGELOG.md / DEVELOPMENT.md / README.md before each push.'
argument-hint: 'Describe the task (e.g., "start fresh setup", "prepare git push", "review changes for docs")'
user-invocable: true
disable-model-invocation: false
---

# Pixiv Plugin Development Workflow

本 skill 定义了 `astrbot_plugin_search_pixiv_pic` 项目的开发工作流规范。**仅限本项目使用**。

---

## 1. 新环境初始化（Fresh Setup）

> ⚠️ **一次性流程**：以下步骤**仅在**新环境首次开发时执行一次。之后的开发任务中，直接使用已建立的项目认知进行修改，**无需**重复阅读所有文档。
>
> 触发条件：全新工作区、首次接触本项目、或用户明确说"初始化"/"从头了解"。

当在**新的开发环境**中首次打开本项目时，必须按以下顺序了解上下文：

### 1.1 了解 AstrBot 框架

先阅读 AstrBot 框架文档和插件开发文档，建立框架认知：

#### 必读文档（按顺序）

| 优先级 | 文档 | 链接 |
|--------|------|------|
| 🔴 必读 | AstrBot 主仓库 | https://github.com/AstrBotDevs/AstrBot |
| 🔴 必读 | 插件开发指南（官方文档） | https://astrbot.dev/dev/plugin.html |
| 🟡 推荐 | 星球 API 参考 | https://astrbot.dev/api/ |
| 🟡 推荐 | AstrBot 源码 `plugin/star.py` | https://github.com/AstrBotDevs/AstrBot/blob/main/astrbot/core/plugin/star.py |
| 🟡 推荐 | AstrBot 源码 `plugin/context.py` | https://github.com/AstrBotDevs/AstrBot/blob/main/astrbot/core/plugin/context.py |
| 🟢 参考 | AstrBot 源码 `message/event.py` | https://github.com/AstrBotDevs/AstrBot/blob/main/astrbot/api/message/event.py |

#### 关键 API 速查

- `Star.__init__(context, config)` → `initialize()` → `terminate()`
- `Context`: `llm_generate()`, `persona_manager`, `register_llm_tool()`, `provider_manager`
- `AstrMessageEvent`: `plain_result()`, `make_result()`, `get_session_id()`, `stop_event()`, `continue_event()`
- `@command_group()`, `.command()`, `@custom_filter()`, `@on_plugin_error()`
- 配置: `_conf_schema.json` → WebUI 自动表单 → `AstrBotConfig` 注入

### 1.2 了解本项目

按以下顺序阅读项目文档：

1. **`DEVELOPMENT.md`** — 项目架构、核心数据流、模块职责清单
2. **`README.md`** — 用户文档、功能特性、配置项说明
3. **`CHANGELOG.md`** — 版本历史、了解最近改动
4. **`metadata.yaml`** — 插件元信息
5. **`_conf_schema.json`** — 配置项 schema
6. **源码**（按依赖关系）:
   - `src/config_manager.py` → `src/dedup_manager.py` → `src/conversation_state.py`
   - `src/pixiv_client.py` → `src/intent_parser.py` → `main.py`

> ✅ 初始化完成后，后续的开发对话中直接基于已有认知工作，**不再**重复加载这些文档，除非涉及重大架构变更需要重新确认。

---

## 2. Git 工作流规则

### 🚫 严禁私自 git push

> **绝对禁止**在没有用户明确指令的情况下执行 `git push`。

- 所有 git push 操作**必须**由用户明确授权
- 即使代码已 commit，也不得自行 push
- 如果用户说"提交代码"，只执行 `git add` + `git commit`，**不**执行 `git push`
- 只有当用户明确说"push"、"推送到远程"、"git push"等指令时，才可以执行 push

### 提交流程

```
用户说"提交"/"commit" → git add + git commit（不 push）
用户说"push"/"推送"   → 先同步文档（见第3节），再 git push
```

---

## 3. 文档同步规则（Push 前必做）

**每次 git push 之前**，必须完成以下文档同步：

### 3.1 更新 `CHANGELOG.md`

在文件顶部（`# What's Changed` 下方、最新版本记录上方）添加本次改动条目：

```markdown
## 🔧 优化 / 🐛 修复 / ✨ 新增

- **改动简述**：具体说明改了什么、为什么改。
```

分类标签：
- `✨ 新增` — 新功能
- `🔧 优化` — 改进现有功能
- `🐛 修复` — Bug 修复
- `📝 文档` — 纯文档更新

### 3.2 更新 `DEVELOPMENT.md`

同步更新以下内容（如有变化）：
- **模块职责清单**（新增/删除/重命名模块）
- **核心数据流**（流程变更）
- **架构概览**（架构调整）
- **外部依赖**（依赖版本变更）
- **状态说明**（Phase 进度更新）

### 3.3 评估是否更新 `README.md`

根据改动程度决定：

| 改动类型 | 是否更新 README |
|---------|---------------|
| 新增/删除功能特性 | ✅ 必须更新 |
| 新增/删除配置项 | ✅ 必须更新 |
| 新增/删除指令 | ✅ 必须更新 |
| 使用方式变更 | ✅ 必须更新 |
| 安装步骤变更 | ✅ 必须更新 |
| 修改 `_conf_schema.json` | ✅ 必须同步更新 README 配置表 |
| Bug 修复（无功能变化） | ❌ 无需更新 |
| 内部重构（无行为变化） | ❌ 无需更新 |
| 性能优化（无行为变化） | ❌ 无需更新 |
| 纯文档/注释更新 | ❌ 无需更新 |

更新 README 时同步更新以下章节：
- `✨ 功能特性` — 新增/删除功能点
- `⚙️ 配置` — 配置项变更（**特别说明**：修改 `_conf_schema.json` 中的配置项名称、类型、默认值、选项时，必须同步更新 README 中的「完整配置项」表格）
- `📖 使用方法` — 指令或用法变更
- `📦 安装` — 安装步骤变更

### 3.4 检查 `_conf_schema.json` ↔ README 一致性

`_conf_schema.json` 是 WebUI 配置表单的定义文件，README 中的「完整配置项」表格是其面向用户的说明。**两者必须保持一致**。

修改 `_conf_schema.json` 时，检查以下字段是否在 README 配置表中同步：
- 配置项 key 名称
- `type` / `default` / `description`
- 下拉选项的 `choices` 列表
- 嵌套配置项（如 `show_image_info` 的子开关）

### 3.5 检查 `requirements.txt`

如果新增/移除/变更了 Python 依赖版本，同步更新 `requirements.txt`。

---

## 4. 代码修改规范

### 修改前

- 确认理解了 `DEVELOPMENT.md` 中的架构设计
- 确认修改不会破坏已有的核心数据流
- 涉及配置项修改时，同步更新 `_conf_schema.json` **和** README 配置表（见 3.4 节）

### 修改后

- 确保模块间接口兼容
- 不引入新的硬编码（使用 `ConfigManager` 管理配置）
- 遵循现有代码风格（类型注解、docstring、日志级别）

---

## 5. 常用参考

| 内容 | 文件 |
|------|------|
| 架构与数据流 | `DEVELOPMENT.md` |
| 用户文档 | `README.md` |
| 版本历史 | `CHANGELOG.md` |
| 模块职责 | `DEVELOPMENT.md` → 模块职责清单 |
| 配置项定义 | `_conf_schema.json` |
| 插件元数据 | `metadata.yaml` |
