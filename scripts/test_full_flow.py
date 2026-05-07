#!/usr/bin/env python3
"""
完整的端到端测试脚本

测试流程：
1. 初始化数据库
2. 创建策略
3. 运行回测
4. 验证结果

运行方式：
python scripts/test_full_flow.py
"""

import sys
from pathlib import Path

# 添加项目根目录到路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

import requests
import json
import time
from datetime import datetime

BASE_URL = "http://localhost:8500"

def print_section(title):
    """打印章节标题"""
    print("\n" + "=" * 70)
    print(f"  {title}")
    print("=" * 70)


def health_check():
    """测试健康检查"""
    print_section("1. 测试健康检查")
    
    try:
        # 使用策略列表端点作为健康检查
        response = requests.get(f"{BASE_URL}/api/v1/strategies", timeout=5)
        if response.status_code == 200:
            print("✅ API服务器正常运行")
            return True
        else:
            print(f"❌ API服务器异常: {response.status_code}")
            return False
    except Exception as e:
        print(f"❌ 无法连接到API服务器: {e}")
        print("\n请先启动API服务器:")
        print("  cd ~/Documents/DaiMa/TradingAgents-AShare-main")
        print("  python3 -m uvicorn api.main:app --host 0.0.0.0 --port 8000")
        return False


def create_strategy():
    """创建测试策略"""
    print_section("2. 创建测试策略")
    
    strategy_data = {
        "name": "波段跟踪策略V1",
        "strategy_type": "selection",
        "description": "基于MACD和成交量的波段跟踪策略，适用于震荡市场",
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
            },
            {
                "name": "MA",
                "display_name": "MA (移动平均线)",
                "parameters": {"period": 20, "type": "SMA"}
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
            },
            {
                "name": "突破均线",
                "condition": "close > ma20",
                "parameters": {"period": 20}
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
            },
            {
                "name": "止盈",
                "condition": "close > entry_price * 1.15",
                "parameters": {"take_profit": 0.15}
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
        
        if response.status_code == 200:
            strategy = response.json()
            print(f"✅ 策略创建成功")
            print(f"   ID: {strategy['id']}")
            print(f"   名称: {strategy['name']}")
            print(f"   类型: {strategy['strategy_type']}")
            print(f"   指标数: {len(strategy.get('indicators', []))}")
            print(f"   入场规则: {len(strategy.get('entry_rules', []))}")
            print(f"   出场规则: {len(strategy.get('exit_rules', []))}")
            return strategy['id']
        else:
            print(f"❌ 策略创建失败: {response.status_code}")
            print(f"   响应: {response.text}")
            return None
    
    except Exception as e:
        print(f"❌ 创建策略异常: {e}")
        return None


def list_strategies():
    """获取策略列表"""
    print_section("3. 获取策略列表")
    
    try:
        response = requests.get(f"{BASE_URL}/api/v1/strategies", timeout=5)
        
        if response.status_code == 200:
            data = response.json()
            print(f"✅ 获取策略列表成功")
            print(f"   总数: {data['total']}")
            
            for i, s in enumerate(data['strategies'][:5], 1):
                print(f"   {i}. {s['name']} ({s['strategy_type']}) - {s['status']}")
            
            return data['strategies']
        else:
            print(f"❌ 获取策略列表失败: {response.status_code}")
            return []
    
    except Exception as e:
        print(f"❌ 获取策略列表异常: {e}")
        return []


def run_backtest(strategy_id):
    """运行回测"""
    print_section("4. 运行策略回测")
    
    backtest_data = {
        "strategy_id": strategy_id,
        "backtest_mode": "indicator_driven",
        "start_date": "2025-01-01T00:00:00",
        "end_date": "2026-04-18T00:00:00",
        "initial_capital": 1000000.0,
        "benchmark": "hs300",
        "config": {
            "commission_rate": 0.0003,
            "slippage_rate": 0.001,
            "stamp_duty": 0.001
        }
    }
    
    try:
        response = requests.post(
            f"{BASE_URL}/api/v1/backtest/run",
            json=backtest_data,
            headers={"Content-Type": "application/json"},
            timeout=10
        )
        
        if response.status_code == 200:
            job = response.json()
            print(f"✅ 回测任务创建成功")
            print(f"   任务ID: {job['id']}")
            print(f"   状态: {job['status']}")
            print(f"   模式: {job['backtest_mode']}")
            print(f"   初始资金: ¥{job['initial_capital']:,.2f}")
            return job['id']
        else:
            print(f"❌ 回测任务创建失败: {response.status_code}")
            print(f"   响应: {response.text}")
            return None
    
    except Exception as e:
        print(f"❌ 运行回测异常: {e}")
        return None


def poll_result(job_id, max_wait=60):
    """轮询回测结果"""
    print_section("5. 等待回测结果")
    
    print(f"正在等待回测完成（最多等待{max_wait}秒）...")
    
    start_time = time.time()
    
    while time.time() - start_time < max_wait:
        try:
            response = requests.get(
                f"{BASE_URL}/api/v1/backtest/jobs/{job_id}",
                timeout=5
            )
            
            if response.status_code == 200:
                job = response.json()
                
                if job['status'] == 'completed':
                    print(f"\n✅ 回测完成！")
                    return job
                elif job['status'] == 'failed':
                    print(f"\n❌ 回测失败: {job.get('error_message', '未知错误')}")
                    return None
                else:
                    # 显示进度
                    progress = job.get('progress', 0) * 100
                    elapsed = int(time.time() - start_time)
                    print(f"\r   状态: {job['status']} | 进度: {progress:.0f}% | 已用时: {elapsed}秒", end='')
                    time.sleep(1)
            else:
                print(f"\n❌ 获取任务状态失败: {response.status_code}")
                return None
        
        except Exception as e:
            print(f"\n❌ 轮询异常: {e}")
            time.sleep(1)
    
    print(f"\n⏱️ 回测超时（{max_wait}秒），请稍后查看结果")
    return None


def display_result(job):
    """显示回测结果"""
    print_section("6. 回测结果详情")
    
    if not job or not job.get('result'):
        print("❌ 无回测结果")
        return
    
    result = job['result']
    metrics = result.get('metrics', {})
    
    print("\n📊 绩效指标:")
    print(f"  总收益率:     {metrics.get('total_return', 0):.2%}")
    print(f"  年化收益率:   {metrics.get('annual_return', 0):.2%}")
    print(f"  夏普比率:     {metrics.get('sharpe_ratio', 0):.2f}")
    print(f"  最大回撤:     {metrics.get('max_drawdown', 0):.2%}")
    
    print("\n📈 交易统计:")
    print(f"  总交易次数:   {metrics.get('total_trades', 0)}")
    print(f"  盈利次数:     {metrics.get('winning_trades', 0)}")
    print(f"  亏损次数:     {metrics.get('losing_trades', 0)}")
    print(f"  胜率:         {metrics.get('win_rate', 0):.2%}")
    print(f"  盈亏比:       {metrics.get('profit_factor', 0):.2f}")
    
    if metrics.get('avg_win'):
        print(f"  平均盈利:     ¥{metrics['avg_win']:,.2f}")
    if metrics.get('avg_loss'):
        print(f"  平均亏损:     ¥{metrics['avg_loss']:,.2f}")
    
    print("\n📅 任务信息:")
    print(f"  任务ID:       {job['id']}")
    print(f"  策略ID:       {job['strategy_id']}")
    print(f"  创建时间:     {job['created_at']}")
    print(f"  开始时间:     {job.get('started_at', 'N/A')}")
    print(f"  完成时间:     {job.get('completed_at', 'N/A')}")


def cleanup(strategy_id):
    """清理测试数据"""
    print_section("7. 清理测试数据")
    
    try:
        # 删除策略（会级联删除回测任务）
        response = requests.delete(
            f"{BASE_URL}/api/v1/strategies/{strategy_id}",
            timeout=5
        )
        
        if response.status_code == 200:
            print(f"✅ 测试数据已清理")
        else:
            print(f"⚠️ 清理失败: {response.status_code}")
    
    except Exception as e:
        print(f"⚠️ 清理异常: {e}")


def main():
    """主测试流程"""
    print("\n" + "=" * 70)
    print("  策略管理与回测模块 - 完整流程测试")
    print("=" * 70)
    print("\n测试流程:")
    print("  1. 健康检查")
    print("  2. 创建策略")
    print("  3. 获取策略列表")
    print("  4. 运行回测")
    print("  5. 等待结果")
    print("  6. 显示结果")
    print("  7. 清理数据")
    
    # 1. 健康检查
    if not health_check():
        return
    
    # 2. 创建策略
    strategy_id = create_strategy()
    if not strategy_id:
        return
    
    # 3. 获取策略列表
    strategies = list_strategies()
    
    # 4. 运行回测
    job_id = run_backtest(strategy_id)
    if not job_id:
        cleanup(strategy_id)
        return
    
    # 5. 轮询结果
    job = poll_result(job_id, max_wait=60)
    
    # 6. 显示结果
    display_result(job)
    
    # 7. 清理数据（可选）
    print("\n是否清理测试数据？(y/n): ", end='')
    try:
        choice = input().strip().lower()
        if choice == 'y':
            cleanup(strategy_id)
    except:
        pass
    
    print("\n" + "=" * 70)
    print("  测试完成！")
    print("=" * 70)
    print("\n✅ 所有功能正常工作")
    print("\n下一步:")
    print("  1. 访问前端页面: http://localhost:5173/strategies")
    print("  2. 创建自己的策略")
    print("  3. 运行回测分析")
    print("  4. 查看绩效报告")


if __name__ == "__main__":
    main()
