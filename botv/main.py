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


async def main():
    """主函数：初始化各模块，启动WebSocket服务器，异常时自动重启"""
    # ===================== 初始化各模块 =====================
    load_memories()  # 从数据库加载对话记忆和全局关键词
    init_sticker_archive()  # 初始化旧表情包存档（迁移到新库）
    init_clip_model()  # 加载CLIP视觉模型（CPU模式）
    reload_api_keys()  # 从数据库重新加载API密钥
    load_personality_supplement()  # 从远程URL加载人设补充
    
    # 确保 ACG 图片表存在（兼容旧版）
    try:
        c = get_cursor()  # 获取数据库游标
        c.execute("""
            CREATE TABLE IF NOT EXISTS acg_images (  # 创建ACG图片表（如果不存在）
                id INT AUTO_INCREMENT PRIMARY KEY,  # 自增主键
                md5_hash VARCHAR(32) NOT NULL UNIQUE,  # MD5哈希（唯一）
                image_data MEDIUMBLOB,  # 图片二进制数据
                tags VARCHAR(255) DEFAULT '',  # 标签
                source_url VARCHAR(512) DEFAULT '',  # 来源URL
                file_path VARCHAR(255) DEFAULT '',  # 本地文件路径
                ext VARCHAR(10) DEFAULT 'jpg',  # 文件扩展名
                use_count INT DEFAULT 0,  # 使用次数
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP  # 创建时间
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4  # InnoDB引擎，UTF8MB4编码
        """)
        c.connection.commit()  # 提交事务
        log_system("acg_images 表已就绪")  # 日志记录
    except Exception as e:
        log_err(f"建表失败: {e}")  # 建表失败记录错误
    
    cfg.PROCESS_LOCK = asyncio.Lock()  # 初始化消息处理锁（防止并发处理同一条消息）
    log_system("初始化完成(CLIP识图版)")  # 日志记录初始化完成
    
    # ===================== 主循环 =====================
    while True:  # 无限循环，异常时自动重启
        hb = asyncio.create_task(heartbeat_monitor("QQ", cfg.active_ws_qq))  # 创建心跳监控任务
        cyc = asyncio.create_task(cycle_task_run())  # 创建定时任务循环
        try:
            async with websockets.serve(websocket_handle_qq, LISTEN_HOST, LISTEN_PORT_QQ):  # 启动WebSocket服务器
                await asyncio.Future()  # 保持运行直到被取消
        except Exception as e:  # 捕获异常
            log_err(f"重启:{e}")  # 日志记录异常并准备重启
        finally:
            hb.cancel()  # 取消心跳任务
            cyc.cancel()  # 取消定时任务
            await asyncio.sleep(5)  # 等待5秒后重启
