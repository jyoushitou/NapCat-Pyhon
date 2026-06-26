# ===================== WebSocket 心跳监测模块 =====================
# 定期发送 ping 帧检测 WebSocket 连接是否存活
# 如果 ping 失败则记录日志，由上层逻辑处理重连

import asyncio  # 异步 IO：定时器
from .config import HEARTBEAT_INTERVAL  # 心跳间隔（秒）
from .log import log_system  # 系统日志

async def heartbeat_monitor(label: str, ws_ref):
    """通用心跳监测协程
    
    参数：
        label: 连接标识，如 'QQ'/'微信'，用于日志区分
        ws_ref: 全局 WebSocket 变量引用（如 cfg.active_ws_qq），
                每次循环重新读取以获取最新连接状态
    
    行为：
        - 每 HEARTBEAT_INTERVAL 秒发送一次 ping
        - 如果连接已关闭或 ping 失败，记录日志
        - 不主动关闭连接，由主循环处理断开逻辑
    """
    while True:
        await asyncio.sleep(HEARTBEAT_INTERVAL)  # 等待指定间隔
        ws = ws_ref  # 重新读取全局变量（可能已被其他协程更新）
        if ws and not getattr(ws, "closed", False):  # 连接存在且未关闭
            try:
                await ws.ping()  # 发送 WebSocket ping 帧
            except:
                log_system(f"{label}心跳断开")  # ping 失败，记录日志
