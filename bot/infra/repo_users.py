# ===================== 账号 / 身份 / 角色（v23.0） =====================
# 单用户时代的主人是 __owner__；v23 引入 users/identities/roles。
# 所有函数不依赖 MySQL 方言：用 SELECT + INSERT/UPDATE，SQLite/MySQL 都能跑。

from ..log import log_api

OWNER_ID = "__owner__"
ROLES = {
    "owner": ("主人", "all"),
    "admin": ("管理员", "manage_users,read_all"),
    "user": ("普通用户", "chat,memory,ledger"),
}


def _close(c):
    try:
        c.close()
    except Exception:
        pass


def _get_cursor(cursor):
    if cursor is not None:
        return cursor, False
    from .conn import get_cursor
    return get_cursor(), True


def _one(c, sql, params):
    c.execute(sql, params)
    return c.fetchone()


def _insert_ignore(c, sql, params):
    """跨方言的 INSERT IGNORE / INSERT OR IGNORE"""
    try:
        from .conn import _resolve_backend
        sqlite = _resolve_backend() == "sqlite"
    except Exception:
        sqlite = False
    if sqlite:
        c.execute(sql.replace("INSERT IGNORE", "INSERT OR IGNORE"), params)
    else:
        c.execute(sql, params)


def ensure_defaults(cursor=None):
    """幂等：roles + owner 用户 + owner 的 QQ 身份"""
    from ..config import MASTER_QQ
    from . import tenant

    owner = tenant.owner_id()
    c, owned = _get_cursor(cursor)
    try:
        for name, (display, perms) in ROLES.items():
            _insert_ignore(
                c,
                "INSERT IGNORE INTO roles(name, display_name, permissions) VALUES(%s,%s,%s)",
                (name, display, perms))
        _insert_ignore(
            c,
            "INSERT IGNORE INTO users(id, nickname, role, status) VALUES(%s,%s,%s,%s)",
            (owner, "owner", "owner", "active"))
        if int(MASTER_QQ or 0) > 0:
            _insert_ignore(
                c,
                "INSERT IGNORE INTO identities(user_id, channel, external_id) VALUES(%s,%s,%s)",
                (owner, "qq", str(MASTER_QQ)))
        c.connection.commit()
        return True
    except Exception as e:
        try:
            c.connection.rollback()
        except Exception:
            pass
        log_api(f"[账号] 初始化失败: {e}")
        return False
    finally:
        if owned:
            _close(c)


def get(user_id, cursor=None):
    c, owned = _get_cursor(cursor)
    try:
        return _one(c, "SELECT id,nickname,password_hash,password_prompted,setup_code_hash,setup_expires_at,role,status,created_at FROM users WHERE id=%s",
                    (str(user_id),))
    finally:
        if owned:
            _close(c)


def create(user_id, nickname="", role="user", status="active", cursor=None):
    c, owned = _get_cursor(cursor)
    try:
        _insert_ignore(
            c,
            "INSERT IGNORE INTO users(id, nickname, role, status) VALUES(%s,%s,%s,%s)",
            (str(user_id), str(nickname or user_id), str(role), str(status)))
        c.connection.commit()
        return get(user_id, c)
    finally:
        if owned:
            _close(c)


def set_status(user_id, status, cursor=None):
    c, owned = _get_cursor(cursor)
    try:
        c.execute("UPDATE users SET status=%s WHERE id=%s", (str(status), str(user_id)))
        c.connection.commit()
        return c.rowcount > 0
    finally:
        if owned:
            _close(c)


def set_role(user_id, role, cursor=None):
    c, owned = _get_cursor(cursor)
    try:
        c.execute("UPDATE users SET role=%s WHERE id=%s", (str(role), str(user_id)))
        c.connection.commit()
        return c.rowcount > 0
    finally:
        if owned:
            _close(c)


def list_users(cursor=None):
    c, owned = _get_cursor(cursor)
    try:
        c.execute("SELECT id,nickname,role,status,created_at FROM users ORDER BY created_at")
        return list(c.fetchall() or [])
    finally:
        if owned:
            _close(c)


def bind_identity(user_id, channel, external_id, cursor=None):
    c, owned = _get_cursor(cursor)
    try:
        _insert_ignore(
            c,
            "INSERT IGNORE INTO identities(user_id, channel, external_id) VALUES(%s,%s,%s)",
            (str(user_id), str(channel), str(external_id)))
        c.connection.commit()
        return resolve_identity(channel, external_id, c) is not None
    finally:
        if owned:
            _close(c)


def resolve_identity(channel, external_id, cursor=None):
    c, owned = _get_cursor(cursor)
    try:
        c.execute(
            "SELECT user_id FROM identities WHERE channel=%s AND external_id=%s",
            (str(channel), str(external_id)))
        row = c.fetchone()
        return row["user_id"] if row else None
    finally:
        if owned:
            _close(c)


def identities_of(user_id, cursor=None):
    c, owned = _get_cursor(cursor)
    try:
        c.execute("SELECT channel,external_id,created_at FROM identities WHERE user_id=%s",
                  (str(user_id),))
        return list(c.fetchall() or [])
    finally:
        if owned:
            _close(c)


def create_invite(code, role="user", created_by=OWNER_ID, expires_at=None, cursor=None):
    c, owned = _get_cursor(cursor)
    try:
        _insert_ignore(
            c,
            "INSERT IGNORE INTO invites(code, role, created_by, expires_at) VALUES(%s,%s,%s,%s)",
            (str(code), str(role), str(created_by), expires_at))
        c.connection.commit()
        return True
    finally:
        if owned:
            _close(c)


def consume_invite(code, user_id, cursor=None):
    """核销邀请码；成功返回 role，失败返回 None"""
    c, owned = _get_cursor(cursor)
    try:
        c.execute(
            "SELECT role,used_by,expires_at FROM invites WHERE code=%s", (str(code),))
        row = c.fetchone()
        if not row or row.get("used_by"):
            return None
        if row.get("expires_at"):
            c.execute("SELECT CURRENT_TIMESTAMP AS now")
            # 交给上层/数据库比较太依赖时区；这里只做「已过期」由调用方预判
        role = row["role"]
        c.execute("UPDATE invites SET used_by=%s WHERE code=%s AND used_by IS NULL",
                  (str(user_id), str(code)))
        c.connection.commit()
        return role if c.rowcount > 0 else None
    finally:
        if owned:
            _close(c)

# ===================== 密码（v23.3） =====================
def hash_password(password):
    import hashlib
    import secrets
    salt = secrets.token_hex(16)
    iterations = 120000
    digest = hashlib.pbkdf2_hmac("sha256", str(password).encode("utf-8"),
                                 salt.encode("ascii"), iterations).hex()
    return f"pbkdf2${iterations}${salt}${digest}"


def verify_password(password, stored):
    import hashlib
    import hmac
    try:
        algo, iterations, salt, expected = str(stored or "").split("$", 3)
        if algo != "pbkdf2":
            return False
        digest = hashlib.pbkdf2_hmac("sha256", str(password).encode("utf-8"),
                                     salt.encode("ascii"), int(iterations)).hex()
        return hmac.compare_digest(digest, expected)
    except Exception:
        return False


def set_password(user_id, password, cursor=None):
    c, owned = _get_cursor(cursor)
    try:
        c.execute("UPDATE users SET password_hash=%s WHERE id=%s",
                  (hash_password(password), str(user_id)))
        c.connection.commit()
        return c.rowcount > 0
    finally:
        if owned:
            _close(c)


def create_with_password(user_id, password, nickname="", role="user", cursor=None):
    c, owned = _get_cursor(cursor)
    try:
        _insert_ignore(
            c,
            "INSERT IGNORE INTO users(id, nickname, password_hash, role, status) "
            "VALUES(%s,%s,%s,%s,%s)",
            (str(user_id), str(nickname or user_id), hash_password(password),
             str(role), "active"))
        c.connection.commit()
        return get(user_id, c)
    finally:
        if owned:
            _close(c)




# ===================== v23.5.1 QQ 入站身份 =====================
def ensure_qq_user(qq, cursor=None):
    """QQ 入站：有 identity 返回用户；没有就建 user_id=QQ、role=user。"""
    qq = str(qq)
    uid = resolve_identity("qq", qq, cursor)
    if uid:
        return get(uid, cursor)
    from . import tenant
    role = "owner" if tenant.is_owner(qq) else "user"
    user = create(qq, nickname=qq, role=role, cursor=cursor)
    bind_identity(qq, "qq", qq, cursor=cursor)
    return user


def is_owner_row(row):
    try:
        from . import tenant
        return bool(row) and tenant.is_owner(row.get("id"))
    except Exception:
        return bool(row) and row.get("role") == "owner"

# ===================== v23.5.2 首次 QQ 密码 =====================
def needs_password(row):
    return bool(row) and not row.get("password_hash")


def mark_password_prompted(user_id, cursor=None):
    c, owned = _get_cursor(cursor)
    try:
        c.execute("UPDATE users SET password_prompted=1 WHERE id=%s", (str(user_id),))
        c.connection.commit()
        return True
    finally:
        if owned:
            _close(c)


def finish_setup(user_id, password, cursor=None):
    c, owned = _get_cursor(cursor)
    try:
        c.execute("UPDATE users SET password_hash=%s, password_prompted=0, "
                  "setup_code_hash=NULL, setup_expires_at=NULL WHERE id=%s",
                  (hash_password(password), str(user_id)))
        c.connection.commit()
        return True
    finally:
        if owned:
            _close(c)



# ===================== v23.5.3 客户端首次 setup =====================
def create_client_user(qq, setup_code, ttl_sec=86400, cursor=None):
    """owner 发创建命令：预建客户端用户，只存 setup code hash。"""
    import datetime
    from ..config import CST

    uid = str(qq)
    expires = (datetime.datetime.now(CST) + datetime.timedelta(seconds=int(ttl_sec))
               ).strftime("%Y-%m-%d %H:%M:%S")
    c, owned = _get_cursor(cursor)
    try:
        _insert_ignore(
            c,
            "INSERT IGNORE INTO users(id, nickname, password_hash, role, status, "
            "setup_code_hash, setup_expires_at) VALUES(%s,%s,NULL,'user','active',%s,%s)",
            (uid, uid, hash_password(setup_code), expires))
        c.execute("UPDATE users SET setup_code_hash=%s, setup_expires_at=%s "
                  "WHERE id=%s AND password_hash IS NULL",
                  (hash_password(setup_code), expires, uid))
        c.connection.commit()
        bind_identity(uid, "qq", uid, c)
        return uid
    finally:
        if owned:
            _close(c)


def verify_setup_code(user_id, code, row=None):
    import datetime
    from ..config import CST

    row = row or get(user_id)
    if not row or not row.get("setup_code_hash"):
        return False
    if row.get("setup_expires_at"):
        try:
            exp = row["setup_expires_at"]
            if not isinstance(exp, datetime.datetime):
                exp = datetime.datetime.fromisoformat(str(exp))
            if exp.tzinfo is None:
                exp = exp.replace(tzinfo=CST)
            if exp < datetime.datetime.now(CST):
                return False
        except Exception:
            pass
    return verify_password(code, row["setup_code_hash"])


def verify_login(user_id, password, setup_code=None):
    """返回 (row, error)。首次无密码时必须 setup_code + 新密码。"""
    row = get(user_id)
    if not row:
        return None, "invalid_credentials"
    if row.get("status") != "active":
        return None, "banned"
    if needs_password(row):
        if not setup_code or not verify_setup_code(user_id, setup_code, row):
            return None, "password_setup_required"
        if len(str(password or "")) < 8:
            return None, "password_too_short"
        finish_setup(user_id, password)
        return get(user_id), None
    if not verify_password(password, row.get("password_hash")):
        return None, "invalid_credentials"
    return row, None
