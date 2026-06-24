# 配置：所有常量、API地址、TOKEN 集中管理
import os, random, asyncio
from collections import deque, defaultdict
from requests.adapters import HTTPAdapter
import requests, urllib3
from datetime import timedelta, timezone, date

CST = timezone(timedelta(hours=8))
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

def create_http_session():
    s=requests.Session(); s.mount("https://",HTTPAdapter(max_retries=0)); s.mount("http://",HTTPAdapter(max_retries=0)); return s

# ===================== 配置常量 =====================
MASTER_QQ=822891053; LISTEN_HOST="0.0.0.0"; LISTEN_PORT_QQ=3001
HEARTBEAT_INTERVAL=15; API_RETRY_DELAY=1.5; MAX_RETRY_TIMES=3
PROCESSED_MSG_IDS=deque(maxlen=80); PROCESS_LOCK=None; LOCK_RELEASE_DELAY=0.8
DS_API_KEY=DOUBAO_API_KEY=SEARCH_STICKER_KEY=STICKER_API_ALAPI_TOKEN=""
DS_API_URL="https://api.deepseek.com/v1/chat/completions"; DS_MODEL="deepseek-v4-flash"; DS_TIMEOUT=60
DOUBAO_API_URL="https://ark.cn-beijing.volces.com/api/v3/chat/completions"
DOUBAO_MODEL="ep-20260524110944-g7vqr"; DOUBAO_TIMEOUT=60
STICKER_KEYWORDS=["表情包","发个表情","来个表情","给我表情","要表情包","表情"]
STICKER_FACE_IDS=[14,91,99,176,179,183,196,202,211]
STICKER_ARCHIVE_DIR="sticker_archive"
MAX_USER_STICKERS=30
IMAGE_DIR="images"

CLIP_IMAGE_TAGS = ["表情包","二次元","动漫","真人","美女","帅哥","动物","猫","狗","食物","风景","沙雕图","搞笑","可爱","帅气","悲伤","生气","开心","懵逼","无语","流汗","抠鼻","点赞","比心","晚安","早安","加油","谢谢","对不起","666","笑哭","截图","自拍","合照","游戏截图","漫画","文字","动图","纯色","黑白"]

# ===================== 全局运行时变量 =====================
active_ws_qq=None
active_ws_lock=asyncio.Lock()
daily_trigger=set(); today=date.today()
daily_chat_trigger_times=[]; triggered_today=set()
send_lock=asyncio.Lock(); task_trigger_minute={}
user_memory_pool={}; global_keyword_set=set()
USER_STICKER_CACHE=defaultdict(list)
USER_STICKER_ARCHIVE=defaultdict(list)
STICKER_DATA={}
