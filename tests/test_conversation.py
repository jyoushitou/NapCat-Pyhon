# ===================== v19.1 对话消息仓储 =====================
import unittest

from bot.infra import repo_conversation as R


class _Cursor:
    def __init__(self, rows=None):
        self.statements = []
        self.rows = rows or []
        self.connection = self
        self.rowcount = 0

    def execute(self, sql, params=None):
        self.statements.append((" ".join(str(sql).split()), params))
        return self

    def fetchall(self):
        return self.rows

    def commit(self):
        pass

    def rollback(self):
        pass


class TestConversationRepo(unittest.TestCase):
    def test_schema_has_table(self):
        from bot.infra import schema

        self.assertIn("conversation_messages", schema.TABLES)
        ddl = schema.TABLES["conversation_messages"]
        self.assertIn("uk_channel_msg", ddl)
        self.assertIn("idx_target_time", ddl)

    def test_append_uses_dedupe_and_meta(self):
        orig = R._backend
        R._backend = lambda: "sqlite"
        c = _Cursor()
        try:
            ok = R.append(target_id="1", content="你好", role="user",
                          message_id=9, meta={"images": ["x"]}, cursor=c)
        finally:
            R._backend = orig
        self.assertTrue(ok)
        sql, params = c.statements[0]
        self.assertIn("INSERT OR IGNORE", sql)
        self.assertEqual(params[0], "__owner__")
        self.assertEqual(params[6], "你好")
        self.assertIn('"images"', params[8])

    def test_recent_reverses_to_time_order(self):
        c = _Cursor(rows=[{"id": 3}, {"id": 2}, {"id": 1}])
        rows = R.recent("1", limit=3, cursor=c)
        self.assertEqual([r["id"] for r in rows], [1, 2, 3])
        sql, params = c.statements[0]
        self.assertIn("ORDER BY id DESC", sql)
        self.assertEqual(params[-1], 3)

    def test_cleanup_deletes_old_and_extra(self):
        c = _Cursor(rows=[])
        c.rows = [{"user_id": "__owner__", "target_id": "1"}]
        # 第一次 fetchall 返回分组；随后查询多余 id 返回空
        orig_fetch = c.fetchall
        calls = {"n": 0}

        def fetch():
            calls["n"] += 1
            return orig_fetch() if calls["n"] == 1 else []

        c.fetchall = fetch
        n = R.cleanup(cursor=c)
        self.assertGreaterEqual(n, 0)
        sqls = " ".join(s for s, _ in c.statements)
        self.assertIn("DELETE FROM conversation_messages WHERE created_at", sqls)
        self.assertIn("OFFSET", sqls)


class TestRecentDefault(unittest.TestCase):
    def test_default_100(self):
        from bot.infra import repo_conversation as R

        c = _Cursor(rows=[])
        R.recent("1", cursor=c)
        self.assertEqual(c.statements[0][1][-1], 100)


if __name__ == "__main__":
    unittest.main()

