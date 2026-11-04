"""性能评估模块单元测试。
"""
import unittest
import numpy as np
import pandas as pd
from datetime import datetime, timedelta

# 导入待测试的模块
import sys
import os
sys.path.append(os.path.join(os.path.dirname(__file__)))

from performance_evaluator import ModelPerformanceEvaluator


class TestModelPerformanceEvaluator(unittest.TestCase):
    """模型性能评估器测试类。"""
    
    def setUp(self):
        """测试前的准备工作。"""
        # 创建测试数据
        np.random.seed(42)
        self.y_true = np.array([1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0])
        self.y_pred = np.array([1.1, 2.2, 2.8, 4.1, 4.8, 6.2, 6.9, 8.1, 9.2, 9.8])
        
        # 创建分类测试数据
        self.y_true_cls = np.array([0, 1, 0, 1, 0, 1, 0, 1, 0, 1])
        self.y_pred_cls = np.array([0, 1, 1, 1, 0, 0, 0, 1, 1, 0])
        
        # 创建收益率测试数据
        self.returns = np.array([0.01, -0.02, 0.03, -0.01, 0.02, 0.01, -0.03, 0.02, 0.01, -0.01])
        
        # 创建基准收益率
        self.benchmark_returns = np.array([0.005, -0.01, 0.02, -0.005, 0.01, 0.005, -0.02, 0.01, 0.005, -0.005])
    
    def test_initialization(self):
        """测试初始化。"""
        evaluator = ModelPerformanceEvaluator(risk_free_rate=0.02)
        self.assertEqual(evaluator.risk_free_rate, 0.02)
        self.assertEqual(len(evaluator.evaluation_history), 0)
    
    def test_evaluate_regression(self):
        """测试回归模型评估。"""
        evaluator = ModelPerformanceEvaluator()
        results = evaluator.evaluate_regression(self.y_true, self.y_pred)
        
        # 检查返回的指标
        self.assertIn('mse', results)
        self.assertIn('mae', results)
        self.assertIn('rmse', results)
        self.assertIn('r2', results)
        self.assertIn('mape', results)
        self.assertIn('smape', results)
        self.assertIn('explained_variance', results)
        
        # 检查指标值的合理性
        self.assertGreaterEqual(results['mse'], 0)
        self.assertGreaterEqual(results['mae'], 0)
        self.assertGreaterEqual(results['rmse'], 0)
        self.assertLessEqual(results['r2'], 1.0)
        self.assertGreaterEqual(results['r2'], 0.0)  # 在良好预测情况下应该是正的
        self.assertGreaterEqual(results['explained_variance'], 0.0)
        self.assertLessEqual(results['explained_variance'], 1.0)
        
        # 手动计算验证
        expected_mse = np.mean((self.y_true - self.y_pred) ** 2)
        self.assertAlmostEqual(results['mse'], expected_mse, places=6)
        
        expected_mae = np.mean(np.abs(self.y_true - self.y_pred))
        self.assertAlmostEqual(results['mae'], expected_mae, places=6)
        
        expected_rmse = np.sqrt(expected_mse)
        self.assertAlmostEqual(results['rmse'], expected_rmse, places=6)
    
    def test_evaluate_classification(self):
        """测试分类模型评估。"""
        evaluator = ModelPerformanceEvaluator()
        results = evaluator.evaluate_classification(self.y_true_cls, self.y_pred_cls)
        
        # 检查返回的指标
        self.assertIn('accuracy', results)
        self.assertIn('precision_macro', results)
        self.assertIn('precision_micro', results)
        self.assertIn('precision_weighted', results)
        self.assertIn('recall_macro', results)
        self.assertIn('recall_micro', results)
        self.assertIn('recall_weighted', results)
        self.assertIn('f1_macro', results)
        self.assertIn('f1_micro', results)
        self.assertIn('f1_weighted', results)
        self.assertIn('confusion_matrix', results)
        self.assertIn('classification_report', results)
        
        # 检查指标值的合理性
        self.assertGreaterEqual(results['accuracy'], 0.0)
        self.assertLessEqual(results['accuracy'], 1.0)
        
        for metric in ['precision_macro', 'precision_micro', 'precision_weighted',
                      'recall_macro', 'recall_micro', 'recall_weighted',
                      'f1_macro', 'f1_micro', 'f1_weighted']:
            self.assertGreaterEqual(results[metric], 0.0)
            self.assertLessEqual(results[metric], 1.0)
        
        # 手动计算验证准确率
        expected_accuracy = np.mean(self.y_true_cls == self.y_pred_cls)
        self.assertAlmostEqual(results['accuracy'], expected_accuracy, places=6)
    
    def test_evaluate_directional_accuracy(self):
        """测试方向预测准确率评估。"""
        evaluator = ModelPerformanceEvaluator()
        results = evaluator.evaluate_directional_accuracy(self.y_true, self.y_pred)
        
        # 检查返回的指标
        self.assertIn('directional_accuracy', results)
        self.assertIn('up_precision', results)
        self.assertIn('up_recall', results)
        self.assertIn('down_precision', results)
        self.assertIn('down_recall', results)
        self.assertIn('cohens_kappa', results)
        
        # 检查指标值的合理性
        self.assertGreaterEqual(results['directional_accuracy'], 0.0)
        self.assertLessEqual(results['directional_accuracy'], 1.0)
        
        for metric in ['up_precision', 'up_recall', 'down_precision', 'down_recall']:
            self.assertGreaterEqual(results[metric], 0.0)
            self.assertLessEqual(results[metric], 1.0)
        
        self.assertGreaterEqual(results['cohens_kappa'], -1.0)
        self.assertLessEqual(results['cohens_kappa'], 1.0)
    
    def test_evaluate_financial_performance(self):
        """测试金融性能评估。"""
        evaluator = ModelPerformanceEvaluator(risk_free_rate=0.02)
        results = evaluator.evaluate_financial_performance(self.returns, self.benchmark_returns)
        
        # 检查返回的指标
        self.assertIn('total_return', results)
        self.assertIn('annualized_return', results)
        self.assertIn('mean_return', results)
        self.assertIn('volatility', results)
        self.assertIn('sharpe_ratio', results)
        self.assertIn('sortino_ratio', results)
        self.assertIn('max_drawdown', results)
        self.assertIn('calmar_ratio', results)
        
        # 如果有基准收益率，还应该有这些指标
        if self.benchmark_returns is not None:
            self.assertIn('beta', results)
            self.assertIn('alpha', results)
            self.assertIn('information_ratio', results)
        
        # 检查指标值的合理性
        # 总收益应该是合理的（不会极端大）
        self.assertGreater(results['total_return'], -1.0)  # 不能亏损超过100%
        self.assertLess(results['total_return'], 10.0)     # 不能赚超过1000%（在测试数据中不太可能）
        
        # 最大回撤应该是负值或零（表示没有回撤）
        self.assertLessEqual(results['max_drawdown'], 0.0)
        self.assertGreaterEqual(results['max_drawdown'], -1.0)  # 回撤不会超过100%
        
        # 波动率应该是非负的
        self.assertGreaterEqual(results['volatility'], 0.0)
        
        # 夏普率可以是任何实数，但极端值不太可能
        self.assertGreater(results['sharpe_ratio'], -10.0)
        self.assertLess(results['sharpe_ratio'], 10.0)
    
    def test_evaluate_model_comprehensive(self):
        """测试综合模型评估。"""
        evaluator = ModelPerformanceEvaluator()
        
        # 测试回归任务
        results_reg = evaluator.evaluate_model_comprehensive(
            y_true=self.y_true,
            y_pred=self.y_pred,
            returns=self.returns,
            benchmark_returns=self.benchmark_returns,
            task_type="regression"
        )
        
        self.assertEqual(results_reg['task_type'], 'regression')
        self.assertIn('mse', results_reg)
        self.assertIn('sharpe_ratio', results_reg)  # 金融指标应该被包含
        
        # 测试分类任务
        results_cls = evaluator.evaluate_model_comprehensive(
            y_true=self.y_true_cls,
            y_pred=self.y_pred_cls,
            task_type="classification"
        )
        
        self.assertEqual(results_cls['task_type'], 'classification')
        self.assertIn('accuracy', results_cls)
        self.assertNotIn('mse', results_cls)  # 分类任务不应该有MSE
        
        # 测试方向任务
        results_dir = evaluator.evaluate_model_comprehensive(
            y_true=self.y_true,
            y_pred=self.y_pred,
            returns=self.returns,
            benchmark_returns=self.benchmark_returns,
            task_type="directional"
        )
        
        self.assertEqual(results_dir['task_type'], 'directional')
        self.assertIn('directional_accuracy', results_dir)
        self.assertIn('sharpe_ratio', results_dir)  # 金融指标应该被包含
    
    def test_get_evaluation_history(self):
        """测试获取评估历史。"""
        evaluator = ModelPerformanceEvaluator()
        
        # 初始状态下历史应该为空
        history = evaluator.get_evaluation_history()
        self.assertEqual(len(history), 0)
        
        # 执行一次评估后
        evaluator.evaluate_regression(self.y_true, self.y_pred)
        
        history = evaluator.get_evaluation_history()
        self.assertEqual(len(history), 1)
        self.assertIn('task_type', history[0])
        self.assertEqual(history[0]['task_type'], 'regression')
    
    def test_compare_models(self):
        """测试模型比较功能。"""
        evaluator = ModelPerformanceEvaluator()
        
        # 创建三个不同性能的模型结果
        model_results = [
            {
                'model_name': 'Model_A',
                'mse': 0.5,
                'mae': 0.6,
                'financial_metrics': {
                    'sharpe_ratio': 1.2,
                    'max_drawdown': -0.1,
                    'annualized_return': 0.15
                }
            },
            {
                'model_name': 'Model_B',
                'mse': 0.3,  # 更好的MSE
                'mae': 0.4,
                'financial_metrics': {
                    'sharpe_ratio': 0.8,  # 较差的夏普率
                    'max_drawdown': -0.2,
                    'annualized_return': 0.10
                }
            },
            {
                'model_name': 'Model_C',
                'mse': 0.4,
                'mae': 0.5,
                'financial_metrics': {
                    'sharpe_ratio': 1.5,  # 最好的夏普率
                    'max_drawdown': -0.05,
                    'annualized_return': 0.20  # 最好的年化收益
                }
            }
        ]
        
        # 使用夏普率进行比较（越大越好）
        comparison = evaluator.compare_models(
            model_results=model_results,
            primary_metric="sharpe_ratio",
            higher_better=True
        )
        
        # 检查返回结果
        self.assertIn('primary_metric', comparison)
        self.assertEqual(comparison['primary_metric'], 'sharpe_ratio')
        self.assertTrue(comparison['higher_better'])
        self.assertIn('best_model_index', comparison)
        self.assertIn('best_score', comparison)
        self.assertIn('worst_model_index', comparison)
        self.assertIn('worst_score', comparison)
        self.assertIn('ranked_results', comparison)
        self.assertEqual(comparison['total_models'], 3)
        
        # 检查排名结果（应该是C、A、B的顺序，因为夏普率分别是1.5, 1.2, 0.8)
        ranked_results = comparison['ranked_results']
        self.assertEqual(len(ranked_results), 3)
        
        # 第一名应该是Model_C（夏普率1.5）
        self.assertEqual(ranked_results[0]['model_name'], 'Model_C')
        self.assertEqual(ranked_results[0]['rank'], 1)
        self.assertAlmostEqual(ranked_results[0]['score'], 1.5, places=6)
        
        # 第二名应该是Model_A（夏普率1.2）
        self.assertEqual(ranked_results[1]['model_name'], 'Model_A')
        self.assertEqual(ranked_results[1]['rank'], 2)
        self.assertAlmostEqual(ranked_results[1]['score'], 1.2, places=6)
        
        # 第三名应该是Model_B（夏普率0.8）
        self.assertEqual(ranked_results[2]['model_name'], 'Model_B')
        self.assertEqual(ranked_results[2]['rank'], 3)
        self.assertAlmostEqual(ranked_results[2]['score'], 0.8, places=6)
        
        # 测试使用MSE进行比较（越小越好）
        comparison_mse = evaluator.compare_models(
            model_results=model_results,
            primary_metric="mse",
            higher_better=False  # MSE越小越好
        )
        
        # 检查排名结果（应该是B、C、A的顺序，因为MSE分别是0.3, 0.4, 0.5）
        ranked_results_mse = comparison_mse['ranked_results']
        self.assertEqual(len(ranked_results_mse), 3)
        
        # 第一名应该是Model_B（MSE0.3）
        self.assertEqual(ranked_results_mse[0]['model_name'], 'Model_B')
        self.assertEqual(ranked_results_mse[0]['rank'], 1)
        self.assertAlmostEqual(ranked_results_mse[0]['score'], 0.3, places=6)
        
        # 第二名应该是Model_C（MSE0.4）
        self.assertEqual(ranked_results_mse[1]['model_name'], 'Model_C')
        self.assertEqual(ranked_results_mse[1]['rank'], 2)
        self.assertAlmostEqual(ranked_results_mse[1]['score'], 0.4, places=6)
        
        # 第三名应该是Model_A（MSE0.5）
        self.assertEqual(ranked_results_mse[2]['model_name'], 'Model_A')
        self.assertEqual(ranked_results_mse[2]['rank'], 3)
        self.assertAlmostEqual(ranked_results_mse[2]['score'], 0.5, places=6)


if __name__ == '__main__':
    unittest.main()