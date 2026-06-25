# ===================== 统一图片系统 =====================
# 下载→CLIP打标→本地存档→入库→按tag搜索复用

import os  # 文件路径操作
import hashlib  # MD5哈希计算
import asyncio  # 异步IO
import random  # 随机选择

from .config import IMAGE_DIR, CLIP_IMAGE_TAGS  # 图片目录配置、CLIP标签列表
import botv.config as cfg  # 全局运行时变量
from .db import get_cursor  # 数据库游标
from .log import log_system, log_api, log_err  # 日志
from .clip import analyze_image_with_clip  # CLIP图片分析
from .utils import download_url, create_http_session, encode_image_base64  # 工具函数


def image_local_path(md5_hash, ext="jpg"):
    """根据MD5和扩展名生成图片本地绝对路径"""
    os.makedirs(IMAGE_DIR, exist_ok=True)  # 确保图片目录存在
    rel = os.path.join(IMAGE_DIR, f"{md5_hash}.{ext}")  # 相对路径
    return os.path.abspath(rel)  # 转为绝对路径


def save_image_to_db(md5_hash, img_data, tags, source_url="", uid=""):
    """将图片数据存入数据库images表"""
    ext = "gif" if img_data[:6] in (b"GIF89a", b"GIF87a") else "jpg"  # 检测是否为GIF
    fp = image_local_path(md5_hash, ext)  # 生成文件路径
    try:
        c = get_cursor()  # 获取数据库游标
        c.execute(
            "INSERT IGNORE INTO images(md5_hash, image_data, tags, source_url, file_path, ext, use_count) VALUES(%s,%s,%s,%s,%s,%s,0)",
            (md5_hash, img_data, tags, source_url, fp, ext)  # 插入图片记录，use_count初始为0
        )
        c.connection.commit()  # 提交事务
    except Exception as e:
        log_err(f"图片入库失败: {e}")  # 入库失败记录错误


def load_image_from_db(md5_hash):
    """从数据库加载图片二进制数据和扩展名"""
    try:
        c = get_cursor()  # 获取数据库游标
        c.execute("SELECT image_data, ext FROM images WHERE md5_hash=%s", (md5_hash,))  # 按MD5查询
        r = c.fetchone()  # 获取结果
        if r:
            return r["image_data"], r["ext"]  # 返回二进制数据和扩展名
    except:
        pass  # 查询失败返回None
    return None, None


def image_already_exists(md5_hash):
    """检查图片是否已存在，返回(是否存在, 标签, 文件路径)"""
    try:
        c = get_cursor()  # 获取数据库游标
        c.execute("SELECT id, tags, file_path, ext FROM images WHERE md5_hash=%s", (md5_hash,))  # 按MD5查询
        r = c.fetchone()  # 获取结果
        if r:
            fp = r["file_path"]  # 获取文件路径
            if fp and os.path.exists(fp):  # 文件已存在磁盘上
                return True, r["tags"], fp  # 直接返回
            img_data, ext = load_image_from_db(md5_hash)  # 从数据库加载二进制数据
            if img_data:
                fp = image_local_path(md5_hash, ext)  # 生成文件路径
                with open(fp, "wb") as f:
                    f.write(img_data)  # 写入磁盘
                return True, r["tags"], fp  # 返回
        return False, "", ""  # 不存在
    except:
        return False, "", ""  # 查询失败视为不存在


async def process_and_save_image(img_data, source_url="", uid=""):
    """统一处理一张图片：CLIP打标→存本地→入库，返回(md5, tags_str, file_path)"""
    if not img_data:  # 图片数据为空
        return None, "", ""
    md5 = hashlib.md5(img_data).hexdigest()  # 计算MD5哈希
    exists, tags_str, fp = image_already_exists(md5)  # 检查是否已存在
    if exists:  # 命中缓存
        log_api(f"图片命中缓存: {md5[:12]} tags={tags_str}")
        return md5, tags_str, fp  # 直接返回
    tags, desc = await analyze_image_with_clip(img_data, CLIP_IMAGE_TAGS)  # CLIP分析图片
    tags_str = ",".join(tags)  # 标签列表转逗号分隔字符串
    ext = "gif" if img_data[:6] in (b"GIF89a", b"GIF87a") else "jpg"  # 检测GIF
    fp = image_local_path(md5, ext)  # 生成文件路径
    with open(fp, "wb") as f:
        f.write(img_data)  # 写入磁盘
    save_image_to_db(md5, img_data, tags_str, source_url, uid)  # 入库
    log_api(f"图片已保存: {md5[:12]}.{ext} tags={tags_str}")
    return md5, tags_str, fp  # 返回结果


def search_local_image_by_tags(keywords, limit=5):
    """从数据库按tags关键词搜索图片，返回[(md5, tags, file_path), ...]"""
    if not keywords:  # 关键词为空
        return []
    try:
        c = get_cursor()  # 获取数据库游标
        conds = " OR ".join(["tags LIKE %s" for _ in keywords[:3]])  # 构建LIKE条件（最多3个关键词）
        params = [f"%{kw}%" for kw in keywords[:3]]  # 构建参数列表
        sql = f"SELECT md5_hash, tags, file_path, use_count FROM images WHERE {conds} ORDER BY use_count DESC LIMIT %s"  # 按使用次数降序
        params.append(limit)  # 添加limit参数
        c.execute(sql, params)  # 执行查询
        results = []
        for r in c.fetchall():  # 遍历结果
            fp = r["file_path"]  # 获取文件路径
            if fp and os.path.exists(fp):  # 文件存在
                results.append((r["md5_hash"], r["tags"], fp))  # 添加到结果列表
        return results
    except Exception as e:
        log_err(f"搜索图片失败: {e}")  # 搜索失败记录错误
        return []


def get_random_local_image():
    """从数据库随机获取一张本地图片"""
    try:
        c = get_cursor()  # 获取数据库游标
        c.execute("SELECT md5_hash, tags, file_path FROM images ORDER BY RAND() LIMIT 1")  # 随机排序取1条
        r = c.fetchone()  # 获取结果
        if r and r["file_path"] and os.path.exists(r["file_path"]):  # 文件存在
            return (r["md5_hash"], r["tags"], r["file_path"])  # 返回
    except:
        pass  # 失败返回None
    return None


async def fetch_and_save_acg_image():
    """从 ALAPI ACG 接口获取二次元图→下载→打标→入库，返回文件路径"""
    session = create_http_session()  # 创建HTTP会话
    try:
        r = session.get("https://v3.alapi.cn/api/acg",  # 调用ALAPI ACG接口
                       params={"token": cfg.STICKER_API_ALAPI_TOKEN, "format": "json"},  # 传token和格式
                       timeout=10, verify=False)  # 10秒超时，不验证SSL
        if r.status_code == 200:  # HTTP请求成功
            data = r.json()  # 解析JSON
            if data.get("code") == 200 and data.get("data"):  # API返回成功
                img_url = data["data"].get("url") if isinstance(data["data"], dict) else None  # 获取图片URL
                if img_url:
                    img_data = download_url(img_url)  # 下载图片
                    if img_data:
                        md5, tags_str, fp = await process_and_save_image(img_data, img_url, "acg")  # 处理并保存
                        if fp:
                            return fp  # 返回文件路径
    except Exception as e:
        log_api(f"ACG接口异常: {e}")  # 接口异常记录
    finally:
        session.close()  # 关闭会话
    return None  # 失败返回None


async def search_alapi_and_save(keywords):
    """从 ALAPI 斗图接口搜图→下载→打标→入库，返回文件路径"""
    kw = "表情包 " + " ".join(keywords[:3])  # 构建搜索关键词
    session = create_http_session()  # 创建HTTP会话
    try:
        r = session.get("https://v3.alapi.cn/api/doutu",  # 调用ALAPI斗图接口
                       params={"token": cfg.STICKER_API_ALAPI_TOKEN, "keyword": kw},  # 传token和关键词
                       timeout=10, verify=False)  # 10秒超时，不验证SSL
        if r.status_code == 200:  # HTTP请求成功
            data = r.json()  # 解析JSON
            if data.get("data") and isinstance(data["data"], list) and data["data"]:  # 返回图片列表
                selected = random.choice(data["data"])  # 随机选一张
                img_url = selected if isinstance(selected, str) else selected.get("url") or selected.get("img")  # 获取图片URL
                if img_url:
                    img_data = download_url(img_url)  # 下载图片
                    if img_data:
                        md5, tags_str, fp = await process_and_save_image(img_data, img_url, "alapi")  # 处理并保存
                        if fp:
                            return fp  # 返回文件路径
    except Exception as e:
        log_api(f"ALAPI搜图异常: {e}")  # 接口异常记录
    finally:
        session.close()  # 关闭会话
    return None  # 失败返回None


async def get_best_image(keywords, uid=""):
    """核心发图函数：优先本地匹配→没有则ALAPI搜→搜到入库，返回文件路径"""
    results = search_local_image_by_tags(keywords, limit=5)  # 本地搜索（最多5张）
    if results:  # 本地有匹配
        selected = random.choice(results)  # 随机选一张
        try:
            c = get_cursor()  # 获取数据库游标
            c.execute("UPDATE images SET use_count=use_count+1 WHERE md5_hash=%s", (selected[0],))  # 使用次数+1
            c.connection.commit()  # 提交事务
        except:
            pass  # 更新失败不影响
        return selected[2]  # 返回文件路径
    fp = await search_alapi_and_save(keywords)  # 本地无匹配，ALAPI在线搜图
    if fp:  # ALAPI搜到
        return fp  # 返回文件路径
    rand = get_random_local_image()  # ALAPI也没搜到，随机取一张本地图
    if rand:  # 有随机图
        return rand[2]  # 返回文件路径
    return None  # 完全无图可用

