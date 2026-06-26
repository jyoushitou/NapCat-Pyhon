# ===================== 通用工具模块 =====================
# 网络下载、Base64编码、图片消息构建、AI回复解析

import os, base64
from .config import create_http_session
from .log import log_api

# 默认请求头，模拟浏览器访问，避免403
DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Referer": "https://www.google.com/"
}

def download_url(url):
    """下载URL内容，返回二进制数据，失败返回None"""
    if not url:
        log_api(f"[下载] URL为空")
        return None
    s=create_http_session()  # 创建带连接池的会话
    try:
        log_api(f"[下载] 开始下载: {url[:80]}")
        r=s.get(url,timeout=(5,10),verify=False,headers=DEFAULT_HEADERS)  # 5秒连接超时，10秒读取超时，添加浏览器UA头避免403
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
    if not ans:  # 安全处理None或空字符串
        return "嗯嗯", "", [], "", []
    # 清理AI回复中的特殊标记（[sticker]等），避免被当作文本发送
    cleaned = ans.replace("[sticker]", "").replace("[Sticker]", "").replace("[STICKER]", "").strip()
    lines = [l.strip() for l in cleaned.split('\n') if l.strip()]
    if not lines:  # 清理后没有内容
        return "嗯嗯", "", [], "", []
    
    dialog = lines[0]  # 第一行：对话
    action = ""  # 动作描写
    img_kw = []  # 图片搜索关键词列表
    event = ""  # 事件摘要
    refined_kw = []  # AI提炼的关键词
    
    # 遍历所有行，按前缀标记分类解析
    # 第二行及之后：先找动作行（以（开头），再找带标记的行
    found_img_tag = False
    extra_dialogs = []  # 额外的对话内容（没有标记的中间行）
    
    for i, line in enumerate(lines[1:], 1):
        if "关键词搜索图片用" in line:
            kw_part = line.split("：")[-1].split(":")[-1].strip()
            # 支持中文顿号、逗号、空格、全角空格分隔
            img_kw = [k.strip() for k in kw_part.replace("，"," ").replace(","," ").replace("、"," ").replace("　"," ").replace("  "," ").split() if k.strip()]
            found_img_tag = True
        elif "事件摘要" in line:
            event = line.split("：")[-1].split(":")[-1].strip()
            if "|" in event:
                event = event.split("|")[0].strip()
        elif "关键词提炼" in line:
            kw_part = line.split("：")[-1].split(":")[-1].strip()
            # 支持中文顿号、逗号、空格、全角空格分隔
            refined_kw = [k.strip() for k in kw_part.replace("，"," ").replace(","," ").replace("、"," ").replace("　"," ").replace("  "," ").split() if k.strip()]
        elif line.startswith("（") or line.startswith("("):
            # 动作描写行（以括号开头），只取第一个动作行
            if not action:
                action = line
        else:
            # 没有标记的普通行，且不是动作行，收集为额外对话
            extra_dialogs.append(line)
    
    # 如果没有找到带标记的关键词行，尝试用第三行兜底
    if not found_img_tag and len(lines) > 2:
        third_line = lines[2]
        # 排除明显不是关键词的行
        if third_line and not third_line.startswith("事件") and not third_line.startswith("关键词") and not third_line.startswith("（") and not third_line.startswith("("):
            # 支持中文顿号、逗号、空格、全角空格分隔
            img_kw = [k.strip() for k in third_line.replace("，"," ").replace(","," ").replace("、"," ").replace("　"," ").replace("  "," ").split() if k.strip()]
    
    # 如果有多行额外对话，追加到dialog后面
    if extra_dialogs:
        dialog = dialog + "\n" + "\n".join(extra_dialogs)
    
    if action in ("（无）","(无)","无"):
        action = ""  # 空动作视为无动作
    return dialog, action, img_kw, event, refined_kw
