# ===================== 大模型调用模块 =====================
# DeepSeek + 豆包 双模型兜底，自动重试，保存原始返回数据

import asyncio  # 异步IO
import random  # 随机选择兜底回复

from .config import DS_API_URL, DS_MODEL, DS_TIMEOUT, DOUBAO_API_URL, DOUBAO_MODEL, DOUBAO_TIMEOUT, API_RETRY_DELAY, MAX_RETRY_TIMES  # API配置
from .log import log_api, log_err, log_system  # 日志
from .utils import create_http_session  # HTTP会话
from .db import save_ai_raw_response  # 保存AI原始返回数据
import botv.config as cfg  # 全局运行时变量


def _extract_user_msg(msgs):
    """从消息列表中提取用户消息内容（截断前500字符）"""
    for m in msgs:  # 遍历消息列表
        if m.get("role") == "user":  # 找到用户消息
            return m.get("content", "")[:500]  # 返回内容（截断）
    return ""  # 未找到返回空字符串


def _extract_target_id(msgs):
    """从消息中提取目标ID（取user消息末尾的tid信息，截断前80字符）"""
    user_content = _extract_user_msg(msgs)  # 获取用户消息内容
    return user_content[:80] if user_content else ""  # 截断前80字符作为ID


async def call_deepseek(msgs, retry=2):
    """调用DeepSeek API，支持重试，返回回复文本或None"""
    log_api(f"[DS] 开始调用, model={DS_MODEL}, 消息数={len(msgs)}, key={'有' if cfg.DS_API_KEY else '无'}")  # 日志记录调用信息
    if not cfg.DS_API_KEY:  # 无API密钥
        log_api("[DS] 无API key，跳过")  # 日志记录
        return None  # 返回None
    h={"Authorization":f"Bearer {cfg.DS_API_KEY}","Content-Type":"application/json"}  # 请求头：Bearer认证
    d={"model":DS_MODEL,"messages":msgs,"max_tokens":200,"temperature":0.7}  # 请求体：模型、消息、最大token、温度
    user_msg = _extract_user_msg(msgs)  # 提取用户消息
    target_id = _extract_target_id(msgs)  # 提取目标ID
    for a in range(retry):  # 重试循环
        try:
            log_api(f"[DS] 第{a+1}次请求...")  # 日志记录重试次数
            def req():
                """同步HTTP请求函数（在子线程中运行）"""
                s=create_http_session()  # 创建HTTP会话
                return s.post(DS_API_URL, headers=h, json=d, timeout=DS_TIMEOUT, verify=False)  # POST请求
            r=await asyncio.to_thread(req)  # 在子线程中执行，避免阻塞事件循环
            log_api(f"[DS] 响应状态码: {r.status_code}")  # 日志记录状态码
            if r.status_code==200:  # 请求成功
                raw_json = r.json()  # 解析JSON
                t=raw_json["choices"][0]["message"]["content"].strip()  # 提取回复文本
                log_api(f"[DS] 回复内容: {t[:60]}")  # 日志记录回复前60字符
                if t:  # 回复非空
                    log_api("[DS] 回复成功")  # 日志记录成功
                    # 保存原始完整JSON返回数据到数据库
                    save_ai_raw_response(
                        model_name=f"DeepSeek({DS_MODEL})",  # 模型名称
                        user_msg=user_msg,  # 用户消息
                        raw_response_json=raw_json,  # 完整JSON
                        response_text=t,  # 回复文本
                        target_id=target_id,  # 目标ID
                        status="success"  # 状态：成功
                    )
                    return t  # 返回回复文本
                else:  # 回复为空
                    log_api("[DS] 回复内容为空")  # 日志记录
                    save_ai_raw_response("DeepSeek", user_msg, raw_json, "", target_id, "empty_reply")  # 保存空回复记录
            else:  # 非200状态码
                log_api(f"[DS] 非200响应: {r.text[:200]}")  # 日志记录错误信息
                save_ai_raw_response("DeepSeek", user_msg, {"status_code": r.status_code, "text": r.text[:500]}, "", target_id, f"http_error_{r.status_code}")  # 保存错误记录
        except Exception as e:  # 捕获异常
            log_api(f"[DS] 第{a+1}次失败: {e}")  # 日志记录异常
        await asyncio.sleep(API_RETRY_DELAY*(a+1))  # 指数退避等待
    log_api("[DS] 全部重试失败，返回None")  # 所有重试都失败
    return None  # 返回None


async def call_doubao(msgs):
    """调用豆包API，支持重试，失败时返回随机兜底回复"""
    log_api(f"[豆包] 开始调用, model={DOUBAO_MODEL}, key={'有' if cfg.DOUBAO_API_KEY else '无'}")  # 日志记录调用信息
    user_msg = _extract_user_msg(msgs)  # 提取用户消息
    target_id = _extract_target_id(msgs)  # 提取目标ID
    if not cfg.DOUBAO_API_KEY:  # 无API密钥
        log_api("[豆包] 无API key，返回默认回复")  # 日志记录
        fallback = random.choice(["哼(扭头)","才不理你(抱手)","切(翻白眼)"])  # 随机选择兜底回复
        save_ai_raw_response("豆包(无key)", user_msg, {}, fallback, target_id, "no_api_key")  # 保存无key记录
        return fallback  # 返回兜底回复
    h={"Authorization":f"Bearer {cfg.DOUBAO_API_KEY}","Content-Type":"application/json"}  # 请求头：Bearer认证
    d={"model":DOUBAO_MODEL,"messages":msgs,"max_tokens":200,"temperature":0.7}  # 请求体
    for a in range(MAX_RETRY_TIMES):  # 重试循环（最大重试次数）
        try:
            log_api(f"[豆包] 第{a+1}次请求...")  # 日志记录重试次数
            def req():
                """同步HTTP请求函数（在子线程中运行）"""
                s=create_http_session()  # 创建HTTP会话
                return s.post(DOUBAO_API_URL, headers=h, json=d, timeout=DOUBAO_TIMEOUT, verify=False)  # POST请求
            r=await asyncio.to_thread(req)  # 在子线程中执行
            log_api(f"[豆包] 响应状态码: {r.status_code}")  # 日志记录状态码
            if r.status_code==200:  # 请求成功
                raw_json = r.json()  # 解析JSON
                t=raw_json["choices"][0]["message"]["content"].strip()  # 提取回复文本
                log_api(f"[豆包] 回复内容: {t[:60]}")  # 日志记录回复前60字符
                if t:  # 回复非空
                    log_api("[豆包] 回复成功")  # 日志记录成功
                    # 保存原始完整JSON返回数据到数据库
                    save_ai_raw_response(
                        model_name=f"豆包({DOUBAO_MODEL})",  # 模型名称
                        user_msg=user_msg,  # 用户消息
                        raw_response_json=raw_json,  # 完整JSON
                        response_text=t,  # 回复文本
                        target_id=target_id,  # 目标ID
                        status="success"  # 状态：成功
                    )
                    return t  # 返回回复文本
                else:  # 回复为空
                    log_api("[豆包] 回复内容为空")  # 日志记录
                    save_ai_raw_response("豆包", user_msg, raw_json, "", target_id, "empty_reply")  # 保存空回复记录
            else:  # 非200状态码
                log_api(f"[豆包] 非200响应: {r.text[:200]}")  # 日志记录错误信息
                save_ai_raw_response("豆包", user_msg, {"status_code": r.status_code, "text": r.text[:500]}, "", target_id, f"http_error_{r.status_code}")  # 保存错误记录
        except Exception as e:  # 捕获异常
            log_api(f"[豆包] 第{a+1}次失败: {e}")  # 日志记录异常
        await asyncio.sleep(API_RETRY_DELAY*(a+1))  # 指数退避等待
    fallback = random.choice(["哼(扭头)","才不理你(抱手)","切(翻白眼)"])  # 所有重试失败，随机选择兜底回复
    log_api(f"[豆包] 全部重试失败，返回兜底: {fallback}")  # 日志记录
    return fallback  # 返回兜底回复


from .memory import build_memory_context  # 构建对话上下文
from .personality import get_system_prompt  # 获取系统提示词


async def get_character_reply(txt, tid, current_kws=None):
    """核心函数：获取角色回复，优先DeepSeek，失败时降级到豆包"""
    log_api(f"[get_character_reply] 收到消息: {txt[:40]}, tid={tid}, kws={current_kws}")  # 日志记录输入
    kw, dia, events = build_memory_context(tid, current_kws)  # 构建对话上下文（关键词、对话历史、事件）
    log_api(f"[get_character_reply] 记忆: kw_len={len(kw)}, dia_len={len(dia)}, events={events[:40]}")  # 日志记录上下文信息
    cur_kw_str = "、".join(current_kws) if current_kws else "无"  # 当前话题关键词（顿号分隔）
    sys_p = get_system_prompt().format(global_keywords=kw, current_dialogue=dia, events=events)  # 格式化系统提示词
    log_api(f"[get_character_reply] system_prompt长度: {len(sys_p)}")  # 日志记录提示词长度
    user_content = f"{txt}\n(当前话题关键词:{cur_kw_str})"  # 构建用户消息（追加当前话题关键词）
    msgs = [{"role":"system","content":sys_p}, {"role":"user","content":user_content}]  # 构建消息列表
    r = await call_deepseek(msgs)  # 优先调用DeepSeek
    if not r:  # DeepSeek无回复
        log_api("[get_character_reply] DeepSeek无回复，转豆包")  # 日志记录降级
        r = await call_doubao(msgs)  # 降级到豆包
    log_api(f"[get_character_reply] 最终回复: {r[:60] if r else 'None'}")  # 日志记录最终回复
    return r  # 返回回复文本
