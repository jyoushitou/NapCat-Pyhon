# ===================== 版本信息（v17.1） =====================
# 对话里用 `!version` 查当前跑的是哪个版本。
#
# 版本号来源（优先级从高到低）：
#   1. 环境变量 NAO_VERSION（部署时注入，比如镜像里）
#   2. git describe --tags（仓库目录里跑时有）
#   3. 内置常量 VERSION
#
# 只在启动时算一次，之后读缓存——别每问一次就 fork 一个 git。

import os
import platform
import subprocess
import sys
import time

VERSION = "23.5.0"         # 与 README / tag 对齐；发版时改这里
_started_at = time.time()
_cache = {}


def _git(*args):
    """跑一个 git 命令；失败返回空串"""
    try:
        out = subprocess.run(
            ["git", *args], capture_output=True, text=True, timeout=3,
            cwd=os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
        )
        return (out.stdout or "").strip() if out.returncode == 0 else ""
    except Exception:
        return ""


def get_version(force=False):
    """当前版本号，如 v17.0.0"""
    if not force and "version" in _cache:
        return _cache["version"]

    env = (os.getenv("NAO_VERSION") or "").strip()
    if env:
        ver = env if env.startswith("v") else f"v{env}"
    else:
        described = _git("describe", "--tags", "--always")
        if described.startswith("v"):
            ver = described
        elif described:
            ver = f"v{VERSION}+{described}"     # 不在 tag 上：v17.0.0+3a1b2c
        else:
            ver = f"v{VERSION}"

    _cache["version"] = ver
    return ver


def get_commit():
    """当前提交短哈希；不是 git 仓库返回空"""
    if "commit" not in _cache:
        _cache["commit"] = _git("rev-parse", "--short", "HEAD")
    return _cache["commit"]


def get_branch():
    if "branch" not in _cache:
        _cache["branch"] = _git("rev-parse", "--abbrev-ref", "HEAD")
    return _cache["branch"]


def uptime_seconds():
    return max(0.0, time.time() - _started_at)


def describe():
    """给 !version 用的多行文本"""
    ver = get_version()
    commit = get_commit()
    branch = get_branch()
    secs = int(uptime_seconds())
    days, rest = divmod(secs, 86400)
    hours, rest = divmod(rest, 3600)
    minutes = rest // 60
    if days:
        up = f"{days} 天 {hours} 小时"
    elif hours:
        up = f"{hours} 小时 {minutes} 分"
    else:
        up = f"{minutes} 分"

    lines = [f"🏷️ Hoshinoumi（REC） · 版本：{ver}"]
    if commit:
        lines.append(f"🔀 提交：{commit}" + (f"（{branch}）" if branch and branch != "HEAD" else ""))
    lines.append(f"⏱️ 已运行：{up}")
    lines.append(f"🐍 Python：{platform.python_version()} / {platform.system()} {platform.machine()}")
    try:
        from . import clock

        lines.append(f"🕐 时区：{clock.tz_label()}｜{clock.fmt_full()}")
    except Exception:
        pass
    return "\n".join(lines)




