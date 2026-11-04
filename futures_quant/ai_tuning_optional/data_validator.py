"""数据验证模块。

提供期货数据的全面准确性校验功能，包括数据格式检查、逻辑一致性验证、
数值范围确认及来源可靠性审核。针对发现的不准确数据，提供修正方案并记录
数据修正过程，确保修正后的数据符合业务需求和质量标准。
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from typing import Dict, List, Tuple, Optional, Any, Union, Callable
from datetime import datetime, timedelta
import logging
import json
import os
from pathlib import Path

logger = logging.getLogger(__name__)


class FuturesDataValidator:
    """期货数据验证器。
    
    负责期货行情数据的全面准确性校验，包括：
    - 数据格式检查（列名、数据类型、缺失值等）
    - 逻辑一致性验证（OHLC关系、成交量非负等）
    - 数值范围确认（价格合理范围、成交量范围等）
    - 时间序列完整性检查（连续性、重复值等）
    - 来源可靠性审核（数据完整性、异常值检测等）
    """
    
    def __init__(self, 
                 price_tolerance: float = 0.1,
                 volume_tolerance: float = 0.01,
                 max_price_change_pct: float = 0.2,
                 enable_auto_correction: bool = True):
        """初始化数据验证器。
        
        Args:
            price_tolerance: 价格容忍度（用于异常值检测的百分比）
            volume_tolerance: 成交量容忍度（用于异常值检测的百分比）
            max_price_change_pct: 单日最大价格变化百分比阈值
            enable_auto_correction: 是否启用自动纠正
        """
        self.price_tolerance = price_tolerance
        self.volume_tolerance = volume_tolerance
        self.max_price_change_pct = max_price_change_pct
        self.enable_auto_correction = enable_auto_correction
        
        # 验证历史
        self.validation_history = []
        self.correction_log = []
        
        # 期货数据必需列
        self.required_columns = ['datetime', 'open', 'high', 'low', 'close', 'volume']
        self.optional_columns = ['open_interest']
        
        # 品种特定的价格范围（示例，实际应从配置中获取）
        self.price_ranges = {
            'default': (0, 100000),  # 通用范围
            'IF': (1000, 10000),    # 沪深300指数期货
            'IH': (1000, 10000),    # 上证50指数期货
            'IC': (1000, 10000),    # 中证500指数期货
            'AU': (200, 800),       # 黄金期货（每克）
            'AG': (3, 15),          # 白银期货（每克）
            'CU': (30000, 100000),  # 铜期货（每吨）
            'AL': (10000, 50000),   # 铝期货（每吨）
            'ZN': (10000, 50000),   # 锌期货（每吨）
            'PB': (10000, 50000),   # 铅期货（每吨）
            'SN': (100000, 500000), # 锡期货（每吨）
            'RB': (2000, 10000),    # 螺纹钢期货（每吨）
            'HC': (2000, 10000),    # 热轧卷板期货（每吨）
            'BU': (2000, 10000),    # 沥青期货（每吨）
            'FU': (1000, 10000),    # 燃油期货（每吨）
            'V': (5000, 30000),     # PVC期货（每吨）
            'MA': (2000, 10000),    # 甲醇期货（每吨）
            'TA': (4000, 15000),    # PTA期货（每吨）
            'PP': (5000, 20000),    # 聚丙烯期货（每吨）
            'PE': (5000, 20000),    # 聚乙烯期货（每吨）
            'L': (5000, 20000),     # 聚氯乙烯期货（每吨）
            'J': (1000, 20000),     # 焦炭期货（每吨）
            'JM': (1000, 20000),    # 焦煤期货（每吨）
            'I': (1000, 20000),     # 铁矿石期货（每吨）
            'CF': (1000, 5000),     # 棉花期货（每吨）
            'SR': (3000, 10000),    # 糖期货（每吨）
            'ZC': (1000, 5000),     # 粳米期货（每斤）
            'FG': (1500, 8000),     # 玻璃期货（每吨）
            'PF': (1500, 8000),     # 短纤期货（每吨）
            'EG': (4000, 15000),    # 乙二醇期货（每吨）
            'RR': (1000, 5000),     # 粳米期货（每斤）
            'JD': (5000, 30000),    # 鸡蛋期货（每斤）
            'LR': (6000, 20000),    # 晚籼稻期货（每斤）
            'RI': (3000, 10000),    # 早籼稻期货（每斤）
            'WH': (1000, 5000),     # 强麦期货（每斤）
            'PM': (1000, 5000),     # 普麦期货（每斤）
            'SM': (1000, 5000),     # 棉籽油期货（每吨）
            'Y': (4000, 20000),     # 棕榈油期货（每吨）
            'OI': (4000, 20000),    # 菜籽油期货（每吨）
            'P': (1000, 10000),     # 棕榈油期货（每吨）
            'C': (1000, 10000),     # 玉米期货（每斤）
            'CS': (1000, 10000),    # 玉米淀粉期货（每吨）
            'RS': (2000, 10000),    # 菜籽期货（每吨）
            'RM': (2000, 10000),    # 饲料期货（每吨）
            'SF': (4000, 20000),    # 橡胶期货（每吨）
            'SA': (1000, 10000),    # 锂盐期货（每吨）
            'AP': (1000, 10000),    # 苹果期货（每斤）
            'CJ': (2000, 10000),    # 胶合板期货（每张）
            'UR': (2000, 10000),    # 尿素期货（每吨）
            'LR': (6000, 20000),    # 晚籼稻期货（每斤）
        }
    
    def validate_dataframe(self, 
                          df: pd.DataFrame,
                          symbol: Optional[str] = None,
                          data_source: str = "unknown") -> Dict[str, Any]:
        """验证期货数据DataFrame。
        
        Args:
            df: 待验证的数据DataFrame
            symbol: 期货品种代码（用于获取特定的验证规则）
            data_source: 数据来源描述
            
        Returns:
            包含验证结果和建议的字典
        """
        logger.info(f"开始验证{data_source}的数据，形状: {df.shape}")
        start_time = datetime.now()
        
        # 初始化验证结果
        validation_result = {
            'symbol': symbol,
            'data_source': data_source,
            'validation_time': start_time.isoformat(),
            'original_shape': df.shape,
            'is_valid': True,
            'errors': [],
            'warnings': [],
            'corrections_applied': [],
            'data_quality_score': 100.0,  # 数据质量分数（0-100）
            'validated_df': df.copy() if self.enable_auto_correction else None
        }
        
        # 复制数据用于可能的修正
        if self.enable_auto_correction:
            validated_df = df.copy()
        else:
            validated_df = df
        
        # 1. 数据格式检查
        format_check = self._check_data_format(validated_df, symbol)
        validation_result['errors'].extend(format_check['errors'])
        validation_result['warnings'].extend(format_check['warnings'])
        if self.enable_auto_correction and format_check['corrections']:
            validated_df = format_check['corrected_df']
            validation_result['corrections_applied'].extend(format_check['corrections'])
        
        # 2. 逻辑一致性验证
        logic_check = self._check_logical_consistency(validated_df, symbol)
        validation_result['errors'].extend(logic_check['errors'])
        validation_result['warnings'].extend(logic_check['warnings'])
        if self.enable_auto_correction and logic_check['corrections']:
            validated_df = logic_check['corrected_df']
            validation_result['corrections_applied'].extend(logic_check['corrections'])
        
        # 3. 数值范围确认
        range_check = self._check_value_ranges(validated_df, symbol)
        validation_result['errors'].extend(range_check['errors'])
        validation_result['warnings'].extend(range_check['warnings'])
        if self.enable_auto_correction and range_check['corrections']:
            validated_df = range_check['corrected_df']
            validation_result['corrections_applied'].extend(range_check['corrections'])
        
        # 4. 时间序列完整性检查
        time_check = self._check_time_series_integrity(validated_df)
        validation_result['errors'].extend(time_check['errors'])
        validation_result['warnings'].extend(time_check['warnings'])
        if self.enable_auto_correction and time_check['corrections']:
            validated_df = time_check['corrected_df']
            validation_result['corrections_applied'].extend(time_check['corrections'])
        
        # 5. 异常值检测
        anomaly_check = self._detect_anomalies(validated_df, symbol)
        validation_result['errors'].extend(anomaly_check['errors'])
        validation_result['warnings'].extend(anomaly_check['warnings'])
        if self.enable_auto_correction and anomaly_check['corrections']:
            validated_df = anomaly_check['corrected_df']
            validation_result['corrections_applied'].extend(anomaly_check['corrections'])
        
        # 计算数据质量分数
        validation_result['data_quality_score'] = self._calculate_quality_score(
            validation_result['errors'], 
            validation_result['warnings'],
            len(df)
        )
        
        # 确定数据是否有效（没有严重错误）
        validation_result['is_valid'] = len(validation_result['errors']) == 0
        
        # 保存验证后的数据
        if self.enable_auto_correction:
            validation_result['validated_df'] = validated_df
        else:
            validation_result['validated_df'] = df
        
        # 记录验证历史
        validation_result['validation_duration'] = (datetime.now() - start_time).total_seconds()
        self.validation_history.append(validation_result.copy())
        
        logger.info(f"数据验证完成，质量分数: {validation_result['data_quality_score']:.2f}, "
                   f"错误: {len(validation_result['errors'])}, 警告: {len(validation_result['warnings'])}")
        
        return validation_result
    
    def _check_data_format(self, df: pd.DataFrame, symbol: Optional[str]) -> Dict[str, Any]:
        """检查数据格式。
        
        Args:
            df: 待检查的DataFrame
            symbol: 期货品种代码
            
        Returns:
            包含检查结果的字典
        """
        errors = []
        warnings = []
        corrections = []
        corrected_df = df.copy()
        
        # 检查必需列
        missing_columns = [col for col in self.required_columns if col not in df.columns]
        if missing_columns:
            errors.append(f"缺少必需列: {missing_columns}")
        
        # 检查数据类型
        if 'datetime' in df.columns:
            # 尝试转换datetime列
            try:
                corrected_df['datetime'] = pd.to_datetime(corrected_df['datetime'])
            except Exception as e:
                errors.append(f"datetime列转换失败: {e}")
        
        # 检查数值列的数据类型
        numeric_columns = ['open', 'high', 'low', 'close', 'volume']
        if 'open_interest' in df.columns:
            numeric_columns.append('open_interest')
        
        for col in numeric_columns:
            if col in df.columns:
                # 检查是否为数值类型
                if not pd.api.types.is_numeric_dtype(df[col]):
                    try:
                        corrected_df[col] = pd.to_numeric(corrected_df[col], errors='coerce')
                        corrections.append(f"列{col}已转换为数值类型")
                    except Exception as e:
                        errors.append(f"列{col}无法转换为数值类型: {e}")
        
        # 检查缺失值
        for col in df.columns:
            missing_count = df[col].isnull().sum()
            if missing_count > 0:
                missing_pct = (missing_count / len(df)) * 100
                if missing_pct > 10:  # 超过10%的缺失值视为错误
                    errors.append(f"列{col}缺失值过多: {missing_count}个 ({missing_pct:.2f}%)")
                else:
                    warnings.append(f"列{col}存在缺失值: {missing_count}个 ({missing_pct:.2f}%)")
                    
                    # 如果启用自动纠正，使用前向填充
                    if self.enable_auto_correction and col in ['open', 'high', 'low', 'close']:
                        corrected_df[col] = corrected_df[col].fillna(method='ffill')
                        corrections.append(f"列{col}缺失值已用前向填充处理")
                    elif self.enable_auto_correction and col == 'volume':
                        corrected_df[col] = corrected_df[col].fillna(0)
                        corrections.append(f"列{col}缺失值已填充为0")
        
        return {
            'errors': errors,
            'warnings': warnings,
            'corrections': corrections,
            'corrected_df': corrected_df
        }
    
    def _check_logical_consistency(self, df: pd.DataFrame, symbol: Optional[str]) -> Dict[str, Any]:
        """检查逻辑一致性。
        
        Args:
            df: 待检查的DataFrame
            symbol: 期货品种代码
            
        Returns:
            包含检查结果的字典
        """
        errors = []
        warnings = []
        corrections = []
        corrected_df = df.copy()
        
        # 确保必要的列存在
        required_ohlc = ['open', 'high', 'low', 'close']
        if not all(col in df.columns for col in required_ohlc):
            return {
                'errors': errors + ["缺少OHLC列，无法进行逻辑一致性检查"],
                'warnings': warnings,
                'corrections': corrections,
                'corrected_df': corrected_df
            }
        
        # 检查OHLC逻辑关系
        # high >= low
        invalid_hl = corrected_df['high'] < corrected_df['low']
        if invalid_hl.any():
            error_count = invalid_hl.sum()
            errors.append(f"发现{error_count}条记录的high低于low")
            
            if self.enable_auto_correction:
                # 修正：将low设置为high的值（或反之，取较保守的方案）
                corrected_df.loc[invalid_hl, 'low'] = corrected_df.loc[invalid_hl, 'high']
                corrections.append(f"已修正{error_count}条high<low的记录，将low设置为high的值")
        
        # 检查open和close是否在[low, high]范围内
        invalid_oc = (
            (corrected_df['open'] < corrected_df['low']) | 
            (corrected_df['open'] > corrected_df['high']) |
            (corrected_df['close'] < corrected_df['low']) | 
            (corrected_df['close'] > corrected_df['high'])
        )
        if invalid_oc.any():
            error_count = invalid_oc.sum()
            errors.append(f"发现{error_count}条记录的open或close超出[low, high]范围")
            
            if self.enable_auto_correction:
                # 将超出范围的值裁剪到[low, high]范围内
                corrected_df.loc[invalid_oc, 'open'] = corrected_df.loc[invalid_oc, 'open'].clip(
                    corrected_df.loc[invalid_oc, 'low'], 
                    corrected_df.loc[invalid_oc, 'high']
                )
                corrected_df.loc[invalid_oc, 'close'] = corrected_df.loc[invalid_oc, 'close'].clip(
                    corrected_df.loc[invalid_oc, 'low'], 
                    corrected_df.loc[invalid_oc, 'high']
                )
                corrections.append(f"已修正{error_count}条open或close超出[low, high]范围的记录")
        
        # 检查成交量非负
        if 'volume' in df.columns:
            negative_volume = corrected_df['volume'] < 0
            if negative_volume.any():
                error_count = negative_volume.sum()
                errors.append(f"发现{error_count}条记录的成交量为负值")
                
                if self.enable_auto_correction:
                    corrected_df.loc[negative_volume, 'volume'] = 0
                    corrections.append(f"已将{error_count}条负成交量记录设置为0")
        
        # 检查持仓量非负（如果存在）
        if 'open_interest' in df.columns:
            negative_oi = corrected_df['open_interest'] < 0
            if negative_oi.any():
                error_count = negative_oi.sum()
                warnings.append(f"发现{error_count}条记录的持仓量为负值")
                
                if self.enable_auto_correction:
                    corrected_df.loc[negative_oi, 'open_interest'] = 0
                    corrections.append(f"已将{error_count}条负持仓量记录设置为0")
        
        return {
            'errors': errors,
            'warnings': warnings,
            'corrections': corrections,
            'corrected_df': corrected_df
        }
    
    def _check_value_ranges(self, df: pd.DataFrame, symbol: Optional[str]) -> Dict[str, Any]:
        """检查数值范围。
        
        Args:
            df: 待检查的DataFrame
            symbol: 期货品种代码
            
        Returns:
            包含检查结果的字典
        """
        errors = []
        warnings = []
        corrections = []
        corrected_df = df.copy()
        
        # 获取品种特定的价格范围
        price_range = self.price_ranges.get(symbol, self.price_ranges['default']) if symbol else self.price_ranges['default']
        min_price, max_price = price_range
        
        # 检查价格列的范围
        price_columns = ['open', 'high', 'low', 'close']
        for col in price_columns:
            if col in df.columns:
                # 检查是否超出合理范围
                out_of_range = (corrected_df[col] < min_price) | (corrected_df[col] > max_price)
                if out_of_range.any():
                    error_count = out_of_range.sum()
                    errors.append(f"列{col}有{error_count}个值超出合理范围[{min_price}, {max_price}]")
                    
                    if self.enable_auto_correction:
                        # 将超出范围的值设置为边界值
                        corrected_df.loc[corrected_df[col] < min_price, col] = min_price
                        corrected_df.loc[corrected_df[col] > max_price, col] = max_price
                        corrections.append(f"列{col}超出范围的值已被截断到[{min_price}, {max_price}]")
        
        # 检查成交量范围（应该非负，且通常不会异常大）
        if 'volume' in df.columns:
            # 检查极端大值（使用IQR方法）
            Q1 = corrected_df['volume'].quantile(0.25)
            Q3 = corrected_df['volume'].quantile(0.75)
            IQR = Q3 - Q1
            lower_bound = Q1 - 1.5 * IQR
            upper_bound = Q3 + 1.5 * IQR
            
            # 只检查上界异常（下界已经在逻辑一致性中检查过非负）
            extreme_high = corrected_df['volume'] > upper_bound
            if extreme_high.any():
                error_count = extreme_high.sum()
                warnings.append(f"成交量列有{error_count}个可能的极端大值（超过上界{upper_bound:.0f}）")
                
                if self.enable_auto_correction:
                    # 使用中位数替换极端值
                    median_volume = corrected_df['volume'].median()
                    corrected_df.loc[extreme_high, 'volume'] = median_volume
                    corrections.append(f"已将{error_count}个极端大成交量值替换为中位数{median_volume:.0f}")
        
        # 检持仓量范围（如果存在）
        if 'open_interest' in df.columns:
            # 同样使用IQR方法检查异常大值
            Q1 = corrected_df['open_interest'].quantile(0.25)
            Q3 = corrected_df['open_interest'].quantile(0.75)
            IQR = Q3 - Q1
            upper_bound = Q3 + 1.5 * IQR
            
            extreme_high = corrected_df['open_interest'] > upper_bound
            if extreme_high.any():
                error_count = extreme_high.sum()
                warnings.append(f"持仓量列有{error_count}个可能的极端大值（超过上界{upper_bound:.0f}）")
                
                if self.enable_auto_correction:
                    median_oi = corrected_df['open_interest'].median()
                    corrected_df.loc[extreme_high, 'open_interest'] = median_oi
                    corrections.append(f"已将{error_count}个极端大持仓量值替换为中位数{median_oi:.0f}")
        
        return {
            'errors': errors,
            'warnings': warnings,
            'corrections': corrections,
            'corrected_df': corrected_df
        }
    
    def _check_time_series_integrity(self, df: pd.DataFrame) -> Dict[str, Any]:
        """检查时间序列完整性。
        
        Args:
            df: 待检查的DataFrame
            
        Returns:
            包含检查结果的字典
        """
        errors = []
        warnings = []
        corrections = []
        corrected_df = df.copy()
        
        if 'datetime' not in df.columns:
            return {
                'errors': errors,
                'warnings': warnings + ["缺少datetime列，无法进行时间序列完整性检查"],
                'corrections': corrections,
                'corrected_df': corrected_df
            }
        
        # 确保datetime是datetime类型
        if not pd.api.types.is_datetime64_any_dtype(corrected_df['datetime']):
            try:
                corrected_df['datetime'] = pd.to_datetime(corrected_df['datetime'])
            except Exception as e:
                return {
                    'errors': errors + [f"datetime列转换失败: {e}"],
                    'warnings': warnings,
                    'corrections': corrections,
                    'corrected_df': corrected_df
                }
        
        # 按时间排序
        if not corrected_df['datetime'].is_monotonic_increasing:
            warnings.append("数据不是按时间升序排列")
            if self.enable_auto_correction:
                corrected_df = corrected_df.sort_values('datetime').reset_index(drop=True)
                corrections.append("数据已按时间升序排列")
        
        # 检查重复的时间戳
        duplicate_times = corrected_df['datetime'].duplicated()
        if duplicate_times.any():
            error_count = duplicate_times.sum()
            errors.append(f"发现{error_count}个重复的时间戳")
            
            if self.enable_auto_correction:
                # 保留第一条记录，删除重复的
                corrected_df = corrected_df.drop_duplicates(subset=['datetime'], keep='first')
                corrections.append(f"已删除{error_count}个重复的时间戳记录")
        
        # 检查时间间隔（期货数据通常应该是连续的交易日）
        # 这里我们只做基本的检查，不强制要求连续（因为可能有停牌、周末等）
        if len(corrected_df) > 1:
            time_diffs = corrected_df['datetime'].diff().dt.total_seconds() / (24 * 3600)  # 转换为天数
            # 排除第一个NaN值
            time_diffs = time_diffs.dropna()
            
            # 检查异常大的时间间隔（可能表示数据缺失）
            # 正常期货数据间隔应该是1天（交易日）或2-3天（周末）
            large_gaps = time_diffs > 7  # 超过一周的间隔可能值得注意
            if large_gaps.any():
                gap_count = large_gaps.sum()
                max_gap = time_diffs.max()
                warnings.append(f"发现{gap_count}个时间间隔超过7天的记录，最大间隔{max_gap:.1f}天")
                
                # 不自动纠正时间间隔，因为这可能是真实的市场情况（如节假日）
        
        return {
            'errors': errors,
            'warnings': warnings,
            'corrections': corrections,
            'corrected_df': corrected_df
        }
    
    def _detect_anomalies(self, df: pd.DataFrame, symbol: Optional[str]) -> Dict[str, Any]:
        """检测异常值。
        
        Args:
            df: 待检测的DataFrame
            symbol: 期货品种代码
            
        Returns:
            包含检测结果的字典
        """
        errors = []
        warnings = []
        corrections = []
        corrected_df = df.copy()
        
        # 确保必要的列存在
        required_columns = ['open', 'high', 'low', 'close']
        if not all(col in df.columns for col in required_columns):
            return {
                'errors': errors,
                'warnings': warnings,
                'corrections': corrections,
                'corrected_df': corrected_df
            }
        
        # 计算价格变化率
        corrected_df['price_change'] = corrected_df['close'].pct_change()
        
        # 检测异常大的价格变化（使用阈值）
        extreme_changes = abs(corrected_df['price_change']) > self.max_price_change_pct
        # 排除第一个NaN值
        extreme_changes.iloc[0] = False
        
        if extreme_changes.any():
            error_count = extreme_changes.sum()
            max_change = corrected_df['price_change'].abs().max()
            warnings.append(f"发现{error_count}个价格变化率超过{self.max_price_change_pct*100}%的记录，最大变化率{max_change*100:.2f}%")
            
            # 价格异常通常不自动纠正，因为这可能是真实的市场波动
            # 但可以记录下来供人工审查
        
        # 检测成交量异常（使用Z-score方法）
        if 'volume' in df.columns and len(df) > 10:  # 需要足够的数据计算统计量
            volume_mean = corrected_df['volume'].mean()
            volume_std = corrected_df['volume'].std()
            
            if volume_std > 0:  # 避免除以零
                volume_z_scores = abs((corrected_df['volume'] - volume_mean) / volume_std)
                extreme_volume = volume_z_scores > 3  # 超过3个标准差视为异常
                
                if extreme_volume.any():
                    error_count = extreme_volume.sum()
                    warnings.append(f"发现{error_count}个成交量异常值（Z-score > 3）")
                    
                    if self.enable_auto_correction:
                        # 使用中位数替换异常值
                        median_volume = corrected_df['volume'].median()
                        corrected_df.loc[extreme_volume, 'volume'] = median_volume
                        corrections.append(f"已将{error_count}个异常成交量值替换为中位数{median_volume:.0f}")
        
        # 检测价格异常点（使用布林带方法）
        if len(df) > 20:  # 需要足够的数据
            # 计算移动平均和标准差
            window = min(20, len(df) // 2)
            rolling_mean = corrected_df['close'].rolling(window=window, center=False).mean()
            rolling_std = corrected_df['close'].rolling(window=window, center=False).std()
            
            # 布林带上下轨
            upper_band = rolling_mean + (2 * rolling_std)
            lower_band = rolling_mean - (2 * rolling_std)
            
            # 检测超出布林带的点
            above_upper = corrected_df['close'] > upper_band
            below_lower = corrected_df['close'] < lower_band
            extreme_prices = above_upper | below_lower
            # 排除开始时的NaN值（由于滚动窗口）
            extreme_prices.iloc[:window] = False
            
            if extreme_prices.any():
                error_count = extreme_prices.sum()
                warnings.append(f"发现{error_count}个价格超出布林带(2σ)的记录")
                
                if self.enable_auto_correction:
                    # 将超出布林带的值拉回到带内
                    corrected_df.loc[above_upper, 'close'] = upper_band[above_upper]
                    corrected_df.loc[below_lower, 'close'] = lower_band[below_lower]
                    corrections.append(f"已将{error_count}个超出布林带的价格拉回到带内")
        
        # 删除临时列
        if 'price_change' in corrected_df.columns:
            corrected_df = corrected_df.drop(columns=['price_change'])
        
        return {
            'errors': errors,
            'warnings': warnings,
            'corrections': corrections,
            'corrected_df': corrected_df
        }
    
    def _calculate_quality_score(self, 
                                errors: List[str], 
                                warnings: List[str], 
                                total_records: int) -> float:
        """计算数据质量分数。
        
        Args:
            errors: 错误列表
            warnings: 警告列表
            total_records: 总记录数
            
        Returns:
            数据质量分数（0-100）
        """
        if total_records == 0:
            return 0.0
        
        # 基础分数
        score = 100.0
        
        # 根据错误扣分（每个错误扣10分，但最多扣50分）
        error_penalty = min(len(errors) * 10, 50)
        score -= error_penalty
        
        # 根据警告扣分（每个警告扣2分，但最多扣30分）
        warning_penalty = min(len(warnings) * 2, 30)
        score -= warning_penalty
        
        # 确保分数在0-100范围内
        score = max(0.0, min(100.0, score))
        
        return round(score, 2)
    
    def validate_multiple_files(self, 
                               file_paths: List[Union[str, Path]],
                               symbols: Optional[List[str]] = None) -> List[Dict[str, Any]]:
        """批量验证多个数据文件。
        
        Args:
            file_paths: 文件路径列表
            symbols: 对应的品种代码列表（可选）
            
        Returns:
            验证结果列表
        """
        if symbols is None:
            symbols = [None] * len(file_paths)
        elif len(symbols) != len(file_paths):
            raise ValueError("symbols列表长度必须与file_paths列表长度匹配")
        
        results = []
        for i, file_path in enumerate(file_paths):
            symbol = symbols[i] if i < len(symbols) else None
            try:
                # 读取文件
                if isinstance(file_path, str):
                    file_path = Path(file_path)
                
                if file_path.suffix.lower() == '.csv':
                    df = pd.read_csv(file_path)
                elif file_path.suffix.lower() in ['.xlsx', '.xls']:
                    df = pd.read_excel(file_path)
                else:
                    raise ValueError(f"不支持的文件格式: {file_path.suffix}")
                
                # 验证数据
                result = self.validate_dataframe(
                    df, 
                    symbol=symbol, 
                    data_source=str(file_path)
                )
                result['file_path'] = str(file_path)
                results.append(result)
                
            except Exception as e:
                logger.error(f"读取或验证文件{file_path}时出错: {e}")
                results.append({
                    'file_path': str(file_path),
                    'symbol': symbol,
                    'data_source': str(file_path),
                    'validation_time': datetime.now().isoformat(),
                    'original_shape': (0, 0),
                    'is_valid': False,
                    'errors': [f"文件读取或验证失败: {e}"],
                    'warnings': [],
                    'corrections_applied': [],
                    'data_quality_score': 0.0,
                    'validated_df': pd.DataFrame()
                })
        
        return results
    
    def generate_validation_report(self, 
                                  validation_results: List[Dict[str, Any]],
                                  output_path: Optional[Union[str, Path]] = None) -> str:
        """生成数据验证报告。
        
        Args:
            validation_results: 验证结果列表
            output_path: 报告输出路径（可选）
            
        Returns:
            报告内容（字符串格式）
        """
        report_lines = [
            "=" * 80,
            "期货数据验证报告",
            "=" * 80,
            f"生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            f"验证文件数量: {len(validation_results)}",
            ""
        ]
        
        # 汇总统计
        total_files = len(validation_results)
        valid_files = sum(1 for r in validation_results if r['is_valid'])
        invalid_files = total_files - valid_files
        
        avg_quality_score = np.mean([r['data_quality_score'] for r in validation_results]) if validation_results else 0
        
        report_lines.extend([
            "汇总统计:",
            f"  有效文件: {valid_files}/{total_files} ({valid_files/total_files*100:.1f}%)",
            f"  无效文件: {invalid_files}/{total_files} ({invalid_files/total_files*100:.1f}%)",
            f"  平均质量分数: {avg_quality_score:.2f}",
            ""
        ])
        
        # 详细结果
        report_lines.append("详细验证结果:")
        report_lines.append("-" * 80)
        
        for i, result in enumerate(validation_results, 1):
            report_lines.extend([
                f"{i}. 文件: {result.get('file_path', 'Unknown')}",
                f"   品种: {result.get('symbol', 'Unknown')}",
                f"   数据来源: {result.get('data_source', 'Unknown')}",
                f"   原始数据形状: {result['original_shape']}",
                f"   是否有效: {'是' if result['is_valid'] else '否'}",
                f"   数据质量分数: {result['data_quality_score']:.2f}",
                f"   错误数量: {len(result['errors'])}",
                f"   警告数量: {len(result['warnings'])}",
                f"   应用修正数量: {len(result['corrections_applied'])}",
                ""
            ])
            
            if result['errors']:
                report_lines.append("   错误详情:")
                for error in result['errors'][:5]:  # 只显示前5个错误
                    report_lines.append(f"     - {error}")
                if len(result['errors']) > 5:
                    report_lines.append(f"     ... 以及另外 {len(result['errors']) - 5} 个错误")
                report_lines.append("")
            
            if result['warnings']:
                report_lines.append("   警告详情:")
                for warning in result['warnings'][:5]:  # 只显示前5个警告
                    report_lines.append(f"     - {warning}")
                if len(result['warnings']) > 5:
                    report_lines.append(f"     ... 以及另外 {len(result['warnings']) - 5} 个警告")
                report_lines.append("")
            
            if result['corrections_applied']:
                report_lines.append("   应用的修正:")
                for correction in result['corrections_applied'][:5]:  # 只显示前5个修正
                    report_lines.append(f"     - {correction}")
                if len(result['corrections_applied']) > 5:
                    report_lines.append(f"     ... 以及另外 {len(result['corrections_applied']) - 5} 个修正")
                report_lines.append("")
            
            report_lines.append("")
        
        # 建议
        report_lines.extend([
            "改进建议:",
            "-" * 40
        ])
        
        # 基于验证结果生成建议
        all_errors = []
        all_warnings = []
        for result in validation_results:
            all_errors.extend(result['errors'])
            all_warnings.extend(result['warnings'])
        
        # 错误类型统计
        error_types = {}
        for error in all_errors:
            # 简单分类
            if '缺少' in error or 'missing' in error.lower():
                error_types['missing_columns'] = error_types.get('missing_columns', 0) + 1
            elif '转换' in error or 'convert' in error.lower():
                error_types['data_type'] = error_types.get('data_type', 0) + 1
            elif '缺失值' in error or 'null' in error.lower():
                error_types['missing_values'] = error_types.get('missing_values', 0) + 1
            elif 'high低于low' in error or 'high.*low' in error.lower():
                error_types['ohlc_logic'] = error_types.get('ohlc_logic', 0) + 1
            elif '超出[low, high]范围' in error or 'range' in error.lower():
                error_types['price_range'] = error_types.get('price_range', 0) + 1
            elif '成交量为负' in error or 'negative volume' in error.lower():
                error_types['negative_volume'] = error_types.get('negative_volume', 0) + 1
            else:
                error_types['other'] = error_types.get('other', 0) + 1
        
        if error_types:
            report_lines.append("主要问题类型:")
            for error_type, count in sorted(error_types.items(), key=lambda x: x[1], reverse=True):
                report_lines.append(f"  {error_type}: {count} 次")
            report_lines.append("")
        
        # 通用建议
        report_lines.extend([
            "通用改进建议:",
            "1. 确保数据文件包含所有必需列: datetime, open, high, low, close, volume",
            "2. 确保datetime列能被正确解析为日期时间格式",
            "3. 确保OHLC逻辑关系正确: high >= low, open和close在[low, high]范围内",
            "4. 确保成交量和持仓量非负",
            "5. 定期检查和清理数据中的异常值和缺失值",
            "6. 考虑使用数据验证作为数据管道的一部分，在数据进入系统之前进行验证",
            ""
        ])
        
        report_lines.extend([
            "=" * 80,
            "报告结束",
            "=" * 80
        ])
        
        report_content = "\n".join(report_lines)
        
        # 如果指定了输出路径，保存报告
        if output_path:
            try:
                if isinstance(output_path, str):
                    output_path = Path(output_path)
                output_path.parent.mkdir(parents=True, exist_ok=True)
                with open(output_path, 'w', encoding='utf-8') as f:
                    f.write(report_content)
                logger.info(f"验证报告已保存至: {output_path}")
            except Exception as e:
                logger.error(f"保存验证报告时出错: {e}")
        
        return report_content


def validate_futures_data(df: pd.DataFrame, 
                         symbol: Optional[str] = None,
                         data_source: str = "unknown") -> Dict[str, Any]:
    """便捷函数：验证期货数据。
    
    Args:
        df: 待验证的数据DataFrame
        symbol: 期货品种代码（用于获取特定的验证规则）
        data_source: 数据来源描述
        
    Returns:
        包含验证结果和建议的字典
    """
    validator = FuturesDataValidator()
    return validator.validate_dataframe(df, symbol, data_source)


def validate_futures_file(file_path: Union[str, Path],
                         symbol: Optional[str] = None) -> Dict[str, Any]:
    """便捷函数：验证期货数据文件。
    
    Args:
        file_path: 文件路径
        symbol: 期货品种代码（可选）
        
    Returns:
        包含验证结果和建议的字典
    """
    validator = FuturesDataValidator()
    
    # 读取文件
    if isinstance(file_path, str):
        file_path = Path(file_path)
    
    try:
        if file_path.suffix.lower() == '.csv':
            df = pd.read_csv(file_path)
        elif file_path.suffix.lower() in ['.xlsx', '.xls']:
            df = pd.read_excel(file_path)
        else:
            raise ValueError(f"不支持的文件格式: {file_path.suffix}")
        
        # 验证数据
        result = validator.validate_dataframe(df, symbol, str(file_path))
        result['file_path'] = str(file_path)
        return result
        
    except Exception as e:
        logger.error(f"读取或验证文件{file_path}时出错: {e}")
        return {
            'file_path': str(file_path),
            'symbol': symbol,
            'data_source': str(file_path),
            'validation_time': datetime.now().isoformat(),
            'original_shape': (0, 0),
            'is_valid': False,
            'errors': [f"文件读取或验证失败: {e}"],
            'warnings': [],
            'corrections_applied': [],
            'data_quality_score': 0.0,
            'validated_df': pd.DataFrame()
        }


if __name__ == "__main__":
    # 示例用法
    import sys
    
    if len(sys.argv) > 1:
        # 从命令行参数读取文件路径
        file_path = sys.argv[1]
        symbol = sys.argv[2] if len(sys.argv) > 2 else None
        
        result = validate_futures_file(file_path, symbol)
        
        print(f"文件: {result['file_path']}")
        print(f"品种: {result['symbol']}")
        print(f"是否有效: {result['is_valid']}")
        print(f"数据质量分数: {result['data_quality_score']:.2f}")
        print(f"错误数量: {len(result['errors'])}")
        print(f"警告数量: {len(result['warnings'])}")
        
        if result['errors']:
            print("\n错误:")
            for error in result['errors']:
                print(f"  - {error}")
        
        if result['warnings']:
            print("\n警告:")
            for warning in result['warnings']:
                print(f"  - {warning}")
    else:
        print("用法: python data_validator.py <文件路径> [品种代码]")