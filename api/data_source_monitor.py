"""
数据源使用统计和监控
"""
import json
import os
from datetime import datetime, date
from typing import Dict, Any
import logging

logger = logging.getLogger(__name__)


class DataSourceMonitor:
    """数据源使用监控器"""

    # 统计文件路径
    STATS_FILE = "/tmp/data_source_stats.json"

    # 数据源配置
    DATA_SOURCES = {
        'quantclass': {
            'name': '量化课堂',
            'daily_limit': 188,
            'description': '快速、高质量数据源'
        },
        'qmt': {
            'name': 'QMT',
            'daily_limit': None,
            'description': '本机 / 桥接 xtquant 历史分钟线数据源'
        },
        'akshare': {
            'name': 'AKShare',
            'daily_limit': None,  # 无限制
            'description': '免费、无限制数据源'
        }
    }

    def __init__(self):
        self.stats = self._load_stats()
        self._ensure_source_keys()

    def _load_stats(self) -> Dict:
        """加载统计数据"""
        if os.path.exists(self.STATS_FILE):
            try:
                with open(self.STATS_FILE, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception as e:
                logger.error(f"加载统计数据失败: {e}")

        # 初始化统计数据
        return {
            'quantclass': {
                'daily_usage': {},
                'total_downloads': 0,
                'total_records': 0,
                'errors': 0
            },
            'qmt': {
                'daily_usage': {},
                'total_downloads': 0,
                'total_records': 0,
                'errors': 0
            },
            'akshare': {
                'daily_usage': {},
                'total_downloads': 0,
                'total_records': 0,
                'errors': 0
            }
        }

    def _ensure_source_keys(self):
        for source in self.DATA_SOURCES:
            if source not in self.stats:
                self.stats[source] = {
                    'daily_usage': {},
                    'total_downloads': 0,
                    'total_records': 0,
                    'errors': 0
                }

    def _save_stats(self):
        """保存统计数据"""
        try:
            with open(self.STATS_FILE, 'w', encoding='utf-8') as f:
                json.dump(self.stats, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"保存统计数据失败: {e}")

    def record_download(self, source: str, data_type: str, records: int, success: bool):
        """
        记录下载事件

        Args:
            source: 数据源名称
            data_type: 数据类型
            records: 记录数
            success: 是否成功
        """
        if source not in self.stats:
            return

        today = str(date.today())

        # 初始化今日统计
        if today not in self.stats[source]['daily_usage']:
            self.stats[source]['daily_usage'][today] = {
                'downloads': 0,
                'records': 0,
                'data_types': {}
            }

        # 更新今日统计
        self.stats[source]['daily_usage'][today]['downloads'] += 1
        self.stats[source]['daily_usage'][today]['records'] += records

        # 按数据类型统计
        if data_type not in self.stats[source]['daily_usage'][today]['data_types']:
            self.stats[source]['daily_usage'][today]['data_types'][data_type] = {
                'downloads': 0,
                'records': 0
            }

        self.stats[source]['daily_usage'][today]['data_types'][data_type]['downloads'] += 1
        self.stats[source]['daily_usage'][today]['data_types'][data_type]['records'] += records

        # 更新总计
        self.stats[source]['total_downloads'] += 1
        if success:
            self.stats[source]['total_records'] += records
        else:
            self.stats[source]['errors'] += 1

        # 保存
        self._save_stats()

        logger.info(f"记录下载事件: {source} - {data_type} - {records}条记录 - {'成功' if success else '失败'}")

    def get_usage_status(self, source: str) -> Dict[str, Any]:
        """
        获取使用状态

        Args:
            source: 数据源名称

        Returns:
            {
                'source': str,
                'daily_limit': int,
                'used_today': int,
                'remaining_today': int,
                'total_downloads': int,
                'total_records': int,
                'errors': int
            }
        """
        if source not in self.DATA_SOURCES:
            return {'error': 'Unknown data source'}

        source_config = self.DATA_SOURCES[source]
        today = str(date.today())

        # 获取今日使用量
        used_today = 0
        if today in self.stats[source]['daily_usage']:
            used_today = self.stats[source]['daily_usage'][today]['downloads']

        # 计算剩余次数
        remaining = None
        if source_config['daily_limit']:
            remaining = max(0, source_config['daily_limit'] - used_today)

        return {
            'source': source,
            'name': source_config['name'],
            'daily_limit': source_config['daily_limit'],
            'used_today': used_today,
            'remaining_today': remaining,
            'total_downloads': self.stats[source]['total_downloads'],
            'total_records': self.stats[source]['total_records'],
            'errors': self.stats[source]['errors'],
            'description': source_config['description']
        }

    def get_all_sources_status(self) -> Dict[str, Any]:
        """获取所有数据源状态"""
        result = {}
        for source in self.DATA_SOURCES:
            result[source] = self.get_usage_status(source)
        return result

    def get_daily_report(self, target_date: str = None) -> Dict[str, Any]:
        """
        获取每日报告

        Args:
            target_date: 目标日期，默认今天

        Returns:
            每日使用报告
        """
        if not target_date:
            target_date = str(date.today())

        report = {
            'date': target_date,
            'sources': {}
        }

        for source in self.DATA_SOURCES:
            if target_date in self.stats[source]['daily_usage']:
                daily_data = self.stats[source]['daily_usage'][target_date]
                report['sources'][source] = {
                    'name': self.DATA_SOURCES[source]['name'],
                    'downloads': daily_data['downloads'],
                    'records': daily_data['records'],
                    'data_types': daily_data['data_types']
                }

        return report

    def cleanup_old_stats(self, keep_days: int = 30):
        """
        清理旧统计数据

        Args:
            keep_days: 保留天数
        """
        from datetime import timedelta

        cutoff_date = (date.today() - timedelta(days=keep_days)).isoformat()

        for source in self.stats:
            dates_to_remove = [
                d for d in self.stats[source]['daily_usage']
                if d < cutoff_date
            ]

            for d in dates_to_remove:
                del self.stats[source]['daily_usage'][d]
                logger.info(f"清理旧统计数据: {source} - {d}")

        self._save_stats()


# 全局监控器实例
_monitor = None


def get_data_source_monitor() -> DataSourceMonitor:
    """获取全局监控器实例"""
    global _monitor
    if _monitor is None:
        _monitor = DataSourceMonitor()
    return _monitor
