#!/usr/bin/env python3
"""统一迁移入口（推荐部署第一步）

    python3 scripts/migrate.py            # 预览：还缺什么/有多少旧数据
    python3 scripts/migrate.py --apply    # 执行：建表 + 补列 + 迁数据 + 场景 + 索引

幂等：已经迁过的库再跑只会补缺，不会重复搬数据。
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    sys.stdout.reconfigure(errors="replace")
except Exception:
    pass


def _preview(c):
    from bot.infra import schema
    from scripts import migrate_v18

    missing = schema.missing_tables(c)
    print(f"  缺表：{', '.join(missing) if missing else '无'}")
    if migrate_v18._table_exists(c, "events"):
        try:
            cols = migrate_v18._existing(c, "events")
            c.execute("SELECT COUNT(*) AS n FROM events")
            n = c.fetchone()["n"]
            print(f"  events 基表：{n} 行；缺列："
                  f"{', '.join(x for x in ('deleted_at', 'due_date', 'hit_count') if x not in cols) or '无'}")
        except Exception as e:
            print(f"  events 读取失败：{e}")
    else:
        print("  events：已是视图或不存在，无需数据迁移")
    mem = migrate_v18._existing(c, "memories")
    if mem:
        need = [x for x in ("weight", "tier", "due_date", "hit_count") if x not in mem]
        print(f"  memories 缺列：{', '.join(need) if need else '无'}")
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="真的执行（默认只看）")
    args = ap.parse_args()

    from bot.infra.conn import get_cursor

    c = get_cursor()
    try:
        print("=" * 56)
        print("  v18/v19 数据库迁移")
        print("=" * 56)
        print("当前：")
        if not args.apply:
            return _preview(c)

        from bot.infra import schema
        from scripts import migrate_indexes, migrate_v18, migrate_v23, migrate_v24, setup

        print("  [1/8] 建缺表")
        made = schema.ensure_tables(c, log=lambda m: print("        " + m))
        print(f"        新建 {len(made)} 张")

        print("  [2/8] 业务表 user_id / 索引 / 回填")
        made_u = migrate_v23.apply(c)
        print(f"        新增 user_id 列 {len(made_u)} 张")

        print("  [3/8] owner user_id → MASTER_QQ")
        migrated = migrate_v24.apply(c)
        print(f"        {migrated['old']} -> {migrated['new']}（{migrated['changed']} 行）")

        print("  [4/8] 账号底座（users/identities/roles）")
        from bot.infra import repo_users
        repo_users.ensure_defaults(c)
        print("        owner / roles 已就绪")

        print("  [5/8] 定时表补列 / 场景规则")
        setup.ensure_cron_schema()

        print("  [6/8] v18.17 events → memories")
        rc = migrate_v18.upgrade(c)
        if rc:
            print("[X] 迁移中断，先别启动")
            return rc

        # v21.4：events 已迁到 memories；旧库若还留着兼容视图，迁移时删掉
        try:
            c.execute("DROP VIEW IF EXISTS events")
            c.connection.commit()
            print("        events 兼容视图已移除")
        except Exception as e:
            print(f"        events 视图清理跳过：{e}")

        print("  [7/8] 索引")
        try:
            migrate_indexes.apply(c)
        except Exception as e:
            print(f"  [!] 索引补齐失败（不影响启动，可跳过后重试）：{e}")

        print("  [8/8] 内置场景")
        setup.seed_scenes()

        from bot.infra import repo_meta
        repo_meta.set_value("schema_version", "27")
        print("        schema_version=27")
        print("\n[OK] 迁移完成，下一步：python3 checks/env_check.py")
        return 0
    finally:
        try:
            c.close()
        except Exception:
            pass


if __name__ == "__main__":
    sys.exit(main())

