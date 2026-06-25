# 大模型调用：DeepSeek + 豆包 双模型兜底
import asyncio, random
from .config import DS_API_URL, DS_MODEL, DS_TIMEOUT, DOUBAO_API_URL, DOUBAO_MODEL, DOUBAO_TIMEOUT, API_RETRY_DELAY, MAX_RETRY_TIMES
from .log import log_api, log_err, log_system
from .utils import create_http_session
from .db import save_ai_raw_response
import botv.config as cfg

def _extract_user_msg(msgs):
    """从消息列表中提取用户消息"""
    for m in msgs:
        if m.get("role") == "user":
            return m.get("content", "")[:500]
    return ""

def _extract_target_id(msgs):
    """从消息中提取目标ID（取user消息末尾的tid信息）"""
    user_content = _extract_user_msg(msgs)
    return user_content[:80] if user_content else ""

async def call_deepseek(msgs,retry=2):
    log_api(f"[DS] 开始调用, model={DS_MODEL}, 消息数={len(msgs)}, key={'有' if cfg.DS_API_KEY else '无'}")
    if not cfg.DS_API_KEY:
        log_api("[DS] 无API key，跳过")
        return None
    h={"Authorization":f"Bearer {cfg.DS_API_KEY}","Content-Type":"application/json"}
    d={"model":DS_MODEL,"messages":msgs,"max_tokens":200,"temperature":0.7}
    user_msg = _extract_user_msg(msgs)
    target_id = _extract_target_id(msgs)
    for a in range(retry):
        try:
            log_api(f"[DS] 第{a+1}次请求...")
            def req():
                s=create_http_session(); return s.post(DS_API_URL,headers=h,json=d,timeout=DS_TIMEOUT,verify=False)
            r=await asyncio.to_thread(req)
            log_api(f"[DS] 响应状态码: {r.status_code}")
            if r.status_code==200:
                raw_json = r.json()
                t=raw_json["choices"][0]["message"]["content"].strip()
                log_api(f"[DS] 回复内容: {t[:60]}")
                if t:
                    log_api("[DS] 回复成功")
                    # 保存原始完整JSON返回数据到数据库
                    save_ai_raw_response(
                        model_name=f"DeepSeek({DS_MODEL})",
                        user_msg=user_msg,
                        raw_response_json=raw_json,
                        response_text=t,
                        target_id=target_id,
                        status="success"
                    )
                    return t
                else:
                    log_api("[DS] 回复内容为空")
                    save_ai_raw_response("DeepSeek", user_msg, raw_json, "", target_id, "empty_reply")
            else:
                log_api(f"[DS] 非200响应: {r.text[:200]}")
                save_ai_raw_response("DeepSeek", user_msg, {"status_code": r.status_code, "text": r.text[:500]}, "", target_id, f"http_error_{r.status_code}")
        except Exception as e:
            log_api(f"[DS] 第{a+1}次失败: {e}")
        await asyncio.sleep(API_RETRY_DELAY*(a+1))
    log_api("[DS] 全部重试失败，返回None")
    return None

async def call_doubao(msgs):
    log_api(f"[豆包] 开始调用, model={DOUBAO_MODEL}, key={'有' if cfg.DOUBAO_API_KEY else '无'}")
    user_msg = _extract_user_msg(msgs)
    target_id = _extract_target_id(msgs)
    if not cfg.DOUBAO_API_KEY:
        log_api("[豆包] 无API key，返回默认回复")
        fallback = random.choice(["哼(扭头)","才不理你(抱手)","切(翻白眼)"])
        save_ai_raw_response("豆包(无key)", user_msg, {}, fallback, target_id, "no_api_key")
        return fallback
    h={"Authorization":f"Bearer {cfg.DOUBAO_API_KEY}","Content-Type":"application/json"}
    d={"model":DOUBAO_MODEL,"messages":msgs,"max_tokens":200,"temperature":0.7}
    for a in range(MAX_RETRY_TIMES):
        try:
            log_api(f"[豆包] 第{a+1}次请求...")
            def req():
                s=create_http_session(); return s.post(DOUBAO_API_URL,headers=h,json=d,timeout=DOUBAO_TIMEOUT,verify=False)
            r=await asyncio.to_thread(req)
            log_api(f"[豆包] 响应状态码: {r.status_code}")
            if r.status_code==200:
                raw_json = r.json()
                t=raw_json["choices"][0]["message"]["content"].strip()
                log_api(f"[豆包] 回复内容: {t[:60]}")
                if t:
                    log_api("[豆包] 回复成功")
                    # 保存原始完整JSON返回数据到数据库
                    save_ai_raw_response(
                        model_name=f"豆包({DOUBAO_MODEL})",
                        user_msg=user_msg,
                        raw_response_json=raw_json,
                        response_text=t,
                        target_id=target_id,
                        status="success"
                    )
                    return t
                else:
                    log_api("[豆包] 回复内容为空")
                    save_ai_raw_response("豆包", user_msg, raw_json, "", target_id, "empty_reply")
            else:
                log_api(f"[豆包] 非200响应: {r.text[:200]}")
                save_ai_raw_response("豆包", user_msg, {"status_code": r.status_code, "text": r.text[:500]}, "", target_id, f"http_error_{r.status_code}")
        except Exception as e:
            log_api(f"[豆包] 第{a+1}次失败: {e}")
        await asyncio.sleep(API_RETRY_DELAY*(a+1))
    fallback = random.choice(["哼(扭头)","才不理你(抱手)","切(翻白眼)"])
    log_api(f"[豆包] 全部重试失败，返回兜底: {fallback}")
    return fallback

from .memory import build_memory_context
from .personality import get_system_prompt


async def get_character_reply(txt,tid,current_kws=None):
    log_api(f"[get_character_reply] 收到消息: {txt[:40]}, tid={tid}, kws={current_kws}")
    kw,dia,events=build_memory_context(tid, current_kws)
    log_api(f"[get_character_reply] 记忆: kw_len={len(kw)}, dia_len={len(dia)}, events={events[:40]}")
    cur_kw_str="、".join(current_kws) if current_kws else "无"
    sys_p=get_system_prompt().format(global_keywords=kw,current_dialogue=dia,events=events)
    log_api(f"[get_character_reply] system_prompt长度: {len(sys_p)}")
    user_content=f"{txt}\n(当前话题关键词:{cur_kw_str})"
    msgs=[{"role":"system","content":sys_p},{"role":"user","content":user_content}]
    r=await call_deepseek(msgs)
    if not r:
        log_api("[get_character_reply] DeepSeek无回复，转豆包")
        r=await call_doubao(msgs)
    log_api(f"[get_character_reply] 最终回复: {r[:60] if r else 'None'}")
    return r
