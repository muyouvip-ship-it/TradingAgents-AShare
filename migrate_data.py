#!/usr/bin/env python3
"""
将数据从SQLite迁移到PostgreSQL
"""

import sqlite3
import psycopg2
from psycopg2.extras import execute_batch
import os
from datetime import datetime

def get_sqlite_connection():
    """连接SQLite数据库"""
    sqlite_path = os.path.join(os.path.dirname(__file__), 'tradingagents.db')
    if not os.path.exists(sqlite_path):
        raise FileNotFoundError(f"SQLite数据库文件不存在: {sqlite_path}")
    
    return sqlite3.connect(sqlite_path)

def get_postgresql_connection():
    """连接PostgreSQL数据库"""
    return psycopg2.connect("postgresql://localhost/trading_agents")

def migrate_table(table_name, sqlite_conn, pg_conn):
    """迁移单个表的数据"""
    print(f"迁移表: {table_name}")
    
    # 从SQLite读取数据
    sqlite_cursor = sqlite_conn.cursor()
    sqlite_cursor.execute(f"SELECT * FROM {table_name}")
    rows = sqlite_cursor.fetchall()
    
    if not rows:
        print(f"  ⚠️  表 {table_name} 没有数据")
        return 0
    
    # 获取列名
    sqlite_cursor.execute(f"PRAGMA table_info({table_name})")
    columns = [col[1] for col in sqlite_cursor.fetchall()]
    
    # 构建INSERT语句
    placeholders = ', '.join(['%s'] * len(columns))
    column_names = ', '.join([f'"{col}"' for col in columns])
    insert_sql = f'INSERT INTO {table_name} ({column_names}) VALUES ({placeholders})'
    
    # 插入数据到PostgreSQL
    pg_cursor = pg_conn.cursor()
    
    try:
        execute_batch(pg_cursor, insert_sql, rows)
        pg_conn.commit()
        print(f"  ✅ 迁移 {len(rows)} 条记录")
        return len(rows)
    except Exception as e:
        pg_conn.rollback()
        print(f"  ❌ 迁移失败: {e}")
        return 0

def main():
    """主迁移函数"""
    print("开始数据迁移: SQLite → PostgreSQL")
    print("=" * 50)
    
    # 表迁移顺序（考虑外键依赖）
    tables = [
        'users',  # 用户表应该先迁移
        'user_llm_configs',
        'user_tokens',
        'watchlist_items',
        'reports',
        'scheduled_analyses',
        'imported_portfolio_positions',
        'email_verification_codes',
        'feedbacks',
        'sponsors',
        'version_stats'
    ]
    
    sqlite_conn = None
    pg_conn = None
    
    try:
        sqlite_conn = get_sqlite_connection()
        pg_conn = get_postgresql_connection()
        
        total_migrated = 0
        
        for table in tables:
            count = migrate_table(table, sqlite_conn, pg_conn)
            total_migrated += count
        
        print("=" * 50)
        print(f"✅ 数据迁移完成！总共迁移了 {total_migrated} 条记录")
        
        # 验证数据迁移
        print("\n验证数据迁移:")
        pg_cursor = pg_conn.cursor()
        for table in tables:
            pg_cursor.execute(f"SELECT COUNT(*) FROM {table}")
            count = pg_cursor.fetchone()[0]
            print(f"  {table}: {count} 条记录")
        
    except Exception as e:
        print(f"❌ 迁移过程中出现错误: {e}")
        raise
    finally:
        if sqlite_conn:
            sqlite_conn.close()
        if pg_conn:
            pg_conn.close()

if __name__ == '__main__':
    main()