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

from sqlalchemy import create_engine
from api.models.strategy_models import Base
import os

# 创建数据目录
data_dir = project_root / "data"
data_dir.mkdir(parents=True, exist_ok=True)

# 数据库路径
db_path = data_dir / "strategy_management.db"

print(f"📁 数据库路径: {db_path}")

# 创建引擎
engine = create_engine(f"sqlite:///{db_path}")

print("🔨 创建数据库表...")

# 创建所有表
Base.metadata.create_all(engine)

print("✅ 数据库初始化完成")
print("\n创建的表:")
for table in Base.metadata.tables.keys():
    print(f"  - {table}")
