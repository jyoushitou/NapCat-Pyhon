# ===================== 对话记忆与关键词模块 =====================
# 管理用户对话记忆、全局关键词、事件记忆的存储和检索

import jieba  # 中文分词库
from collections import deque  # 双端队列（用于对话记忆池）

from .config import MAX_USER_ROUND  # 每个用户最大对话轮数
from .db import load_user_memories_from_db, load_global_keywords_from_db, add_user_memory_to_db, add_global_keywords_to_db, load_events_from_db, add_event_to_db  # 数据库操作
from .log import log_system  # 日志
import botv.config as cfg  # 全局运行时变量


def extract_keywords(text):
    """使用jieba分词从文本中提取关键词（过滤停用词和单字词）"""
    sw={"的","了","是","我","你","在","有","就","不","都","吗","吧","啊","哦","呀","呢","呗","啦"}  # 停用词集合
    return [w for w in jieba.lcut(text) if len(w)>1 and w not in sw]  # 分词后过滤：长度>1且不是停用词


def load_memories():
    """从数据库加载所有用户的对话记忆和全局关键词到内存"""
    cfg.user_memory_pool = load_user_memories_from_db()  # 加载用户对话记忆池
    cfg.global_keyword_set = load_global_keywords_from_db()  # 加载全局关键词集合
    log_system(f"记忆: {len(cfg.user_memory_pool)}对象,{len(cfg.global_keyword_set)}关键词")  # 日志统计


def add_target_memory(tid, user_msg, bot_msg, img_keywords=None, refined_keywords=None, event_summary=None):
    """添加一条对话记忆：入库+内存更新+事件存储+关键词更新"""
    add_user_memory_to_db(tid, user_msg, bot_msg)  # 写入数据库
    cfg.user_memory_pool.setdefault(tid, deque(maxlen=MAX_USER_ROUND)).append([user_msg, bot_msg])  # 更新内存池
    
    # 存储事件（带标签）
    if event_summary:  # 有事件摘要
        tag_str = ",".join(refined_keywords[:5]) if refined_keywords else ""  # 取前5个提炼关键词作为标签
        add_event_to_db(tid, event_summary, tag_str)  # 写入数据库
    
    # AI提炼的关键词合并到长期记忆
    if refined_keywords:  # AI提供了提炼关键词
        add_global_keywords_to_db(refined_keywords)  # 写入数据库
        for k in refined_keywords:
            cfg.global_keyword_set.add(k)  # 更新内存集合
    else:
        # 降级方案：使用jieba分词提取关键词
        nk = extract_keywords(f"{user_msg} {bot_msg}")  # 从对话中提取关键词
        if img_keywords:  # 有图片关键词
            nk.extend(img_keywords)  # 合并图片关键词
        add_global_keywords_to_db(nk)  # 写入数据库
        for k in nk:
            cfg.global_keyword_set.add(k)  # 更新内存集合


def build_memory_context(tid, current_kws=None):
    """构建对话上下文：全局关键词 + 最近对话历史 + 相关事件记忆"""
    kw = "、".join(cfg.global_keyword_set) if cfg.global_keyword_set else "无"  # 全局关键词（顿号分隔）
    
    dia = ""  # 对话历史字符串
    if tid in cfg.user_memory_pool:  # 该用户有记忆
        for u, b in list(cfg.user_memory_pool[tid])[-6:]:  # 取最近6轮对话
            dia += f"用户:{u}\n奈绪:{b}\n"  # 格式化：用户:xxx\n奈绪:xxx\n
    else:
        dia = "无"  # 无对话历史
    
    # 按当前对话关键词过滤事件，只传匹配的
    events = load_events_from_db(tid, tag_keywords=current_kws, limit=3)  # 加载相关事件（最多3条）
    events_str = "\n".join(f"· {e[0]}" for e in events) if events else "无"  # 格式化事件列表
    
    return kw, dia, events_str  # 返回(全局关键词, 对话历史, 事件记忆)

