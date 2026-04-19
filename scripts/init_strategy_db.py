"""
数据库初始化脚本

初始化策略管理相关的数据库表。
"""

import sys
from pathlib import Path

# 添加项目根目录到路径
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from sqlalchemy import create_engine
from api.models.strategy_models import init_database, Base
import os


def main():
    """初始化数据库"""
    # 使用SQLite数据库（开发环境）
    db_path = project_root / "data" / "strategy_management.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)

    engine = create_engine(f"sqlite:///{db_path}")

    print(f"📁 数据库路径: {db_path}")
    print("🔨 创建数据库表...")

    # 创建所有表
    Base.metadata.create_all(engine)

    print("✅ 数据库初始化完成")
    print("\n创建的表:")
    for table in Base.metadata.tables.keys():
        print(f"  - {table}")


if __name__ == "__main__":
    main()
