"""模型参数优化模块。

提供超参数自动搜索、网格搜索、随机搜索和贝叶斯优化等功能，
能够根据项目需求自动或半自动地调整模型参数，提升模型性能。
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from typing import Dict, List, Tuple, Optional, Any, Callable, Union
import logging
import time

logger = logging.getLogger(__name__)

# M2-11：scikit-learn 为**可选**依赖。原实现在模块顶层硬导入 sklearn，
# 导致未安装 scikit-learn 的环境下 `import parameter_optimizer` 直接崩溃，
# 连带让所有依赖它的模块不可用。现改为惰性导入：本模块始终可正常导入，
# 真正调用搜索接口时才校验依赖，缺失时抛出带安装命令的明确提示。
_SKLEARN_INSTALL_HINT = (
    "需安装 scikit-learn：pip install scikit-learn"
    "（conda 环境可用 conda install scikit-learn）。"
    "超参搜索（grid_search / random_search）依赖该库。"
)


def _require_sklearn():
    """惰性导入 sklearn 组件；缺失时抛出带安装指引的 ImportError。

    Returns:
        ``(ParameterGrid, RandomizedSearchCV, GridSearchCV, make_scorer,
        TimeSeriesSplit)``
    """
    try:
        from sklearn.model_selection import (
            ParameterGrid, RandomizedSearchCV, GridSearchCV, TimeSeriesSplit,
        )
        from sklearn.metrics import make_scorer
    except ImportError as e:  # pragma: no cover - 取决于运行环境
        raise ImportError(_SKLEARN_INSTALL_HINT) from e
    return ParameterGrid, RandomizedSearchCV, GridSearchCV, make_scorer, TimeSeriesSplit


def _time_series_cv(n_splits: int):
    """M2-11：时序交叉验证切分器。

    金融时序数据**不能随机打散**切分，整数 ``cv=5`` 会被 sklearn 解释为
    KFold 随机折，导致用未来数据验证过去（未来函数）。改用 TimeSeriesSplit
    保证验证集始终位于训练集之后。
    """
    _, _, _, _, TimeSeriesSplit = _require_sklearn()
    return TimeSeriesSplit(n_splits=n_splits)


class ModelParameterOptimizer:
    """模型参数优化器。
    
    提供超参数自动搜索功能，支持网格搜索、随机搜索和贝叶斯优化等方法，
    为各种机器学习和深度学习模型寻找最优参数组合。
    """
    
    def __init__(self, 
                 scoring_metric: str = "neg_mean_squared_error",
                 cv_folds: int = 5,
                 n_jobs: int = -1,
                 verbose: int = 0):
        """初始化参数优化器。
        
        Args:
            scoring_metric: 评估指标，用于模型选择
            cv_folds: 交叉验证折数
            n_jobs: 并作业数，-1表示使用所有可用核心
            verbose: 详细程度
        """
        self.scoring_metric = scoring_metric
        self.cv_folds = cv_folds
        self.n_jobs = n_jobs
        self.verbose = verbose
        
        # 优化历史
        self.optimization_history = []
        self.best_params = None
        self.best_score = None
        self.best_estimator = None
    
    def grid_search(self, 
                   estimator: Any,
                   param_grid: Dict[str, List],
                   X: Union[np.ndarray, pd.DataFrame],
                   y: Union[np.ndarray, pd.Series],
                   **kwargs) -> Dict[str, Any]:
        """网格搜索超参数优化。
        
        Args:
            estimator: 待优化的模型估计器
            param_grid: 参数网格字典
            X: 特征数据
            y: 目标数据
            **kwargs: 传递给GridSearchCV的其他参数
            
        Returns:
            包含最优参数和评分的字典
        """
        logger.info("开始网格搜索超参数优化...")
        start_time = time.time()
        
        # M2-11：惰性校验 sklearn 依赖（缺失时给出安装提示，而非 import 期崩溃）
        ParameterGrid, _, GridSearchCV, make_scorer, _tss = _require_sklearn()

        # 创建得分函数
        scorer = make_scorer(self._get_score_func())

        # 执行网格搜索
        grid_search = GridSearchCV(
            estimator=estimator,
            param_grid=param_grid,
            scoring=scorer,
            cv=_time_series_cv(self.cv_folds),
            n_jobs=self.n_jobs,
            verbose=self.verbose,
            **kwargs
        )

        grid_search.fit(X, y)

        # 记录结果
        self.best_params = grid_search.best_params_
        self.best_score = grid_search.best_score_
        self.best_estimator = grid_search.best_estimator_

        optimization_result = {
            'method': 'grid_search',
            'best_params': self.best_params,
            'best_score': self.best_score,
            'best_estimator': self.best_estimator,
            'cv_results': grid_search.cv_results_,
            'n_iterations': len(list(ParameterGrid(param_grid))),
            'optimization_time': time.time() - start_time
        }
        
        self.optimization_history.append(optimization_result)
        logger.info(f"网格搜索完成，最佳参数: {self.best_params}, 最佳得分: {self.best_score:.6f}")
        
        return optimization_result
    
    def random_search(self, 
                     estimator: Any,
                     param_distributions: Dict[str, Any],
                     X: Union[np.ndarray, pd.DataFrame],
                     y: Union[np.ndarray, pd.Series],
                     n_iter: int = 100,
                     **kwargs) -> Dict[str, Any]:
        """随机搜索超参数优化。
        
        Args:
            estimator: 待优化的模型估计器
            param_distributions: 参数分布字典
            X: 特征数据
            y: 目标数据
            n_iter: 随机搜索迭代次数
            **kwargs: 传递给RandomizedSearchCV的其他参数
            
        Returns:
            包含最优参数和评分的字典
        """
        logger.info(f"开始随机搜索超参数优化（{n_iter}次迭代）...")
        start_time = time.time()
        
        # M2-11：惰性校验 sklearn 依赖
        _, RandomizedSearchCV, _, make_scorer, _tss = _require_sklearn()

        # 创建得分函数
        scorer = make_scorer(self._get_score_func())
        
        # 执行随机搜索
        random_search = RandomizedSearchCV(
            estimator=estimator,
            param_distributions=param_distributions,
            n_iter=n_iter,
            scoring=scorer,
            cv=_time_series_cv(self.cv_folds),
            n_jobs=self.n_jobs,
            verbose=self.verbose,
            random_state=42,
            **kwargs
        )
        
        random_search.fit(X, y)
        
        # 记录结果
        self.best_params = random_search.best_params_
        self.best_score = random_search.best_score_
        self.best_estimator = random_search.best_estimator_
        
        optimization_result = {
            'method': 'random_search',
            'best_params': self.best_params,
            'best_score': self.best_score,
            'best_estimator': self.best_estimator,
            'cv_results': random_search.cv_results_,
            'n_iterations': n_iter,
            'optimization_time': time.time() - start_time
        }
        
        self.optimization_history.append(optimization_result)
        logger.info(f"随机搜索完成，最佳参数: {self.best_params}, 最佳得分: {self.best_score:.6f}")
        
        return optimization_result
    
    def optimize_lstm_hyperparameters(self, 
                                     X_train: np.ndarray,
                                     y_train: np.ndarray,
                                     X_val: np.ndarray,
                                     y_val: np.ndarray,
                                     input_shape: Tuple[int, int],
                                     epochs: int = 50) -> Dict[str, Any]:
        """专门优化LSTM模型的超参数。
        
        Args:
            X_train: 训练特征数据
            y_train: 训练目标数据
            X_val: 验证特征数据
            y_val: 验证目标数据
            input_shape: 输入数据形状 (sequence_length, n_features)
            epochs: 训练轮数
            
        Returns:
            包含最优LSTM超参数的字典
        """
        logger.info("开始LSTM超参数优化...")
        start_time = time.time()
        
        # 定义LSTM超参数搜索空间
        param_grid = {
            'hidden_size': [32, 64, 128, 256],
            'learning_rate': [0.0001, 0.001, 0.01, 0.1],
            'batch_size': [16, 32, 64, 128],
            'dropout_rate': [0.0, 0.1, 0.2, 0.3],
            'num_layers': [1, 2, 3]
        }
        
        # 这里我们需要一个能够接受这些参数的LSTM包装器
        # 由于现有的LSTM实现可能不直接支持sklearn的接口，
        # 我们将实现一个简单的网格搜索来演示概念
        
        best_score = float('-inf')
        best_params = None
        best_model = None
        results = []
        
        # 简化的网格搜索实现
        from itertools import product
        
        param_names = list(param_grid.keys())
        param_values = list(param_grid.values())
        
        for i, combination in enumerate(product(*param_values)):
            params = dict(zip(param_names, combination))
            logger.debug(f"尝试参数组合 {i+1}: {params}")
            
            try:
                # 创建LSTM模型实例
                # M2-11 + M1-07：修正导入路径。本文件 M1-07 后位于
                # futures_quant/ai_tuning_optional/，`..` 即 futures_quant/，
                # 因此 LSTM 应为 `..ai.lstm`（原 M2-11 阶段的 `..lstm` 是在
                # ai/tuning/ 下的正确写法，M1-07 迁移后需重新校正）。
                from ..ai.lstm import LSTM
                
                model = LSTM(
                    input_size=input_shape[1],
                    hidden_size=params['hidden_size'],
                    output_size=1,
                    # 注意：这里需要根据实际的LSTM实现调整参数
                )
                
                # 训练模型（简化版）
                # 在实际实现中，这里需要适配现有LSTM的fit方法
                # 为了演示，我们假设有一个通用的接口
                model.fit(
                    [X_train[j] for j in range(len(X_train))],
                    y_train,
                    epochs=epochs,
                    lr=params['learning_rate']
                )
                
                # 在验证集上评估
                val_predictions = []
                for j in range(len(X_val)):
                    pred = model.predict_last(X_val[j])
                    val_predictions.append(pred)
                
                val_predictions = np.array(val_predictions)
                # 使用负均方误差作为得分（因为我们要最大化）
                score = -np.mean((val_predictions - y_val) ** 2)
                
                results.append({
                    'params': params.copy(),
                    'score': score
                })
                
                if score > best_score:
                    best_score = score
                    best_params = params.copy()
                    best_model = model
                    
            except Exception as e:
                logger.warning(f"参数组合 {params} 评估失败: {e}")
                continue
        
        optimization_result = {
            'method': 'lstm_hyperparameter_optimization',
            'best_params': best_params,
            'best_score': best_score,
            'best_estimator': best_model,
            'all_results': results,
            'n_iterations': len(results),
            'optimization_time': time.time() - start_time
        }
        
        self.best_params = best_params
        self.best_score = best_score
        self.best_estimator = best_model
        self.optimization_history.append(optimization_result)
        
        logger.info(f"LSTM超参数优化完成，最佳参数: {best_params}, 最佳得分: {best_score:.6f}")
        
        return optimization_result
    
    def _get_score_func(self) -> Callable:
        """获取得分函数。

        Returns:
            可调用的得分函数

        Raises:
            ImportError: 未安装 scikit-learn 时抛出带安装命令的清晰提示
                （M2-11：调用时才需依赖，import 期不校验）。
        """
        # M2-11：改 lazy import —— 无 sklearn 环境下本方法可被"引用到但
        # 不能立刻执行"，实际调用时给出明确错误而不是 ImportError 静默穿透。
        try:
            from sklearn.metrics import (
                mean_squared_error, mean_absolute_error, r2_score,
            )
        except ImportError as e:  # pragma: no cover
            raise ImportError(_SKLEARN_INSTALL_HINT) from e

        if self.scoring_metric == "neg_mean_squared_error":
            return lambda y_true, y_pred: -mean_squared_error(y_true, y_pred)
        elif self.scoring_metric == "neg_mean_absolute_error":
            return lambda y_true, y_pred: -mean_absolute_error(y_true, y_pred)
        elif self.scoring_metric == "r2":
            return lambda y_true, y_pred: r2_score(y_true, y_pred)
        else:
            # 默认使用负均方误差
            return lambda y_true, y_pred: -mean_squared_error(y_true, y_pred)
    
    def get_optimization_history(self) -> List[Dict[str, Any]]:
        """获取优化历史。
        
        Returns:
            优化历史列表
        """
        return self.optimization_history.copy()
    
    def get_best_result(self) -> Dict[str, Any]:
        """获取最优化结果。
        
        Returns:
            包含最优参数和评分的字典
        """
        if self.best_params is None:
            return {}
        
        return {
            'best_params': self.best_params,
            'best_score': self.best_score,
            'best_estimator': self.best_estimator
        }


def optimize_model_parameters(model: Any,
                             X_train: np.ndarray,
                             y_train: np.ndarray,
                             param_grid: Dict[str, List],
                             method: str = "grid_search",
                             **kwargs) -> Dict[str, Any]:
    """便捷函数：优化模型参数。
    
    Args:
        model: 待优化的模型
        X_train: 训练特征数据
        y_train: 训练目标数据
        param_grid: 参数网格或分布
        method: 优化方法，可选 "grid_search", "random_search"
        **kwargs: 传递给优化器的其他参数
        
        Returns:
            优化结果字典
    """
    optimizer = ModelParameterOptimizer(**kwargs)
    
    if method == "grid_search":
        return optimizer.grid_search(model, param_grid, X_train, y_train)
    elif method == "random_search":
        n_iter = kwargs.pop('n_iter', 100)
        return optimizer.random_search(model, param_grid, X_train, y_train, n_iter=n_iter)
    else:
        raise ValueError(f"不支持的优化方法: {method}")


# 预定义的参数网格供常用模型使用
COMMON_PARAM_GRIDS = {
    'lstm': {
        'hidden_size': [32, 64, 128],
        'learning_rate': [0.001, 0.01, 0.1],
        'batch_size': [16, 32, 64]
    },
    'random_forest': {
        'n_estimators': [50, 100, 200],
        'max_depth': [10, 20, None],
        'min_samples_split': [2, 5, 10]
    },
    'xgboost': {
        'n_estimators': [50, 100, 200],
        'max_depth': [3, 6, 9],
        'learning_rate': [0.01, 0.1, 0.2],
        'subsample': [0.8, 0.9, 1.0]
    }
}