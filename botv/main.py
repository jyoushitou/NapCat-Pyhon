# ===================== 主程序入口 =====================
# 初始化所有模块，启动WebSocket服务器，管理心跳和定时任务

import asyncio  # 异步IO
import websockets  # WebSocket服务器库

from .config import LISTEN_HOST, LISTEN_PORT_QQ  # 监听地址和端口
import botv.config as cfg  # 全局运行时变量
from .log import log_system, log_err  # 日志
from .db import reload_api_keys, get_cursor  # 数据库：重新加载API密钥、获取游标
from .memory import load_memories  # 加载对话记忆
from .sticker_archive import init_sticker_archive  # 初始化表情包存档
from .clip import init_clip_model  # 初始化CLIP模型
from .personality import load_personality_supplement  # 加载人设补充
from .heartbeat import heartbeat_monitor  # 心跳监控
from .schedule import cycle_task_run, CHINESE_CALENDAR_OK  # 定时任务循环、农历日历状态
from .handler import websocket_handle_qq  # WebSocket消息处理函数
from .api_server import start_api_server  # HTTP API服务器


async def main():
    """主函数：初始化各模块，启动WebSocket服务器，异常时自动重启"""
    # ===================== 初始化各模块 =====================
    load_memories()
    init_sticker_archive()
    init_clip_model()
    reload_api_keys()
    load_personality_supplement()
    
    # 确保 ACG 图片表存在
    try:
        c = get_cursor()
        c.execute("""
            CREATE TABLE IF NOT EXISTS acg_images (
                id INT AUTO_INCREMENT PRIMARY KEY,
                md5_hash VARCHAR(32) NOT NULL UNIQUE,
                image_data MEDIUMBLOB,
                tags VARCHAR(255) DEFAULT '',
                source_url VARCHAR(512) DEFAULT '',
                file_path VARCHAR(255) DEFAULT '',
                ext VARCHAR(10) DEFAULT 'jpg',
                use_count INT DEFAULT 0,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """)
        c.connection.commit()
        log_system("acg_images 表已就绪")
    except Exception as e:
        log_err(f"建表失败: {e}")
    
    # 确保 ai_raw_responses 表有 token 用量字段
    try:
        c = get_cursor()
        c.execute("SHOW COLUMNS FROM ai_raw_responses LIKE 'prompt_tokens'")
        if not c.fetchone():
            c.execute("ALTER TABLE ai_raw_responses ADD COLUMN prompt_tokens INT DEFAULT 0")
            c.execute("ALTER TABLE ai_raw_responses ADD COLUMN completion_tokens INT DEFAULT 0")
            c.execute("ALTER TABLE ai_raw_responses ADD COLUMN total_tokens INT DEFAULT 0")
            c.connection.commit()
            log_system("ai_raw_responses 表已升级，添加token用量字段")
        else:
            log_system("ai_raw_responses 表token字段已存在")
    except Exception as e:
        log_err(f"升级ai_raw_responses表失败: {e}")
    
    cfg.PROCESS_LOCK = asyncio.Lock()  # 初始化消息处理锁
    log_system("初始化完成(CLIP识图版)")
    
    # ===================== 启动 API 服务器 =====================
    try:
        api_runner = await start_api_server()
        log_system("API 服务器已启动")
    except Exception as e:
        log_err(f"API 服务器启动失败: {e}")
        api_runner = None
    
    # ===================== 主循环 =====================
    while True:
        hb = asyncio.create_task(heartbeat_monitor("QQ", cfg.active_ws_qq))
        cyc = asyncio.create_task(cycle_task_run())
        try:
            async with websockets.serve(websocket_handle_qq, LISTEN_HOST, LISTEN_PORT_QQ):
                await asyncio.Future()
        except Exception as e:
            log_err(f"重启:{e}")
        finally:
            hb.cancel()
            cyc.cancel()
            if api_runner:
                try:
                    await api_runner.cleanup()
                except:
                    pass
            await asyncio.sleep(5)
