# 友利奈绪 QQ 机器人 v5 —— CLIP 视觉识图 + 简短动作回复

基于 **NapCat** 的 QQ 收发，**Python** 作为后端，调用 **DeepSeek** 网络 API 为主模型、**豆包** 网络 API 为备用模型，使用 **OpenAI CLIP (ViT-B/32, CPU)** 进行本地图片识别打标存档的 QQ 聊天机器人。

---

## 核心特性

### 0. MySQL 数据库存储
- 使用 MySQL 替代 JSON 文件存储 + txt 日志 + 环境变量密钥。
- 数据库共 4 张表：`logs`、`api_keys`、`global_keywords`、`user_memory`。
- 默认连接 `192.168.0.50:3306`，数据库 `TomoriNaoBotData`，用户 `TomoriNaoBot`。
- 日志、对话记忆、全局关键词、API 密钥全部从数据库读写，重启后自动加载。
- 表情包存档（图片文件 + JSON 索引）仍保留本地文件存储（`sticker_archive/` 目录）。

### 1. 多轮对话记忆系统
- **私聊/群聊独立记忆**：对每个用户（私聊）和每个群（群聊）分别维护最近 **15 条** 对话记录，形成独立上下文。
- **全局关键词记忆**：从所有对话中提取高频词，长期保存（最多 **40 个**），用于丰富人设提示词。
- 记忆持久化到 **MySQL 数据库**，重启后自动加载。

### 2. 双模型兜底回复
- **主模型**：DeepSeek V4 Flash（需 `DS_API_KEY`），超时 60 秒，支持重试。
- **备用模型**：豆包（需 `ARK_API_KEY`），当 DeepSeek 失败时自动切换。
- **本地话术**：两个模型都不可用时，随机返回预设的傲娇回复。
- **人设提示词**：固定为《Charlotte》友利奈绪（傲娇毒舌、外冷内热），动态注入全局关键词 + 当前对话历史 + 当前话题关键词。
- **可选的在线人设补充**：支持从 URL 远程拉取人设补充文本。

### 3. CLIP 本地识图打标 & 表情包存档（v5 新增 ⭐）
- **OpenAI CLIP (ViT-B/32)** 运行在 CPU 上，对用户发送的图片进行本地识别，打标分类（如"二次元""熊猫头""沙雕图""可爱"等 40+ 候选标签）。
- 所有图片以 **MD5 哈希** 命名保存到 `sticker_archive/` 目录，标签/描述存入 JSON 索引。
- 每个用户最多保留 **30 张** 最近发送的图片，用于个性化表情包推荐。
- 回复时根据上下文关键词，从用户自己的图片库或全局图片库中匹配最佳表情包（按标签得分排序）。

### 4. 网络搜表情包（ALAPI）
- 当需要回复表情包时，优先从 **ALAPI 斗图** 接口在线搜索表情包（按对话关键词匹配）。
- 搜索失败时降级到本地存档或内置 QQ 表情。

### 5. 简短回复 + 动作描写
- 模型回复限 **max_tokens=80**，保证回复简短精炼。
- 支持 **两段式回复**：第一行对话内容，第二行动作描写（如 `（扭头）`）。
- 动作行后自动附带匹配的表情包图片，无动作行时附带 QQ 表情。

### 6. 定时任务 + 随机偏移
- **8 个预设场景**：催起床、周末吐槽赖床、提醒点外卖、叮嘱午睡、提醒起身、提醒晚餐、催睡觉、勒令睡觉。
- **随机偏移 ±10 分钟**，避免机械感。
- **智能起床时间**：使用 `chinesecalendar` 模块判断中国法定工作日/节假日，**工作日 7:30** 叫起床，**周末/法定节假日 8:30** 叫起床（国庆、春节等假期自动延后，调休上班日自动提前）。
- **起床时附带 ACG 二次元图片**：调 ALAPI ACG 接口获取一张二次元图片，起床消息后直接发送，既是叫醒也是检验网络连通性。
- **上线检测**：程序启动连接 QQ 成功后，同样发送 ACG 图片检验全链路连通性。
- **随机日常闲聊**：每天随机 2~4 个时刻（12:00~18:00）主动找主人闲聊。

### 7. 消息发送优化
- **对话 + 动作分离**：对话内容与动作描写分行发送，动作后附带匹配的表情包图片。
- **表情包优先匹配**：根据关键词从用户历史/全局存档中选最合适的图片。
- **并发锁**：使用 `send_lock` 避免 WebSocket 发送冲突。

### 8. 心跳保活
- 每隔 **15 秒** 发送 WebSocket ping 帧，检测连接是否存活。
- 若 ping 失败，自动清空连接状态，等待重连。

### 9. 日志与容错
- **控制台 + MySQL 数据库** 双写日志（系统/接收/发送/接口/异常 五级）。
- **消息去重**：缓存最近 80 条已处理消息 ID，避免重复响应。
- **网络容错**：图片下载、模型请求均带重试机制；API 密钥缺失时自动降级。

---

## 依赖与环境

### 数据库（MySQL）
提前创建数据库及 4 张表：

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

### Python 依赖
```bash
pip install websockets requests urllib3 jieba Pillow pymysql chinesecalendar
```

**CLIP 额外依赖（可选，不影响核心功能）：**
```bash
pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu
pip install git+https://github.com/openai/CLIP.git
```
> 若未安装 CLIP 依赖，程序会禁用 CLIP 识图功能，仅做普通图片存档。

### NapCat 配置
- NapCat 网络配置中添加 WebSocket 客户端地址：`ws://127.0.0.1:3001`

---

## 启动流程

1. **创建 MySQL 数据库** `TomoriNaoBotData` 并执行建表 SQL。
2. 在 `api_keys` 表中插入你的 DeepSeek 和豆包 API 密钥。
3. **启动 NapCat** 或兼容的 QQ 客户端。
4. **运行 botv5.py**：
   ```bash
   python botv5.py
   ```
5. 程序启动时自动：
   - 从 MySQL 加载对话记忆和全局关键词
   - 初始化表情包存档目录，加载图片索引
   - 从 MySQL 加载 API 密钥
   - **加载 CLIP 模型（CPU）**，用于识图打标
   - 尝试远程拉取人设补充文本
   - 启动 WebSocket 服务（监听 `0.0.0.0:3001`），等待 QQ 连接
   - 启动心跳监控和定时任务协程
   - 连接成功后向主人发送上线提示

---

## 写在最后
- 目前该程序已在 **联想小新 Air14 2018（Intel 8250U + MX150 + 16G）** 上成功运行，CLIP CPU 推理单张图片约 1~3 秒。
- 人设、定时任务时间、API 端点等均可按需修改。
- 运行文件：**`botv5.py`**（CLIP 识图版）/ `botv4.py`（旧版 Tesseract OCR）/ 其他文件为历史版本。
