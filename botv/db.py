# ===================== 数据库模块 =====================
# MySQL数据库连接与操作：日志、API密钥、对话记忆、关键词、事件、图片、AI原始数据

import threading, json, pymysql  # 线程本地存储、JSON、MySQL驱动
from collections import deque  # 双端队列（用于对话记忆池）
from datetime import datetime  # 时间戳
from .config import DB_CONFIG, CST, MAX_USER_ROUND, MAX_GLOBAL_KEY  # 配置常量
from .log import log_system, log_err  # 日志
import botv.config as cfg  # 全局运行时变量

_local = threading.local()  # 线程本地存储（每个线程独立数据库连接）

def get_db():
    """获取当前线程的数据库连接（懒加载）"""
    if not hasattr(_local,"conn") or _local.conn is None:
        _local.conn = pymysql.connect(**DB_CONFIG,cursorclass=pymysql.cursors.DictCursor)  # 创建连接，返回字典游标
    return _local.conn

def get_cursor():
    """获取数据库游标"""
    return get_db().cursor()

# ===================== 数据库操作 =====================
def write_log_to_db(level,msg):
    """写入日志到数据库logs表"""
    try:
        c=get_cursor()
        c.execute("INSERT INTO logs(level,message,created_at)VALUES(%s,%s,%s)",
                  (level,msg,datetime.now(CST).strftime('%Y-%m-%d %H:%M:%S')))
        c.connection.commit()
    except: pass  # 日志写入失败不影响主流程

def get_api_key_from_db(name):
    """从数据库api_keys表获取指定密钥"""
    c=get_cursor()
    c.execute("SELECT key_value FROM api_keys WHERE key_name=%s",(name,))
    r=c.fetchone()
    return r["key_value"] if r else ""

def reload_api_keys():
    """重新加载所有API密钥到全局变量"""
    cfg.DS_API_KEY = get_api_key_from_db("DS_API_KEY")  # DeepSeek密钥
    cfg.DOUBAO_API_KEY = get_api_key_from_db("ARK_API_KEY")  # 豆包密钥
    cfg.STICKER_API_ALAPI_TOKEN = get_api_key_from_db("ALAPI_TOKEN")  # ALAPI搜图密钥
    log_system(f"API: DS={bool(cfg.DS_API_KEY)},豆包={bool(cfg.DOUBAO_API_KEY)},ALAPI={bool(cfg.STICKER_API_ALAPI_TOKEN)}")

def load_user_memories_from_db():
    """从数据库加载所有用户的对话记忆"""
    c=get_cursor()
    c.execute("SELECT target_id,user_msg,bot_msg FROM user_memory ORDER BY target_id,id")
    pool={}
    for r in c.fetchall():
        tid=r["target_id"]
        if tid not in pool:
            pool[tid]=deque(maxlen=MAX_USER_ROUND)  # 每个用户最多保留MAX_USER_ROUND轮对话
        pool[tid].append([r["user_msg"],r["bot_msg"]])
    return pool

def add_user_memory_to_db(tid,user_msg,bot_msg):
    """添加一条对话记忆到数据库，并清理超出轮数的旧记录"""
    c=get_cursor()
    c.execute("INSERT INTO user_memory(target_id,user_msg,bot_msg)VALUES(%s,%s,%s)",(tid,user_msg,bot_msg))
    # 删除超出MAX_USER_ROUND的旧记录
    c.execute("DELETE FROM user_memory WHERE id NOT IN(SELECT id FROM(SELECT id FROM user_memory WHERE target_id=%s ORDER BY id DESC LIMIT %s)AS tmp)AND target_id=%s",(tid,MAX_USER_ROUND,tid))
    c.connection.commit()

def load_global_keywords_from_db():
    """从数据库加载全局关键词集合"""
    c=get_cursor()
    c.execute("SELECT keyword FROM global_keywords ORDER BY id")
    return set(r["keyword"] for r in c.fetchall())

def add_global_keywords_to_db(kws):
    """添加关键词到全局关键词表，超出MAX_GLOBAL_KEY时删除最旧的"""
    c=get_cursor()
    for kw in kws:
        c.execute("INSERT IGNORE INTO global_keywords(keyword)VALUES(%s)",(kw,))  # 忽略重复
    c.execute("SELECT COUNT(*)as cnt FROM global_keywords")
    if c.fetchone()["cnt"]>MAX_GLOBAL_KEY:
        # 只保留最新的MAX_GLOBAL_KEY个
        c.execute("DELETE FROM global_keywords WHERE id NOT IN(SELECT id FROM(SELECT id FROM global_keywords ORDER BY id DESC LIMIT %s)AS tmp)",(MAX_GLOBAL_KEY,))
    c.connection.commit()

# ===================== 事件记忆（拟人化） =====================
def load_events_from_db(tid, tag_keywords=None, limit=5):
    """加载事件记忆，可按标签关键词过滤（最多3个标签）"""
    c=get_cursor()
    if tag_keywords:
        conds = " OR ".join(["tags LIKE %s" for _ in tag_keywords[:3]])  # 动态构建LIKE条件
        params = [f"%{kw}%" for kw in tag_keywords[:3]]
        sql = f"SELECT event_summary, tags FROM events WHERE target_id=%s AND ({conds}) ORDER BY id DESC LIMIT %s"
        c.execute(sql, [tid] + params + [limit])
    else:
        c.execute("SELECT event_summary, tags FROM events WHERE target_id=%s ORDER BY id DESC LIMIT %s", (tid, limit))
    return [(r["event_summary"], r["tags"]) for r in c.fetchall()]

def add_event_to_db(tid, event_summary, tags=""):
    """添加事件记忆，每个对象最多保留20条"""
    if not event_summary: return
    c=get_cursor()
    c.execute("INSERT INTO events(target_id, event_summary, tags) VALUES(%s,%s,%s)", (tid, event_summary, tags))
    # 每个对象最多保留 20 条事件
    c.execute("DELETE FROM events WHERE id NOT IN(SELECT id FROM(SELECT id FROM events WHERE target_id=%s ORDER BY id DESC LIMIT 20)AS tmp)AND target_id=%s", (tid, tid))
    c.connection.commit()

# ===================== AI 原始返回数据保存 =====================
def save_ai_raw_response(model_name, user_msg, raw_response_json, response_text, target_id, status="success"):
    """保存AI的原始完整返回数据到 ai_raw_responses 表（用于调试和分析）"""
    try:
        c = get_cursor()
        c.execute("""
            INSERT INTO ai_raw_responses 
            (model_name, user_msg, raw_response_json, response_text, target_id, status, created_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
        """, (
            model_name,  # 模型名称
            user_msg[:500],  # 用户消息（截断）
            json.dumps(raw_response_json, ensure_ascii=False),  # 完整JSON
            response_text[:1000] if response_text else '',  # 提取的文本
            target_id,  # 对话目标ID
            status,  # 状态
            datetime.now(CST).strftime('%Y-%m-%d %H:%M:%S')  # 创建时间
        ))
        c.connection.commit()
    except Exception as e:
        log_err(f"保存AI原始数据失败: {e}")
