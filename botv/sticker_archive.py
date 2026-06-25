# 旧 sticker_archive 兼容层
import os, json
from collections import defaultdict
from .config import STICKER_ARCHIVE_DIR, MAX_USER_STICKERS
import botv.config as cfg
from .db import get_cursor
from .log import log_system, log_err
from .image import save_image_to_db

def init_sticker_archive():
    if not os.path.exists(STICKER_ARCHIVE_DIR): os.makedirs(STICKER_ARCHIVE_DIR)
    load_sticker_archive()

def load_sticker_archive():
    ip = os.path.join(STICKER_ARCHIVE_DIR, "sticker_index.json")
    if not os.path.exists(ip):
        return
    try:
        with open(ip, "r", encoding="utf-8") as f:
            d = json.load(f)
        for uid, hs in d.get("user_stickers", {}).items():
            cfg.USER_STICKER_ARCHIVE[uid] = hs
        for h, info in d.get("stickers", {}).items():
            cfg.STICKER_DATA[h] = {
                "type": info["type"],
                "data": None,
                "tags": info["tags"],
                "desc": info["desc"],
                "use_count": info["use_count"],
                "users": set(info["users"]),
            }
            try:
                c = get_cursor()
                c.execute("SELECT id FROM images WHERE md5_hash=%s", (h,))
                if not c.fetchone():
                    fp = os.path.join(STICKER_ARCHIVE_DIR, f"{h}.jpg")
                    with open(fp, "rb") as f:
                        img_data = f.read()
                    tags_str = ",".join(info["tags"])
                    save_image_to_db(h, img_data, tags_str)
                    log_system(f"旧存档迁移: {h[:12]}")
            except:
                pass
        log_system(f"存档案: {len(cfg.STICKER_DATA)}个+已迁入新库")
    except Exception as e:
        log_err(f"加载存档失败: {e}")

def save_sticker_archive():
    try:
        d = {
            "user_stickers": {k: list(v) for k, v in cfg.USER_STICKER_ARCHIVE.items()},
            "stickers": {},
        }
        for h, info in cfg.STICKER_DATA.items():
            d["stickers"][h] = {
                "type": info["type"],
                "tags": info["tags"],
                "desc": info["desc"],
                "use_count": info["use_count"],
                "users": list(info["users"]),
            }
        with open(os.path.join(STICKER_ARCHIVE_DIR, "sticker_index.json"), "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False, indent=2)
    except Exception as e:
        log_err(f"保存失败: {e}")
