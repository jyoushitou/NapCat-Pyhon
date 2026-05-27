# ==============================================
# 基于消息ID精准防抖 + 20次接口重试 彻底杜绝复读
# ==============================================
import asyncio
import websockets
import requests
import json
import random
import os
import urllib3
from collections import deque
from datetime import datetime, time, date

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# 基础配置
MASTER_QQ = 822891053
LISTEN_HOST = "0.0.0.0"
LISTEN_PORT = 3001
MEMORY_FILE = "chat_memory.json"
HISTORY_TOPICS_FILE = "history_topics.json"
HEARTBEAT_INTERVAL = 8
TIME_RAND_OFFSET = 10
CONTEXT_MAX = 12
API_RETRY_DELAY = 1.5
MAX_RETRY_TIMES = 20
# 防抖参数：缓存已处理消息ID，精准拦截重复推送
PROCESSED_MSG_IDS = set()
PROCESS_LOCK = False
LOCK_RELEASE_DELAY = 0.8

# 接口配置
API_KEY = os.getenv("ARK_API_KEY")
API_URL = "https://ark.cn-beijing.volces.com/api/v3/chat/completions"
MODEL_ID = "ep-20260524110944-g7vqr"
API_TIMEOUT = 15

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
"""

# 全局变量
chat_memory = deque(maxlen=CONTEXT_MAX)
client_ws = None
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

# AI对话接口 最高重试20次
async def get_character_reply(prompt):
    msg_list = [{"role": "system", "content": SYSTEM_PROMPT}]
    for role, content in chat_memory:
        msg_list.append({"role": role, "content": content})
    msg_list.append({"role": "user", "content": prompt})

    headers = {"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"}
    req_data = {"model": MODEL_ID, "messages": msg_list, "max_tokens": 80, "temperature": 0.7}

    for idx in range(MAX_RETRY_TIMES):
        try:
            resp = requests.post(API_URL, headers=headers, json=req_data, timeout=API_TIMEOUT, verify=False)
            if resp.status_code == 200:
                res_data = resp.json()
                reply_text = res_data["choices"][0]["message"]["content"].strip()
                log_api("接口请求成功")
                return reply_text
        except Exception as e:
            log_api(f"第{idx+1}次请求失败：{str(e)}")
        await asyncio.sleep(API_RETRY_DELAY)

    backup_words = ["真是啰嗦，没必要一直说这些吧","切，随便你怎么想好了","别太过缠着我，我可没闲工夫陪你胡闹","也就只能勉强陪你聊几句而已"]
    return random.choice(backup_words)

# 消息发送
async def send_qq_msg(qq_num, text):
    global client_ws, send_lock
    async with send_lock:
        if not client_ws:
            log_err("连接离线")
            return
        try:
            payload = {"action": "send_private_msg", "params": {"user_id": qq_num, "message": text}}
            await client_ws.send(json.dumps(payload, ensure_ascii=False))
        except Exception as e:
            log_err(f"发送失败：{str(e)}")

async def split_send_reply(qq, full_text):
    final_text = full_text + "喵"
    await send_qq_msg(qq, final_text)
    log_send(final_text)

# 定时任务
SCHEDULE_TASKS = [
    {"scene":"工作日有早八，用傲娇语气催促7:30起床","weekday":[0,1,2,3,4],"t":time(7,30)},
    {"scene":"工作日无早八/周六日，吐槽赖床，8:30提醒起床","weekday":[0,1,2,3,4,5,6],"t":time(8,30)},
    {"scene":"别扭提醒10:40该点外卖了","weekday":[0,1,2,3,4,5,6],"t":time(10,40)},
    {"scene":"随口叮嘱12:30准备午睡","weekday":[0,1,2,3,4,5,6],"t":time(12,30)},
    {"scene":"提醒13:30午睡结束该起身了","weekday":[0,1,2,3,4,5,6],"t":time(13,30)},
    {"scene":"提醒16:40可以点晚餐了","weekday":[0,1,2,3,4,5,6],"t":time(16,40)},
    {"scene":"严肃催促23:00上床休息","weekday":[0,1,2,3,4,5,6],"t":time(23,0)},
    {"scene":"勒令23:30按时睡觉","weekday":[0,1,2,3,4,5,6],"t":time(23,30)},
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
                random_count = random.randint(2, 4)
                daily_chat_trigger_times = random.sample(range(720, 1080), random_count)

            curr_min = now.hour * 60 + now.minute
            week_day = now.weekday()

            for task in SCHEDULE_TASKS:
                task_key = f"{task['scene']}_{today}"
                if task_key in daily_trigger:
                    continue
                if week_day not in task["weekday"]:
                    continue
                if task_key not in task_random_offset:
                    task_random_offset[task_key] = random.randint(-TIME_RAND_OFFSET, TIME_RAND_OFFSET)
                off_min = task_random_offset[task_key]
                total_base = task["t"].hour * 60 + task["t"].minute
                real_trigger_min = total_base + off_min
                if curr_min == real_trigger_min:
                    reply_txt = await get_character_reply(task["scene"])
                    await split_send_reply(MASTER_QQ, reply_txt)
                    daily_trigger.add(task_key)
                    log_system("定时提醒执行完毕")

            if curr_min in daily_chat_trigger_times and curr_min not in triggered_today:
                triggered_today.add(curr_min)
                talk_reply = await get_character_reply("主动开启日常闲聊")
                await split_send_reply(MASTER_QQ, talk_reply)
                log_system("随机闲聊触发")
        except Exception as e:
            log_err(f"定时任务异常：{str(e)}")
        await asyncio.sleep(1)

# 心跳保活
async def heartbeat_monitor():
    global client_ws
    while True:
        await asyncio.sleep(HEARTBEAT_INTERVAL)
        if client_ws:
            try:
                await client_ws.ping()
            except:
                client_ws = None
                log_system("心跳断开")

# 消息处理：基于消息ID精准拦截重复推送
async def websocket_handle(websocket):
    global client_ws, PROCESSED_MSG_IDS, PROCESS_LOCK
    client_ws = websocket
    log_system("机器人上线，消息ID防抖+20次接口重试已启用")
    asyncio.create_task(heartbeat_monitor())
    asyncio.create_task(cycle_task_run())
    await split_send_reply(MASTER_QQ, "哼，我已经上线了，别以为我会主动搭理你")

    try:
        while True:
            raw_buf = await websocket.recv()
            raw_data = raw_buf.decode("utf-8", errors="ignore") if isinstance(raw_buf, bytes) else raw_buf
            msg_data = json.loads(raw_data)

            # 仅处理私聊消息
            if msg_data.get("message_type") != "private" or msg_data.get("user_id") != MASTER_QQ:
                continue

            # 提取OneBot标准消息ID，精准去重
            msg_id = msg_data.get("message_id")
            if msg_id in PROCESSED_MSG_IDS or PROCESS_LOCK:
                continue

            # 解析消息文本
            raw_content = msg_data.get("message", "")
            input_text = ""
            if isinstance(raw_content, list):
                for item in raw_content:
                    if item.get("type") == "text":
                        input_text += item.get("data", {}).get("text", "")
            else:
                input_text = str(raw_content).strip()
            if not input_text:
                continue

            # 锁定流程+标记已处理消息ID
            PROCESS_LOCK = True
            PROCESSED_MSG_IDS.add(msg_id)
            log_recv(f"[{msg_id}] {input_text}")

            chat_memory.append(("user", input_text))
            save_history_topic({"topic": input_text})
            answer = await get_character_reply(input_text)
            chat_memory.append(("assistant", answer))
            save_chat_memory()
            await split_send_reply(MASTER_QQ, answer)

            # 延时解锁，清理过期消息ID（避免集合无限膨胀）
            await asyncio.sleep(LOCK_RELEASE_DELAY)
            PROCESS_LOCK = False
            # 保留最近50条消息ID，防止内存堆积
            if len(PROCESSED_MSG_IDS) > 50:
                PROCESSED_MSG_IDS = set(list(PROCESSED_MSG_IDS)[-50:])
    except Exception as e:
        log_err(f"连接异常：{str(e)}")
    finally:
        client_ws = None
        PROCESS_LOCK = False
        PROCESSED_MSG_IDS.clear()
        log_system("连接断开")

# 服务启动
async def main():
    load_chat_memory()
    load_history_topics()
    log_system("初始化完成，开始监听")
    while True:
        try:
            async with websockets.serve(websocket_handle, LISTEN_HOST, LISTEN_PORT):
                await asyncio.Future()
        except Exception as e:
            log_err(f"服务异常，5秒重启：{str(e)}")
            await asyncio.sleep(5)

if __name__ == "__main__":
    asyncio.run(main())