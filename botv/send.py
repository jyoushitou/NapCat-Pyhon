# 消息发送：构建 reply message + 选图 + WS 发送
import asyncio, json, random, os
from .config import STICKER_FACE_IDS, STICKER_ARCHIVE_DIR, STICKER_DATA, USER_STICKER_ARCHIVE
from .log import log_send, log_err, log_system
from .image import search_local_image_by_tags, get_best_image
from .memory import extract_keywords
from .utils import encode_image_base64

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
