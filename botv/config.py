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
DS_API_KEY=DOUBAO_API_KEY=STICKER_API_ALAPI_TOKEN=""
DS_API_URL="https://api.deepseek.com/v1/chat/completions"; DS_MODEL="deepseek-v4-flash"; DS_TIMEOUT=60
DOUBAO_API_URL="https://ark.cn-beijing.volces.com/api/v3/chat/completions"
DOUBAO_MODEL="ep-20260524110944-g7vqr"; DOUBAO_TIMEOUT=60
STICKER_KEYWORDS=["表情包","发个表情","来个表情","给我表情","要表情包","表情"]
STICKER_FACE_IDS=[14,91,99,176,179,183,196,202,211]
STICKER_ARCHIVE_DIR="sticker_archive"
MAX_USER_STICKERS=30
IMAGE_DIR="images"
MAX_USER_ROUND = 15
MAX_GLOBAL_KEY = 40

DB_CONFIG = {"host":"192.168.0.50","port":3306,"user":"TomoriNaoBot",
             "password":"TNB","database":"TomoriNaoBotData","charset":"utf8mb4"}

CLIP_IMAGE_TAGS = [
    # === 表情包常用 ===
    "表情包","沙雕图","搞笑","魔性","鬼畜","燃","生草","生草","生草","生草",
    "流汗","抠鼻","点赞","比心","666","笑哭","无语","懵逼","嫌弃","得意",
    "惊讶","吐槽","中二","狗头","熊猫头","黄豆脸","滑稽","阴险","抠脚","躺平",
    # === 可爱系 ===
    "可爱","萌","软萌","治愈","温馨","软乎乎","毛茸茸","圆圆","粉嫩","闪亮",
    "微笑","撒娇","害羞","脸红","嘟嘴","眨眼","歪头","抱抱","摸摸头","蹭蹭",
    "猫","猫猫","猫咪","小狗","狗狗","兔兔","仓鼠","松鼠","熊猫","考拉",
    "水獭","刺猬","企鹅","海豹","羊驼","鹿","狐狸","熊","树懒","龙猫",
    # === 二次元 ===
    "二次元","动漫","漫画","手绘","赛璐璐","厚涂","像素风","Q版","同人","原画",
    "少女","萝莉","正太","御姐","哥特","和服","校服","泳装","猫耳","女仆",
    "眼罩","呆毛","双马尾","单马尾","长发","短发","眼镜娘","兽耳","尾巴","翅膀",
    # === 场景/背景 ===
    "风景","天空","夕阳","夜景","大海","沙滩","樱花","枫叶","雪景","星空",
    "城市","街道","乡村","森林","山","花田","彩虹","云朵","光影","剪影",
    # === 食物 ===
    "食物","甜品","蛋糕","冰淇淋","奶茶","咖啡","水果","草莓","西瓜","桃子",
    "面包","饼干","棒棒糖","棉花糖","布丁","果冻","甜甜圈","马卡龙","泡芙","巧克力",
    # === 日常 ===
    "自拍","合照","截图","壁纸","插画","海报","贴纸","头像","背景","模板",
    "早安","晚安","加油","谢谢","对不起","你好","再见","哈哈","呜呜","摸摸",
    # === 其他补充 ===
    "文字","动图","纯色","黑白","手写","涂鸦","水彩","油画","水墨","剪纸",
    "真人","美女","帅哥","情侣","闺蜜","兄弟","全家福","宠物","萌娃","老人",
    "旅行","露营","骑行","跑步","跳舞","唱歌","画画","摄影","看书","睡觉",
    "游戏","电脑","手机","键盘","鼠标","手柄","街机","像素","RPG","FPS",
    "生日","圣诞","新年","万圣","情人节","下雨","彩虹","烟花","气球","礼物"
]

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
