"""
并行执行器 - P1优化
支持Agent并行执行，提升性能
"""

import asyncio
from typing import Dict, Any, List, Callable, Tuple, Optional
from dataclasses import dataclass
import time
import logging

logger = logging.getLogger(__name__)


@dataclass
class ExecutionResult:
    """执行结果"""
    agent_name: str
    success: bool
    result: Dict[str, Any]
    error: Optional[Exception] = None
    latency: float = 0.0


class ParallelAnalystExecutor:
    """
    并行分析师执行器
    
    使用示例:
        executor = ParallelAnalystExecutor()
        results = await executor.execute_all(analyst_nodes, state)
    """
    
    def __init__(
        self,
        max_concurrent: int = 7,
        timeout: float = 30.0,
    ):
        """
        Args:
            max_concurrent: 最大并发数
            timeout: 单个Agent超时时间（秒）
        """
        self.max_concurrent = max_concurrent
        self.timeout = timeout
        self.semaphore = asyncio.Semaphore(max_concurrent)
    
    async def execute_single(
        self,
        agent_name: str,
        agent_node: Callable,
        state: Dict[str, Any],
    ) -> ExecutionResult:
        """
        执行单个Agent（带超时和并发控制）
        """
        async with self.semaphore:
            start_time = time.time()
            try:
                # 设置超时
                result = await asyncio.wait_for(
                    agent_node(state),
                    timeout=self.timeout,
                )
                latency = time.time() - start_time
                
                logger.info(
                    f"Agent {agent_name} 执行成功 "
                    f"(latency={latency:.2f}s)"
                )
                
                return ExecutionResult(
                    agent_name=agent_name,
                    success=True,
                    result=result,
                    latency=latency,
                )
                
            except asyncio.TimeoutError:
                latency = time.time() - start_time
                logger.error(f"Agent {agent_name} 执行超时 ({self.timeout}s)")
                
                return ExecutionResult(
                    agent_name=agent_name,
                    success=False,
                    result={},
                    error=asyncio.TimeoutError(f"Agent {agent_name} 超时"),
                    latency=latency,
                )
                
            except Exception as e:
                latency = time.time() - start_time
                logger.error(f"Agent {agent_name} 执行失败: {e}")
                
                return ExecutionResult(
                    agent_name=agent_name,
                    success=False,
                    result={},
                    error=e,
                    latency=latency,
                )
    
    async def execute_all(
        self,
        analyst_nodes: Dict[str, Callable],
        state: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        并行执行所有分析师
        
        Args:
            analyst_nodes: {agent_name: agent_node} 字典
            state: 共享状态
        
        Returns:
            合并后的状态更新
        """
        logger.info(
            f"开始并行执行 {len(analyst_nodes)} 个分析师 "
            f"(max_concurrent={self.max_concurrent})"
        )
        
        start_time = time.time()
        
        # 创建所有任务
        tasks = [
            self.execute_single(name, node, state)
            for name, node in analyst_nodes.items()
        ]
        
        # 并行执行
        results: List[ExecutionResult] = await asyncio.gather(*tasks)
        
        total_time = time.time() - start_time
        
        # 合并结果
        merged_state = {}
        success_count = 0
        failed_agents = []
        
        for result in results:
            if result.success:
                success_count += 1
                merged_state.update(result.result)
            else:
                failed_agents.append(result.agent_name)
                # 失败的Agent也记录到状态中
                merged_state[f"{result.agent_name}_error"] = str(result.error)
        
        logger.info(
            f"并行执行完成: {success_count}/{len(results)} 成功, "
            f"总耗时={total_time:.2f}s, "
            f"平均耗时={sum(r.latency for r in results) / len(results):.2f}s"
        )
        
        if failed_agents:
            logger.warning(f"失败的Agent: {failed_agents}")
        
        # 添加执行统计
        merged_state["_execution_stats"] = {
            "total_agents": len(results),
            "success_count": success_count,
            "failed_count": len(failed_agents),
            "failed_agents": failed_agents,
            "total_time": total_time,
            "avg_latency": sum(r.latency for r in results) / len(results),
            "max_latency": max(r.latency for r in results),
        }
        
        return merged_state


async def run_analysts_parallel(
    analyst_nodes: Dict[str, Callable],
    state: Dict[str, Any],
    max_concurrent: int = 7,
    timeout: float = 30.0,
) -> Dict[str, Any]:
    """
    便捷函数：并行运行分析师
    
    Args:
        analyst_nodes: 分析师节点字典
        state: 共享状态
        max_concurrent: 最大并发数
        timeout: 超时时间
    
    Returns:
        合并后的状态更新
    """
    executor = ParallelAnalystExecutor(
        max_concurrent=max_concurrent,
        timeout=timeout,
    )
    return await executor.execute_all(analyst_nodes, state)


# ━━━━ 集成到LangGraph的节点 ━━━━

def create_parallel_analyst_node(
    analyst_nodes: Dict[str, Callable],
    max_concurrent: int = 7,
):
    """
    创建并行分析师节点（用于LangGraph）
    
    这个节点会并行执行所有分析师，然后合并结果
    """
    
    async def parallel_node(state: Dict[str, Any]) -> Dict[str, Any]:
        return await run_analysts_parallel(
            analyst_nodes,
            state,
            max_concurrent=max_concurrent,
        )
    
    return parallel_node


# ━━━━ 顺序执行器（用于对比） ━━━━

async def run_analysts_sequential(
    analyst_nodes: Dict[str, Callable],
    state: Dict[str, Any],
) -> Dict[str, Any]:
    """
    顺序运行分析师（原有逻辑，用于性能对比）
    """
    start_time = time.time()
    merged_state = {}
    
    for name, node in analyst_nodes.items():
        try:
            result = await node(state)
            merged_state.update(result)
            logger.info(f"Agent {name} 执行完成")
        except Exception as e:
            logger.error(f"Agent {name} 执行失败: {e}")
            merged_state[f"{name}_error"] = str(e)
    
    total_time = time.time() - start_time
    logger.info(f"顺序执行完成，总耗时={total_time:.2f}s")
    
    return merged_state
