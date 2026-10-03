"""结果可视化模块。

提供模型性能评估结果、参数优化过程、预测结果等的可视化功能，
支持多种图表类型和交互式可视化。
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from typing import Dict, List, Tuple, Optional, Any, Union
import logging

# ============================================================
# Lazy import: matplotlib / seaborn（M1-07 隔离）
# ============================================================
# 无 matplotlib 环境下 `import futures_quant.ai_tuning_optional.visualizer`
# 不能抛 ModuleNotFoundError —— 否则上层（若有 import 触达）会被误判为代码
# 回归。业务入口（页面 / 引擎）本就不应 import 本模块；但作为可选模块仍
# 应保证顶层 import 无副作用地通过。
# 实际调用可视化方法前会抛 ImportError 并提示 pip install 命令。
# ============================================================
_HAVE_MATPLOTLIB = False
_HAVE_SEABORN = False
try:
    import matplotlib.pyplot as plt  # type: ignore[assignment]
    from matplotlib.figure import Figure  # type: ignore[assignment]
    _HAVE_MATPLOTLIB = True
except ImportError:  # pragma: no cover
    class _MatplotlibStub:
        """matplotlib 缺失时占位。属性访问/调用会抛 ImportError（懒触发）。"""

        def __getattr__(self, name):
            raise ImportError(
                "使用 futures_quant.ai_tuning_optional.visualizer 需要 matplotlib：pip install matplotlib"
            )

        def __call__(self, *args, **kwargs):
            raise ImportError(
                "使用 futures_quant.ai_tuning_optional.visualizer 需要 matplotlib：pip install matplotlib"
            )

    class Figure:  # type: ignore[no-redef]
        """Figure 占位类：类型注解可用；实例化或访问属性抛 ImportError。"""

        def __init__(self, *args, **kwargs):  # noqa: D407
            raise ImportError(
                "使用 futures_quant.ai_tuning_optional.visualizer 需要 matplotlib：pip install matplotlib"
            )

    plt = _MatplotlibStub()  # type: ignore[assignment]

try:
    import seaborn as sns  # type: ignore[assignment]
    _HAVE_SEABORN = True
except ImportError:  # pragma: no cover
    class _SeabornStub:
        """seaborn 缺失时占位。属性访问抛 ImportError（懒触发）。"""

        def __getattr__(self, name):
            raise ImportError(
                "使用 futures_quant.ai_tuning_optional.visualizer 需要 seaborn：pip install seaborn"
            )

        def __call__(self, *args, **kwargs):
            raise ImportError(
                "使用 futures_quant.ai_tuning_optional.visualizer 需要 seaborn：pip install seaborn"
            )

    sns = _SeabornStub()  # type: ignore[assignment]

# 设置中文字体和样式（仅在依赖就绪时执行，避免顶层副作用）
if _HAVE_MATPLOTLIB and _HAVE_SEABORN:
    plt.rcParams['font.sans-serif'] = ['SimHei', 'DejaVu Sans']
    plt.rcParams['axes.unicode_minus'] = False
    sns.set_style("whitegrid")

logger = logging.getLogger(__name__)


class TuningResultVisualizer:
    """调优结果可视化器。
    
    提供以下可视化功能：
    - 模型性能指标对比图
    - 参数优化过程热力图
    - 预测结果与实际结果对比图
    - 训练过程损失曲线
    - 特征重要性图
    - 回测收益曲线和回撤图
    """
    
    def __init__(self, figsize: Tuple[int, int] = (12, 8), style: str = "whitegrid"):
        """初始化可视化器。
        
        Args:
            figsize: 默认图表大小
            style: seaborn样式
        """
        self.figsize = figsize
        self.style = style
        if _HAVE_MATPLOTLIB and _HAVE_SEABORN:
            sns.set_style(style)
    
    def plot_model_comparison(self, 
                             model_results: List[Dict[str, Any]],
                             metric: str = "sharpe_ratio",
                             task_type: str = "financial",
                             higher_better: bool = True,
                             save_path: Optional[str] = None) -> Figure:
        """绘制模型性能对比条形图。
        
        Args:
            model_results: 模型评估结果列表
            metric: 用于比较的指标名称
            task_type: 任务类型，用于确定从哪里提取指标
            higher_better: 指标是否越大越好
            save_path: 保存路径，如果提供则保存图表
            
        Returns:
            matplotlib Figure对象
        """
        logger.info(f"绘制{len(model_results)}个模型的{metric}对比图...")
        
        # 提取模型名称和得分
        model_names = []
        scores = []
        
        for i, result in enumerate(model_results):
            model_name = result.get('model_name', f'Model_{i}')
            score = None
            
            # 根据任务类型提取指标
            if task_type == "financial" and 'financial_metrics' in result:
                score = result['financial_metrics'].get(metric)
            elif task_type == "regression" and 'regression_metrics' in result:
                score = result['regression_metrics'].get(metric)
            elif task_type == "classification" and 'classification_metrics' in result:
                score = result['classification_metrics'].get(metric)
            elif metric in result:
                score = result[metric]
            
            if score is None:
                logger.warning(f"模型{model_name}中未找到指标{metric}，使用0")
                score = 0.0
            
            model_names.append(model_name)
            scores.append(score)
        
        # 创建图表
        fig, ax = plt.subplots(figsize=self.figsize)
        
        # 创建条形图
        bars = ax.bar(range(len(model_names)), scores, 
                     color=['#ff4757' if s == max(scores) and higher_better 
                           else '#2ed573' if s == min(scores) and not higher_better
                           else '#1e90ff' for s in scores])
        
        # 添加数值标签
        for bar, score in zip(bars, scores):
            height = bar.get_height()
            ax.text(bar.get_x() + bar.get_width()/2., height,
                   f'{score:.4f}',
                   ha='center', va='bottom' if height >= 0 else 'top',
                   fontsize=9)
        
        # 设置图表属性
        ax.set_xlabel('模型', fontsize=12)
        ax.set_ylabel(metric.replace('_', ' ').title(), fontsize=12)
        ax.set_title(f'模型{metric.replace("_", " ").title()}对比', fontsize=14, fontweight='bold')
        ax.set_xticks(range(len(model_names)))
        ax.set_xticklabels(model_names, rotation=45, ha='right')
        
        # 添加网格
        ax.grid(True, alpha=0.3)
        
        plt.tight_layout()
        
        if save_path:
            plt.savefig(save_path, dpi=300, bbox_inches='tight')
            logger.info(f"图表已保存至: {save_path}")
        
        return fig
    
    def plot_optimization_history(self, 
                                 optimization_history: List[Dict[str, Any]],
                                 param_name: Optional[str] = None,
                                 save_path: Optional[str] = None) -> Figure:
        """绘制参数优化过程图。
        
        Args:
            optimization_history: 优化历史列表
            param_name: 特定参数名称，如果提供则绘制该参数的变化
            save_path: 保存路径
            
        Returns:
            matplotlib Figure对象
        """
        logger.info("绘制参数优化过程图...")
        
        if not optimization_history:
            logger.warning("优化历史为空")
            fig, ax = plt.subplots(figsize=self.figsize)
            ax.text(0.5, 0.5, '暂无优化历史数据', 
                   ha='center', va='center', transform=ax.transAxes)
            return fig
        
        # 如果指定了特定参数
        if param_name:
            return self._plot_parameter_evolution(optimization_history, param_name, save_path)
        
        # 否则绘制得分进化图
        fig, (ax1, ax2) = plt.subplots(2, 1, figsize=self.figsize)
        
        iterations = list(range(len(optimization_history)))
        scores = [opt.get('best_score', 0) for opt in optimization_history]
        
        # 得分进化图
        ax1.plot(iterations, scores, 'b-o', linewidth=2, markersize=4)
        ax1.set_xlabel('优化迭代')
        ax1.set_ylabel('最佳得分')
        ax1.set_title('参数优化过程 - 最佳得分进化')
        ax1.grid(True, alpha=0.3)
        
        # 参数分布图（如果有多个参数）
        if optimization_history and 'all_results' in optimization_history[0]:
            # 提取所有参数名称
            first_result = optimization_history[0]
            if 'all_results' in first_result and first_result['all_results']:
                param_names = list(first_result['all_results'][0].get('params', {}).keys())
                if param_names:
                    # 选择前两个参数进行散点图
                    param1, param2 = param_names[0], param_names[1] if len(param_names) > 1 else param_names[0]
                    
                    # 收集所有迭代的参数值和得分
                    param1_vals = []
                    param2_vals = []
                    score_vals = []
                    
                    for opt in optimization_history:
                        if 'all_results' in opt:
                            for result in opt['all_results']:
                                params = result.get('params', {})
                                param1_vals.append(params.get(param1, 0))
                                param2_vals.append(params.get(param2, 0))
                                score_vals.append(result.get('score', 0))
                    
                    if param1_vals and param2_vals:
                        scatter = ax2.scatter(param1_vals, param2_vals, c=score_vals, 
                                            cmap='viridis', alpha=0.6, s=30)
                        ax2.set_xlabel(param1)
                        ax2.set_ylabel(param2)
                        ax2.set_title(f'参数空间分布 (颜色表示得分)')
                        plt.colorbar(scatter, ax=ax2, label='得分')
        
        plt.tight_layout()
        
        if save_path:
            plt.savefig(save_path, dpi=300, bbox_inches='tight')
            logger.info(f"图表已保存至: {save_path}")
        
        return fig
    
    def _plot_parameter_evolution(self, 
                                 optimization_history: List[Dict[str, Any]],
                                 param_name: str,
                                 save_path: Optional[str] = None) -> Figure:
        """绘制特定参数的演化过程。
        
        Args:
            optimization_history: 优化历史列表
            param_name: 参数名称
            save_path: 保存路径
            
        Returns:
            matplotlib Figure对象
        """
        fig, ax = plt.subplots(figsize=self.figsize)
        
        iterations = []
        param_values = []
        best_scores = []
        
        for i, opt in enumerate(optimization_history):
            iterations.append(i)
            best_scores.append(opt.get('best_score', 0))
            
            # 从最佳参数中提取特定参数值
            best_params = opt.get('best_params', {})
            param_values.append(best_params.get(param_name, 0))
        
        # 创建双轴图
        ax2 = ax.twinx()
        
        # 参数值线条
        line1 = ax.plot(iterations, param_values, 'b-o', label=f'{param_name}值', 
                       linewidth=2, markersize=4)
        ax.set_xlabel('优化迭代')
        ax.set_ylabel(f'{param_name}值', color='b')
        ax.tick_params(axis='y', labelcolor='b')
        
        # 得分线条
        line2 = ax2.plot(iterations, best_scores, 'r-s', label='最佳得分', 
                        linewidth=2, markersize=4)
        ax2.set_ylabel('最佳得分', color='r')
        ax2.tick_params(axis='y', labelcolor='r')
        
        # 合并图例
        lines = line1 + line2
        labels = [l.get_label() for l in lines]
        ax.legend(lines, labels, loc='upper left')
        
        ax.set_title(f'参数{param_name}与最佳得分的演化过程')
        ax.grid(True, alpha=0.3)
        
        plt.tight_layout()
        
        if save_path:
            plt.savefig(save_path, dpi=300, bbox_inches='tight')
            logger.info(f"图表已保存至: {save_path}")
        
        return fig
    
    def plot_prediction_vs_actual(self, 
                                 y_true: Union[np.ndarray, pd.Series],
                                 y_pred: Union[np.ndarray, pd.Series],
                                 timestamps: Optional[Union[np.ndarray, pd.Series]] = None,
                                 model_name: str = "Model",
                                 save_path: Optional[str] = None) -> Figure:
        """绘制预测值与实际值对比图。
        
        Args:
            y_true: 真实值
            y_pred: 预测值
            timestamps: 时间戳（可选）
            model_name: 模型名称
            save_path: 保存路径
            
        Returns:
            matplotlib Figure对象
        """
        logger.info(f"绘制{model_name}的预测值与实际值对比图...")
        
        # 转换为numpy数组
        y_true = np.asarray(y_true)
        y_pred = np.asarray(y_pred)
        
        # 移除NaN值
        mask = ~(np.isnan(y_true) | np.isnan(y_pred))
        y_true_clean = y_true[mask]
        y_pred_clean = y_pred[mask]
        
        if timestamps is not None:
            timestamps = np.asarray(timestamps)[mask]
            x_axis = timestamps
            x_label = '时间'
        else:
            x_axis = np.arange(len(y_true_clean))
            x_label = '样本索引'
        
        # 创建图表
        fig, (ax1, ax2) = plt.subplots(2, 1, figsize=self.figsize, height_ratios=[3, 1])
        
        # 上图：预测值 vs 实际值
        ax1.plot(x_axis, y_true_clean, label='实际值', color='#2ed573', linewidth=2)
        ax1.plot(x_axis, y_pred_clean, label='预测值', color='#ff4757', linewidth=2, alpha=0.8)
        ax1.set_ylabel('数值')
        ax1.set_title(f'{model_name} - 预测值与实际值对比', fontsize=14, fontweight='bold')
        ax1.legend()
        ax1.grid(True, alpha=0.3)
        
        # 下图：误差
        errors = y_true_clean - y_pred_clean
        ax2.plot(x_axis, errors, label='预测误差', color='#1e90ff', linewidth=1.5)
        ax2.axhline(y=0, color='black', linestyle='-', alpha=0.3)
        ax2.fill_between(x_axis, errors, 0, alpha=0.3, color='#1e90ff')
        ax2.set_xlabel(x_label)
        ax2.set_ylabel('误差')
        ax2.set_title('预测误差')
        ax2.grid(True, alpha=0.3)
        
        plt.tight_layout()
        
        if save_path:
            plt.savefig(save_path, dpi=300, bbox_inches='tight')
            logger.info(f"图表已保存至: {save_path}")
        
        return fig
    
    def plot_returns_and_drawdown(self, 
                                 returns: Union[np.ndarray, pd.Series],
                                 timestamps: Optional[Union[np.ndarray, pd.Series]] = None,
                                 strategy_name: str = "Strategy",
                                 save_path: Optional[str] = None) -> Figure:
        """绘制收益曲线和回撤图。
        
        Args:
            returns: 收益率序列
            timestamps: 时间戳（可选）
            strategy_name: 策略名称
            save_path: 保存路径
            
        Returns:
            matplotlib Figure对象
        """
        logger.info(f"绘制{strategy_name}的收益曲线和回撤图...")
        
        # 转换为numpy数组
        returns = np.asarray(returns)
        returns_clean = returns[~np.isnan(returns)]
        
        if len(returns_clean) == 0:
            logger.warning("没有有效的收益率数据")
            fig, ax = plt.subplots(figsize=self.figsize)
            ax.text(0.5, 0.5, '暂无收益率数据', 
                   ha='center', va='center', transform=ax.transAxes)
            return fig
        
        # 计算累计收益
        cumulative_returns = np.cumprod(1 + returns_clean) - 1
        
        # 计算回撤
        running_max = np.maximum.accumulate(cumulative_returns)
        drawdown = (cumulative_returns - running_max) / running_max
        
        # 时间轴
        if timestamps is not None:
            timestamps = np.asarray(timestamps)
            timestamps_clean = timestamps[~np.isnan(returns)][:len(returns_clean)]
            x_axis = timestamps_clean
            x_label = '时间'
        else:
            x_axis = np.arange(len(returns_clean))
            x_label = '时间步'
        
        # 创建图表
        fig, (ax1, ax2) = plt.subplots(2, 1, figsize=self.figsize, height_ratios=[3, 1])
        
        # 上图：累计收益曲线
        ax1.plot(x_axis, cumulative_returns, label='累计收益', color='#2ed573', linewidth=2)
        ax1.set_ylabel('累计收益率')
        ax1.set_title(f'{strategy_name} - 收益曲线', fontsize=14, fontweight='bold')
        ax1.legend()
        ax1.grid(True, alpha=0.3)
        
        # 下图：回撤图
        ax2.fill_between(x_axis, drawdown, 0, color='#ff4757', alpha=0.7)
        ax2.plot(x_axis, drawdown, color='#ff4757', linewidth=1)
        ax2.set_ylabel('回撤率')
        ax2.set_xlabel(x_label)
        ax2.set_title('回撤图')
        ax2.grid(True, alpha=0.3)
        
        # 添加最大回撤标注
        max_dd = np.min(drawdown)
        max_dd_idx = np.argmin(drawdown)
        ax2.annotate(f'最大回撤: {max_dd:.2%}', 
                    xy=(x_axis[max_dd_idx], max_dd),
                    xytext=(10, 10), textcoords='offset points',
                    bbox=dict(boxstyle='round,pad=0.3', facecolor='yellow', alpha=0.7),
                    arrowprops=dict(arrowstyle='->', connectionstyle='arc3,rad=0'))
        
        plt.tight_layout()
        
        if save_path:
            plt.savefig(save_path, dpi=300, bbox_inches='tight')
            logger.info(f"图表已保存至: {save_path}")
        
        return fig
    
    def plot_feature_importance(self, 
                               feature_names: List[str],
                               importance_scores: Union[np.ndarray, List[float]],
                               model_name: str = "Model",
                               top_n: int = 10,
                               save_path: Optional[str] = None) -> Figure:
        """绘制特征重要性图。
        
        Args:
            feature_names: 特征名称列表
            importance_scores: 特征重要性得分
            model_name: 模型名称
            top_n: 显示前N个重要特征
            save_path: 保存路径
            
        Returns:
            matplotlib Figure对象
        """
        logger.info(f"绘制{model_name}的特征重要性图...")
        
        # 转换为numpy数组
        importance_scores = np.asarray(importance_scores)
        
        # 确保长度匹配
        if len(feature_names) != len(importance_scores):
            logger.error("特征名称和重要性得分长度不匹配")
            fig, ax = plt.subplots(figsize=self.figsize)
            ax.text(0.5, 0.5, '特征名称和重要性得分长度不匹配', 
                   ha='center', va='center', transform=ax.transAxes)
            return fig
        
        # 选择前N个重要特征
        if top_n and len(feature_names) > top_n:
            indices = np.argsort(importance_scores)[::-1][:top_n]
        else:
            indices = np.argsort(importance_scores)[::-1]
        
        top_feature_names = [feature_names[i] for i in indices]
        top_importance = importance_scores[indices]
        
        # 创建图表
        fig, ax = plt.subplots(figsize=self.figsize)
        
        # 水平条形图
        y_pos = np.arange(len(top_feature_names))
        bars = ax.barh(y_pos, top_importance, color='#1e90ff')
        
        # 添加数值标签
        for i, (bar, score) in enumerate(zip(bars, top_importance)):
            width = bar.get_width()
            ax.text(width, bar.get_y() + bar.get_height()/2.,
                   f' {score:.4f}',
                   ha='left', va='center', fontsize=9)
        
        # 设置图表属性
        ax.set_yticks(y_pos)
        ax.set_yticklabels(top_feature_names)
        ax.set_xlabel('重要性得分')
        ax.set_title(f'{model_name} - 特征重要性 (Top {len(top_feature_names)})', 
                    fontsize=14, fontweight='bold')
        ax.grid(True, alpha=0.3, axis='x')
        
        # 反转y轴使最重要的特征在顶部
        ax.invert_yaxis()
        
        plt.tight_layout()
        
        if save_path:
            plt.savefig(save_path, dpi=300, bbox_inches='tight')
            logger.info(f"图表已保存至: {save_path}")
        
        return fig
    
    def create_dashboard(self,                         tuning_results: Dict[str, Any],
                        save_path: Optional[str] = None) -> Figure:
        """创建调优结果综合仪表板。
        
        Args:
            tuning_results: 调优结果字典，应包含：
                - model_comparison: 模型比较结果
                - optimization_history: 参数优化历史
                - prediction_results: 预测结果
                - financial_performance: 金融性能指标
            save_path: 保存路径
            
        Returns:
            matplotlib Figure对象
        """
        logger.info("创建调优结果综合仪表板...")
        
        # 创建2x3的子图布局
        fig = plt.figure(figsize=(20, 12))
        gs = fig.add_gridspec(2, 3, hspace=0.3, wspace=0.3)
        
        # 1. 模型比较图 (左上)
        ax1 = fig.add_subplot(gs[0, 0])
        if 'model_comparison' in tuning_results:
            self._plot_model_comparison_ax(ax1, tuning_results['model_comparison'])
        else:
            ax1.text(0.5, 0.5, '暂无模型比较数据', 
                    ha='center', va='center', transform=ax1.transAxes)
            ax1.set_title('模型比较')
        
        # 2. 参数优化过程 (中上)
        ax2 = fig.add_subplot(gs[0, 1])
        if 'optimization_history' in tuning_results:
            self._plot_optimization_ax(ax2, tuning_results['optimization_history'])
        else:
            ax2.text(0.5, 0.5, '暂无优化历史数据', 
                    ha='center', va='center', transform=ax2.transAxes)
            ax2.set_title('参数优化过程')
        
        # 3. 预测结果对比 (右上)
        ax3 = fig.add_subplot(gs[0, 2])
        if 'prediction_results' in tuning_results:
            self._plot_prediction_ax(ax3, tuning_results['prediction_results'])
        else:
            ax3.text(0.5, 0.5, '暂无预测结果数据', 
                    ha='center', va='center', transform=ax3.transAxes)
            ax3.set_title('预测结果对比')
        
        # 4. 收益曲线和回撤 (左下)
        ax4 = fig.add_subplot(gs[1, 0])
        if 'financial_performance' in tuning_results:
            self._plot_financial_ax(ax4, tuning_results['financial_performance'])
        else:
            ax4.text(0.5, 0.5, '暂无金融性能数据', 
                    ha='center', va='center', transform=ax4.transAxes)
            ax4.set_title('收益曲线和回撤')
        
        # 5. 特征重要性 (中下)
        ax5 = fig.add_subplot(gs[1, 1])
        if 'feature_importance' in tuning_results:
            self._plot_feature_importance_ax(ax5, tuning_results['feature_importance'])
        else:
            ax5.text(0.5, 0.5, '暂无特征重要性数据', 
                    ha='center', va='center', transform=ax5.transAxes)
            ax5.set_title('特征重要性')
        
        # 6. 综合性能指标 (右下)
        ax6 = fig.add_subplot(gs[1, 2])
        self._plot_performance_summary_ax(ax6, tuning_results)
        ax6.set_title('综合性能指标')
        
        fig.suptitle('AI模型辅助调优结果综合仪表板', fontsize=16, fontweight='bold')
        
        if save_path:
            plt.savefig(save_path, dpi=300, bbox_inches='tight')
            logger.info(f"仪表板已保存至: {save_path}")
        
        return fig
    
    def _plot_model_comparison_ax(self, ax, comparison_data: Dict[str, Any]):
        """在指定轴上绘制模型比较图."""
        # 这里需要根据实际数据结构进行适配
        ax.text(0.5, 0.5, '模型比较图\n(需根据实际数据结构实现)', 
                ha='center', va='center', transform=ax.transAxes)
        ax.set_title('模型比较')
    
    def _plot_optimization_ax(self, ax, history_data: Dict[str, Any]):
        """在指定轴上绘制优化过程图."""
        ax.text(0.5, 0.5, '优化过程图\n(需根据实际数据结构实现)', 
                ha='center', va='center', transform=ax.transAxes)
        ax.set_title('参数优化过程')
    
    def _plot_prediction_ax(self, ax, prediction_data: Dict[str, Any]):
        """在指定轴上绘制预测结果图."""
        ax.text(0.5, 0.5, '预测结果图\n(需根据实际数据结构实现)', 
                ha='center', va='center', transform=ax.transAxes)
        ax.set_title('预测结果对比')
    
    def _plot_financial_ax(self, ax, financial_data: Dict[str, Any]):
        """在指定轴上绘制金融性能图."""
        ax.text(0.5, 0.5, '金融性能图\n(需根据实际数据结构实现)', 
                ha='center', va='center', transform=ax.transAxes)
        ax.set_title('收益曲线和回撤')
    
    def _plot_feature_importance_ax(self, ax, feature_data: Dict[str, Any]):
        """在指定轴上绘制特征重要性图."""
        ax.text(0.5, 0.5, '特征重要性图\n(需根据实际数据结构实现)', 
                ha='center', va='center', transform=ax.transAxes)
        ax.set_title('特征重要性')
    
    def _plot_performance_summary_ax(self, ax, results: Dict[str, Any]):
        """在指定轴上绘制性能指标摘要."""
        # 提取关键性能指标进行展示
        metrics_text = "关键性能指标:\n\n"
        
        # 从不同位置尝试提取指标
        if 'financial_metrics' in results:
            fm = results['financial_metrics']
            metrics_text += f"年化收益: {fm.get('annualized_return', 0):.2%}\n"
            metrics_text += f"夏普率: {fm.get('sharpe_ratio', 0):.2f}\n"
            metrics_text += f"最大回撤: {fm.get('max_drawdown', 0):.2%}\n"
            metrics_text += f"卡尔马比率: {fm.get('calmar_ratio', 0):.2f}\n"
        elif 'regression_metrics' in results:
            rm = results['regression_metrics']
            metrics_text += f"均方误差: {rm.get('mse', 0):.4f}\n"
            metrics_text += f"R²分数: {rm.get('r2', 0):.4f}\n"
            metrics_text += f"平均绝对误差: {rm.get('mae', 0):.4f}\n"
        elif 'classification_metrics' in results:
            cm = results['classification_metrics']
            metrics_text += f"准确率: {cm.get('accuracy', 0):.2%}\n"
            metrics_text += f"F1分数: {cm.get('f1_weighted', 0):.4f}\n"
            metrics_text += f"精确率: {cm.get('precision_weighted', 0):.4f}\n"
            metrics_text += f"召回率: {cm.get('recall_weighted', 0):.4f}\n"
        
        ax.text(0.1, 0.5, metrics_text, 
                ha='left', va='center', transform=ax.transAxes,
                fontsize=10, bbox=dict(boxstyle='round,pad=0.5', 
                                     facecolor='lightblue', alpha=0.8))
        ax.set_xlim(0, 1)
        ax.set_ylim(0, 1)
        ax.axis('off')


def visualize_model_comparison(model_results: List[Dict[str, Any]], 
                              metric: str = "sharpe_ratio",
                              task_type: str = "financial",
                              save_path: Optional[str] = None) -> Figure:
    """便捷函数：绘制模型性能对比图."""
    visualizer = TuningResultVisualizer()
    return visualizer.plot_model_comparison(model_results, metric, task_type, save_path=save_path)


def visualize_optimization_history(optimization_history: List[Dict[str, Any]],
                                  param_name: Optional[str] = None,
                                  save_path: Optional[str] = None) -> Figure:
    """便捷函数：绘制参数优化过程图."""
    visualizer = TuningResultVisualizer()
    return visualizer.plot_optimization_history(optimization_history, param_name, save_path=save_path)


def visualize_prediction_vs_actual(y_true: Union[np.ndarray, pd.Series],
                                  y_pred: Union[np.ndarray, pd.Series],
                                  timestamps: Optional[Union[np.ndarray, pd.Series]] = None,
                                  model_name: str = "Model",
                                  save_path: Optional[str] = None) -> Figure:
    """便捷函数：绘制预测值与实际值对比图."""
    visualizer = TuningResultVisualizer()
    return visualizer.plot_prediction_vs_actual(y_true, y_pred, timestamps, model_name, save_path=save_path)


def visualize_returns_and_drawdown(returns: Union[np.ndarray, pd.Series],
                                  timestamps: Optional[Union[np.ndarray, pd.Series]] = None,
                                  strategy_name: str = "Strategy",
                                  save_path: Optional[str] = None) -> Figure:
    """便捷函数：绘制收益曲线和回撤图."""
    visualizer = TuningResultVisualizer()
    return visualizer.plot_returns_and_drawdown(returns, timestamps, strategy_name, save_path=save_path)


def visualize_feature_importance(feature_names: List[str],
                                importance_scores: Union[np.ndarray, List[float]],
                                model_name: str = "Model",
                                top_n: int = 10,
                                save_path: Optional[str] = None) -> Figure:
    """便捷函数：绘制特征重要性图."""
    visualizer = TuningResultVisualizer()
    return visualizer.plot_feature_importance(feature_names, importance_scores, model_name, top_n, save_path=save_path)


def create_tuning_dashboard(tuning_results: Dict[str, Any],
                           save_path: Optional[str] = None) -> Figure:
    """便捷函数：创建调优结果综合仪表板."""
    visualizer = TuningResultVisualizer()
    return visualizer.create_dashboard(tuning_results, save_path=save_path)