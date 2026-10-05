"""模型参数优化模块单元测试。
"""
import unittest
import numpy as np
import pandas as pd
from sklearn.linear_model import LinearRegression
from sklearn.datasets import make_regression

# 导入待测试的模块
import sys
import os
sys.path.append(os.path.join(os.path.dirname(__file__)))

from parameter_optimizer import ModelParameterOptimizer, optimize_model_parameters


class TestModelParameterOptimizer(unittest.TestCase):
    """模型参数优化器测试类。"""
    
    def setUp(self):
        """测试前的准备工作。"""
        # 创建测试数据
        self.X, self.y = make_regression(n_samples=100, n_features=5, noise=0.1, random_state=42)
        self.X_df = pd.DataFrame(self.X, columns=[f'feature_{i}' for i in range(5)])
        self.y_series = pd.Series(self.y, name='target')
        
        # 定义简单的参数网格
        self.param_grid = {
            'fit_intercept': [True, False],
            'normalize': [True, False]  # 注意：在较新的sklearn版本中此参数可能被废弃
        }
    
    def test_initialization(self):
        """测试初始化。"""
        optimizer = ModelParameterOptimizer(
            scoring_metric="neg_mean_squared_error",
            cv_folds=3,
            n_jobs=1,
            verbose=0
        )
        
        self.assertEqual(optimizer.scoring_metric, "neg_mean_squared_error")
        self.assertEqual(optimizer.cv_folds, 3)
        self.assertEqual(optimizer.n_jobs, 1)
        self.assertEqual(optimizer.verbose, 0)
    
    def test_grid_search(self):
        """测试网格搜索功能。"""
        optimizer = ModelParameterOptimizer(scoring_metric="neg_mean_squared_error", cv_folds=3)
        
        # 使用线性回归模型进行测试
        model = LinearRegression()
        
        result = optimizer.grid_search(
            estimator=model,
            param_grid=self.param_grid,
            X=self.X_df,
            y=self.y_series
        )
        
        # 检查返回结果
        self.assertIn('method', result)
        self.assertEqual(result['method'], 'grid_search')
        self.assertIn('best_params', result)
        self.assertIn('best_score', result)
        self.assertIn('best_estimator', result)
        self.assertIn('cv_results', result)
        self.assertIn('n_iterations', result)
        self.assertIn('optimization_time', result)
        
        # 检查最佳参数是否是我们定义网格中的值
        self.assertIn(result['best_params']['fit_intercept'], [True, False])
        self.assertIn(result['best_params']['normalize'], [True, False])
        
        # 检查最佳估计器是否已经训练
        self.assertIsNotNone(result['best_estimator'])
        # 尝试进行预测以确认模型可用
        predictions = result['best_estimator'].predict(self.X_df[:5])
        self.assertEqual(len(predictions), 5)
    
    def test_random_search(self):
        """测试随机搜索功能。"""
        optimizer = ModelParameterOptimizer(scoring_metric="neg_mean_squared_error", cv_folds=3)
        
        # 使用线性回归模型进行测试
        model = LinearRegression()
        
        # 定义参数分布
        param_distributions = {
            'fit_intercept': [True, False],
            'normalize': [True, False]
        }
        
        result = optimizer.random_search(
            estimator=model,
            param_distributions=param_distributions,
            X=self.X_df,
            y=self.y_series,
            n_iter=4  # 只有4种组合，所以迭代4次
        )
        
        # 检查返回结果
        self.assertIn('method', result)
        self.assertEqual(result['method'], 'random_search')
        self.assertIn('best_params', result)
        self.assertIn('best_score', result)
        self.assertIn('best_estimator', result)
        self.assertIn('cv_results', result)
        self.assertIn('n_iterations', result)
        self.assertEqual(result['n_iterations'], 4)
        self.assertIn('optimization_time', result)
    
    def test_optimize_model_parameters_function(self):
        """测试便捷函数。"""
        # 测试网格搜索
        result_grid = optimize_model_parameters(
            model=LinearRegression(),
            X_train=self.X_df,
            y_train=self.y_series,
            param_grid=self.param_grid,
            method="grid_search"
        )
        
        self.assertIn('method', result_grid)
        self.assertEqual(result_grid['method'], 'grid_search')
        self.assertIn('best_params', result_grid)
        self.assertIn('best_score', result_grid)
        
        # 测试随机搜索
        result_random = optimize_model_parameters(
            model=LinearRegression(),
            X_train=self.X_df,
            y_train=self.y_series,
            param_grid=self.param_grid,
            method="random_search",
            n_iter=4
        )
        
        self.assertIn('method', result_random)
        self.assertEqual(result_random['method'], 'random_search')
        self.assertIn('best_params', result_random)
        self.assertIn('best_score', result_random)
    
    def test_get_optimization_history(self):
        """测试获取优化历史。"""
        optimizer = ModelParameterOptimizer()
        
        # 初始状态下历史应该为空
        history = optimizer.get_optimization_history()
        self.assertEqual(len(history), 0)
        
        # 执行一次优化后
        model = LinearRegression()
        optimizer.grid_search(model, self.param_grid, self.X_df, self.y_series)
        
        history = optimizer.get_optimization_history()
        self.assertEqual(len(history), 1)
        self.assertIn('method', history[0])
        self.assertEqual(history[0]['method'], 'grid_search')
    
    def test_get_best_result(self):
        """测试获取最佳结果。"""
        optimizer = ModelParameterOptimizer()
        
        # 初始状态下应该为空
        best_result = optimizer.get_best_result()
        self.assertEqual(len(best_result), 0)
        
        # 执行一次优化后
        model = LinearRegression()
        optimizer.grid_search(model, self.param_grid, self.X_df, self.y_series)
        
        best_result = optimizer.get_best_result()
        self.assertIn('best_params', best_result)
        self.assertIn('best_score', best_result)
        self.assertIn('best_estimator', best_result)


if __name__ == '__main__':
    unittest.main()