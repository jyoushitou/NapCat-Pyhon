# QQ 消息处理主循环
import asyncio, json
from .config import MASTER_QQ, PROCESSED_MSG_IDS, PROCESS_LOCK, LOCK_RELEASE_DELAY, USER_STICKER_CACHE, STICKER_KEYWORDS, active_ws_qq, active_ws_lock
from .log import log_recv, log_send, log_err, log_system
from .image import process_and_save_image, fetch_and_save_acg_image
from .memory import extract_keywords, add_target_memory, get_character_reply
from .send import send_short_reply, send_private_msg, send_sticker_private, send_sticker_group, select_best_sticker
from .commands import handle_command
from .utils import download_url, encode_image_base64


def contains_sticker_key(text):
    for kw in STICKER_KEYWORDS:
        if kw in text: return True
    return False


async def parse_message_content(raw_content, user_id):
    input_text=""; img_info=[]
    if isinstance(raw_content,list):
        for item in raw_content:
            t=item.get("type"); d=item.get("data",{})
            if t=="text": input_text+=d.get("text","")
            elif t=="image":
                url=d.get("url") or d.get("file")
                img_data=download_url(url)
                if img_data:
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
