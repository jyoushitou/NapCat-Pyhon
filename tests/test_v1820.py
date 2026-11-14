# ===================== v18.20 收尾 =====================

import sys
import types
import unittest


def _stub_missing_deps():
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


_stub_missing_deps()


class TestV1820(unittest.TestCase):
    def test_fullwidth_command(self):
        from bot.commands import normalize_command

        self.assertEqual(normalize_command("！version"), "!version")
        self.assertEqual(normalize_command("！cron：list，x"), "!cron:list,x")

    def test_normal_chat_untouched(self):
        from bot.commands import normalize_command

        self.assertEqual(normalize_command("今天好累，想睡"), "今天好累，想睡")
        self.assertEqual(normalize_command("！？"), "!?")

    def test_version_bumped(self):
        from bot.core import version

        self.assertEqual(version.VERSION, "23.5.0")


if __name__ == "__main__":
    unittest.main()




