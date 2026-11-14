# 她自己的生活：状态、事件、日记、关系、摩擦、习惯

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

class TestAgenda(unittest.TestCase):
    """v10-U10：日程时间解析"""

    NOW = None

    def setUp(self):
        from datetime import datetime
        from bot.config import CST
        self.now = datetime(2026, 11, 9, 10, 30, tzinfo=CST)  # 周一

    def _when(self, text):
        from bot.life.agenda import parse_when
        return parse_when(text, self.now)

    def test_tomorrow(self):
        self.assertEqual(self._when("明天上午交作业").strftime("%m-%d %H:%M"), "11-10 09:00")

    def test_day_after(self):
        self.assertEqual(self._when("后天晚上八点约会").strftime("%m-%d %H:%M"), "11-11 20:00")

    def test_weekday(self):
        self.assertEqual(self._when("周五下午三点面试").strftime("%m-%d %H:%M"), "11-13 15:00")

    def test_date(self):
        self.assertEqual(self._when("11月15日答辩").strftime("%m-%d %H:%M"), "11-15 09:00")

    def test_tonight_chinese_numeral(self):
        self.assertEqual(self._when("今晚九点开会").strftime("%m-%d %H:%M"), "11-09 21:00")

    def test_no_time(self):
        self.assertIsNone(self._when("你好呀"))

    def test_extract_needs_event_word(self):
        from bot.life.agenda import extract
        self.assertIsNone(extract("明天出去玩", self.now), "没有事件词不该记")
        self.assertIsNotNone(extract("明天面试", self.now))

    def test_extract_ignores_past(self):
        from bot.life.agenda import extract
        self.assertIsNone(extract("昨天面试", self.now))

    def test_past_today_ignored(self):
        from bot.life.agenda import extract
        self.assertIsNone(extract("今天上午九点开会", self.now), "已经过去的今天不记")

class TestDiaryReflow(unittest.TestCase):
    """v9-U11：日记压成记忆 + 情绪余韵"""

    DIARY = ("今天学生会开到很晚，散会时天都黑了。新来的干事又写错记录，我改到眼睛发酸。"
             "回家路上买了关东煮，小咪在门口等我。其实有点累，但还行。")

    def test_split_count(self):
        from bot.life.reflow import split_memories
        items = split_memories(self.DIARY)
        self.assertGreaterEqual(len(items), 2)
        self.assertLessEqual(len(items), 3)

    def test_split_truncates_long(self):
        from bot.life.reflow import split_memories
        items = split_memories("啊" * 200 + "。")
        self.assertTrue(items)
        self.assertTrue(all(len(i) <= 61 for i in items))

    def test_sentiment_signs(self):
        from bot.life.reflow import sentiment_bias
        self.assertLess(sentiment_bias("很累，很烦，什么都做错"), 0)
        self.assertGreater(sentiment_bias("很开心，顺利完成"), 0)

    def test_sentiment_capped(self):
        from bot.life.reflow import sentiment_bias
        self.assertLessEqual(abs(sentiment_bias("累烦难过冷" * 100)), 0.15)

    def test_reflow_writes_to_self(self):
        import bot.life.reflow as R
        import bot.infra.repo_memory as rm
        calls = []
        orig_add, orig_apply = rm.add_event_to_db, R._apply_bias
        rm.add_event_to_db = lambda tid, text, **k: calls.append((tid, text, k.get("kind")))
        R._apply_bias = lambda b: None
        try:
            n, _bias = R.reflow("2026-11-08", self.DIARY)
        finally:
            rm.add_event_to_db, R._apply_bias = orig_add, orig_apply
        self.assertGreaterEqual(n, 1)
        self.assertTrue(calls)
        self.assertTrue(all(c[0] == rm.STATE_TARGET and c[2] == "life" for c in calls))

class TestFriction(unittest.TestCase):
    """v13-U20：期待 → 失落 → 冷战 → 和好（有上限）"""

    def setUp(self):
        from bot.core import state as cfg
        self.cfg = cfg
        cfg.friction_states.clear()
        import bot.infra.repo_memory as rm
        self.rm = rm
        self._orig = (rm.load_friction, rm.save_friction)
        self.store = {}
        rm.load_friction = lambda tid: self.store.get(tid, "")
        rm.save_friction = lambda tid, p: self.store.__setitem__(tid, p) or True

    def tearDown(self):
        self.rm.load_friction, self.rm.save_friction = self._orig
        self.cfg.friction_states.clear()

    def _t(self, n=0):
        from datetime import datetime, timedelta
        from bot.config import CST
        return datetime(2026, 11, 9, 12, tzinfo=CST) + timedelta(hours=n)

    def test_expectation_and_letdown(self):
        from bot.life import friction as F
        F.note_expectation("1", "早点睡吧", self._t())
        self.assertEqual(F.phase("1", self._t()), "waiting")
        F.refresh("1", now=self._t(9))  # 超过 8 小时
        self.assertEqual(F.phase("1", self._t(9)), "letdown")

    def test_three_letdowns_start_cold_war(self):
        from bot.life import friction as F
        st = F.load("1")
        st["disappoint"] = 3
        F.save("1")
        F.refresh("1", now=self._t())
        self.assertEqual(F.phase("1", self._t()), "cold")

    def test_cold_war_auto_ends_in_a_day(self):
        from bot.life import friction as F
        st = F.load("1")
        st["disappoint"] = 3
        st["cold_ts"] = self._t().timestamp()
        F.save("1")
        self.assertEqual(F.phase("1", self._t(1)), "cold")
        F.refresh("1", now=self._t(25))
        self.assertEqual(F.phase("1", self._t(25)), "calm", "24 小时后必须自动和好")

    def test_apologize_ends_it(self):
        from bot.life import friction as F
        st = F.load("1")
        st["disappoint"] = 3
        st["cold_ts"] = self._t().timestamp()
        F.save("1")
        self.assertTrue(F.apologize("1"))
        self.assertEqual(F.phase("1"), "calm")

    def test_three_messages_end_cold_war(self):
        from bot.life import friction as F
        st = F.load("1")
        st["disappoint"] = 3
        st["cold_ts"] = self._t().timestamp()
        F.save("1")
        for _ in range(3):
            F.on_user_message("1", self._t())
        self.assertEqual(F.phase("1"), "calm")

    def test_grudge_weekly_limit(self):
        from bot.life import friction as F
        self.assertTrue(F.grudge_allowed("1", self._t()))
        self.assertFalse(F.grudge_allowed("1", self._t(24)), "一周只能一次")
        self.assertTrue(F.grudge_allowed("1", self._t(24 * 8)))

    def test_prompt_line_cold(self):
        from bot.life import friction as F
        st = F.load("1")
        st["cold_ts"] = self._t().timestamp()
        F.save("1")
        self.assertIn("生闷气", F.prompt_line("1", self._t()))

    def test_trail_off(self):
        from bot.life.friction import maybe_trail_off

        class R:
            def __init__(self, v):
                self.v = v

            def random(self):
                return self.v

        text = "今天好累\n不想动\n（趴下）"
        out = maybe_trail_off(text, R(0.0))
        self.assertTrue(out.endswith("算了。"))
        self.assertNotIn("（趴下）", out)
        self.assertEqual(maybe_trail_off(text, R(0.9)), text)
        self.assertEqual(maybe_trail_off("只有一句", R(0.0)), "只有一句")

    def test_is_sorry(self):
        from bot.life.friction import is_sorry
        self.assertTrue(is_sorry("对不起嘛"))
        self.assertFalse(is_sorry("在吗"))

class TestGrowth(unittest.TestCase):
    """v13-U21：成长轨迹 / 称呼演化 / 管你 / 惊喜"""

    def test_growth_registered(self):
        import bot.commands  # noqa: F401
        from bot.cmd import registry
        self.assertIn("growth", registry.COMMANDS)

    def test_addressing_changes_with_tier(self):
        import bot.life.relation as R
        orig = R.get
        try:
            R.get = lambda tid: 0.9
            close = R.addressing("1")
            R.get = lambda tid: 0.05
            stranger = R.addressing("1")
        finally:
            R.get = orig
        self.assertIn("笨蛋", close)
        self.assertNotIn("笨蛋", stranger)


    def test_pick_seed_surprise(self):
        """心情不差、没有生活事件、掷骰 < 0.05 → 惊喜分支（v17.3：测新执行器）"""
        import bot.executors.proactive as P

        orig_random = P.random.random
        orig_life = None
        try:
            import bot.infra.repo_memory as rm

            orig_life = rm.load_today_life
            rm.load_today_life = lambda: []
        except Exception:
            pass
        P.random.random = lambda: 0.01      # 分享 0.5 跳过，惊喜 0.05 命中
        try:
            seed, tag = P._pick_seed()
        finally:
            P.random.random = orig_random
            if orig_life is not None:
                import bot.infra.repo_memory as rm

                rm.load_today_life = orig_life

        self.assertEqual(tag, "惊喜")
        self.assertIn("逗他", seed)

    def test_pick_seed_shares_life(self):
        """有生活事件且掷骰命中 → 分享生活分支"""
        import bot.executors.proactive as P

        orig_random = P.random.random
        try:
            import bot.infra.repo_memory as rm

            orig_life = rm.load_today_life
            rm.load_today_life = lambda: ["今天下雨了"]
        except Exception:
            orig_life = None
        P.random.random = lambda: 0.1
        try:
            seed, tag = P._pick_seed()
        finally:
            P.random.random = orig_random
            if orig_life is not None:
                import bot.infra.repo_memory as rm

                rm.load_today_life = orig_life

        self.assertIn("分享生活", tag)
        self.assertIn("今天下雨了", seed)


class TestHabit(unittest.TestCase):
    """v12-A17：学口头禅"""

    def setUp(self):
        from bot.core import state as cfg
        cfg.habit_counters.clear()

    def tearDown(self):
        from bot.core import state as cfg
        cfg.habit_counters.clear()

    def test_ngrams_filters_stopwords(self):
        from bot.life.habit import ngrams
        pieces = ngrams("就是这样的")
        self.assertNotIn("就是", pieces)
        self.assertNotIn("这样", pieces)

    def test_ngrams_lengths(self):
        from bot.life.habit import ngrams
        for piece in ngrams("绝了绝了"):
            self.assertTrue(2 <= len(piece) <= 4, piece)

    def test_top_needs_three(self):
        from collections import Counter
        from bot.life.habit import top
        c = Counter()
        c["绝了"] = 2
        self.assertEqual(top(c), [], "不够 3 次不算")

    def test_top_prefers_short(self):
        """次数相同时优先短词，避免学出跨词边界的废词"""
        from collections import Counter
        from bot.life.habit import top
        c = Counter({"草了": 5, "草了草了": 5})
        picked = top(c)
        self.assertIn("草了", picked)
        self.assertNotIn("草了草了", picked, "互相包含的只留一个")

    def test_top_limits_three(self):
        from collections import Counter
        from bot.life.habit import top
        c = Counter({"甲甲": 5, "乙乙": 5, "丙丙": 5, "丁丁": 5})
        self.assertEqual(len(top(c)), 3)

    def test_learn_accumulates(self):
        import bot.life.habit as H
        for _ in range(4):
            H.learn("100", "绝了这也太草了")
        self.assertIn("绝了", H.phrases_for("100"))

    def test_describe(self):
        from bot.life.habit import describe
        self.assertEqual(describe([]), "")
        self.assertIn("绝了", describe(["绝了"]))

    def test_profile_with_habit(self):
        import bot.ai.client as client
        from bot.core import lifeport

        orig_build = client.build_profile_text
        lifeport.register("habit_line", lambda tid: "口头禅：绝了")
        client.build_profile_text = lambda tid: "昵称：小奈"
        try:
            text = client._profile_with_habit("1")
        finally:
            client.build_profile_text = orig_build
            lifeport.unregister("habit_line")
        self.assertIn("小奈", text)
        self.assertIn("绝了", text)

class TestImpulse(unittest.TestCase):
    """v10-U9：主动消息的六道闸门"""

    class _R:
        def __init__(self, v):
            self.v = v

        def random(self):
            return self.v

    NOW = None

    def setUp(self):
        from datetime import datetime
        from bot.config import CST
        self.now = datetime.now(CST).replace(hour=20, minute=0, second=0)
        self.cfg = __import__("bot.core.state", fromlist=["x"])
        self.cfg.last_user_msg_ts = 0.0
        self.cfg.last_proactive_ts = 0.0
        self.cfg.proactive_count_today = 0
        self.cfg.proactive_unanswered = 0

    def test_quiet_hours(self):
        from bot.life.impulse import should_reach_out
        ok, why = should_reach_out(now=self.now.replace(hour=2), state={"lonely": 0.9},
                                   rng=self._R(0.01))
        self.assertFalse(ok)
        self.assertEqual(why, "深夜")

    def test_just_talked(self):
        import time
        from bot.life.impulse import should_reach_out
        ok, why = should_reach_out(now=self.now, state={"lonely": 0.9},
                                   rng=self._R(0.01), last_user_ts=time.time() - 60)
        self.assertFalse(ok)
        self.assertEqual(why, "刚聊过")

    def test_not_lonely_enough(self):
        from bot.life.impulse import should_reach_out
        ok, _why = should_reach_out(now=self.now, state={"lonely": 0.2}, rng=self._R(0.01))
        self.assertFalse(ok)

    def test_probability_gate(self):
        from bot.life.impulse import should_reach_out
        ok_no, _ = should_reach_out(now=self.now, state={"lonely": 0.9}, rng=self._R(0.99))
        ok_yes, _ = should_reach_out(now=self.now, state={"lonely": 0.9}, rng=self._R(0.01))
        self.assertFalse(ok_no)
        self.assertTrue(ok_yes)

    def test_daily_cap(self):
        import time
        from bot.life.impulse import should_reach_out
        ok, why = should_reach_out(now=self.now, state={"lonely": 0.9}, rng=self._R(0.01),
                                   last_proactive_ts=time.time() - 3600, proactive_count=3)
        self.assertFalse(ok)
        self.assertEqual(why, "今日配额用完")

    def test_unanswered_backoff(self):
        from bot.life.impulse import should_reach_out
        ok, why = should_reach_out(now=self.now, state={"lonely": 0.9}, rng=self._R(0.01),
                                   unanswered=2)
        self.assertFalse(ok)
        self.assertEqual(why, "连续没回应")

    def test_note_counters(self):
        from bot.life.impulse import note_proactive, note_user_message
        note_proactive()
        note_proactive()
        self.assertEqual(self.cfg.proactive_count_today, 2)
        self.assertEqual(self.cfg.proactive_unanswered, 2)
        note_user_message()
        self.assertEqual(self.cfg.proactive_unanswered, 0)

class TestInsideJokes(unittest.TestCase):
    """v12-G37：内部梗（按标签频次）"""

    def test_counts_and_picks(self):
        from bot.life.inside_jokes import count_tags, pick_jokes
        rows = [{"tags": "猫,加班"}, {"tags": "猫"}, {"tags": "猫,加班"}, {"tags": "加班"}]
        jokes = pick_jokes(count_tags(rows))
        self.assertIn("猫", jokes)
        self.assertIn("加班", jokes)

    def test_threshold(self):
        from bot.life.inside_jokes import count_tags, pick_jokes
        rows = [{"tags": "面试"}, {"tags": "面试"}]
        self.assertEqual(pick_jokes(count_tags(rows)), [])

    def test_describe(self):
        from bot.life.inside_jokes import describe
        self.assertEqual(describe([]), "")
        self.assertIn("猫", describe(["猫"]))

    def test_bad_rows(self):
        from bot.life.inside_jokes import count_tags
        self.assertEqual(len(count_tags([{}, None, {"tags": ""}])), 0)

class TestLifeEvents(unittest.TestCase):
    """v9-U7：每日生活事件"""

    def test_count_in_range(self):
        from bot.life.events import generate, MIN_EVENTS, MAX_EVENTS
        for _ in range(30):
            n = len(generate())
            self.assertGreaterEqual(n, MIN_EVENTS)
            self.assertLessEqual(n, MAX_EVENTS)

    def test_no_dup_within_day(self):
        from bot.life.events import generate
        for _ in range(20):
            items = generate()
            self.assertEqual(len(items), len(set(items)))

    def test_all_from_pools(self):
        from bot.life.events import generate, POOLS
        all_texts = {t for _w, pool in POOLS for t in pool}
        for _ in range(20):
            for t in generate():
                self.assertIn(t, all_texts)

    def test_template_count(self):
        from bot.life.events import total_templates
        self.assertGreaterEqual(total_templates(), 100, "模板至少要 100 条")

    def test_grief_pool_is_low_weight(self):
        from bot.life.events import POOLS
        weights = [w for w, _pool in POOLS]
        self.assertEqual(POOLS[-1][0], min(weights), "关于他的模板权重应最低")

    def test_ensure_once_per_day(self):
        import bot.life.events as ev
        import bot.infra.repo_memory as rm
        from bot.core import state as cfg
        calls = []
        orig = rm.add_event_to_db
        rm.add_event_to_db = lambda tid, text, **k: calls.append((tid, text, k.get("kind")))
        try:
            cfg.life_last_date = {}
            n1 = ev.ensure_daily_life()
            n2 = ev.ensure_daily_life()
        finally:
            rm.add_event_to_db = orig
            cfg.life_last_date = {}
        self.assertGreaterEqual(n1, 1)
        self.assertEqual(n2, 0, "同一天第二次不应再写")
        self.assertTrue(all(c[2] == "life" for c in calls))

class TestLifeState(unittest.TestCase):
    """v9-U4：状态向量"""

    def test_default_in_range(self):
        from bot.life.state import default_state, CLAMP
        s = default_state()
        for k, (lo, hi) in CLAMP.items():
            self.assertGreaterEqual(s[k], lo)
            self.assertLessEqual(s[k], hi)

    def test_tick_moves_toward_base(self):
        from bot.life.state import tick, BASE
        s = {"mood": 0.9, "energy": 0.1, "lonely": 0.1}
        out = tick(s, 1)
        self.assertLess(out["mood"], 0.9)          # 高情绪向基线回落
        self.assertGreater(out["energy"], 0.1)     # 低精力向基线回升

    def test_tick_alone_increases_lonely(self):
        from bot.life.state import tick
        out = tick({"mood": 0.1, "energy": 0.7, "lonely": 0.2}, 5)
        self.assertGreater(out["lonely"], 0.2)

    def test_clamp_bounds(self):
        from bot.life.state import clamp
        s = clamp({"mood": 5, "energy": -3, "lonely": 99})
        self.assertLessEqual(s["mood"], 1.0)
        self.assertGreaterEqual(s["energy"], 0.0)
        self.assertLessEqual(s["lonely"], 1.0)

    def test_talk_relieves_lonely(self):
        from bot.life.state import on_talk
        s = {"mood": 0.0, "energy": 0.5, "lonely": 0.8}
        self.assertLess(on_talk(s)["lonely"], 0.8)

    def test_describe_has_no_numbers(self):
        from bot.life.state import describe
        text = describe({"mood": -0.7, "energy": 0.1, "lonely": 0.9})
        self.assertTrue(text.endswith("。"))
        self.assertFalse(any(ch.isdigit() for ch in text), f"不该出现数字: {text}")

    def test_json_roundtrip(self):
        from bot.life.state import to_json, from_json
        s = {"mood": 0.3, "energy": 0.6, "lonely": 0.2}
        back = from_json(to_json(s))
        for k, v in s.items():
            self.assertEqual(back[k], v)

    def test_from_json_garbage(self):
        from bot.life.state import from_json, default_state
        self.assertEqual(from_json("not json"), default_state())
        self.assertEqual(from_json(""), default_state())

class TestMilestone(unittest.TestCase):
    """v12-G38：认识第几天"""

    def setUp(self):
        import bot.life.milestone as M
        import bot.infra.repo_memory as rm
        self.M = M
        self.rm = rm
        self.store = {}
        self._orig = (rm.load_relation, rm.save_relation)
        rm.load_relation = lambda tid: self.store.get(tid, "")
        rm.save_relation = lambda tid, payload: self.store.__setitem__(tid, payload) or True

    def tearDown(self):
        self.rm.load_relation, self.rm.save_relation = self._orig

    def _day(self, n):
        from datetime import datetime, timedelta
        from bot.config import CST
        base = datetime(2026, 1, 1, tzinfo=CST)
        return base, base + timedelta(days=n)

    def test_first_call_records_since(self):
        base, _ = self._day(0)
        self.M.since_date("u1", base)
        self.assertIn("2026-01-01", self.store["u1"])

    def test_days_together(self):
        base, _ = self._day(0)
        self.M.since_date("u1", base)
        _, later = self._day(99)
        self.assertEqual(self.M.days_together("u1", later), 100)

    def test_milestones(self):
        base, _ = self._day(0)
        self.M.since_date("u1", base)
        for n, keyword in ((1, "第一天"), (7, "一周"), (30, "一个月"), (100, "一百天")):
            _, now = self._day(n - 1)
            text = self.M.milestone_text("u1", now)
            self.assertIn(keyword, text, f"第 {n} 天应提到 {keyword}")

    def test_normal_day_no_text(self):
        base, _ = self._day(0)
        self.M.since_date("u1", base)
        _, now = self._day(42)
        self.assertEqual(self.M.milestone_text("u1", now), "")

    def test_profile_includes_milestone(self):
        import bot.ai.client as client
        from bot.core import lifeport

        orig_build = client.build_profile_text
        lifeport.register("habit_line", lambda tid: "")
        lifeport.register("milestone_line",
                          lambda tid: "今天正好认识一百天（第 100 天）")
        client.build_profile_text = lambda tid: "昵称：小奈"
        try:
            text = client._profile_with_habit("1")
        finally:
            client.build_profile_text = orig_build
            lifeport.unregister("habit_line")
            lifeport.unregister("milestone_line")
        self.assertIn("一百天", text)

class TestPending(unittest.TestCase):
    """v10-U9b：承诺与时间锚点识别"""

    def test_promise(self):
        from bot.life.pending import detect
        items = detect("今天有点累，回头再说吧")
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["k"], "promise")

    def test_anchor(self):
        from bot.life.pending import detect
        items = detect("我先去吃饭了，等下聊")
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["k"], "anchor")
        self.assertEqual(items[0]["t"], "吃饭")

    def test_anchor_delay(self):
        from bot.life.pending import detect
        from datetime import datetime
        from bot.config import CST
        now = datetime(2026, 11, 9, 12, 0, tzinfo=CST)
        it = detect("去洗澡", now)[0]
        self.assertAlmostEqual(it["due"] - now.timestamp(), 25 * 60, delta=5)

    def test_promise_delay(self):
        from bot.life.pending import detect
        from datetime import datetime
        from bot.config import CST
        now = datetime(2026, 11, 9, 22, 0, tzinfo=CST)
        it = detect("改天聊", now)[0]
        self.assertAlmostEqual((it["due"] - now.timestamp()) / 3600, 20, delta=0.1)

    def test_plain_text_no_item(self):
        from bot.life.pending import detect
        self.assertEqual(detect("你好呀，在干嘛"), [])

    def test_not_both(self):
        """同一句话不该既记承诺又记锚点"""
        from bot.life.pending import detect
        items = detect("我去吃饭了，回头再说")
        self.assertLessEqual(len(items), 2)

    def test_describe(self):
        from bot.life.pending import describe
        self.assertIn("答应过", describe({"k": "promise", "s": "回头再说"}))
        self.assertIn("吃饭", describe({"k": "anchor", "t": "吃饭", "s": "去吃饭"}))

class TestRapport(unittest.TestCase):
    """v12-G51：够熟才允许接半句"""

    def _describe(self, aff):
        import bot.life.relation as R
        orig = R.get
        R.get = lambda tid: aff
        try:
            return R.describe("1")
        finally:
            R.get = orig

    def test_close_allows(self):
        self.assertIn("接下去", self._describe(0.8))

    def test_stranger_not(self):
        self.assertNotIn("接下去", self._describe(0.1))

    def test_tier_text_present(self):
        self.assertIn("亲近", self._describe(0.8))
        self.assertIn("陌生", self._describe(0.05))

class TestRelation(unittest.TestCase):
    """v10-U8：关系分档"""

    def test_tiers(self):
        from bot.life.relation import tier_of
        self.assertEqual(tier_of(0.9)[0], "亲近")
        self.assertEqual(tier_of(0.5)[0], "熟")
        self.assertEqual(tier_of(0.3)[0], "认识")
        self.assertEqual(tier_of(0.0)[0], "归零")

    def test_master_starts_higher(self):
        import bot.life.relation as R
        import bot.infra.repo_memory as rm
        from bot.config import MASTER_QQ
        orig = rm.load_relation
        rm.load_relation = lambda tid: ""
        try:
            a_master = R.get(str(MASTER_QQ))
            a_other = R.get("99999")
        finally:
            rm.load_relation = orig
        self.assertGreater(a_master, a_other)

    def test_describe_contains_tier(self):
        import bot.life.relation as R
        orig = R.get
        R.get = lambda tid: 0.8
        try:
            s = R.describe("1")
        finally:
            R.get = orig
        self.assertIn("亲近", s)
        self.assertNotIn("0.8", s, "数值不该出现在描述里")

    def test_tier_bounds(self):
        from bot.life.relation import TIERS
        lows = [lo for lo, _n, _d in TIERS]
        self.assertEqual(lows, sorted(lows, reverse=True))
        self.assertEqual(lows[-1], -1.0)

class TestV12Extras(unittest.TestCase):
    """v12：仪式 / 记忆本 / 旧事重提"""

    def test_sunday_ritual_task(self):
        from bot.executors.schedule import SCENES
        self.assertIn("周日复盘", SCENES, "周日晚上要有一次复盘仪式")

    def test_memorybook_registered(self):
        import bot.commands  # noqa: F401
        from bot.cmd import registry
        self.assertIn("memorybook", registry.COMMANDS)
    def test_pick_seed_old_event(self):
        """有旧事 → 旧事重提分支（v17.3：测新执行器的 _pick_seed）"""
        import bot.executors.proactive as P

        orig_random = P.random.random
        orig_life, orig_old = None, None
        try:
            import bot.infra.repo_memory as rm

            orig_life = rm.load_today_life
            orig_old = rm.load_old_events
            rm.load_today_life = lambda: []
            rm.load_old_events = lambda *a, **k: [
                {"summary": "去打疫苗", "day": "2026-10-01"}]
        except Exception:
            pass
        P.random.random = lambda: 0.1     # 惊喜不中，旧事命中
        try:
            seed, tag = P._pick_seed()
        finally:
            P.random.random = orig_random
            if orig_life is not None:
                import bot.infra.repo_memory as rm

                rm.load_today_life = orig_life
                rm.load_old_events = orig_old

        self.assertEqual(tag, "旧事")
        self.assertIn("去打疫苗", seed)


class TestWeather(unittest.TestCase):
    """v12-A21：天气（没配城市就完全跳过）"""

    def test_parse(self):
        from bot.life.weather import parse_j1
        data = {"current_condition": [{"temp_C": "12", "weatherDesc": [{"value": "小雨"}]}]}
        info = parse_j1(data)
        self.assertEqual(info["temp"], 12)
        self.assertEqual(info["desc"], "小雨")

    def test_parse_bad(self):
        from bot.life.weather import parse_j1
        self.assertIsNone(parse_j1({}))
        self.assertIsNone(parse_j1({"current_condition": []}))

    def test_describe(self):
        from bot.life.weather import describe
        self.assertEqual(describe(None), "")
        self.assertIn("12", describe({"temp": 12, "desc": "小雨"}))

    def test_no_city_returns_none(self):
        import asyncio
        from bot.life.weather import current
        import os
        old = os.environ.pop("NAO_CITY", None)
        try:
            self.assertIsNone(asyncio.run(current()))
        finally:
            if old is not None:
                os.environ["NAO_CITY"] = old

if __name__ == "__main__":
    unittest.main()

if __name__ == "__main__":
    unittest.main()

