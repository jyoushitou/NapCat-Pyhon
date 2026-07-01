# 友利奈绪 QQ 机器人 v2.0 —— CLIP 视觉识图 + 简短动作回复 + HTTP API 服务

基于 **NapCat** 的 QQ 收发，**Python** 作为后端，调用 **DeepSeek** 网络 API 为主模型、**豆包** 网络 API 为备用模型，使用 **OpenAI CLIP (ViT-B/32, CPU)** 进行本地图片识别打标存档的 QQ 聊天机器人。

---

## 核心特性

### 0. MySQL 数据库存储
- 使用 MySQL 替代 JSON 文件存储 + txt 日志 + 环境变量密钥。
- 数据库共 **8 张表**：`logs`、`api_keys`、`global_keywords`、`user_memory`、`images`、`events`、`ai_raw_responses`、`acg_images`。
- 默认连接 `192.168.0.50:3306`，数据库 `TomoriNaoBotData`，用户 `TomoriNaoBot`。
- 日志、对话记忆、全局关键词、API 密钥全部从数据库读写，重启后自动加载。
- 表情包存档（图片文件 + JSON 索引）仍保留本地文件存储（`sticker_archive/` 目录）。
- 新图片统一存入 `images/` 目录 + `images` 数据库表。

### 1. 多轮对话记忆系统
- **私聊/群聊独立记忆**：对每个用户（私聊）和每个群（群聊）分别维护最近 **15 条** 对话记录，形成独立上下文。
- **全局关键词记忆**：从所有对话中提取高频词，长期保存（最多 **40 个**），用于丰富人设提示词。
- 记忆持久化到 **MySQL 数据库**，重启后自动加载。
- **记忆去旧逻辑**：插入新记忆时自动删除超出 15 轮的最旧记录，同时内存 `deque` 也限制 `maxlen=15`，双重保障。

### 2. 双模型兜底回复
- **主模型**：DeepSeek V4 Flash（需 `DS_API_KEY`），超时 60 秒，支持 2 次重试。
  - 异步非阻塞调用：`asyncio.to_thread` 将同步 HTTP 请求分发到子线程，不阻塞事件循环。
  - 调用详情全部日志记录：模型名、消息数、密钥有无、状态码、回复预览。
- **备用模型**：豆包（需 `ARK_API_KEY`），当 DeepSeek 失败时自动切换，最多重试 3 次（401 认证错误直接跳过不再重试）。
  - 仍失败时返回随机傲娇兜底话术（"哼(扭头)"、"才不理你(抱手)"、"切(翻白眼)"）。
- **本地话术**：两个模型都不可用时，随机返回预设的傲娇回复。
- **人设提示词**：固定为《Charlotte》友利奈绪（傲娇毒舌、外冷内热），动态注入全局关键词 + 当前对话历史 + 当前话题关键词 + 事件记忆。
- **身份区分**：对主人（配置中的 MASTER_QQ）以亲密的身份亲密对话，对其他用户保持普通朋友距离。
- **可选的在线人设补充**：支持从 URL 远程拉取人设补充文本（遍历 PERSONALITY_SUPPLEMENT_URLS 列表），也支持本地 `personality_supplement.txt` 文件加载。
- **AI 回复五行格式**（必须严格按照此格式）：
  1. 对话内容（100 字以内）
  2. 动作描写（用括号包裹，如"（扭头）"，无动作写"（无）"）
  3. 关键词搜索图片用：20 个从可用列表选取的标签（逗号分隔）
  4. 事件摘要：xxx（可带标签 | tag1,tag2,tag3）
  5. 关键词提炼：5 个关键词（逗号分隔）

### 3. CLIP 本地识图打标 & 统一图片系统
- **OpenAI CLIP (ViT-B/32)** 运行在 CPU 上，使用 **约 200 个候选标签** 对用户发送的图片进行本地识别、多标签分类。
  - 候选标签分布在 7 大类：表情包常用（20 个）、可爱系（30 个）、二次元（30 个）、场景背景（20 个）、食物（20 个）、日常（20 个）、其他补充（60 个）。
  - 推理过程在子线程中执行（`asyncio.to_thread`），不阻塞主事件循环。
  - 使用 `torch.no_grad()` 禁用梯度计算优化性能。
  - 返回前 3 个得分 > 0.01 的标签，最高分标签作为描述。
- 所有图片以 **MD5 哈希** 命名保存到 `images/` 目录，标签、来源、使用次数存入 `images` 数据库表。
- 回复时根据对话关键词，从数据库中按标签搜索匹配图片（`LIKE %kw%` 匹配，按 use_count DESC 排序），优先返回高频图。
- **ALAPI 在线搜图兜底**：本地无匹配时自动从 ALAPI 斗图接口（`/api/doutu`）或 ACG 接口（`/api/acg`）下载、打标、入库，后续可直接复用。
- **旧 sticker_archive 兼容**：启动时自动将旧存档 JSON 索引数据（`sticker_index.json`）迁入新库（`images` 表 + `sticker_archive/` 目录）。

### 4. AI 回复自动关键词补全
- 位于 `api.py` 中 `get_character_reply()` 函数的最后一步修复逻辑：
  若 AI 回复缺少图片搜索关键词行（第三行），系统自动用 **jieba 分词** 从对话内容（第一行）中提取关键词补充到回复末尾（限制前 10 个）。
- 在 `send.py` 中 `build_reply_message()` 函数的发图逻辑：
  无论 AI 是否提供图片关键词（第三行有 img_kw 还是空），始终立即用 jieba 从对话+动作中提取关键词兜底搜图（`get_best_image`），**无需等待 60 秒**。
- 旧的 `_delayed_jieba_fallback()`（延迟 60 秒后用 jieba 兜底）作为兼容保留，不再被调用。
- 回复限 **max_tokens=200**，保证回复简短精炼。
- AI 完整五行格式由 `utils.py` 中的 `parse_ai_reply()` 解析：
  - 第二行以 `（` 或 `(` 开头 → 动作
  - 含"关键词搜索图片用" → 图片关键词列表
  - 含"事件摘要" → 事件描述
  - 含"关键词提炼" → 提炼关键词
  - 不满足以上条件的中间行 → 额外对话内容追加到第一行

### 5. 定时任务 + 随机偏移
- **7 个预设场景**：催起床、周末吐槽赖床、提醒点外卖、叮嘱午睡、提醒起身、提醒晚餐、催睡觉。
- **随机偏移 ±10 分钟**，避免机械感。
- **智能起床时间**：使用 `chinesecalendar` 模块判断中国法定工作日/节假日，**工作日 7:30** 叫起床，**周末/法定节假日 8:30** 叫起床（国庆、春节等假期自动延后，调休上班日自动提前）。
- **智能催睡时间**：根据**明天**是否是工作日决定今晚催睡觉时间，**工作日前一晚 23:00**，**休息日前一晚 23:30**。
- **周末吐槽赖床**：仅非工作日触发（涵盖周末及法定节假日，`only_holiday=True`）。
- **起床/催睡时附带 ACG 二次元图片**：调 ALAPI ACG 接口获取一张二次元图片，消息后直接发送。
- **上线检测**：程序启动连接 QQ 成功后，同样发送 ACG 图片检验全链路连通性。
- **随机日常闲聊**：每天随机 2~4 个时刻（8:00~23:00），自动避开定时任务前后 60 分钟，闲聊之间也至少间隔 60 分钟。
- **闲聊话题关联事件记忆**：优先从数据库加载用户最近事件作为闲聊话题，让闲聊更加自然有记忆。
- **生日祝福**：
  - 9月6日 12:00 — 主人生日（由主人设定），自动发送生日祝福并附带生日相关图片
  - 11月13日 8:00 — 奈绪生日（Charlotte 角色生日），自动发送祝福并附带奈绪/夏洛特相关图片或 ACG 图
- **跨天自动初始化**：每天首次运行清空 `daily_trigger`、`triggered_today`，重新计算当天所有任务触发时刻和闲聊时间点（`_calc_day_tasks`）。
- **任务执行防重复**：触发前先标记 `daily_trigger.add(key)`，即使异常也不会重复触发同一任务。
- **每个定时任务使用随机自然提示**：催起床/催睡觉/提醒吃饭等场景各有 2~3 种不同的 Prompt 模板，每次随机选一个，让 AI 每次说不同的话而不是固定回复。

### 6. 对话命令系统
- 主人（MASTER_QQ）通过私聊发送 `!` 前缀命令查看/修改运行时参数。
- 非主人发送的命令被忽略（返回 False 继续走 AI 对话）。
- 支持 **21 个命令**：
  - `!help` - 显示完整帮助列表
  - `!status` - 运行状态概览（DS/豆包/CLIP 状态、工作日、对话对象数、关键词数、存档数等）
  - `!status all` - 详细参数（WebSocket 地址、心跳间隔、消息去重缓存、chinesecalendar 状态、今天的日期/星期/工作日类型）
  - `!task` - 定时任务列表与下次触发时间，含今日闲聊时间点
  - `!memory` - 对话记忆统计（总对象数，每个对象的轮数、最后消息预览）
  - `!memory <uid>` - 指定对象的记忆详情（最近 10 条）
  - `!sticker` - 表情包存档统计（总数、贡献用户数）
  - `!clip` - CLIP 状态（是否加载、候选标签数）
  - `!keywords` - 查看全局关键词（按排序显示前 40 个）
  - `!apikeys` - API 密钥状态（DS/豆包/ALAPI 是否存在）
  - `!reload` - 重新加载 API 密钥和记忆数据
  - `!set <键> <值>` - 修改配置（支持：`master_qq`、`heartbeat`）
  - `!say <内容>` - 让奈绪用 AI 回复一句话
  - `!sayg <群号> <内容>` - 让奈绪在指定群说话
  - `!img <关键词...>` - 手动搜图并发送（自动调用 get_best_image）
  - `!acg` - 获取一张 ACG 二次元图（调用 ALAPI ACG 接口）
  - `!event <uid>` - 查看指定对象的事件记忆（最近 10 条）
  - `!clear <uid>` - 清除指定对象的对话记忆和事件记录
  - `!log <行数>` - 查看最近 N 条日志（默认 20，上限 100）
  - `!db` - 数据库统计数据（图片数、记忆条数、事件条数、日志条数、关键词条数）
  - `!usage` - 最近 10 次 token 用量和使用模型（含合计统计）
  - `!uptime` - 机器人运行时长（从数据库第一条日志计算）
  - `!ping` - 测试机器人是否在线

### 7. 消息发送优化（`botv/send.py`）
- **`build_reply_message()` 核心函数**：
  1. 解析 AI 回复五行格式 → 分割为 (dialog, action, img_kw, event, refined_kw)
  2. 有对话内容 → 添加文本消息段
  3. 有动作描写 → 添加动作文本段
  4. 用 AI 提供的图片关键词（第三行 20 纬度）搜图 → 找到图则添加图片段
  5. AI 没提供关键词或 20 纬度搜不到 → **立即**用 jieba 从对话+动作提取关键词兜底搜图（不等 60s）
  6. jieba 也搜不到 → 从数据库中随机取一张本地图片
  7. 全部失败 → 不发图
- **消息逐条发送间隔 0.5 秒**，避免刷屏。
- **`send_short_reply()` 入口函数**：接收 AI 回复文本 → 调用 `build_reply_message()` 构建消息列表 → 逐条调用 `send_private_msg()` / `send_group_msg()` 通过 WebSocket 发送。
- **并发安全**：`send_private_msg()` 和 `send_group_msg()` 内部使用 `cfg.send_lock`（`asyncio.Lock`）避免 WebSocket 发送冲突。
- **`select_best_sticker()` 旧接口兼容**：查新库 images 表 → 旧存档 STICKER_DATA → QQ 表情 ID 兜底。
- **`send_sticker_private/group()` 表情包发送**：调用 `select_best_sticker()` → 文件路径用 `make_image_msg()` 构建 NapCat 图片消息，ID 字符串用 `face` 类型消息。
- **`make_image_msg()` 统一图片消息构建**：将本地路径转为 NapCat 绝对路径格式 `[{"type":"image","data":{"file":"绝对路径"}}]`。

### 8. 心跳保活（`botv/heartbeat.py`）
- **通用心跳协程** `heartbeat_monitor(label, ws_ref)`：
  - 每 `HEARTBEAT_INTERVAL=15` 秒发送一次 WebSocket ping 帧
  - `label` 参数用于日志区分（如 'QQ'）
  - `ws_ref` 是全局变量的引用（如 `cfg.active_ws_qq`），每次循环重新读取以获取最新连接
  - 只检测不处理：ping 失败只记日志，不主动关闭连接，由主循环处理重连逻辑

### 9. 日志与容错（`botv/log.py` + `botv/db.py`）
- **五级日志**：系统（初始化/定时任务等）、接收（收到的消息）、发送（发出去的内容）、接口（API 调用/图片处理/CLIP）、异常（错误捕获）
- **双写**：控制台 `print()` + MySQL 数据库 `logs` 表，数据库写入失败不影响主流程（`try/except pass`）
- **`get_recent_logs(limit)`**：从数据库按 id DESC 查询，反转使时间正序返回，带 `[时间] [级别] 内容` 格式
- **消息去重**：`cfg.PROCESSED_MSG_IDS` — `deque(maxlen=80)`，收到消息检查 message_id 是否已存在
- **消息处理锁**：`cfg.PROCESS_LOCK`（`asyncio.Lock`），防止并发处理同一消息，锁释放延迟 `LOCK_RELEASE_DELAY=0.8` 秒
- **网络容错**：图片下载失败记录日志不崩溃；模型请求重试 2~3 次；API 密钥缺失时自动降级
- **AI 原始返回保存**（`db.py` 的 `save_ai_raw_response()`）：
  - 每次模型调用结果（完整 JSON）存入 `ai_raw_responses` 表
  - 从 JSON 中提取 `usage.prompt_tokens`、`usage.completion_tokens`、`usage.total_tokens`
  - 兼容 DeepSeek 和豆包的 usage 格式
  - 记录 status：`success` / `empty_reply` / `http_error_xxx` / `auth_error` / `no_api_key`
- **自动建表和迁移**：启动时自动创建 `acg_images` 表；自动检查 `ai_raw_responses` 表的 token 字段，不存在时 ALTER TABLE
- **`get_recent_usage(limit)`**：查询最近 N 次成功调用的 token 用量统计，用于 `!usage` 命令

### 10. 事件记忆系统（`botv/db.py`）
- **`add_event_to_db(tid, event_summary, tags)`**：从对话中提取重要事件存入 `events` 表，每个对象最多保留 20 条，超出时删除最旧记录
- **`load_events_from_db(tid, tag_keywords=None, limit=5)`**：按目标 ID + 可选的标签关键词过滤（最多 3 个 LIKE 条件），返回 `[(event_summary, tags), ...]`
- **注入提示词**：在 `memory.py` 的 `build_memory_context()` 中，按当前对话关键词过滤并注入最近事件记忆，让 AI 记住用户的重要日程
- **闲聊关联**：定时闲聊触发时优先从数据库加载最近 5 条事件作为话题传递给 AI，让闲聊更自然

### 11. HTTP API 服务器（v2.0 新增 ⭐ `botv/api_server.py`）
- 基于 `aiohttp` 的异步 HTTP 服务器，监听端口 **60908**，共享 `aiohttp.ClientSession`
- 所有接口需 **Bearer Token** 验证（自动生成 32 位字母数字字符串，存入数据库 `api_keys` 表 `API_SERVER_TOKEN` 行）
- 认证中间件统一使用 `hmac.compare_digest` 安全比较，避免时序攻击
- 支持 **20 个并发** 请求（`aiohttp.TCPConnector(limit=20)`），所有响应统一 UTF-8 编码
- **接口列表**：
  - `GET /api/health` — 无需 Token，返回 `{"status":"ok","timestamp":"..."}`
  - `GET /api/status` — 运行状态 + 数据库统计（图片数、记忆数、事件数、日志数、关键词数、AI 响应数）+ 运行时数据
  - `GET /api/usage?limit=N` — 最近 N 次 AI 调用的 token 用量统计
  - `GET /api/memory?target_id=XXX` — 指定对象对话记忆详情（每条的用户/机器人消息）；不传 target_id 返回所有对象概况
  - `GET /api/logs?limit=N` — 最近 N 条日志
  - `GET /api/token` — 返回 Token 前缀、地址、端口、完整接口列表说明
  - `POST /api/chat` — 传入 `{"message":"...","target_id":"..."}`，返回 AI 回复（共享 QQ 的对话记忆和关键词系统）
  - `POST /api/command` — 传入 `{"command":"help"}`，执行 ! 命令并返回文本结果

---

## 项目结构

```
NapCat+Python/
├── run.py                    # 入口文件，python run.py 启动
├── README.md                 # 项目说明文档
├── botv.py                   # 旧版单文件（v1.x），包含所有函数和运行逻辑，已归档
├── botv/                     # v2.0 模块化功能包
│   ├── __init__.py           # 模块入口（导向 config，避免循环依赖）
│   ├── config.py             # 配置常量 + 全局运行时变量（WebSocket地址、数据库配置、超时、所有状态变量）
│   ├── db.py                 # 数据库连接池（连接池 5~20 个连接）、8 张表 CRUD 操作（含自动建表）
│   ├── log.py                # 日志系统：控制台 print() + MySQL logs 表双写，五级日志
│   ├── utils.py              # 通用工具：图片下载(base64/url)、base64编码、AI回复五行格式解析(parse_ai_reply)
│   ├── clip.py               # CLIP 模型加载（ViT-B/32 CPU）+ 图片多标签分析（约200候选标签，子线程推理）
│   ├── image.py              # 统一图片系统：下载→CLIP打标→本地存档→MD5入库→按tag搜索→ALAPI兜底
│   ├── sticker_archive.py    # 旧表情包存档兼容层：加载旧 JSON 索引 → 迁入新库/acg_images 表
│   ├── personality.py        # 人设系统：本地基础人设 + 远程/本地人设补充 + 600个候选标签分类（20纬度×30标签）
│   ├── personality_supplement.txt  # 本地人设补充文件（可选）
│   ├── memory.py             # 对话记忆与关键词管理：jieba分词、数据库CRUD、上下文构建（15轮+关键词+事件）
│   ├── api.py                # DeepSeek + 豆包 双模型调用：asyncio.to_thread异步、2~3次重试、原始JSON保存、自动关键词补全
│   ├── send.py               # 消息发送与选图策略：五行解析→文本+动作+图片→WebSocket发送（含0.5秒间隔、并发锁）
│   ├── commands.py           # ! 命令系统：23个命令，主人才可调用，解析→执行→发结果
│   ├── schedule.py           # 定时任务：7个场景+随机闲聊+生日祝福，chinesecalendar工作日判断，跨天自动初始化
│   ├── heartbeat.py          # WebSocket 心跳保活：通用协程，每 15 秒 ping，只检测日志不处理
│   ├── handler.py            # QQ 消息处理主循环：消息解析→去重→命令/表情包/AI回复→发送
│   ├── api_server.py         # HTTP API 服务器：aiohttp 端口 60908，Bearer Token认证，8个REST接口
│   └── main.py               # async def main() 启动函数：初始化各模块→启动WebSocket+API+心跳+定时
├── images/                   # 新图片存储目录（自动创建，MD5哈希命名）
└── sticker_archive/          # 旧表情包存档目录（sticker_index.json + 图片文件）
```

---

## 数据库建表

提前创建数据库及 8 张表：

```sql
CREATE DATABASE IF NOT EXISTS TomoriNaoBotData;
USE TomoriNaoBotData;

CREATE TABLE logs (
    id INT AUTO_INCREMENT PRIMARY KEY,
    level VARCHAR(10) NOT NULL COMMENT '日志级别：系统/接收/发送/接口/异常',
    message TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE api_keys (
    id INT AUTO_INCREMENT PRIMARY KEY,
    key_name VARCHAR(50) NOT NULL UNIQUE COMMENT '密钥名称，如 DS_API_KEY / ARK_API_KEY / ALAPI_TOKEN / API_SERVER_TOKEN',
    key_value VARCHAR(255) NOT NULL,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
);

INSERT INTO api_keys (key_name, key_value) VALUES ('DS_API_KEY', 'your_deepseek_key');
INSERT INTO api_keys (key_name, key_value) VALUES ('ARK_API_KEY', 'your_doubao_key');
INSERT INTO api_keys (key_name, key_value) VALUES ('ALAPI_TOKEN', 'your_alapi_token');
-- API_SERVER_TOKEN 由程序首次启动时自动生成并写入

CREATE TABLE global_keywords (
    id INT AUTO_INCREMENT PRIMARY KEY,
    keyword VARCHAR(50) NOT NULL UNIQUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE user_memory (
    id INT AUTO_INCREMENT PRIMARY KEY,
    target_id VARCHAR(50) NOT NULL COMMENT '私聊用QQ号，群聊用群号',
    user_msg TEXT NOT NULL,
    bot_msg TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_target_id (target_id)
);

CREATE TABLE images (
    id INT AUTO_INCREMENT PRIMARY KEY,
    md5_hash VARCHAR(32) NOT NULL UNIQUE,
    image_data MEDIUMBLOB COMMENT '图片二进制数据',
    tags VARCHAR(255) DEFAULT '' COMMENT 'CLIP标签，逗号分隔',
    source_url VARCHAR(512) DEFAULT '' COMMENT '来源URL',
    file_path VARCHAR(255) DEFAULT '' COMMENT '本地文件路径',
    ext VARCHAR(10) DEFAULT 'jpg' COMMENT '文件扩展名',
    use_count INT DEFAULT 0 COMMENT '使用次数',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE events (
    id INT AUTO_INCREMENT PRIMARY KEY,
    target_id VARCHAR(50) NOT NULL,
    event_summary VARCHAR(255) NOT NULL COMMENT '事件摘要',
    tags VARCHAR(100) DEFAULT '' COMMENT '事件相关标签，逗号分隔',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_target_id (target_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE ai_raw_responses (
    id INT AUTO_INCREMENT PRIMARY KEY,
    model_name VARCHAR(50) NOT NULL COMMENT '模型名称，如 DeepSeek(deepseek-v4-flash)',
    user_msg TEXT COMMENT '用户消息',
    raw_response_json JSON COMMENT 'AI返回的完整JSON',
    response_text TEXT COMMENT '提取的回复文本',
    target_id VARCHAR(50) DEFAULT '' COMMENT '对话目标ID',
    status VARCHAR(20) DEFAULT '' COMMENT '状态：success/empty_reply/http_error/auth_error等',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    prompt_tokens INT DEFAULT 0 COMMENT '输入token数',
    completion_tokens INT DEFAULT 0 COMMENT '输出token数',
    total_tokens INT DEFAULT 0 COMMENT '总token数'
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- acg_images 表由程序启动时自动创建，结构与 images 表一致，用于缓存ACG二次元图片
```

---

## Python 依赖

```bash
pip install websockets requests urllib3 jieba Pillow pymysql chinesecalendar aiohttp
```

**CLIP 额外依赖（可选，不影响核心功能）：**
```bash
pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu
pip install git+https://github.com/openai/CLIP.git
```
> 若未安装 CLIP 依赖，程序会禁用 CLIP 识图功能，仅做普通图片存档。

**NapCat 配置：**
- NapCat 网络配置中添加 WebSocket 客户端地址：`ws://127.0.0.1:3001`

---

## 启动流程

1. **创建 MySQL 数据库** `TomoriNaoBotData` 并执行建表 SQL。
2. 在 `api_keys` 表中插入你的 DeepSeek、豆包、ALAPI 密钥（`API_SERVER_TOKEN` 由程序自动生成）。
3. **启动 NapCat** 或兼容的 QQ 客户端。
4. **运行入口文件**：
   ```bash
   python run.py
   ```
5. 程序启动时自动执行以下初始化流程（`main.py` 的 `async def main()`）：
   - **日志系统初始化**：设置 MySQL 数据库日志表
   - **加载对话记忆**：从 MySQL 加载所有对话历史到内存 deque
   - **加载全局关键词**：从 MySQL 加载关键词列表
   - **初始化图片系统**：创建 `images/` 目录，迁移旧版 JSON 索引到新库
   - **加载 API 密钥**：从 MySQL `api_keys` 表加载所有密钥
   - **加载 CLIP 模型**：检查并加载 CLIP ViT-B/32（CPU），约 1~3 秒
   - **加载人设补充**：远程 URL 拉取 → 失败则加载本地 `personality_supplement.txt`
   - **创建 acg_images 表**：自动创建并检查 token 字段
   - **启动 HTTP API 服务器**：监听 `0.0.0.0:60908`，自动生成 API Token
   - **启动 WebSocket 服务**：监听 `0.0.0.0:3001`，等待 QQ 客户端连接
   - **启动心跳监控**：每 15 秒发送 ping 帧检测连接
   - **启动定时任务循环**：7 个场景 + 随机闲聊 + 生日祝福
   - **启动上线检测**：连接成功后向主人发送上线提示（文字 + ACG 图片）

---

## 各模块核心函数一览

| 模块 | 函数 | 说明 |
|------|------|------|
| `db.py` | `init_db_pool()` | 初始化数据库连接池（5~20 连接），支持自动重连 |
| `db.py` | `ensure_tables()` | 自动创建 8 张表，检查并迁移 token 字段 |
| `db.py` | `get/set_api_key()` | 读取/更新 API 密钥 |
| `db.py` | `add/load/clear_memory()` | 对话记忆的增删查 |
| `db.py` | `add/load_keywords()` | 全局关键词的增查（最多 40 个） |
| `db.py` | `save_image()` | 保存图片信息到数据库 |
| `db.py` | `get_best_image()` | 按标签搜索最佳图片（LIKE + use_count 排序） |
| `db.py` | `get_random_image()` | 随机获取一张本地图片 |
| `db.py` | `add_event_to_db/load_events_from_db()` | 事件记忆的增查 |
| `db.py` | `save_ai_raw_response()` | 保存 AI 调用原始 JSON |
| `db.py` | `get_recent_logs/usage()` | 日志和用量查询 |
| `log.py` | `log_system/receive/send/interface/error()` | 五级日志记录 |
| `utils.py` | `parse_ai_reply()` | 解析 AI 五行格式回复 |
| `utils.py` | `download_image_base64/url()` | 图片下载（base64/URL 两种方式） |
| `clip.py` | `get_clip_instance()` | 懒加载获取 CLIP 模型实例 |
| `clip.py` | `analyze_image()` | 分析图片返回多标签（子线程异步） |
| `image.py` | `process_save_image()` | 保存一张新图片（下载→CLIP打标→入库） |
| `image.py` | `download_image_tags()` | 从 ALAPI 斗图接口搜图并打标入库 |
| `image.py` | `save_acg_image()` | 从 ALAPI ACG 接口获取二次元图并缓存 |
| `memory.py` | `save_chat_to_db()` | 保存对话到数据库 + 更新内存 |
| `memory.py` | `build_memory_context()` | 构建提示词中的对话历史上下文 |
| `api.py` | `get_character_reply()` | 双模型调用核心函数（DS→豆包→兜底） |
| `send.py` | `send_short_reply()` | 发送 AI 回复（文本+动作+图片） |
| `send.py` | `send_private_msg/group_msg()` | WebSocket 发送单条消息 |
| `send.py` | `make_image_msg()` | 构建 NapCat 图片消息格式 |
| `commands.py` | `handle_command()` | 处理 ! 前缀命令入口 |
| `schedule.py` | `schedule_loop()` | 定时任务主循环 |
| `handler.py` | `handle_qq_message()` | QQ 消息处理入口 |
| `api_server.py` | `run_api_server()` | 启动 HTTP API 服务器 |
| `heartbeat.py` | `heartbeat_monitor()` | 通用心跳监控协程 |
| `main.py` | `main()` | 主启动函数 |

---

## 代码注释说明

所有核心模块均已添加**统一风格**的逐行中文注释，便于理解和二次开发：

| 文件 | 说明 | 注释风格 |
|------|------|---------|
| `botv/config.py` | 配置常量 + 全局运行时变量 | ✅ 模块注释 + 行内注释 |
| `botv/db.py` | 数据库连接池、建表、CRUD 操作（8张表） | ✅ 模块注释 + 函数文档 + 行内注释 |
| `botv/log.py` | 日志系统（控制台 + MySQL 双写，五级日志） | ✅ 模块注释 + 函数文档 |
| `botv/utils.py` | 通用工具函数（下载、base64编码、AI回复五行格式解析） | ✅ 模块注释 + 函数文档 + 行内注释 |
| `botv/clip.py` | CLIP 模型加载（ViT-B/32 CPU）与图片多标签分析 | ✅ 模块注释 + 函数文档 + 行内注释 |
| `botv/image.py` | 统一图片系统（下载→CLIP打标→本地存档→入库→按tag搜索→复用） | ✅ 模块注释 + 函数文档 + 行内注释 |
| `botv/sticker_archive.py` | 旧表情包存档兼容层（加载旧JSON索引→迁入新库） | ✅ 模块注释 + 函数文档 + 行内注释 |
| `botv/personality.py` | 人设系统（本地基础人设 + 远程/本地补充 + 600个候选标签分类） | ✅ 模块注释 + 函数文档 + 行内注释 |
| `botv/memory.py` | 对话记忆与关键词管理（jieba分词、数据库CRUD、上下文构建） | ✅ 模块注释 + 函数文档 + 行内注释 |
| `botv/api.py` | DeepSeek + 豆包 双模型调用（异步重试、原始JSON保存、自动关键词补全） | ✅ 模块注释 + 函数文档 + 行内注释 |
| `botv/send.py` | 消息发送与选图策略（五行解析→文本+动作+图片→WebSocket发送） | ✅ 模块注释 + 函数文档 + 行内注释 |
| `botv/commands.py` | ! 命令系统（21个命令：help/status/task/memory/sticker/clip等） | ✅ 模块注释 + 函数文档 + 行内注释 |
| `botv/schedule.py` | 定时任务 + 工作日判断（7个场景、chinesecalendar、闲聊、生日祝福） | ✅ 模块注释 + 函数文档 + 行内注释 |
| `botv/heartbeat.py` | WebSocket 心跳保活（通用协程，每15秒ping） | ✅ 模块注释 + 函数文档 + 行内注释 |
| `botv/handler.py` | QQ 消息处理主循环（消息解析→命令/表情包/AI回复→发送） | ✅ 模块注释 + 函数文档 + 行内注释 |
| `botv/api_server.py` | HTTP API 服务器（端口60908，Bearer Token认证，8个接口） | ✅ 模块注释 + 函数文档 + 行内注释 |
| `botv/main.py` | 主程序入口（初始化各模块→启动WebSocket+API+心跳+定时） | ✅ 模块注释 + 函数文档 + 行内注释 |
| `botv/__init__.py` | 模块入口 | ✅ 模块注释 |

### 统一注释风格规范

所有代码文件遵循以下注释规范：

| 注释类型 | 格式 | 示例 |
|---------|------|------|
| **模块级注释** | `# ===================== 模块名 =====================` + 功能说明 | `# ===================== 配置模块 =====================` |
| **函数文档字符串** | `"""功能说明"""`（单行）或带参数说明的多行 | `def log_system(m): """系统级日志"""` |
| **行内注释** | `# 说明`（与代码保持2个空格间隔） | `CST = timezone(timedelta(hours=8))  # 东八区（北京时间）` |
| **代码块分隔** | `# ===================== 标题 =====================` | `# ===================== 配置常量 =====================` |
| **全局变量注释** | `# 说明`（与变量同行） | `active_ws_qq=None  # 当前活跃的QQ WebSocket连接` |

---

## 写在最后
- 目前该程序已在 **联想小新 Air14 2018（Intel 8250U + MX150 + 16G）** 上成功运行，CLIP CPU 推理单张图片约 1~3 秒。因为cpu比较老旧，从拿到消息，到api回复几毫秒，但是对于图片处理，仍需1min左右，由于没有的对照的部署，仍未知其是哪里拖慢了发送解析。
- 人设、定时任务时间、API 端点、数据库配置等均可按需修改（`botv/config.py`）。
- 运行文件：**`run.py`**（模块化版），旧版单文件 **`botv.py`**（v1.x，包含所有函数和运行逻辑）已归档保留。
- 所有代码文件均已添加统一风格的逐行中文注释，便于二次开发和维护。