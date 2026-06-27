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
try:
    from chinesecalendar import is_workday as _is_workday
    CHINESE_CALENDAR_OK = True
except:
    CHINESE_CALENDAR_OK = False
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
MASTER_QQ=822891053; LISTEN_HOST="0.0.0.0"; LISTEN_PORT_QQ=3001
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

# CLIP 打标候选标签（图片通用）
CLIP_IMAGE_TAGS = ["表情包","二次元","动漫","真人","美女","帅哥","动物","猫","狗","食物","风景","沙雕图","搞笑","可爱","帅气","悲伤","生气","开心","懵逼","无语","流汗","抠鼻","点赞","比心","晚安","早安","加油","谢谢","对不起","666","笑哭","截图","自拍","合照","游戏截图","漫画","文字","动图","纯色","黑白"]

# ===================== 6. CLIP（CPU） =====================
CLIP_ENABLED=False; clip_model=None; clip_processor=None

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
        tags=custom_tags or CLIP_IMAGE_TAGS
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

# ===================== 7. 统一图片系统（兼容旧 sticker_archive + 新 images 表） =====================
# 旧 sticker_archive 系统保留，迁移到新库时自动导入
# 新图片存 images/ 目录 + images 数据库表
IMAGE_DIR = "images"

def image_local_path(md5_hash, ext="jpg"):
    os.makedirs(IMAGE_DIR, exist_ok=True)
    return os.path.join(IMAGE_DIR, f"{md5_hash}.{ext}")

def save_image_to_db(md5_hash, img_data, tags, source_url="", uid=""):
    ext = "gif" if img_data[:6] in (b"GIF89a", b"GIF87a") else "jpg"
    fp = image_local_path(md5_hash, ext)
    try:
        c = get_cursor()
        c.execute(
            "INSERT IGNORE INTO images(md5_hash, image_data, tags, source_url, file_path, ext, use_count) VALUES(%s,%s,%s,%s,%s,%s,0)",
            (md5_hash, img_data, tags, source_url, fp, ext)
        )
        c.connection.commit()
    except Exception as e:
        log_err(f"图片入库失败: {e}")

def load_image_from_db(md5_hash):
    try:
        c = get_cursor()
        c.execute("SELECT image_data, ext FROM images WHERE md5_hash=%s", (md5_hash,))
        r = c.fetchone()
        if r:
            return r["image_data"], r["ext"]
    except:
        pass
    return None, None

def image_already_exists(md5_hash):
    try:
        c = get_cursor()
        c.execute("SELECT id, tags, file_path, ext FROM images WHERE md5_hash=%s", (md5_hash,))
        r = c.fetchone()
        if r:
            fp = r["file_path"]
            if fp and os.path.exists(fp):
                return True, r["tags"], fp
            img_data, ext = load_image_from_db(md5_hash)
            if img_data:
                fp = image_local_path(md5_hash, ext)
                with open(fp, "wb") as f:
                    f.write(img_data)
                return True, r["tags"], fp
        return False, "", ""
    except:
        return False, "", ""

async def process_and_save_image(img_data, source_url="", uid=""):
    """统一处理一张图片：CLIP打标→存本地→入库，返回(md5, tags_str, file_path)"""
    if not img_data:
        return None, "", ""
    md5 = hashlib.md5(img_data).hexdigest()
    exists, tags_str, fp = image_already_exists(md5)
    if exists:
        log_api(f"图片命中缓存: {md5[:12]} tags={tags_str}")
        return md5, tags_str, fp
    tags, desc = await analyze_image_with_clip(img_data, CLIP_IMAGE_TAGS)
    tags_str = ",".join(tags)
    ext = "gif" if img_data[:6] in (b"GIF89a", b"GIF87a") else "jpg"
    fp = image_local_path(md5, ext)
    with open(fp, "wb") as f:
        f.write(img_data)
    save_image_to_db(md5, img_data, tags_str, source_url, uid)
    log_api(f"图片已保存: {md5[:12]}.{ext} tags={tags_str}")
    return md5, tags_str, fp

def search_local_image_by_tags(keywords, limit=5):
    """从数据库按tags关键词搜索图片"""
    if not keywords:
        return []
    try:
        c = get_cursor()
        conds = " OR ".join(["tags LIKE %s" for _ in keywords[:3]])
        params = [f"%{kw}%" for kw in keywords[:3]]
        sql = f"SELECT md5_hash, tags, file_path, use_count FROM images WHERE {conds} ORDER BY use_count DESC LIMIT %s"
        params.append(limit)
        c.execute(sql, params)
        results = []
        for r in c.fetchall():
            fp = r["file_path"]
            if fp and os.path.exists(fp):
                results.append((r["md5_hash"], r["tags"], fp))
        return results
    except Exception as e:
        log_err(f"搜索图片失败: {e}")
        return []

def get_random_local_image():
    try:
        c = get_cursor()
        c.execute("SELECT md5_hash, tags, file_path FROM images ORDER BY RAND() LIMIT 1")
        r = c.fetchone()
        if r and r["file_path"] and os.path.exists(r["file_path"]):
            return (r["md5_hash"], r["tags"], r["file_path"])
    except:
        pass
    return None

async def fetch_and_save_acg_image():
    """从 ALAPI ACG 获取二次元图→下载→打标→入库，返回文件路径"""
    session = create_http_session()
    try:
        r = session.get("https://v3.alapi.cn/api/acg",
                       params={"token": STICKER_API_ALAPI_TOKEN, "format": "json"},
                       timeout=10, verify=False)
        if r.status_code == 200:
            data = r.json()
            if data.get("code") == 200 and data.get("data"):
                img_url = data["data"].get("url") if isinstance(data["data"], dict) else None
                if img_url:
                    img_data = download_url(img_url)
                    if img_data:
                        md5, tags_str, fp = await process_and_save_image(img_data, img_url, "acg")
                        if fp:
                            return fp
    except Exception as e:
        log_api(f"ACG接口异常: {e}")
    finally:
        session.close()
    return None

async def search_alapi_and_save(keywords):
    """从 ALAPI 搜图→下载→打标→入库，返回文件路径"""
    kw = "表情包 " + " ".join(keywords[:3])
    session = create_http_session()
    try:
        r = session.get("https://v3.alapi.cn/api/doutu",
                       params={"token": STICKER_API_ALAPI_TOKEN, "keyword": kw},
                       timeout=10, verify=False)
        if r.status_code == 200:
            data = r.json()
            if data.get("data") and isinstance(data["data"], list) and data["data"]:
                selected = random.choice(data["data"])
                img_url = selected if isinstance(selected, str) else selected.get("url") or selected.get("img")
                if img_url:
                    img_data = download_url(img_url)
                    if img_data:
                        md5, tags_str, fp = await process_and_save_image(img_data, img_url, "alapi")
                        if fp:
                            return fp
    except Exception as e:
        log_api(f"ALAPI搜图异常: {e}")
    finally:
        session.close()
    return None

async def get_best_image(keywords, uid=""):
    """核心发图函数：优先本地匹配→没有则ALAPI搜→搜到入库，返回文件路径"""
    results = search_local_image_by_tags(keywords, limit=5)
    if results:
        selected = random.choice(results)
        try:
            c = get_cursor()
            c.execute("UPDATE images SET use_count=use_count+1 WHERE md5_hash=%s", (selected[0],))
            c.connection.commit()
        except:
            pass
        return selected[2]
    fp = await search_alapi_and_save(keywords)
    if fp:
        return fp
    rand = get_random_local_image()
    if rand:
        return rand[2]
    return None

# 旧 sticker_archive 系统保留兼容
STICKER_ARCHIVE_DIR = "sticker_archive"
USER_STICKER_CACHE = defaultdict(list)
USER_STICKER_ARCHIVE = defaultdict(list)
STICKER_DATA = {}
STICKER_FACE_IDS = [14,91,99,176,179,183,196,202,211]
MAX_USER_STICKERS = 30

def init_sticker_archive():
    if not os.path.exists(STICKER_ARCHIVE_DIR): os.makedirs(STICKER_ARCHIVE_DIR)
    load_sticker_archive()

def load_sticker_archive():
    global USER_STICKER_ARCHIVE, STICKER_DATA
    ip = os.path.join(STICKER_ARCHIVE_DIR, "sticker_index.json")
    if not os.path.exists(ip):
        return
    try:
        with open(ip, "r", encoding="utf-8") as f:
            d = json.load(f)
        for uid, hs in d.get("user_stickers", {}).items():
            USER_STICKER_ARCHIVE[uid] = hs
        for h, info in d.get("stickers", {}).items():
            STICKER_DATA[h] = {
                "type": info["type"],
                "data": None,
                "tags": info["tags"],
                "desc": info["desc"],
                "use_count": info["use_count"],
                "users": set(info["users"]),
            }
            # 尝试迁入新库
            try:
                c = get_cursor()
                c.execute("SELECT id FROM images WHERE md5_hash=%s", (h,))
                if not c.fetchone():
                    fp = os.path.join(STICKER_ARCHIVE_DIR, f"{h}.jpg")
                    with open(fp, "rb") as f:
                        img_data = f.read()
                    c.execute(
                        "INSERT IGNORE INTO images(md5_hash, image_data, tags, source_url, file_path, ext, use_count) VALUES(%s,%s,%s,'','',%s,%s)",
                        (h, img_data, ",".join(info["tags"]), f"images/{h}.jpg", info["use_count"]),
                    )
                    c.connection.commit()
                    log_system(f"旧存档迁移: {h[:12]}")
            except:
                pass
        log_system(f"存档案: {len(STICKER_DATA)}个+已迁入新库")
    except Exception as e:
        log_err(f"加载存档失败: {e}")

def save_sticker_archive():
    try:
        d = {
            "user_stickers": {k: list(v) for k, v in USER_STICKER_ARCHIVE.items()},
            "stickers": {},
        }
        for h, info in STICKER_DATA.items():
            d["stickers"][h] = {
                "type": info["type"],
                "tags": info["tags"],
                "desc": info["desc"],
                "use_count": info["use_count"],
                "users": list(info["users"]),
            }
        with open(os.path.join(STICKER_ARCHIVE_DIR, "sticker_index.json"), "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False, indent=2)
    except Exception as e:
        log_err(f"保存失败: {e}")

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
active_ws_qq=None
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

def contains_sticker_key(text):
    """检查文本是否包含表情包触发关键词"""
    for kw in STICKER_KEYWORDS:
        if kw in text:
            return True
    return False

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
                    # 统一处理：打标→本地→入库
                    md5, tags_str, fp = await process_and_save_image(img_data, url, user_id)
                    if tags_str:
                        tag_list = tags_str.split(",")
                        img_info.append(f"[{tag_list[0]}]")
                        input_text += " " + " ".join(tag_list[:2])
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
    """旧接口兼容，优先查新库，其次旧存档，最后QQ表情"""
    kws = extract_keywords(ctx)
    # 新库查
    results = search_local_image_by_tags(kws, limit=3)
    if results:
        try:
            c = get_cursor()
            c.execute("UPDATE images SET use_count=use_count+1 WHERE md5_hash=%s", (results[0][0],))
            c.connection.commit()
        except:
            pass
        return results[0][2]  # 返回文件路径
    # 旧存档查
    uid_s = str(uid)
    if uid_s in USER_STICKER_ARCHIVE and USER_STICKER_ARCHIVE[uid_s]:
        for h in reversed(USER_STICKER_ARCHIVE[uid_s]):
            if h in STICKER_DATA:
                fp = os.path.join(STICKER_ARCHIVE_DIR, f"{h}.jpg")
                if os.path.exists(fp):
                    return fp
    # 兜底QQ表情
    return str(random.choice(STICKER_FACE_IDS))

def build_reply_message(txt,uid,kws=None):
    txt=txt.replace("[sticker]","").strip()
    lines=[l.strip() for l in txt.split('\n') if l.strip()]
    dialog=lines[0] if lines else txt
    action_line=lines[1] if len(lines)>1 else ""
    if action_line and not (action_line.startswith('（') or action_line.startswith('(')):
        dialog=txt
        action_line=""
    kw=kws or extract_keywords(txt)
    msg=[]
    if dialog: msg.append({"type":"text","data":{"text":dialog}})
    if action_line: msg.append({"type":"text","data":{"text":action_line}})
    if action_line:
        # 用新系统选图
        fp = get_best_image(kw, uid) if kw else select_best_sticker(uid, txt)
        if fp:
            with open(fp, "rb") as f:
                b64 = encode_image_base64(f.read())
            msg.append({"type":"image","data":{"file":b64}})
    elif not action_line:
        s=select_best_sticker(uid,txt+" "+" ".join(kw))
        if isinstance(s,str): msg.append({"type":"face","data":{"id":s}})
        elif s:
            with open(s, "rb") as f:
                b64 = encode_image_base64(f.read())
            msg.append({"type":"image","data":{"file":b64}})
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

# ===================== 14c. 对话命令系统 =====================
# 主人通过私聊发命令查看/修改运行时参数
CMD_PREFIX = "!"

def build_cmd_help():
    return (
        "📋 可用命令（私聊发送，仅主人有效）：\n"
        "!help        - 显示本帮助\n"
        "!status      - 查看运行状态概览\n"
        "!status all  - 查看所有详细参数\n"
        "!task        - 查看定时任务列表与下次触发时间\n"
        "!memory      - 查看对话记忆统计\n"
        "!sticker     - 查看表情包存档统计\n"
        "!clip        - 查看CLIP状态\n"
        "!keywords    - 查看全局关键词\n"
        "!apikeys     - 查看API密钥状态（隐藏完整值）\n"
        "!reload      - 重新加载API密钥和记忆\n"
        "!set <键> <值> - 修改配置（仅支持部分参数）\n"
        "              支持: master_qq, heartbeat, maxtokens, temperature\n"
    )

def format_status_detailed():
    lines = []
    lines.append(f"🤖 主人QQ: {MASTER_QQ}")
    lines.append(f"🔌 WebSocket: {LISTEN_HOST}:{LISTEN_PORT_QQ}")
    lines.append(f"❤️ 心跳间隔: {HEARTBEAT_INTERVAL}s")
    lines.append(f"📦 消息去重缓存: {len(PROCESSED_MSG_IDS)}/80")
    lines.append("")
    lines.append(f"🧠 DeepSeek: {'✅' if DS_API_KEY else '❌'} {DS_MODEL}")
    lines.append(f"🫘 豆包: {'✅' if DOUBAO_API_KEY else '❌'}")
    lines.append(f"🖼️ CLIP: {'✅' if CLIP_ENABLED else '❌'}")
    lines.append(f"📅 chinesecalendar: {'✅ 已加载' if CHINESE_CALENDAR_OK else '⚠️ 未安装(降级weekday)'}")
    lines.append(f"🔑 搜图Token: {'✅ 已配置' if SEARCH_STICKER_KEY else '❌ 缺失'}")
    lines.append("")
    lines.append(f"🗂️ 对话对象数: {len(user_memory_pool)}")
    lines.append(f"🏷️ 全局关键词数: {len(global_keyword_set)}")
    lines.append(f"🖼️ 表情包存档: {len(STICKER_DATA)} 张")
    lines.append(f"👤 本日已触发定时: {len(daily_trigger)} 个")
    lines.append(f"💬 今日闲聊次数: {len(triggered_today)}/{len(daily_chat_trigger_times) if daily_chat_trigger_times else '?'}")
    wd = "工作日" if is_workday_today() else ("周末" if date.today().weekday() >= 5 else "法定节假日")
    lines.append(f"📆 今天: {date.today().strftime('%Y-%m-%d')} {['周一','周二','周三','周四','周五','周六','周日'][date.today().weekday()]}({wd})")
    return "\n".join(lines)

def format_task_list():
    lines = ["⏰ 定时任务列表："]
    today_key = date.today().isoformat()
    for task in SCHEDULE_TASKS:
        sc = task["scene"]
        key = f"{sc}_{today_key}"
        tm = task_trigger_minute.get(key, -1)
        tm_str = f"{tm//60:02d}:{tm%60:02d}" if tm >= 0 else "待计算"
        trig = "✅" if key in daily_trigger else "⏳"
        if sc == "催起床":
            wd_info = "工作日7:30 / 假日8:30"
        else:
            wd_info = f"{task['t'].strftime('%H:%M') if 't' in task else '动态'}"
        lines.append(f"  {trig} {sc} ({wd_info}) → {tm_str}")
    lines.append("")
    lines.append(f"💬 今日闲聊时间点: {', '.join(f'{t//60:02d}:{t%60:02d}' for t in daily_chat_trigger_times) if daily_chat_trigger_times else '待计算'}")
    return "\n".join(lines)

def format_memory_stats():
    lines = [f"🧠 对话记忆统计："]
    lines.append(f"  总对象数: {len(user_memory_pool)}")
    for tid, deq in list(user_memory_pool.items())[:10]:
        kw = extract_keywords(deq[-1][1] if deq else "")
        lines.append(f"  [{tid}] {len(deq)}条 | 最近: {deq[-1][0][:20] if deq else '无'}...")
    if len(user_memory_pool) > 10:
        lines.append(f"  ... 还有 {len(user_memory_pool)-10} 个对象")
    return "\n".join(lines)

def format_sticker_stats():
    lines = [f"🖼️ 表情包存档统计："]
    lines.append(f"  图片总数: {len(STICKER_DATA)} 张")
    lines.append(f"  存档目录: {STICKER_ARCHIVE_DIR}/")
    uid_count = len(set().union(*[info["users"] for info in STICKER_DATA.values()])) if STICKER_DATA else 0
    lines.append(f"  贡献用户: {uid_count} 人")
    if STICKER_DATA:
        top = sorted(STICKER_DATA.keys(), key=lambda h: STICKER_DATA[h]["use_count"], reverse=True)[:3]
        lines.append(f"  热门标签: tags统计略")
    return "\n".join(lines)

def format_clip_status():
    if CLIP_ENABLED:
        return f"🖼️ CLIP状态: ✅ 已加载 (ViT-B/32, CPU)\n  候选标签数: {len(CLIP_IMAGE_TAGS)}"
    else:
        return "🖼️ CLIP状态: ❌ 未加载（未安装torch/CLIP或加载失败）"

def format_keywords():
    if not global_keyword_set:
        return "🏷️ 全局关键词: 无"
    kws = sorted(global_keyword_set)
    return f"🏷️ 全局关键词 ({len(kws)}):\n  {'、'.join(kws[:40])}"

def format_apikeys():
    return (
        f"🔑 API密钥状态：\n"
        f"  DS_API_KEY: {'✅ 已配置' if DS_API_KEY else '❌ 缺失'}\n"
        f"  DOUBAO_API_KEY: {'✅ 已配置' if DOUBAO_API_KEY else '❌ 缺失'}\n"
        f"  STICKER_API_KEY: {'✅ 已配置' if SEARCH_STICKER_KEY else '❌ 缺失'}"
    )

async def handle_command(text, uid, ws, is_group, gid):
    """处理对话命令，返回True表示已处理（不再走AI回复）"""
    if not text.startswith(CMD_PREFIX):
        return False
    # 只有主人才能用命令
    if str(uid) != str(MASTER_QQ):
        return False

    cmd = text[1:].strip()
    parts = cmd.split()
    cmd_name = parts[0].lower() if parts else ""

    reply = ""

    if cmd_name == "help":
        reply = build_cmd_help()

    elif cmd_name == "status":
        if "all" in parts:
            reply = format_status_detailed()
        else:
            lines = []
            lines.append(f"🤖 状态概览：")
            lines.append(f"  DS: {'✅' if DS_API_KEY else '❌'} | 豆包: {'✅' if DOUBAO_API_KEY else '❌'} | CLIP: {'✅' if CLIP_ENABLED else '❌'}")
            lines.append(f"  📅 {'工作日' if is_workday_today() else '休息日'} | 对话对象: {len(user_memory_pool)} | 关键词: {len(global_keyword_set)}")
            lines.append(f"  🖼️ 存档: {len(STICKER_DATA)}张 | 定时触发: {len(daily_trigger)}个")
            lines.append(f"  💬 闲聊: {len(triggered_today)}/合")
            lines.append(f"  使用 !status all 查看详细")
            reply = "\n".join(lines)

    elif cmd_name == "task":
        reply = format_task_list()

    elif cmd_name == "memory":
        reply = format_memory_stats()

    elif cmd_name == "sticker":
        reply = format_sticker_stats()

    elif cmd_name == "clip":
        reply = format_clip_status()

    elif cmd_name == "keywords":
        reply = format_keywords()

    elif cmd_name == "apikeys":
        reply = format_apikeys()

    elif cmd_name == "reload":
        try:
            reload_api_keys()
            load_memories()
            reply = "♻️ 已重新加载API密钥和记忆数据"
        except Exception as e:
            reply = f"❌ 重载失败: {e}"

    elif cmd_name == "set":
        if len(parts) < 3:
            reply = "用法: !set <键> <值>\n支持: master_qq, heartbeat, maxtokens, temperature"
        else:
            key = parts[1].lower()
            val = " ".join(parts[2:])
            try:
                if key == "master_qq":
                    globals()["MASTER_QQ"] = int(val)
                    reply = f"✅ 主人QQ已设为 {MASTER_QQ}"
                elif key == "heartbeat":
                    globals()["HEARTBEAT_INTERVAL"] = int(val)
                    reply = f"✅ 心跳间隔已设为 {HEARTBEAT_INTERVAL}s"
                elif key == "maxtokens":
                    # 修改全局变量需小心，这里只是示例
                    reply = f"❌ max_tokens 当前为代码内固定值，不建议运行时修改"
                elif key == "temperature":
                    reply = f"❌ temperature 当前为代码内固定值 0.7，不建议运行时修改"
                else:
                    reply = f"❌ 不支持的配置项: {key}"
            except Exception as e:
                reply = f"❌ 设置失败: {e}"

    else:
        reply = f"❌ 未知命令: {cmd_name}\n输入 !help 查看可用命令"

    # 发送回复
    if reply:
        msg = [{"type": "text", "data": {"text": reply}}]
        if is_group:
            await send_group_msg(gid, msg, ws)
        else:
            await send_private_msg(uid, msg, ws)
        log_send(f"[命令回复] {reply[:50]}...")
    return True

# ===================== 14d-1. 工作日/节假日判断 =====================
def is_workday_today():
    """判断今天是否是法定工作日，使用 chinesecalendar 库"""
    if CHINESE_CALENDAR_OK:
        try:
            return _is_workday(date.today())
        except:
            pass
    # 备用：降级到简单 weekday 判断（周一到周五算工作日）
    return date.today().weekday() < 5

# ===================== 15. 定时任务 =====================
# "催起床"只有一条，每天动态判断是否是工作日来决定 7:30 还是 8:30 叫。
# 其他任务固定 weekday=全部，每天触发一次（均由 daily_trigger 防重复）。
SCHEDULE_TASKS=[
    {"scene":"催起床","weekday":[0,1,2,3,4,5,6]},
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
                    if task["scene"] == "催起床":
                        # 动态判断：工作日 7:30，周末/节假日 8:30
                        base_h, base_m = (7, 30) if is_workday_today() else (8, 30)
                        base = base_h * 60 + base_m
                    else:
                        base=task["t"].hour*60+task["t"].minute
                    task_trigger_minute[f"{task['scene']}_{today}"]=max(0,min(1439,base+random.randint(-10,10)))
            cur=now.hour*60+now.minute
            for task in SCHEDULE_TASKS:
                key=f"{task['scene']}_{today}"
                if key in daily_trigger: continue
                if now.weekday() not in task["weekday"]: continue
                tm=task_trigger_minute.get(key)
                if tm is None or cur!=tm: continue
                # ★ 修复：先标记任务已触发，防止异常导致重复触发
                daily_trigger.add(key)
                log_system(f"定时:{task['scene']}")
                # 催起床特殊处理：发文字 + ACG 图片
                try:
                    if task["scene"] == "催起床":
                        rep = await get_character_reply("催起床", str(MASTER_QQ))
                        await send_short_reply(MASTER_QQ, rep, active_ws_qq, MASTER_QQ)
                        # 异步获取 ACG 图片并发送
                        img_fp = await asyncio.to_thread(fetch_and_save_acg_image)
                        if img_fp and active_ws_qq and not getattr(active_ws_qq, "closed", False):
                            with open(img_fp, "rb") as f:
                                b64 = encode_image_base64(f.read())
                            await send_private_msg(MASTER_QQ, [{"type":"image","data":{"file":b64}}], active_ws_qq)
                            log_system("ACG起床图已发送")
                    else:
                        rep = await get_character_reply(task["scene"], str(MASTER_QQ))
                        await send_short_reply(MASTER_QQ, rep, active_ws_qq, MASTER_QQ)
                except Exception as task_e:
                    log_err(f"定时任务执行异常({task['scene']}):{task_e}")
            if cur in daily_chat_trigger_times and cur not in triggered_today:
                # ★ 修复：先标记已触发，防止异常导致重复触发
                triggered_today.add(cur)
                try:
                    rep=await get_character_reply("闲聊",str(MASTER_QQ))
                    await send_short_reply(MASTER_QQ,rep,active_ws_qq,MASTER_QQ)
                    log_system("闲聊触发")
                except Exception as chat_e:
                    log_err(f"主动闲聊执行异常:{chat_e}")
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
    # 上线发文字 + ACG图片 检验连通性
    await send_short_reply(MASTER_QQ,"哼,上线了(叉腰)",ws,MASTER_QQ)
    img_fp = await asyncio.to_thread(fetch_and_save_acg_image)
    if img_fp and not getattr(ws, "closed", False):
        with open(img_fp, "rb") as f:
            b64 = encode_image_base64(f.read())
        await send_private_msg(MASTER_QQ, [{"type":"image","data":{"file":b64}}], ws)
        log_system("上线ACG图片已发送")
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
                # 先检查是否是命令（仅主人有效）
                if await handle_command(text, uid, ws, mt=="group", gid):
                    pass  # 命令已处理，不再走AI回复
                elif contains_sticker_key(text):
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

# ===================== 18. 主程序 =====================
async def main():
    global PROCESS_LOCK
    load_memories(); init_sticker_archive(); init_clip_model(); reload_api_keys(); load_personality_supplement()
    # 确保 ACG 图片表存在
    try:
        c = get_cursor()
        c.execute("""
            CREATE TABLE IF NOT EXISTS acg_images (
                id INT AUTO_INCREMENT PRIMARY KEY,
                md5_hash VARCHAR(32) NOT NULL UNIQUE,
                image_data MEDIUMBLOB,
                tags VARCHAR(255) DEFAULT '',
                source_url VARCHAR(512) DEFAULT '',
                file_path VARCHAR(255) DEFAULT '',
                use_count INT DEFAULT 0,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """)
        c.connection.commit()
        log_system("acg_images 表已就绪")
    except Exception as e:
        log_err(f"建表失败: {e}")
    PROCESS_LOCK=asyncio.Lock()
    log_system("初始化完成(CLIP识图版)")
    while True:
        hb=asyncio.create_task(heartbeat_monitor("QQ",active_ws_qq))
        cyc=asyncio.create_task(cycle_task_run())
        try:
            async with websockets.serve(websocket_handle_qq,LISTEN_HOST,LISTEN_PORT_QQ):
                await asyncio.Future()
        except Exception as e:
            log_err(f"重启:{e}")
        finally:
            hb.cancel(); cyc.cancel()
            await asyncio.sleep(5)

if __name__=="__main__": asyncio.run(main())