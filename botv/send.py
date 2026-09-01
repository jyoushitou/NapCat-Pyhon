# ===================== 消息发送模块 =====================
# 构建回复消息（文本+图片）、选图策略、WebSocket发送

import asyncio  # 异步IO
import json  # JSON序列化
import random  # 随机选择
import os  # 文件路径操作

from .config import STICKER_FACE_IDS, STICKER_ARCHIVE_DIR  # QQ表情ID列表、旧存档目录
import botv.config as cfg  # 全局运行时变量
from .log import log_send, log_err, log_system, log_api  # 日志
from .image import search_local_image_by_tags, get_best_image  # 图片搜索
from .memory import extract_keywords  # 关键词提取
from .utils import encode_image_base64, make_image_msg, parse_ai_reply  # 工具函数
from .db import get_cursor  # 数据库游标


def select_best_sticker(uid, ctx=""):
    """旧接口兼容：优先查新库→其次旧存档→最后QQ表情兜底"""
    kws = extract_keywords(ctx)  # 从上下文提取关键词
    log_api(f"[选图] uid={uid}, ctx_kws={kws}")  # 日志记录
    # 新库查
    results = search_local_image_by_tags(kws, limit=3)  # 按标签搜索新库（最多3张）
    if results:  # 新库命中
        log_api(f"[选图] 新库命中: {results[0][2]}")  # 日志记录
        try:
            c = get_cursor()  # 获取数据库游标
            c.execute("UPDATE images SET use_count=use_count+1 WHERE md5_hash=%s", (results[0][0],))  # 使用次数+1
            c.connection.commit()  # 提交事务
        except:
            pass  # 更新失败不影响
        return results[0][2]  # 返回文件路径
    # 旧存档查
    uid_s = str(uid)  # 用户ID转字符串
    if uid_s in cfg.USER_STICKER_ARCHIVE and cfg.USER_STICKER_ARCHIVE[uid_s]:  # 用户有旧存档
        for h in reversed(cfg.USER_STICKER_ARCHIVE[uid_s]):  # 从最新到最旧遍历
            if h in cfg.STICKER_DATA:  # 表情包数据存在
                fp = os.path.join(STICKER_ARCHIVE_DIR, f"{h}.jpg")  # 旧存档文件路径
                if os.path.exists(fp):  # 文件存在
                    log_api(f"[选图] 旧存档命中: {fp}")  # 日志记录
                    return fp  # 返回文件路径
    # 兜底QQ表情
    face_id = str(random.choice(STICKER_FACE_IDS))  # 随机选一个QQ表情ID
    log_api(f"[选图] 兜底QQ表情: {face_id}")  # 日志记录
    return face_id  # 返回表情ID


async def build_reply_message(txt, uid, kws=None):
    """构建回复消息列表：解析AI回复→文本+动作+图片，返回[(类型, 内容), ...]
        目标：AI回复只输出角色剧情内容（第一行对话+第二行动作）→ 两条独立QQ消息（两个气泡）+ 一张表情包
        标签、摘要、关键词仅用于内部搜图处理，禁止输出到对话"""
    dialog, action, img_kw, event, refined_kw = parse_ai_reply(txt)  # 解析AI回复
    log_api(f"[构建回复] dialog={dialog[:30]}, action={action[:20]}, img_kw={img_kw}")  # 日志记录
    parts = []  # 消息片段列表

    # ★ 不依赖 dialog 拼接结果（parse_ai_reply 可能将无标记行拼入 dialog）
    # 直接从原始文本拆出每一行 → 每一行 = 一条独立QQ消息（一个气泡）
    raw_lines = [l.strip() for l in txt.split('\n') if l.strip()]  # 去除空行后的所有行

    # 剥离可能的行号前缀（"第一行：""第二行："等），AI可能错误输出这些内部标记
    import re as _re
    def _strip_line_prefix(l):
        return _re.sub(r"^[第]{0,1}[一二三四五六七八九十0-9]{1,3}[行]：[\s　]*", "", l)
    raw_lines = [_strip_line_prefix(l) for l in raw_lines]

    # 第一行：对话内容 → 独立消息（气泡1）
    if len(raw_lines) >= 1 and raw_lines[0]:
        parts.append(("text", [{"type":"text","data":{"text":raw_lines[0]}}]))  # 气泡1
        log_api(f"[构建回复] 气泡1(对话): {raw_lines[0][:30]}")

    # 第二行：动作描写 → 独立消息（气泡2）
    # 严格固定结构：对话 → 动作 → 表情包，动作消息不允许缺失。
    # 若第二行缺失或是内部元数据（AI漏写动作行），自动补（无）兜底。
    _action_line = raw_lines[1] if len(raw_lines) >= 2 else ""
    _is_internal = _action_line.startswith(("关键词", "事件", "标签", "摘要", "动作", "描述", "提炼", "回复格式"))
    if _action_line and not _is_internal:
        parts.append(("text", [{"type":"text","data":{"text":_action_line}}]))  # 气泡2
        log_api(f"[构建回复] 气泡2(动作): {_action_line[:30]}")
    else:
        # AI漏写动作行 → 兜底补（无），保证动作消息永不缺失
        parts.append(("text", [{"type":"text","data":{"text":"（无）"}}]))  # 气泡2兜底
        log_api(f"[构建回复] 气泡2(动作)缺失({_action_line[:20]})，兜底补（无）")

    # 第三行及之后：标签、摘要、关键词提炼等内部元数据 → 仅用于内部搜图，禁止输出
    # 只输出角色剧情内容（对话+动作），后跟表情包
    internal_lines = raw_lines[2:]
    if internal_lines:
        log_api(f"[构建回复] 截留{len(internal_lines)}行内部元数据(关键词/事件摘要/关键词提炼)，禁止输出")
    
    # 代码模式：只发送文字不发送图片，保证完整详细的技术回答
    if cfg.CODE_MODE:
        log_api("[构建回复] 代码模式，跳过图片发送")
        return parts
    # 用第三行关键词选图，如果没有则用jieba从对话+动作中提取
    if img_kw:  # AI提供了图片关键词
        log_api(f"[构建回复] 按AI关键词搜图(20纬度): {img_kw}")  # 日志记录
        fp = await get_best_image(img_kw, uid)  # 按关键词搜图
        if fp:  # 搜到图片
            abs_fp = os.path.abspath(fp)  # 转为绝对路径（NapCat需要绝对路径）
            log_api(f"[构建回复] 搜到图片: {abs_fp}")  # 日志记录
            parts.append(("image", [{"type":"image","data":{"file":abs_fp}}]))  # 添加图片消息
        else:  # 20纬度都搜不到，立即用jieba兜底（不等1分钟）
            log_api(f"[构建回复] 20纬度均未搜到图，立即用jieba兜底")  # 日志记录
            search_kws = extract_keywords(f"{dialog} {action}")  # 用jieba从对话+动作中提取关键词
            if search_kws:
                log_api(f"[构建回复] jieba兜底关键词: {search_kws}")  # 日志记录
                fp2 = await get_best_image(search_kws, uid)  # 按jieba关键词搜图
                if fp2:
                    abs_fp2 = os.path.abspath(fp2)
                    log_api(f"[构建回复] jieba兜底搜到图片: {abs_fp2}")
                    parts.append(("image", [{"type":"image","data":{"file":abs_fp2}}]))
                else:
                    log_api(f"[构建回复] jieba兜底搜图也无结果")
            else:
                log_api(f"[构建回复] jieba兜底无关键词")
    else:  # img_kw为空，立即用jieba兜底
        log_api(f"[构建回复] img_kw为空，立即用jieba兜底")  # 日志记录
        search_kws = extract_keywords(f"{dialog} {action}")  # 用jieba从对话+动作中提取关键词
        if search_kws:
            log_api(f"[构建回复] jieba兜底关键词: {search_kws}")  # 日志记录
            fp = await get_best_image(search_kws, uid)  # 按jieba关键词搜图
            if fp:
                abs_fp = os.path.abspath(fp)
                log_api(f"[构建回复] jieba兜底搜到图片: {abs_fp}")
                parts.append(("image", [{"type":"image","data":{"file":abs_fp}}]))
            else:
                log_api(f"[构建回复] jieba兜底搜图也无结果")
        else:
            log_api(f"[构建回复] jieba兜底无关键词")
    return parts  # 返回消息片段列表


async def _delayed_jieba_fallback(dialog, action, uid):
    """延迟1分钟后用jieba提取关键词搜图兜底（后台任务）
    注意：此函数已不再被build_reply_message调用，保留以兼容旧代码"""
    await asyncio.sleep(60)  # 等待60秒
    search_kws = extract_keywords(f"{dialog} {action}")  # 用jieba从对话+动作中提取关键词
    log_api(f"[构建回复] jieba兜底关键词(延迟1min): {search_kws}")  # 日志记录
    if search_kws:  # 提取到关键词
        fp = await get_best_image(search_kws, uid)  # 按关键词搜图
        if fp:  # 搜到图片
            abs_fp = os.path.abspath(fp)  # 转为绝对路径（NapCat需要绝对路径）
            log_api(f"[构建回复] jieba兜底搜到图片(延迟1min): {abs_fp}")  # 日志记录
            img_msg = [{"type":"image","data":{"file":abs_fp}}]  # 构建图片消息
            ws = cfg.active_ws_qq  # 获取当前WebSocket连接
            if ws and not getattr(ws, "closed", False):  # 连接有效
                try:
                    await send_private_msg(uid, img_msg, ws)  # 发送图片
                    log_api(f"[构建回复] 延迟兜底图片已发送给{uid}")
                except Exception as e:
                    log_err(f"[构建回复] 延迟兜底发送失败: {e}")  # 日志记录
        else:  # 搜图无结果
            log_api(f"[构建回复] jieba兜底搜图无结果(延迟1min)")  # 日志记录


async def send_private_msg(qq, msg, ws):
    """通过WebSocket发送私聊消息"""
    async with cfg.send_lock:  # 加发送锁，防止并发发送
        try:
            await ws.send(json.dumps({"action":"send_private_msg","params":{"user_id":qq,"message":msg}}, ensure_ascii=False))  # 发送私聊消息
        except Exception as e:
            log_err(f"私聊失败:{e}")  # 发送失败记录错误


async def send_group_msg(gid, msg, ws):
    """通过WebSocket发送群聊消息"""
    async with cfg.send_lock:  # 加发送锁
        try:
            await ws.send(json.dumps({"action":"send_group_msg","params":{"group_id":gid,"message":msg}}, ensure_ascii=False))  # 发送群聊消息
        except Exception as e:
            log_err(f"群聊失败:{e}")  # 发送失败记录错误


async def send_short_reply(tid, text, ws, uid, is_group=False, kws=None):
    """发送完整回复：构建消息→逐条发送（文本+图片）"""
    parts = await build_reply_message(text, uid, kws)  # 构建回复消息列表
    log_api(f"[发送] 共{len(parts)}条消息: {[p[0] for p in parts]}")  # 日志记录消息数量
    for ptype, msg in parts:  # 遍历每条消息
        log_api(f"[发送] 类型={ptype}, 内容预览={str(msg)[:60]}")  # 日志记录
        if is_group:  # 群聊
            await send_group_msg(tid, msg, ws)  # 发送群消息
        else:  # 私聊
            await send_private_msg(tid, msg, ws)  # 发送私聊消息
        await asyncio.sleep(2.0)  # 每条间隔2秒，确保QQ识别为独立消息，一条一条发
    log_send(f"回复:{text[:40]}")  # 日志记录发送


async def send_sticker_private(qq, ws, uid):
    """发送私聊表情包"""
    s = select_best_sticker(uid)  # 选择最佳表情包
    if isinstance(s, str):  # 返回的是QQ表情ID（字符串）
        await send_private_msg(qq, [{"type":"face","data":{"id":s}}], ws)  # 发送QQ表情
    else:  # 返回的是文件路径
        img_msg = make_image_msg(s)  # 构建图片消息
        if img_msg:  # 构建成功
            await send_private_msg(qq, img_msg, ws)  # 发送图片


async def send_sticker_group(gid, ws, uid):
    """发送群聊表情包"""
    s = select_best_sticker(uid)  # 选择最佳表情包
    if isinstance(s, str):  # 返回的是QQ表情ID（字符串）
        await send_group_msg(gid, [{"type":"face","data":{"id":s}}], ws)  # 发送QQ表情
    else:  # 返回的是文件路径
        img_msg = make_image_msg(s)  # 构建图片消息
        if img_msg:  # 构建成功
            await send_group_msg(gid, img_msg, ws)  # 发送图片
