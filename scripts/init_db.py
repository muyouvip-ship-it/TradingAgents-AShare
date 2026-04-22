#!/usr/bin/env python3
"""
数据库初始化脚本
运行: python init_db.py
"""

import sys
from pathlib import Path

# 添加项目根目录到路径
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from api.core.strategy_db import strategy_engine
from api.models.strategy_models import Base

print(f"📁 数据库引擎: {strategy_engine.url.render_as_string(hide_password=True)}")

print("🔨 创建数据库表...")

# 创建所有表
Base.metadata.create_all(strategy_engine)

print("✅ 数据库初始化完成")
print("\n创建的表:")
for table in Base.metadata.tables.keys():
    print(f"  - {table}")
