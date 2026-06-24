# 数据库连接与操作
import threading, pymysql
from collections import deque
from datetime import datetime
from .config import DB_CONFIG, CST, DS_API_KEY, DOUBAO_API_KEY, SEARCH_STICKER_KEY, STICKER_API_ALAPI_TOKEN
from .log import log_system, log_err

DB_CONFIG = {"host":"192.168.0.50","port":3306,"user":"TomoriNaoBot",
             "password":"TNB","database":"TomoriNaoBotData","charset":"utf8mb4"}
_local = threading.local()
def get_db():
    if not hasattr(_local,"conn") or _local.conn is None:
        _local.conn = pymysql.connect(**DB_CONFIG,cursorclass=pymysql.cursors.DictCursor)
    return _local.conn
def get_cursor(): return get_db().cursor()

# ===================== 数据库操作 =====================
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
    global DS_API_KEY,DOUBAO_API_KEY,SEARCH_STICKER_KEY,STICKER_API_ALAPI_TOKEN
    DS_API_KEY=get_api_key_from_db("DS_API_KEY")
    DOUBAO_API_KEY=get_api_key_from_db("ARK_API_KEY")
    SEARCH_STICKER_KEY=get_api_key_from_db("STICKER_API_KEY")
    STICKER_API_ALAPI_TOKEN=get_api_key_from_db("ALAPI_TOKEN")
    log_system(f"API: DS={bool(DS_API_KEY)},豆包={bool(DOUBAO_API_KEY)},搜图={bool(SEARCH_STICKER_KEY)},ALAPI={bool(STICKER_API_ALAPI_TOKEN)}")

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
