#!/usr/bin/env python3
"""
修复数据类型后的数据迁移
"""

import sqlite3
import psycopg2
from psycopg2.extras import execute_batch
import os

def get_column_types(table_name, sqlite_cursor, pg_cursor):
    """获取两个数据库中的列类型"""
    # SQLite列信息
    sqlite_cursor.execute(f"PRAGMA table_info({table_name})")
    sqlite_cols = {row[1]: row[2] for row in sqlite_cursor.fetchall()}
    
    # PostgreSQL列信息
    pg_cursor.execute(f"""
        SELECT column_name, data_type 
        FROM information_schema.columns 
        WHERE table_name = '{table_name}' 
        ORDER BY ordinal_position
    """)
    pg_cols = {row[0]: row[1] for row in pg_cursor.fetchall()}
    
    return sqlite_cols, pg_cols

def convert_value(value, sqlite_type, pg_type):
    """根据类型转换值"""
    if value is None:
        return None
    
    # 布尔值转换：SQLite存储为0/1整数，PostgreSQL需要True/False
    if pg_type == 'boolean':
        if isinstance(value, int):
            return bool(value)
        elif isinstance(value, str):
            return value.lower() in ('true', '1', 't', 'yes', 'y')
    
    # JSON类型转换
    if pg_type in ('json', 'jsonb'):
        if isinstance(value, str):
            return value
    
    return value

def migrate_table_with_type_conversion(table_name, sqlite_conn, pg_conn):
    """迁移单个表的数据，处理类型转换"""
    print(f"迁移表: {table_name}")
    
    # 获取列信息
    sqlite_cursor = sqlite_conn.cursor()
    pg_cursor = pg_conn.cursor()
    
    sqlite_cols, pg_cols = get_column_types(table_name, sqlite_cursor, pg_cursor)
    
    if not sqlite_cols:
        print(f"  ⚠️  表 {table_name} 在SQLite中不存在")
        return 0
    
    # 从SQLite读取数据
    sqlite_cursor.execute(f"SELECT * FROM {table_name}")
    rows = sqlite_cursor.fetchall()
    
    if not rows:
        print(f"  ⚠️  表 {table_name} 没有数据")
        return 0
    
    # 获取列名（确保顺序一致）
    sqlite_cursor.execute(f"PRAGMA table_info({table_name})")
    columns = [col[1] for col in sqlite_cursor.fetchall()]
    
    # 转换数据
    converted_rows = []
    for row in rows:
        converted_row = []
        for i, (col_name, value) in enumerate(zip(columns, row)):
            if i < len(columns):
                sqlite_type = sqlite_cols.get(col_name, '')
                pg_type = pg_cols.get(col_name, '')
                converted_value = convert_value(value, sqlite_type, pg_type)
                converted_row.append(converted_value)
        converted_rows.append(tuple(converted_row))
    
    # 构建INSERT语句
    placeholders = ', '.join(['%s'] * len(columns))
    column_names = ', '.join([f'"{col}"' for col in columns])
    insert_sql = f'INSERT INTO {table_name} ({column_names}) VALUES ({placeholders})'
    
    # 插入数据到PostgreSQL
    try:
        execute_batch(pg_cursor, insert_sql, converted_rows)
        pg_conn.commit()
        print(f"  ✅ 迁移 {len(converted_rows)} 条记录")
        return len(converted_rows)
    except Exception as e:
        pg_conn.rollback()
        print(f"  ❌ 迁移失败: {e}")
        # 打印第一条失败的数据以便调试
        if converted_rows:
            print(f"    示例数据: {converted_rows[0]}")
        return 0

def main():
    print("开始数据迁移（修复类型转换）: SQLite → PostgreSQL")
    print("=" * 60)
    
    # 表迁移顺序
    tables = [
        'users',
        'user_llm_configs',
        'user_tokens',
        'reports',
        'watchlist_items',
        'scheduled_analyses',
        'imported_portfolio_positions',
        'email_verification_codes',
        'feedbacks',
        'sponsors',
        'version_stats'
    ]
    
    sqlite_conn = sqlite3.connect('tradingagents.db')
    pg_conn = psycopg2.connect('postgresql://localhost/trading_agents')
    
    total_migrated = 0
    
    for table in tables:
        count = migrate_table_with_type_conversion(table, sqlite_conn, pg_conn)
        total_migrated += count
    
    sqlite_conn.close()
    pg_conn.close()
    
    print("=" * 60)
    print(f"✅ 数据迁移完成！总共迁移了 {total_migrated} 条记录")
    
    # 验证
    print("\n验证数据迁移:")
    pg_conn = psycopg2.connect('postgresql://localhost/trading_agents')
    pg_cursor = pg_conn.cursor()
    for table in tables:
        pg_cursor.execute(f'SELECT COUNT(*) FROM {table}')
        count = pg_cursor.fetchone()[0]
        print(f"  {table}: {count} 条记录")
    pg_conn.close()

if __name__ == '__main__':
    main()