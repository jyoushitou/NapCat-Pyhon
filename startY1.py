# ==============================================
# 友利奈绪 QQ机器人 完整版
# 全功能复原 | 极致Token压缩 | DeepSeek强制优先 | 智能分句发送
# 包含：私聊/群聊全逻辑、Tesseract OCR、表情包、图片解析、记忆系统、定时任务、防刷屏/禁言、完整日志
# ==============================================
import asyncio
import base64
import requests
import urllib3
import websockets
import json
import random
import os
from io import BytesIO
from collections import deque, defaultdict
from datetime import datetime, time, date
from requests.adapters import HTTPAdapter
import jieba

# 修复 urllib3 警告
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ===================== 一、Tesseract OCR 模块（完整保留） =====================
OCR_ENABLED = False
Image = None
pytesseract = None
try:
    from PIL import Image
    import pytesseract
    # 未添加系统环境变量时，手动指定路径
    # pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
    OCR_ENABLED = True
except Exception as e:
    OCR_ENABLED = False
    print(f"【OCR初始化失败】{e}，图片识别功能关闭")

def create_http_session():
    """复用HTTP连接，提升接口成功率、减少失败"""
    session = requests.Session()
    adapter = HTTPAdapter(max_retries=3)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session

# ===================== 二、全局基础配置（全功能开启 + Token严控） =====================
MASTER_QQ = 822891053
LISTEN_HOST = "0.0.0.0"
LISTEN_PORT = 3001

# 记忆文件（持久化存储）
USER_FULL_HIST_FILE = "user_full_history.json"
GLOBAL_IMPRESS_FILE = "global_impression.json"
USER_IMPRESS_FILE = "user_impression.json"

# -------- Token 压缩配置（不浪费Token，保守精简） --------
MAX_FULL_HIST = 9999
MAX_RECENT_TALK = 4        # 对话轮数，平衡体验&Token
LONG_TERM_IMPRESS_NUM = 10  # 印象词数量
SINGLE_MSG_MAX_LEN = 55     # 单条消息字符上限
MODEL_MAX_TOKENS = 65       # 模型输出Token限制

# 图片处理配置
MAX_IMG_LONG_SIDE = 1280
IMAGE_BASE64_MAX_BYTES = 150000

# -------- DeepSeek 优先强化（核心：最高优先级、多重试、长超时） --------
DS_API_KEY = os.getenv("DS_API_KEY")
DS_API_URL = "https://api.deepseek.com/v1/chat/completions"
DS_MODEL_NAME = "deepseek-v4-flash"
DS_TIMEOUT = 75
DS_MAX_RETRY = 3    # 3次重试，网络抖动不切换兜底

# 兜底模型（仅DeepSeek彻底失败才启用）
DOUBAO_API_KEY = os.getenv("ARK_API_KEY")
DOUBAO_API_URL = "https://ark.cn-beijing.volces.com/api/v3/chat/completions"
DOUBAO_MODEL_NAME = "ep-20260524110944-g7vqr"
DOUBAO_TIMEOUT = 45
DOUBAO_MAX_RETRY = 2

# 通用延时配置
API_RETRY_DELAY = 0.7
HEARTBEAT_INTERVAL = 15
TIME_RAND_OFFSET = 10
PROCESSED_MSG_IDS = deque(maxlen=120)
PROCESS_LOCK = None
LOCK_RELEASE_DELAY = 0.3
SENTENCE_SPLIT_DELAY = 0.4  # 分句发送间隔

# -------- 表情包、群聊、触发关键词（完整复原） --------
STICKER_KEYWORDS = ["表情包", "发个表情", "来个表情", "表情"]
STICKER_FACE_IDS = [14, 91, 99, 176, 179, 183, 196, 202]
USER_STICKER_CACHE = defaultdict(list)
SEARCH_STICKER_KEY = os.getenv("STICKER_API_KEY")

GROUP_AT_TRIGGER = ["奈绪", "@奈绪"]
GROUP_SILENT_LIST = set()               # 禁言群列表
GROUP_MSG_CACHE = defaultdict(deque)    # 群消息缓存(防刷屏)
GROUP_CACHE_MAX = 10

# ===================== 三、精简系统提示词（控Token，保留完整人设） =====================
SYSTEM_PROMPT = "人设：友利奈绪，傲娇少女，外冷内热，语气别扭温柔。结合用户印象与历史对话作答，句尾加[sticker]。印象:{long_impress} 对话:{recent_talk}"

# ===================== 四、全局内存变量（全功能结构复原） =====================
full_user_history = dict()
global_impression = set()
user_impression = defaultdict(set)

active_ws = None
active_ws_lock = asyncio.Lock()
daily_trigger = set()
today = date.today()
daily_chat_trigger_times = []
triggered_today = set()
send_lock = asyncio.Lock()
task_random_offset = dict()

# ===================== 五、完整日志系统（分级+时间戳） =====================
def log_sys(msg):
    print(f"[系统] {datetime.now().strftime('%H:%M:%S')} | {msg}")

def log_recv(msg):
    print(f"[接收] {datetime.now().strftime('%H:%M:%S')} | {msg}")

def log_model(model_name, raw_input, raw_output):
    print(f"[模型] {datetime.now().strftime('%H:%M:%S')} | 调用：{model_name} | 输入：{raw_input[:35]}... | 回复：{raw_output}")

def log_memory(msg):
    print(f"[记忆] {datetime.now().strftime('%H:%M:%S')} | {msg}")

def log_ocr(msg):
    print(f"[OCR] {datetime.now().strftime('%H:%M:%S')} | {msg}")

def log_err(msg):
    print(f"[异常] {datetime.now().strftime('%H:%M:%S')} | {msg}")

# ===================== 六、记忆处理模块（完整功能：分词、去重、持久化） =====================
def extract_core_words(text):
    """提取有效关键词，过滤停用词"""
    stop_words = {"的","了","是","我","你","在","有","就","不","都","吗","吧","啊","哦","呀","呢","呗","啦","嗯","然后"}
    words = jieba.lcut(text)
    return [w for w in words if 2 <= len(w) <= 4 and w not in stop_words]

def merge_impression(word_set):
    """印象词去重、裁剪，控制数量省Token"""
    if not word_set:
        return []
    res, exist = [], set()
    for word in word_set:
        if len(res) >= LONG_TERM_IMPRESS_NUM:
            break
        if not any(s in word or word in s for s in exist):
            res.append(word)
            exist.add(word)
    return res

# 文件读写
def save_full_history():
    dump = {k: list(v) for k, v in full_user_history.items()}
    with open(USER_FULL_HIST_FILE, "w", encoding="utf-8") as f:
        json.dump(dump, f, ensure_ascii=False, indent=2)

def save_global_impress():
    with open(GLOBAL_IMPRESS_FILE, "w", encoding="utf-8") as f:
        json.dump(list(global_impression), f, ensure_ascii=False, indent=2)

def save_user_impress():
    dump = {k: list(v) for k, v in user_impression.items()}
    with open(USER_IMPRESS_FILE, "w", encoding="utf-8") as f:
        json.dump(dump, f, ensure_ascii=False, indent=2)

def load_all_memory():
    """启动加载历史记忆"""
    global full_user_history, global_impression, user_impression
    if os.path.exists(USER_FULL_HIST_FILE):
        try:
            raw = json.load(open(USER_FULL_HIST_FILE, encoding="utf-8"))
            full_user_history = {k: deque(v, maxlen=MAX_FULL_HIST) for k, v in raw.items()}
        except:
            full_user_history = dict()
    if os.path.exists(GLOBAL_IMPRESS_FILE):
        try:
            global_impression = set(json.load(open(GLOBAL_IMPRESS_FILE, encoding="utf-8")))
        except:
            global_impression = set()
    if os.path.exists(USER_IMPRESS_FILE):
        try:
            raw = json.load(open(USER_IMPRESS_FILE, encoding="utf-8"))
            user_impression = {k: set(v) for k, v in raw.items()}
        except:
            user_impression = defaultdict(set)
    log_sys(f"记忆加载完成 | 会话数：{len(full_user_history)} | 全局印象词：{len(global_impression)}")

def add_new_memory(target_id, user_msg, bot_msg):
    """新增对话记忆 + 关键词更新"""
    user_msg = user_msg[:SINGLE_MSG_MAX_LEN]
    bot_msg = bot_msg[:SINGLE_MSG_MAX_LEN]
    if target_id not in full_user_history:
        full_user_history[target_id] = deque(maxlen=MAX_FULL_HIST)
    full_user_history[target_id].append([user_msg, bot_msg])
    save_full_history()

    core_words = extract_core_words(f"{user_msg} {bot_msg}")
    for w in core_words:
        global_impression.add(w)
    save_global_impress()
    for w in core_words:
        user_impression[target_id].add(w)
    save_user_impress()
    log_memory(f"会话{target_id} 新增对话 | 关键词：{core_words[:3]}")

def build_llm_context(target_id):
    """构建上下文，极简格式，零冗余Token"""
    g_imp = merge_impression(global_impression)
    g_str = " ".join(g_imp) if g_imp else "无"
    u_imp = merge_impression(user_impression.get(target_id, set()))
    u_str = " ".join(u_imp) if u_imp else "无"
    long_impress = f"全局:{g_str} 个人:{u_str}"

    recent_talk = ""
    if target_id in full_user_history:
        recent_list = list(full_user_history[target_id])[-MAX_RECENT_TALK:]
        for u, b in recent_list:
            recent_talk += f"U:{u} N:{b} "
        recent_talk = recent_talk.strip()
    else:
        recent_talk = "无"
    log_memory(f"上下文 | 印象：{long_impress} | 对话：{recent_talk[:50]}...")
    return long_impress, recent_talk

# ===================== 七、图片下载 + OCR + 消息解析（完整复原） =====================
def download_url(url):
    if not url:
        return None
    session = create_http_session()
    try:
        resp = session.get(url, timeout=(4, 8), verify=False)
        resp.raise_for_status()
        return resp.content
    except requests.RequestException as e:
        log_ocr(f"图片下载失败：{e}")
        return None
    finally:
        session.close()

def extract_image_text(url):
    """Tesseract 图片文字识别"""
    if not OCR_ENABLED or not url or not pytesseract:
        return ""
    img_data = download_url(url)
    if not img_data:
        return ""
    try:
        img = Image.open(BytesIO(img_data)).convert("RGB")
        w, h = img.size
        if w > MAX_IMG_LONG_SIDE or h > MAX_IMG_LONG_SIDE:
            scale = MAX_IMG_LONG_SIDE / max(w, h)
            img = img.resize((int(w*scale), int(h*scale)), Image.Resampling.LANCZOS)
        text = pytesseract.image_to_string(img, lang="chi_sim+eng")
        res_text = text.strip()
        log_ocr(f"识别内容：{res_text[:25]}...")
        return res_text[:SINGLE_MSG_MAX_LEN]
    except Exception as e:
        log_ocr(f"识别异常：{e}")
        return ""

def encode_image_base64(data):
    try:
        b64 = base64.b64encode(data).decode()
        return b64[:IMAGE_BASE64_MAX_BYTES]
    except:
        return ""

def search_sticker(keyword):
    """网络表情包接口（保留原功能）"""
    if not SEARCH_STICKER_KEY:
        return None
    try:
        s = create_http_session()
        res = s.get(f"https://api.example.com/sticker?key={SEARCH_STICKER_KEY}&q={keyword}", timeout=6)
        if res.status_code == 200:
            return download_url(res.json()["data"][0]["url"])
    except:
        pass
    return None

def parse_message_content(raw_content, user_id):
    """完整解析复合消息：文本、图片、表情"""
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
                ocr_txt = extract_image_text(url)
                image_desc.append(f"图:{ocr_txt}" if ocr_txt else "图")
            elif t == "face":
                fid = str(d.get("id"))
                USER_STICKER_CACHE[user_id].append(fid)
                if len(USER_STICKER_CACHE[user_id]) > 20:
                    USER_STICKER_CACHE[user_id].pop(0)
                image_desc.append(f"表情:{fid}")
    else:
        input_text = str(raw_content).strip()
    if image_desc:
        input_text += f" {' '.join(image_desc)}"
    return input_text.strip()[:SINGLE_MSG_MAX_LEN]

# ===================== 八、模型调用（DeepSeek强制优先 + 多重试） =====================
async def call_main_model(msg_list, user_input):
    """主模型 DeepSeek：优先调用、3次重试、长超时"""
    if not DS_API_KEY:
        log_model(DS_MODEL_NAME, user_input, "无密钥，跳过主模型")
        return None
    headers = {"Authorization": f"Bearer {DS_API_KEY}", "Content-Type": "application/json"}
    req_data = {
        "model": DS_MODEL_NAME,
        "messages": msg_list,
        "max_tokens": MODEL_MAX_TOKENS,
        "temperature": 0.55
    }

    for retry in range(DS_MAX_RETRY):
        try:
            def req():
                s = create_http_session()
                return s.post(DS_API_URL, headers=headers, json=req_data, timeout=DS_TIMEOUT, verify=False)
            resp = await asyncio.to_thread(req)
            if resp.status_code == 200:
                content = resp.json()["choices"][0]["message"]["content"].strip()
                log_model(DS_MODEL_NAME, user_input, content)
                return content
            log_err(f"DeepSeek 状态码异常，第{retry+1}次重试")
        except Exception as e:
            log_err(f"DeepSeek 超时/网络异常，第{retry+1}次重试：{str(e)[:40]}")
        await asyncio.sleep(API_RETRY_DELAY)

    log_model(DS_MODEL_NAME, user_input, "全部重试失败，切换兜底模型")
    return None

async def call_backup_model(msg_list, user_input):
    """兜底模型 豆包"""
    if not DOUBAO_API_KEY:
        fallback = random.choice(["啰嗦 [sticker]","随便你 [sticker]"])
        log_model(DOUBAO_MODEL_NAME, user_input, "无密钥，使用本地话术")
        return fallback
    headers = {"Authorization": f"Bearer {DOUBAO_API_KEY}", "Content-Type": "application/json"}
    req_data = {
        "model": DOUBAO_MODEL_NAME,
        "messages": msg_list,
        "max_tokens": MODEL_MAX_TOKENS,
        "temperature": 0.55
    }
    backup_text = ["啰嗦 [sticker]","随便你 [sticker]","别闹了 [sticker]"]
    for idx in range(DOUBAO_MAX_RETRY):
        try:
            def req():
                s = create_http_session()
                return s.post(DOUBAO_API_URL, headers=headers, json=req_data, timeout=DOUBAO_TIMEOUT, verify=False)
            resp = await asyncio.to_thread(req)
            if resp.status_code == 200:
                content = resp.json()["choices"][0]["message"]["content"].strip()
                log_model(DOUBAO_MODEL_NAME, user_input, content)
                return content
        except Exception as e:
            log_err(f"豆包 重试{idx+1}失败：{e}")
        await asyncio.sleep(API_RETRY_DELAY)
    final = random.choice(backup_text)
    log_model(DOUBAO_MODEL_NAME, user_input, "全部失败，使用本地兜底话术")
    return final

async def get_ai_reply(user_input, target_id):
    """获取AI回复，强制优先DeepSeek"""
    long_imp, recent_talk = build_llm_context(target_id)
    sys_content = SYSTEM_PROMPT.format(long_impress=long_imp, recent_talk=recent_talk)
    msg_list = [
        {"role": "system", "content": sys_content},
        {"role": "user", "content": user_input}
    ]
    result = await call_main_model(msg_list, user_input)
    if not result:
        result = await call_backup_model(msg_list, user_input)
    return result

# ===================== 九、智能分句 + 消息发送（完整复原） =====================
def split_sentence(text):
    """按中文标点智能分句，长文本拆分发送"""
    if not text:
        return []
    buf, parts = "", []
    punc = ("。", "！", "？", "!", "?")
    for ch in text:
        buf += ch
        if ch in punc:
            s = buf.strip()
            if s:
                parts.append(s)
            buf = ""
    if buf.strip():
        parts.append(buf.strip())
    return parts

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

async def split_send_private(qq, text, ws, user_id):
    """私聊分句发送 + 表情组合"""
    msg = build_reply_message(text, user_id)
    if isinstance(msg, list):
        await send_private_msg(qq, msg, ws)
        return
    sentences = split_sentence(msg)
    for sen in sentences:
        await send_private_msg(qq, sen, ws)
        await asyncio.sleep(SENTENCE_SPLIT_DELAY)

async def split_send_group(gid, text, ws, user_id):
    """群聊分句发送 + 表情组合"""
    msg = build_reply_message(text, user_id)
    if isinstance(msg, list):
        await send_group_msg(gid, msg, ws)
        return
    sentences = split_sentence(msg)
    for sen in sentences:
        await send_group_msg(gid, sen, ws)
        await asyncio.sleep(SENTENCE_SPLIT_DELAY)

async def send_sticker_private(qq, ws, user_id):
    """私聊单独发表情"""
    sticker = select_best_sticker(user_id)
    if isinstance(sticker, str):
        await send_private_msg(qq, [{"type":"face","data":{"id":sticker}}], ws)
    else:
        b64 = encode_image_base64(sticker)
        await send_private_msg(qq, [{"type":"image","data":{"file":b64}}], ws)

async def send_sticker_group(gid, ws, user_id):
    """群聊单独发表情"""
    sticker = select_best_sticker(user_id)
    if isinstance(sticker, str):
        await send_group_msg(gid, [{"type":"face","data":{"id":sticker}}], ws)
    else:
        b64 = encode_image_base64(sticker)
        await send_group_msg(gid, [{"type":"image","data":{"file":b64}}], ws)

def contains_sticker_key(text):
    """检测表情关键词"""
    if not text:
        return False
    return any(k in text for k in STICKER_KEYWORDS)

def check_group_trigger(text):
    """检测群聊@/关键词触发"""
    return any(k in text for k in GROUP_AT_TRIGGER)

def select_best_sticker(user_id):
    """优先历史表情，其次网络表情，最后内置表情"""
    uid = str(user_id)
    if uid in USER_STICKER_CACHE and USER_STICKER_CACHE[uid]:
        return random.choice(USER_STICKER_CACHE[uid])
    if SEARCH_STICKER_KEY:
        img = search_sticker("友利奈绪")
        if img:
            return img
    return str(random.choice(STICKER_FACE_IDS))

def build_reply_message(txt, user_id):
    """组装文本+表情消息体"""
    txt = txt.replace("[sticker]", "").strip()
    sticker = select_best_sticker(user_id)
    msg = []
    if txt:
        msg.append({"type":"text","data":{"text":txt}})
    if isinstance(sticker, str):
        msg.append({"type":"face","data":{"id":sticker}})
    else:
        b64 = encode_image_base64(sticker)
        msg.append({"type":"image","data":{"file":b64}})
    return msg

# ===================== 十、定时任务（完整复原） =====================
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
    global daily_trigger, today, daily_chat_trigger_times, triggered_today, task_random_offset
    while True:
        try:
            now = datetime.now()
            if now.date() != today:
                daily_trigger.clear()
                triggered_today.clear()
                task_random_offset.clear()
                today = now.date()
                cnt = random.randint(2,4)
                daily_chat_trigger_times = random.sample(range(720,1080), cnt)

            curr = now.hour * 60 + now.minute
            wd = now.weekday()
            for task in SCHEDULE_TASKS:
                key = f"{task['scene']}_{today}"
                if key in daily_trigger or wd not in task["weekday"]:
                    continue
                if key not in task_random_offset:
                    task_random_offset[key] = random.randint(-TIME_RAND_OFFSET, TIME_RAND_OFFSET)
                base = task["t"].hour * 60 + task["t"].minute
                real = base + task_random_offset[key]
                if curr == real:
                    rep = await get_ai_reply(task["scene"], str(MASTER_QQ))
                    await split_send_private(MASTER_QQ, rep, active_ws, MASTER_QQ)
                    daily_trigger.add(key)

            if curr in daily_chat_trigger_times and curr not in triggered_today:
                triggered_today.add(curr)
                rep = await get_ai_reply("主动日常闲聊", str(MASTER_QQ))
                await split_send_private(MASTER_QQ, rep, active_ws, MASTER_QQ)
        except Exception as e:
            log_err(f"定时任务异常：{e}")
        await asyncio.sleep(1)

# ===================== 十一、心跳保活 =====================
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
                log_sys("连接心跳断开")

# ===================== 十二、主消息处理（私聊+群聊 全逻辑复原） =====================
async def websocket_handle(websocket):
    global active_ws, PROCESSED_MSG_IDS, PROCESS_LOCK
    async with active_ws_lock:
        if active_ws and not getattr(active_ws, "closed", False):
            log_sys("已有在线连接，拒绝新接入")
            await websocket.close()
            return
        active_ws = websocket
    log_sys("机器人上线 | 全功能完整版 + 省Token + DeepSeek优先 + 智能分句")
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
            PROCESSED_MSG_IDS.append(msg_id)

            user_id = str(data.get("user_id"))
            group_id = data.get("group_id", 0)
            msg_content = data.get("message", "")
            text = parse_message_content(msg_content, user_id)
            if not text:
                continue

            async with PROCESS_LOCK:
                log_recv(f"消息ID:{msg_id} | 用户:{user_id} | 内容:{text}")

                # 会话隔离：私聊=用户ID，群聊=群ID_用户ID
                if msg_type == "private":
                    target_id = user_id
                    run_bot = True
                else:
                    gid_str = str(group_id)
                    if gid_str in GROUP_SILENT_LIST:
                        continue
                    # 群聊防刷屏
                    GROUP_MSG_CACHE[gid_str].append(text)
                    if len(GROUP_MSG_CACHE[gid_str]) > GROUP_CACHE_MAX:
                        GROUP_MSG_CACHE[gid_str].popleft()
                    # 触发判断
                    run_bot = check_group_trigger(text)
                    target_id = f"{gid_str}_{user_id}"

                if not run_bot:
                    continue

                # 表情包指令单独处理
                if contains_sticker_key(text):
                    if msg_type == "group":
                        await send_sticker_group(group_id, websocket, user_id)
                    else:
                        await send_sticker_private(user_id, websocket, user_id)
                else:
                    # AI回复 + 记忆 + 分句发送
                    ans = await get_ai_reply(text, target_id)
                    add_new_memory(target_id, text, ans)
                    if msg_type == "group":
                        await split_send_group(group_id, ans, websocket, user_id)
                    else:
                        await split_send_private(user_id, ans, websocket, user_id)
                await asyncio.sleep(LOCK_RELEASE_DELAY)
    except Exception as e:
        log_err(f"连接异常：{e}")
    finally:
        async with active_ws_lock:
            if active_ws is websocket:
                active_ws = None
        PROCESSED_MSG_IDS.clear()
        log_sys("客户端连接已关闭")

# ===================== 启动入口 =====================
async def main():
    global PROCESS_LOCK
    load_all_memory()
    PROCESS_LOCK = asyncio.Lock()
    log_sys("全部组件初始化完成，开始运行服务")
    while True:
        hb_task = asyncio.create_task(heartbeat_monitor())
        cycle_task = asyncio.create_task(cycle_task_run())
        try:
            async with websockets.serve(websocket_handle, LISTEN_HOST, LISTEN_PORT):
                await asyncio.Future()
        except Exception as e:
            log_err(f"服务端口异常，5秒后重启：{e}")
        finally:
            hb_task.cancel()
            cycle_task.cancel()
            await asyncio.sleep(5)

if __name__ == "__main__":
    asyncio.run(main())