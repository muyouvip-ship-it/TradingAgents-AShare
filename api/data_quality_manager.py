"""
数据下载质量管理器
确保数据完整性、正确性和一致性
"""
import pandas as pd
from typing import Dict, Any, List, Optional
from datetime import datetime, date
import logging

logger = logging.getLogger(__name__)


class DataQualityManager:
    """数据质量管理器"""

    # 数据完整性检查规则
    QUALITY_RULES = {
        'daily_kline': {
            'required_columns': ['股票代码', '交易日期', '开盘价', '最高价', '最低价', '收盘价', '成交量'],
            'min_records': 3000,  # 最少股票数
            'date_column': '交易日期',
            'symbol_column': '股票代码',
            'price_columns': ['开盘价', '最高价', '最低价', '收盘价'],
            'volume_column': '成交量'
        },
        'index_data': {
            'required_columns': ['index_code', 'candle_end_time', 'open', 'high', 'low', 'close', 'volume'],
            'min_records': 10,  # 最少指数数
            'date_column': 'candle_end_time',
            'symbol_column': 'index_code',
            'price_columns': ['open', 'high', 'low', 'close'],
            'volume_column': 'volume'
        }
    }

    def validate_csv_data(self, csv_path: str, data_type: str) -> Dict[str, Any]:
        """
        验证CSV数据质量

        Args:
            csv_path: CSV文件路径
            data_type: 数据类型

        Returns:
            {
                'valid': bool,
                'errors': List[str],
                'warnings': List[str],
                'stats': Dict
            }
        """
        result = {
            'valid': True,
            'errors': [],
            'warnings': [],
            'stats': {}
        }

        try:
            # 读取CSV
            logger.info(f"开始验证数据质量: {csv_path}")
            df = pd.read_csv(csv_path, encoding='gbk', skiprows=1)

            # 获取验证规则
            rules = self.QUALITY_RULES.get(data_type)
            if not rules:
                result['warnings'].append(f"未找到数据类型 {data_type} 的验证规则")
                return result

            # 1. 检查必需列
            missing_columns = []
            for col in rules['required_columns']:
                if col not in df.columns:
                    missing_columns.append(col)

            if missing_columns:
                result['errors'].append(f"缺少必需列: {', '.join(missing_columns)}")
                result['valid'] = False

            # 2. 检查数据量
            record_count = len(df)
            if record_count < rules['min_records']:
                result['warnings'].append(
                    f"数据量偏少: {record_count} < {rules['min_records']}"
                )

            # 3. 检查日期格式
            if rules['date_column'] in df.columns:
                try:
                    df[rules['date_column']] = pd.to_datetime(df[rules['date_column']])
                    date_range = {
                        'min': df[rules['date_column']].min().strftime('%Y-%m-%d'),
                        'max': df[rules['date_column']].max().strftime('%Y-%m-%d')
                    }
                    result['stats']['date_range'] = date_range
                except Exception as e:
                    result['errors'].append(f"日期格式错误: {e}")
                    result['valid'] = False

            # 4. 检查价格数据合理性
            if rules['price_columns'][0] in df.columns:
                for price_col in rules['price_columns']:
                    if price_col in df.columns:
                        # 检查负值
                        negative_count = (df[price_col] < 0).sum()
                        if negative_count > 0:
                            result['warnings'].append(f"{price_col}存在{negative_count}个负值")

                        # 检查异常值(价格应该大于0且小于10000)
                        abnormal_count = ((df[price_col] <= 0) | (df[price_col] > 10000)).sum()
                        if abnormal_count > 0:
                            result['warnings'].append(f"{price_col}存在{abnormal_count}个异常值")

            # 5. 检查成交量合理性
            if rules.get('volume_column') and rules['volume_column'] in df.columns:
                volume_col = rules['volume_column']
                negative_volume = (df[volume_col] < 0).sum()
                if negative_volume > 0:
                    result['errors'].append(f"{volume_col}存在{negative_volume}个负值")
                    result['valid'] = False

            # 6. 检查空值
            null_stats = {}
            for col in df.columns:
                null_count = df[col].isnull().sum()
                if null_count > 0:
                    null_stats[col] = null_count

            if null_stats:
                result['warnings'].append(f"存在空值: {null_stats}")

            # 7. 检查重复数据
            if rules['symbol_column'] in df.columns and rules['date_column'] in df.columns:
                duplicates = df.duplicated(subset=[rules['symbol_column'], rules['date_column']])
                duplicate_count = duplicates.sum()
                if duplicate_count > 0:
                    result['warnings'].append(f"存在{duplicate_count}条重复数据")

            # 统计信息
            result['stats'].update({
                'total_records': record_count,
                'unique_symbols': df[rules['symbol_column']].nunique() if rules['symbol_column'] in df.columns else 0,
                'columns': list(df.columns)
            })

            logger.info(f"数据验证完成: {result['valid']}, 错误数: {len(result['errors'])}, 警告数: {len(result['warnings'])}")

        except Exception as e:
            result['valid'] = False
            result['errors'].append(f"验证过程异常: {e}")
            logger.error(f"数据验证异常: {e}")

        return result

    def validate_database_integrity(self, db_session, table_name: str, data_type: str) -> Dict[str, Any]:
        """
        验证数据库数据完整性

        Args:
            db_session: 数据库会话
            table_name: 表名
            data_type: 数据类型

        Returns:
            {
                'valid': bool,
                'issues': List[str],
                'stats': Dict
            }
        """
        result = {
            'valid': True,
            'issues': [],
            'stats': {}
        }

        try:
            from sqlalchemy import text

            # 1. 检查表是否存在
            check_table = text(f"""
                SELECT COUNT(*)
                FROM information_schema.tables
                WHERE table_schema = 'public' AND table_name = :table_name
            """)
            table_count = db_session.execute(check_table, {"table_name": table_name}).scalar()
            
            if table_count == 0:
                result['valid'] = False
                result['issues'].append(f"表 {table_name} 不存在")
                return result

            # 2. 统计基本信息
            stats_query = text(f"""
                SELECT
                    COUNT(*) as total_records,
                    COUNT(DISTINCT symbol) as unique_symbols,
                    MIN(trade_date) as min_date,
                    MAX(trade_date) as max_date,
                    COUNT(DISTINCT trade_date) as trading_days
                FROM {table_name}
            """)
            stats = db_session.execute(stats_query).fetchone()

            result['stats'] = {
                'total_records': stats[0],
                'unique_symbols': stats[1],
                'min_date': str(stats[2]),
                'max_date': str(stats[3]),
                'trading_days': stats[4]
            }

            # 3. 检查空值
            null_check = text(f"""
                SELECT
                    COUNT(*) FILTER (WHERE symbol IS NULL) as null_symbols,
                    COUNT(*) FILTER (WHERE trade_date IS NULL) as null_dates,
                    COUNT(*) FILTER (WHERE close IS NULL) as null_close
                FROM {table_name}
            """)
            null_stats = db_session.execute(null_check).fetchone()

            if null_stats[0] > 0 or null_stats[1] > 0 or null_stats[2] > 0:
                result['issues'].append(
                    f"存在空值 - 股票代码: {null_stats[0]}, 日期: {null_stats[1]}, 收盘价: {null_stats[2]}"
                )

            # 4. 检查重复数据
            duplicate_check = text(f"""
                SELECT COUNT(*) FROM (
                    SELECT symbol, trade_date, COUNT(*)
                    FROM {table_name}
                    GROUP BY symbol, trade_date
                    HAVING COUNT(*) > 1
                ) duplicates
            """)
            duplicate_count = db_session.execute(duplicate_check).scalar()

            if duplicate_count > 0:
                result['issues'].append(f"存在{duplicate_count}条重复数据")

            # 5. 检查价格合理性
            price_check = text(f"""
                SELECT
                    COUNT(*) FILTER (WHERE close <= 0) as negative_close,
                    COUNT(*) FILTER (WHERE close > 10000) as abnormal_close,
                    COUNT(*) FILTER (WHERE high < low) as invalid_high_low
                FROM {table_name}
            """)
            price_stats = db_session.execute(price_check).fetchone()

            if price_stats[0] > 0:
                result['issues'].append(f"存在{price_stats[0]}条收盘价<=0的数据")
            if price_stats[1] > 0:
                result['issues'].append(f"存在{price_stats[1]}条收盘价>10000的异常数据")
            if price_stats[2] > 0:
                result['issues'].append(f"存在{price_stats[2]}条最高价<最低价的错误数据")

            # 6. 检查数据连续性
            if data_type == 'daily_kline':
                # 检查是否有股票缺失某些日期的数据
                continuity_check = text(f"""
                    WITH trading_dates AS (
                        SELECT DISTINCT trade_date FROM {table_name}
                        ORDER BY trade_date DESC LIMIT 5
                    ),
                    symbol_dates AS (
                        SELECT symbol, COUNT(DISTINCT trade_date) as date_count
                        FROM {table_name}
                        WHERE trade_date IN (SELECT trade_date FROM trading_dates)
                        GROUP BY symbol
                    )
                    SELECT COUNT(*) FROM symbol_dates WHERE date_count < 5
                """)
                incomplete_symbols = db_session.execute(continuity_check).scalar()

                if incomplete_symbols > 0:
                    result['issues'].append(f"有{incomplete_symbols}只股票数据不完整(近5个交易日有缺失)")

        except Exception as e:
            result['valid'] = False
            result['issues'].append(f"完整性检查异常: {e}")
            logger.error(f"数据库完整性检查异常: {e}")

        return result

    def generate_quality_report(self, csv_result: Dict, db_result: Dict) -> str:
        """生成数据质量报告"""
        report = []
        report.append("=" * 60)
        report.append("数据质量检查报告")
        report.append("=" * 60)
        report.append("")

        # CSV数据验证
        report.append("【CSV数据验证】")
        if csv_result['valid']:
            report.append("✅ 数据验证通过")
        else:
            report.append("❌ 数据验证失败")

        if csv_result.get('errors'):
            report.append("\n错误:")
            for error in csv_result['errors']:
                report.append(f"  - {error}")

        if csv_result.get('warnings'):
            report.append("\n警告:")
            for warning in csv_result['warnings']:
                report.append(f"  - {warning}")

        if csv_result.get('stats'):
            report.append("\n统计信息:")
            for key, value in csv_result['stats'].items():
                report.append(f"  - {key}: {value}")

        report.append("")

        # 数据库完整性检查
        report.append("【数据库完整性检查】")
        if db_result['valid']:
            report.append("✅ 数据完整性检查通过")
        else:
            report.append("❌ 数据完整性检查失败")

        if db_result.get('issues'):
            report.append("\n问题:")
            for issue in db_result['issues']:
                report.append(f"  - {issue}")

        if db_result.get('stats'):
            report.append("\n统计信息:")
            for key, value in db_result['stats'].items():
                report.append(f"  - {key}: {value}")

        report.append("")
        report.append("=" * 60)

        return "\n".join(report)
