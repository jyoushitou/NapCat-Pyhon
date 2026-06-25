# ===================== QQ消息处理主循环 =====================
# 接收QQ消息→解析内容→命令/表情包/AI回复→发送回复

import asyncio  # 异步IO
import json  # JSON解析
import os  # 文件路径操作

from .config import MASTER_QQ, LOCK_RELEASE_DELAY  # 主人QQ、锁释放延迟
import botv.config as cfg  # 全局运行时变量
from .log import log_recv, log_send, log_err, log_system, log_api  # 日志
from .image import process_and_save_image, fetch_and_save_acg_image  # 图片处理
from .memory import extract_keywords, add_target_memory  # 记忆管理
from .api import get_character_reply  # AI回复
from .send import send_short_reply, send_private_msg, send_sticker_private, send_sticker_group, select_best_sticker  # 发送消息
from .commands import handle_command  # 命令处理
from .utils import download_url, encode_image_base64, make_image_msg, parse_ai_reply  # 工具函数


def contains_sticker_key(text):
    """检查文本是否包含表情包触发关键词"""
    for kw in cfg.STICKER_KEYWORDS:  # 遍历表情包关键词列表
        if kw in text:  # 文本包含该关键词
            return True  # 返回True
    return False  # 不包含任何关键词


async def parse_message_content(raw_content, user_id):
    """解析消息内容：提取文本、处理图片（下载+CLIP打标）、记录表情"""
    input_text = ""  # 最终文本
    img_info = []  # 图片信息列表
    if isinstance(raw_content, list):  # 消息是数组格式（包含多种类型）
        for item in raw_content:  # 遍历消息片段
            t = item.get("type")  # 消息类型
            d = item.get("data", {})  # 消息数据
            if t == "text":  # 文本类型
                input_text += d.get("text", "")  # 追加文本
            elif t == "image":  # 图片类型
                url = d.get("url") or d.get("file")  # 获取图片URL
                log_api(f"[消息解析] 收到图片: {url[:60]}")  # 日志记录
                img_data = download_url(url)  # 下载图片
                if img_data:  # 下载成功
                    md5, tags_str, fp = await process_and_save_image(img_data, url, user_id)  # CLIP打标+保存
                    log_api(f"[消息解析] 图片处理结果: md5={md5}, tags={tags_str}, fp={fp}")  # 日志记录
                    if tags_str:  # 有标签
                        tag_list = tags_str.split(",")  # 分割标签
                        img_info.append(f"[{tag_list[0]}]")  # 添加第一个标签作为图片标识
                        input_text += " " + " ".join(tag_list[:5])  # 将前5个标签追加到文本
                else:  # 下载失败
                    img_info.append("[图]")  # 添加通用图片标识
                    log_api(f"[消息解析] 图片下载失败: {url[:60]}")  # 日志记录
            elif t == "face":  # QQ表情类型
                fid = str(d.get("id"))  # 获取表情ID
                if fid:  # 表情ID有效
                    cfg.USER_STICKER_CACHE[user_id].append(fid)  # 缓存用户最近使用的表情
                    if len(cfg.USER_STICKER_CACHE[user_id]) > 20:  # 缓存超过20个
                        cfg.USER_STICKER_CACHE[user_id].pop(0)  # 移除最旧的
                img_info.append(f"[表情{fid}]")  # 添加表情标识
    else:  # 消息是纯文本
        input_text = str(raw_content).strip()  # 直接转为字符串
    if img_info:  # 有图片/表情信息
        input_text = f"{input_text} {' '.join(img_info)}"  # 追加到文本末尾
    log_api(f"[消息解析] 最终文本: {input_text[:60]}")  # 日志记录
    return input_text.strip()  # 返回处理后的文本


async def websocket_handle_qq(ws):
    """WebSocket消息处理主函数：接收→解析→处理→回复"""
    async with cfg.active_ws_lock:  # 加锁，确保只有一个WebSocket连接
        if cfg.active_ws_qq and not getattr(cfg.active_ws_qq,"closed",False):  # 已有活跃连接
            await ws.close()  # 关闭新连接
            return  # 返回
        cfg.active_ws_qq = ws  # 设置当前活跃连接
    log_system("QQ上线(CLIP版)")  # 日志记录上线
    
    # 上线发文字 + ACG图片 检验连通性
    await send_short_reply(MASTER_QQ, "哼,上线了(叉腰)", ws, MASTER_QQ)  # 发送上线通知
    
    img_fp = await fetch_and_save_acg_image()  # 获取ACG图片
    if img_fp:
        img_fp = os.path.abspath(img_fp)  # 转为绝对路径
        log_api(f"[上线] ACG图片绝对路径: {img_fp}")  # 日志记录
        img_msg = make_image_msg(img_fp)  # 构建图片消息
        if img_msg and not getattr(ws, "closed", False):  # 图片有效且连接未关闭
            await send_private_msg(MASTER_QQ, img_msg, ws)  # 发送图片给主人
            log_system("上线ACG图片已发送")  # 日志记录
    else:
        log_api("[上线] ACG图片获取失败")  # 日志记录
    
    try:
        while True:  # 消息接收循环
            raw = await ws.recv()  # 接收原始消息
            rs = raw.decode("utf-8","ignore") if isinstance(raw,bytes) else raw  # 解码字节为字符串
            d = json.loads(rs)  # 解析JSON
            mt = d.get("message_type")  # 消息类型：private/group
            mid = d.get("message_id")  # 消息ID
            if not mid or mid in cfg.PROCESSED_MSG_IDS:  # 消息ID无效或已处理
                continue  # 跳过
            uid = str(d.get("user_id"))  # 用户QQ号
            gid = d.get("group_id", 0)  # 群号（私聊为0）
            text = await parse_message_content(d.get("message",""), uid)  # 解析消息内容
            if not text:  # 解析后文本为空
                continue  # 跳过
            
            async with cfg.PROCESS_LOCK:  # 加消息处理锁
                cfg.PROCESSED_MSG_IDS.append(mid)  # 记录已处理的消息ID
                log_recv(f"[QQ]{uid}:{text}")  # 日志记录接收
                tid = uid if mt=="private" else str(gid)  # 目标ID：私聊用QQ号，群聊用群号
                ck = extract_keywords(text)  # 提取关键词
                
                # 先检查是否是命令（仅主人有效）
                if await handle_command(text, uid, ws, mt=="group", gid):  # 是命令
                    pass  # 命令已处理，不再走AI回复
                elif contains_sticker_key(text):  # 包含表情包关键词
                    if mt=="group":  # 群聊
                        await send_sticker_group(gid, ws, uid)  # 发送群表情包
                    else:  # 私聊
                        await send_sticker_private(uid, ws, uid)  # 发送私聊表情包
                else:  # 普通对话
                    ans = await get_character_reply(text, tid, ck)  # 获取AI回复
                    dialog, action, img_kw, event, refined_kw = parse_ai_reply(ans)  # 解析AI回复
                    add_target_memory(tid, text, ans, img_kw, refined_kw, event)  # 保存记忆
                    await send_short_reply(gid if mt=="group" else uid, ans, ws, uid, mt=="group", ck)  # 发送回复
                
                await asyncio.sleep(LOCK_RELEASE_DELAY)  # 锁释放延迟，防止消息处理过快
    except Exception as e:  # 捕获异常
        log_err(f"QQ异常:{e}")  # 日志记录异常
    finally:  # 清理
        async with cfg.active_ws_lock:  # 加锁
            if cfg.active_ws_qq is ws:  # 当前连接就是本连接
                cfg.active_ws_qq = None  # 清空活跃连接
        cfg.PROCESSED_MSG_IDS.clear()  # 清空已处理消息ID列表
        log_system("QQ断开")  # 日志记录断开
