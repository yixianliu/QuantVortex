"""结果可视化模块单元测试。
"""
import unittest
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')  # 使用非交互式后端
import matplotlib.pyplot as plt
import tempfile
import os

# 导入待测试的模块
import sys
import sys
sys.path.append(os.path.join(os.path.dirname(__file__)))

from visualizer import (
    TuningResultVisualizer,
    visualize_model_comparison,
    visualize_optimization_history,
    visualize_prediction_vs_actual,
    visualize_returns_and_drawdown,
    visualize_feature_importance,
    create_tuning_dashboard
)


class TestTuningResultVisualizer(unittest.TestCase):
    """调优结果可视化器测试类。"""
    
    def setUp(self):
        """测试前的准备工作。"""
        self.visualizer = TuningResultVisualizer()
        
        # 创建测试数据
        self.model_results = [
            {
                'model_name': 'Model_A',
                'sharpe_ratio': 1.2,
                'max_drawdown': -0.1,
                'annualized_return': 0.15
            },
            {
                'model_name': 'Model_B',
                'sharpe_ratio': 0.8,
                'max_drawdown': -0.2,
                'annualized_return': 0.10
            },
            {
                'model_name': 'Model_C',
                'sharpe_ratio': 1.5,
                'max_drawdown': -0.05,
                'annualized_return': 0.20
            }
        ]
        
        self.optimization_history = [
            {
                'method': 'grid_search',
                'best_score': -0.5,
                'best_params': {'learning_rate': 0.01, 'hidden_size': 64},
                'all_results': [
                    {'params': {'learning_rate': 0.001, 'hidden_size': 32}, 'score': -0.8},
                    {'params': {'learning_rate': 0.01, 'hidden_size': 64}, 'score': -0.5},
                    {'params': {'learning_rate': 0.1, 'hidden_size': 128}, 'score': -0.6}
                ]
            },
            {
                'method': 'grid_search',
                'best_score': -0.3,
                'best_params': {'learning_rate': 0.005, 'hidden_size': 100},
                'all_results': [
                    {'params': {'learning_rate': 0.001, 'hidden_size': 50}, 'score': -0.7},
                    {'params': {'learning_rate': 0.005, 'hidden_size': 100}, 'score': -0.3},
                    {'params': {'learning_rate': 0.01, 'hidden_size': 200}, 'score': -0.4}
                ]
            }
        ]
        
        self.y_true = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
        self.y_pred = np.array([1.1, 2.2, 2.8, 4.1, 4.8])
        
        self.returns = np.array([0.01, -0.02, 0.03, -0.01, 0.02])
        
        self.feature_names = ['feature_A', 'feature_B', 'feature_C', 'feature_D']
        self.importance_scores = np.array([0.1, 0.5, 0.3, 0.1])
    
    def test_initialization(self):
        """测试初始化。"""
        self.assertIsInstance(self.visualizer, TuningResultVisualizer)
        self.assertEqual(self.visualizer.style, "whitegrid")
    
    def test_plot_model_comparison(self):
        """测试模型比较图绘制。"""
        # 测试基本功能
        fig = self.visualizer.plot_model_comparison(
            self.model_results,
            metric="sharpe_ratio",
            task_type="financial"
        )
        
        self.assertIsInstance(fig, plt.Figure)
        plt.close(fig)  # 防止内存泄漏
        
        # 测试保存功能
        with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as tmp:
            try:
                fig = self.visualizer.plot_model_comparison(
                    self.model_results,
                    metric="sharpe_ratio",
                    task_type="financial",
                    save_path=tmp.name
                )
                self.assertTrue(os.path.exists(tmp.name))
                plt.close(fig)
            finally:
                if os.path.exists(tmp.name):
                    os.unlink(tmp.name)
    
    def test_plot_optimization_history(self):
        """测试参数优化历史图绘制。"""
        # 测试基本功能
        fig = self.visualizer.plot_optimization_history(self.optimization_history)
        
        self.assertIsInstance(fig, plt.Figure)
        plt.close(fig)
        
        # 测试特定参数追踪
        fig = self.visualizer.plot_optimization_history(
            self.optimization_history,
            param_name="learning_rate"
        )
        
        self.assertIsInstance(fig, plt.Figure)
        plt.close(fig)
    
    def test_plot_prediction_vs_actual(self):
        """测试预测值与实际值对比图绘制。"""
        # 测试基本功能
        fig = self.visualizer.plot_prediction_vs_actual(
            self.y_true,
            self.y_pred,
            model_name="Test_Model"
        )
        
        self.assertIsInstance(fig, plt.Figure)
        plt.close(fig)
        
        # 测试带时间戳的功能
        timestamps = pd.date_range(start='2023-01-01', periods=len(self.y_true), freq='D')
        fig = self.visualizer.plot_prediction_vs_actual(
            self.y_true,
            self.y_pred,
            timestamps=timestamps,
            model_name="Test_Model"
        )
        
        self.assertIsInstance(fig, plt.Figure)
        plt.close(fig)
    
    def test_plot_returns_and_drawdown(self):
        """测试收益曲线和回撤图绘制。"""
        # 测试基本功能
        fig = self.visualizer.plot_returns_and_drawdown(
            self.returns,
            strategy_name="Test_Strategy"
        )
        
        self.assertIsInstance(fig, plt.Figure)
        plt.close(fig)
        
        # 测试带时间戳的功能
        timestamps = pd.date_range(start='2023-01-01', periods=len(self.returns), freq='D')
        fig = self.visualizer.plot_returns_and_drawdown(
            self.returns,
            timestamps=timestamps,
            strategy_name="Test_Strategy"
        )
        
        self.assertIsInstance(fig, plt.Figure)
        plt.close(fig)
    
    def test_plot_feature_importance(self):
        """测试特征重要性图绘制。"""
        # 测试基本功能
        fig = self.visualizer.plot_feature_importance(
            self.feature_names,
            self.importance_scores,
            model_name="Test_Model"
        )
        
        self.assertIsInstance(fig, plt.Figure)
        plt.close(fig)
        
        # 测试Top N功能
        fig = self.visualizer.plot_feature_importance(
            self.feature_names,
            self.importance_scores,
            model_name="Test_Model",
            top_n=2
        )
        
        self.assertIsInstance(fig, plt.Figure)
        plt.close(fig)
    
    def test_create_dashboard(self):
        """测试创建综合仪表板。"""
        tuning_results = {
            'model_comparison': {'method': 'grid_search'},
            'optimization_history': self.optimization_history,
            'prediction_results': {
                'y_true': self.y_true,
                'y_pred': self.y_pred
            },
            'financial_performance': {
                'sharpe_ratio': 1.2,
                'max_drawdown': -0.1,
                'annualized_return': 0.15
            },
            'feature_importance': {
                'feature_names': self.feature_names,
                'importance_scores': self.importance_scores
            }
        }
        
        # 测试基本功能
        fig = self.visualizer.create_dashboard(tuning_results)
        
        self.assertIsInstance(fig, plt.Figure)
        plt.close(fig)
        
        # 测试保存功能
        with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as tmp:
            try:
                fig = self.visualizer.create_dashboard(tuning_results, save_path=tmp.name)
                self.assertTrue(os.path.exists(tmp.name))
                plt.close(fig)
            finally:
                if os.path.exists(tmp.name):
                    os.unlink(tmp.name)


class TestVisualizerFunctions(unittest.TestCase):
    """可视化便捷函数测试类。"""
    
    def setUp(self):
        """测试前的准备工作。"""
        self.model_results = [
            {
                'model_name': 'Model_A',
                'sharpe_ratio': 1.2
            },
            {
                'model_name': 'Model_B',
                'sharpe_ratio': 0.8
            }
        ]
        
        self.optimization_history = [
            {
                'best_score': -0.5,
                'best_params': {'learning_rate': 0.01}
            }
        ]
        
        self.y_true = np.array([1.0, 2.0, 3.0])
        self.y_pred = np.array([1.1, 2.2, 2.8])
        
        self.returns = np.array([0.01, -0.02, 0.03])
        
        self.feature_names = ['feature_A', 'feature_B']
        self.importance_scores = np.array([0.3, 0.7])
        
        self.tuning_results = {
            'model_comparison': {},
            'optimization_history': self.optimization_history,
            'prediction_results': {},
            'financial_performance': {},
            'feature_importance': {}
        }
    
    def test_visualize_model_comparison(self):
        """测试可视化模型比较便捷函数。"""
        fig = visualize_model_comparison(
            self.model_results,
            metric="sharpe_ratio"
        )
        
        self.assertIsInstance(fig, plt.Figure)
        plt.close(fig)
    
    def test_visualize_optimization_history(self):
        """测试可视化优化历史便捷函数。"""
        fig = visualize_optimization_history(
            self.optimization_history
        )
        
        self.assertIsInstance(fig, plt.Figure)
        plt.close(fig)
    
    def test_visualize_prediction_vs_actual(self):
        """测试可视化预测值与实际值便捷函数。"""
        fig = visualize_prediction_vs_actual(
            self.y_true,
            self.y_pred
        )
        
        self.assertIsInstance(fig, plt.Figure)
        plt.close(fig)
    
    def test_visualize_returns_and_drawdown(self):
        """测试可视化收益曲线和回撤便捷函数。"""
        fig = visualize_returns_and_drawdown(
            self.returns
        )
        
        self.assertIsInstance(fig, plt.Figure)
        plt.close(fig)
    
    def test_visualize_feature_importance(self):
        """测试可视化特征重要性便捷函数。"""
        fig = visualize_feature_importance(
            self.feature_names,
            self.importance_scores
        )
        
        self.assertIsInstance(fig, plt.Figure)
        plt.close(fig)
    
    def test_create_tuning_dashboard(self):
        """测试创建调优仪表板便捷函数。"""
        fig = create_tuning_dashboard(
            self.tuning_results
        )
        
        self.assertIsInstance(fig, plt.Figure)
        plt.close(fig)


if __name__ == '__main__':
    unittest.main()