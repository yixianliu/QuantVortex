"""性能评估模块。

提供模型性能的全面评估功能，包括回归指标、分类指标、风险调整收益指标等，
能够根据项目需求评估不同模型和参数组合的表现。

M1-07：顶层引入 ``_HAVE_SKLEARN`` 开关——缺 scikit-learn 时 import 不崩，
首次调用相关函数/类时才抛出带安装命令的 ``ImportError``。
"""
from __future__ import annotations

import logging
from typing import Dict, List, Tuple, Optional, Any, Union

import numpy as np
import pandas as pd

# ---------------------------------------------------------------------------
# M1-07 lazy import：sklearn 缺失时以 _SklearnStub 占位；scipy 缺失同理。
# ---------------------------------------------------------------------------
_HAVE_SKLEARN = False
try:
    from sklearn.metrics import (
        mean_squared_error, mean_absolute_error, r2_score,
        accuracy_score, precision_score, recall_score, f1_score,
        confusion_matrix, classification_report,
    )
    _HAVE_SKLEARN = True
except ImportError:  # pragma: no cover - 依赖缺失路径
    class _SklearnStub:
        def __init__(self, *args, **kwargs):
            raise ImportError("使用本模块需要 scikit-learn：pip install scikit-learn")
        def __getattr__(self, name: str) -> Any:
            raise ImportError("使用本模块需要 scikit-learn：pip install scikit-learn")
    def _unavailable(*a, **kw):
        raise ImportError("使用本模块需要 scikit-learn：pip install scikit-learn")
    mean_squared_error = mean_absolute_error = r2_score = _unavailable
    accuracy_score = precision_score = recall_score = f1_score = _unavailable
    confusion_matrix = classification_report = _unavailable
    # 占位类以通过任何类型引用
    _SklearnMetricStub = _SklearnStub

try:
    from scipy import stats
    _HAVE_SCIPY = True
except ImportError:  # pragma: no cover
    _HAVE_SCIPY = False
    class _ScipyStatsStub:
        def __init__(self, *a, **kw):
            raise ImportError("使用本模块需要 scipy：pip install scipy")
        def __getattr__(self, name: str) -> Any:
            raise ImportError("使用本模块需要 scipy：pip install scipy")
    stats = _ScipyStatsStub  # type: ignore

logger = logging.getLogger(__name__)


class ModelPerformanceEvaluator:
    """模型性能评估器。
    
    提供全面的模型性能评估功能，包括：
    - 回归模型评估（MSE, MAE, RMSE, R²等）
    - 分类模型评估（准确率, 精确率, 召回率, F1等）
    - 时间序列预测评估（方向准确率, 趋势一致性等）
    - 金融模型特有评估（夏普率, 最大回撤, 风险调整收益等）
    """
    
    def __init__(self, risk_free_rate: float = 0.02):
        """初始化性能评估器。
        
        Args:
            risk_free_rate: 无风险利率，用于计算夏普率等指标
        """
        self.risk_free_rate = risk_free_rate
        self.evaluation_history = []
    
    def evaluate_regression(self, 
                           y_true: Union[np.ndarray, pd.Series],
                           y_pred: Union[np.ndarray, pd.Series],
                           verbose: bool = True) -> Dict[str, float]:
        """评估回归模型性能。
        
        Args:
            y_true: 真实值
            y_pred: 预测值
            verbose: 是否记录详细日志
            
        Returns:
            包含各种回归评估指标的字典
        """
        logger.info("开始评估回归模型性能...") if verbose else None
        
        # 转换为numpy数组以确保兼容性
        y_true = np.asarray(y_true)
        y_pred = np.asarray(y_pred)
        
        # 移除任何NaN值
        mask = ~(np.isnan(y_true) | np.isnan(y_pred))
        y_true_clean = y_true[mask]
        y_pred_clean = y_pred[mask]
        
        if len(y_true_clean) == 0:
            logger.warning("清理后没有有效数据用于评估")
            return {}
        
        # 计算基本回归指标
        mse = mean_squared_error(y_true_clean, y_pred_clean)
        mae = mean_absolute_error(y_true_clean, y_pred_clean)
        rmse = np.sqrt(mse)
        r2 = r2_score(y_true_clean, y_pred_clean)
        
        # 计算平均绝对百分比误差（MAPE）
        # 避免除以零
        non_zero_mask = y_true_clean != 0
        if np.any(non_zero_mask):
            mape = np.mean(np.abs((y_true_clean[non_zero_mask] - y_pred_clean[non_zero_mask]) / y_true_clean[non_zero_mask])) * 100
        else:
            mape = np.inf
        
        # 计算对称平均绝对百分比误差（sMAPE）
        denominator = np.abs(y_true_clean) + np.abs(y_pred_clean)
        smape_denominator_mask = denominator != 0
        if np.any(smape_denominator_mask):
            smape = np.mean(2.0 * np.abs(y_pred_clean[smape_denominator_mask] - y_true_clean[smape_denominator_mask]) / 
                           denominator[smape_denominator_mask]) * 100
        else:
            smape = np.inf
        
        # 计算解释方差分数
        if np.var(y_true_clean) > 0:
            explained_variance = 1 - (np.var(y_true_clean - y_pred_clean) / np.var(y_true_clean))
        else:
            explained_variance = 0.0
        
        results = {
            'mse': float(mse),
            'mae': float(mae),
            'rmse': float(rmse),
            'r2': float(r2),
            'mape': float(mape),
            'smape': float(smape),
            'explained_variance': float(explained_variance),
            'max_error': float(np.max(np.abs(y_true_clean - y_pred_clean))),
            'mean_prediction': float(np.mean(y_pred_clean)),
            'mean_true': float(np.mean(y_true_clean)),
            'std_prediction': float(np.std(y_pred_clean)),
            'std_true': float(np.std(y_true_clean))
        }
        
        logger.info(f"回归模型评估完成 - RMSE: {rmse:.6f}, R²: {r2:.6f}") if verbose else None
        return results
    
    def evaluate_classification(self, 
                               y_true: Union[np.ndarray, pd.Series],
                               y_pred: Union[np.ndarray, pd.Series],
                               labels: Optional[List] = None,
                               verbose: bool = True) -> Dict[str, Any]:
        """评估分类模型性能。
        
        Args:
            y_true: 真实标签
            y_pred: 预测标签
            labels: 类别标签列表，用于指定类别顺序
            verbose: 是否记录详细日志
            
        Returns:
            包含各种分类评估指标的字典
        """
        logger.info("开始评估分类模型性能...") if verbose else None
        
        # 转换为numpy数组
        y_true = np.asarray(y_true)
        y_pred = np.asarray(y_pred)
        
        # 移除任何NaN值
        mask = ~(np.isnan(y_true) | np.isnan(y_pred))
        y_true_clean = y_true[mask]
        y_pred_clean = y_pred[mask]
        
        if len(y_true_clean) == 0:
            logger.warning("清理后没有有效数据用于评估")
            return {}
        
        # 计算基本分类指标
        accuracy = accuracy_score(y_true_clean, y_pred_clean)
        
        # 计算精确率、召回率和F1（宏平均和微平均）
        precision_macro = precision_score(y_true_clean, y_pred_clean, average='macro', zero_division=0)
        precision_micro = precision_score(y_true_clean, y_pred_clean, average='micro', zero_division=0)
        precision_weighted = precision_score(y_true_clean, y_pred_clean, average='weighted', zero_division=0)
        
        recall_macro = recall_score(y_true_clean, y_pred_clean, average='macro', zero_division=0)
        recall_micro = recall_score(y_true_clean, y_pred_clean, average='micro', zero_division=0)
        recall_weighted = recall_score(y_true_clean, y_pred_clean, average='weighted', zero_division=0)
        
        f1_macro = f1_score(y_true_clean, y_pred_clean, average='macro', zero_division=0)
        f1_micro = f1_score(y_true_clean, y_pred_clean, average='micro', zero_division=0)
        f1_weighted = f1_score(y_true_clean, y_pred_clean, average='weighted', zero_division=0)
        
        # 混淆矩阵
        cm = confusion_matrix(y_true_clean, y_pred_clean, labels=labels)
        
        # 分类报告（字符串形式）
        class_report = classification_report(y_true_clean, y_pred_clean, labels=labels, output_dict=True)
        
        results = {
            'accuracy': float(accuracy),
            'precision_macro': float(precision_macro),
            'precision_micro': float(precision_micro),
            'precision_weighted': float(precision_weighted),
            'recall_macro': float(recall_macro),
            'recall_micro': float(recall_micro),
            'recall_weighted': float(recall_weighted),
            'f1_macro': float(f1_macro),
            'f1_micro': float(f1_micro),
            'f1_weighted': float(f1_weighted),
            'confusion_matrix': cm.tolist() if hasattr(cm, 'tolist') else cm,
            'classification_report': class_report
        }
        
        logger.info(f"分类模型评估完成 - 准确率: {accuracy:.4f}") if verbose else None
        return results
    
    def evaluate_directional_accuracy(self, 
                                     y_true: Union[np.ndarray, pd.Series],
                                     y_pred: Union[np.ndarray, pd.Series],
                                     verbose: bool = True) -> Dict[str, float]:
        """评估方向预测准确率（特别适用于金融时间序列）。
        
        评估模型预测价格变动方向（上涨/下跌）的准确率。
        
        Args:
            y_true: 真实值序列
            y_pred: 预测值序列
            verbose: 是否记录详细日志
            
        Returns:
            包含方向准确率相关指标的字典
        """
        logger.info("开始评估方向预测准确率...") if verbose else None
        
        # 转换为numpy数组
        y_true = np.asarray(y_true)
        y_pred = np.asarray(y_pred)
        
        # 移除任何NaN值
        mask = ~(np.isnan(y_true) | np.isnan(y_pred))
        y_true_clean = y_true[mask]
        y_pred_clean = y_pred[mask]
        
        if len(y_true_clean) < 2:
            logger.warning("数据点太少，无法计算方准确率")
            return {}
        
        # 计算价格变化（使用一阶差分）
        true_changes = np.diff(y_true_clean)
        pred_changes = np.diff(y_pred_clean)
        
        # 确定方向（1表示上涨，-1表示下跌，0表示无变化）
        true_directions = np.sign(true_changes)
        pred_directions = np.sign(pred_changes)
        
        # 计算方向准确率
        directional_accuracy = np.mean(true_directions == pred_directions)
        
        # 计算方向精确率和召回率（对于上涨预测）
        up_mask = true_directions == 1
        if np.any(up_mask):
            up_precision = np.mean(pred_directions[up_mask] == 1) if np.any(pred_directions[up_mask] == 1) else 0.0
            up_recall = np.mean(true_directions[pred_directions == 1] == 1) if np.any(pred_directions == 1) else 0.0
        else:
            up_precision = 0.0
            up_recall = 0.0
        
        # 计算方向精确率和召回率（对于下跌预测）
        down_mask = true_directions == -1
        if np.any(down_mask):
            down_precision = np.mean(pred_directions[down_mask] == -1) if np.any(pred_directions[down_mask] == -1) else 0.0
            down_recall = np.mean(true_directions[pred_directions == -1] == -1) if np.any(pred_directions == -1) else 0.0
        else:
            down_precision = 0.0
            down_recall = 0.0
        
        # 计算 Cohen's Kappa 系数衡量一致性
        # 简化版本：观察一致性 - 预期一致性
        n_samples = len(true_directions)
        if n_samples > 0:
            # 观察一致性
            observed_agreement = np.mean(true_directions == pred_directions)
            
            # 预期一致性（假设独立）
            true_dist = np.bincount(true_directions + 1, minlength=3) / n_samples  # +1为了将-1,0,1映射到0,1,2
            pred_dist = np.bincount(pred_directions + 1, minlength=3) / n_samples
            expected_agreement = np.sum(true_dist * pred_dist)
            
            if expected_agreement < 1:
                cohens_kappa = (observed_agreement - expected_agreement) / (1 - expected_agreement)
            else:
                cohens_kappa = 0.0
        else:
            cohens_kappa = 0.0
        
        results = {
            'directional_accuracy': float(directional_accuracy),
            'up_precision': float(up_precision),
            'up_recall': float(up_recall),
            'down_precision': float(down_precision),
            'down_recall': float(down_recall),
            'cohens_kappa': float(cohens_kappa),
            'n_samples': int(n_samples),
            'true_up_ratio': float(np.mean(true_directions == 1)),
            'true_down_ratio': float(np.mean(true_directions == -1)),
            'true_neutral_ratio': float(np.mean(true_directions == 0)),
            'pred_up_ratio': float(np.mean(pred_directions == 1)),
            'pred_down_ratio': float(np.mean(pred_directions == -1)),
            'pred_neutral_ratio': float(np.mean(pred_directions == 0))
        }
        
        logger.info(f"方向预测准确率评估完成 - 准确率: {directional_accuracy:.4f}") if verbose else None
        return results
    
    def evaluate_financial_performance(self, 
                                      returns: Union[np.ndarray, pd.Series],
                                      benchmark_returns: Optional[Union[np.ndarray, pd.Series]] = None,
                                      verbose: bool = True) -> Dict[str, float]:
        """评估金融模型性能（基于收益率序列）。
        
        计算夏普率、最大回撤、卡玛比率等金融特有指标。
        
        Args:
            returns: 模型收益率序列（日收益率或周期收益率）
            benchmark_returns: 基准收益率序列，用于计算阿尔法、贝塔等相对指标
            verbose: 是否记录详细日志
            
        Returns:
            包含金融性能指标的字典
        """
        logger.info("开始评估金融模型性能...") if verbose else None
        
        # 转换为numpy数组
        returns = np.asarray(returns)
        
        # 移除任何NaN值
        returns_clean = returns[~np.isnan(returns)]
        
        if len(returns_clean) == 0:
            logger.warning("没有有效的收益率数据用于评估")
            return {}
        
        # 计算基本收益指标
        total_return = np.prod(1 + returns_clean) - 1  # 累计收益
        annualized_return = np.prod(1 + returns_clean) ** (252 / len(returns_clean)) - 1  # 年化收益（假设252个交易日）
        mean_return = np.mean(returns_clean)
        std_return = np.std(returns_clean)
        
        # 计算夏普率
        excess_returns = returns_clean - self.risk_free_rate / 252  # 日无风险利率
        if std_return > 0:
            sharpe_ratio = np.mean(excess_returns) / std_return * np.sqrt(252)  # 年化夏普率
        else:
            sharpe_ratio = 0.0
        
        # 计算索提诺率（使用下行偏差）
        downside_returns = np.minimum(returns_clean - self.risk_free_rate / 252, 0)
        downside_std = np.std(downside_returns) if np.any(downside_returns < 0) else 0.0
        if downside_std > 0:
            sortino_ratio = np.mean(excess_returns) / downside_std * np.sqrt(252)
        else:
            sortino_ratio = np.inf if np.mean(excess_returns) > 0 else 0.0
        
        # 计算最大回撤
        cumulative_returns = np.cumprod(1 + returns_clean)
        running_max = np.maximum.accumulate(cumulative_returns)
        drawdown = (cumulative_returns - running_max) / running_max
        max_drawdown = np.min(drawdown)  # 最大回撤为负值
        
        # 计算卡玛比率（年化收益率 / 绝对值最大回撤）
        if max_drawdown != 0:
            calmar_ratio = annualized_return / abs(max_drawdown)
        else:
            calmar_ratio = np.inf if annualized_return > 0 else 0.0
        
        # 计算收益波动率
        volatility = std_return * np.sqrt(252)  # 年化波动率
        
        # 如果提供了基准收益率，计算相对指标
        if benchmark_returns is not None:
            benchmark_returns = np.asarray(benchmark_returns)
            benchmark_clean = benchmark_returns[~np.isnan(benchmark_returns)]
            
            # 确保长度匹配（取较短的长度）
            min_len = min(len(returns_clean), len(benchmark_clean))
            if min_len > 0:
                returns_aligned = returns_clean[:min_len]
                benchmark_aligned = benchmark_clean[:min_len]
                
                # 计算贝塔
                if np.var(benchmark_aligned) > 0:
                    covariance = np.cov(returns_aligned, benchmark_aligned)[0][1]
                    beta = covariance / np.var(benchmark_aligned)
                else:
                    beta = 0.0
                
                # 计算阿尔法（年化）
                benchmark_annual_return = np.prod(1 + benchmark_aligned) ** (252 / min_len) - 1
                alpha = annualized_return - (self.risk_free_rate + beta * (benchmark_annual_return - self.risk_free_rate))
                
                # 计算信息比率
                active_returns = returns_aligned - benchmark_aligned
                tracking_error = np.std(active_returns) * np.sqrt(252)
                if tracking_error > 0:
                    information_ratio = (annualized_return - benchmark_annual_return) / tracking_error
                else:
                    information_ratio = 0.0
            else:
                beta = alpha = information_ratio = 0.0
        else:
            beta = alpha = information_ratio = 0.0
        
        results = {
            'total_return': float(total_return),
            'annualized_return': float(annualized_return),
            'mean_return': float(mean_return),
            'volatility': float(volatility),
            'sharpe_ratio': float(sharpe_ratio),
            'sortino_ratio': float(sortino_ratio),
            'max_drawdown': float(max_drawdown),
            'calmar_ratio': float(calmar_ratio),
            'beta': float(beta) if benchmark_returns is not None else None,
            'alpha': float(alpha) if benchmark_returns is not None else None,
            'information_ratio': float(information_ratio) if benchmark_returns is not None else None,
            'win_rate': float(np.mean(returns_clean > 0)),
            'profit_factor': float(np.sum(returns_clean[returns_clean > 0]) / abs(np.sum(returns_clean[returns_clean < 0]))) if np.any(returns_clean < 0) and np.sum(returns_clean[returns_clean < 0]) != 0 else np.inf
        }
        
        logger.info(f"金融模型评估完成 - 年化收益: {annualized_return:.4f}, 夏普率: {sharpe_ratio:.4f}, 最大回撤: {max_drawdown:.4f}") if verbose else None
        return results
    
    def evaluate_model_comprehensive(self, 
                                   y_true: Union[np.ndarray, pd.Series],
                                   y_pred: Union[np.ndarray, pd.Series],
                                   returns: Optional[Union[np.ndarray, pd.Series]] = None,
                                   benchmark_returns: Optional[Union[np.ndarray, pd.Series]] = None,
                                   task_type: str = "regression",
                                   verbose: bool = True) -> Dict[str, Any]:
        """综合评估模型性能。
        
        根据任务类型自动选择合适的评估指标。
        
        Args:
            y_true: 真实值
            y_pred: 预测值
            returns: 收益率序列（用于金融评估，可选）
            benchmark_returns: 基准收益率序列（用于金融评估，可选）
            task_type: 任务类型，可选 "regression", "classification", "financial"
            verbose: 是否记录详细日志
            
        Returns:
            包含所有相关评估指标的综合字典
        """
        logger.info(f"开始综合评估{task_type}模型性能...")
        start_time = time.time()
        
        results = {
            'task_type': task_type,
            'evaluation_time': 0.0,
            'timestamp': pd.Timestamp.now().isoformat()
        }
        
        if task_type == "regression":
            results.update(self.evaluate_regression(y_true, y_pred, verbose))
            # 如果提供了收益率数据，也进行金融评估
            if returns is not None:
                results['financial_metrics'] = self.evaluate_financial_performance(returns, benchmark_returns, verbose)
                
        elif task_type == "classification":
            results.update(self.evaluate_classification(y_true, y_pred, verbose))
            
        elif task_type == "directional":
            results.update(self.evaluate_directional_accuracy(y_true, y_pred, verbose))
            # 方向预测通常也关注收益表现
            if returns is not None:
                results['financial_metrics'] = self.evaluate_financial_performance(returns, benchmark_returns, verbose)
                
        elif task_type == "financial":
            if returns is not None:
                results.update(self.evaluate_financial_performance(returns, benchmark_returns, verbose))
            else:
                logger.warning("金融任务类型需要提供returns参数")
        else:
            logger.warning(f"不支持的任务类型: {task_type}")
            return {}
        
        results['evaluation_time'] = time.time() - start_time
        self.evaluation_history.append(results.copy())
        
        logger.info(f"综合模型评估完成，耗时{results['evaluation_time']:.2f}秒")
        return results
    
    def get_evaluation_history(self) -> List[Dict[str, Any]]:
        """获取评估历史。
        
        Returns:
            评估历史列表
        """
        return self.evaluation_history.copy()
    
    def compare_models(self, 
                      model_results: List[Dict[str, Any]],
                      primary_metric: str = "sharpe_ratio",
                      higher_better: bool = True) -> Dict[str, Any]:
        """比较多个模型的性能。
        
        Args:
            model_results: 模型评估结果列表
            primary_metric: 用于比较的主要指标名称
            higher_better: 指标是否越大越好
            
        Returns:
            包含比较结果和排名的字典
        """
        logger.info(f"开始比较{len(model_results)}个模型的性能...")
        
        if not model_results:
            return {}
        
        # 提取主要指标用于排序
        scores = []
        for i, result in enumerate(model_results):
            # 尝试从不同位置获取主要指标
            score = None
            if primary_metric in result:
                score = result[primary_metric]
            elif 'financial_metrics' in result and primary_metric in result['financial_metrics']:
                score = result['financial_metrics'][primary_metric]
            elif 'regression_metrics' in result and primary_metric in result['regression_metrics']:
                score = result['regression_metrics'][primary_metric]
            
            if score is None:
                logger.warning(f"模型{i}中未找到指标{primary_metric}，将使用0作为得分")
                score = 0.0
            
            scores.append((i, score))
        
        # 排序
        scores.sort(key=lambda x: x[1], reverse=higher_better)
        
        # 生成排名结果
        ranked_results = []
        for rank, (index, score) in enumerate(scores, 1):
            ranked_results.append({
                'rank': rank,
                'model_index': index,
                'score': score,
                'model_result': model_results[index]
            })
        
        comparison_result = {
            'primary_metric': primary_metric,
            'higher_better': higher_better,
            'best_model_index': scores[0][0] if scores else None,
            'best_score': scores[0][1] if scores else None,
            'worst_model_index': scores[-1][0] if scores else None,
            'worst_score': scores[-1][1] if scores else None,
            'ranked_results': ranked_results,
            'total_models': len(model_results)
        }
        
        logger.info(f"模型比较完成，最佳模型索引: {scores[0][0] if scores else None}")
        return comparison_result