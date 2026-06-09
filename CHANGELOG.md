# What's Changed

> 📢 v1.0.2 → v1.0.3

## 🐛 修复

- **修复 `context.llm_generate()` 缺少必传 `chat_provider_id`**：回退路径和审核回退路径通过 `get_all_providers()` 获取默认 provider ID，避免 TypeError
- **修复内容审核撤回 `message_id=None` 导致撤回失效**：`_check_and_moderate()` 新增 `message_id` 参数，`_send_illust_images()` 传递真实消息 ID，确保审核触发时能正确撤回
- **修复 LLM Tool 注册失败（v4.25.2+ JSON Schema 校验）**：`func_args` 中 `"int"` → `"integer"`、`"bool"` → `"boolean"`，符合 JSON Schema 类型规范

## ✨ 新增

- **多标签组合搜索**：`search_by_tags()` 优先尝试组合标签（AND 搜索）。如 "原神"+"ニコ" → "原神 ニコ"，精准定位"某游戏的某角色"，解决之前只搜单个标签命中不精准的问题
- **角色智能解析 + 联网搜索**：`resolve_search_intent()` 用 LLM 识别用户搜索中的游戏/作品+角色名。对不确定的冷门/新角色，自动调用 AstrBot 内置联网搜索工具（Tavily/Bocha/Baidu）确认角色信息，再用准确的日文名进行 Pixiv 搜索
- **内容审核日志增强**：记录发送给视觉模型的 prompt 和压缩后图片大小，以及模型返回的原始文本内容

## 🔧 优化

- **`conversation_state.is_waiting()` 锁安全**：移除查询路径中的无锁 `pop()` 操作，超时清理由 `cleanup_expired()` 统一负责
- **`config_manager.get_all()` 深拷贝**：改用 `copy.deepcopy()` 防止嵌套配置对象（如 `show_image_info`）被意外共享修改
- **`find_fresh_illust()` 回退路径增加 API 错误检测**：与 `search_by_tag()` 保持一致，检测 token 过期等 API 错误字段
- **`_extract_tag()` 噪声词优化**：按长度降序排列避免短词误伤，新增短噪声字集合精确过滤
- **临时图片文件自动清理**：新增 `_cleanup_temp_file()`，发送完成后立即删除临时文件，防止磁盘堆积
- **`DedupManager` 数据库自动重连**：新增 `_ensure_connection()` 健康检查，连接断开时自动恢复
- **修正 `astrbot_version` 最低要求**：`>=4.0.0` → `>=4.5.7`（插件依赖 `context.llm_generate()`）

## 📝 文档

- **DEVELOPMENT.md 文档完善**：修正架构图（LLM 优先→关键词回退）、补充缺失文件、新增核心方法速查表
- **新增 `.github/skills/pixiv-plugin-dev/SKILL.md`**：定义本项目专属的开发工作流规范（环境初始化、Git 规则、文档同步、代码规范）

---

> 📢 v1.0.1 → v1.0.2

## 🔧 优化

- **移除全局去重，改为纯会话独立去重**：每个会话（群聊/私聊）独立管理自己的去重记录（默认 20 条），互不干扰。避免「群A发过的图群B发不出」的问题。同时移除 `global_dedup_limit` 配置项。

## 🐛 修复

- **修复单图发送失败时误标记去重**：`mark_sent()` 从 `_send_image()` 之前移到之后，确保只有真正发送成功的作品才被标记为已发送，发送失败的作品下次搜索仍可被重新选中。

---

> 📢 v1.0.0 → v1.0.1

## 🐛 修复

- **修复 AstrBot 事件钩子 AssertionError**：`command_group("pixiv")` 父方法由 `def` 改为 `async def`，消除 `context_utils.py:94` 处的断言失败，该错误此前在每次消息处理时都会打印一条异常堆栈。

## 🔧 优化

- 完善插件元数据：更新 `repo` 字段为实际仓库地址，使插件支持 WebUI 自动更新检测。

---

<details>
<summary>📦 v1.0.0 初始版本</summary>

## ✨ 功能

- Pixiv 图片检索：支持按作品 ID (`/pixiv id`) 和标签 (`/pixiv tag`) 搜索
- 自然语言意图识别：基于 LLM 自动分类用户意图（找图/切R18/帮助/无关）
- 中文标签富化：LLM 自动将中文标签翻译为日语/英语以提升搜索命中率
- 加权随机去重：基于作品热度（bookmarks）加权随机选图，避免重复发送
- 多页漫画/图集支持：自动检测并发送多页作品，可配置最大页数
- R18 内容过滤：三种模式（safe/off/r18_only），支持管理员切换
- 定时消息撤回：可配置的自动撤回，通过 OneBot delete_msg API
- 视觉内容审核：可选启用，使用视觉 LLM 对图片进行 NSFW 评分
- 人格化回复：注入 AstrBot 当前人格提示词，生成带角色风味的自然语言回复
- 会话状态管理：支持追问澄清流程，对话上下文保持
- Token 自动刷新：50 分钟周期自动刷新 Pixiv access_token，搜索失败时自愈重试
- LLM Tool 注册：向 AstrBot Agent 注册 3 个工具（搜ID/搜标签/切R18）
- WebUI 配置面板：基于 `_conf_schema.json` 自动生成设置表单

</details>
