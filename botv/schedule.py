# 定时任务：催起床、提醒等 + 工作日判断
import asyncio, random
from datetime import datetime, time, date
from .config import MASTER_QQ, CST, active_ws_qq
from .log import log_system, log_err
from .memory import get_character_reply
from .send import send_short_reply, send_private_msg
from .image import fetch_and_save_acg_image
from .utils import encode_image_base64

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
    # 备用：降级到简单 weekday 判断（周一到周五算工作日）
    return date.today().weekday() < 5

# "催起床"只有一条，每天动态判断是否是工作日来决定 7:30 还是 8:30 叫。
# 其他任务固定 weekday=全部，每天触发一次（均由 daily_trigger 防重复）。
SCHEDULE_TASKS=[
    {"scene":"催起床","weekday":[0,1,2,3,4,5,6]},
    {"scene":"周末吐槽赖床","weekday":[0,1,2,3,4,5,6],"t":time(8,30)},
    {"scene":"提醒点外卖","weekday":[0,1,2,3,4,5,6],"t":time(10,40)},
    {"scene":"叮嘱午睡","weekday":[0,1,2,3,4,5,6],"t":time(12,30)},
    {"scene":"提醒起身","weekday":[0,1,2,3,4,5,6],"t":time(13,30)},
    {"scene":"提醒晚餐","weekday":[0,1,2,3,4,5,6],"t":time(16,40)},
    {"scene":"催睡觉","weekday":[0,1,2,3,4,5,6],"t":time(23,0)},
    {"scene":"勒令睡觉","weekday":[0,1,2,3,4,5,6],"t":time(23,30)},
]

async def cycle_task_run():
    global daily_trigger,today,daily_chat_trigger_times,triggered_today,task_trigger_minute
    await asyncio.sleep(10)
    while True:
        try:
            now=datetime.now()
            if now.date()!=today:
                daily_trigger.clear(); triggered_today.clear(); task_trigger_minute.clear()
                today=now.date(); cnt=random.randint(2,4)
                daily_chat_trigger_times=random.sample(range(720,1080),cnt)
                for task in SCHEDULE_TASKS:
                    if now.weekday() not in task["weekday"]: continue
                    if task["scene"] == "催起床":
                        # 动态判断：工作日 7:30，周末/节假日 8:30
                        base_h, base_m = (7, 30) if is_workday_today() else (8, 30)
                        base = base_h * 60 + base_m
                    else:
                        base=task["t"].hour*60+task["t"].minute
                    task_trigger_minute[f"{task['scene']}_{today}"]=max(0,min(1439,base+random.randint(-10,10)))
            cur=now.hour*60+now.minute
            for task in SCHEDULE_TASKS:
                key=f"{task['scene']}_{today}"
                if key in daily_trigger: continue
                if now.weekday() not in task["weekday"]: continue
                tm=task_trigger_minute.get(key)
                if tm is None or cur!=tm: continue
                # 催起床特殊处理：发文字 + ACG 图片
                if task["scene"] == "催起床":
                    rep = await get_character_reply("催起床", str(MASTER_QQ))
                    await send_short_reply(MASTER_QQ, rep, active_ws_qq, MASTER_QQ)
                    # 异步获取 ACG 图片并发送
                    img_fp = await asyncio.to_thread(fetch_and_save_acg_image)
                    if img_fp and active_ws_qq and not getattr(active_ws_qq, "closed", False):
                        with open(img_fp, "rb") as f:
                            b64 = encode_image_base64(f.read())
                        await send_private_msg(MASTER_QQ, [{"type":"image","data":{"file":b64}}], active_ws_qq)
                        log_system("ACG起床图已发送")
                else:
                    rep = await get_character_reply(task["scene"], str(MASTER_QQ))
                    await send_short_reply(MASTER_QQ, rep, active_ws_qq, MASTER_QQ)
                daily_trigger.add(key); log_system(f"定时:{task['scene']}")
            if cur in daily_chat_trigger_times and cur not in triggered_today:
                triggered_today.add(cur)
                rep=await get_character_reply("闲聊",str(MASTER_QQ))
                await send_short_reply(MASTER_QQ,rep,active_ws_qq,MASTER_QQ)
                log_system("闲聊触发")
        except Exception as e: log_err(f"定时异常:{e}")
        await asyncio.sleep(1)
