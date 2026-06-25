# 通用工具函数
import os, base64
from .config import create_http_session
from .log import log_api

def download_url(url):
    if not url:
        log_api(f"[下载] URL为空")
        return None
    s=create_http_session()
    try:
        log_api(f"[下载] 开始下载: {url[:80]}")
        r=s.get(url,timeout=(5,10),verify=False); r.raise_for_status()
        log_api(f"[下载] 成功: {len(r.content)} bytes")
        return r.content
    except Exception as e:
        log_api(f"[下载] 失败: {e}")
        return None
    finally: s.close()

def encode_image_base64(d):
    try: return "base64://" + base64.b64encode(d).decode()
    except: return ""

def make_image_msg(filepath):
    """统一将本地图片路径转为 NapCat 图片消息体，返回 [{"type":"image","data":{"file":"file:///..."}}] 或 None"""
    if not filepath or not os.path.exists(filepath):
        return None
    abs_path = os.path.abspath(filepath)
    return [{"type":"image","data":{"file":f"file:///{abs_path}"}}]

def parse_ai_reply(ans):
    """解析AI回复的五行格式，返回(dialog, action, img_kw, event, refined_kw)"""
    lines = [l.strip() for l in ans.split('\n') if l.strip()]
    dialog = lines[0] if len(lines) > 0 else ans
    action = lines[1] if len(lines) > 1 else ""
    img_kw = []
    event = ""
    refined_kw = []
    # 先尝试按带前缀标记的方式解析
    found_img_tag = False
    for line in lines[2:]:
        if "关键词搜索图片用" in line:
            kw_part = line.split("：")[-1].split(":")[-1].strip()
            img_kw = [k.strip() for k in kw_part.replace("，"," ").replace(","," ").split() if k.strip()]
            found_img_tag = True
        elif "事件摘要" in line:
            event = line.split("：")[-1].split(":")[-1].strip()
            if "|" in event:
                event = event.split("|")[0].strip()
        elif "关键词提炼" in line:
            kw_part = line.split("：")[-1].split(":")[-1].strip()
            refined_kw = [k.strip() for k in kw_part.replace("，"," ").replace(","," ").split() if k.strip()]
    # 如果没有带前缀标记，则把第三行（lines[2]）当作图片关键词兜底
    # 前提是第三行不是事件摘要/关键词提炼等标记行
    if not found_img_tag and len(lines) > 2:
        third_line = lines[2]
        # 排除明显不是关键词的行
        if third_line and not third_line.startswith("事件") and not third_line.startswith("关键词") and not third_line.startswith("（") and not third_line.startswith("("):
            img_kw = [k.strip() for k in third_line.replace("，"," ").replace(","," ").split() if k.strip()]
    if action in ("（无）","(无)","无"):
        action = ""
    return dialog, action, img_kw, event, refined_kw
