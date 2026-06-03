# 🛠️ astrbot_pixiv-plugins 开发文档

> 本文档旨在帮助新开发者快速了解项目结构、核心架构和开发约定。
> 如需更换开发 Agent，请先阅读本文档。

---

## 📂 项目结构一览

```
astrbot_pixiv-plugins/
├── main.py                   # 🔴 插件入口 — Star 类 + 所有 handler
├── metadata.yaml             # 🟡 AstrBot 插件元信息
├── requirements.txt          # 🟡 Python 依赖
├── README.md                 # 🟢 用户文档
├── DEVELOPMENT.md            # 🟢 本文档
└── src/                      # 🔴 核心逻辑
    ├── __init__.py            #   包初始化
    ├── pixiv_client.py        #   Pixiv API 封装
    ├── intent_parser.py       #   LLM 意图分类
    ├── dedup_manager.py       #   去重管理
    ├── config_manager.py      #   配置管理
    └── conversation_state.py  #   对话状态机
```

🔴 = 核心代码，修改需谨慎 | 🟡 = 配置文件 | 🟢 = 文档

---

## 🏛️ 架构概览

```
                        ┌─────────────────────┐
                        │    用户消息          │
                        └─────────┬───────────┘
                                  │
                        ┌─────────▼───────────┐
                        │   main.py            │
                        │   AstrBotPixivPlugin │
                        │   (Star 基类)        │
                        └──┬──────┬──────┬────┘
                           │      │      │
              ┌────────────▼┐  ┌──▼──┐  └──────────────┐
              │ /pixiv 指令  │  │ NL  │                 │
              │ 直接路由     │  │拦截器│                 │
              └──────┬──────┘  └──┬──┘                 │
                     │            │                     │
              ┌──────▼────────────▼──────┐              │
              │   intent_parser.py       │              │
              │   ┌──────────────────┐   │              │
              │   │ 快速关键词匹配   │   │              │
              │   │       ↓          │   │              │
              │   │ LLM 深度分类     │   │              │
              │   └──────────────────┘   │              │
              └──────────┬───────────────┘              │
                         │                              │
          ┌──────────────┼──────────────┐               │
          │              │              │               │
    ┌─────▼─────┐ ┌──────▼──────┐ ┌────▼─────┐        │
    │FIND_BY_ID │ │FIND_BY_TAG  │ │UNKNOWN   │        │
    └─────┬─────┘ └──────┬──────┘ └────┬─────┘        │
          │              │              │               │
    ┌─────▼──────────────▼──────┐ ┌────▼──────────┐    │
    │  pixiv_client.py          │ │conversation_   │    │
    │  ┌──────────────────┐    │ │state.py (反问) │    │
    │  │ search_by_id()   │    │ └────────────────┘    │
    │  │ search_by_tag()  │    │                        │
    │  │ download_image() │    │                        │
    │  └────────┬─────────┘    │                        │
    └───────────┼──────────────┘                        │
                │                                       │
    ┌───────────▼───────────────┐                      │
    │  dedup_manager.py         │                      │
    │  全局100 + 会话20 去重    │                      │
    └───────────┬───────────────┘                      │
                │                                       │
    ┌───────────▼───────────────┐                      │
    │  config_manager.py        │◄─────────────────────┘
    │  R18开关 / Token / 限制   │
    └───────────────────────────┘
```

### 搜索管线（search_by_tag → find_fresh_illust → 加权随机）

```
search_by_tag(tag, page=N)          ← 每页返回全部合格作品（R18/质量/黑名单过滤后）
  │                                   不随机、不采样，按收藏降序
  ▼
find_fresh_illust(tag, session_id)  ← 遍历 1~max_pages 页
  │   for page in 1..max_pages:
  │       results = search_by_tag(tag, page)
  │       for info in results:
  │           if not dedup.is_duplicate(info.id, session_id):
  │               fresh_pool.append(info)     ← 收集全部未发送作品
  │
  ▼
加权随机选图                            ← 最后一步才随机
      weights = [info.bookmarks + 1 for info in fresh_pool]
      picked = random.choices(fresh_pool, weights=weights, k=1)[0]
```

> ⚠️ **架构要点**: 随机必须在去重之后。如果先去重前随机采样，可能抽到的全是已发送作品，
> 导致"明明 Pixiv 有图却搜不到"。当前设计确保新鲜池 = 全部可用的未发送作品，不会遗漏。

---

## 🔄 核心数据流

### 1. 显式指令流程

```
用户: /pixiv id 12345678
  → @filter.command_group("pixiv") → cmd_pixiv_id()
  → pixiv_client.search_by_id(12345678)
  → config_mgr.is_r18_enabled 检查
  → dedup_mgr.mark_sent()
  → pixiv_client.download_image()
  → event.make_result().file_image() 发送
```

### 2. 自然语言流程

```
用户: "找一张猫娘的 pixiv 图"
  → PixivMessageFilter 预过滤（群聊@检测）
  → natural_language_handler()
  → 清理 @前缀、跳过 /pixiv 指令
  → 检查 WAITING_CLARIFICATION 状态
  → intent_parser.parse() → LLM 分类 (6 种意图)
  → FIND_BY_TAG → _nl_find_by_tag()
    → 提取 count (LLM 识别张数)
    → enrich_tags() 标签富化
    → inject_persona() 注入人格
    → generate_search_reply() 拟人化提示
    → search_by_tags() 多标签搜索+质量回退
    → download_image() + 发送
  → NOT_IMAGE_REQUEST → clear_result() + continue_event() 透传
```

### 3. 反问流程

```
用户: "来张图" (模糊)
  → intent_parser.parse() → UNKNOWN
  → _nl_unknown() → generate_clarification()
  → conv_state.set_waiting() → WAITING_CLARIFICATION
  → 回复: "🤔 请问您想搜索什么主题/标签的图片呢？"

用户: "随便" (仍模糊)
  → natural_language_handler()
  → is_waiting(session_id) = True
  → _handle_clarification_response()
  → intent_parser.parse("随便") → 仍 UNKNOWN
  → 回复: "😔 抱歉，仍然无法理解..." → 终止
  → conv_state.clear()
```

---

## 📦 模块职责清单

| 模块 | 文件 | 核心类 | 职责 |
|------|------|--------|------|
| **入口** | `main.py` | `AstrBotPixivPlugin` | 命令注册、消息拦截、流程编排 |
| **Pixiv** | `src/pixiv_client.py` | `PixivClient` | API 封装、认证、下载、加权随机选图、标签黑名单 |
| **意图** | `src/intent_parser.py` | `IntentParser` | LLM 分类、反问生成、关键词匹配 |
| **去重** | `src/dedup_manager.py` | `DedupManager` | SQLite 记录、重复检查 |
| **配置** | `src/config_manager.py` | `ConfigManager` | 配置读写、持久化 |
| **状态** | `src/conversation_state.py` | `ConversationStateManager` | 对话状态、超时清理 |

---

## 🔌 外部依赖

| 依赖 | 版本 | 用途 |
|------|------|------|
| `pixivpy3` | ≥3.0.0 | Pixiv 非官方 API |
| `httpx` | ≥0.25.0 | 异步 HTTP 客户端（图片下载） |
| `Pillow` | ≥10.0.0 | 图片处理（可选） |
| `AstrBot` | ≥4.0.0 | 插件框架（隐式依赖） |

---

## 🧪 状态说明

### 当前进度

| Phase | 状态 | 完成内容 |
|-------|------|---------|
| Phase 1: 项目骨架 | ✅ 完成 | metadata.yaml, requirements.txt, main.py 骨架 |
| Phase 2: Pixiv API | ✅ 完成 | pixiv_client.py (search_by_id/tag, download) |
| Phase 3: 去重管理 | ✅ 完成 | dedup_manager.py (SQLite 双层去重) |
| Phase 4: 配置管理 | ✅ 完成 | config_manager.py (6 个配置项) |
| Phase 5: 状态机+意图 | ✅ 完成 | conversation_state.py + intent_parser.py |
| Phase 6: 主逻辑集成 | ✅ 完成 | main.py 完整版 (所有 handler + NL 拦截器) |
| Phase 7: 测试验证 | ⬜ 待做 | 单元测试 + 集成测试 |

### 已知限制

1. **LLM 调用依赖 AstrBot 环境**: `intent_parser.py` 中的 LLM 分类需要 AstrBot 的 `event.request_llm()` 可用
2. **Pixiv API 稳定性**: 依赖 pixivpy3 和非官方 API，可能因 Pixiv 更新而失效
3. **无图片缓存**: 每次从 Pixiv CDN 实时获取，无本地缓存
4. **配置存储**: 优先使用 AstrBot 内置配置，回退到本地 JSON
5. **热度排序需 Premium**: `popular_desc` 排序需要 Pixiv Premium，否则自动回退为时间排序

### 待扩展功能

- [x] 多图智能发送（LLM 识别数量）
- [x] 加权随机选图（去重后从新鲜池随机）
- [x] 标签黑名单
- [ ] 画师搜索
- [ ] 排行榜浏览
- [ ] WebUI 管理面板
- [ ] 本地图片缓存
- [ ] 搜索结果分页浏览

---

## 📝 代码约定

### 注释规范

- 所有类和方法都必须有 docstring（Google 风格）
- 复杂逻辑必须在注释中解释原因
- 使用 `# ---` 分隔代码段
- 日志标签统一为 `[pixiv:模块名]`

### 命名约定

- 类名: PascalCase (`PixivClient`, `DedupManager`)
- 方法/函数: snake_case (`search_by_id`, `is_duplicate`)
- 私有方法: 前缀 `_` (`_cleanup_global`, `_ensure_logged_in`)
- 常量: UPPER_SNAKE_CASE (`DEFAULT_CONFIG`, `STATE_TIMEOUT`)

### 错误处理

- Pixiv 相关的自定义异常在 `pixiv_client.py` 中定义
- 所有网络/API 异常都必须捕获并转换为友好提示
- 使用 `logger.error()` 记录完整 traceback

---

## 🚀 快速上手（新 Agent）

1. **阅读本文档**（你正在读 ✅）
2. **看 `main.py`** — 了解命令注册和消息拦截模式
3. **看 `src/pixiv_client.py`** — 了解 Pixiv API 交互
4. **看 `src/intent_parser.py`** — 了解 LLM prompt 设计
5. **运行测试** — `python -m pytest tests/`
6. **开始修改** — 修改前先创建新分支

---

## 📞 联系方式

- AstrBot 官方: https://github.com/AstrBotDevs/AstrBot
- pixivpy3 文档: https://github.com/upbit/pixivpy
- Pixiv: https://www.pixiv.net
