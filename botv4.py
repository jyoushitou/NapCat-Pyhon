# ==============================================
# 友利奈绪 QQ 机器人 —— MySQL 数据库存储版
# 功能：私聊/群聊独立记忆 + 全局关键词记忆 + 双模型兜底 + AI图片打标存档 + 定时任务随机偏移 + 心跳保活
# 数据存储：MySQL（替代原有的JSON文件 + txt日志 + 环境变量密钥）
# 数据库4张表：logs, api_keys, global_keywords, user_memory
# ==============================================
import asyncio
import base64
import requests
import urllib3
import websockets
import json
import random
import os
import hashlib
import re
from io import BytesIO
from collections import deque, defaultdict
from datetime import datetime, time, date
import importlib.util
from requests.adapters import HTTPAdapter
import jieba
import pymysql
import threading

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ===================== MySQL 数据库配置 =====================
DB_CONFIG = {
    "host": "192.168.0.50",
    "port": 3306,
    "user": "TomoriNaoBot",
    "password": "TNB",
    "database": "TomoriNaoBotData",
    "charset": "utf8mb4"
}

_local = threading.local()

def get_db():
    if not hasattr(_local, "conn") or _local.conn is None:
        _local.conn = pymysql.connect(
            host=DB_CONFIG["host"],
            port=DB_CONFIG["port"],
            user=DB_CONFIG["user"],
            password=DB_CONFIG["password"],
            database=DB_CONFIG["database"],
            charset=DB_CONFIG["charset"],
            cursorclass=pymysql.cursors.DictCursor
        )
    return _local.conn

def get_cursor():
    conn = get_db()
    return conn.cursor()

# ===================== 数据库操作函数 =====================
MAX_USER_ROUND = 15
MAX_GLOBAL_KEY = 40

# --- 日志操作 ---
def write_log_to_db(level: str, message: str):
    try:
        cursor = get_cursor()
        cursor.execute(
            "INSERT INTO logs (level, message) VALUES (%s, %s)",
            (level, message)
        )
        cursor.connection.commit()
    except Exception:
        pass

# --- API密钥操作 ---
def get_api_key_from_db(key_name: str) -> str:
    cursor = get_cursor()
    cursor.execute("SELECT key_value FROM api_keys WHERE key_name = %s", (key_name,))
    row = cursor.fetchone()
    return row["key_value"] if row else ""

def reload_api_keys():
    global DS_API_KEY, DOUBAO_API_KEY, SEARCH_STICKER_KEY
    DS_API_KEY = get_api_key_from_db("DS_API_KEY")
    DOUBAO_API_KEY = get_api_key_from_db("ARK_API_KEY")
    SEARCH_STICKER_KEY = get_api_key_from_db("STICKER_API_KEY")
    log_system(f"API密钥已加载：DS={bool(DS_API_KEY)}, 豆包={bool(DOUBAO_API_KEY)}, 搜图={bool(SEARCH_STICKER_KEY)}")

# --- 记忆操作 ---
def load_user_memories_from_db():
    cursor = get_cursor()
    cursor.execute("SELECT target_id, user_msg, bot_msg FROM user_memory ORDER BY target_id, id")
    rows = cursor.fetchall()
    pool = {}
    for row in rows:
        tid = row["target_id"]
        if tid not in pool:
            pool[tid] = deque(maxlen=MAX_USER_ROUND)
        pool[tid].append([row["user_msg"], row["bot_msg"]])
    return pool

def add_user_memory_to_db(target_id, user_msg, bot_msg):
    cursor = get_cursor()
    cursor.execute(
        "INSERT INTO user_memory (target_id, user_msg, bot_msg) VALUES (%s, %s, %s)",
        (target_id, user_msg, bot_msg)
    )
    cursor.execute("""
        DELETE FROM user_memory
        WHERE id NOT IN (
            SELECT id FROM (
                SELECT id FROM user_memory WHERE target_id = %s
                ORDER BY id DESC LIMIT %s
            ) AS tmp
        ) AND target_id = %s
    """, (target_id, MAX_USER_ROUND, target_id))
    cursor.connection.commit()

def load_global_keywords_from_db():
    cursor = get_cursor()
    cursor.execute("SELECT keyword FROM global_keywords ORDER BY id")
    rows = cursor.fetchall()
    return set(row["keyword"] for row in rows)

def add_global_keywords_to_db(keywords):
    cursor = get_cursor()
    for kw in keywords:
        cursor.execute("INSERT IGNORE INTO global_keywords (keyword) VALUES (%s)", (kw,))
    cursor.execute("SELECT COUNT(*) as cnt FROM global_keywords")
    count = cursor.fetchone()["cnt"]
    if count > MAX_GLOBAL_KEY:
        cursor.execute("""
            DELETE FROM global_keywords
            WHERE id NOT IN (
                SELECT id FROM (
                    SELECT id FROM global_keywords ORDER BY id DESC LIMIT %s
                ) AS tmp
            )
        """, (MAX_GLOBAL_KEY,))
    cursor.connection.commit()
# ===================== 日志函数（控制台打印 + MySQL写入） =====================
def log_system(msg):
    print(f"【系统】{datetime.now().strftime('%H:%M:%S')} | {msg}")
    write_log_to_db("系统", msg)

def log_recv(msg):
    print(f"【接收】{datetime.now().strftime('%H:%M:%S')} | {msg}")
    write_log_to_db("接收", msg)

def log_send(msg):
    print(f"【发送】{datetime.now().strftime('%H:%M:%S')} | {msg}")
    write_log_to_db("发送", str(msg))

def log_api(msg):
    print(f"【接口】{datetime.now().strftime('%H:%M:%S')} | {msg}")
    write_log_to_db("接口", msg)

def log_err(msg):
    print(f"【异常】{datetime.now().strftime('%H:%M:%S')} | {msg}")
    write_log_to_db("异常", msg)

# ===================== 通用工具 =====================
def create_http_session():
    session = requests.Session()
    adapter = HTTPAdapter(max_retries=0)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session

# 基础配置
MASTER_QQ = 822891053
LISTEN_HOST = "0.0.0.0"
LISTEN_PORT = 3001

HEARTBEAT_INTERVAL = 15
TIME_RAND_OFFSET = 10
API_RETRY_DELAY = 1.5
MAX_RETRY_TIMES = 3
PROCESSED_MSG_IDS = deque(maxlen=80)
PROCESS_LOCK = None
LOCK_RELEASE_DELAY = 0.8

# 密钥（从MySQL读取）
DS_API_KEY = ""
DOUBAO_API_KEY = ""
SEARCH_STICKER_KEY = ""

DS_API_URL = "https://api.deepseek.com/v1/chat/completions"
DS_MODEL = "deepseek-v4-flash"
DS_TIMEOUT = 60

DOUBAO_API_URL = "https://ark.cn-beijing.volces.com/api/v3/chat/completions"
DOUBAO_MODEL = "ep-20260524110944-g7vqr"
DOUBAO_TIMEOUT = 60

# 表情包配置
STICKER_KEYWORDS = ["表情包", "发个表情", "来个表情", "给我表情", "要表情包", "表情"]
STICKER_FACE_IDS = [14, 91, 99, 176, 179, 183, 196, 202, 211]
USER_STICKER_CACHE = defaultdict(list)

# 表情包存档系统（保留本地文件 + JSON索引，图片数据不存数据库）
STICKER_ARCHIVE_DIR = "sticker_archive"
USER_STICKER_ARCHIVE = defaultdict(list)
STICKER_DATA = {}
MAX_USER_STICKERS = 30

def init_sticker_archive():
    if not os.path.exists(STICKER_ARCHIVE_DIR):
        os.makedirs(STICKER_ARCHIVE_DIR)
    load_sticker_archive()

def get_sticker_hash(image_data):
    return hashlib.md5(image_data).hexdigest()

async def analyze_image_with_ai(image_base64: str) -> tuple:
    if not OCR_ENABLED:
        log_api("OCR未启用，无法分析图片，使用默认标签")
        return ["表情包"], "图片"
    try:
        img_data = base64.b64decode(image_base64)
        def do_ocr():
            with Image.open(BytesIO(img_data)) as img:
                text = pytesseract.image_to_string(img, lang="chi_sim+eng")
            return text.strip()
        text = await asyncio.to_thread(do_ocr)
        if not text:
            log_api("OCR未识别到文字，使用默认标签")
            return ["表情包"], "图片（无文字）"
        words = jieba.lcut(text)
        stop_words = {"的","了","是","我","你","在","有","就","不","都","吗","吧","啊","哦","呀","呢","呗","啦","这","那","也","还","个","对","把","被","让","给","和","与","或","但","而","却","所","以","为","于","之","到","去","来","就","又","只","着","过","也","已","将","从","由","向","对","给","拿","用","把","被","比","和","跟","同","与","让","叫","让","被","对","对于","关于","除了","由于","随着","通过","根据","按照","为了"}
        tags = [w for w in words if len(w) > 1 and w not in stop_words]
        tags = tags[:5]
        if not tags:
            tags = ["表情包"]
        desc = text[:50]
        log_api(f"OCR分析成功，识别文字：{desc}，标签：{tags}")
        return tags, desc
    except Exception as e:
        log_err(f"OCR分析失败: {e}")
        return ["表情包"], "图片"

def archive_sticker_image(user_id, image_data, tags, desc):
    try:
        sticker_hash = get_sticker_hash(image_data)
        if sticker_hash not in STICKER_DATA:
            filepath = os.path.join(STICKER_ARCHIVE_DIR, f"{sticker_hash}.jpg")
            with open(filepath, "wb") as f:
                f.write(image_data)
            STICKER_DATA[sticker_hash] = {
                "type": "image",
                "data": image_data,
                "tags": tags,
                "desc": desc,
                "use_count": 0,
                "users": set()
            }
        STICKER_DATA[sticker_hash]["users"].add(str(user_id))
        STICKER_DATA[sticker_hash]["use_count"] += 1
        if sticker_hash not in USER_STICKER_ARCHIVE[str(user_id)]:
            USER_STICKER_ARCHIVE[str(user_id)].append(sticker_hash)
            if len(USER_STICKER_ARCHIVE[str(user_id)]) > MAX_USER_STICKERS:
                USER_STICKER_ARCHIVE[str(user_id)].pop(0)
        save_sticker_archive()
        log_api(f"图片表情包已存档: hash={sticker_hash[:8]}, tags={tags}")
    except Exception as e:
        log_err(f"存档图片失败: {e}")

def load_sticker_archive():
    global USER_STICKER_ARCHIVE, STICKER_DATA
    index_path = os.path.join(STICKER_ARCHIVE_DIR, "sticker_index.json")
    if not os.path.exists(index_path):
        return
    try:
        with open(index_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        for uid, hashes in data.get("user_stickers", {}).items():
            USER_STICKER_ARCHIVE[uid] = hashes
        for h, info in data.get("stickers", {}).items():
            STICKER_DATA[h] = {
                "type": info["type"],
                "data": None,
                "tags": info["tags"],
                "desc": info["desc"],
                "use_count": info["use_count"],
                "users": set(info["users"])
            }
        log_system(f"表情包存档加载：{len(STICKER_DATA)}个图片，{len(USER_STICKER_ARCHIVE)}个用户")
    except Exception as e:
        log_err(f"加载表情包存档失败: {e}")

def save_sticker_archive():
    try:
        save_data = {
            "user_stickers": {k: list(v) for k, v in USER_STICKER_ARCHIVE.items()},
            "stickers": {}
        }
        for h, info in STICKER_DATA.items():
            save_data["stickers"][h] = {
                "type": info["type"],
                "tags": info["tags"],
                "desc": info["desc"],
                "use_count": info["use_count"],
                "users": list(info["users"])
            }
        with open(os.path.join(STICKER_ARCHIVE_DIR, "sticker_index.json"), "w", encoding="utf-8") as f:
            json.dump(save_data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        log_err(f"保存表情包存档失败: {e}")

def load_sticker_data(sticker_hash):
    if sticker_hash not in STICKER_DATA:
        return None
    if STICKER_DATA[sticker_hash]["data"] is not None:
        return STICKER_DATA[sticker_hash]["data"]
    filepath = os.path.join(STICKER_ARCHIVE_DIR, f"{sticker_hash}.jpg")
    if os.path.exists(filepath):
        with open(filepath, "rb") as f:
            data = f.read()
        STICKER_DATA[sticker_hash]["data"] = data
        return data
    return None

def select_best_sticker_by_tags(context_keywords, user_id):
    if not STICKER_DATA:
        return None
    user_stickers = []
    for h in USER_STICKER_ARCHIVE.get(str(user_id), []):
        if h in STICKER_DATA:
            user_stickers.append(h)
    candidates = user_stickers if user_stickers else list(STICKER_DATA.keys())
    if not candidates:
        return None
    best_hash = None
    best_score = -1
    for h in candidates:
        tags = STICKER_DATA[h]["tags"]
        if not tags:
            continue
        score = sum(1 for kw in context_keywords if any(kw in tag or tag in kw for tag in tags))
        if score > best_score:
            best_score = score
            best_hash = h
    if best_hash and best_score > 0:
        img_data = load_sticker_data(best_hash)
        if img_data:
            log_api(f"匹配到表情包: tags={STICKER_DATA[best_hash]['tags']}, score={best_score}")
            return img_data
    if user_stickers:
        h = random.choice(user_stickers)
        return load_sticker_data(h)
    return None
# 人设提示词
SYSTEM_PROMPT = """
人物出处：动漫《Charlotte夏洛特》
姓名：友利奈绪
年龄：15岁
身份：星之海学园学生会会长
专属异能：掠夺

核心性格：傲娇毒舌、外冷内热、护短、天然呆萌、敏感缺爱
说话风格：吐槽式关心、别扭温柔、少女语气、不讨好、不煽情

聊天规则：
1. 只根据当前对象的对话历史回复
2. 全局关键词是长期记忆
3. 每条回复自动匹配一个最符合语境的表情包，格式 [sticker]
4. 其余正常文本回复

【全局长期记忆】：{global_keywords}
【与你最近的对话】：{current_dialogue}
"""

# 全局变量
user_memory_pool = dict()
global_keyword_set = set()
active_ws = None
active_ws_lock = asyncio.Lock()
daily_trigger = set()
today = date.today()
daily_chat_trigger_times = []
triggered_today = set()
send_lock = asyncio.Lock()
task_trigger_minute = {}

# OCR组件
OCR_ENABLED = False
Image = None
pytesseract = None
if importlib.util.find_spec("PIL") and importlib.util.find_spec("pytesseract"):
    try:
        Image = importlib.import_module("PIL.Image")
        pytesseract = importlib.import_module("pytesseract")
        OCR_ENABLED = True
    except Exception:
        OCR_ENABLED = False

# ===================== 拟人记忆核心（MySQL替代JSON） =====================
def extract_keywords(text):
    stop_words = {"的","了","是","我","你","在","有","就","不","都","吗","吧","啊","哦","呀","呢","呗","啦"}
    words = jieba.lcut(text)
    return [w for w in words if len(w) > 1 and w not in stop_words]

def load_memories():
    """从MySQL加载记忆，替代原JSON文件"""
    global user_memory_pool, global_keyword_set
    user_memory_pool = load_user_memories_from_db()
    global_keyword_set = load_global_keywords_from_db()
    log_system(f"记忆加载完成：独立对话对象{len(user_memory_pool)}个 | 全局关键词{len(global_keyword_set)}个")

def add_target_memory(target_id, user_msg, bot_msg):
    """添加对话记忆到MySQL，替代原JSON文件"""
    add_user_memory_to_db(target_id, user_msg, bot_msg)
    user_memory_pool.setdefault(target_id, deque(maxlen=MAX_USER_ROUND)).append([user_msg, bot_msg])
    new_keys = extract_keywords(f"{user_msg} {bot_msg}")
    add_global_keywords_to_db(new_keys)
    for k in new_keys:
        global_keyword_set.add(k)
    log_system(f"[{target_id}] 新增对话 | 新增关键词：{new_keys[:3]}...")

def build_memory_context(target_id):
    kw_str = "、".join(global_keyword_set) if global_keyword_set else "无"
    dialog_str = ""
    if target_id in user_memory_pool:
        for u, b in user_memory_pool[target_id]:
            dialog_str += f"用户：{u}\n奈绪：{b}\n"
    else:
        dialog_str = "暂无该对象历史对话"
    return kw_str, dialog_str

# ===================== 图片下载与OCR =====================
IMAGE_BASE64_MAX_BYTES = 150000

def download_url(url):
    if not url:
        return None
    session = create_http_session()
    try:
        resp = session.get(url, timeout=(5, 10), verify=False)
        resp.raise_for_status()
        return resp.content
    except requests.RequestException as e:
        log_api(f"图片下载失败：{str(e)}")
        return None
    finally:
        session.close()

def extract_image_text(url):
    if not OCR_ENABLED or not url:
        return ""
    img_data = download_url(url)
    if not img_data:
        return ""
    try:
        with Image.open(BytesIO(img_data)) as img:
            text = pytesseract.image_to_string(img, lang="chi_sim+eng")
        return text.strip()
    except Exception as e:
        log_api(f"OCR识别失败：{str(e)}")
        return ""

def encode_image_base64(data):
    try:
        b64 = base64.b64encode(data).decode()
        return b64[:IMAGE_BASE64_MAX_BYTES]
    except:
        return ""

def search_sticker(keyword):
    if not SEARCH_STICKER_KEY:
        return None
    try:
        s = create_http_session()
        res = s.get(f"https://api.example.com/sticker?key={SEARCH_STICKER_KEY}&q={keyword}", timeout=8)
        if res.status_code == 200:
            return download_url(res.json()["data"][0]["url"])
    except:
        pass
    return None

# ===================== 消息解析（AI图片分析） =====================
async def parse_message_content(raw_content, user_id):
    input_text = ""
    image_desc = []
    if isinstance(raw_content, list):
        for item in raw_content:
            t = item.get("type")
            d = item.get("data", {})
            if t == "text":
                input_text += d.get("text", "")
            elif t == "image":
                url = d.get("url") or d.get("file")
                img_data = download_url(url)
                if img_data:
                    img_base64 = base64.b64encode(img_data).decode('utf-8')
                    tags, desc = await analyze_image_with_ai(img_base64)
                    archive_sticker_image(user_id, img_data, tags, desc)
                    image_desc.append(f"图片({','.join(tags)})：{desc}")
                    if OCR_ENABLED:
                        ocr_txt = extract_image_text(url)
                        if ocr_txt:
                            image_desc.append(f"OCR文字：{ocr_txt}")
                else:
                    image_desc.append("图片")
            elif t == "face":
                fid = str(d.get("id"))
                if fid:
                    USER_STICKER_CACHE[user_id].append(fid)
                    if len(USER_STICKER_CACHE[user_id]) > 20:
                        USER_STICKER_CACHE[user_id].pop(0)
                image_desc.append(f"表情：{fid}")
    else:
        input_text = str(raw_content).strip()
    if image_desc:
        input_text += f"\n图片/表情：{';'.join(image_desc)}"
    return input_text.strip()

# ===================== 模型调用 =====================
async def call_deepseek(msg_list, retry=2):
    if not DS_API_KEY:
        log_api("未配置DeepSeek密钥，切换豆包")
        return None
    headers = {"Authorization": f"Bearer {DS_API_KEY}", "Content-Type": "application/json"}
    req_data = {"model": DS_MODEL, "messages": msg_list, "max_tokens": 512, "temperature": 0.7}
    for attempt in range(retry):
        try:
            def req():
                s = create_http_session()
                return s.post(DS_API_URL, headers=headers, json=req_data, timeout=DS_TIMEOUT, verify=False)
            resp = await asyncio.to_thread(req)
            if resp.status_code == 200:
                result = resp.json()
                txt = result["choices"][0]["message"]["content"].strip()
                if txt:
                    log_api("本次回复模型：DeepSeek-v4-flash")
                    return txt
                else:
                    log_api(f"DeepSeek返回空内容，尝试重试({attempt+1}/{retry})")
            else:
                log_api(f"DeepSeek异常，状态码：{resp.status_code}，尝试重试({attempt+1}/{retry})")
        except requests.exceptions.ReadTimeout:
            log_api(f"DeepSeek超时，尝试重试({attempt+1}/{retry})")
        except Exception as e:
            log_api(f"DeepSeek请求错误：{str(e)}，尝试重试({attempt+1}/{retry})")
        await asyncio.sleep(API_RETRY_DELAY * (attempt + 1))
    log_api("DeepSeek多次失败，切换豆包")
    return None

async def call_doubao(msg_list):
    if not DOUBAO_API_KEY:
        return random.choice(["真是啰嗦，没必要多说 [sticker]","切，随便你怎么想 [sticker]"])
    headers = {"Authorization":f"Bearer {DOUBAO_API_KEY}", "Content-Type":"application/json"}
    req_data = {"model":DOUBAO_MODEL, "messages":msg_list, "max_tokens":256, "temperature":0.7}
    backup = ["真是啰嗦，没必要多说 [sticker]","切，随便你怎么想 [sticker]","别缠着我闲聊 [sticker]"]
    for idx in range(MAX_RETRY_TIMES):
        try:
            def req():
                s = create_http_session()
                return s.post(DOUBAO_API_URL, headers=headers, json=req_data, timeout=DOUBAO_TIMEOUT, verify=False)
            resp = await asyncio.to_thread(req)
            if resp.status_code == 200:
                txt = resp.json()["choices"][0]["message"]["content"].strip()
                log_api("本次回复模型：豆包兜底")
                return txt
        except Exception as e:
            log_api(f"豆包第{idx+1}次失败：{str(e)}")
        await asyncio.sleep(API_RETRY_DELAY*(idx+1))
    log_api("接口全部失败，使用本地话术")
    return random.choice(backup)

async def get_character_reply(user_txt, target_id):
    kw, dialog = build_memory_context(target_id)
    sys_prompt = SYSTEM_PROMPT.format(global_keywords=kw, current_dialogue=dialog)
    msg_list = [{"role":"system","content":sys_prompt}, {"role":"user","content":user_txt}]
    res = await call_deepseek(msg_list)
    if not res:
        res = await call_doubao(msg_list)
    return res
# ===================== 消息发送与表情包选择 =====================
def select_best_sticker(user_id, context_text=""):
    uid = str(user_id)
    if uid in USER_STICKER_CACHE and USER_STICKER_CACHE[uid]:
        return random.choice(USER_STICKER_CACHE[uid])
    return str(random.choice(STICKER_FACE_IDS))

def build_reply_message(txt, user_id, context_keywords=None):
    txt = txt.replace("[sticker]", "").strip()
    kw = context_keywords if context_keywords else extract_keywords(txt)
    sticker = select_best_sticker(user_id, " ".join(kw))
    msg = []
    if txt:
        msg.append({"type":"text","data":{"text":txt}})
    if isinstance(sticker, str):
        msg.append({"type":"face","data":{"id":sticker}})
    else:
        b64 = encode_image_base64(sticker)
        msg.append({"type":"image","data":{"file":b64}})
    return msg

async def send_private_msg(qq, msg, ws):
    async with send_lock:
        payload = {"action":"send_private_msg","params":{"user_id":qq,"message":msg}}
        try:
            await ws.send(json.dumps(payload, ensure_ascii=False))
        except Exception as e:
            log_err(f"私聊发送失败：{e}")

async def send_group_msg(gid, msg, ws):
    async with send_lock:
        payload = {"action":"send_group_msg","params":{"group_id":gid,"message":msg}}
        try:
            await ws.send(json.dumps(payload, ensure_ascii=False))
        except Exception as e:
            log_err(f"群聊发送失败：{e}")

def split_sentence(text):
    if not text:
        return []
    delimiters = r'[。！？!?；;…]+'
    parts = re.split(f'({delimiters})', text)
    sentences = []
    current = ""
    for part in parts:
        current += part
        if re.fullmatch(delimiters, part):
            if current.strip():
                sentences.append(current.strip())
            current = ""
    if current.strip():
        sentences.append(current.strip())
    if not sentences:
        sentences = [text.strip()]
    if len(sentences) == 1 and len(sentences[0]) > 50:
        weak = r'[，,；;]'
        sub_parts = re.split(f'({weak})', sentences[0])
        weak_sentences = []
        cur = ""
        for p in sub_parts:
            cur += p
            if re.fullmatch(weak, p):
                if cur.strip():
                    weak_sentences.append(cur.strip())
                cur = ""
        if cur.strip():
            weak_sentences.append(cur.strip())
        if len(weak_sentences) > 1:
            sentences = weak_sentences
    return sentences

async def split_send_private(qq, text, ws, user_id, context_keywords=None):
    full_msg = build_reply_message(text, user_id, context_keywords)
    full_text = ""
    face_part = None
    if isinstance(full_msg, list):
        for item in full_msg:
            if item.get("type") == "text":
                full_text = item["data"].get("text", "")
            elif item.get("type") == "face":
                face_part = item
    else:
        full_text = full_msg
    if not full_text:
        return
    log_api(f"完整回复原文: {full_text}")
    sentences = split_sentence(full_text)
    log_api(f"分割为 {len(sentences)} 个句子")
    for i, sen in enumerate(sentences):
        msg_parts = [{"type": "text", "data": {"text": sen}}]
        if face_part:
            msg_parts.append(face_part)
        await send_private_msg(qq, msg_parts, ws)
        log_send(f"句子{i+1}: {sen[:30]}..." if len(sen)>30 else f"句子{i+1}: {sen}")
        if i < len(sentences) - 1:
            await asyncio.sleep(0.3)

async def split_send_group(gid, text, ws, user_id, context_keywords=None):
    full_msg = build_reply_message(text, user_id, context_keywords)
    full_text = ""
    face_part = None
    if isinstance(full_msg, list):
        for item in full_msg:
            if item.get("type") == "text":
                full_text = item["data"].get("text", "")
            elif item.get("type") == "face":
                face_part = item
    else:
        full_text = full_msg
    if not full_text:
        return
    log_api(f"完整回复原文: {full_text}")
    sentences = split_sentence(full_text)
    log_api(f"分割为 {len(sentences)} 个句子")
    for i, sen in enumerate(sentences):
        msg_parts = [{"type": "text", "data": {"text": sen}}]
        if face_part:
            msg_parts.append(face_part)
        await send_group_msg(gid, msg_parts, ws)
        log_send(f"句子{i+1}: {sen[:30]}..." if len(sen)>30 else f"句子{i+1}: {sen}")
        if i < len(sentences) - 1:
            await asyncio.sleep(0.3)

async def send_sticker_private(qq, ws, user_id):
    sticker = select_best_sticker(user_id)
    if isinstance(sticker, str):
        await send_private_msg(qq, [{"type":"face","data":{"id":sticker}}], ws)
    else:
        b64 = encode_image_base64(sticker)
        await send_private_msg(qq, [{"type":"image","data":{"file":b64}}], ws)
    log_send(f"私聊表情")

async def send_sticker_group(gid, ws, user_id):
    sticker = select_best_sticker(user_id)
    if isinstance(sticker, str):
        await send_group_msg(gid, [{"type":"face","data":{"id":sticker}}], ws)
    else:
        b64 = encode_image_base64(sticker)
        await send_group_msg(gid, [{"type":"image","data":{"file":b64}}], ws)
    log_send(f"群聊表情")

def contains_sticker_key(text):
    if not text:
        return False
    low = text.lower()
    return any(k in low for k in STICKER_KEYWORDS)

# ===================== 定时任务 =====================
SCHEDULE_TASKS = [
    {"scene":"工作日早八傲娇催起床","weekday":[0,1,2,3,4],"t":time(7,30)},
    {"scene":"周末吐槽赖床提醒起床","weekday":[0,1,2,3,4,5,6],"t":time(8,30)},
    {"scene":"别扭提醒点外卖","weekday":[0,1,2,3,4,5,6],"t":time(10,40)},
    {"scene":"叮嘱准备午睡","weekday":[0,1,2,3,4,5,6],"t":time(12,30)},
    {"scene":"提醒睡醒起身","weekday":[0,1,2,3,4,5,6],"t":time(13,30)},
    {"scene":"提醒点晚餐","weekday":[0,1,2,3,4,5,6],"t":time(16,40)},
    {"scene":"催促上床休息","weekday":[0,1,2,3,4,5,6],"t":time(23,0)},
    {"scene":"勒令按时睡觉","weekday":[0,1,2,3,4,5,6],"t":time(23,30)},
]

async def cycle_task_run():
    global daily_trigger, today, daily_chat_trigger_times, triggered_today, task_trigger_minute
    while True:
        try:
            now = datetime.now()
            if now.date() != today:
                daily_trigger.clear()
                triggered_today.clear()
                task_trigger_minute.clear()
                today = now.date()
                cnt = random.randint(2, 4)
                daily_chat_trigger_times = random.sample(range(720, 1080), cnt)
                for task in SCHEDULE_TASKS:
                    wd = now.weekday()
                    if wd not in task["weekday"]:
                        continue
                    key = f"{task['scene']}_{today}"
                    base_min = task["t"].hour * 60 + task["t"].minute
                    offset = random.randint(-10, 10)
                    trigger_min = max(0, min(1439, base_min + offset))
                    task_trigger_minute[key] = trigger_min
                    log_system(f"定时任务 [{task['scene']}] 今日触发时间: {trigger_min//60:02d}:{trigger_min%60:02d}")
            curr = now.hour * 60 + now.minute
            for task in SCHEDULE_TASKS:
                key = f"{task['scene']}_{today}"
                if key in daily_trigger:
                    continue
                wd = now.weekday()
                if wd not in task["weekday"]:
                    continue
                trigger_min = task_trigger_minute.get(key)
                if trigger_min is None:
                    continue
                if curr == trigger_min:
                    rep = await get_character_reply(task["scene"], str(MASTER_QQ))
                    await split_send_private(MASTER_QQ, rep, active_ws, MASTER_QQ)
                    daily_trigger.add(key)
                    log_system(f"定时提醒已发送: {task['scene']}")
            if curr in daily_chat_trigger_times and curr not in triggered_today:
                triggered_today.add(curr)
                rep = await get_character_reply("主动日常闲聊", str(MASTER_QQ))
                await split_send_private(MASTER_QQ, rep, active_ws, MASTER_QQ)
                log_system("随机闲聊触发")
        except Exception as e:
            log_err(f"定时任务异常：{e}")
        await asyncio.sleep(1)

# ===================== 心跳保活 =====================
async def heartbeat_monitor():
    global active_ws
    while True:
        await asyncio.sleep(HEARTBEAT_INTERVAL)
        async with active_ws_lock:
            ws = active_ws
        if ws and not getattr(ws, "closed", False):
            try:
                await ws.ping()
            except:
                async with active_ws_lock:
                    if active_ws is ws:
                        active_ws = None
                log_system("心跳连接断开")

# ===================== 消息处理 =====================
async def websocket_handle(websocket):
    global active_ws, PROCESSED_MSG_IDS, PROCESS_LOCK
    async with active_ws_lock:
        if active_ws and not getattr(active_ws, "closed", False):
            log_system("已有连接，拒绝接入")
            await websocket.close()
            return
        active_ws = websocket
    log_system("机器人上线，AI视觉表情包分析已启用")
    await split_send_private(MASTER_QQ, "哼，我上线咯，别没事乱找茬", websocket, MASTER_QQ)
    try:
        while True:
            raw = await websocket.recv()
            raw_str = raw.decode("utf-8","ignore") if isinstance(raw,bytes) else raw
            data = json.loads(raw_str)
            msg_type = data.get("message_type")
            msg_id = data.get("message_id")
            if not msg_id or msg_id in PROCESSED_MSG_IDS:
                continue
            user_id = str(data.get("user_id"))
            group_id = data.get("group_id", 0)
            msg_content = data.get("message", "")
            text = await parse_message_content(msg_content, user_id)
            if not text:
                continue
            async with PROCESS_LOCK:
                PROCESSED_MSG_IDS.append(msg_id)
                log_recv(f"[{msg_id}] 用户{user_id}：{text}")
                target_id = user_id if msg_type == "private" else str(group_id)
                context_keywords = extract_keywords(text)
                if contains_sticker_key(text):
                    if msg_type == "group":
                        await send_sticker_group(group_id, websocket, user_id)
                    else:
                        await send_sticker_private(user_id, websocket, user_id)
                else:
                    ans = await get_character_reply(text, target_id)
                    add_target_memory(target_id, text, ans)
                    if msg_type == "group":
                        await split_send_group(group_id, ans, websocket, user_id, context_keywords)
                    else:
                        await split_send_private(user_id, ans, websocket, user_id, context_keywords)
                await asyncio.sleep(LOCK_RELEASE_DELAY)
    except Exception as e:
        log_err(f"连接异常：{e}")
    finally:
        async with active_ws_lock:
            if active_ws is websocket:
                active_ws = None
        PROCESSED_MSG_IDS.clear()
        log_system("连接已断开")

# ===================== 主程序 =====================
async def main():
    global PROCESS_LOCK
    load_memories()
    init_sticker_archive()
    reload_api_keys()
    PROCESS_LOCK = asyncio.Lock()
    log_system("全部初始化完成（MySQL数据库存储版）")
    while True:
        hb_task = asyncio.create_task(heartbeat_monitor())
        cycle_task = asyncio.create_task(cycle_task_run())
        try:
            async with websockets.serve(websocket_handle, LISTEN_HOST, LISTEN_PORT):
                await asyncio.Future()
        except Exception as e:
            log_err(f"服务异常，5秒重启：{e}")
        finally:
            hb_task.cancel()
            cycle_task.cancel()
            await asyncio.sleep(5)

if __name__ == "__main__":
    asyncio.run(main())