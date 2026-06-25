# ===================== HTTP API 服务器 =====================
# 提供 RESTful API 接口，支持命令执行和对话调用
# 所有接口需要 Bearer Token 验证
# 使用 aiohttp 实现异步 HTTP 服务器
# 支持至少 10 个并发连接
# 所有文本统一 UTF-8 编码，Token 使用英文+数字

import asyncio
import json
import hmac
import secrets
from datetime import datetime

from aiohttp import web

from .config import CST, MASTER_QQ
from .log import log_system, log_err, log_api
from .db import get_cursor, get_recent_usage
from .api import get_character_reply
import botv.config as cfg

# ===================== 配置 =====================
API_HOST = "0.0.0.0"
API_PORT = 60908
API_TOKEN = ""
API_TOKEN_KEY_NAME = "API_SERVER_TOKEN"
MAX_CONCURRENT_REQUESTS = 20
_semaphore = None


def load_api_token():
    global API_TOKEN
    try:
        c = get_cursor()
        c.execute("SELECT key_value FROM api_keys WHERE key_name=%s", (API_TOKEN_KEY_NAME,))
        r = c.fetchone()
        if r and r.get("key_value"):
            API_TOKEN = r["key_value"]
            log_system("API Token 已从数据库加载")
            return
    except Exception as e:
        log_err(f"加载 API Token 失败: {e}")

    API_TOKEN = "nao_" + secrets.token_hex(20)
    try:
        c = get_cursor()
        c.execute(
            "INSERT INTO api_keys (key_name, key_value) VALUES (%s, %s) ON DUPLICATE KEY UPDATE key_value=%s",
            (API_TOKEN_KEY_NAME, API_TOKEN, API_TOKEN)
        )
        c.connection.commit()
        log_system(f"已生成默认 API Token: {API_TOKEN[:20]}...")
    except Exception as e:
        log_err(f"保存 API Token 失败: {e}")


@web.middleware
async def auth_middleware(request, handler):
    if request.path == "/api/health":
        return await handler(request)

    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        return web.json_response(
            {"error": "missing_auth_header", "message": "缺少 Authorization header"},
            status=401
        )
    token = auth_header[7:]
    if not hmac.compare_digest(token, API_TOKEN):
        return web.json_response(
            {"error": "invalid_token", "message": "Token 无效"},
            status=403
        )
    return await handler(request)


def _format_dt(dt):
    if hasattr(dt, 'strftime'):
        return dt.strftime('%Y-%m-%d %H:%M:%S')
    return str(dt)[:19] if dt else ""


def _json_response(data, status=200):
    return web.json_response(data, status=status, dumps=lambda x: json.dumps(x, ensure_ascii=False))


async def handle_health(request):
    return _json_response({
        "status": "ok",
        "timestamp": datetime.now(CST).strftime('%Y-%m-%d %H:%M:%S'),
    })


async def handle_status(request):
    try:
        c = get_cursor()
        c.execute("SELECT COUNT(*) as cnt FROM images")
        img_count = c.fetchone()["cnt"]
        c.execute("SELECT COUNT(*) as cnt FROM user_memory")
        mem_count = c.fetchone()["cnt"]
        c.execute("SELECT COUNT(*) as cnt FROM events")
        evt_count = c.fetchone()["cnt"]
        c.execute("SELECT COUNT(*) as cnt FROM logs")
        log_count = c.fetchone()["cnt"]
        c.execute("SELECT COUNT(*) as cnt FROM global_keywords")
        kw_count = c.fetchone()["cnt"]
        c.execute("SELECT COUNT(*) as cnt FROM ai_raw_responses")
        ai_count = c.fetchone()["cnt"]
    except Exception as e:
        return _json_response({"error": "db_query_failed", "message": str(e)}, 500)

    return _json_response({
        "status": "running",
        "master_qq": MASTER_QQ,
        "deepseek": bool(cfg.DS_API_KEY),
        "doubao": bool(cfg.DOUBAO_API_KEY),
        "clip": cfg.CLIP_ENABLED,
        "sticker_api": bool(cfg.STICKER_API_ALAPI_TOKEN),
        "stats": {
            "images": img_count,
            "memories": mem_count,
            "events": evt_count,
            "logs": log_count,
            "keywords": kw_count,
            "ai_responses": ai_count,
        },
        "runtime": {
            "dialogue_targets": len(cfg.user_memory_pool),
            "global_keywords": len(cfg.global_keyword_set),
            "stickers": len(cfg.STICKER_DATA),
            "daily_triggers": len(cfg.daily_trigger),
        }
    })


async def handle_usage(request):
    try:
        limit = int(request.query.get("limit", 10))
        limit = min(max(limit, 1), 100)
    except ValueError:
        limit = 10

    try:
        records = get_recent_usage(limit)
        result = []
        total_prompt = 0
        total_completion = 0
        total_all = 0
        for r in records:
            pt = r["prompt_tokens"] or 0
            ct = r["completion_tokens"] or 0
            tt = r["total_tokens"] or 0
            result.append({
                "model": r["model_name"],
                "prompt_tokens": pt,
                "completion_tokens": ct,
                "total_tokens": tt,
                "status": r["status"],
                "created_at": _format_dt(r.get("created_at")),
            })
            total_prompt += pt
            total_completion += ct
            total_all += tt
        return _json_response({
            "records": result,
            "summary": {
                "total_prompt_tokens": total_prompt,
                "total_completion_tokens": total_completion,
                "total_tokens": total_all,
                "count": len(result),
            }
        })
    except Exception as e:
        return _json_response({"error": "query_failed", "message": str(e)}, 500)


async def handle_memory(request):
    target_id = request.query.get("target_id", "")
    if target_id:
        if target_id in cfg.user_memory_pool:
            deq = cfg.user_memory_pool[target_id]
            records = []
            for u, b in deq:
                records.append({"user": u, "bot": b})
            return _json_response({
                "target_id": target_id,
                "count": len(records),
                "records": records[-20:],
            })
        else:
            return _json_response({
                "target_id": target_id,
                "count": 0,
                "records": [],
            })
    else:
        targets = []
        for tid, deq in cfg.user_memory_pool.items():
            targets.append({
                "target_id": tid,
                "count": len(deq),
                "last_message": deq[-1][0][:30] if deq else "",
            })
        return _json_response({
            "total_targets": len(cfg.user_memory_pool),
            "targets": targets,
        })


async def handle_logs(request):
    try:
        limit = int(request.query.get("limit", 20))
        limit = min(max(limit, 1), 100)
    except ValueError:
        limit = 20

    try:
        from .log import get_recent_logs
        logs_text = get_recent_logs(limit)
        return _json_response({
            "count": limit,
            "logs": logs_text,
        })
    except Exception as e:
        return _json_response({"error": "log_query_failed", "message": str(e)}, 500)


async def handle_chat(request):
    try:
        body = await request.json()
    except Exception:
        return _json_response({"error": "invalid_json", "message": "请求体必须是 JSON 格式"}, 400)

    message = body.get("message", "").strip()
    if not message:
        return _json_response({"error": "empty_message", "message": "message 不能为空"}, 400)

    target_id = str(body.get("target_id", MASTER_QQ))
    keywords = body.get("keywords", None)

    try:
        reply = await get_character_reply(message, target_id, keywords)
        return _json_response({
            "success": True,
            "reply": reply,
            "target_id": target_id,
        })
    except Exception as e:
        log_err(f"API 对话调用失败: {e}")
        return _json_response({"error": "ai_call_failed", "message": str(e)}, 500)


async def handle_command(request):
    try:
        body = await request.json()
    except Exception:
        return _json_response({"error": "invalid_json", "message": "请求体必须是 JSON 格式"}, 400)

    cmd = body.get("command", "").strip().lower()
    args = body.get("args", [])

    try:
        if cmd == "help":
            from .commands import build_cmd_help
            result = build_cmd_help()
        elif cmd == "status":
            from .commands import format_status_detailed
            result = format_status_detailed()
        elif cmd == "task":
            from .commands import format_task_list
            result = format_task_list()
        elif cmd == "memory":
            if args:
                target = args[0]
                if target in cfg.user_memory_pool:
                    deq = cfg.user_memory_pool[target]
                    lines = [f"{target} 的对话记忆（共{len(deq)}条）："]
                    for i, (u, b) in enumerate(deq[-10:], 1):
                        lines.append(f"  {i}. 用户: {u[:30]}...")
                        lines.append(f"     奈绪: {b[:30]}...")
                    result = "\n".join(lines)
                else:
                    result = f"{target} 暂无对话记忆"
            else:
                from .commands import format_memory_stats
                result = format_memory_stats()
        elif cmd == "sticker":
            from .commands import format_sticker_stats
            result = format_sticker_stats()
        elif cmd == "clip":
            from .commands import format_clip_status
            result = format_clip_status()
        elif cmd == "keywords":
            from .commands import format_keywords
            result = format_keywords()
        elif cmd == "apikeys":
            from .commands import format_apikeys
            result = format_apikeys()
        elif cmd == "usage":
            records = get_recent_usage(10)
            if not records:
                result = "暂无token用量记录"
            else:
                lines = ["最近10次AI调用token用量："]
                total_prompt = 0
                total_completion = 0
                total_all = 0
                for i, r in enumerate(records, 1):
                    model = r["model_name"]
                    pt = r["prompt_tokens"] or 0
                    ct = r["completion_tokens"] or 0
                    tt = r["total_tokens"] or 0
                    tm = _format_dt(r.get("created_at"))
                    lines.append(f"  {i}. [{model}] 输入{pt}+输出{ct}={tt} ({tm})")
                    total_prompt += pt
                    total_completion += ct
                    total_all += tt
                lines.append("  ---")
                lines.append(f"  合计: 输入{total_prompt}+输出{total_completion}={total_all}")
                result = "\n".join(lines)
        else:
            return _json_response({"error": "unknown_command", "message": f"未知命令: {cmd}"}, 400)

        return _json_response({
            "success": True,
            "command": cmd,
            "args": args,
            "result": result,
        })
    except Exception as e:
        return _json_response({"error": "command_failed", "message": str(e)}, 500)


async def handle_get_token(request):
    return _json_response({
        "token_prefix": API_TOKEN[:12] + "...",
        "host": API_HOST,
        "port": API_PORT,
        "endpoints": [
            {"path": "/api/health", "method": "GET", "auth": False},
            {"path": "/api/status", "method": "GET", "auth": True},
            {"path": "/api/usage", "method": "GET", "auth": True},
            {"path": "/api/memory", "method": "GET", "auth": True},
            {"path": "/api/logs", "method": "GET", "auth": True},
            {"path": "/api/chat", "method": "POST", "auth": True},
            {"path": "/api/command", "method": "POST", "auth": True},
            {"path": "/api/token", "method": "GET", "auth": True},
        ]
    })


async def start_api_server():
    global _semaphore
    _semaphore = asyncio.Semaphore(MAX_CONCURRENT_REQUESTS)
    load_api_token()

    app = web.Application(middlewares=[auth_middleware])
    app.router.add_get("/api/health", handle_health)
    app.router.add_get("/api/status", handle_status)
    app.router.add_get("/api/usage", handle_usage)
    app.router.add_get("/api/memory", handle_memory)
    app.router.add_get("/api/logs", handle_logs)
    app.router.add_get("/api/token", handle_get_token)
    app.router.add_post("/api/chat", handle_chat)
    app.router.add_post("/api/command", handle_command)

    runner = web.AppRunner(app, handle_signals=False)
    await runner.setup()
    site = web.TCPSite(runner, API_HOST, API_PORT, reuse_address=True, reuse_port=True)
    await site.start()

    log_system(f"API 服务器已启动: http://{API_HOST}:{API_PORT}")
    log_system(f"API Token: {API_TOKEN[:12]}...")
    log_system(f"最大并发: {MAX_CONCURRENT_REQUESTS}")

    return runner


def format_api_token_info():
    return (
        f"API 服务器 Token：\n"
        f"  Token: {API_TOKEN}\n"
        f"  地址: http://{API_HOST}:{API_PORT}\n"
        f"  用法: Authorization: Bearer {API_TOKEN}\n"
        f"  接口列表:"
        f"    GET  /api/health   - 健康检查（无需Token）"
        f"    GET  /api/status   - 运行状态"
        f"    GET  /api/usage    - Token用量"
        f"    GET  /api/memory   - 对话记忆"
        f"    GET  /api/logs     - 最近日志"
        f"    GET  /api/token    - Token信息"
        f"    POST /api/chat     - AI对话"
        f"    POST /api/command  - 执行命令"
    )
