#!/usr/bin/env python3
"""
独立的API启动脚本
避免环境冲突
"""

import sys
from pathlib import Path

# 添加项目根目录
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

# 切换到项目目录
import os
os.chdir(project_root / "api")

# 导入并启动
from main import app
import uvicorn

if __name__ == "__main__":
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=8000,
        log_level="info"
    )
