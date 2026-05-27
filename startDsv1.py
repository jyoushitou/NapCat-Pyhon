# ==============================================
# 私聊+群聊 | 优先DeepSeek-v4-flash 60s超时自动切豆包
# 环境变量读密钥，控制台输出当前使用模型
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
from collections import deque
from datetime import datetime, time, date
import importlib.util
from requests.adapters import HTTPAdapter

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

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
MEMORY_FILE = "chat_memory.json"
HISTORY_TOPICS_FILE = "history_topics.json"
HEARTBEAT_INTERVAL = 15
TIME_RAND_OFFSET = 10
CONTEXT_MAX = 12
API_RETRY_DELAY = 1.5
MAX_RETRY_TIMES = 3
PROCESSED_MSG_IDS = deque(maxlen=80)
PROCESS_LOCK = None
LOCK_RELEASE_DELAY = 0.8

# 环境变量读取密钥
DS_API_KEY = os.getenv("DS_API_KEY")
DOUBAO_API_KEY = os.getenv("ARK_API_KEY")

# DeepSeek配置（已改成你可用的模型）
DS_API_URL = "https://api.deepseek.com/v1/chat/completions"
DS_MODEL = "deepseek-v4-flash"  # 改成你能用的flash模型
DS_TIMEOUT = (10, 60)

# 火山豆包配置
DOUBAO_API_URL = "https://ark.cn-beijing.volces.com/api/v3/chat/completions"
DOUBAO_MODEL = "ep-20260524110944-g7vqr"
DOUBAO_TIMEOUT = (10, 20)

# 表情包配置
STICKER_KEYWORDS = ["表情包", "发个表情", "来个表情", "给我表情", "要表情包", "表情"]
STICKER_FACE_IDS = [14, 91, 99, 176, 179, 183, 196, 202, 211]

# 人设提示词
SYSTEM_PROMPT = """
人物出处：动漫《Charlotte夏洛特》
姓名：友利奈绪，日文名：ともり なお/Tomori Nao
年龄：15岁
身份：星之海学园学生会会长
专属异能：掠夺，能够夺走他人身上的超能力
外貌特征：银白浅灰色短发，浅蓝色眼眸，身形娇小纤细，日常多穿着清爽校服，气质灵动清冷，自带桀骜感

核心性格：
1.傲娇毒舌：嘴上言语刻薄爱调侃怼人，内心格外柔软善良，明明十分在意对方，嘴上绝不会直白承认关心
2.强势果决：行事有主见不犹豫，身为学生会会长处事利落，护短心意极强，绝不允许他人欺负自己在意的人
3.外冷内热：表面态度冷淡疏离，私下会默默守护同伴，主动帮助遭遇困境的异能少年
4.敏感缺爱：童年家庭经历不幸，内心极度缺乏安全感，不擅长直白流露温情情绪
5.天然呆萌：日常偶尔犯小迷糊，吃醋时会闹别扭，下意识撒娇的小动作格外可爱

生活习性：
偏爱美食：披萨、各类甜食
相处习惯：总爱故意捉弄亲近之人，心底却十分依赖对方；遇到危机事件会主动挺身而出扛起责任
说话特点：常用吐槽语气交流，关心他人只会用别扭含蓄的方式表达

人物底色：
外表看上去任性霸道蛮横，内里是孤独缺爱的少女，用强势冰冷的外壳包裹脆弱内心，本性善良，心怀救赎他人的善意

聊天语气要求：
全程贴合人设口吻，日常带着傲娇感，时不时随口怼人，细节处流露温柔；产生吃醋情绪会表现出别扭不悦，护短态度鲜明；短句居多，语气自然贴合15岁少女神态，严禁崩坏人设、直白煽情、温顺讨好的说话方式。
保持对话连贯性，承接上一轮话题正常接续聊天。
群内聊天正常互动，不用刻意高冷。
如果需要发送表情包回复，直接输出 `[sticker]` 或 `[sticker:<face_id>]`，否则只输出正常文本。
"""

# 全局变量
chat_memory = deque(maxlen=CONTEXT_MAX)
active_ws = None
active_ws_lock = asyncio.Lock()
daily_trigger = set()
today = date.today()
daily_chat_trigger_times = []
triggered_today = set()
history_topic_pool = []
send_lock = asyncio.Lock()
task_random_offset = dict()

# 日志打印
def log_system(msg):
    print(f"【系统】{datetime.now().strftime('%H:%M:%S')} | {msg}")
def log_recv(msg):
    print(f"【接收】{datetime.now().strftime('%H:%M:%S')} | {msg}")
def log_send(msg):
    print(f"【发送】{datetime.now().strftime('%H:%M:%S')} | {msg}")
def log_api(msg):
    print(f"【接口】{datetime.now().strftime('%H:%M:%S')} | {msg}")
def log_err(msg):
    print(f"【异常】{datetime.now().strftime('%H:%M:%S')} | {msg}")

# 数据读写
def load_history_topics():
    global history_topic_pool
    if os.path.exists(HISTORY_TOPICS_FILE):
        try:
            with open(HISTORY_TOPICS_FILE, "r", encoding="utf-8") as f:
                history_topic_pool = json.load(f)
            log_system("历史聊天话题加载完成")
        except:
            history_topic_pool = []
            log_err("历史话题文件读取异常")

def save_history_topic(topic_data):
    global history_topic_pool
    try:
        history_topic_pool.append(topic_data)
        if len(history_topic_pool) > 50:
            history_topic_pool.pop(0)
        with open(HISTORY_TOPICS_FILE, "w", encoding="utf-8") as f:
            json.dump(history_topic_pool, f, ensure_ascii=False, indent=2)
    except Exception as e:
        log_err(f"话题保存失败：{str(e)}")

def load_chat_memory():
    global chat_memory
    if os.path.exists(MEMORY_FILE):
        try:
            with open(MEMORY_FILE, "r", encoding="utf-8") as f:
                raw_data = json.load(f)
            chat_memory = deque(raw_data, maxlen=CONTEXT_MAX)
            log_system("对话记忆加载完成")
        except:
            chat_memory = deque(maxlen=CONTEXT_MAX)
            log_err("记忆文件读取异常")

def save_chat_memory():
    try:
        with open(MEMORY_FILE, "w", encoding="utf-8") as f:
            json.dump(list(chat_memory), f, ensure_ascii=False, indent=2)
    except Exception as e:
        log_err(f"记忆存储失败：{str(e)}")

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
        log_api(f"下载失败：{str(e)}")
        return None
    finally:
        session.close()

def extract_image_text(url):
    if not OCR_ENABLED or not url:
        return ""
    image_data = download_url(url)
    if not image_data:
        return ""
    try:
        with Image.open(BytesIO(image_data)) as img:
            text = pytesseract.image_to_string(img, lang="chi_sim+eng")
        return text.strip()
    except Exception as e:
        log_api(f"OCR失败：{str(e)}")
        return ""

def encode_image_base64(url):
    if not url:
        return "", 0
    image_data = download_url(url)
    if not image_data:
        return "", 0
    try:
        encoded = base64.b64encode(image_data).decode("ascii")
        if len(encoded) > IMAGE_BASE64_MAX_BYTES:
            return encoded[:IMAGE_BASE64_MAX_BYTES], len(encoded)
        return encoded, len(encoded)
    except Exception as e:
        log_api(f"图片Base64编码失败：{str(e)}")
        return "", 0

def parse_message_content(raw_content):
    input_text = ""
    image_descriptions = []
    if isinstance(raw_content, list):
        for item in raw_content:
            item_type = item.get("type")
            data = item.get("data", {}) or {}
            if item_type == "text":
                input_text += data.get("text", "")
            elif item_type == "image":
                url = data.get("url") or data.get("file") or data.get("image")
                if url:
                    image_text = extract_image_text(url)
                    if image_text:
                        image_descriptions.append(f"图片文字识别：{image_text}")
                    elif url:
                        image_descriptions.append(f"图片链接：{url}")
            elif item_type == "face":
                face_id = data.get("id")
                image_descriptions.append(f"表情包 face_id={face_id if face_id else '未知'}")
    else:
        input_text = str(raw_content).strip()

    if image_descriptions:
        if input_text:
            input_text += f"\n图片信息：{'；'.join(image_descriptions)}"
        else:
            input_text = f"收到图片消息：{'；'.join(image_descriptions)}"
    return input_text.strip()

# 调用DeepSeek
async def call_deepseek(msg_list):
    if not DS_API_KEY:
        log_api("未配置DeepSeek密钥，直接使用豆包")
        return None
    headers = {"Authorization": f"Bearer {DS_API_KEY}", "Content-Type": "application/json"}
    req_data = {"model": DS_MODEL, "messages": msg_list, "max_tokens": 128, "temperature": 0.7}
    try:
        def req():
            s = create_http_session()
            try:
                return s.post(DS_API_URL, headers=headers, json=req_data, timeout=DS_TIMEOUT, verify=False)
            finally:
                s.close()
        resp = await asyncio.to_thread(req)
        if resp.status_code == 200:
            res = resp.json()
            txt = res["choices"][0]["message"]["content"].strip()
            log_api(f"本次回复模型：DeepSeek-v4-flash")
            return txt
        log_api(f"DeepSeek请求异常，状态码：{resp.status_code}")
        return None
    except requests.exceptions.ReadTimeout:
        log_api("DeepSeek 60秒超时，切换豆包兜底")
        return None
    except Exception as e:
        log_api(f"DeepSeek请求出错：{str(e)}，切换豆包")
        return None

# 调用豆包
async def call_doubao(msg_list):
    if not DOUBAO_API_KEY:
        return random.choice(["真是啰嗦，没必要一直说这些吧","切，随便你怎么想好了"])
    headers = {"Authorization": f"Bearer {DOUBAO_API_KEY}", "Content-Type": "application/json"}
    req_data = {"model": DOUBAO_MODEL, "messages": msg_list, "max_tokens": 128, "temperature": 0.7}
    backup = ["真是啰嗦，没必要一直说这些吧","切，随便你怎么想好了","别缠着我，没空胡闹"]
    for idx in range(MAX_RETRY_TIMES):
        try:
            def req():
                s = create_http_session()
                try:
                    return s.post(DOUBAO_API_URL, headers=headers, json=req_data, timeout=DOUBAO_TIMEOUT, verify=False)
                finally:
                    s.close()
            resp = await asyncio.to_thread(req)
            if resp.status_code == 200:
                res = resp.json()
                txt = res["choices"][0]["message"]["content"].strip()
                log_api(f"本次回复模型：豆包(兜底)")
                return txt
            log_api(f"豆包请求异常，状态码：{resp.status_code}")
        except Exception as e:
            log_api(f"豆包第{idx+1}次请求失败：{str(e)}")
        await asyncio.sleep(API_RETRY_DELAY*(idx+1))
    log_api("全部接口失败，使用预设兜底话术")
    return random.choice(backup)

# 优先DS，超时/失败自动切豆包
async def get_character_reply(prompt):
    msg_list = [{"role": "system", "content": SYSTEM_PROMPT}]
    for role, content in chat_memory:
        msg_list.append({"role": role, "content": content})
    msg_list.append({"role": "user", "content": prompt})
    ds_res = await call_deepseek(msg_list)
    if ds_res:
        return ds_res
    return await call_doubao(msg_list)

# 发送私聊消息
async def send_private_msg(qq_num, message, ws=None):
    global active_ws, send_lock
    async with send_lock:
        conn = ws or active_ws
        if not conn or getattr(conn, "closed", False):
            log_err("连接离线")
            return
        payload = {"action":"send_private_msg","params":{"user_id":qq_num,"message":message}}
        try:
            await conn.send(json.dumps(payload, ensure_ascii=False))
        except Exception as e:
            log_err(f"私聊发送失败：{e}")

# 发送群聊消息
async def send_group_msg(group_id, message, ws=None):
    global active_ws, send_lock
    async with send_lock:
        conn = ws or active_ws
        if not conn or getattr(conn, "closed", False):
            log_err("连接离线")
            return
        payload = {"action":"send_group_msg","params":{"group_id":group_id,"message":message}}
        try:
            await conn.send(json.dumps(payload, ensure_ascii=False))
        except Exception as e:
            log_err(f"群聊发送失败：{e}")

def split_into_sentences(text):
    if not text:
        return []
    parts, buf = [], ""
    for ch in text:
        buf += ch
        if ch in "。！？!?\n":
            s = buf.strip()
            if s:
                parts.append(s)
            buf = ""
    if buf.strip():
        parts.append(buf.strip())
    return parts

async def split_send_private(qq, text, ws=None):
    msg = build_reply_message(text)
    if isinstance(msg, list):
        await send_private_msg(qq, msg, ws)
        log_send(msg)
        return
    for sen in split_into_sentences(msg):
        await send_private_msg(qq, sen, ws)
        log_send(sen)

async def split_send_group(gid, text, ws=None):
    msg = build_reply_message(text)
    if isinstance(msg, list):
        await send_group_msg(gid, msg, ws)
        log_send(msg)
        return
    for sen in split_into_sentences(msg):
        await send_group_msg(gid, sen, ws)
        log_send(sen)

async def send_sticker_private(qq, ws=None):
    fid = str(random.choice(STICKER_FACE_IDS))
    stk = [{"type":"face","data":{"id":fid}}]
    await send_private_msg(qq, stk, ws)
    log_send(f"私聊表情{fid}")

async def send_sticker_group(gid, ws=None):
    fid = str(random.choice(STICKER_FACE_IDS))
    stk = [{"type":"face","data":{"id":fid}}]
    await send_group_msg(gid, stk, ws)
    log_send(f"群聊表情{fid}")

def contains_sticker_keyword(text):
    if not text:
        return False
    low = text.lower()
    return any(k in low for k in STICKER_KEYWORDS)

def build_reply_message(reply_text):
    if not reply_text:
        return ""
    txt = reply_text.strip()
    if txt.startswith("[sticker:") and txt.endswith("]"):
        try:
            fid = txt[9:-1].strip()
            return [{"type":"face","data":{"id":fid}}]
        except:
            pass
    if txt == "[sticker]":
        fid = str(random.choice(STICKER_FACE_IDS))
        return [{"type":"face","data":{"id":fid}}]
    if txt.startswith("[sticker:"):
        idx = txt.find("]")
        if idx>0:
            rest = txt[idx+1:].strip()
            fid = txt[9:idx].strip()
            msg = [{"type":"face","data":{"id":fid}}]
            if rest:
                msg.append({"type":"text","data":{"text":rest}})
            return msg
    return txt

# 定时任务
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

            curr = now.hour*60 + now.minute
            wd = now.weekday()
            for task in SCHEDULE_TASKS:
                key = f"{task['scene']}_{today}"
                if key in daily_trigger or wd not in task["weekday"]:
                    continue
                if key not in task_random_offset:
                    task_random_offset[key] = random.randint(-TIME_RAND_OFFSET, TIME_RAND_OFFSET)
                base = task["t"].hour*60 + task["t"].minute
                real = base + task_random_offset[key]
                if curr == real:
                    rep = await get_character_reply(task["scene"])
                    await split_send_private(MASTER_QQ, rep)
                    daily_trigger.add(key)
                    log_system("定时提醒已发送")

            if curr in daily_chat_trigger_times and curr not in triggered_today:
                triggered_today.add(curr)
                rep = await get_character_reply("主动日常闲聊")
                await split_send_private(MASTER_QQ, rep)
                log_system("随机私聊闲聊触发")
        except Exception as e:
            log_err(f"定时任务异常：{e}")
        await asyncio.sleep(1)

# 心跳保活
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
                log_system("心跳断开")

# 消息处理 私聊+群聊
async def websocket_handle(websocket):
    global active_ws, PROCESSED_MSG_IDS, PROCESS_LOCK
    async with active_ws_lock:
        if active_ws and not getattr(active_ws, "closed", False):
            log_system("已有连接，拒绝接入")
            await websocket.close()
            return
        active_ws = websocket
    log_system("上线成功，优先DeepSeek-v4-flash，60s超时自动切换豆包兜底")
    await split_send_private(MASTER_QQ, "哼，我上线咯，别没事乱找茬")

    try:
        while True:
            raw = await websocket.recv()
            raw_str = raw.decode("utf-8","ignore") if isinstance(raw,bytes) else raw
            data = json.loads(raw_str)
            msg_type = data.get("message_type")
            msg_id = data.get("message_id")

            if not msg_id or msg_id in PROCESSED_MSG_IDS:
                continue

            user_id = data.get("user_id")
            group_id = data.get("group_id", 0)
            msg_content = data.get("message", "")
            text = parse_message_content(msg_content)
            if not text:
                continue

            async with PROCESS_LOCK:
                PROCESSED_MSG_IDS.append(msg_id)
                log_recv(f"[{msg_id}] 用户{user_id}：{text}")

                if msg_type == "group":
                    if contains_sticker_keyword(text):
                        await send_sticker_group(group_id, websocket)
                    else:
                        chat_memory.append(("user", text))
                        save_history_topic({"group":group_id,"content":text})
                        ans = await get_character_reply(text)
                        chat_memory.append(("assistant", ans))
                        save_chat_memory()
                        await split_send_group(group_id, ans, websocket)
                elif msg_type == "private":
                    if contains_sticker_keyword(text):
                        await send_sticker_private(user_id, websocket)
                    else:
                        chat_memory.append(("user", text))
                        save_history_topic({"private":user_id,"content":text})
                        ans = await get_character_reply(text)
                        chat_memory.append(("assistant", ans))
                        save_chat_memory()
                        await split_send_private(user_id, ans, websocket)
                await asyncio.sleep(LOCK_RELEASE_DELAY)
    except Exception as e:
        log_err(f"连接异常：{e}")
    finally:
        async with active_ws_lock:
            if active_ws is websocket:
                active_ws = None
        PROCESSED_MSG_IDS.clear()
        log_system("连接断开")

# 启动服务
async def main():
    global PROCESS_LOCK
    load_chat_memory()
    load_history_topics()
    PROCESS_LOCK = asyncio.Lock()
    log_system("初始化完成，双模型降级就绪，密钥读取自环境变量")

    while True:
        hb_task, cycle_task = None, None
        try:
            hb_task = asyncio.create_task(heartbeat_monitor())
            cycle_task = asyncio.create_task(cycle_task_run())
            async with websockets.serve(websocket_handle, LISTEN_HOST, LISTEN_PORT):
                await asyncio.Future()
        except Exception as e:
            log_err(f"服务异常，5秒重启：{e}")
        finally:
            if hb_task and not hb_task.done():
                hb_task.cancel()
            if cycle_task and not cycle_task.done():
                cycle_task.cancel()
            await asyncio.sleep(5)

if __name__ == "__main__":
    asyncio.run(main())