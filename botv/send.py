# 消息发送：构建 reply message + 选图 + WS 发送
import asyncio, json, random, os
from .config import STICKER_FACE_IDS, STICKER_ARCHIVE_DIR
import botv.config as cfg
from .log import log_send, log_err, log_system, log_api
from .image import search_local_image_by_tags, get_best_image
from .memory import extract_keywords
from .utils import encode_image_base64, make_image_msg, parse_ai_reply
from .db import get_cursor


def select_best_sticker(uid,ctx=""):
    """旧接口兼容，优先查新库，其次旧存档，最后QQ表情"""
    kws = extract_keywords(ctx)
    log_api(f"[选图] uid={uid}, ctx_kws={kws}")
    # 新库查
    results = search_local_image_by_tags(kws, limit=3)
    if results:
        log_api(f"[选图] 新库命中: {results[0][2]}")
        try:
            c = get_cursor()
            c.execute("UPDATE images SET use_count=use_count+1 WHERE md5_hash=%s", (results[0][0],))
            c.connection.commit()
        except:
            pass
        return results[0][2]  # 返回文件路径
    # 旧存档查
    uid_s = str(uid)
    if uid_s in cfg.USER_STICKER_ARCHIVE and cfg.USER_STICKER_ARCHIVE[uid_s]:
        for h in reversed(cfg.USER_STICKER_ARCHIVE[uid_s]):
            if h in cfg.STICKER_DATA:
                fp = os.path.join(STICKER_ARCHIVE_DIR, f"{h}.jpg")
                if os.path.exists(fp):
                    log_api(f"[选图] 旧存档命中: {fp}")
                    return fp
    # 兜底QQ表情
    face_id = str(random.choice(STICKER_FACE_IDS))
    log_api(f"[选图] 兜底QQ表情: {face_id}")
    return face_id

async def build_reply_message(txt,uid,kws=None):
    """返回 [(消息类型, 内容), ...] 列表，每条独立发送"""
    dialog, action, img_kw, event, refined_kw = parse_ai_reply(txt)
    log_api(f"[构建回复] dialog={dialog[:30]}, action={action[:20]}, img_kw={img_kw}")
    parts = []
    if dialog:
        parts.append(("text", [{"type":"text","data":{"text":dialog}}]))
    if action:
        parts.append(("text", [{"type":"text","data":{"text":action}}]))
            # 用第三行关键词选图，如果没有则用jieba从对话+动作中提取
        if img_kw:
            log_api(f"[构建回复] 按AI关键词搜图(20纬度): {img_kw}")
        fp = await get_best_image(img_kw, uid)
        if fp:
            abs_fp = os.path.abspath(fp)
            log_api(f"[构建回复] 搜到图片: {abs_fp}")
            parts.append(("image", [{"type":"image","data":{"file":f"file:///{abs_fp}"}}]))
        else:
            # 20纬度都搜不到，延迟1分钟用jieba兜底
            log_api(f"[构建回复] 20纬度均未搜到图，启动1分钟延迟jieba兜底")
            asyncio.create_task(_delayed_jieba_fallback(dialog, action, uid))
    else:
        # img_kw为空，延迟1分钟用jieba兜底
        log_api(f"[构建回复] img_kw为空，启动1分钟延迟jieba兜底")
        asyncio.create_task(_delayed_jieba_fallback(dialog, action, uid))
    return parts

async def _delayed_jieba_fallback(dialog, action, uid):
    """延迟1分钟后用jieba提取关键词搜图兜底"""
    await asyncio.sleep(60)
    search_kws = extract_keywords(f"{dialog} {action}")
    log_api(f"[构建回复] jieba兜底关键词(延迟1min): {search_kws}")
    if search_kws:
        fp = await get_best_image(search_kws, uid)
        if fp:
            abs_fp = os.path.abspath(fp)
            log_api(f"[构建回复] jieba兜底搜到图片(延迟1min): {abs_fp}")
            img_msg = [{"type":"image","data":{"file":f"file:///{abs_fp}"}}]
            ws = cfg.active_ws_qq
            if ws and not getattr(ws, "closed", False):
                await send_private_msg(uid, img_msg, ws)
                log_api(f"[构建回复] 延迟兜底图片已发送给{uid}")
        else:
            log_api(f"[构建回复] jieba兜底搜图无结果(延迟1min)")

async def send_private_msg(qq,msg,ws):
    async with cfg.send_lock:
        try: await ws.send(json.dumps({"action":"send_private_msg","params":{"user_id":qq,"message":msg}},ensure_ascii=False))
        except Exception as e: log_err(f"私聊失败:{e}")

async def send_group_msg(gid,msg,ws):
    async with cfg.send_lock:
        try: await ws.send(json.dumps({"action":"send_group_msg","params":{"group_id":gid,"message":msg}},ensure_ascii=False))
        except Exception as e: log_err(f"群聊失败:{e}")

async def send_short_reply(tid,text,ws,uid,is_group=False,kws=None):
    parts=await build_reply_message(text,uid,kws)
    log_api(f"[发送] 共{len(parts)}条消息: {[p[0] for p in parts]}")
    for ptype, msg in parts:
        log_api(f"[发送] 类型={ptype}, 内容预览={str(msg)[:60]}")
        if is_group: await send_group_msg(tid,msg,ws)
        else: await send_private_msg(tid,msg,ws)
        await asyncio.sleep(0.5)  # 每条间隔，避免刷屏
    log_send(f"回复:{text[:40]}")

async def send_sticker_private(qq,ws,uid):
    s=select_best_sticker(uid)
    if isinstance(s,str):
        await send_private_msg(qq,[{"type":"face","data":{"id":s}}],ws)
    else:
        img_msg = make_image_msg(s)
        if img_msg:
            await send_private_msg(qq, img_msg, ws)

async def send_sticker_group(gid,ws,uid):
    s=select_best_sticker(uid)
    if isinstance(s,str):
        await send_group_msg(gid,[{"type":"face","data":{"id":s}}],ws)
    else:
        img_msg = make_image_msg(s)
        if img_msg:
            await send_group_msg(gid, img_msg, ws)
