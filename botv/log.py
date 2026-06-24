# 日志系统
from datetime import datetime
from .config import CST
from .db import write_log_to_db

def log_system(m): print(f"【系统】{datetime.now().strftime('%H:%M:%S')}|{m}"); write_log_to_db("系统",m)
def log_recv(m): print(f"【接收】{datetime.now().strftime('%H:%M:%S')}|{m}"); write_log_to_db("接收",m)
def log_send(m): print(f"【发送】{datetime.now().strftime('%H:%M:%S')}|{m}"); write_log_to_db("发送",str(m))
def log_api(m): print(f"【接口】{datetime.now().strftime('%H:%M:%S')}|{m}"); write_log_to_db("接口",m)
def log_err(m): print(f"【异常】{datetime.now().strftime('%H:%M:%S')}|{m}"); write_log_to_db("异常",m)
