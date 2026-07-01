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

### 2. 双模型兜底回复
- **主模型**：DeepSeek V4 Flash（需 `DS_API_KEY`），超时 60 秒，支持 2 次重试。
- **备用模型**：豆包（需 `ARK_API_KEY`），当 DeepSeek 失败时自动切换，最多重试 3 次（401 认证错误直接跳过）。
- **本地话术**：两个模型都不可用时，随机返回预设的傲娇回复（如"哼(扭头)"）。
- **人设提示词**：固定为《Charlotte》友利奈绪（傲娇毒舌、外冷内热），动态注入全局关键词 + 当前对话历史 + 当前话题关键词 + 事件记忆。
- **身份区分**：对主人（配置中的 MASTER_QQ）以女友身份亲密对话，对其他用户保持普通朋友距离。
- **可选的在线人设补充**：支持从 URL 远程拉取人设补充文本，也支持本地 `personality_supplement.txt` 文件加载。
- **AI 回复五行格式**：对话内容、动作描写、图片搜索关键词（20纬度×30标签共600个候选）、事件摘要、关键词提炼。

### 3. CLIP 本地识图打标 & 统一图片系统（）
- **OpenAI CLIP (ViT-B/32)** 运行在 CPU 上，使用 **约 200 个候选标签** 对用户发送的图片进行本地识别、多标签分类。
- 所有图片以 **MD5 哈希** 命名保存到 `images/` 目录，标签、来源、使用次数存入 `images` 数据库表。
- 回复时根据对话关键词，从数据库中按标签搜索匹配图片（按使用次数排序），优先返回高频图。
- **ALAPI 在线搜图兜底**：本地无匹配时自动从 ALAPI 斗图/ACG 接口下载、打标、入库，后续可直接复用。
- **旧 sticker_archive 兼容**：启动时自动将旧存档 JSON 索引数据迁入新库（`images` 表 + `sticker_archive/` 目录）。

### 4. AI 回复自动关键词补全
- 若 AI 回复缺少图片搜索关键词行（第三行），系统自动用 **jieba 分词** 从对话内容中提取关键词补充到回复中。
- 无论 AI 是否提供图片关键词，始终立即用 jieba 从对话+动作中提取关键词兜底搜图，无需等待 60 秒。
- 回复限 **max_tokens=200**，保证回复简短精炼。

### 5. 定时任务 + 随机偏移
- **7 个预设场景**：催起床、周末吐槽赖床、提醒点外卖、叮嘱午睡、提醒起身、提醒晚餐、催睡觉。
- **随机偏移 ±10 分钟**，避免机械感。
- **智能起床时间**：使用 `chinesecalendar` 模块判断中国法定工作日/节假日，**工作日 7:30** 叫起床，**周末/法定节假日 8:30** 叫起床（国庆、春节等假期自动延后，调休上班日自动提前）。
- **智能催睡时间**：根据明天是否是工作日决定今晚催睡觉时间，**工作日前一晚 23:00**，**休息日前一晚 23:30**。
- **周末吐槽赖床**：仅非工作日触发（涵盖周末及法定节假日）。
- **起床/催睡时附带 ACG 二次元图片**：调 ALAPI ACG 接口获取一张二次元图片，消息后直接发送。
- **上线检测**：程序启动连接 QQ 成功后，同样发送 ACG 图片检验全链路连通性。
- **随机日常闲聊**：每天随机 2~4 个时刻（8:00~23:00），自动避开定时任务前后 60 分钟，闲聊之间也至少间隔 60 分钟。
- **闲聊话题关联事件记忆**：优先从数据库加载用户最近事件作为闲聊话题，让闲聊更加自然有记忆。
- **生日祝福**：9月6日（主人设定的生日）12:00 自动发送生日祝福；11月13日（奈绪生日/Charlotte角色生日）8:00 自动发送生日祝福。

### 6. 对话命令系统
- 主人（MASTER_QQ）通过私聊发送 `!` 前缀命令查看/修改运行时参数。
- 支持 **23 个命令**：
  - `!help` - 显示帮助
  - `!status` / `!status all` - 运行状态概览/详细参数
  - `!task` - 定时任务列表与下次触发时间
  - `!memory` / `!memory <uid>` - 对话记忆统计/指定对象记忆详情
  - `!sticker` - 表情包存档统计
  - `!clip` - CLIP 状态
  - `!keywords` - 全局关键词
  - `!apikeys` - API 密钥状态
  - `!reload` - 重新加载 API 密钥和记忆
  - `!set <键> <值>` - 修改配置（支持 `master_qq`、`heartbeat`）
  - `!say <内容>` - 让奈绪主动说一句话
  - `!sayg <群号> <内容>` - 在指定群说话
  - `!img <关键词>` - 手动搜图并发送
  - `!acg` - 获取一张 ACG 二次元图
  - `!event <uid>` - 查看事件记忆
  - `!clear <uid>` - 清除对话记忆和事件记录
  - `!log <行数>` - 查看最近日志（默认 20 行）
  - `!db` - 数据库统计数据
  - `!usage` - 最近 10 次 token 用量和使用模型
  - `!uptime` - 机器人运行时长
  - `!ping` - 测试机器人是否在线

### 7. 消息发送优化
- **对话 + 动作分离**：对话内容与动作描写分行发送，动作后附带匹配的图片。
- **图片优先匹配**：根据关键词从 `images` 数据库按标签 + 使用次数选最合适的图片。
- **并发锁**：使用 `send_lock` 避免 WebSocket 发送冲突。
- **消息逐条发送间隔 0.5 秒**，避免刷屏。

### 8. 心跳保活
- 每隔 **15 秒** 发送 WebSocket ping 帧，检测连接是否存活。
- 若 ping 失败，自动清空连接状态，由主循环处理重连。

### 9. 日志与容错
- **控制台 + MySQL 数据库** 双写日志（系统/接收/发送/接口/异常 五级）。
- **消息去重**：缓存最近 80 条已处理消息 ID，避免重复响应。
- **消息处理锁**：使用 `asyncio.Lock` 防止并发处理同一消息，锁释放延迟 0.8 秒。
- **网络容错**：图片下载、模型请求均带重试机制；API 密钥缺失时自动降级。
- **AI 原始返回保存**：每次模型调用结果（完整 JSON）存入 `ai_raw_responses` 表，包含 `prompt_tokens`、`completion_tokens`、`total_tokens` 用量统计。
- **自动建表和迁移**：启动时自动检查 `ai_raw_responses` 表的 token 字段，不存在时自动 ALTER TABLE 升级。

### 10. 事件记忆系统
- 从对话中提取重要事件（如"今天考试""明天出去玩"），存入 `events` 数据库表。
- 在构建提示词时按当前对话关键词过滤注入最近事件记忆，让 AI 记住用户的重要日程。
- 每个用户最多保留 20 条事件，支持按标签关键词（最多 3 个）过滤检索。

### 11. HTTP API 服务器（v2.0 新增 ⭐）
- 基于 `aiohttp` 的异步 HTTP 服务器，监听端口 **60908**。
- 所有接口需 **Bearer Token** 验证（自动生成并存入数据库 `api_keys` 表）。
- 支持 **20 个并发** 请求，所有响应统一 UTF-8 编码。
- **健康检查** `GET /api/health` — 无需 Token，返回服务状态和时间戳。
- **状态接口** `GET /api/status` — 返回机器人运行状态、数据库统计（图片数、记忆数、事件数、日志数、关键词数、AI 响应数）、运行时数据。
- **用量接口** `GET /api/usage?limit=10` — 返回最近 N 次 AI 调用的 token 用量统计。
- **记忆接口** `GET /api/memory?target_id=` — 查询指定对象的对话记忆详情，不传 target_id 返回所有对象的概况。
- **日志接口** `GET /api/logs?limit=20` — 获取最近 N 条日志。
- **Token 信息** `GET /api/token` — 返回 Token 前缀、地址、端口、完整接口列表。
- **对话接口** `POST /api/chat` — 传入 `message` + `target_id`（必填，用于记忆隔离），返回和 QQ 完全一致的 AI 回复，共享记忆系统。
- **命令接口** `POST /api/command` — 执行 `!` 命令（如 `help`、`status`、`memory` 等）并返回文本结果。
- **认证中间件**：统一使用 `hmac.compare_digest` 安全比较 Token，避免时序攻击。

---

## 项目结构

```
NapCat+Python/
├── run.py                    # 入口文件，python run.py 启动
├── README.md                 # 项目说明文档
├── botv.py                   # 旧版单文件（v1.x），包含所有函数和运行逻辑，已归档
├── botv/                     # v2.0 模块化功能包
│   ├── __init__.py           # 模块入口（避免循环依赖）
│   ├── config.py             # 配置常量 + 全局运行时变量
│   ├── db.py                 # 数据库连接与操作（8张表）
│   ├── log.py                # 日志系统（控制台 + MySQL 双写）
│   ├── utils.py              # 通用工具（下载、base64编码、AI回复解析）
│   ├── clip.py               # CLIP 模型加载与图片分析
│   ├── image.py              # 统一图片系统（下载→打标→入库→搜索）
│   ├── sticker_archive.py    # 旧表情包存档兼容层
│   ├── personality.py        # 人设系统（本地 + 远程补充）
│   ├── personality_supplement.txt  # 本地人设补充文件
│   ├── memory.py             # 对话记忆与关键词管理
│   ├── api.py                # DeepSeek + 豆包 双模型调用
│   ├── send.py               # 消息发送与选图策略
│   ├── commands.py           # ! 命令系统（23个命令）
│   ├── schedule.py           # 定时任务 + 工作日判断
│   ├── heartbeat.py          # WebSocket 心跳保活
│   ├── handler.py            # QQ 消息处理主循环
│   ├── api_server.py         # HTTP API 服务器（端口 60908）
│   └── main.py               # async def main() 启动函数
├── images/                   # 新图片存储目录（自动创建）
└── sticker_archive/          # 旧表情包存档目录
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
2. 在 `api_keys` 表中插入你的 DeepSeek、豆包、ALAPI 密钥（API_SERVER_TOKEN 程序自动生成）。
3. **启动 NapCat** 或兼容的 QQ 客户端。
4. **运行入口文件**：
   ```bash
   python run.py
   ```
5. 程序启动时自动：
   - 从 MySQL 加载对话记忆和全局关键词
   - 初始化表情包存档目录，迁移旧版 JSON 索引到新库
   - 从 MySQL 加载 API 密钥
   - **加载 CLIP 模型（CPU）**，用于识图打标（约 1~3 秒/张）
   - 尝试远程拉取人设补充文本（失败则加载本地 `personality_supplement.txt`）
   - 自动创建 `acg_images` 表并检查 `ai_raw_responses` 表的 token 字段
   - 启动 HTTP API 服务器（监听 `0.0.0.0:60908`），自动生成 API Token
   - 启动 WebSocket 服务（监听 `0.0.0.0:3001`），等待 QQ 连接
   - 启动心跳监控（每 15 秒 ping）
   - 启动定时任务循环（7 个场景 + 随机闲聊）
   - 连接成功后向主人发送上线提示（文字 + ACG 图片）

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
| `botv/commands.py` | ! 命令系统（23个命令：help/status/task/memory/sticker/clip等） | ✅ 模块注释 + 函数文档 + 行内注释 |
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
- 目前该程序已在 **联想小新 Air14 2018（Intel 8250U + MX150 + 16G）** 上成功运行，CLIP CPU 推理单张图片约 1~3 秒。
- 人设、定时任务时间、API 端点、数据库配置等均可按需修改（`botv/config.py`）。
- 运行文件：**`run.py`**（模块化版），旧版单文件 **`botv.py`**（v1.x，包含所有函数和运行逻辑）已归档保留。
- 所有代码文件均已添加统一风格的逐行中文注释，便于二次开发和维护。
