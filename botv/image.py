# 统一图片系统：下载→CLIP打标→本地存档→入库→按tag搜索复用
import os, hashlib, asyncio, random
from .config import STICKER_API_ALAPI_TOKEN, IMAGE_DIR, CLIP_IMAGE_TAGS
from .db import get_cursor
from .log import log_system, log_api, log_err
from .clip import analyze_image_with_clip
from .utils import download_url, create_http_session, encode_image_base64

def image_local_path(md5_hash, ext="jpg"):
    os.makedirs(IMAGE_DIR, exist_ok=True)
    return os.path.join(IMAGE_DIR, f"{md5_hash}.{ext}")

def save_image_to_db(md5_hash, img_data, tags, source_url="", uid=""):
    ext = "gif" if img_data[:6] in (b"GIF89a", b"GIF87a") else "jpg"
    fp = image_local_path(md5_hash, ext)
    try:
        c = get_cursor()
        c.execute(
            "INSERT IGNORE INTO images(md5_hash, image_data, tags, source_url, file_path, ext, use_count) VALUES(%s,%s,%s,%s,%s,%s,0)",
            (md5_hash, img_data, tags, source_url, fp, ext)
        )
        c.connection.commit()
    except Exception as e:
        log_err(f"图片入库失败: {e}")

def load_image_from_db(md5_hash):
    try:
        c = get_cursor()
        c.execute("SELECT image_data, ext FROM images WHERE md5_hash=%s", (md5_hash,))
        r = c.fetchone()
        if r:
            return r["image_data"], r["ext"]
    except:
        pass
    return None, None

def image_already_exists(md5_hash):
    try:
        c = get_cursor()
        c.execute("SELECT id, tags, file_path, ext FROM images WHERE md5_hash=%s", (md5_hash,))
        r = c.fetchone()
        if r:
            fp = r["file_path"]
            if fp and os.path.exists(fp):
                return True, r["tags"], fp
            img_data, ext = load_image_from_db(md5_hash)
            if img_data:
                fp = image_local_path(md5_hash, ext)
                with open(fp, "wb") as f:
                    f.write(img_data)
                return True, r["tags"], fp
        return False, "", ""
    except:
        return False, "", ""

async def process_and_save_image(img_data, source_url="", uid=""):
    """统一处理一张图片：CLIP打标→存本地→入库，返回(md5, tags_str, file_path)"""
    if not img_data:
        return None, "", ""
    md5 = hashlib.md5(img_data).hexdigest()
    exists, tags_str, fp = image_already_exists(md5)
    if exists:
        log_api(f"图片命中缓存: {md5[:12]} tags={tags_str}")
        return md5, tags_str, fp
    tags, desc = await analyze_image_with_clip(img_data, CLIP_IMAGE_TAGS)
    tags_str = ",".join(tags)
    ext = "gif" if img_data[:6] in (b"GIF89a", b"GIF87a") else "jpg"
    fp = image_local_path(md5, ext)
    with open(fp, "wb") as f:
        f.write(img_data)
    save_image_to_db(md5, img_data, tags_str, source_url, uid)
    log_api(f"图片已保存: {md5[:12]}.{ext} tags={tags_str}")
    return md5, tags_str, fp

def search_local_image_by_tags(keywords, limit=5):
    """从数据库按tags关键词搜索图片"""
    if not keywords:
        return []
    try:
        c = get_cursor()
        conds = " OR ".join(["tags LIKE %s" for _ in keywords[:3]])
        params = [f"%{kw}%" for kw in keywords[:3]]
        sql = f"SELECT md5_hash, tags, file_path, use_count FROM images WHERE {conds} ORDER BY use_count DESC LIMIT %s"
        params.append(limit)
        c.execute(sql, params)
        results = []
        for r in c.fetchall():
            fp = r["file_path"]
            if fp and os.path.exists(fp):
                results.append((r["md5_hash"], r["tags"], fp))
        return results
    except Exception as e:
        log_err(f"搜索图片失败: {e}")
        return []

def get_random_local_image():
    try:
        c = get_cursor()
        c.execute("SELECT md5_hash, tags, file_path FROM images ORDER BY RAND() LIMIT 1")
        r = c.fetchone()
        if r and r["file_path"] and os.path.exists(r["file_path"]):
            return (r["md5_hash"], r["tags"], r["file_path"])
    except:
        pass
    return None

async def fetch_and_save_acg_image():
    """从 ALAPI ACG 获取二次元图→下载→打标→入库，返回文件路径"""
    session = create_http_session()
    try:
        r = session.get("https://v3.alapi.cn/api/acg",
                       params={"token": STICKER_API_ALAPI_TOKEN, "format": "json"},
                       timeout=10, verify=False)
        if r.status_code == 200:
            data = r.json()
            if data.get("code") == 200 and data.get("data"):
                img_url = data["data"].get("url") if isinstance(data["data"], dict) else None
                if img_url:
                    img_data = download_url(img_url)
                    if img_data:
                        md5, tags_str, fp = await process_and_save_image(img_data, img_url, "acg")
                        if fp:
                            return fp
    except Exception as e:
        log_api(f"ACG接口异常: {e}")
    finally:
        session.close()
    return None

async def search_alapi_and_save(keywords):
    """从 ALAPI 搜图→下载→打标→入库，返回文件路径"""
    kw = "表情包 " + " ".join(keywords[:3])
    session = create_http_session()
    try:
        r = session.get("https://v3.alapi.cn/api/doutu",
                       params={"token": STICKER_API_ALAPI_TOKEN, "keyword": kw},
                       timeout=10, verify=False)
        if r.status_code == 200:
            data = r.json()
            if data.get("data") and isinstance(data["data"], list) and data["data"]:
                selected = random.choice(data["data"])
                img_url = selected if isinstance(selected, str) else selected.get("url") or selected.get("img")
                if img_url:
                    img_data = download_url(img_url)
                    if img_data:
                        md5, tags_str, fp = await process_and_save_image(img_data, img_url, "alapi")
                        if fp:
                            return fp
    except Exception as e:
        log_api(f"ALAPI搜图异常: {e}")
    finally:
        session.close()
    return None

async def get_best_image(keywords, uid=""):
    """核心发图函数：优先本地匹配→没有则ALAPI搜→搜到入库，返回文件路径"""
    results = search_local_image_by_tags(keywords, limit=5)
    if results:
        selected = random.choice(results)
        try:
            c = get_cursor()
            c.execute("UPDATE images SET use_count=use_count+1 WHERE md5_hash=%s", (selected[0],))
            c.connection.commit()
        except:
            pass
        return selected[2]
    fp = await search_alapi_and_save(keywords)
    if fp:
        return fp
    rand = get_random_local_image()
    if rand:
        return rand[2]
    return None

