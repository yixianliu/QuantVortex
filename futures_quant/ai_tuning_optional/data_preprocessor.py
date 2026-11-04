"""数据预处理模块。

提供期货数据的清洗、标准化、特征工程等预处理功能，
为模型训练和参数优化准备高质量的输入数据。

M1-07：本包从 ``futures_quant/ai/tuning/`` 迁移到 ``ai_tuning_optional/``，
顶层引入 ``_HAVE_SKLEARN`` 开关——缺 scikit-learn 时 import 不崩，
首次调用相关类时才抛出带安装命令的 ``ImportError``。
"""
from __future__ import annotations

import logging
from typing import Dict, List, Tuple, Optional, Any

import numpy as np
import pandas as pd

# ---------------------------------------------------------------------------
# M1-07 lazy import：sklearn 缺失时以 _SklearnStub 占位，import 不崩；
# 首次实例化才抛出带 pip 命令的 ImportError。
# ---------------------------------------------------------------------------
_HAVE_SKLEARN = False
try:
    from sklearn.preprocessing import StandardScaler, MinMaxScaler, RobustScaler
    from sklearn.impute import SimpleImputer
    _HAVE_SKLEARN = True
except ImportError:  # pragma: no cover - 依赖缺失路径
    class _SklearnStub:
        """占位类：任何调用均抛带安装命令的 ImportError。"""

        def __init__(self, *args, **kwargs):
            raise ImportError(
                "使用本模块需要 scikit-learn：pip install scikit-learn")

        def __getattr__(self, name: str) -> Any:
            raise ImportError(
                "使用本模块需要 scikit-learn：pip install scikit-learn")

    StandardScaler = MinMaxScaler = RobustScaler = SimpleImputer = _SklearnStub  # type: ignore

logger = logging.getLogger(__name__)


class FuturesDataPreprocessor:
    """期货数据预处理器。
    
    负责期货行情数据的清洗、标准化、特征工程等预处理工作，
    确保输入数据质量，提升模型训练和参数优化的效果。
    """
    
    def __init__(self, 
                 scaling_method: str = "standard",
                 handle_missing: str = "mean",
                 feature_range: Tuple[float, float] = (-1, 1)):
        """初始化数据预处理器。
        
        Args:
            scaling_method: 标准化方法，可选 "standard", "minmax", "robust"
            handle_missing: 缺失值处理方法，可选 "mean", "median", "forward_fill", "drop"
            feature_range: 特征缩放范围（仅当使用MinMaxScaler时有效）
        """
        self.scaling_method = scaling_method
        self.handle_missing = handle_missing
        self.feature_range = feature_range
        
        # 初始化各种预处理器
        self.scaler = None
        self.imputer = None
        self.feature_names = None
        
        self._initialize_preprocessors()
    
    def _initialize_preprocessors(self):
        """初始化预处理器对象."""
        # 缺失值处理器
        if self.handle_missing in ["mean", "median"]:
            self.imputer = SimpleImputer(strategy=self.handle_missing)
        # 注意：forward_fill和drop需要在DataFrame上直接处理
        
        # 标准化器
        if self.scaling_method == "standard":
            self.scaler = StandardScaler()
        elif self.scaling_method == "minmax":
            self.scaler = MinMaxScaler(feature_range=self.feature_range)
        elif self.scaling_method == "robust":
            self.scaler = RobustScaler()
        else:
            raise ValueError(f"不支持的标准化方法: {self.scaling_method}")
    
    def clean_data(self, df: pd.DataFrame) -> pd.DataFrame:
        """清洗期货数据。
        
        移除明显异常的数据点，确保数据质量。
        
        Args:
            df: 原始期货数据DataFrame，应包含OHLCV等字段
            
        Returns:
            清洗后的DataFrame
        """
        logger.info("开始清洗期货数据...")
        cleaned_df = df.copy()
        
        # 确保必要的列存在
        required_columns = ['open', 'high', 'low', 'close', 'volume']
        missing_columns = [col for col in required_columns if col in required_columns if col not in cleaned_df.columns]
        if missing_columns:
            logger.warning(f"缺少必要的列: {missing_columns}")
        
        # 处理缺失值
        if self.handle_missing == "forward_fill":
            cleaned_df = cleaned_df.fillna(method='ffill')
        elif self.handle_missing == "drop":
            cleaned_df = cleaned_df.dropna()
        # 对于mean/median，将在transform阶段处理
        
        # 移除明显异常的价格数据
        if all(col in cleaned_df.columns for col in ['high', 'low']):
            # 确保high >= low
            invalid_hl = cleaned_df['high'] < cleaned_df['low']
            if invalid_hl.any():
                logger.warning(f"发现{invalid_hl.sum()}条high<low的记录，将进行修正")
                # 修正：将low设置为high的最小值，或high设置为low的最大值
                cleaned_df.loc[invalid_hl, 'low'] = cleaned_df.loc[invalid_hl, 'high']
        
        if all(col in cleaned_df.columns for col in ['open', 'high', 'low', 'close']):
            # 确保open和close在[low, high]范围内
            invalid_oc = (
                (cleaned_df['open'] < cleaned_df['low']) | 
                (cleaned_df['open'] > cleaned_df['high']) |
                (cleaned_df['close'] < cleaned_df['low']) | 
                (cleaned_df['close'] > cleaned_df['high'])
            )
            if invalid_oc.any():
                logger.warning(f"发现{invalid_oc.sum()}条open或close超出[low,high]范围的记录")
                # 将超出范围的值裁剪到[low, high]范围内
                cleaned_df.loc[invalid_oc, 'open'] = cleaned_df.loc[invalid_oc, 'open'].clip(
                    cleaned_df.loc[invalid_oc, 'low'], 
                    cleaned_df.loc[invalid_oc, 'high']
                )
                cleaned_df.loc[invalid_oc, 'close'] = cleaned_df.loc[invalid_oc, 'close'].clip(
                    cleaned_df.loc[invalid_oc, 'low'], 
                    cleaned_df.loc[invalid_oc, 'high']
                )
        
        # 移除成交量为负值的记录
        if 'volume' in cleaned_df.columns:
            invalid_volume = cleaned_df['volume'] < 0
            if invalid_volume.any():
                logger.warning(f"发现{invalid_volume.sum()}条成交量为负值的记录，将设置为0")
                cleaned_df.loc[invalid_volume, 'volume'] = 0
        
        logger.info(f"数据清洗完成，原始数据{len(df)}条，清洗后{len(cleaned_df)}条")
        return cleaned_df
    
    def normalize_features(self, df: pd.DataFrame, 
                          feature_columns: Optional[List[str]] = None) -> Tuple[pd.DataFrame, Dict]:
        """标准化特征。
        
        Args:
            df: 需要标准化的数据DataFrame
            feature_columns: 需要标准化的特征列名列表，None表示所有数值列
            
        Returns:
            (标准化后的DataFrame, 预处理参数字典)
        """
        logger.info("开始特征标准化...")
        
        # 确定要处理的特征列
        if feature_columns is None:
            # 自动选择所有数值列
            feature_columns = df.select_dtypes(include=[np.number]).columns.tolist()
        
        if not feature_columns:
            logger.warning("没有找到需要标准化的数值特征")
            return df, {}
        
        # 提取特征数据
        feature_data = df[feature_columns].values
        
        # 处理缺失值（如果使用mean/median策略）
        if self.imputer is not None and self.handle_missing in ["mean", "median"]:
            feature_data = self.imputer.fit_transform(feature_data)
        
        # 标准化
        scaled_data = self.scaler.fit_transform(feature_data)
        
        # 创建结果DataFrame
        result_df = df.copy()
        result_df[feature_columns] = scaled_data
        
        # 保存预处理参数，以便后续逆变换
        prep_params = {
            'scaling_method': self.scaling_method,
            'feature_columns': feature_columns,
            'scaler_params': {
                'mean': getattr(self.scaler, 'mean_', None).tolist() if hasattr(self.scaler, 'mean_') else None,
                'scale': getattr(self.scaler, 'scale_', None).tolist() if hasattr(self.scaler, 'scale_') else None,
                'min': getattr(self.scaler, 'min_', None).tolist() if hasattr(self.scaler, 'min_') else None,
                'data_min': getattr(self.scaler, 'data_min_', None).tolist() if hasattr(self.scaler, 'data_min_') else None,
                'data_max': getattr(self.scaler, 'data_max_', None).tolist() if hasattr(self.scaler, 'data_max_') else None,
            },
            'imputer_params': {
                'strategy': getattr(self.imputer, 'strategy', None) if self.imputer else None,
                'statistics': getattr(self.imputer, 'statistics_', None).tolist() if hasattr(self.imputer, 'statistics_') else None
            } if self.imputer else None
        }
        
        self.feature_names = feature_columns
        logger.info(f"特征标准化完成，处理了{len(feature_columns)}个特征")
        return result_df, prep_params
    
    def create_sequences(self, data: np.ndarray, 
                        sequence_length: int,
                        target_column_index: int = 0) -> Tuple[np.ndarray, np.ndarray]:
        """创建时间序列数据用于时序模型训练。
        
        Args:
            data: 输入数据数组，形状为 (n_samples, n_features)
            sequence_length: 时间序列长度
            target_column_index: 目标变量在特征中的索引位置
            
        Returns:
            (X, y) 其中X形状为 (n_samples-sequence_length, sequence_length, n_features),
                  y形状为 (n_samples-sequence_length,)
        """
        logger.info(f"创建时间序列数据，序列长度: {sequence_length}")
        
        if len(data) < sequence_length + 1:
            raise ValueError(f"数据长度({len(data)})必须大于序列长度({sequence_length})+1")
        
        X, y = [], []
        for i in range(len(data) - sequence_length):
            X.append(data[i:(i + sequence_length)])
            y.append(data[i + sequence_length, target_column_index])
        
        X_array = np.array(X)
        y_array = np.array(y)
        
        logger.info(f"创建了{len(X_array)}个序列，X形状: {X_array.shape}, y形状: {y_array.shape}")
        return X_array, y_array
    
    def inverse_transform(self, scaled_data: np.ndarray) -> np.ndarray:
        """逆标准化数据。
        
        Args:
            scaled_data: 标准化后的数据
            
        Returns:
            逆标准化后的原始数据
        """
        if self.scaler is None:
            raise ValueError("标准化器未初始化，请先调用normalize_features方法")
        
        return self.scaler.inverse_transform(scaled_data)
    
    def get_feature_names(self) -> Optional[List[str]]:
        """获取特征名称列表。
        
        Returns:
            特征名称列表，如果尚未处理数据则返回None
        """
        return self.feature_names


def preprocess_futures_data(df: pd.DataFrame,
                           scaling_method: str = "standard",
                           handle_missing: str = "mean",
                           feature_range: Tuple[float, float] = (-1, 1),
                           sequence_length: Optional[int] = None,
                           target_column: str = "close") -> Tuple[pd.DataFrame, Dict, Optional[Tuple[np.ndarray, np.ndarray]]]:
    """便捷函数：一步完成期货数据的预处理。
    
    Args:
        df: 原始期货数据DataFrame
        scaling_method: 标准化方法
        handle_missing: 缺失值处理方法
        feature_range: 特征缩放范围
        sequence_length: 时间序列长度，如果提供则创建序列数据
        target_column: 目标列名（用于序列创建时的目标变量）
        
    Returns:
        (预处理后的DataFrame, 预处理参数, 可选的序列数据(X, y))
    """
    # 创建预处理器
    preprocessor = FuturesDataPreprocessor(
        scaling_method=scaling_method,
        handle_missing=handle_missing,
        feature_range=feature_range
    )
    
    # 清洗数据
    cleaned_df = preprocessor.clean_data(df)
    
    # 标准化特征
    normalized_df, prep_params = preprocessor.normalize_features(cleaned_df)
    
    # 如果需要，创建时间序列数据
    sequence_data = None
    if sequence_length is not None and target_column in normalized_df.columns:
        # 获取目标列的索引
        feature_cols = preprocessor.get_feature_names()
        if feature_cols is None:
            feature_cols = normalized_df.select_dtypes(include=[np.number]).columns.tolist()
        
        try:
            target_idx = feature_cols.index(target_column)
        except ValueError:
            logger.warning(f"目标列{target_column}不在特征列中，将使用第一个数值列作为目标")
            target_idx = 0 if feature_cols else 0
        
        # 准备用于序列创建的数据（所有数值列）
        feature_data = normalized_df[feature_cols].values
        sequence_data = preprocessor.create_sequences(feature_data, sequence_length, target_idx)
    
    return normalized_df, prep_params, sequence_data