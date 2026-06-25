# ===================== 日志模块 =====================
# 五级日志系统：系统/接收/发送/接口/异常，控制台+数据库双写

from datetime import datetime
from .config import CST

def get_db_writer():
    """延迟导入db模块，避免循环依赖"""
    from .db import write_log_to_db
    return write_log_to_db

def log_system(m):
    """系统级日志：初始化、定时任务、状态变更等"""
    print(f"【系统】{datetime.now().strftime('%H:%M:%S')}|{m}")
    get_db_writer()("系统",m)

def log_recv(m):
    """接收日志：收到的QQ消息"""
    print(f"【接收】{datetime.now().strftime('%H:%M:%S')}|{m}")
    get_db_writer()("接收",m)

def log_send(m):
    """发送日志：发送的消息内容"""
    print(f"【发送】{datetime.now().strftime('%H:%M:%S')}|{m}")
    get_db_writer()("发送",str(m))

def log_api(m):
    """接口日志：API调用、图片处理、CLIP分析等"""
    print(f"【接口】{datetime.now().strftime('%H:%M:%S')}|{m}")
    get_db_writer()("接口",m)

def log_err(m):
    """异常日志：捕获到的错误和异常"""
    print(f"【异常】{datetime.now().strftime('%H:%M:%S')}|{m}")
    get_db_writer()("异常",m)

def get_recent_logs(limit=20):
    """从数据库获取最近日志（用于!log命令）"""
    try:
        from .db import get_cursor
        c = get_cursor()
        c.execute("SELECT level, message, created_at FROM logs ORDER BY id DESC LIMIT %s", (limit,))
        rows = c.fetchall()
        if not rows:
            return "暂无日志记录"
        lines = []
        for r in reversed(rows):  # 反转使时间正序
            lines.append(f"[{r['created_at']}] [{r['level']}] {r['message']}")
        return "\n".join(lines)
    except Exception as e:
        return f"获取日志失败: {e}"
