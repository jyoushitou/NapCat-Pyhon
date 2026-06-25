# ===================== 通用工具模块 =====================
# 网络下载、Base64编码、图片消息构建、AI回复解析

import os, base64
from .config import create_http_session
from .log import log_api

def download_url(url):
    """下载URL内容，返回二进制数据，失败返回None"""
    if not url:
        log_api(f"[下载] URL为空")
        return None
    s=create_http_session()  # 创建带连接池的会话
    try:
        log_api(f"[下载] 开始下载: {url[:80]}")
        r=s.get(url,timeout=(5,10),verify=False)  # 5秒连接超时，10秒读取超时
        r.raise_for_status()  # 检查HTTP状态码
        log_api(f"[下载] 成功: {len(r.content)} bytes")
        return r.content
    except Exception as e:
        log_api(f"[下载] 失败: {e}")
        return None
    finally:
        s.close()  # 关闭会话

def encode_image_base64(d):
    """将二进制图片数据编码为NapCat的base64格式"""
    try:
        return "base64://" + base64.b64encode(d).decode()
    except:
        return ""

def make_image_msg(filepath):
    """统一将本地图片路径转为 NapCat 图片消息体
    返回 [{"type":"image","data":{"file":"绝对路径"}}] 或 None"""
    if not filepath or not os.path.exists(filepath):
        return None
    abs_path = os.path.abspath(filepath)  # 转为绝对路径
    return [{"type":"image","data":{"file":abs_path}}]

def parse_ai_reply(ans):
    """解析AI回复的五行格式
    返回 (dialog, action, img_kw, event, refined_kw)
    格式：
      第一行：对话内容
      第二行：动作描写（如（扭头））
      第三行：关键词搜索图片用：词1 词2 ...（20个纬度）
      第四行：事件摘要：xxx
      第五行：关键词提炼：词1 词2 ..."""
    lines = [l.strip() for l in ans.split('\n') if l.strip()]
    dialog = lines[0] if len(lines) > 0 else ans  # 第一行：对话
    action = lines[1] if len(lines) > 1 else ""  # 第二行：动作
    img_kw = []  # 图片搜索关键词列表
    event = ""  # 事件摘要
    refined_kw = []  # AI提炼的关键词
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
    # 如果没有带前缀标记，则把第三行当作图片关键词兜底
    if not found_img_tag and len(lines) > 2:
        third_line = lines[2]
        # 排除明显不是关键词的行
        if third_line and not third_line.startswith("事件") and not third_line.startswith("关键词") and not third_line.startswith("（") and not third_line.startswith("("):
            img_kw = [k.strip() for k in third_line.replace("，"," ").replace(","," ").split() if k.strip()]
    if action in ("（无）","(无)","无"):
        action = ""  # 空动作视为无动作
    return dialog, action, img_kw, event, refined_kw
