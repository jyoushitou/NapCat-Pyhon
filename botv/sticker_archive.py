# ===================== 旧表情包存档兼容层 =====================
# 兼容旧版 sticker_archive 的JSON索引文件，启动时自动迁移到新数据库

import os  # 文件路径操作
import json  # JSON读写
from collections import defaultdict  # 默认字典（未使用但保留）

from .config import STICKER_ARCHIVE_DIR, MAX_USER_STICKERS  # 存档目录配置
import botv.config as cfg  # 全局运行时变量
from .db import get_cursor  # 数据库游标
from .log import log_system, log_err  # 日志
from .image import save_image_to_db  # 图片入库


def init_sticker_archive():
    """初始化表情包存档目录，加载旧存档"""
    if not os.path.exists(STICKER_ARCHIVE_DIR):  # 存档目录不存在
        os.makedirs(STICKER_ARCHIVE_DIR)  # 创建目录
    load_sticker_archive()  # 加载旧存档


def load_sticker_archive():
    """加载旧版 sticker_index.json，迁移到新数据库"""
    ip = os.path.join(STICKER_ARCHIVE_DIR, "sticker_index.json")  # 旧索引文件路径
    if not os.path.exists(ip):  # 索引文件不存在
        return  # 直接返回
    try:
        with open(ip, "r", encoding="utf-8") as f:  # 打开索引文件
            d = json.load(f)  # 解析JSON
        for uid, hs in d.get("user_stickers", {}).items():  # 遍历用户收藏
            cfg.USER_STICKER_ARCHIVE[uid] = hs  # 加载到全局变量
        for h, info in d.get("stickers", {}).items():  # 遍历表情包数据
            cfg.STICKER_DATA[h] = {  # 加载到全局变量
                "type": info["type"],  # 类型
                "data": None,  # 二进制数据（延迟加载）
                "tags": info["tags"],  # 标签
                "desc": info["desc"],  # 描述
                "use_count": info["use_count"],  # 使用次数
                "users": set(info["users"]),  # 使用过的用户集合
            }
            try:
                c = get_cursor()  # 获取数据库游标
                c.execute("SELECT id FROM images WHERE md5_hash=%s", (h,))  # 检查是否已入库
                if not c.fetchone():  # 未入库
                    fp = os.path.join(STICKER_ARCHIVE_DIR, f"{h}.jpg")  # 旧文件路径
                    with open(fp, "rb") as f:  # 读取图片文件
                        img_data = f.read()  # 读取二进制数据
                    tags_str = ",".join(info["tags"])  # 标签列表转字符串
                    save_image_to_db(h, img_data, tags_str)  # 迁移到新库
                    log_system(f"旧存档迁移: {h[:12]}")  # 日志记录
            except:
                pass  # 迁移失败不影响
        log_system(f"存档案: {len(cfg.STICKER_DATA)}个+已迁入新库")  # 日志统计
    except Exception as e:
        log_err(f"加载存档失败: {e}")  # 加载失败记录错误


def save_sticker_archive():
    """保存表情包存档到JSON索引文件（兼容旧版）"""
    try:
        d = {  # 构建存档数据
            "user_stickers": {k: list(v) for k, v in cfg.USER_STICKER_ARCHIVE.items()},  # 用户收藏
            "stickers": {},  # 表情包数据
        }
        for h, info in cfg.STICKER_DATA.items():  # 遍历表情包
            d["stickers"][h] = {  # 构建每条记录
                "type": info["type"],  # 类型
                "tags": info["tags"],  # 标签
                "desc": info["desc"],  # 描述
                "use_count": info["use_count"],  # 使用次数
                "users": list(info["users"]),  # 用户列表
            }
        with open(os.path.join(STICKER_ARCHIVE_DIR, "sticker_index.json"), "w", encoding="utf-8") as f:  # 写入文件
            json.dump(d, f, ensure_ascii=False, indent=2)  # 格式化写入
    except Exception as e:
        log_err(f"保存失败: {e}")  # 保存失败记录错误
