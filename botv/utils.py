# 通用工具函数
import base64
from .config import create_http_session
from .log import log_api

def download_url(url):
    if not url: return None
    s=create_http_session()
    try:
        r=s.get(url,timeout=(5,10),verify=False); r.raise_for_status(); return r.content
    except Exception as e: log_api(f"下载失败:{e}"); return None
    finally: s.close()

def encode_image_base64(d):
    try: return base64.b64encode(d).decode()[:150000]
    except: return ""
