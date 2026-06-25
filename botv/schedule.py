# 定时任务：催起床、提醒等 + 工作日判断
import asyncio, random, os
from datetime import datetime, time, date
from .config import MASTER_QQ, CST, IMAGE_DIR
import botv.config as cfg
from .log import log_system, log_err
from .api import get_character_reply
from .memory import add_target_memory
from .send import send_short_reply, send_private_msg
from .image import fetch_and_save_acg_image, search_local_image_by_tags, get_best_image
from .utils import encode_image_base64, make_image_msg, parse_ai_reply

# 工作日判断（chinesecalendar 可选）
try:
    from chinesecalendar import is_workday as _is_workday
    CHINESE_CALENDAR_OK = True
except:
    CHINESE_CALENDAR_OK = False

def is_workday_today():
    """判断今天是否是法定工作日，使用 chinesecalendar 库"""
    if CHINESE_CALENDAR_OK:
        try:
            return _is_workday(date.today())
        except:
            pass
    return date.today().weekday() < 5

# 定时任务配置
# weekday: 0=周一 ... 6=周日
# 催起床特殊：工作日7:30，非工作日8:30
# 周末吐槽赖床仅非工作日触发（用 is_workday_today 动态判断，涵盖周末+法定节假日）
SCHEDULE_TASKS=[
    {"scene":"催起床","weekday":[0,1,2,3,4,5,6]},
    {"scene":"周末吐槽赖床","weekday":[0,1,2,3,4,5,6],"t":time(8,30),"only_holiday":True},
    {"scene":"提醒点外卖","weekday":[0,1,2,3,4,5,6],"t":time(10,40)},
    {"scene":"叮嘱午睡","weekday":[0,1,2,3,4,5,6],"t":time(12,30)},
    {"scene":"提醒起身","weekday":[0,1,2,3,4,5,6],"t":time(13,30)},
    {"scene":"提醒晚餐","weekday":[0,1,2,3,4,5,6],"t":time(16,40)},
    {"scene":"催睡觉","weekday":[0,1,2,3,4,5,6]},
]

# 计算一天的触发时间表（只应计算一次）
def _calc_day_tasks(today: date, is_workday: bool):
    """计算某一天所有任务的触发分钟（带随机偏移），返回 {key: minute}"""
    result = {}
    today_weekday = today.weekday()
    for task in SCHEDULE_TASKS:
        if today_weekday not in task["weekday"]:
            continue
        # 仅节假日触发的任务（周末吐槽赖床），工作日跳过
        if task.get("only_holiday") and is_workday:
            continue
        if task["scene"] == "催起床":
            base_h, base_m = (7, 30) if is_workday else (8, 30)
            base = base_h * 60 + base_m
        elif task["scene"] == "催睡觉":
            # 根据明天是否是工作日决定今晚催睡觉时间
            from datetime import timedelta
            tomorrow = today + timedelta(days=1)
            if CHINESE_CALENDAR_OK:
                try:
                    tomorrow_workday = _is_workday(tomorrow)
                except:
                    tomorrow_workday = tomorrow.weekday() < 5
            else:
                tomorrow_workday = tomorrow.weekday() < 5
            base_h, base_m = (23, 0) if tomorrow_workday else (23, 30)
            base = base_h * 60 + base_m
        else:
            base = task["t"].hour * 60 + task["t"].minute
        key = f"{task['scene']}_{today}"
        result[key] = max(0, min(1439, base + random.randint(-10, 10)))
    return result

# 每天首次运行的延迟（秒），用于跨天精确触发
_FIRST_RUN_DELAY = 10

async def cycle_task_run():
    await asyncio.sleep(_FIRST_RUN_DELAY)
    _last_today = None  # 记录上一次检查的日期
    _is_workday = True  # 缓存当天是否工作日
    while True:
        try:
            now = datetime.now(CST)
            today = now.date()
            cur_minute = now.hour * 60 + now.minute

            # ---------- 跨天/首次初始化 ----------
            if today != _last_today:
                log_system(f"定时任务：切换到 {today}")
                _is_workday = is_workday_today()
                log_system(f"今天 {'工作日' if _is_workday else '非工作日'} 催起床={'7:30' if _is_workday else '8:30'} 催睡觉=看明天工作日定")
                # 清空所有触发记录
                cfg.daily_trigger.clear()
                cfg.triggered_today.clear()
                cfg.task_trigger_minute.clear()
                cfg.today = today
                # 计算当日闲聊触发时刻（随机2~4次，12:00~18:00）
                cfg.daily_chat_trigger_times = random.sample(range(720, 1080), random.randint(2, 4))
                # 计算当日所有任务触发时刻
                cfg.task_trigger_minute.update(_calc_day_tasks(today, _is_workday))
                _last_today = today
                log_system(f"定时任务初始化完成，共 {len(cfg.task_trigger_minute)} 个任务点")

            # ---------- 生日检查 ----------
            birthday_flag_key = f"birthday_{today.year}"
            if (birthday_flag_key not in cfg.daily_trigger and
                    now.month == 9 and now.day == 6 and now.hour == 12 and now.minute == 0):
                age = now.year - 2006
                rep = await get_character_reply(f"生日快乐,今年{age}岁了", str(MASTER_QQ))
                dialog, action, img_kw, event, refined_kw = parse_ai_reply(rep)
                add_target_memory(str(MASTER_QQ), f"今天是我{age}岁生日", rep, img_kw, refined_kw, event or f"主人过{age}岁生日")
                await send_short_reply(MASTER_QQ, rep, cfg.active_ws_qq, MASTER_QQ)
                bd_fp = await get_best_image(["生日快乐","生日","蛋糕","庆祝","happy"], str(MASTER_QQ))
                bd_msg = make_image_msg(bd_fp)
                if bd_msg:
                    await send_private_msg(MASTER_QQ, bd_msg, cfg.active_ws_qq)
                cfg.daily_trigger.add(birthday_flag_key)
                log_system(f"主人生日快乐！今年{age}岁了")

            nao_birthday_key = f"nao_birthday_{today.year}"
            if (nao_birthday_key not in cfg.daily_trigger and
                    now.month == 11 and now.day == 13 and now.hour == 8 and now.minute == 0):
                rep = await get_character_reply("奈绪生日快乐", str(MASTER_QQ))
                dialog, action, img_kw, event, refined_kw = parse_ai_reply(rep)
                add_target_memory(str(MASTER_QQ), "友利奈绪生日", rep, img_kw, refined_kw, event or "今天是我(奈绪)的生日")
                await send_short_reply(MASTER_QQ, rep, cfg.active_ws_qq, MASTER_QQ)
                nao_results = search_local_image_by_tags(["奈绪","友利奈绪","Charlotte","夏洛特"], limit=5)
                if nao_results:
                    nao_fp = random.choice(nao_results)[2]
                    nao_msg = make_image_msg(nao_fp)
                    if nao_msg:
                        await send_private_msg(MASTER_QQ, nao_msg, cfg.active_ws_qq)
                else:
                    img_fp = await fetch_and_save_acg_image()
                    img_msg = make_image_msg(img_fp)
                    if img_msg and cfg.active_ws_qq and not getattr(cfg.active_ws_qq, "closed", False):
                        await send_private_msg(MASTER_QQ, img_msg, cfg.active_ws_qq)
                cfg.daily_trigger.add(nao_birthday_key)
                log_system("奈绪生日快乐！")

                                    # ---------- 任务触发 ----------
            for task in SCHEDULE_TASKS:
                key = f"{task['scene']}_{today}"
                if key in cfg.daily_trigger:
                    continue
                if today.weekday() not in task["weekday"]:
                    continue
                # 仅节假日任务（周末吐槽赖床），工作日跳过
                if task.get("only_holiday") and _is_workday:
                    continue
                tm = cfg.task_trigger_minute.get(key)
                if tm is None or cur_minute != tm:
                    continue

                # 执行任务
                if task["scene"] == "催起床":
                    rep = await get_character_reply("催起床", str(MASTER_QQ))
                    await send_short_reply(MASTER_QQ, rep, cfg.active_ws_qq, MASTER_QQ)
                    img_fp = await fetch_and_save_acg_image()
                    img_msg = make_image_msg(img_fp)
                    if img_msg and cfg.active_ws_qq and not getattr(cfg.active_ws_qq, "closed", False):
                        await send_private_msg(MASTER_QQ, img_msg, cfg.active_ws_qq)
                        log_system("ACG起床图已发送")
                elif task["scene"] == "催睡觉":
                    rep = await get_character_reply(task["scene"], str(MASTER_QQ))
                    await send_short_reply(MASTER_QQ, rep, cfg.active_ws_qq, MASTER_QQ)
                    img_fp = await fetch_and_save_acg_image()
                    img_msg = make_image_msg(img_fp)
                    if img_msg and cfg.active_ws_qq and not getattr(cfg.active_ws_qq, "closed", False):
                        await send_private_msg(MASTER_QQ, img_msg, cfg.active_ws_qq)
                        log_system("ACG催睡图已发送")
                else:
                    rep = await get_character_reply(task["scene"], str(MASTER_QQ))
                    await send_short_reply(MASTER_QQ, rep, cfg.active_ws_qq, MASTER_QQ)

                cfg.daily_trigger.add(key)
                log_system(f"定时:{task['scene']}")

            # ---------- 闲聊触发 ----------
            if (cur_minute in cfg.daily_chat_trigger_times and
                    cur_minute not in cfg.triggered_today):
                cfg.triggered_today.add(cur_minute)
                rep = await get_character_reply("闲聊", str(MASTER_QQ))
                await send_short_reply(MASTER_QQ, rep, cfg.active_ws_qq, MASTER_QQ)
                log_system("闲聊触发")

        except Exception as e:
            log_err(f"定时异常:{e}")

        await asyncio.sleep(1)
