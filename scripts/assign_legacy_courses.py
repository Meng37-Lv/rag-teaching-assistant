"""Explicit, local-only legacy ownership operation. Never run automatically."""
from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.auth import AccountStore


def main():
    parser = argparse.ArgumentParser(description="显式将指定旧课程关联到账户；默认仅预览")
    parser.add_argument('--database', required=True)
    parser.add_argument('--account-id', required=True)
    parser.add_argument('--course-id', action='append', required=True)
    parser.add_argument('--apply', action='store_true', help='经过授权后显式执行关联')
    args = parser.parse_args()
    database = Path(args.database).resolve()
    if not database.is_file():
        parser.error('数据库不存在；不会创建新库')
    if not args.apply:
        connection = sqlite3.connect(database.as_uri() + '?mode=ro', uri=True)
        try:
            for course_id in args.course_id:
                row = connection.execute('SELECT id, name FROM courses WHERE id = ?', (course_id,)).fetchone()
                print('预览课程：', row or '课程不存在')
            print('目标账户：', args.account_id)
            print('未执行；只有授权后使用 --apply 才写入归属。')
        finally:
            connection.close()
        return
    AccountStore(database).assign_legacy(args.account_id, args.course_id)
    print('已关联指定课程；课程资料、历史和旧分数未改写。')


if __name__ == '__main__':
    main()
