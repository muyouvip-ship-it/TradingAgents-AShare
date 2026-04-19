#!/usr/bin/env python3
"""
测试策略管理API
"""

import requests
import json
import time

BASE_URL = "http://localhost:8500"

def test_api():
    """测试API是否正常运行"""
    
    print("=" * 60)
    print("测试策略管理API")
    print("=" * 60)
    
    # 1. 测试健康检查
    print("\n1. 测试健康检查...")
    try:
        response = requests.get(f"{BASE_URL}/health", timeout=5)
        print(f"   状态码: {response.status_code}")
        if response.status_code == 200:
            print("   ✅ API服务器正常运行")
        else:
            print("   ❌ API服务器异常")
            return
    except Exception as e:
        print(f"   ❌ 无法连接到API服务器: {e}")
        print("   请先启动API服务器: cd api && python main.py")
        return
    
    # 2. 测试创建策略
    print("\n2. 测试创建策略...")
    strategy_data = {
        "name": "波段跟踪策略V1",
        "strategy_type": "selection",
        "description": "基于MACD和成交量的波段跟踪策略",
        "indicators": [
            {
                "name": "MACD",
                "display_name": "MACD (指数平滑异同移动平均线)",
                "parameters": {"fast": 12, "slow": 26, "signal": 9}
            },
            {
                "name": "VOL_MA",
                "display_name": "VOL_MA (成交量均线)",
                "parameters": {"period": 5}
            }
        ],
        "entry_rules": [
            {
                "name": "MACD金叉",
                "condition": "macd > signal AND macd_prev < signal_prev",
                "parameters": {}
            },
            {
                "name": "成交量放大",
                "condition": "volume > volume_ma * 1.5",
                "parameters": {"multiplier": 1.5}
            }
        ],
        "exit_rules": [
            {
                "name": "MACD死叉",
                "condition": "macd < signal AND macd_prev > signal_prev",
                "parameters": {}
            },
            {
                "name": "止损",
                "condition": "close < entry_price * 0.95",
                "parameters": {"stop_loss": 0.05}
            }
        ],
        "position_rules": {
            "initial": 0.3,
            "max_position": 0.8,
            "max_single_position": 0.3
        },
        "risk_rules": {
            "stop_loss": 0.05,
            "take_profit": 0.15,
            "trailing_stop": 0.03,
            "max_positions": 10,
            "max_daily_loss": 0.03
        }
    }
    
    try:
        response = requests.post(
            f"{BASE_URL}/api/v1/strategies",
            json=strategy_data,
            headers={"Content-Type": "application/json"},
            timeout=10
        )
        print(f"   状态码: {response.status_code}")
        
        if response.status_code == 200:
            strategy = response.json()
            strategy_id = strategy["id"]
            print(f"   ✅ 策略创建成功")
            print(f"   策略ID: {strategy_id}")
            print(f"   策略名称: {strategy['name']}")
            
            # 3. 测试获取策略列表
            print("\n3. 测试获取策略列表...")
            response = requests.get(f"{BASE_URL}/api/v1/strategies", timeout=5)
            print(f"   状态码: {response.status_code}")
            
            if response.status_code == 200:
                data = response.json()
                print(f"   ✅ 获取策略列表成功")
                print(f"   总数: {data['total']}")
            else:
                print(f"   ❌ 获取策略列表失败")
            
            # 4. 测试获取策略详情
            print("\n4. 测试获取策略详情...")
            response = requests.get(f"{BASE_URL}/api/v1/strategies/{strategy_id}", timeout=5)
            print(f"   状态码: {response.status_code}")
            
            if response.status_code == 200:
                strategy_detail = response.json()
                print(f"   ✅ 获取策略详情成功")
                print(f"   策略名称: {strategy_detail['name']}")
                print(f"   指标数量: {len(strategy_detail.get('indicators', []))}")
                print(f"   入场规则: {len(strategy_detail.get('entry_rules', []))}")
                print(f"   出场规则: {len(strategy_detail.get('exit_rules', []))}")
            else:
                print(f"   ❌ 获取策略详情失败")
            
            # 5. 测试激活策略
            print("\n5. 测试激活策略...")
            response = requests.post(f"{BASE_URL}/api/v1/strategies/{strategy_id}/activate", timeout=5)
            print(f"   状态码: {response.status_code}")
            
            if response.status_code == 200:
                print(f"   ✅ 策略激活成功")
            else:
                print(f"   ❌ 策略激活失败")
            
            # 6. 测试停用策略
            print("\n6. 测试停用策略...")
            response = requests.post(f"{BASE_URL}/api/v1/strategies/{strategy_id}/deactivate", timeout=5)
            print(f"   状态码: {response.status_code}")
            
            if response.status_code == 200:
                print(f"   ✅ 策略停用成功")
            else:
                print(f"   ❌ 策略停用失败")
            
            # 7. 测试删除策略
            print("\n7. 测试删除策略...")
            response = requests.delete(f"{BASE_URL}/api/v1/strategies/{strategy_id}", timeout=5)
            print(f"   状态码: {response.status_code}")
            
            if response.status_code == 200:
                print(f"   ✅ 策略删除成功")
            else:
                print(f"   ❌ 策略删除失败")
            
        else:
            print(f"   ❌ 策略创建失败")
            print(f"   响应: {response.text}")
    
    except Exception as e:
        print(f"   ❌ 测试失败: {e}")
    
    print("\n" + "=" * 60)
    print("测试完成")
    print("=" * 60)


if __name__ == "__main__":
    test_api()
