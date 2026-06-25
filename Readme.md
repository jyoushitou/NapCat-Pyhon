# 友利奈绪 QQ 机器人 v6 —— CLIP 视觉识图 + 简短动作回复

基于 **NapCat** 的 QQ 收发，**Python** 作为后端，调用 **DeepSeek** 网络 API 为主模型、**豆包** 网络 API 为备用模型，使用 **OpenAI CLIP (ViT-B/32, CPU)** 进行本地图片识别打标存档的 QQ 聊天机器人。

---

## 核心特性

### 0. MySQL 数据库存储
- 使用 MySQL 替代 JSON 文件存储 + txt 日志 + 环境变量密钥。
- 数据库共 7 张表：`logs`、`api_keys`、`global_keywords`、`user_memory`、`images`、`events`、`ai_raw_responses`。
- 默认连接 `192.168.0.50:3306`，数据库 `TomoriNaoBotData`，用户 `TomoriNaoBot`。
- 日志、对话记忆、全局关键词、API 密钥全部从数据库读写，重启后自动加载。
- 表情包存档（图片文件 + JSON 索引）仍保留本地文件存储（`sticker_archive/` 目录）。
- 新图片统一存入 `images/` 目录 + `images` 数据库表。

### 1. 多轮对话记忆系统
- **私聊/群聊独立记忆**：对每个用户（私聊）和每个群（群聊）分别维护最近 **15 条** 对话记录，形成独立上下文。
- **全局关键词记忆**：从所有对话中提取高频词，长期保存（最多 **40 个**），用于丰富人设提示词。
- 记忆持久化到 **MySQL 数据库**，重启后自动加载。

### 2. 双模型兜底回复
- **主模型**：DeepSeek V4 Flash（需 `DS_API_KEY`），超时 60 秒，支持重试。
- **备用模型**：豆包（需 `ARK_API_KEY`），当 DeepSeek 失败时自动切换。
- **本地话术**：两个模型都不可用时，随机返回预设的傲娇回复。
- **人设提示词**：固定为《Charlotte》友利奈绪（傲娇毒舌、外冷内热），动态注入全局关键词 + 当前对话历史 + 当前话题关键词 + 事件记忆。
- **可选的在线人设补充**：支持从 URL 远程拉取人设补充文本。

### 3. CLIP 本地识图打标 & 统一图片系统（v5 新增 ⭐）
- **OpenAI CLIP (ViT-B/32)** 运行在 CPU 上，对用户发送的图片进行本地识别，打标分类（如"二次元""沙雕图""可爱"等 600个 候选标签）。
- 所有图片以 **MD5 哈希** 命名保存到 `images/` 目录，标签、来源、使用次数存入 `images` 数据库表。
- 回复时根据对话关键词，从数据库中按标签搜索匹配图片（按使用次数排序），优先返回高频图。
- **ALAPI 在线搜图兜底**：本地无匹配时自动从 ALAPI 斗图/ACG 接口下载、打标、入库，后续可直接复用。
- **旧 sticker_archive 兼容**：启动时自动将旧存档数据迁入新库。

### 4. 简短回复 + 动作描写
- 模型回复限 **max_tokens=200**，保证回复简短精炼。
- 支持 **两段式回复**：第一行对话内容，第二行动作描写（如 `（扭头）`）。
- 动作行后自动附带匹配的表情包图片，无动作行时附带 QQ 表情。

### 5. 定时任务 + 随机偏移
- **8 个预设场景**：催起床、周末吐槽赖床、提醒点外卖、叮嘱午睡、提醒起身、提醒晚餐、催睡觉、勒令睡觉。
- **随机偏移 ±10 分钟**，避免机械感。
- **智能起床时间**：使用 `chinesecalendar` 模块判断中国法定工作日/节假日，**工作日 7:30** 叫起床，**周末/法定节假日 8:30** 叫起床（国庆、春节等假期自动延后，调休上班日自动提前）。
- **起床时附带 ACG 二次元图片**：调 ALAPI ACG 接口获取一张二次元图片，起床消息后直接发送。
- **上线检测**：程序启动连接 QQ 成功后，同样发送 ACG 图片检验全链路连通性。
- **随机日常闲聊**：每天随机 2~4 个时刻（12:00~18:00）主动找主人闲聊。

### 6. 对话命令系统
- 主人通过私聊发送 `!` 前缀命令查看/修改运行时参数。
- 支持命令：`!help`、`!status`、`!status all`、`!task`、`!memory`、`!memory <uid>`、`!sticker`、`!clip`、`!keywords`、`!apikeys`、`!reload`、`!set`、`!say`、`!sayg`、`!img`、`!acg`、`!event`、`!clear`、`!log`、`!db`、`!uptime`、`!ping`。

### 7. 消息发送优化
- **对话 + 动作分离**：对话内容与动作描写分行发送，动作后附带匹配的图片。
- **图片优先匹配**：根据关键词从 `images` 数据库按标签 + 使用次数选最合适的图片。
- **并发锁**：使用 `send_lock` 避免 WebSocket 发送冲突。
- **延迟兜底搜图**：AI 未提供图片关键词时，1 分钟后用 jieba 从对话中提取关键词再次搜图。

### 8. 心跳保活
- 每隔 **15 秒** 发送 WebSocket ping 帧，检测连接是否存活。
- 若 ping 失败，自动清空连接状态，等待重连。

### 9. 日志与容错
- **控制台 + MySQL 数据库** 双写日志（系统/接收/发送/接口/异常 五级）。
- **消息去重**：缓存最近 80 条已处理消息 ID，避免重复响应。
- **网络容错**：图片下载、模型请求均带重试机制；API 密钥缺失时自动降级。
- **AI 原始返回保存**：每次模型调用结果（完整 JSON）存入 `ai_raw_responses` 表，便于调试。

### 10. 事件记忆系统
- 从对话中提取重要事件（如"今天考试""明天出去玩"），存入 `events` 数据库表。
- 在构建提示词时注入事件记忆，让 AI 记住用户的重要日程。

---

## 项目结构

```
NapCat+Pyhon/
├── run.py                    # 入口文件，python run.py 启动
├── Readme.md
├── botv/                     # 功能模块包
│   ├── __init__.py           # 模块导出
│   ├── config.py             # 配置常量 + 全局运行时变量
│   ├── db.py                 # 数据库连接与操作
│   ├── log.py                # 日志系统
│   ├── utils.py              # 通用工具（下载、base64编码、AI回复解析等）
│   ├── clip.py               # CLIP 模型加载与图片分析
│   ├── image.py              # 统一图片系统（下载→打标→入库→搜索）
│   ├── sticker_archive.py    # 旧表情包存档兼容层
│   ├── personality.py        # 人设系统
│   ├── memory.py             # 对话记忆与关键词
│   ├── api.py                # DeepSeek + 豆包 模型调用
│   ├── send.py               # 消息发送与选图
│   ├── commands.py           # ! 命令系统
│   ├── schedule.py           # 定时任务 + 工作日判断
│   ├── heartbeat.py          # WebSocket 心跳
│   ├── handler.py            # QQ 消息处理主循环
│   └── main.py               # async def main() 启动函数
```

---

## 数据库建表

提前创建数据库及 7 张表：

```sql
CREATE DATABASE IF NOT EXISTS TomoriNaoBotData;
USE TomoriNaoBotData;

CREATE TABLE logs (
    id INT AUTO_INCREMENT PRIMARY KEY,
    level VARCHAR(10) NOT NULL,
    message TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE api_keys (
    id INT AUTO_INCREMENT PRIMARY KEY,
    key_name VARCHAR(50) NOT NULL UNIQUE,
    key_value VARCHAR(255) NOT NULL,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
);

INSERT INTO api_keys (key_name, key_value) VALUES ('DS_API_KEY', 'your_deepseek_key');
INSERT INTO api_keys (key_name, key_value) VALUES ('ARK_API_KEY', 'your_doubao_key');
INSERT INTO api_keys (key_name, key_value) VALUES ('ALAPI_TOKEN', 'your_alapi_token');

CREATE TABLE global_keywords (
    id INT AUTO_INCREMENT PRIMARY KEY,
    keyword VARCHAR(50) NOT NULL UNIQUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE user_memory (
    id INT AUTO_INCREMENT PRIMARY KEY,
    target_id VARCHAR(50) NOT NULL,
    user_msg TEXT NOT NULL,
    bot_msg TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_target_id (target_id)
);

CREATE TABLE images (
    id INT AUTO_INCREMENT PRIMARY KEY,
    md5_hash VARCHAR(32) NOT NULL UNIQUE,
    image_data MEDIUMBLOB,
    tags VARCHAR(255) DEFAULT '',
    source_url VARCHAR(512) DEFAULT '',
    file_path VARCHAR(255) DEFAULT '',
    ext VARCHAR(10) DEFAULT 'jpg',
    use_count INT DEFAULT 0,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS events (
    id INT AUTO_INCREMENT PRIMARY KEY,
    target_id VARCHAR(50) NOT NULL,
    summary VARCHAR(255) NOT NULL,
    tags VARCHAR(100) DEFAULT '',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_target_id (target_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS ai_raw_responses (
    id INT AUTO_INCREMENT PRIMARY KEY,
    model_name VARCHAR(50) NOT NULL,
    user_msg TEXT,
    raw_response_json JSON,
    response_text TEXT,
    target_id VARCHAR(50) DEFAULT '',
    status VARCHAR(20) DEFAULT '',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```

---

## Python 依赖

```bash
pip install websockets requests urllib3 jieba Pillow pymysql chinesecalendar
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
2. 在 `api_keys` 表中插入你的 DeepSeek、豆包、ALAPI 密钥。
3. **启动 NapCat** 或兼容的 QQ 客户端。
4. **运行入口文件**：
   ```bash
   python run.py
   ```
5. 程序启动时自动：
   - 从 MySQL 加载对话记忆和全局关键词
   - 初始化表情包存档目录，加载图片索引
   - 从 MySQL 加载 API 密钥
   - **加载 CLIP 模型（CPU）**，用于识图打标
   - 尝试远程拉取人设补充文本
   - 启动 WebSocket 服务（监听 `0.0.0.0:3001`），等待 QQ 连接
   - 启动心跳监控和定时任务协程
   - 连接成功后向主人发送上线提示（文字 + ACG 图片）

---

## 代码注释说明

所有核心模块均已添加逐行中文注释，便于理解和二次开发：

| 文件 | 说明 |
|------|------|
| `botv/config.py` | 配置常量 + 全局运行时变量，每行注释 |
| `botv/db.py` | 数据库连接池、建表、CRUD 操作 |
| `botv/log.py` | 日志系统（控制台 + MySQL 双写） |
| `botv/utils.py` | 通用工具函数（下载、编码、AI回复解析） |
| `botv/clip.py` | CLIP 模型加载与图片分析 |
| `botv/image.py` | 统一图片系统（下载→打标→入库→搜索） |
| `botv/sticker_archive.py` | 旧表情包存档兼容层 |
| `botv/personality.py` | 人设系统（本地 + 远程补充） |
| `botv/memory.py` | 对话记忆与关键词管理 |
| `botv/api.py` | DeepSeek + 豆包 双模型调用 |
| `botv/send.py` | 消息发送与选图策略 |
| `botv/commands.py` | ! 命令系统 |
| `botv/schedule.py` | 定时任务 + 工作日判断 |
| `botv/heartbeat.py` | WebSocket 心跳保活 |
| `botv/handler.py` | QQ 消息处理主循环 |
| `botv/main.py` | 主程序入口 |

---

## 写在最后
- 目前该程序已在 **联想小新 Air14 2018（Intel 8250U + MX150 + 16G）** 上成功运行，CLIP CPU 推理单张图片约 1~3 秒。
- 人设、定时任务时间、API 端点等均可按需修改。
- 运行文件：**`run.py`**（模块化版）