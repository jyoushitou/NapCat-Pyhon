# 简介
基于NapCat的QQ收发，python作为后端，调用的deepseek网络API，豆包的网络API作为保底的QQ聊天机器人，同时使用Tesseract作为图片识别的工具
# 下载 botv4.py 启动
# 功能

## 0. MySQL 数据库存储（v4 新增）
- 使用 MySQL 替代原有的 JSON 文件存储 + txt 日志 + 环境变量密钥。
- 数据库共 4 张表：`logs`、`api_keys`、`global_keywords`、`user_memory`。
- 数据库默认连接 `192.168.0.50:3306`，数据库 `TomoriNaoBotData`，用户 `TomoriNaoBot`。
- 日志、对话记忆、全局关键词、API 密钥全部从数据库读写，重启后自动从 MySQL 加载。
- 表情包存档（图片文件 + JSON 索引）仍保留本地文件存储（`sticker_archive/` 目录）。

## 1. 多轮对话记忆系统
- 私聊/群聊独立记忆：对每个用户（私聊）和每个群（群聊）分别维护最近 MAX_USER_ROUND（15）条对话记录，形成独立上下文。
- 全局关键词记忆：从所有对话中提取高频词，长期保存（最多 40 个），用于丰富人设提示词。
- 记忆持久化：对话历史和关键词保存到 **MySQL 数据库**，重启后自动加载。
## 2. 双模型兜底回复
- 主模型：DeepSeek V4 Flash（需 `api_keys` 表中 `DS_API_KEY`），超时 60 秒，支持重试 3 次。
- 备用模型：豆包（需 `api_keys` 表中 `ARK_API_KEY`），当 DeepSeek 失败时自动切换。

- 本地话术：当两个模型都不可用时，随机返回预设的傲娇回复。

- 人设提示词：系统提示词固定为《Charlotte》中的友利奈绪（傲娇毒舌、外冷内热），并动态注入全局关键词和当前对话历史。
PS人设可以自己根据需求更改

## 3. 图片 / 表情包处理
- 自动识别表情包请求：当用户消息包含“表情包”、“来个表情”等关键词时，直接返回一个随机（或基于用户历史）的 QQ 表情或图片。

- AI 图片分析（可选）：

- 若安装 PIL 和 pytesseract，会对用户发送的图片进行 OCR 文字识别 + jieba 分词，生成标签（tags）和简短描述。

- 图片分析结果用于存档（保存图片本体及标签），后续可根据对话关键词匹配最合适的图片表情包回复。

- 图片表情包存档：

- 所有用户发送的图片都会以 MD5 哈希命名保存到 sticker_archive/ 目录。

- 每个用户最多保留 30 张最近发送的图片，用于个性化表情包推荐。

- 回复时根据上下文关键词，从用户自己的图片库或全局图片库中匹配最佳表情包（按标签得分排序）。

## 4. 定时任务 + 随机偏移
- 预设提醒场景：工作日早八催起床、周末吐槽赖床、别扭提醒点外卖、叮嘱午睡、提醒点晚餐、催促上床休息等共 8 个任务。

- 随机偏移：每个任务的实际执行时间在原始时间基础上随机偏移 ±10 分钟，避免机械感。

- 随机日常闲聊：每天随机 2~4 个时刻（12:00~18:00 之间）主动向主人发起闲聊。

- 所有定时任务通过 cycle_task_run 协程每秒检查当前时间，触发时调用 AI 生成符合语境的回复，并私聊发送给主人（MASTER_QQ）。

## 5. 消息发送优化
- 长句分割：AI 回复可能较长，代码会按句号、感叹号、问号等分隔符拆分成短句，逐句发送，每条间隔 0.3 秒，更接近真人聊天。

- 表情包与文字分离：回复中的 [sticker] 占位符会被替换为实际表情（QQ 表情 ID 或图片 base64），最终构造为 CQ 码格式的消息段。

- 并发锁：使用 send_lock 避免 websocket 发送冲突。

## 6. 心跳保活
- 每隔 HEARTBEAT_INTERVAL（15 秒）发送 websocket ping 帧，检测连接是否存活。

- 若 ping 失败，自动清空连接状态，等待重连。

## 7. 日志与容错
- 控制台 + **MySQL 数据库**日志：所有接收、发送、接口调用、异常信息都同时输出到控制台和数据库 `logs` 表（不再写入本地 txt 文件）。

- 消息去重：使用 PROCESSED_MSG_IDS（最多 80 条）缓存已处理的消息 ID，避免重复响应。

- 网络容错：图片下载、模型请求均带重试机制；API 密钥缺失时自动降级。

# 8. 依赖与环境

## 数据库
- 需要提前创建 MySQL 数据库 `TomoriNaoBotData` 以及以下 4 张表：

```sql
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
INSERT INTO api_keys (key_name, key_value) VALUES ('STICKER_API_KEY', 'your_sticker_api_key');

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
```

## Python 依赖
- 必要的库可以使用如下命令安装：
```
pip install websockets requests urllib3 jieba Pillow pytesseract pymysql
```
- OCR 功能依赖 PIL 和 pytesseract，若未安装则自动禁用图片分析，仅作普通图片存档。
- 需安装 Tesseract OCR 引擎（系统级，非 Python 包）。

## NapCat 配置
- 需要前往 NapCat 的网络配置，配置 WebSocket 客户端的程序地址（如 `ws://127.0.0.1:3001`）。

# 9. 启动流程
1. 确保 MySQL 数据库已创建且表结构正确。
2. 在 `api_keys` 表中插入你的 DeepSeek 和豆包 API 密钥。
3. 启动 NapCat 或兼容的 QQ 客户端。
4. 运行 `python botv4.py`。
5. 程序启动时自动：
   - 从 MySQL 加载对话记忆和全局关键词。
   - 初始化表情包存档目录，加载图片索引（`sticker_archive/sticker_index.json`）。
   - 从 MySQL 加载 API 密钥。
   - 启动 WebSocket 服务（监听 `0.0.0.0:3001`），等待 QQ 客户端连接。
   - 同时启动心跳监控和定时任务协程。
   - 连接成功后向主人发送上线提示。

# 写在最后
- 目前该程序已经在联想小新 Air14 2018（Intel 8250U + MX150 + 16G）上成功运行。