# 对话记忆与关键词
import jieba
from collections import deque
from .config import MAX_USER_ROUND, user_memory_pool, global_keyword_set
from .db import load_user_memories_from_db, load_global_keywords_from_db, add_user_memory_to_db, add_global_keywords_to_db
from .log import log_system

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

