# 大模型调用：DeepSeek + 豆包 双模型兜底
import asyncio, random
from .config import DS_API_KEY, DOUBAO_API_KEY, DS_API_URL, DS_MODEL, DS_TIMEOUT, DOUBAO_API_URL, DOUBAO_MODEL, DOUBAO_TIMEOUT, API_RETRY_DELAY, MAX_RETRY_TIMES
from .log import log_api, log_err
from .utils import create_http_session

async def call_deepseek(msgs,retry=2):
    if not DS_API_KEY: return None
    h={"Authorization":f"Bearer {DS_API_KEY}","Content-Type":"application/json"}
    d={"model":DS_MODEL,"messages":msgs,"max_tokens":80,"temperature":0.7}
    for a in range(retry):
        try:
            def req():
                s=create_http_session(); return s.post(DS_API_URL,headers=h,json=d,timeout=DS_TIMEOUT,verify=False)
            r=await asyncio.to_thread(req)
            if r.status_code==200:
                t=r.json()["choices"][0]["message"]["content"].strip()
                if t: log_api("DS回复"); return t
        except Exception as e: log_api(f"DS{a+1}失败:{e}")
        await asyncio.sleep(API_RETRY_DELAY*(a+1))
    return None

async def call_doubao(msgs):
    if not DOUBAO_API_KEY: return random.choice(["哼(扭头)","才不理你(抱手)","切(翻白眼)"])
    h={"Authorization":f"Bearer {DOUBAO_API_KEY}","Content-Type":"application/json"}
    d={"model":DOUBAO_MODEL,"messages":msgs,"max_tokens":80,"temperature":0.7}
    for a in range(MAX_RETRY_TIMES):
        try:
            def req():
                s=create_http_session(); return s.post(DOUBAO_API_URL,headers=h,json=d,timeout=DOUBAO_TIMEOUT,verify=False)
            r=await asyncio.to_thread(req)
            if r.status_code==200:
                t=r.json()["choices"][0]["message"]["content"].strip()
                log_api("豆包回复"); return t
        except Exception as e: log_api(f"豆包{a+1}失败:{e}")
        await asyncio.sleep(API_RETRY_DELAY*(a+1))
    return random.choice(["哼(扭头)","才不理你(抱手)","切(翻白眼)"])

async def get_character_reply(txt,tid,current_kws=None):
    kw,dia=build_memory_context(tid)
    # 当前关键词也喂给AI
    cur_kw_str="、".join(current_kws) if current_kws else "无"
    sys_p=get_system_prompt().format(global_keywords=kw,current_dialogue=dia)
    # 把当前关键词加入user消息
    user_content=f"{txt}\n(当前话题关键词:{cur_kw_str})"
    msgs=[{"role":"system","content":sys_p},{"role":"user","content":user_content}]
    r=await call_deepseek(msgs)
    if not r: r=await call_doubao(msgs)
    return r
