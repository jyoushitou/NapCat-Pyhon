# ===================== 主程序入口 =====================
# 初始化所有模块，启动 WebSocket 服务器和 HTTP API 服务器
# 管理心跳监控和定时任务，异常时自动重启

import asyncio  # 异步 IO：协程和任务管理
import websockets  # WebSocket 服务器库：接收 QQ 消息

from .config import LISTEN_HOST, LISTEN_PORT_QQ  # 监听地址和端口
import botv.config as cfg  # 全局运行时变量
from .log import log_system, log_err  # 日志
from .db import reload_api_keys, get_cursor  # 数据库：重新加载 API 密钥、获取游标
from .memory import load_memories  # 加载对话记忆
from .sticker_archive import init_sticker_archive  # 初始化表情包存档
from .clip import init_clip_model  # 初始化 CLIP 模型
from .personality import load_personality_supplement  # 加载人设补充
from .heartbeat import heartbeat_monitor  # 心跳监控
from .schedule import cycle_task_run, CHINESE_CALENDAR_OK  # 定时任务循环、农历日历状态
from .handler import websocket_handle_qq  # WebSocket 消息处理函数
from .api_server import start_api_server  # HTTP API 服务器


async def main():
    """主函数：初始化各模块，启动 WebSocket 服务器，异常时自动重启
    
    启动流程：
        1. 加载对话记忆和全局关键词
        2. 初始化表情包存档（兼容旧版 JSON 索引）
        3. 加载 CLIP 模型（可选，失败不影响运行）
        4. 从数据库加载 API 密钥
        5. 加载人设补充文本
        6. 检查并升级数据库表结构
        7. 启动 HTTP API 服务器
        8. 进入主循环：启动心跳 + 定时任务 + WebSocket 服务器
    """
    # ===================== 初始化各模块 =====================
    load_memories()  # 从数据库加载对话记忆和全局关键词到内存
    init_sticker_archive()  # 初始化表情包存档目录，迁移旧版 JSON 索引
    init_clip_model()  # 加载 CLIP 模型（CPU），失败不影响运行
    reload_api_keys()  # 从数据库重新加载所有 API 密钥
    load_personality_supplement()  # 加载人设补充文本（远程 > 本地）
    
    # 确保 ACG 图片表存在（用于缓存 ACG 二次元图片）
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
    
    # 确保 ai_raw_responses 表有 token 用量字段（数据库迁移）
    try:
        c = get_cursor()
        c.execute("SHOW COLUMNS FROM ai_raw_responses LIKE 'prompt_tokens'")
        if not c.fetchone():  # 字段不存在，执行迁移
            c.execute("ALTER TABLE ai_raw_responses ADD COLUMN prompt_tokens INT DEFAULT 0")
            c.execute("ALTER TABLE ai_raw_responses ADD COLUMN completion_tokens INT DEFAULT 0")
            c.execute("ALTER TABLE ai_raw_responses ADD COLUMN total_tokens INT DEFAULT 0")
            c.connection.commit()
            log_system("ai_raw_responses 表已升级，添加token用量字段")
        else:
            log_system("ai_raw_responses 表token字段已存在")
    except Exception as e:
        log_err(f"升级ai_raw_responses表失败: {e}")
    
    cfg.PROCESS_LOCK = asyncio.Lock()  # 初始化消息处理锁（防止并发处理消息）
    log_system("初始化完成(CLIP识图版)")
    
    # ===================== 启动 API 服务器 =====================
    try:
        api_runner = await start_api_server()  # 启动 HTTP API 服务器
        log_system("API 服务器已启动")
    except Exception as e:
        log_err(f"API 服务器启动失败: {e}")
        api_runner = None  # API 服务器启动失败不影响主流程
    
    # ===================== 主循环 =====================
    while True:
        hb = asyncio.create_task(heartbeat_monitor("QQ", cfg.active_ws_qq))  # 启动心跳监控
        cyc = asyncio.create_task(cycle_task_run())  # 启动定时任务循环
        try:
            async with websockets.serve(websocket_handle_qq, LISTEN_HOST, LISTEN_PORT_QQ):  # 启动 WebSocket 服务器
                await asyncio.Future()  # 保持运行直到被取消
        except Exception as e:
            log_err(f"重启:{e}")  # 异常时记录日志并自动重启
        finally:
            hb.cancel()  # 取消心跳任务
            cyc.cancel()  # 取消定时任务
            if api_runner:  # 清理 API 服务器
                try:
                    await api_runner.cleanup()
                except:
                    pass
            await asyncio.sleep(5)  # 等待 5 秒后重启
