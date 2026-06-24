# ! 命令系统（仅主人可用）
import asyncio
from datetime import date
from .config import MASTER_QQ, LISTEN_HOST, LISTEN_PORT_QQ, HEARTBEAT_INTERVAL, DS_API_KEY, DOUBAO_API_KEY, SEARCH_STICKER_KEY, DS_MODEL, STICKER_DATA, STICKER_ARCHIVE_DIR, CLIP_IMAGE_TAGS
from .log import log_send, log_system, log_err
from .db import reload_api_keys
from .memory import load_memories, user_memory_pool, global_keyword_set, extract_keywords
from .schedule import is_workday_today, SCHEDULE_TASKS, daily_trigger, triggered_today, daily_chat_trigger_times, task_trigger_minute, CHINESE_CALENDAR_OK
from .send import send_private_msg, send_group_msg
from .clip import CLIP_ENABLED

# 主人通过私聊发命令查看/修改运行时参数
CMD_PREFIX = "!"

def build_cmd_help():
    return (
        "📋 可用命令（私聊发送，仅主人有效）：\n"
        "!help        - 显示本帮助\n"
        "!status      - 查看运行状态概览\n"
        "!status all  - 查看所有详细参数\n"
        "!task        - 查看定时任务列表与下次触发时间\n"
        "!memory      - 查看对话记忆统计\n"
        "!sticker     - 查看表情包存档统计\n"
        "!clip        - 查看CLIP状态\n"
        "!keywords    - 查看全局关键词\n"
        "!apikeys     - 查看API密钥状态（隐藏完整值）\n"
        "!reload      - 重新加载API密钥和记忆\n"
        "!set <键> <值> - 修改配置（仅支持部分参数）\n"
        "              支持: master_qq, heartbeat, maxtokens, temperature\n"
    )

def format_status_detailed():
    lines = []
    lines.append(f"🤖 主人QQ: {MASTER_QQ}")
    lines.append(f"🔌 WebSocket: {LISTEN_HOST}:{LISTEN_PORT_QQ}")
    lines.append(f"❤️ 心跳间隔: {HEARTBEAT_INTERVAL}s")
    lines.append(f"📦 消息去重缓存: {len(PROCESSED_MSG_IDS)}/80")
    lines.append("")
    lines.append(f"🧠 DeepSeek: {'✅' if DS_API_KEY else '❌'} {DS_MODEL}")
    lines.append(f"🫘 豆包: {'✅' if DOUBAO_API_KEY else '❌'}")
    lines.append(f"🖼️ CLIP: {'✅' if CLIP_ENABLED else '❌'}")
    lines.append(f"📅 chinesecalendar: {'✅ 已加载' if CHINESE_CALENDAR_OK else '⚠️ 未安装(降级weekday)'}")
    lines.append(f"🔑 搜图Token: {'✅ 已配置' if SEARCH_STICKER_KEY else '❌ 缺失'}")
    lines.append("")
    lines.append(f"🗂️ 对话对象数: {len(user_memory_pool)}")
    lines.append(f"🏷️ 全局关键词数: {len(global_keyword_set)}")
    lines.append(f"🖼️ 表情包存档: {len(STICKER_DATA)} 张")
    lines.append(f"👤 本日已触发定时: {len(daily_trigger)} 个")
    lines.append(f"💬 今日闲聊次数: {len(triggered_today)}/{len(daily_chat_trigger_times) if daily_chat_trigger_times else '?'}")
    wd = "工作日" if is_workday_today() else ("周末" if date.today().weekday() >= 5 else "法定节假日")
    lines.append(f"📆 今天: {date.today().strftime('%Y-%m-%d')} {['周一','周二','周三','周四','周五','周六','周日'][date.today().weekday()]}({wd})")
    return "\n".join(lines)

def format_task_list():
    lines = ["⏰ 定时任务列表："]
    today_key = date.today().isoformat()
    for task in SCHEDULE_TASKS:
        sc = task["scene"]
        key = f"{sc}_{today_key}"
        tm = task_trigger_minute.get(key, -1)
        tm_str = f"{tm//60:02d}:{tm%60:02d}" if tm >= 0 else "待计算"
        trig = "✅" if key in daily_trigger else "⏳"
        if sc == "催起床":
            wd_info = "工作日7:30 / 假日8:30"
        else:
            wd_info = f"{task['t'].strftime('%H:%M') if 't' in task else '动态'}"
        lines.append(f"  {trig} {sc} ({wd_info}) → {tm_str}")
    lines.append("")
    lines.append(f"💬 今日闲聊时间点: {', '.join(f'{t//60:02d}:{t%60:02d}' for t in daily_chat_trigger_times) if daily_chat_trigger_times else '待计算'}")
    return "\n".join(lines)

def format_memory_stats():
    lines = [f"🧠 对话记忆统计："]
    lines.append(f"  总对象数: {len(user_memory_pool)}")
    for tid, deq in list(user_memory_pool.items())[:10]:
        kw = extract_keywords(deq[-1][1] if deq else "")
        lines.append(f"  [{tid}] {len(deq)}条 | 最近: {deq[-1][0][:20] if deq else '无'}...")
    if len(user_memory_pool) > 10:
        lines.append(f"  ... 还有 {len(user_memory_pool)-10} 个对象")
    return "\n".join(lines)

def format_sticker_stats():
    lines = [f"🖼️ 表情包存档统计："]
    lines.append(f"  图片总数: {len(STICKER_DATA)} 张")
    lines.append(f"  存档目录: {STICKER_ARCHIVE_DIR}/")
    uid_count = len(set().union(*[info["users"] for info in STICKER_DATA.values()])) if STICKER_DATA else 0
    lines.append(f"  贡献用户: {uid_count} 人")
    if STICKER_DATA:
        top = sorted(STICKER_DATA.keys(), key=lambda h: STICKER_DATA[h]["use_count"], reverse=True)[:3]
        lines.append(f"  热门标签: tags统计略")
    return "\n".join(lines)

def format_clip_status():
    if CLIP_ENABLED:
        return f"🖼️ CLIP状态: ✅ 已加载 (ViT-B/32, CPU)\n  候选标签数: {len(CLIP_IMAGE_TAGS)}"
    else:
        return "🖼️ CLIP状态: ❌ 未加载（未安装torch/CLIP或加载失败）"

def format_keywords():
    if not global_keyword_set:
        return "🏷️ 全局关键词: 无"
    kws = sorted(global_keyword_set)
    return f"🏷️ 全局关键词 ({len(kws)}):\n  {'、'.join(kws[:40])}"

def format_apikeys():
    return (
        f"🔑 API密钥状态：\n"
        f"  DS_API_KEY: {'✅ 已配置' if DS_API_KEY else '❌ 缺失'}\n"
        f"  DOUBAO_API_KEY: {'✅ 已配置' if DOUBAO_API_KEY else '❌ 缺失'}\n"
        f"  STICKER_API_KEY: {'✅ 已配置' if SEARCH_STICKER_KEY else '❌ 缺失'}"
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
            lines.append(f"  DS: {'✅' if DS_API_KEY else '❌'} | 豆包: {'✅' if DOUBAO_API_KEY else '❌'} | CLIP: {'✅' if CLIP_ENABLED else '❌'}")
            lines.append(f"  📅 {'工作日' if is_workday_today() else '休息日'} | 对话对象: {len(user_memory_pool)} | 关键词: {len(global_keyword_set)}")
            lines.append(f"  🖼️ 存档: {len(STICKER_DATA)}张 | 定时触发: {len(daily_trigger)}个")
            lines.append(f"  💬 闲聊: {len(triggered_today)}/合")
            lines.append(f"  使用 !status all 查看详细")
            reply = "\n".join(lines)

    elif cmd_name == "task":
        reply = format_task_list()

    elif cmd_name == "memory":
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
            reply = "用法: !set <键> <值>\n支持: master_qq, heartbeat, maxtokens, temperature"
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
                elif key == "maxtokens":
                    # 修改全局变量需小心，这里只是示例
                    reply = f"❌ max_tokens 当前为代码内固定值，不建议运行时修改"
                elif key == "temperature":
                    reply = f"❌ temperature 当前为代码内固定值 0.7，不建议运行时修改"
                else:
                    reply = f"❌ 不支持的配置项: {key}"
            except Exception as e:
                reply = f"❌ 设置失败: {e}"

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
