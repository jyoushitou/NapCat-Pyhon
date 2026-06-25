# ===================== 命令系统 =====================
# 仅主人可用，通过 ! 前缀触发，支持查看状态/管理记忆/手动操作等
import asyncio, os
from datetime import date
from .config import MASTER_QQ, LISTEN_HOST, LISTEN_PORT_QQ, HEARTBEAT_INTERVAL, DS_MODEL, STICKER_ARCHIVE_DIR, CLIP_IMAGE_TAGS
import botv.config as cfg

from .log import log_send, log_system, log_err, get_recent_logs
from .db import reload_api_keys, get_db, get_cursor, get_recent_usage
from .memory import load_memories, extract_keywords
from .schedule import is_workday_today, SCHEDULE_TASKS, CHINESE_CALENDAR_OK
from .send import send_private_msg, send_group_msg
from .image import get_best_image, fetch_and_save_acg_image
from .utils import make_image_msg
from .api import get_character_reply
from datetime import datetime

# 主人通过私聊发命令查看/修改运行时参数
CMD_PREFIX = "!"  # 命令前缀

def build_cmd_help():
    """构建帮助文本：列出所有可用命令及说明"""
    return (
        "📋 可用命令（私聊发送，仅主人有效）：\n"
        "!help          - 显示本帮助\n"
        "!status        - 查看运行状态概览\n"
        "!status all    - 查看所有详细参数\n"
        "!task          - 查看定时任务列表与下次触发时间\n"
        "!memory        - 查看对话记忆统计\n"
        "!memory <uid>  - 查看指定对象的记忆详情\n"
        "!sticker       - 查看表情包存档统计\n"
        "!clip          - 查看CLIP状态\n"
        "!keywords      - 查看全局关键词\n"
        "!apikeys       - 查看API密钥状态（隐藏完整值）\n"
        "!reload        - 重新加载API密钥和记忆\n"
        "!set <键> <值>  - 修改配置（仅支持部分参数）\n"
        "                支持: master_qq, heartbeat\n"
        "!say <内容>     - 让奈绪主动说一句话\n"
        "!sayg <群号> <内容> - 让奈绪在指定群说话\n"
        "!img <关键词>   - 手动搜图并发送\n"
        "!acg           - 获取一张ACG二次元图\n"
        "!event <uid>   - 查看指定对象的事件记忆\n"
        "!clear <uid>   - 清除指定对象的对话记忆\n"
        "!log <行数>     - 查看最近日志（默认20行）\n"
        "!db            - 查看数据库连接状态\n"
        "!usage         - 查看最近10次token用量和使用模型\n"
        "!uptime        - 查看机器人运行时长\n"
        "!ping          - 测试机器人是否在线\n"
    )

def format_status_detailed():
    """格式化详细状态信息：配置、API、记忆、定时任务等"""
    lines = []
    lines.append(f"🤖 主人QQ: {MASTER_QQ}")
    lines.append(f"🔌 WebSocket: {LISTEN_HOST}:{LISTEN_PORT_QQ}")
    lines.append(f"❤️ 心跳间隔: {HEARTBEAT_INTERVAL}s")
    lines.append(f"📦 消息去重缓存: {len(cfg.PROCESSED_MSG_IDS)}/80")
    lines.append("")
    lines.append(f"🧠 DeepSeek: {'✅' if cfg.DS_API_KEY else '❌'} {DS_MODEL}")
    lines.append(f"🫘 豆包: {'✅' if cfg.DOUBAO_API_KEY else '❌'}")
    lines.append(f"🖼️ CLIP: {'✅' if cfg.CLIP_ENABLED else '❌'}")
    lines.append(f"📅 chinesecalendar: {'✅ 已加载' if CHINESE_CALENDAR_OK else '⚠️ 未安装(降级weekday)'}")
    lines.append(f"🔑 搜图Token: {'✅ 已配置' if cfg.STICKER_API_ALAPI_TOKEN else '❌ 缺失'}")
    lines.append("")
    lines.append(f"🗂️ 对话对象数: {len(cfg.user_memory_pool)}")
    lines.append(f"🏷️ 全局关键词数: {len(cfg.global_keyword_set)}")
    lines.append(f"🖼️ 表情包存档: {len(cfg.STICKER_DATA)} 张")
    lines.append(f"👤 本日已触发定时: {len(cfg.daily_trigger)} 个")
    lines.append(f"💬 今日闲聊次数: {len(cfg.triggered_today)}/{len(cfg.daily_chat_trigger_times) if cfg.daily_chat_trigger_times else '?'}")
    wd = "工作日" if is_workday_today() else ("周末" if date.today().weekday() >= 5 else "法定节假日")
    lines.append(f"📆 今天: {date.today().strftime('%Y-%m-%d')} {['周一','周二','周三','周四','周五','周六','周日'][date.today().weekday()]}({wd})")
    return "\n".join(lines)

def format_task_list():
    lines = ["⏰ 定时任务列表："]
    today_key = date.today().isoformat()
    for task in SCHEDULE_TASKS:
        sc = task["scene"]
        key = f"{sc}_{today_key}"
        tm = cfg.task_trigger_minute.get(key, -1)
        tm_str = f"{tm//60:02d}:{tm%60:02d}" if tm >= 0 else "待计算"
        trig = "✅" if key in cfg.daily_trigger else "⏳"
        if sc == "催起床":
            wd_info = "工作日7:30 / 假日8:30"
        else:
            wd_info = f"{task['t'].strftime('%H:%M') if 't' in task else '动态'}"
        lines.append(f"  {trig} {sc} ({wd_info}) → {tm_str}")
    lines.append("")
    lines.append(f"💬 今日闲聊时间点: {', '.join(f'{t//60:02d}:{t%60:02d}' for t in cfg.daily_chat_trigger_times) if cfg.daily_chat_trigger_times else '待计算'}")
    return "\n".join(lines)

def format_memory_stats():
    lines = [f"🧠 对话记忆统计："]
    lines.append(f"  总对象数: {len(cfg.user_memory_pool)}")
    for tid, deq in list(cfg.user_memory_pool.items())[:10]:
        kw = extract_keywords(deq[-1][1] if deq else "")
        lines.append(f"  [{tid}] {len(deq)}条 | 最近: {deq[-1][0][:20] if deq else '无'}...")
    if len(cfg.user_memory_pool) > 10:
        lines.append(f"  ... 还有 {len(cfg.user_memory_pool)-10} 个对象")
    return "\n".join(lines)

def format_sticker_stats():
    lines = [f"🖼️ 表情包存档统计："]
    lines.append(f"  图片总数: {len(cfg.STICKER_DATA)} 张")
    lines.append(f"  存档目录: {STICKER_ARCHIVE_DIR}/")
    uid_count = len(set().union(*[info["users"] for info in cfg.STICKER_DATA.values()])) if cfg.STICKER_DATA else 0
    lines.append(f"  贡献用户: {uid_count} 人")
    if cfg.STICKER_DATA:
        top = sorted(cfg.STICKER_DATA.keys(), key=lambda h: cfg.STICKER_DATA[h]["use_count"], reverse=True)[:3]
        lines.append(f"  热门标签: tags统计略")
    return "\n".join(lines)

def format_clip_status():
    if cfg.CLIP_ENABLED:
        return f"🖼️ CLIP状态: ✅ 已加载 (ViT-B/32, CPU)\n  候选标签数: {len(CLIP_IMAGE_TAGS)}"
    else:
        return "🖼️ CLIP状态: ❌ 未加载（未安装torch/CLIP或加载失败）"

def format_keywords():
    if not cfg.global_keyword_set:
        return "🏷️ 全局关键词: 无"
    kws = sorted(cfg.global_keyword_set)
    return f"🏷️ 全局关键词 ({len(kws)}):\n  {'、'.join(kws[:40])}"

def format_apikeys():
    return (
                f"🔑 API密钥状态：\n"
        f"  DS_API_KEY: {'✅ 已配置' if cfg.DS_API_KEY else '❌ 缺失'}\n"
        f"  DOUBAO_API_KEY: {'✅ 已配置' if cfg.DOUBAO_API_KEY else '❌ 缺失'}\n"
        f"  STICKER_API_KEY: {'✅ 已配置' if cfg.STICKER_API_ALAPI_TOKEN else '❌ 缺失'}"
    )

async def handle_command(text, uid, ws, is_group, gid):
    """处理对话命令，返回True表示已处理（不再走AI回复）"""
    if not text.startswith(CMD_PREFIX):
        return False
    # 只有主人才能用命令
    if str(uid) != str(MASTER_QQ):
        return False

    cmd = text[1:].strip()
    parts = cmd.split()
    cmd_name = parts[0].lower() if parts else ""

    reply = ""

    if cmd_name == "help":
        reply = build_cmd_help()

    elif cmd_name == "status":
        if "all" in parts:
            reply = format_status_detailed()
        else:
            lines = []
            lines.append(f"🤖 状态概览：")
            lines.append(f"  DS: {'✅' if cfg.DS_API_KEY else '❌'} | 豆包: {'✅' if cfg.DOUBAO_API_KEY else '❌'} | CLIP: {'✅' if cfg.CLIP_ENABLED else '❌'}")
            lines.append(f"  📅 {'工作日' if is_workday_today() else '休息日'} | 对话对象: {len(cfg.user_memory_pool)} | 关键词: {len(cfg.global_keyword_set)}")
            lines.append(f"  🖼️ 存档: {len(cfg.STICKER_DATA)}张 | 定时触发: {len(cfg.daily_trigger)}个")
            lines.append(f"  💬 闲聊: {len(cfg.triggered_today)}/合")
            lines.append(f"  使用 !status all 查看详细")
            reply = "\n".join(lines)

    elif cmd_name == "task":
        reply = format_task_list()

    elif cmd_name == "memory":
        if len(parts) > 1:
            target = parts[1]
            if target in cfg.user_memory_pool:
                deq = cfg.user_memory_pool[target]
                lines = [f"🧠 {target} 的对话记忆（共{len(deq)}条）："]
                for i, (u, b) in enumerate(deq[-10:], 1):
                    lines.append(f"  {i}. 用户: {u[:30]}...")
                    lines.append(f"     奈绪: {b[:30]}...")
                reply = "\n".join(lines)
            else:
                reply = f"🧠 {target} 暂无对话记忆"
        else:
            reply = format_memory_stats()

    elif cmd_name == "sticker":
        reply = format_sticker_stats()

    elif cmd_name == "clip":
        reply = format_clip_status()

    elif cmd_name == "keywords":
        reply = format_keywords()

    elif cmd_name == "apikeys":
        reply = format_apikeys()

    elif cmd_name == "reload":
        try:
            reload_api_keys()
            load_memories()
            reply = "♻️ 已重新加载API密钥和记忆数据"
        except Exception as e:
            reply = f"❌ 重载失败: {e}"

    elif cmd_name == "set":
        if len(parts) < 3:
            reply = "用法: !set <键> <值>\n支持: master_qq, heartbeat"
        else:
            key = parts[1].lower()
            val = " ".join(parts[2:])
            try:
                if key == "master_qq":
                    globals()["MASTER_QQ"] = int(val)
                    reply = f"✅ 主人QQ已设为 {MASTER_QQ}"
                elif key == "heartbeat":
                    globals()["HEARTBEAT_INTERVAL"] = int(val)
                    reply = f"✅ 心跳间隔已设为 {HEARTBEAT_INTERVAL}s"
                else:
                    reply = f"❌ 不支持的配置项: {key}"
            except Exception as e:
                reply = f"❌ 设置失败: {e}"

    elif cmd_name == "say":
        if len(parts) < 2:
            reply = "用法: !say <内容>"
        else:
            content = " ".join(parts[1:])
            rep = await get_character_reply(content, str(MASTER_QQ))
            msg = [{"type": "text", "data": {"text": rep}}]
            if is_group:
                await send_group_msg(gid, msg, ws)
            else:
                await send_private_msg(uid, msg, ws)
            log_send(f"[!say] 已回复: {rep[:40]}...")
            return True

    elif cmd_name == "sayg":
        if len(parts) < 3:
            reply = "用法: !sayg <群号> <内容>"
        else:
            target_gid = parts[1]
            content = " ".join(parts[2:])
            rep = await get_character_reply(content, target_gid)
            msg = [{"type": "text", "data": {"text": rep}}]
            try:
                await send_group_msg(int(target_gid), msg, ws)
                log_send(f"[!sayg] 已向群{target_gid}发送: {rep[:40]}...")
            except Exception as e:
                reply = f"❌ 发送失败: {e}"
            return True

    elif cmd_name == "img":
        if len(parts) < 2:
            reply = "用法: !img <关键词1> <关键词2> ..."
        else:
            kws = parts[1:]
            fp = await get_best_image(kws, uid)
            if fp:
                abs_fp = os.path.abspath(fp)
                img_msg = [{"type":"image","data":{"file":f"file:///{abs_fp}"}}]
                if is_group:
                    await send_group_msg(gid, img_msg, ws)
                else:
                    await send_private_msg(uid, img_msg, ws)
                log_send(f"[!img] 已发送图片: {abs_fp}")
            else:
                reply = f"❌ 未搜到与关键词 [{', '.join(kws)}] 相关的图片"
            return True

    elif cmd_name == "acg":
        fp = await fetch_and_save_acg_image()
        if fp:
            abs_fp = os.path.abspath(fp)
            img_msg = [{"type":"image","data":{"file":f"file:///{abs_fp}"}}]
            if is_group:
                await send_group_msg(gid, img_msg, ws)
            else:
                await send_private_msg(uid, img_msg, ws)
            log_send(f"[!acg] 已发送ACG图: {abs_fp}")
        else:
            reply = "❌ 获取ACG图片失败"
        return True

    elif cmd_name == "event":
        target = parts[1] if len(parts) > 1 else str(MASTER_QQ)
        try:
            from .db import load_events_from_db
            events = load_events_from_db(target, limit=10)
            if events:
                lines = [f"📅 {target} 的事件记忆（最近{len(events)}条）："]
                for i, (summary, tags) in enumerate(events, 1):
                    tag_str = f" [{tags}]" if tags else ""
                    lines.append(f"  {i}. {summary}{tag_str}")
                reply = "\n".join(lines)
            else:
                reply = f"📅 {target} 暂无事件记忆"
        except Exception as e:
            reply = f"❌ 查询事件失败: {e}"

    elif cmd_name == "clear":
        target = parts[1] if len(parts) > 1 else str(MASTER_QQ)
        try:
            c = get_cursor()
            c.execute("DELETE FROM user_memory WHERE target_id=%s", (target,))
            c.execute("DELETE FROM events WHERE target_id=%s", (target,))
            c.connection.commit()
            if target in cfg.user_memory_pool:
                del cfg.user_memory_pool[target]
            reply = f"已清除 {target} 的对话记忆和事件记录"
        except Exception as e:
            reply = f"清除失败: {e}"

    elif cmd_name == "log":
        line_count = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 20
        line_count = min(max(line_count, 1), 100)
        logs = get_recent_logs(line_count)
        reply = f"📋 最近{line_count}条日志：\n{logs}"

    elif cmd_name == "db":
        try:
            c = get_cursor()
            c.execute("SELECT COUNT(*) as cnt FROM images")
            img_count = c.fetchone()["cnt"]
            c.execute("SELECT COUNT(*) as cnt FROM user_memory")
            mem_count = c.fetchone()["cnt"]
            c.execute("SELECT COUNT(*) as cnt FROM events")
            evt_count = c.fetchone()["cnt"]
            c.execute("SELECT COUNT(*) as cnt FROM logs")
            log_count = c.fetchone()["cnt"]
            c.execute("SELECT COUNT(*) as cnt FROM global_keywords")
            kw_count = c.fetchone()["cnt"]
            reply = (
                f"🗄️ 数据库状态：\n"
                f"  🖼️ 图片库: {img_count} 张\n"
                f"  🧠 对话记忆: {mem_count} 条\n"
                f"  📅 事件记忆: {evt_count} 条\n"
                f"  📋 日志: {log_count} 条\n"
                f"  🏷️ 全局关键词: {kw_count} 个"
            )
        except Exception as e:
            reply = f"❌ 查询数据库失败: {e}"

    elif cmd_name == "uptime":
        try:
            c = get_cursor()
            c.execute("SELECT MIN(id) as first_id, MIN(created_at) as first_log FROM logs")
            r = c.fetchone()
            if r and r["first_log"]:
                first_log = r["first_log"]
                # created_at 可能是 datetime 对象或字符串
                if isinstance(first_log, datetime):
                    start = first_log
                else:
                    start = datetime.strptime(str(first_log), "%Y-%m-%d %H:%M:%S")
                now = datetime.now()
                delta = now - start
                days = delta.days
                hours = delta.seconds // 3600
                mins = (delta.seconds % 3600) // 60
                reply = f"⏱️ 机器人运行时长：{days}天{hours}小时{mins}分钟\n  首次日志: {start.strftime('%Y-%m-%d %H:%M:%S')}"
            else:
                reply = "⏱️ 暂无运行时长数据"
        except Exception as e:
            reply = f"❌ 查询失败: {e}"

    elif cmd_name == "ping":
        reply = "🏓 Pong！奈绪在线~"

    elif cmd_name == "usage":
        try:
            records = get_recent_usage(10)
            if not records:
                reply = "📊 暂无token用量记录"
            else:
                lines = ["📊 最近10次AI调用token用量："]
                total_prompt = 0
                total_completion = 0
                total_all = 0
                for i, r in enumerate(records, 1):
                    model = r["model_name"]
                    pt = r["prompt_tokens"] or 0
                    ct = r["completion_tokens"] or 0
                    tt = r["total_tokens"] or 0
                    tm = r["created_at"]
                    if hasattr(tm, 'strftime'):
                        tm_str = tm.strftime('%m-%d %H:%M')
                    else:
                        tm_str = str(tm)[5:16] if tm else ''
                    lines.append(f"  {i}. [{model}] 输入{pt}+输出{ct}={tt} ({tm_str})")
                    total_prompt += pt
                    total_completion += ct
                    total_all += tt
                lines.append(f"  ─────────────────────")
                lines.append(f"  📈 合计: 输入{total_prompt}+输出{total_completion}={total_all}")
                reply = "\n".join(lines)
        except Exception as e:
            reply = f"❌ 查询token用量失败: {e}"

    else:
        reply = f"❌ 未知命令: {cmd_name}\n输入 !help 查看可用命令"

    # 发送回复
    if reply:
        msg = [{"type": "text", "data": {"text": reply}}]
        if is_group:
            await send_group_msg(gid, msg, ws)
        else:
            await send_private_msg(uid, msg, ws)
        log_send(f"[命令回复] {reply[:50]}...")
    return True

