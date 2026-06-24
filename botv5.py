# ==============================================
# 友利奈绪 QQ 机器人 v5 —— https://www.weshineapp.com/apiCLIP视觉识图 + 简短动作回复
# 功能：私聊/群聊独立记忆 + 全局关键词 + 双模型兜底
#       + CLIP本地识图打标存档 + 表情包匹配回复
#       + ≤20字+（动作）简短回复 + 定时任务 + 心跳保活
# 数据存储：MySQL
# ==============================================
import asyncio, base64, requests, urllib3, websockets, json, random, os
import hashlib, re
from io import BytesIO
from collections import deque, defaultdict
from datetime import datetime, time, date, timedelta, timezone
CST = timezone(timedelta(hours=8))
import importlib.util
from requests.adapters import HTTPAdapter
import jieba, pymysql, threading
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ===================== 1. MySQL =====================
DB_CONFIG = {"host":"192.168.0.50","port":3306,"user":"TomoriNaoBot",
             "password":"TNB","database":"TomoriNaoBotData","charset":"utf8mb4"}
_local = threading.local()
def get_db():
    if not hasattr(_local,"conn") or _local.conn is None:
        _local.conn = pymysql.connect(**DB_CONFIG,cursorclass=pymysql.cursors.DictCursor)
    return _local.conn
def get_cursor(): return get_db().cursor()

# ===================== 2. 数据库操作 =====================
MAX_USER_ROUND, MAX_GLOBAL_KEY = 15, 40

def write_log_to_db(level,msg):
    try:
        c=get_cursor()
        c.execute("INSERT INTO logs(level,message,created_at)VALUES(%s,%s,%s)",
                  (level,msg,datetime.now(CST).strftime('%Y-%m-%d %H:%M:%S')))
        c.connection.commit()
    except: pass

def get_api_key_from_db(name):
    c=get_cursor(); c.execute("SELECT key_value FROM api_keys WHERE key_name=%s",(name,))
    r=c.fetchone(); return r["key_value"] if r else ""

def reload_api_keys():
    global DS_API_KEY,DOUBAO_API_KEY,SEARCH_STICKER_KEY
    DS_API_KEY=get_api_key_from_db("DS_API_KEY")
    DOUBAO_API_KEY=get_api_key_from_db("ARK_API_KEY")
    SEARCH_STICKER_KEY=get_api_key_from_db("STICKER_API_KEY")
    log_system(f"API: DS={bool(DS_API_KEY)},豆包={bool(DOUBAO_API_KEY)},搜图={bool(SEARCH_STICKER_KEY)}")

def load_user_memories_from_db():
    c=get_cursor(); c.execute("SELECT target_id,user_msg,bot_msg FROM user_memory ORDER BY target_id,id")
    pool={}
    for r in c.fetchall():
        tid=r["target_id"]
        if tid not in pool: pool[tid]=deque(maxlen=MAX_USER_ROUND)
        pool[tid].append([r["user_msg"],r["bot_msg"]])
    return pool

def add_user_memory_to_db(tid,user_msg,bot_msg):
    c=get_cursor()
    c.execute("INSERT INTO user_memory(target_id,user_msg,bot_msg)VALUES(%s,%s,%s)",(tid,user_msg,bot_msg))
    c.execute("DELETE FROM user_memory WHERE id NOT IN(SELECT id FROM(SELECT id FROM user_memory WHERE target_id=%s ORDER BY id DESC LIMIT %s)AS tmp)AND target_id=%s",(tid,MAX_USER_ROUND,tid))
    c.connection.commit()

def load_global_keywords_from_db():
    c=get_cursor(); c.execute("SELECT keyword FROM global_keywords ORDER BY id")
    return set(r["keyword"] for r in c.fetchall())

def add_global_keywords_to_db(kws):
    c=get_cursor()
    for kw in kws: c.execute("INSERT IGNORE INTO global_keywords(keyword)VALUES(%s)",(kw,))
    c.execute("SELECT COUNT(*)as cnt FROM global_keywords")
    if c.fetchone()["cnt"]>MAX_GLOBAL_KEY:
        c.execute("DELETE FROM global_keywords WHERE id NOT IN(SELECT id FROM(SELECT id FROM global_keywords ORDER BY id DESC LIMIT %s)AS tmp)",(MAX_GLOBAL_KEY,))
    c.connection.commit()

# ===================== 3. 日志 =====================
def log_system(m): print(f"【系统】{datetime.now().strftime('%H:%M:%S')}|{m}"); write_log_to_db("系统",m)
def log_recv(m): print(f"【接收】{datetime.now().strftime('%H:%M:%S')}|{m}"); write_log_to_db("接收",m)
def log_send(m): print(f"【发送】{datetime.now().strftime('%H:%M:%S')}|{m}"); write_log_to_db("发送",str(m))
def log_api(m): print(f"【接口】{datetime.now().strftime('%H:%M:%S')}|{m}"); write_log_to_db("接口",m)
def log_err(m): print(f"【异常】{datetime.now().strftime('%H:%M:%S')}|{m}"); write_log_to_db("异常",m)

# ===================== 4. 通用工具 =====================
def create_http_session():
    s=requests.Session(); s.mount("https://",HTTPAdapter(max_retries=0)); s.mount("http://",HTTPAdapter(max_retries=0)); return s

# ===================== 5. 配置 =====================
MASTER_QQ=822891053; LISTEN_HOST="0.0.0.0"; LISTEN_PORT_QQ=3001; LISTEN_PORT_WX=3002
HEARTBEAT_INTERVAL=15; API_RETRY_DELAY=1.5; MAX_RETRY_TIMES=3
PROCESSED_MSG_IDS=deque(maxlen=80); PROCESS_LOCK=None; LOCK_RELEASE_DELAY=0.8
DS_API_KEY=DOUBAO_API_KEY=SEARCH_STICKER_KEY=""
DS_API_URL="https://api.deepseek.com/v1/chat/completions"; DS_MODEL="deepseek-v4-flash"; DS_TIMEOUT=60
DOUBAO_API_URL="https://ark.cn-beijing.volces.com/api/v3/chat/completions"
DOUBAO_MODEL="ep-20260524110944-g7vqr"; DOUBAO_TIMEOUT=60
STICKER_KEYWORDS=["表情包","发个表情","来个表情","给我表情","要表情包","表情"]
STICKER_FACE_IDS=[14,91,99,176,179,183,196,202,211]
USER_STICKER_CACHE=defaultdict(list)
STICKER_ARCHIVE_DIR="sticker_archive"; USER_STICKER_ARCHIVE=defaultdict(list)
STICKER_DATA={}; MAX_USER_STICKERS=30

# 搜图配置
STICKER_API_ALAPI_TOKEN="zyf0tbrbbwqtwtred1toshshhregoe"

# ===================== 6. CLIP（CPU） =====================
CLIP_ENABLED=False; clip_model=None; clip_processor=None
CLIP_CANDIDATE_TAGS=[
    "表情包","熊猫头","狗头","猫","狗","动物","食物","风景",
    "沙雕图","二次元","动漫","美女","帅哥","小孩","老人",
    "文字截图","聊天记录","搞笑","悲伤","生气","开心",
    "可爱","帅气","害怕","惊讶","懵逼","无语","流汗",
    "抠鼻","点赞","比心","握手","抱拳","OK","胜利",
    "晚安","早安","加油","谢谢","对不起","666","笑哭",
    "屏幕截图","自拍","合照","游戏截图","表情","漫画",
]

def init_clip_model():
    global CLIP_ENABLED,clip_model,clip_processor
    try:
        import torch,clip
        log_system("加载 CLIP (CPU)...")
        clip_model,clip_processor=clip.load("ViT-B/32",device="cpu")
        clip_model.eval(); CLIP_ENABLED=True
        log_system("CLIP 加载完成")
    except Exception as e:
        CLIP_ENABLED=False; log_system(f"CLIP加载失败(不影响运行): {e}")

async def analyze_image_with_clip(image_data:bytes,custom_tags:list=None)->tuple:
    """CLIP分析图片，返回(tags列表,描述)"""
    if not CLIP_ENABLED: return ["表情包"],"图片"
    try:
        from PIL import Image as PilImage
        import torch
        img=PilImage.open(BytesIO(image_data)).convert("RGB")
        tags=custom_tags or CLIP_CANDIDATE_TAGS
        def _run():
            inp=clip_processor(images=img,return_tensors="pt")
            txt=clip.tokenize(tags)
            with torch.no_grad():
                img_f=clip_model.encode_image(inp["pixel_values"])
                txt_f=clip_model.encode_text(txt)
            img_f/=img_f.norm(dim=-1,keepdim=True)
            txt_f/=txt_f.norm(dim=-1,keepdim=True)
            return (100.0*img_f@txt_f.T).softmax(dim=-1)[0].tolist()
        scores=await asyncio.to_thread(_run)
        idx=sorted(range(len(scores)),key=lambda i:scores[i],reverse=True)
        best_tags=[tags[i] for i in idx[:3] if scores[i]>0.01]
        desc=tags[idx[0]] if idx else "图片"
        if not best_tags: best_tags=["表情包"]
        log_api(f"CLIP: {best_tags}")
        return best_tags,desc
    except Exception as e:
        log_err(f"CLIP失败: {e}"); return ["表情包"],"图片"

# ===================== 7. 表情包存档 =====================
def init_sticker_archive():
    if not os.path.exists(STICKER_ARCHIVE_DIR): os.makedirs(STICKER_ARCHIVE_DIR)
    load_sticker_archive()
def get_sticker_hash(d): return hashlib.md5(d).hexdigest()

def archive_sticker_image(uid,img_data,tags,desc):
    try:
        h=get_sticker_hash(img_data)
        if h not in STICKER_DATA:
            with open(os.path.join(STICKER_ARCHIVE_DIR,f"{h}.jpg"),"wb") as f: f.write(img_data)
            STICKER_DATA[h]={"type":"image","data":img_data,"tags":tags,"desc":desc,"use_count":0,"users":set()}
        STICKER_DATA[h]["users"].add(str(uid)); STICKER_DATA[h]["use_count"]+=1
        if h not in USER_STICKER_ARCHIVE[str(uid)]:
            USER_STICKER_ARCHIVE[str(uid)].append(h)
            if len(USER_STICKER_ARCHIVE[str(uid)])>MAX_USER_STICKERS: USER_STICKER_ARCHIVE[str(uid)].pop(0)
        save_sticker_archive()
    except Exception as e: log_err(f"存档失败: {e}")

def load_sticker_archive():
    global USER_STICKER_ARCHIVE,STICKER_DATA
    ip=os.path.join(STICKER_ARCHIVE_DIR,"sticker_index.json")
    if not os.path.exists(ip): return
    try:
        with open(ip,"r",encoding="utf-8") as f: d=json.load(f)
        for uid,hs in d.get("user_stickers",{}).items(): USER_STICKER_ARCHIVE[uid]=hs
        for h,info in d.get("stickers",{}).items():
            STICKER_DATA[h]={"type":info["type"],"data":None,"tags":info["tags"],"desc":info["desc"],"use_count":info["use_count"],"users":set(info["users"])}
        log_system(f"存档: {len(STICKER_DATA)}个")
    except Exception as e: log_err(f"加载存档失败: {e}")

def save_sticker_archive():
    try:
        d={"user_stickers":{k:list(v) for k,v in USER_STICKER_ARCHIVE.items()},"stickers":{}}
        for h,info in STICKER_DATA.items():
            d["stickers"][h]={"type":info["type"],"tags":info["tags"],"desc":info["desc"],"use_count":info["use_count"],"users":list(info["users"])}
        with open(os.path.join(STICKER_ARCHIVE_DIR,"sticker_index.json"),"w",encoding="utf-8") as f: json.dump(d,f,ensure_ascii=False,indent=2)
    except Exception as e: log_err(f"保存失败: {e}")

def load_sticker_data(h):
    if h not in STICKER_DATA: return None
    if STICKER_DATA[h]["data"] is not None: return STICKER_DATA[h]["data"]
    fp=os.path.join(STICKER_ARCHIVE_DIR,f"{h}.jpg")
    if os.path.exists(fp):
        with open(fp,"rb") as f: d=f.read()
        STICKER_DATA[h]["data"]=d; return d
    return None

def select_best_sticker_by_tags(kws,uid):
    if not STICKER_DATA: return None
    us=[h for h in USER_STICKER_ARCHIVE.get(str(uid),[]) if h in STICKER_DATA]
    cand=us if us else list(STICKER_DATA.keys())
    if not cand: return None
    best_h,best_s=None,-1
    for h in cand:
        tags=STICKER_DATA[h].get("tags",[])
        if not tags: continue
        s=sum(1 for kw in kws if any(kw in tag or tag in kw for tag in tags))
        if s>best_s: best_h,best_s=h,s
    if best_h and best_s>0: return load_sticker_data(best_h)
    if us: return load_sticker_data(random.choice(us))
    return None

# ===================== 8. 人设 =====================
# 本地基础人设
LOCAL_SYSTEM_PROMPT = """
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
3. 多条回复时，第一条是对话内容，第二条是动作描写（单独一行），如：
   哼，谁理你啊
   （扭头）
4. 如果只有一条，末尾不要带动作括号

【全局长期记忆】：{global_keywords}
【与你最近的对话】：{current_dialogue}
"""

# 人设补充URL（在线拉取，备用）
PERSONALITY_SUPPLEMENT_URLS = [
    "https://raw.githubusercontent.com/your-repo/nao_personality/main/base.txt",
]

PERSONALITY_SUPPLEMENT = ""

def load_personality_supplement():
    global PERSONALITY_SUPPLEMENT
    for url in PERSONALITY_SUPPLEMENT_URLS:
        try:
            s = create_http_session()
            r = s.get(url, timeout=(5, 10), verify=False)
            if r.status_code == 200 and r.text.strip():
                PERSONALITY_SUPPLEMENT = r.text.strip()
                log_system(f"人设补充加载成功: {url}")
                return
        except Exception as e:
            log_api(f"人设补充加载失败 {url}: {e}")
        finally:
            try: s.close()
            except: pass
    log_system("人设补充未加载，使用本地人设")

def get_system_prompt():
    if PERSONALITY_SUPPLEMENT:
        return PERSONALITY_SUPPLEMENT + "\n\n" + LOCAL_SYSTEM_PROMPT
    return LOCAL_SYSTEM_PROMPT

# ===================== 9. 全局变量 =====================
user_memory_pool={}; global_keyword_set=set()
active_ws_qq=None; active_ws_wx=None
active_ws_lock=asyncio.Lock()
daily_trigger=set(); today=date.today()
daily_chat_trigger_times=[]; triggered_today=set()
send_lock=asyncio.Lock(); task_trigger_minute={}

# ===================== 10. 记忆 =====================
def extract_keywords(text):
    sw={"的","了","是","我","你","在","有","就","不","都","吗","吧","啊","哦","呀","呢","呗","啦"}
    return [w for w in jieba.lcut(text) if len(w)>1 and w not in sw]

def load_memories():
    global user_memory_pool,global_keyword_set
    user_memory_pool=load_user_memories_from_db()
    global_keyword_set=load_global_keywords_from_db()
    log_system(f"记忆: {len(user_memory_pool)}对象,{len(global_keyword_set)}关键词")

def add_target_memory(tid,user_msg,bot_msg):
    add_user_memory_to_db(tid,user_msg,bot_msg)
    user_memory_pool.setdefault(tid,deque(maxlen=MAX_USER_ROUND)).append([user_msg,bot_msg])
    nk=extract_keywords(f"{user_msg} {bot_msg}")
    add_global_keywords_to_db(nk)
    for k in nk: global_keyword_set.add(k)

def build_memory_context(tid):
    kw="、".join(global_keyword_set) if global_keyword_set else "无"
    dia=""
    if tid in user_memory_pool:
        for u,b in list(user_memory_pool[tid])[-6:]: dia+=f"用户:{u}\n奈绪:{b}\n"
    else: dia="无"
    return kw,dia

# ===================== 11. 图片下载 =====================
def download_url(url):
    if not url: return None
    s=create_http_session()
    try:
        r=s.get(url,timeout=(5,10),verify=False); r.raise_for_status(); return r.content
    except Exception as e: log_api(f"下载失败:{e}"); return None
    finally: s.close()

def encode_image_base64(d):
    try: return base64.b64encode(d).decode()[:150000]
    except: return ""

# ===================== 12. 消息解析(CLIP识图) =====================
async def parse_message_content(raw_content,user_id):
    input_text=""; img_info=[]
    if isinstance(raw_content,list):
        for item in raw_content:
            t=item.get("type"); d=item.get("data",{})
            if t=="text": input_text+=d.get("text","")
            elif t=="image":
                url=d.get("url") or d.get("file")
                img_data=download_url(url)
                if img_data:
                    tags,desc=await analyze_image_with_clip(img_data)
                    archive_sticker_image(user_id,img_data,tags,desc)
                    img_info.append(f"[{desc}]")
                    input_text+=" "+" ".join(tags[:2])
                else: img_info.append("[图]")
            elif t=="face":
                fid=str(d.get("id"))
                if fid:
                    USER_STICKER_CACHE[user_id].append(fid)
                    if len(USER_STICKER_CACHE[user_id])>20: USER_STICKER_CACHE[user_id].pop(0)
                img_info.append(f"[表情{fid}]")
    else: input_text=str(raw_content).strip()
    if img_info: input_text=f"{input_text} {' '.join(img_info)}"
    return input_text.strip()

# ===================== 13. 模型调用(简短) =====================
async def call_deepseek(msgs,retry=2):
    if not DS_API_KEY: return None
    h={"Authorization":f"Bearer {DS_API_KEY}","Content-Type":"application/json"}
    d={"model":DS_MODEL,"messages":msgs,"max_tokens":80,"temperature":0.7}
    for a in range(retry):
        try:
            def req():
                s=create_http_session(); return s.post(DS_API_URL,headers=h,json=d,timeout=DS_TIMEOUT,verify=False)
            r=await asyncio.to_thread(req)
            if r.status_code==200:
                t=r.json()["choices"][0]["message"]["content"].strip()
                if t: log_api("DS回复"); return t
        except Exception as e: log_api(f"DS{a+1}失败:{e}")
        await asyncio.sleep(API_RETRY_DELAY*(a+1))
    return None

async def call_doubao(msgs):
    if not DOUBAO_API_KEY: return random.choice(["哼(扭头)","才不理你(抱手)","切(翻白眼)"])
    h={"Authorization":f"Bearer {DOUBAO_API_KEY}","Content-Type":"application/json"}
    d={"model":DOUBAO_MODEL,"messages":msgs,"max_tokens":80,"temperature":0.7}
    for a in range(MAX_RETRY_TIMES):
        try:
            def req():
                s=create_http_session(); return s.post(DOUBAO_API_URL,headers=h,json=d,timeout=DOUBAO_TIMEOUT,verify=False)
            r=await asyncio.to_thread(req)
            if r.status_code==200:
                t=r.json()["choices"][0]["message"]["content"].strip()
                log_api("豆包回复"); return t
        except Exception as e: log_api(f"豆包{a+1}失败:{e}")
        await asyncio.sleep(API_RETRY_DELAY*(a+1))
    return random.choice(["哼(扭头)","才不理你(抱手)","切(翻白眼)"])

async def get_character_reply(txt,tid,current_kws=None):
    kw,dia=build_memory_context(tid)
    # 当前关键词也喂给AI
    cur_kw_str="、".join(current_kws) if current_kws else "无"
    sys_p=get_system_prompt().format(global_keywords=kw,current_dialogue=dia)
    # 把当前关键词加入user消息
    user_content=f"{txt}\n(当前话题关键词:{cur_kw_str})"
    msgs=[{"role":"system","content":sys_p},{"role":"user","content":user_content}]
    r=await call_deepseek(msgs)
    if not r: r=await call_doubao(msgs)
    return r

# ===================== 14. 发送 =====================
def select_best_sticker(uid,ctx=""):
    kws=extract_keywords(ctx)
    img=select_best_sticker_by_tags(kws,uid)
    if img: return img
    uid_s=str(uid)
    if uid_s in USER_STICKER_CACHE and USER_STICKER_CACHE[uid_s]: return random.choice(USER_STICKER_CACHE[uid_s])
    return str(random.choice(STICKER_FACE_IDS))

def build_reply_message(txt,uid,kws=None):
    txt=txt.replace("[sticker]","").strip()
    lines=[l.strip() for l in txt.split('\n') if l.strip()]
    dialog=lines[0] if lines else txt
    action_line=lines[1] if len(lines)>1 else ""
    # 如果动作行不是括号格式，合并回对话
    if action_line and not (action_line.startswith('（') or action_line.startswith('(')):
        dialog=txt
        action_line=""
    kw=kws or extract_keywords(txt)
    msg=[]
    if dialog: msg.append({"type":"text","data":{"text":dialog}})
    if action_line: msg.append({"type":"text","data":{"text":action_line}})
    # 在动作后加可爱表情包
    if action_line:
        img=select_best_sticker_by_tags(kw,uid)
        if img:
            msg.append({"type":"image","data":{"file":encode_image_base64(img)}})
    # 如果没有动作行，也加个QQ表情
    elif not action_line:
        s=select_best_sticker(uid,txt+" "+" ".join(kw))
        if isinstance(s,str): msg.append({"type":"face","data":{"id":s}})
        elif s: msg.append({"type":"image","data":{"file":encode_image_base64(s)}})
    return msg

async def send_private_msg(qq,msg,ws):
    async with send_lock:
        try: await ws.send(json.dumps({"action":"send_private_msg","params":{"user_id":qq,"message":msg}},ensure_ascii=False))
        except Exception as e: log_err(f"私聊失败:{e}")

async def send_group_msg(gid,msg,ws):
    async with send_lock:
        try: await ws.send(json.dumps({"action":"send_group_msg","params":{"group_id":gid,"message":msg}},ensure_ascii=False))
        except Exception as e: log_err(f"群聊失败:{e}")

async def send_short_reply(tid,text,ws,uid,is_group=False,kws=None):
    msg=build_reply_message(text,uid,kws)
    if is_group: await send_group_msg(tid,msg,ws)
    else: await send_private_msg(tid,msg,ws)
    log_send(f"回复:{text[:40]}")

async def send_sticker_private(qq,ws,uid):
    s=select_best_sticker(uid)
    if isinstance(s,str): await send_private_msg(qq,[{"type":"face","data":{"id":s}}],ws)
    else: await send_private_msg(qq,[{"type":"image","data":{"file":encode_image_base64(s)}}],ws)

async def send_sticker_group(gid,ws,uid):
    s=select_best_sticker(uid)
    if isinstance(s,str): await send_group_msg(gid,[{"type":"face","data":{"id":s}}],ws)
    else: await send_group_msg(gid,[{"type":"image","data":{"file":encode_image_base64(s)}}],ws)

# ===================== 14b. 网络搜可爱表情包 =====================
def search_cute_sticker_from_web(keywords):
    """从ALAPI搜表情包，返回一堆URL随机选一个"""
    kw="表情包 "+" ".join(keywords[:3])
    session = create_http_session()
    try:
        r = session.get("https://v3.alapi.cn/api/doutu",
                       params={"token": STICKER_API_ALAPI_TOKEN, "keyword": kw},
                       timeout=10, verify=False)
        if r.status_code == 200:
            data = r.json()
            if data.get("data") and isinstance(data["data"], list):
                urls = data["data"]
                log_api(f"ALAPI返回{len(urls)}个表情包链接")
                if len(urls) == 0: return None
                # 随机选一个
                selected = random.choice(urls)
                img_url = selected if isinstance(selected, str) else selected.get("url") or selected.get("img")
                if img_url:
                    img_data = download_url(img_url)
                    if img_data:
                        log_api(f"搜图[ALAPI]: {kw} → {img_url[:40]}")
                        session.close()
                        return img_data
        else:
            log_api(f"ALAPI搜图失败: HTTP {r.status_code}")
    except Exception as e:
        log_api(f"ALAPI异常: {e}")
    finally:
        session.close()
    log_api("搜图全部失败，使用本地存档")
    return None

async def send_cute_sticker(qq,ws,uid,keywords):
    """发可爱表情包（网络搜图+本地备份）"""
    img = search_cute_sticker_from_web(keywords)
    if img:
        b64=encode_image_base64(img)
        msg=[{"type":"image","data":{"file":b64}}]
        await send_private_msg(qq,msg,ws)
    else:
        # 本地兜底：从存档选一个
        img=select_best_sticker_by_tags(keywords,uid)
        if img:
            b64=encode_image_base64(img)
            msg=[{"type":"image","data":{"file":b64}}]
            await send_private_msg(qq,msg,ws)

async def send_cute_sticker_group(gid,ws,uid,keywords):
    img = search_cute_sticker_from_web(keywords)
    if img:
        b64=encode_image_base64(img)
        msg=[{"type":"image","data":{"file":b64}}]
        await send_group_msg(gid,msg,ws)
    else:
        img=select_best_sticker_by_tags(keywords,uid)
        if img:
            b64=encode_image_base64(img)
            msg=[{"type":"image","data":{"file":b64}}]
            await send_group_msg(gid,msg,ws)

def contains_sticker_key(t):
    if not t: return False
    return any(k in t.lower() for k in STICKER_KEYWORDS)

# ===================== 15. 定时任务 =====================
SCHEDULE_TASKS=[
    {"scene":"催起床","weekday":[0,1,2,3,4],"t":time(7,30)},
    {"scene":"周末吐槽赖床","weekday":[0,1,2,3,4,5,6],"t":time(8,30)},
    {"scene":"提醒点外卖","weekday":[0,1,2,3,4,5,6],"t":time(10,40)},
    {"scene":"叮嘱午睡","weekday":[0,1,2,3,4,5,6],"t":time(12,30)},
    {"scene":"提醒起身","weekday":[0,1,2,3,4,5,6],"t":time(13,30)},
    {"scene":"提醒晚餐","weekday":[0,1,2,3,4,5,6],"t":time(16,40)},
    {"scene":"催睡觉","weekday":[0,1,2,3,4,5,6],"t":time(23,0)},
    {"scene":"勒令睡觉","weekday":[0,1,2,3,4,5,6],"t":time(23,30)},
]

async def cycle_task_run():
    global daily_trigger,today,daily_chat_trigger_times,triggered_today,task_trigger_minute
    await asyncio.sleep(10)
    while True:
        try:
            now=datetime.now()
            if now.date()!=today:
                daily_trigger.clear(); triggered_today.clear(); task_trigger_minute.clear()
                today=now.date(); cnt=random.randint(2,4)
                daily_chat_trigger_times=random.sample(range(720,1080),cnt)
                for task in SCHEDULE_TASKS:
                    if now.weekday() not in task["weekday"]: continue
                    base=task["t"].hour*60+task["t"].minute
                    task_trigger_minute[f"{task['scene']}_{today}"]=max(0,min(1439,base+random.randint(-10,10)))
            cur=now.hour*60+now.minute
            for task in SCHEDULE_TASKS:
                key=f"{task['scene']}_{today}"
                if key in daily_trigger: continue
                if now.weekday() not in task["weekday"]: continue
                tm=task_trigger_minute.get(key)
                if tm is None or cur!=tm: continue
                rep=await get_character_reply(task["scene"],str(MASTER_QQ))
                await send_short_reply(MASTER_QQ,rep,active_ws_qq,MASTER_QQ)
                daily_trigger.add(key); log_system(f"定时:{task['scene']}")
            if cur in daily_chat_trigger_times and cur not in triggered_today:
                triggered_today.add(cur)
                rep=await get_character_reply("闲聊",str(MASTER_QQ))
                await send_short_reply(MASTER_QQ,rep,active_ws_qq,MASTER_QQ)
                log_system("闲聊触发")
        except Exception as e: log_err(f"定时异常:{e}")
        await asyncio.sleep(1)

# ===================== 16. 心跳 =====================
async def heartbeat_monitor(label,ws_ref):
    """通用心跳监测，label如'QQ'/'微信'，ws_ref是全局变量引用"""
    while True:
        await asyncio.sleep(HEARTBEAT_INTERVAL)
        ws = ws_ref
        if ws and not getattr(ws,"closed",False):
            try: await ws.ping()
            except:
                log_system(f"{label}心跳断开")

# ===================== 17. QQ消息处理 =====================
async def websocket_handle_qq(ws):
    global active_ws_qq,PROCESSED_MSG_IDS,PROCESS_LOCK
    async with active_ws_lock:
        if active_ws_qq and not getattr(active_ws_qq,"closed",False): await ws.close(); return
        active_ws_qq=ws
    log_system("QQ上线(CLIP版)")
    await send_short_reply(MASTER_QQ,"哼,上线了(叉腰)",ws,MASTER_QQ)
    try:
        while True:
            raw=await ws.recv()
            rs=raw.decode("utf-8","ignore") if isinstance(raw,bytes) else raw
            d=json.loads(rs); mt=d.get("message_type"); mid=d.get("message_id")
            if not mid or mid in PROCESSED_MSG_IDS: continue
            uid=str(d.get("user_id")); gid=d.get("group_id",0)
            text=await parse_message_content(d.get("message",""),uid)
            if not text: continue
            async with PROCESS_LOCK:
                PROCESSED_MSG_IDS.append(mid)
                log_recv(f"[QQ]{uid}:{text}")
                tid=uid if mt=="private" else str(gid)
                ck=extract_keywords(text)
                if contains_sticker_key(text):
                    if mt=="group": await send_sticker_group(gid,ws,uid)
                    else: await send_sticker_private(uid,ws,uid)
                else:
                    ans=await get_character_reply(text,tid,ck)
                    add_target_memory(tid,text,ans)
                    await send_short_reply(gid if mt=="group" else uid,ans,ws,uid,mt=="group",ck)
                await asyncio.sleep(LOCK_RELEASE_DELAY)
    except Exception as e: log_err(f"QQ异常:{e}")
    finally:
        async with active_ws_lock:
            if active_ws_qq is ws: active_ws_qq=None
        PROCESSED_MSG_IDS.clear(); log_system("QQ断开")

# ===================== 17b. 微信消息处理(OpenClaw-WeChat) =====================
WX_PROCESSED_MSG_IDS=deque(maxlen=80)

async def websocket_handle_wx(ws):
    """OpenClaw-WeChat 独立接入，共享同一套记忆/关键词/人设/表情包"""
    global active_ws_wx
    async with active_ws_lock:
        if active_ws_wx and not getattr(active_ws_wx,"closed",False): await ws.close(); return
        active_ws_wx=ws
    log_system("微信上线")
    try:
        while True:
            raw=await ws.recv()
            rs=raw.decode("utf-8","ignore") if isinstance(raw,bytes) else raw
            d=json.loads(rs)
            # —— OpenClaw-WeChat 消息格式 ——
            msg_type=d.get("Type") or d.get("type",0)
            content=d.get("Content") or d.get("content","")
            from_user=d.get("FromUser") or d.get("from","")
            from_group=d.get("FromGroup") or d.get("roomid","")
            msg_id=d.get("MsgId") or d.get("id","")
            is_group=bool(from_group)
            if not msg_id or msg_id in WX_PROCESSED_MSG_IDS: continue
            if not content: continue
            WX_PROCESSED_MSG_IDS.append(msg_id)
            log_recv(f"[微信]{from_user}:{content}")
            tid = from_group if is_group else from_user
            ck=extract_keywords(content)
            if contains_sticker_key(content):
                # 微信搜表情包
                s=search_cute_sticker_from_web(ck) or select_best_sticker_by_tags(ck,from_user)
                if s:
                    b64="base64://"+base64.b64encode(s).decode()
                    wx_reply = {"Type": 3, "Content": b64, "ToUser": from_user}
                    if is_group: wx_reply["ToGroup"] = from_group
                    try:
                        await ws.send(json.dumps(wx_reply, ensure_ascii=False))
                        log_send(f"微信表情包")
                    except Exception as e: log_err(f"微信发图失败:{e}")
                    continue
            ans=await get_character_reply(content,tid,ck)
            add_target_memory(tid,content,ans)
            # 组装回复：对话+动作+表情包
            lines=[l.strip() for l in ans.split('\n') if l.strip()]
            txt=lines[0] if lines else ans
            action=lines[1] if len(lines)>1 and (lines[1].startswith('（') or lines[1].startswith('(')) else ""
            msg_parts = txt
            if action: msg_parts += "\n" + action
            # 加上表情包图片
            img=search_cute_sticker_from_web(ck) or select_best_sticker_by_tags(ck,from_user)
            wx_reply = {"Type": 1, "Content": msg_parts, "ToUser": from_user}
            if is_group: wx_reply["ToGroup"] = from_group
            # 如果有表情包图，Type=3 发图后再发文字
            try:
                await ws.send(json.dumps(wx_reply, ensure_ascii=False))
                log_send(f"微信:{ans[:30]}")
                if img:
                    b64="base64://"+base64.b64encode(img).decode()
                    await ws.send(json.dumps({"Type": 3, "Content": b64, "ToUser": from_user}, ensure_ascii=False))
            except Exception as e:
                log_err(f"微信发消息失败:{e}")
            await asyncio.sleep(LOCK_RELEASE_DELAY)
    except Exception as e: log_err(f"微信异常:{e}")
    finally:
        async with active_ws_lock:
            if active_ws_wx is ws: active_ws_wx=None
        log_system("微信断开")

# ===================== 18. 主程序 =====================
async def main():
    global PROCESS_LOCK
    load_memories(); init_sticker_archive(); init_clip_model(); reload_api_keys(); load_personality_supplement()
    PROCESS_LOCK=asyncio.Lock()
    log_system("初始化完成(CLIP识图版)")
    while True:
        hb=asyncio.create_task(heartbeat_monitor("QQ",active_ws_qq))
        hb_wx=asyncio.create_task(heartbeat_monitor("微信",active_ws_wx))
        cyc=asyncio.create_task(cycle_task_run())
        try:
            async with websockets.serve(websocket_handle_qq,LISTEN_HOST,LISTEN_PORT_QQ), \
                       websockets.serve(websocket_handle_wx,LISTEN_HOST,LISTEN_ORT_WX):
                await asyncio.Future()
        except Exception as e:
            log_err(f"重启:{e}")
        finally:
            hb.cancel(); hb_wx.cancel(); cyc.cancel()
            await asyncio.sleep(5)

if __name__=="__main__": asyncio.run(main())