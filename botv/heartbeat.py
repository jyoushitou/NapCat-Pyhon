# WebSocket 心跳监测
import asyncio
from .config import HEARTBEAT_INTERVAL
from .log import log_system

async def heartbeat_monitor(label,ws_ref):
    """通用心跳监测，label如'QQ'/'微信'，ws_ref是全局变量引用"""
    while True:
        await asyncio.sleep(HEARTBEAT_INTERVAL)
        ws = ws_ref
        if ws and not getattr(ws,"closed",False):
            try: await ws.ping()
            except:
                log_system(f"{label}心跳断开")
