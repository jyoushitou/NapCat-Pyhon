# 冒烟测试：能启动、命令齐全、状态可注入

import sys
import types
import unittest


def _stub_missing_deps():
    """缺依赖就打个桩（必须在导入 bot 之前调用）"""
    def module(name, **attrs):
        m = types.ModuleType(name)
        for k, v in attrs.items():
            setattr(m, k, v)
        sys.modules[name] = m
        return m

    try:
        import pymysql  # noqa: F401
    except ImportError:
        module("pymysql")
        module("pymysql.cursors", DictCursor=object)
        sys.modules["pymysql"].cursors = sys.modules["pymysql.cursors"]
        sys.modules["pymysql"].connect = lambda **kw: None

    for name, attrs in (("jieba", {"lcut": lambda s: list(s)}), ("PIL", {"Image": None})):
        try:
            __import__(name)
        except ImportError:
            module(name, **attrs)

    try:
        import requests  # noqa: F401
    except ImportError:
        module("requests", Session=lambda: None, get=lambda *a, **k: None,
               post=lambda *a, **k: None)


_stub_missing_deps()


import sys
import types
import unittest
from datetime import datetime
from bot.config import CST
import asyncio
import time
import os
import re
import threading
import json
from bot.ports import ChatModel, Transport  # noqa: E402
from bot.ports.models import ChatRequest, ChatReply  # noqa: E402
from bot.ports.transport import Target, Segment  # noqa: E402
from bot.ai import models as model_mod  # noqa: E402
from bot.ai.chain import FallbackChain  # noqa: E402
from bot.chat.transport import QqTransport  # noqa: E402
from bot.core import state as cfg             # noqa: E402  运行时状态（常量也在里面）
import bot.commands as commands               # noqa: E402
import bot.chat.reply as reply_mod            # noqa: E402
from bot.ai.parse import parse_ai_reply       # noqa: E402
from bot.cmd import registry                  # noqa: E402


class FakeConn:
    """假连接：记录 open/ping 行为"""

    def __init__(self, healthy=True):
        self.open = healthy
        self.pinged = 0
        self.closed = False

    def ping(self, reconnect=False):
        self.pinged += 1
        if not self.open:
            raise RuntimeError("连接已断")

    def cursor(self):
        return FakeCursor(self)

    def close(self):
        self.closed = True
        self.open = False

class FakeCursor:
    def __init__(self, conn):
        self.connection = conn
        self.closed = False

    def close(self):
        self.closed = True

class FakeWS:
    def __init__(self):
        self.sent = []

    async def send(self, payload):
        self.sent.append(payload)

    def texts(self):
        """把已发送的报文里的文本段拼出来（命令测试用）"""
        out = []
        for payload in self.sent:
            try:
                d = json.loads(payload)
            except Exception:
                out.append(str(payload))
                continue
            msg = (d.get("params") or {}).get("message") or []
            out.append("".join(
                (seg.get("data") or {}).get("text", "")
                for seg in msg if seg.get("type") == "text"
            ))
        return out

class _FakeCursor:
    """够用的假游标：记录执行过哪些语句"""

    def __init__(self, first_row=None):
        self.first_row = first_row
        self.statements = []

    def execute(self, sql, params=None):
        self.statements.append((" ".join(str(sql).split()), params))

    def fetchone(self):
        return self.first_row

    def fetchall(self):
        return [self.first_row] if self.first_row else []

    @property
    def connection(self):
        return self

    def commit(self):
        pass

    def verbs(self):
        return [s[0].split()[0].upper() for s in self.statements]

class _FakeRandom:
    def __init__(self, value):
        self.value = value

    def random(self):
        return self.value

class _Resp:
    status_code = 200

    def json(self):
        return {"choices": [{"message": {"content": "她回了一句"}}]}

class _Session:
    def post(self, *a, **k):
        return _Resp()

def _at(hour, minute=0):
    return datetime(2026, 11, 10, hour, minute, tzinfo=CST)

class TestCommandRegistry(unittest.TestCase):
    """命令注册表与分发"""

    EXPECTED = {
        "acg", "apikeys", "clear", "clip", "code", "db", "diary", "event",
        "exit", "help", "img", "keywords", "log", "memory", "ping", "quit",
        "reload", "say", "sayg", "set", "status", "sticker", "task",
        "uptime", "usage", "profile", "todo", "voice", "vision", "memorybook", "growth", "persona", "stats", "config", "version", "cron", "hooks", "backup", "meta", "history", "gw", "relation", "adduser",
    }

    def setUp(self):
        cfg.CODE_MODE = False

    def _run(self, text, uid=None):
        ws = FakeWS()
        uid = uid if uid is not None else str(cfg.MASTER_QQ)
        handled = asyncio.run(commands.handle_command(text, uid, ws, False, 0))
        return handled, ws

    def test_all_commands_registered(self):
        self.assertEqual(set(registry.COMMANDS), self.EXPECTED)

    def test_fullwidth_version(self):
        """v18.20：手机输入法打 ！version 也要有反应"""
        handled, ws = self._run("！version")
        self.assertTrue(handled)
        self.assertTrue(ws.texts(), "应返回版本信息")

    def test_help(self):
        handled, ws = self._run("!help")
        self.assertTrue(handled)
        self.assertIn("可用命令", ws.texts()[0])

    def test_ping(self):
        handled, ws = self._run("!ping")
        self.assertTrue(handled)
        self.assertIn("Pong", ws.texts()[0])

    def test_status(self):
        handled, ws = self._run("!status")
        self.assertIn("状态概览", ws.texts()[0])

    def test_unknown_command(self):
        handled, ws = self._run("!nope")
        self.assertTrue(handled)
        self.assertIn("未知命令", ws.texts()[0])

    def test_non_master_rejected(self):
        handled, ws = self._run("!help", uid="123456")
        self.assertTrue(handled)
        self.assertIn("只有主人", ws.texts()[0])

    def test_non_command_ignored(self):
        handled, ws = self._run("你好呀")
        self.assertFalse(handled)
        self.assertEqual(ws.sent, [])

class TestConcurrency(unittest.TestCase):
    """v6-E26：按对象分片锁 + 模型调用上限"""

    def setUp(self):
        cfg.target_locks.clear()

    def tearDown(self):
        cfg.target_locks.clear()

    def test_same_target_serialized(self):
        from bot.core.locks import get_target_lock
        st = {"active": 0, "peak": 0}

        async def run():
            async def worker():
                async with get_target_lock("x"):
                    st["active"] += 1
                    st["peak"] = max(st["peak"], st["active"])
                    await asyncio.sleep(0.01)
                    st["active"] -= 1
            await asyncio.gather(worker(), worker(), worker())

        asyncio.run(run())
        self.assertEqual(st["peak"], 1, "同一个人必须串行")

    def test_different_targets_parallel(self):
        from bot.core.locks import get_target_lock
        st = {"active": 0, "peak": 0}

        async def run():
            async def worker(tid):
                async with get_target_lock(tid):
                    st["active"] += 1
                    st["peak"] = max(st["peak"], st["active"])
                    await asyncio.sleep(0.02)
                    st["active"] -= 1
            await asyncio.gather(worker("a"), worker("b"), worker("c"))

        asyncio.run(run())
        self.assertEqual(st["peak"], 3, "三个人应该能并行")

    def test_cleanup_idle_locks(self):
        from bot.core import locks
        locks.get_target_lock("old")
        locks._last_used["old"] -= 700
        removed = locks.cleanup_idle_locks()
        self.assertGreaterEqual(removed, 1)
        self.assertNotIn("old", cfg.target_locks)

    def test_model_semaphore_limit(self):
        from bot.core import locks
        locks._model_sem = None  # 每个用例用新的信号量，避免跨事件循环
        st = {"active": 0, "peak": 0}

        async def run():
            sem = locks.model_semaphore()

            async def call():
                async with sem:
                    st["active"] += 1
                    st["peak"] = max(st["peak"], st["active"])
                    await asyncio.sleep(0.01)
                    st["active"] -= 1
            await asyncio.gather(*[call() for _ in range(12)])

        asyncio.run(run())
        self.assertEqual(st["peak"], locks.MAX_CONCURRENT_MODEL_CALLS)

class TestHeartbeatWatchdog(unittest.TestCase):
    """F6：心跳连续失败要主动断开"""

    def test_closes_after_failures(self):
        from bot import heartbeat as hb

        class BadWS:
            closed = False

            def __init__(self):
                self.closed_count = 0

            async def ping(self):
                raise RuntimeError("dead")

            async def close(self):
                self.closed = True
                self.closed_count += 1

        ws = BadWS()
        orig = hb.HEARTBEAT_INTERVAL
        hb.HEARTBEAT_INTERVAL = 0.01
        try:
            async def run():
                task = asyncio.create_task(hb.heartbeat_monitor("T", ws))
                await asyncio.sleep(0.1)
                task.cancel()
            asyncio.run(run())
        finally:
            hb.HEARTBEAT_INTERVAL = orig
        self.assertTrue(ws.closed)
        self.assertGreaterEqual(ws.closed_count, 1)

class TestImageGateRegression(unittest.TestCase):
    """回归：发图闸门关闭时，两条发图路径都不能绕过"""

    def _run(self, text, allow):
        import asyncio
        import bot.chat.reply as R
        calls = []
        orig = (R.get_best_image, R.extract_keywords, R.image_allowed, R.materialize_image)

        async def fake_get(kws, uid):
            calls.append(kws)
            return "/tmp/fake.jpg"

        R.get_best_image = fake_get
        R.extract_keywords = lambda t: ["猫"]
        R.image_allowed = lambda *a, **k: allow
        R.materialize_image = lambda p: p
        try:
            parts = asyncio.run(R.build_reply_message(text, "1"))
        finally:
            (R.get_best_image, R.extract_keywords, R.image_allowed,
             R.materialize_image) = orig
        return parts, calls

    def test_gate_closed_no_image(self):
        parts, calls = self._run("今天好累\n（趴下）\n关键词搜索图片用：猫,狗", allow=False)
        self.assertFalse(any(p[0] == "image" for p in parts), "闸门关了不能出图")
        self.assertEqual(calls, [], "闸门关了就不该去搜图")

    def test_gate_open_ai_keywords(self):
        parts, calls = self._run("今天好累\n（趴下）\n关键词搜索图片用：猫,狗", allow=True)
        self.assertTrue(any(p[0] == "image" for p in parts))
        self.assertTrue(calls)

    def test_gate_open_fallback(self):
        """AI 没给关键词时，兜底那条路也要受闸门控制"""
        parts, calls = self._run("今天好累\n（趴下）", allow=True)
        self.assertTrue(any(p[0] == "image" for p in parts))

    def test_gate_closed_fallback(self):
        parts, calls = self._run("今天好累\n（趴下）", allow=False)
        self.assertFalse(any(p[0] == "image" for p in parts))
        self.assertEqual(calls, [])

class TestOnlineNotice(unittest.TestCase):
    """F5：重连时上线通知不能重复刷"""

    def setUp(self):
        cfg.last_online_notice_ts = 0.0

    def tearDown(self):
        cfg.last_online_notice_ts = 0.0

    def test_first_call_claims(self):
        from bot.chat.handler import claim_online_notice
        self.assertTrue(claim_online_notice())

    def test_second_call_blocked(self):
        from bot.chat.handler import claim_online_notice
        self.assertTrue(claim_online_notice())
        self.assertFalse(claim_online_notice())

    def test_after_cooldown_allowed(self):
        from bot.chat.handler import claim_online_notice
        self.assertTrue(claim_online_notice())
        cfg.last_online_notice_ts -= 61  # 模拟 61 秒前
        self.assertTrue(claim_online_notice())

class TestOutbox(unittest.TestCase):
    """F6：断线期间的消息入队，重连后补发"""

    def setUp(self):
        cfg.pending_outbox.clear()

    def tearDown(self):
        cfg.pending_outbox.clear()

    def test_queue_when_disconnected(self):
        from bot.chat.send import send_private_msg
        ok = asyncio.run(send_private_msg(123, [{"type": "text", "data": {"text": "hi"}}], None))
        self.assertFalse(ok)
        self.assertEqual(len(cfg.pending_outbox), 1)

    def test_flush_after_reconnect(self):
        from bot.chat.send import send_private_msg, flush_outbox
        ws = FakeWS()
        asyncio.run(send_private_msg(123, [{"type": "text", "data": {"text": "a"}}], None))
        asyncio.run(send_private_msg(456, [{"type": "text", "data": {"text": "b"}}], None))
        sent = asyncio.run(flush_outbox(ws))
        self.assertEqual(sent, 2)
        self.assertEqual(len(cfg.pending_outbox), 0)
        self.assertEqual(len(ws.sent), 2)

    def test_flush_noop_when_empty(self):
        from bot.chat.send import flush_outbox
        self.assertEqual(asyncio.run(flush_outbox(FakeWS())), 0)

class TestPhotoMemory(unittest.TestCase):
    """v11-A9：她记住你发过的图"""

    def test_kind_registered(self):
        from bot.infra.repo_memory import KIND_LIMITS, DEFAULT_KINDS
        self.assertIn("photo", KIND_LIMITS, "photo 要有独立保留上限")
        self.assertIn("photo", DEFAULT_KINDS, "检索要能召回图片记忆")

    def test_photo_event_written_with_tags(self):
        import bot.infra.repo_memory as rm
        import bot.chat.inbound as inbound
        self.assertTrue(hasattr(inbound, "add_event_to_db"), "inbound 应导入 add_event_to_db")

    def test_kind_limit_value(self):
        from bot.infra.repo_memory import KIND_LIMITS
        self.assertGreaterEqual(KIND_LIMITS["photo"], 20)


class _Ev:
    """伪造的事件对象（只要 args/kind）"""

    def __init__(self, args=()):
        self.args = args
        self.kind = "proactive_tick"


class TestScheduleTick(unittest.TestCase):
    """v10.3：定时循环的两段逻辑，用假数据做代码级测试（不连 AI）"""

    def setUp(self):
        from datetime import datetime
        from bot.config import CST
        import bot.schedule.runner as R
        self.R = R
        self.now = datetime(2026, 11, 9, 20, 0, tzinfo=CST)
        self.sent = []
        self._orig = {}
        self._patch("get_character_reply", self._fake_reply)
        self._patch("send_short_reply", self._fake_send)
        self._patch("note_proactive", lambda: None)

    def tearDown(self):
        for name, fn in self._orig.items():
            if name.startswith("impulse."):
                import bot.life.impulse as IMP
                IMP.should_chat = fn
            else:
                setattr(self.R, name, fn)
        from bot.core import state as cfg
        cfg.daily_chat_trigger_times = []
        cfg.triggered_today.clear()

    def _patch(self, name, fn):
        self._orig.setdefault(name, getattr(self.R, name))
        setattr(self.R, name, fn)

    async def _fake_reply(self, prompt, tid):
        return "假回复"

    async def _fake_send(self, *args, **kwargs):
        self.sent.append(args)

    def test_module_exports(self):
        """回归：这几个名字必须在模块里（曾经漏 import 导致 NameError）"""
        for name in ("pending_due", "agenda_due_soon", "should_reach_out",
                     "note_proactive", "load_today_life", "describe_pending",
                     "finish_pending", "agenda_mark"):
            self.assertTrue(hasattr(self.R, name), f"runner 缺少 {name}")

    def test_throttle_var_is_local(self):
        """回归：节流变量不能是模块全局，否则函数内赋值会 UnboundLocalError"""
        self.assertFalse(hasattr(self.R, "_last_due_check"))

    def test_process_due_submits_agenda(self):
        """v17.1：process_due 只投递事件，生成由 worker 做"""
        import asyncio
        from bot.scheduler.dispatcher import Scheduler, set_scheduler

        sched = Scheduler()
        set_scheduler(sched)
        try:
            self._patch("agenda_due_soon", lambda m: [{"id": 7, "t": "面试"}])
            self._patch("pending_due", lambda now: [])
            self._patch("should_reach_out", lambda **kw: (True, "ok"))
            n = asyncio.run(self.R.process_due(self.now))
        finally:
            set_scheduler(None)

        self.assertEqual(n, 1, "投递成功算一条")
        self.assertEqual(sched.stats()["queue"]["total"], 1)
        ev = sched.queue.get_from((1, 2))
        self.assertEqual(ev.kind, "agenda_remind")
        self.assertEqual(ev.args[0], "面试")

    def test_process_due_blocked_by_gate(self):
        import asyncio
        self._patch("agenda_due_soon", lambda m: [{"id": 7, "t": "面试"}])
        self._patch("pending_due", lambda now: [])
        self._patch("should_reach_out", lambda **kw: (False, "深夜"))
        n = asyncio.run(self.R.process_due(self.now))
        self.assertEqual(n, 0)
        self.assertEqual(self.sent, [])

    def test_process_due_handles_pending(self):
        import asyncio
        self._patch("agenda_due_soon", lambda m: [])
        self._patch("pending_due", lambda now: [(3, {"k": "anchor", "t": "吃饭"})])
        self._patch("should_reach_out", lambda **kw: (True, "ok"))
        self._patch("finish_pending", lambda i: None)
        n = asyncio.run(self.R.process_due(self.now))
        self.assertEqual(n, 1)

    def _patch_should_chat(self, result):
        import bot.life.impulse as IMP
        self._orig["impulse.should_chat"] = IMP.should_chat
        IMP.should_chat = lambda **kw: result
        self._patch("load_today_life", lambda: [])
        self._patch("load_events_from_db", lambda *a, **k: [])

    def _run_proactive_tick(self, gate_result):
        """跑一次 proactive_tick（新执行器，v17.3）"""
        import asyncio

        import bot.executors.proactive as P
        from bot.scheduler.dispatcher import Scheduler, set_scheduler

        sched = Scheduler()
        set_scheduler(sched)
        orig = P.should_chat if hasattr(P, "should_chat") else None
        import bot.life.impulse as IMP

        orig_gate = IMP.should_chat
        IMP.should_chat = lambda **kw: gate_result
        orig_life = None
        try:
            import bot.infra.repo_memory as rm

            orig_life = rm.load_today_life
            rm.load_today_life = lambda: []
        except Exception:
            pass
        try:
            out = asyncio.run(P.handle_proactive_tick(_Ev()))
        finally:
            IMP.should_chat = orig_gate
            if orig_life is not None:
                import bot.infra.repo_memory as rm

                rm.load_today_life = orig_life
            set_scheduler(None)
        return out, sched

    def test_proactive_tick_fires(self):
        out, sched = self._run_proactive_tick((True, "想说话了", 0.1))
        self.assertTrue(out["ok"])
        self.assertEqual(sched.stats()["queue"]["event"], 1, "应投递一条发言事件")

    def test_proactive_tick_skipped_by_gate(self):
        out, sched = self._run_proactive_tick((False, "刚聊过", 0.0))
        self.assertFalse(out["ok"])
        self.assertEqual(out["reason"], "刚聊过")
        self.assertEqual(sched.stats()["queue"]["total"], 0)

    def test_proactive_tick_dedupes(self):
        """已在飞时第二次 tick 不会重复投递"""
        import asyncio

        import bot.executors.proactive as P
        from bot.scheduler.dispatcher import Scheduler, set_scheduler
        import bot.life.impulse as IMP

        sched = Scheduler()
        set_scheduler(sched)
        orig = IMP.should_chat
        IMP.should_chat = lambda **kw: (True, "ok", 0.3)
        try:
            first = asyncio.run(P.handle_proactive_tick(_Ev()))
            second = asyncio.run(P.handle_proactive_tick(_Ev()))
        finally:
            IMP.should_chat = orig
            set_scheduler(None)

        self.assertTrue(first["ok"])
        self.assertFalse(second["ok"], "同一个人不该重复投递")
        self.assertEqual(sched.stats()["queue"]["event"], 1)


class TestSingleInstance(unittest.TestCase):
    """v7-E32：单实例锁"""

    def setUp(self):
        import os
        # 放在仓库目录里：系统临时目录在沙箱下不可写
        root = os.path.dirname(os.path.dirname(__file__))
        self.path = os.path.join(root, f".test-lock-{os.getpid()}")

    def tearDown(self):
        import os
        from bot.core import single_instance as si
        si.release()
        try:
            os.remove(self.path)
        except OSError:
            pass

    def test_second_acquire_fails_then_release_works(self):
        from bot.core import single_instance as si
        self.assertTrue(si.acquire(self.path))
        self.assertFalse(si.acquire(self.path), "同一文件第二次必须拿不到")
        si.release()
        self.assertTrue(si.acquire(self.path), "释放后应该能重新拿到")

    def test_holder_pid_written(self):
        import os
        from bot.core import single_instance as si
        self.assertTrue(si.acquire(self.path))
        self.assertEqual(si.holder_pid(self.path), str(os.getpid()))

class TestStateInPrompt(unittest.TestCase):
    """v9-U4：状态渲染进 prompt"""

    def test_prompt_carries_state(self):
        import bot.ai.client as client
        import bot.memory.context as mem
        from bot.core import locks
        captured = {}

        async def fake_ds(msgs, max_tokens=None, target_id=None):
            captured["sys"] = msgs[0]["content"]
            return "好"

        from bot.core import lifeport

        orig = (client.call_deepseek, mem.load_events_from_db)
        client.call_deepseek = fake_ds
        mem.load_events_from_db = lambda *a, **k: []
        lifeport.register("state_line",
                          lambda tid: "她现在有点烦，困得不行，还有点想你")
        lifeport.register("touch_talk", lambda tid: None)
        locks._model_sem = None
        try:
            asyncio.run(client.get_character_reply("hi", "1"))
        finally:
            client.call_deepseek, mem.load_events_from_db = orig
            lifeport.unregister("state_line")
            lifeport.unregister("touch_talk")
        self.assertIn("有点烦", captured["sys"])
        self.assertIn("困得不行", captured["sys"])

class TestTimePerception(unittest.TestCase):
    """F7：prompt 里必须带当前时间"""

    def setUp(self):
        cfg.CODE_MODE = False

    def test_now_text_format(self):
        from datetime import datetime
        from bot.ai.prompt import now_text
        from bot.config import CST
        s = now_text(datetime(2026, 11, 8, 23, 30, tzinfo=CST))
        self.assertIn("2026年11月8日", s)
        self.assertIn("23:30", s)
        self.assertIn("深夜", s)

    def test_morning_period(self):
        from datetime import datetime
        from bot.ai.prompt import now_text
        from bot.config import CST
        s = now_text(datetime(2026, 11, 9, 7, 15, tzinfo=CST))
        self.assertIn("早上", s)

    def test_prompt_contains_now(self):
        import bot.ai.client as client
        import bot.memory.context as mem

        captured = {}

        async def fake_ds(msgs, max_tokens=None, target_id=None):
            captured["sys"] = msgs[0]["content"]
            return "好"

        orig_ds, orig_ev = client.call_deepseek, mem.load_events_from_db
        client.call_deepseek = fake_ds
        mem.load_events_from_db = lambda *a, **k: []
        try:
            asyncio.run(client.get_character_reply("hi", "1"))
        finally:
            client.call_deepseek = orig_ds
            mem.load_events_from_db = orig_ev

        self.assertIn("现在的时间", captured["sys"])
        self.assertNotIn("{now}", captured["sys"])
        self.assertRegex(captured["sys"], r"\d{4}年\d{1,2}月\d{1,2}日 周")

class TestV14Frequency(unittest.TestCase):
    """v14：发图择时 / @ 判断 / 主动频率自适应"""

    def setUp(self):
        from bot.core import state as cfg
        self.cfg = cfg
        cfg.proactive_adjust = 1.0
        cfg.proactive_pending = False
        import bot.chat.reply as R
        R._last_image_ts.clear()
        self.R = R

    def tearDown(self):
        self.cfg.proactive_adjust = 1.0
        self.cfg.proactive_pending = False
        self.R._last_image_ts.clear()

    # ---- B1 发图择时 ----
    def test_image_probability(self):
        class R:
            def __init__(self, v):
                self.v = v

            def random(self):
                return self.v

        self.assertFalse(self.R.image_allowed("1", False, R(0.99)))
        self.assertTrue(self.R.image_allowed("2", False, R(0.01)))

    def test_image_cooldown(self):
        class R:
            def __init__(self, v):
                self.v = v

            def random(self):
                return self.v

        self.assertTrue(self.R.image_allowed("3", False, R(0.0)))
        self.assertFalse(self.R.image_allowed("3", False, R(0.0)), "10 分钟内同一人只一张")

    def test_group_more_conservative(self):
        from bot.chat.reply import IMAGE_PROB, IMAGE_PROB_GROUP
        self.assertLess(IMAGE_PROB_GROUP, IMAGE_PROB)

    # ---- B2 主动频率自适应 ----
    def test_no_reply_lowers_frequency(self):
        import time
        from bot.life import impulse as I
        self.cfg.proactive_adjust = 1.0
        self.cfg.proactive_pending = True
        from datetime import datetime

        from bot.config import CST

        # 固定到白天：深夜会提前返回，测不到频率调整
        I.should_chat(now=datetime(2026, 11, 10, 15, 0, tzinfo=CST),
                      state={"lonely": 0.3, "mood": 0.0},
                      last_user_ts=0.0, last_proactive_ts=time.time() - 3600,
                      proactive_count=0, unanswered=0)
        self.assertLess(self.cfg.proactive_adjust, 1.0)
        self.assertEqual(self.cfg.proactive_pending, False)

    def test_reply_raises_frequency_back(self):
        from bot.life import impulse as I
        self.cfg.proactive_adjust = 0.5
        self.cfg.proactive_pending = True
        I.note_user_message()
        self.assertGreater(self.cfg.proactive_adjust, 0.5)
        self.assertLessEqual(self.cfg.proactive_adjust, 1.0)

    def test_adjust_floor(self):
        import time
        from bot.life import impulse as I
        self.cfg.proactive_adjust = 0.5
        for _ in range(5):
            self.cfg.proactive_pending = True
            I.should_chat(state={"lonely": 0.3}, last_user_ts=0.0,
                          last_proactive_ts=time.time() - 3600,
                          proactive_count=0, unanswered=0)
        self.assertGreaterEqual(self.cfg.proactive_adjust, 0.5)

class TestV14Parsing(unittest.TestCase):
    """v14：日程模糊说法 / 指代词误伤 / CLIP 停用"""

    def setUp(self):
        from datetime import datetime
        from bot.config import CST
        self.now = datetime(2026, 11, 9, 10, 30, tzinfo=CST)  # 周一

    def _when(self, text):
        from bot.life.agenda import parse_when
        return parse_when(text, self.now)

    def test_month_end(self):
        self.assertEqual(self._when("月底交报告").strftime("%m-%d"), "11-30")

    def test_next_month(self):
        self.assertEqual(self._when("下个月面试").strftime("%m-%d"), "12-01")

    def test_weekend(self):
        self.assertEqual(self._when("这周末出去玩").strftime("%m-%d"), "11-14")

    def test_next_weekend(self):
        self.assertEqual(self._when("下周末考试").strftime("%m-%d"), "11-21")

    def test_clip_disabled_text(self):
        from bot.cmd.formatters import format_clip_status
        from bot.core import state as cfg
        cfg.CLIP_ENABLED = False
        text = format_clip_status()
        self.assertIn("停用", text)

if __name__ == "__main__":
    unittest.main()

if __name__ == "__main__":
    unittest.main()



