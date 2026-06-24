# 人设系统
from .config import CST
from .log import log_system, log_api

# 本地基础人设
LOCAL_SYSTEM_PROMPT = """
人物出处：动漫《Charlotte夏洛特》
姓名：友利奈绪
年龄：15岁
身份：星之海学园学生会会长
专属异能：掠夺

核心性格：傲娇毒舌、外冷内热、护短、天然呆萌、敏感缺爱
说话风格：吐槽式关心、别扭温柔、少女语气、不讨好、不煽情

聊天规则：
1. 只根据当前对象的对话历史回复
2. 全局关键词是长期记忆
3. 多条回复时，第一条是对话内容，第二条是动作描写（单独一行），如：
   哼，谁理你啊
   （扭头）
4. 如果只有一条，末尾不要带动作括号

【全局长期记忆】：{global_keywords}
【与你最近的对话】：{current_dialogue}
"""

# 人设补充URL（在线拉取，备用）
PERSONALITY_SUPPLEMENT_URLS = [
    "https://raw.githubusercontent.com/your-repo/nao_personality/main/base.txt",
]

PERSONALITY_SUPPLEMENT = ""

def load_personality_supplement():
    global PERSONALITY_SUPPLEMENT
    for url in PERSONALITY_SUPPLEMENT_URLS:
        try:
            s = create_http_session()
            r = s.get(url, timeout=(5, 10), verify=False)
            if r.status_code == 200 and r.text.strip():
                PERSONALITY_SUPPLEMENT = r.text.strip()
                log_system(f"人设补充加载成功: {url}")
                return
        except Exception as e:
            log_api(f"人设补充加载失败 {url}: {e}")
        finally:
            try: s.close()
            except: pass
    log_system("人设补充未加载，使用本地人设")

def get_system_prompt():
    if PERSONALITY_SUPPLEMENT:
        return PERSONALITY_SUPPLEMENT + "\n\n" + LOCAL_SYSTEM_PROMPT
    return LOCAL_SYSTEM_PROMPT

user_memory_pool={}; global_keyword_set=set()
active_ws_qq=None
active_ws_lock=asyncio.Lock()
daily_trigger=set(); today=date.today()
daily_chat_trigger_times=[]; triggered_today=set()
send_lock=asyncio.Lock(); task_trigger_minute={}
