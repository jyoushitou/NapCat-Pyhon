# 日志系统
from datetime import datetime
from .config import CST

def get_db_writer():
    from .db import write_log_to_db
    return write_log_to_db

def log_system(m): 
    print(f"【系统】{datetime.now().strftime('%H:%M:%S')}|{m}")
    get_db_writer()("系统",m)

def log_recv(m): 
    print(f"【接收】{datetime.now().strftime('%H:%M:%S')}|{m}")
    get_db_writer()("接收",m)

def log_send(m): 
    print(f"【发送】{datetime.now().strftime('%H:%M:%S')}|{m}")
    get_db_writer()("发送",str(m))

def log_api(m): 
    print(f"【接口】{datetime.now().strftime('%H:%M:%S')}|{m}")
    get_db_writer()("接口",m)

def log_err(m): 
    print(f"【异常】{datetime.now().strftime('%H:%M:%S')}|{m}")
    get_db_writer()("异常",m)

def get_recent_logs(limit=20):
    """从数据库获取最近日志"""
    try:
        from .db import get_cursor
        c = get_cursor()
        c.execute("SELECT level, message, created_at FROM logs ORDER BY id DESC LIMIT %s", (limit,))
        rows = c.fetchall()
        if not rows:
            return "暂无日志记录"
        lines = []
        for r in reversed(rows):
            lines.append(f"[{r['created_at']}] [{r['level']}] {r['message']}")
        return "\n".join(lines)
    except Exception as e:
        return f"获取日志失败: {e}"
