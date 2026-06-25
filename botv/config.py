# ===================== 配置模块 =====================
# 所有常量、API地址、TOKEN、CLIP标签、全局运行时变量集中管理

import os, random, asyncio  # 标准库
from collections import deque, defaultdict  # 双端队列（消息去重）、默认字典
from requests.adapters import HTTPAdapter  # requests 连接适配器
import requests, urllib3  # HTTP请求库、SSL警告抑制
from datetime import timedelta, timezone, date  # 时区、日期处理

CST = timezone(timedelta(hours=8))  # 东八区（北京时间）
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)  # 禁用SSL警告

def create_http_session():
    """创建带连接池的HTTP会话，不重试"""
    s=requests.Session()  # 创建会话
    s.mount("https://",HTTPAdapter(max_retries=0))  # HTTPS挂载适配器，不重试
    s.mount("http://",HTTPAdapter(max_retries=0))  # HTTP挂载适配器，不重试
    return s

# ===================== 配置常量 =====================
MASTER_QQ=822891053  # 主人QQ号（只有此QQ能使用!命令）
LISTEN_HOST="0.0.0.0"  # WebSocket监听地址（所有网卡）
LISTEN_PORT_QQ=3001  # WebSocket监听端口（NapCat连接此端口）
HEARTBEAT_INTERVAL=15  # 心跳间隔（秒）
API_RETRY_DELAY=1.5  # API调用失败重试延迟（秒）
MAX_RETRY_TIMES=3  # API最大重试次数
PROCESSED_MSG_IDS=deque(maxlen=80)  # 已处理消息ID缓存（去重，最多80条）
PROCESS_LOCK=None  # 消息处理锁（在main.py中初始化）
LOCK_RELEASE_DELAY=0.8  # 锁释放延迟（秒）
DS_API_KEY=DOUBAO_API_KEY=STICKER_API_ALAPI_TOKEN=""  # API密钥（从数据库加载）
DS_API_URL="https://api.deepseek.com/v1/chat/completions"  # DeepSeek API地址
DS_MODEL="deepseek-v4-flash"  # DeepSeek模型名
DS_TIMEOUT=60  # DeepSeek超时（秒）
DOUBAO_API_URL="https://ark.cn-beijing.volces.com/api/v3/chat/completions"  # 豆包API地址
DOUBAO_MODEL="ep-20260524110944-g7vqr"  # 豆包模型名
DOUBAO_TIMEOUT=60  # 豆包超时（秒）
STICKER_KEYWORDS=["表情包","发个表情","来个表情","给我表情","要表情包","表情"]  # 触发表情包回复的关键词
STICKER_FACE_IDS=[14,91,99,176,179,183,196,202,211]  # QQ表情ID列表（兜底用）
STICKER_ARCHIVE_DIR="sticker_archive"  # 旧表情包存档目录
MAX_USER_STICKERS=30  # 每个用户最大收藏表情包数
IMAGE_DIR="images"  # 新图片存储目录
MAX_USER_ROUND = 15  # 每个用户最大对话记忆轮数
MAX_GLOBAL_KEY = 40  # 全局关键词最大数量

DB_CONFIG = {"host":"192.168.0.50","port":3306,"user":"TomoriNaoBot",  # MySQL数据库配置
             "password":"TNB","database":"TomoriNaoBotData","charset":"utf8mb4"}

CLIP_IMAGE_TAGS = [
    # === 表情包常用（20个标签） ===
    "表情包","沙雕图","搞笑","魔性","鬼畜","燃","生草","生草","生草","生草",
    "流汗","抠鼻","点赞","比心","666","笑哭","无语","懵逼","嫌弃","得意",
    "惊讶","吐槽","中二","狗头","熊猫头","黄豆脸","滑稽","阴险","抠脚","躺平",
    # === 可爱系（30个标签） ===
    "可爱","萌","软萌","治愈","温馨","软乎乎","毛茸茸","圆圆","粉嫩","闪亮",
    "微笑","撒娇","害羞","脸红","嘟嘴","眨眼","歪头","抱抱","摸摸头","蹭蹭",
    "猫","猫猫","猫咪","小狗","狗狗","兔兔","仓鼠","松鼠","熊猫","考拉",
    "水獭","刺猬","企鹅","海豹","羊驼","鹿","狐狸","熊","树懒","龙猫",
    # === 二次元（30个标签） ===
    "二次元","动漫","漫画","手绘","赛璐璐","厚涂","像素风","Q版","同人","原画",
    "少女","萝莉","正太","御姐","哥特","和服","校服","泳装","猫耳","女仆",
    "眼罩","呆毛","双马尾","单马尾","长发","短发","眼镜娘","兽耳","尾巴","翅膀",
    # === 场景/背景（20个标签） ===
    "风景","天空","夕阳","夜景","大海","沙滩","樱花","枫叶","雪景","星空",
    "城市","街道","乡村","森林","山","花田","彩虹","云朵","光影","剪影",
    # === 食物（20个标签） ===
    "食物","甜品","蛋糕","冰淇淋","奶茶","咖啡","水果","草莓","西瓜","桃子",
    "面包","饼干","棒棒糖","棉花糖","布丁","果冻","甜甜圈","马卡龙","泡芙","巧克力",
    # === 日常（20个标签） ===
    "自拍","合照","截图","壁纸","插画","海报","贴纸","头像","背景","模板",
    "早安","晚安","加油","谢谢","对不起","你好","再见","哈哈","呜呜","摸摸",
    # === 其他补充（60个标签） ===
    "文字","动图","纯色","黑白","手写","涂鸦","水彩","油画","水墨","剪纸",
    "真人","美女","帅哥","情侣","闺蜜","兄弟","全家福","宠物","萌娃","老人",
    "旅行","露营","骑行","跑步","跳舞","唱歌","画画","摄影","看书","睡觉",
    "游戏","电脑","手机","键盘","鼠标","手柄","街机","像素","RPG","FPS",
    "生日","圣诞","新年","万圣","情人节","下雨","彩虹","烟花","气球","礼物"
]  # CLIP打标候选标签列表（共约200个）

# ===================== 全局运行时变量 =====================
active_ws_qq=None  # 当前活跃的QQ WebSocket连接
active_ws_lock=asyncio.Lock()  # WebSocket连接锁（防止多连接冲突）
daily_trigger=set()  # 今日已触发的定时任务key集合
today=date.today()  # 当前日期
daily_chat_trigger_times=[]  # 今日闲聊触发时间点列表
triggered_today=set()  # 今日已触发的闲聊时间点
send_lock=asyncio.Lock()  # 消息发送锁（防止WebSocket发送冲突）
task_trigger_minute={}  # 定时任务触发分钟映射 {key: minute}
user_memory_pool={}  # 用户对话记忆池 {target_id: deque}
global_keyword_set=set()  # 全局关键词集合
USER_STICKER_CACHE=defaultdict(list)  # 用户最近使用的QQ表情缓存
USER_STICKER_ARCHIVE=defaultdict(list)  # 用户旧表情包存档
STICKER_DATA={}  # 表情包数据 {hash: info_dict}
