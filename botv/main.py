# 主程序入口
import asyncio, websockets
from .config import LISTEN_HOST, LISTEN_PORT_QQ, active_ws_qq, PROCESS_LOCK
from .log import log_system, log_err
from .db import reload_api_keys
from .memory import load_memories
from .sticker_archive import init_sticker_archive
from .clip import init_clip_model, CLIP_ENABLED
from .personality import load_personality_supplement
from .heartbeat import heartbeat_monitor
from .schedule import cycle_task_run, CHINESE_CALENDAR_OK
from .handler import websocket_handle_qq

async def main():
    global PROCESS_LOCK
    load_memories(); init_sticker_archive(); init_clip_model(); reload_api_keys(); load_personality_supplement()
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
                use_count INT DEFAULT 0,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """)
        c.connection.commit()
        log_system("acg_images 表已就绪")
    except Exception as e:
        log_err(f"建表失败: {e}")
    PROCESS_LOCK=asyncio.Lock()
    log_system("初始化完成(CLIP识图版)")
    while True:
        hb=asyncio.create_task(heartbeat_monitor("QQ",active_ws_qq))
        cyc=asyncio.create_task(cycle_task_run())
        try:
            async with websockets.serve(websocket_handle_qq,LISTEN_HOST,LISTEN_PORT_QQ):
                await asyncio.Future()
        except Exception as e:
            log_err(f"重启:{e}")
        finally:
            hb.cancel(); cyc.cancel()
            await asyncio.sleep(5)
