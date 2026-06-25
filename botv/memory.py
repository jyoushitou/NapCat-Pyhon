# 对话记忆与关键词
import jieba
from collections import deque
from .config import MAX_USER_ROUND
from .db import load_user_memories_from_db, load_global_keywords_from_db, add_user_memory_to_db, add_global_keywords_to_db, load_events_from_db, add_event_to_db
from .log import log_system
import botv.config as cfg

def extract_keywords(text):
    sw={"的","了","是","我","你","在","有","就","不","都","吗","吧","啊","哦","呀","呢","呗","啦"}
    return [w for w in jieba.lcut(text) if len(w)>1 and w not in sw]

def load_memories():
    cfg.user_memory_pool = load_user_memories_from_db()
    cfg.global_keyword_set = load_global_keywords_from_db()
    log_system(f"记忆: {len(cfg.user_memory_pool)}对象,{len(cfg.global_keyword_set)}关键词")

def add_target_memory(tid,user_msg,bot_msg,img_keywords=None,refined_keywords=None,event_summary=None):
    add_user_memory_to_db(tid,user_msg,bot_msg)
    cfg.user_memory_pool.setdefault(tid,deque(maxlen=MAX_USER_ROUND)).append([user_msg,bot_msg])
    # 存储事件（带标签）
    if event_summary:
        tag_str = ",".join(refined_keywords[:5]) if refined_keywords else ""
        add_event_to_db(tid, event_summary, tag_str)
    # AI提炼的关键词合并到长期记忆
    if refined_keywords:
        add_global_keywords_to_db(refined_keywords)
        for k in refined_keywords: cfg.global_keyword_set.add(k)
    else:
        # 降级：jieba分词提取
        nk=extract_keywords(f"{user_msg} {bot_msg}")
        if img_keywords:
            nk.extend(img_keywords)
        add_global_keywords_to_db(nk)
        for k in nk: cfg.global_keyword_set.add(k)

def build_memory_context(tid, current_kws=None):
    kw="、".join(cfg.global_keyword_set) if cfg.global_keyword_set else "无"
    dia=""
    if tid in cfg.user_memory_pool:
        for u,b in list(cfg.user_memory_pool[tid])[-6:]: dia+=f"用户:{u}\n奈绪:{b}\n"
    else: dia="无"
    # 按当前对话关键词过滤事件，只传匹配的
    events=load_events_from_db(tid, tag_keywords=current_kws, limit=3)
    events_str="\n".join(f"· {e[0]}" for e in events) if events else "无"
    return kw, dia, events_str

