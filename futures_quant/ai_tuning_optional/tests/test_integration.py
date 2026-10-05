"""集成测试：验证AI模型辅助调优处理模块的各组件能够协同工作。
"""
import unittest
import numpy as np
import pandas as pd
from datetime import datetime, timedelta
import tempfile
import os

# 导入待测试的模块
import sys
import os
sys.path.append(os.path.join(os.path.dirname(__file__)))

from data_preprocessor import FuturesDataPreprocessor, preprocess_futures_data
from parameter_optimizer import ModelParameterOptimizer, optimize_model_parameters
from performance_evaluator import ModelPerformanceEvaluator
from visualizer import TuningResultVisualizer, create_tuning_dashboard
from data_validator import FuturesDataValidator, validate_futures_data


class TestAITuningIntegration(unittest.TestCase):
    """AI模型辅助调优处理模块集成测试类。"""
    
    def setUp(self):
        """测试前的准备工作。"""
        # 创建更真实的测试数据
        np.random.seed(42)
        dates = pd.date_range(start='2023-01-01', periods=100, freq='D')
        
        # 模拟价格数据（带趋势和噪声）
        trend = np.linspace(100, 120, 100)
        noise = np.random.normal(0, 2, 100)
        close_prices = trend + noise
        
        # 生成OHLC数据
        self.test_data = pd.DataFrame({
            'datetime': dates,
            'open': close_prices + np.random.normal(0, 0.5, 100),
            'high': close_prices + np.random.uniform(0.5, 2.0, 100),
            'low': close_prices - np.random.uniform(0.5, 2.0, 100),
            'close': close_prices,
            'volume': np.random.uniform(1000, 5000, 100),
            'open_interest': np.random.uniform(100, 500, 100)
        })
        
        # 确保OHLC逻辑正确
        self.test_data['high'] = np.maximum(
            np.maximum(self.test_data['open'], self.test_data['close']),
            self.test_data['high']
        )
        self.test_data['low'] = np.minimum(
            np.minimum(self.test_data['open'], self.test_data['close']),
            self.test_data['low']
        )
        
        # 创建目标变量（未来5天的收益率）
        self.test_data['future_return_5d'] = self.test_data['close'].pct_change(5).shift(-5)
        # 删除最后5行（没有未来数据）
        self.test_data = self.test_data.dropna().reset_index(drop=True)
        
        # 准备特征和目标
        self.feature_columns = ['open', 'high', 'low', 'close', 'volume']
        self.X = self.test_data[self.feature_columns].values
        self.y = self.test_data['future_return_5d'].values
        
        # 分割训练和测试数据（简单分割，实际应用中应使用时间序列交叉验证）
        split_idx = int(len(self.X) * 0.8)
        self.X_train, self.X_test = self.X[:split_idx], self.X[split_idx:]
        self.y_train, self.y_test = self.y[:split_idx], self.y[split_idx:]
        
        self.train_df = pd.DataFrame(self.X_train, columns=self.feature_columns)
        self.train_df['target'] = self.y_train
        self.test_df = pd.DataFrame(self.X_test, columns=self.feature_columns)
        self.test_df['target'] = self.y_test
    
    def test_data_validation_workflow(self):
        """测试数据验证工作流。"""
        validator = FuturesDataValidator()
        
        # 验证原始数据
        validation_result = validator.validate_dataframe(
            self.test_data,
            symbol="TEST",
            data_source="Integration Test Data"
        )
        
        # 基本检查
        self.assertTrue(validation_result['is_valid'])
        self.assertGreaterEqual(validation_result['data_quality_score'], 0)
        self.assertLessEqual(validation_result['data_quality_score'], 100)
        
        # 检查是否有修正被应用（如果有问题的话）
        # 由于我们的测试数据是正确生成的，理想情况下不应有错误
        # 但无论如何，验证过程应该完成
        self.assertIn('validated_df', validation_result)
        self.assertIsInstance(validation_result['validated_df'], pd.DataFrame)
    
    def test_data_preprocessing_workflow(self):
        """测试数据预处理工作流。"""
        preprocessor = FuturesDataPreprocessor(
            scaling_method="standard",
            handle_missing="mean"
        )
        
        # 清洗数据
        cleaned_data = preprocessor.clean_data(self.test_data)
        self.assertEqual(len(cleaned_data), len(self.test_data))
        
        # 标准化特征
        normalized_data, prep_params = preprocessor.normalize_features(
            cleaned_data,
            feature_columns=self.feature_columns
        )
        
        self.assertEqual(len(normalized_data), len(cleaned_data))
        self.assertIn('scaling_method', prep_params)
        self.assertEqual(prep_params['scaling_method'], "standard")
        
        # 检查标准化效果
        for col in self.feature_columns:
            if col in normalized_data.columns:
                mean_val = normalized_data[col].mean()
                std_val = normalized_data[col].std()
                # 标准化后均值应接近0，标准差应接近1
                self.assertAlmostEqual(mean_val, 0.0, places=10)
                self.assertAlmostEqual(std_val, 1.0, places=10)
        
        # 测试便捷函数
        processed_data, prep_params, sequence_data = preprocess_futures_data(
            self.test_data,
            scaling_method="standard",
            handle_missing="mean",
            sequence_length=10,
            target_column="close"
        )
        
        self.assertIsInstance(processed_data, pd.DataFrame)
        self.assertIsInstance(prep_params, dict)
        self.assertIsNotNone(sequence_data)
        if sequence_data is not None:
            X_seq, y_seq = sequence_data
            self.assertIsInstance(X_seq, np.ndarray)
            self.assertIsInstance(y_seq, np.ndarray)
            # 应该生成 len(data) - sequence_length 个序列
            self.assertEqual(X_seq.shape[0], len(self.test_data) - 10)
            self.assertEqual(y_seq.shape[0], len(self.test_data) - 10)
    
    def test_parameter_optimization_workflow(self):
        """测试参数优化工作流。"""
        from sklearn.linear_model import Ridge
        
        # 定义参数网格
        param_grid = {
            'alpha': [0.1, 1.0, 10.0],
            'solver': ['auto', 'svd']
        }
        
        # 使用网格搜索
        optimizer = ModelParameterOptimizer(
            scoring_metric="neg_mean_squared_error",
            cv_folds=3,
            n_jobs=1
        )
        
        model = Ridge()
        result = optimizer.grid_search(
            estimator=model,
            param_grid=param_grid,
            X=self.X_train,
            y=self.y_train
        )
        
        # 检查结果
        self.assertEqual(result['method'], 'grid_search')
        self.assertIn('best_params', result)
        self.assertIn('best_score', result)
        self.assertIn('best_estimator', result)
        
        # 验证最佳参数是否在网格中
        self.assertIn(result['best_params']['alpha'], [0.1, 1.0, 10.0])
        self.assertIn(result['best_params']['solver'], ['auto', 'svd'])
        
        # 验证最佳估计器可以进行预测
        y_pred = result['best_estimator'].predict(self.X_test)
        self.assertEqual(len(y_pred), len(self.y_test))
        
        # 使用便捷函数
        result2 = optimize_model_parameters(
            model=Ridge(),
            X_train=self.X_train,
            y_train=self.y_train,
            param_grid=param_grid,
            method="grid_search"
        )
        
        self.assertEqual(result2['method'], 'grid_search')
        self.assertIn('best_params', result2)
    
    def test_performance_evaluation_workflow(self):
        """测试性能评估工作流。"""
        evaluator = ModelPerformanceEvaluator(risk_free_rate=0.02)
        
        # 生成一些预测值用于测试
        y_pred_test = self.y_test + np.random.normal(0, 0.01, len(self.y_test))
        
        # 回归评估
        regression_results = evaluator.evaluate_regression(self.y_test, y_pred_test)
        self.assertIn('mse', regression_results)
        self.assertIn('mae', regression_results)
        self.assertIn('r2', regression_results)
        
        # 分类评估（将连续值转换为方向）
        y_true_direction = (self.y_test > 0).astype(int)
        y_pred_direction = (y_pred_test > 0).astype(int)
        
        classification_results = evaluator.evaluate_classification(
            y_true_direction, y_pred_direction
        )
        self.assertIn('accuracy', classification_results)
        self.assertIn('precision_macro', classification_results)
        self.assertIn('recall_macro', classification_results)
        self.assertIn('f1_macro', classification_results)
        
        # 方向预测评估
        directional_results = evaluator.evaluate_directional_accuracy(
            self.y_test, y_pred_test
        )
        self.assertIn('directional_accuracy', directional_results)
        
        # 金融性能评估（使用预测收益率作为策略收益率）
        financial_results = evaluator.evaluate_financial_performance(
            y_pred_test  # 使用预测值作为收益率序列
        )
        self.assertIn('sharpe_ratio', financial_results)
        self.assertIn('max_drawdown', financial_results)
        self.assertIn('annualized_return', financial_results)
        
        # 综合评估
        comprehensive_results = evaluator.evaluate_model_comprehensive(
            y_true=self.y_test,
            y_pred=y_pred_test,
            returns=y_pred_test,
            task_type="regression"
        )
        
        self.assertEqual(comprehensive_results['task_type'], 'regression')
        self.assertIn('mse', comprehensive_results)
        self.assertIn('sharpe_ratio', comprehensive_results)  # 金融指标
    
    def test_visualization_workflow(self):
        """测试可视化工作流。"""
        visualizer = TuningResultVisualizer()
        
        # 创建模拟的调优结果
        tuning_results = {
            'model_comparison': {
                'method': 'grid_search',
                'results': [
                    {'model_name': 'Model_A', 'sharpe_ratio': 1.2},
                    {'model_name': 'Model_B', 'sharpe_ratio': 0.8}
                ]
            },
            'optimization_history': [
                {
                    'best_score': -0.5,
                    'best_params': {'learning_rate': 0.01, 'alpha': 1.0},
                    'all_results': [
                        {'params': {'learning_rate': 0.001, 'alpha': 0.1}, 'score': -0.8},
                        {'params': {'learning_rate': 0.01, 'alpha': 1.0}, 'score': -0.5},
                        {'params': {'learning_rate': 0.1, 'alpha': 10.0}, 'score': -0.6}
                    ]
                }
            ],
            'prediction_results': {
                'y_true': self.y_test[:20],  # 只取前20个用于可视化
                'y_pred': self.y_test[:20] + np.random.normal(0, 0.01, 20)
            },
            'financial_performance': {
                'sharpe_ratio': 1.2,
                'max_drawdown': -0.1,
                'annualized_return': 0.15,
                'volatility': 0.05
            },
            'feature_importance': {
                'feature_names': self.feature_columns,
                'importance_scores': np.array([0.2, 0.3, 0.1, 0.25, 0.15])
            }
        }
        
        # 测试各个可视化函数
        # 模型比较图
        fig1 = visualizer.plot_model_comparison(
            tuning_results['model_comparison']['results'],
            metric="sharpe_ratio",
            task_type="financial"
        )
        self.assertIsInstance(fig1, plt.Figure)
        plt.close(fig1)
        
        # 优化历史图
        fig2 = visualizer.plot_optimization_history(
            tuning_results['optimization_history']
        )
        self.assertIsInstance(fig2, plt.Figure)
        plt.close(fig2)
        
        # 预测值对比图
        fig3 = visualizer.plot_prediction_vs_actual(
            tuning_results['prediction_results']['y_true'],
            tuning_results['prediction_results']['y_pred'],
            model_name="Test_Model"
        )
        self.assertIsInstance(fig3, plt.Figure)
        plt.close(fig3)
        
        # 收益曲线和回撤图
        fig4 = visualizer.plot_returns_and_drawdown(
            tuning_results['prediction_results']['y_pred'],
            strategy_name="Test_Strategy"
        )
        self.assertIsInstance(fig4, plt.Figure)
        plt.close(fig4)
        
        # 特征重要性图
        fig5 = visualizer.plot_feature_importance(
            tuning_results['feature_importance']['feature_names'],
            tuning_results['feature_importance']['importance_scores'],
            model_name="Test_Model",
            top_n=5
        )
        self.assertIsInstance(fig5, plt.Figure)
        plt.close(fig5)
        
        # 综合仪表板
        fig6 = visualizer.create_dashboard(tuning_results)
        self.assertIsInstance(fig6, plt.Figure)
        plt.close(fig6)
        
        # 测试便捷函数
        from visualizer import (
            visualize_model_comparison,
            visualize_optimization_history,
            visualize_prediction_vs_actual,
            visualize_returns_and_drawdown,
            visualize_feature_importance,
            create_tuning_dashboard
        )
        
        fig7 = visualize_model_comparison(
            tuning_results['model_comparison']['results'],
            metric="sharpe_ratio"
        )
        self.assertIsInstance(fig7, plt.Figure)
        plt.close(fig7)
        
        fig8 = create_tuning_dashboard(tuning_results)
        self.assertIsInstance(fig8, plt.Figure)
        plt.close(fig8)
    
    def test_end_to_end_workflow(self):
        """测试端到端工作流：从数据验证到模型调优、评估和可视化。"""
        # 1. 数据验证
        validator = FuturesDataValidator()
        validation_result = validator.validate_dataframe(
            self.test_data,
            symbol="INTEGRATION_TEST",
            data_source="End-to-End Test"
        )
        
        self.assertTrue(validation_result['is_valid'])
        processed_data = validation_result['validated_df']
        
        # 2. 数据预处理
        preprocessor = FuturesDataPreprocessor(
            scaling_method="standard",
            handle_missing="mean"
        )
        
        cleaned_data = preprocessor.clean_data(processed_data)
        normalized_data, prep_params = preprocessor.normalize_features(
            cleaned_data,
            feature_columns=self.feature_columns
        )
        
        # 准备建模数据
        X_model = normalized_data[self.feature_columns].values
        y_model = normalized_data['future_return_5d'].values
        
        # 简单分割
        split_idx = int(len(X_model) * 0.8)
        X_train, X_test = X_model[:split_idx], X_model[split_idx:]
        y_train, y_test = y_model[:split_idx], y_model[split_idx:]
        
        # 3. 参数优化
        from sklearn.ensemble import RandomForestRegressor
        
        param_grid = {
            'n_estimators': [10, 50],
            'max_depth': [3, 5, None]
        }
        
        optimizer = ModelParameterOptimizer(
            scoring_metric="neg_mean_squared_error",
            cv_folds=3
        )
        
        model = RandomForestRegressor(random_state=42)
        opt_result = optimizer.grid_search(
            estimator=model,
            param_grid=param_grid,
            X=X_train,
            y=y_train
        )
        
        best_model = opt_result['best_estimator']
        
        # 4. 性能评估
        evaluator = ModelPerformanceEvaluator()
        y_pred = best_model.predict(X_test)
        
        regression_results = evaluator.evaluate_regression(y_test, y_pred)
        financial_results = evaluator.evaluate_financial_performance(
            y_pred - y_test  # 预测误差作为收益率序列（简化处理）
        )
        
        # 5. 可视化
        visualizer = TuningResultVisualizer()
        
        # 准备可视化数据
        tuning_results = {
            'model_comparison': {
                'results': [
                    {
                        'model_name': 'Optimized_Model',
                        'mse': regression_results['mse'],
                        'sharpe_ratio': financial_results.get('sharpe_ratio', 0),
                        'max_drawdown': financial_results.get('max_drawdown', 0)
                    }
                ]
            },
            'optimization_history': [opt_result],  # 简化处理
            'prediction_results': {
                'y_true': y_test,
                'y_pred': y_pred
            },
            'financial_performance': financial_results,
            'feature_importance': {
                'feature_names': self.feature_columns,
                'importance_scores': getattr(best_model, 'feature_importances_', 
                                           np.ones(len(self.feature_columns)) / len(self.feature_columns))
            }
        }
        
        # 生成仪表板
        fig = visualizer.create_dashboard(tuning_results)
        self.assertIsInstance(fig, plt.Figure)
        plt.close(fig)
        
        # 验证整个流程没有抛出异常
        self.assertTrue(True)  # 如果到这里都没有异常，则测试通过


if __name__ == '__main__':
    unittest.main()