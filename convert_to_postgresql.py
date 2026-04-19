#!/usr/bin/env python3
"""
将SQLite导出的SQL转换为PostgreSQL兼容格式
"""

import re

def convert_sqlite_to_postgresql(input_file, output_file):
    """转换SQLite SQL为PostgreSQL兼容格式"""
    
    with open(input_file, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # 分割为语句
    lines = content.split('\n')
    pg_lines = []
    
    inside_create_table = False
    current_table = None
    
    for line in lines:
        line = line.strip()
        if not line:
            continue
            
        # 跳过SQLite特定的语句
        if line.startswith('PRAGMA') or line.startswith('BEGIN TRANSACTION;') or line.startswith('COMMIT;'):
            continue
            
        # 处理CREATE TABLE语句
        if line.startswith('CREATE TABLE'):
            inside_create_table = True
            current_table = re.search(r'CREATE TABLE (\w+)', line).group(1)
            
            # 替换AUTOINCREMENT为SERIAL
            line = line.replace('AUTOINCREMENT', 'SERIAL')
            
            # 对于SQLite的INTEGER PRIMARY KEY，转换为SERIAL PRIMARY KEY
            if 'INTEGER PRIMARY KEY' in line:
                line = line.replace('INTEGER PRIMARY KEY', 'SERIAL PRIMARY KEY')
                
            pg_lines.append(line)
            continue
            
        # 处理CREATE TABLE内的列定义
        if inside_create_table:
            if line.startswith(');'):
                inside_create_table = False
                pg_lines.append(line)
                continue
                
            # 处理列定义
            line = line.replace('AUTOINCREMENT', 'SERIAL')
            if 'INTEGER PRIMARY KEY' in line:
                line = line.replace('INTEGER PRIMARY KEY', 'SERIAL PRIMARY KEY')
                
            pg_lines.append(line)
            continue
            
        # 处理INSERT语句
        if line.startswith('INSERT INTO'):
            # 移除表名周围的引号
            line = re.sub(r'INSERT INTO "(\w+)"', r'INSERT INTO \1', line)
            
            # 处理VALUES中的转义单引号
            line = line.replace("''", "'")
            
            pg_lines.append(line)
            continue
            
        # 处理索引语句
        if line.startswith('CREATE INDEX') or line.startswith('CREATE UNIQUE INDEX'):
            pg_lines.append(line)
            continue
            
    # 写入输出文件
    with open(output_file, 'w', encoding='utf-8') as f:
        f.write('\n'.join(pg_lines))
    
    print(f"转换完成：{len(pg_lines)} 行")

if __name__ == '__main__':
    convert_sqlite_to_postgresql('sqlite_dump.sql', 'postgresql_import.sql')