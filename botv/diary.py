# ===================== AI 日记系统 =====================
# 核心功能：根据 events 事件记录 + ai_raw_responses 对话素材，调用 AI 以奈绪视角生成日记
# 数据源：events 表（事件记忆）+ ai_raw_responses 表（AI 对话记录）
# 持久化：diaries 表（target_id + diary_date 唯一索引）
# 缓存：内存缓存 10 分钟（最多 20 条）
# 双模型：优先 DeepSeek，失败切换豆包
# 追溯：当某目标在 diaries 表无任何记录，但 events 表有历史事件时，
#       读取最近有记录的 7 个日期的所有事件，为这 7 天分别生成日记

import re
from datetime import datetime, timedelta

import botv.config as cfg  # 全局运行时变量
from .config import CST  # 时区
from .log import log_system, log_err, log_api  # 日志
from .db import get_cursor  # 数据库游标
from .api import call_deepseek, call_doubao  # 双模型调用

# ===================== 缓存配置 =====================
_diary_cache = {}  # 日记缓存 {key: (生成时间戳, 日记内容)}
CACHE_TTL = 600  # 缓存有效期（秒）= 10 分钟
MAX_CACHE = 20  # 缓存最大条数

# ===================== 数据库操作 =====================

def ensure_diaries_table():
    """确保 diaries 表存在（启动时调用，失败不致命）"""
    try:
        c = get_cursor()
        c.execute("""
            CREATE TABLE IF NOT EXISTS diaries (
                id INT AUTO_INCREMENT PRIMARY KEY,
                target_id VARCHAR(50) NOT NULL,
                diary_date DATE NOT NULL,
                content TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                INDEX idx_target_date (target_id, diary_date)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """)
        c.connection.commit()
        return True
    except Exception as e:
        log_err(f"确保 diaries 表存在失败: {e}")
        return False

def get_diary_from_db(target_id: str, date_str: str):
    """从 diaries 表查询已保存的日记，不存在返回 None"""
    try:
        c = get_cursor()
        c.execute(
            "SELECT content FROM diaries WHERE target_id=%s AND diary_date=%s ORDER BY id DESC LIMIT 1",
            (target_id, date_str)
        )
        r = c.fetchone()
        if r and r.get("content"):
            return r["content"]
    except Exception as e:
        log_err(f"查询日记失败({target_id}, {date_str}): {e}")
    return None

def save_diary_to_db(target_id: str, date_str: str, content: str):
    """保存日记到 diaries 表（已存在则更新）"""
    try:
        c = get_cursor()
        c.execute("""
            INSERT INTO diaries (target_id, diary_date, content)
            VALUES (%s, %s, %s)
            ON DUPLICATE KEY UPDATE content=VALUES(content)
        """, (target_id, date_str, content))
        c.connection.commit()
        return True
    except Exception as e:
        log_err(f"保存日记失败({target_id}, {date_str}): {e}")
        return False

def get_events_by_date(target_id: str, date_str: str):
    """查询指定日期的所有事件记录，返回 [(event_summary, tags)] 列表"""
    try:
        c = get_cursor()
        c.execute(
            "SELECT event_summary, tags FROM events WHERE target_id=%s AND DATE(created_at)=%s ORDER BY id",
            (target_id, date_str)
        )
        return [(r["event_summary"], r.get("tags") or "") for r in c.fetchall()]
    except Exception as e:
        log_err(f"查询事件失败({target_id}, {date_str}): {e}")
        return []

def get_dialogs_by_date(target_id: str, date_str: str, limit=10):
    """查询指定日期的 AI 调用记录（对话素材），返回 [(user_msg, response_text)] 列表"""
    try:
        c = get_cursor()
        c.execute("""
            SELECT user_msg, response_text FROM ai_raw_responses
            WHERE target_id=%s AND DATE(created_at)=%s
              AND response_text IS NOT NULL AND response_text != ''
            ORDER BY id LIMIT %s
        """, (target_id, date_str, limit))
        return [(r["user_msg"] or "", r["response_text"] or "") for r in c.fetchall()]
    except Exception as e:
        log_err(f"查询对话素材失败({target_id}, {date_str}): {e}")
        return []

def get_dates_with_events(target_id: str, limit=7):
    """追溯查询最近有事件记录的 N 个日期（按日期倒序）
    返回 ['YYYY-MM-DD', ...] 列表"""
    try:
        c = get_cursor()
        c.execute("""
            SELECT DISTINCT DATE(created_at) AS d
            FROM events
            WHERE target_id=%s
            ORDER BY d DESC
            LIMIT %s
        """, (target_id, limit))
        result = []
        for r in c.fetchall():
            d = r["d"]
            # 兼容 date 或 datetime 对象，统一转为 YYYY-MM-DD 字符串
            if hasattr(d, "isoformat"):
                result.append(d.isoformat())
            else:
                result.append(str(d)[:10])
        return result
    except Exception as e:
        log_err(f"追溯查询有事件记录日期失败({target_id}): {e}")
        return []

def count_diaries_of_target(target_id: str) -> int:
    """统计某个目标在 diaries 表中已有的日记数量"""
    try:
        c = get_cursor()
        c.execute("SELECT COUNT(*) AS n FROM diaries WHERE target_id=%s", (target_id,))
        return c.fetchone()["n"] or 0
    except Exception as e:
        log_err(f"统计日记数量失败({target_id}): {e}")
        return 0

# ===================== 追溯生成 =====================

async def generate_missing_7day_diaries(target_id: str):
    """追溯生成：当目标在 diaries 表无任何记录，但 events 表有历史事件时，
    读取最近有记录的 7 个日期的事件，为这 7 天分别生成日记。
    返回 (已生成日期列表, 跳过日期列表)"""
    # 1. 若该目标已有任何日记记录，则跳过追溯（避免重复消耗 AI）
    if count_diaries_of_target(target_id) > 0:
        log_system(f"日记追溯：{target_id} 已有历史日记，跳过追溯生成")
        return [], []

    # 2. 追溯最近有事件记录的 7 个日期
    targets = get_dates_with_events(target_id, limit=7)
    if not targets:
        log_system(f"日记追溯：{target_id} 的 events 表无任何记录，跳过")
        return [], []

    log_system(f"日记追溯：{target_id} diaries 表为空但 events 有 {len(targets)} 个有记录的日期，开始生成")

    generated = []
    skipped = []
    for d in targets:
        # 逐天生成（generate_diary 内部会保存到 diaries 表）
        try:
            text = await generate_diary(target_id, d)
            if text and not text.startswith("📭"):
                generated.append(d)
                log_system(f"  追溯日记 {d}: {text[:40]}...")
            else:
                skipped.append(d)
        except Exception as e:
            log_err(f"追溯日记生成失败({d}): {e}")
            skipped.append(d)

    log_system(f"日记追溯完成：生成 {len(generated)} 篇，跳过 {len(skipped)} 篇")
    return generated, skipped

# ===================== 日记生成 =====================

def _clean_diary_text(text: str) -> str:
    """清理 AI 输出：去除格式行、多余空行、限制长度"""
    if not text:
        return text

    lines = []
    for line in text.strip().split("\n"):
        stripped = line.strip()
        # 跳过 AI 可能输出的格式行
        if stripped.startswith("关键词搜索图片用") or stripped.startswith("关键词提炼") or stripped.startswith("事件摘要"):
            continue
        if stripped.startswith("（无）") or stripped == "(无)":
            continue
        lines.append(stripped)

    cleaned = "\n".join(lines)
    # 合并多余空行
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    # 安全阀：限制 2000 字
    if len(cleaned) > 2000:
        cleaned = cleaned[:2000] + "..."
    return cleaned

async def generate_diary(target_id: str, date_str: str, force: bool = False):
    """生成指定日期的奈绪视角日记（一篇文章样式，200字以上）

    流程：查缓存 → 查库 → 收集素材 → AI 生成 → 保存 → 返回
    参数 force=True 时跳过缓存/数据库，强制重新生成
    无事件记录时返回友好提示（不生成）
    """
    # ---- 参数校验 ----
    try:
        datetime.strptime(date_str, "%Y-%m-%d")
    except ValueError:
        return "❌ 日期格式错误，请用 YYYY-MM-DD 格式"

    cache_key = f"{target_id}_{date_str}"

    # ---- 1. 非强制时查内存缓存 ----
    if not force:
        cache_entry = _diary_cache.get(cache_key)
        if cache_entry:
            gen_time, cached_text = cache_entry
            if datetime.now().timestamp() - gen_time < CACHE_TTL:
                log_api(f"[diary] 命中缓存: {cache_key}")
                return cached_text

    # ---- 2. 非强制时查数据库（已存在的直接读取） ----
    if not force:
        db_text = get_diary_from_db(target_id, date_str)
        if db_text:
            _diary_cache[cache_key] = (datetime.now().timestamp(), db_text)
            log_api(f"[diary] 命中数据库: {cache_key}")
            return db_text

    # ---- 3. 收集素材：当天事件 + 当天对话片段 ----
    events = get_events_by_date(target_id, date_str)
    dialogs = get_dialogs_by_date(target_id, date_str)

    # ---- 4. 无事件记录 → 友好提示，不生成 ----
    if not events:
        log_system(f"日记({date_str}): {target_id} 当天无事件记录，跳过 AI 生成")
        return f"📭 {date_str} 没有事件记录，暂时无法生成日记。"

    # ---- 5. 构造 AI 提示词 ----
    event_lines = []
    for summary, tags in events:
        tag_str = f" [{tags}]" if tags else ""
        event_lines.append(f"- {summary}{tag_str}")
    event_text = "\n".join(event_lines)

    dialog_lines = []
    for user_msg, response_text in dialogs[:8]:  # 最多 8 组对话素材
        if user_msg:
            dialog_lines.append(f"主人: {user_msg[:100]}")
        if response_text:
            dialog_lines.append(f"奈绪: {response_text[:100]}")
    dialog_text = "\n".join(dialog_lines)

    # 组装 AI 用户输入
    user_prompt = (
        f"日期：{date_str}\n"
        f"\n【当天事件记录】\n{event_text}\n"
        f"\n【当天对话片段】\n{dialog_text if dialog_text else '（无对话记录）'}"
    )

    # 系统提示词：要求以奈绪视角写一篇 ≥200 字的文章样式日记
    system_prompt = (
        "你是友利奈绪（Tomori Nao），一个傲娇毒舌但内心温柔的二次元少女。\n"
        "请根据下面提供的事件记录和对话片段，以第一人称视角写一篇完整的日记。\n"
        "要求：\n"
        "1. 以日期自然开头（如'今天''X月X日'），像人类日记一样叙事\n"
        "2. 全文至少200字，是一篇有开头、正文、结尾的完整文章\n"
        "3. 自然地融入事件和对话细节，不要列清单\n"
        "4. 偶尔带出性格特点（'哼''笨蛋主人'等），但不要过度\n"
        "5. 行文流畅、口语化、有温度，体现对主人的关心\n"
        "6. 直接输出日记正文，不要任何前缀、标题、格式行、表情符号"
    )

    msgs = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]

    # ---- 6. 调用 AI 生成（双模型兜底，max_tokens 1500 保证 200 字以上） ----
    log_system(f"日记({date_str}): 开始 AI 生成（事件{len(events)}条，对话{len(dialogs)}条）")
    diary_text = await call_deepseek(msgs, max_tokens=1500, target_id=target_id)
    if not diary_text:
        log_api("[diary] DeepSeek 无回复，切换豆包")
        diary_text = await call_doubao(msgs, max_tokens=1500, target_id=target_id)

    # ---- 7. 清理 AI 输出 ----
    diary_text = _clean_diary_text(diary_text)

    # ---- 8. AI 生成失败降级：返回事件纪要 ----
    if not diary_text or len(diary_text.strip()) < 20:
        log_err(f"日记 AI 生成失败({target_id}, {date_str})，降级为事件纪要")
        diary_text = f"（AI 生成失败，以下为 {date_str} 事件纪要）\n{event_text}"

    # ---- 9. 保存到数据库 ----
    save_diary_to_db(target_id, date_str, diary_text)

    # ---- 10. 更新缓存（限制最大条数，超限时删除最旧） ----
    _diary_cache[cache_key] = (datetime.now().timestamp(), diary_text)
    if len(_diary_cache) > MAX_CACHE:
        oldest_key = min(_diary_cache, key=lambda k: _diary_cache[k][0])
        del _diary_cache[oldest_key]

    log_system(f"日记({date_str}) 已生成并保存（{len(diary_text)}字）")
    return diary_text

# ===================== 概览与原始记录 =====================

def get_raw_events_text(target_id: str, date_str: str) -> str:
    """查看指定日期的原始事件记录文本（不调用 AI）"""
    try:
        datetime.strptime(date_str, "%Y-%m-%d")
    except ValueError:
        return "❌ 日期格式错误，请用 YYYY-MM-DD 格式，如 !diary raw 2026-07-15"

    events = get_events_by_date(target_id, date_str)
    if not events:
        return f"📭 {date_str} 没有事件记录"

    lines = [f"📅 {date_str} 的原始事件记录："]

    # 同时查对话片段
    dialogs = get_dialogs_by_date(target_id, date_str)
    if dialogs:
        lines.append("")
        lines.append("💬 对话片段：")
        for user_msg, response_text in dialogs[:10]:
            if user_msg:
                lines.append(f"  主人: {user_msg[:80]}")
            if response_text:
                lines.append(f"  奈绪: {response_text[:80]}")
        lines.append("")

    lines.append("📌 事件记忆：")
    for summary, tags in events:
        tag_str = f" [{tags}]" if tags else ""
        lines.append(f"  - {summary}{tag_str}")

    return "\n".join(lines)

async def get_diary_overview(target_id: str, days: int = 7) -> str:
    """生成最近 N 天日记概览（显示：日记已生成/有事件/空 状态）
    days: 查询天数，默认 7，上限 30"""
    days = min(max(days, 1), 30)
    lines = [f"📖 最近 {days} 天日记概览（{target_id}）："]

    today = datetime.now(CST).date()
    for offset in range(days):
        d = (today - timedelta(days=offset)).isoformat()
        # 先查数据库
        db_text = get_diary_from_db(target_id, d)
        # 再查事件
        events = get_events_by_date(target_id, d)
        # 再查缓存
        cache_entry = _diary_cache.get(f"{target_id}_{d}")
        cache_text = cache_entry[1] if cache_entry else None

        mark = "❌"
        if db_text or cache_text:
            mark = "✅ 日记已生成"
        elif events:
            mark = "📌 有事件（可生成）"
        else:
            mark = "⬜ 空"

        lines.append(f"  {d}  {mark}")

    return "\n".join(lines)