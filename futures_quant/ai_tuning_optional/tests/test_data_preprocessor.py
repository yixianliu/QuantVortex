"""数据预处理模块单元测试。
"""
import unittest
import numpy as np
import pandas as pd
from datetime import datetime, timedelta

# 导入待测试的模块
import sys
import os
sys.path.append(os.path.join(os.path.dirname(__file__)))

from data_preprocessor import FuturesDataPreprocessor, preprocess_futures_data


class TestFuturesDataPreprocessor(unittest.TestCase):
    """期货数据预处理器测试类。"""
    
    def setUp(self):
        """测试前的准备工作。"""
        # 创建测试数据
        dates = pd.date_range(start='2023-01-01', periods=10, freq='D')
        self.test_data = pd.DataFrame({
            'datetime': dates,
            'open': [100, 101, 102, 103, 104, 105, 106, 107, 108, 109],
            'high': [105, 106, 107, 108, 109, 110, 111, 112, 113, 114],
            'low': [95, 96, 97, 98, 99, 100, 101, 102, 103, 104],
            'close': [103, 104, 105, 106, 107, 108, 109, 110, 111, 112],
            'volume': [1000, 1100, 1200, 1300, 1400, 1500, 1600, 1700, 1800, 1900],
            'open_interest': [500, 520, 540, 560, 580, 600, 620, 640, 660, 680]
        })
        
        # 创建包含问题的测试数据
        self.problematic_data = self.test_data.copy()
        # 添加一些问题数据
        self.problematic_data.loc[2, 'high'] = 90  # high < low
        self.problematic_data.loc[5, 'low'] = 120  # low > high
        self.problematic_data.loc[7, 'open'] = 200  # open > high
        self.problematic_data.loc[8, 'close'] = 50  # close < low
        self.problematic_data.loc[3, 'volume'] = -100  # 负成交量
        self.problematic_data.loc[1, 'volume'] = None  # 缺失值
    
    def test_initialization(self):
        """测试初始化。"""
        preprocessor = FuturesDataPreprocessor(
            scaling_method="standard",
            handle_missing="mean",
            feature_range=(-1, 1)
        )
        
        self.assertEqual(preprocessor.scaling_method, "standard")
        self.assertEqual(preprocessor.handle_missing, "mean")
        self.assertEqual(preprocessor.feature_range, (-1, 1))
        self.assertIsNotNone(preprocessor.scaler)
        self.assertIsNotNone(preprocessor.imputer)
    
    def test_clean_data(self):
        """测试数据清洗功能。"""
        preprocessor = FuturesDataPreprocessor()
        cleaned_data = preprocessor.clean_data(self.problematic_data)
        
        # 检查高低关系是否修正
        self.assertTrue((cleaned_data['high'] >= cleaned_data['low']).all())
        
        # 检查open和close是否在合理范围内
        for idx in range(len(cleaned_data)):
            self.assertGreaterEqual(cleaned_data.loc[idx, 'open'], cleaned_data.loc[idx, 'low'])
            self.assertLessEqual(cleaned_data.loc[idx, 'open'], cleaned_data.loc[idx, 'high'])
            self.assertGreaterEqual(cleaned_data.loc[idx, 'close'], cleaned_data.loc[idx, 'low'])
            self.assertLessEqual(cleaned_data.loc[idx, 'close'], cleaned_data.loc[idx, 'high'])
        
        # 检查成交量非负
        self.assertTrue((cleaned_data['volume'] >= 0).all())
        
        # 检查缺失值是否被处理
        self.assertFalse(cleaned_data['volume'].isnull().any())
    
    def test_normalize_features(self):
        """测试特征标准化功能。"""
        preprocessor = FuturesDataPreprocessor(scaling_method="standard")
        normalized_data, params = preprocessor.normalize_features(self.test_data)
        
        # 检查返回的数据形状是否正确
        self.assertEqual(normalized_data.shape, self.test_data.shape)
        
        # 检查标准化后的均值约为0，标准差约为1
        numeric_cols = ['open', 'high', 'low', 'close', 'volume', 'open_interest']
        for col in numeric_cols:
            if col in normalized_data.columns:
                mean_val = normalized_data[col].mean()
                std_val = normalized_data[col].std()
                self.assertAlmostEqual(mean_val, 0.0, places=10)
                self.assertAlmostEqual(std_val, 1.0, places=10)
        
        # 检查返回的参数
        self.assertIn('scaling_method', params)
        self.assertIn('feature_columns', params)
        self.assertEqual(params['scaling_method'], "standard")
    
    def test_normalize_features_minmax(self):
        """测试MinMax标准化功能。"""
        preprocessor = FuturesDataPreprocessor(scaling_method="minmax", feature_range=(0, 1))
        normalized_data, params = preprocessor.normalize_features(self.test_data)
        
        # 检查返回的数据形状是否正确
        self.assertEqual(normalized_data.shape, self.test_data.shape)
        
        # 检查标准化后的值是否在[0, 1]范围内
        numeric_cols = ['open', 'high', 'low', 'close', 'volume', 'open_interest']
        for col in numeric_cols:
            if col in normalized_data.columns:
                min_val = normalized_data[col].min()
                max_val = normalized_data[col].max()
                self.assertGreaterEqual(min_val, 0.0)
                self.assertLessEqual(max_val, 1.0)
    
    def test_create_sequences(self):
        """测试时间序列创建功能。"""
        preprocessor = FuturesDataPreprocessor()
        
        # 创建测试数据
        data = np.array([[1, 2], [2, 3], [3, 4], [4, 5], [5, 6]])  # 5行2列
        sequence_length = 3
        
        X, y = preprocessor.create_sequences(data, sequence_length, target_column_index=0)
        
        # 检查输出形状
        # 应该生成 5-3 = 2 个序列
        self.assertEqual(X.shape, (2, 3, 2))  # 2个序列，每个序列长度3，特征数2
        self.assertEqual(y.shape, (2,))  # 2个目标值
        
        # 检查序列内容
        # 第一个序列: [[1,2], [2,3], [3,4]] -> 目标应该是第四行第一列: 4
        np.testing.assert_array_equal(X[0], np.array([[1, 2], [2, 3], [3, 4]]))
        self.assertEqual(y[0], 4)
        
        # 第二个序列: [[2,3], [3,4], [4,5]] -> 目标应该是第五行第一列: 5
        np.testing.assert_array_equal(X[1], np.array([[2, 3], [3, 4], [4, 5]]))
        self.assertEqual(y[1], 5)
    
    def test_preprocess_futures_data_function(self):
        """测试便捷函数。"""
        processed_data, prep_params, sequence_data = preprocess_futures_data(
            self.test_data,
            scaling_method="standard",
            handle_missing="mean",
            sequence_length=3
        )
        
        # 检查返回的数据
        self.assertIsInstance(processed_data, pd.DataFrame)
        self.assertEqual(processed_data.shape, self.test_data.shape)
        
        # 检查预处理参数
        self.assertIsInstance(prep_params, dict)
        self.assertIn('scaling_method', prep_params)
        self.assertIn('feature_columns', prep_params)
        
        # 检查序列数据
        self.assertIsNotNone(sequence_data)
        if sequence_data is not None:
            X, y = sequence_data
            self.assertIsInstance(X, np.ndarray)
            self.assertIsInstance(y, np.ndarray)
            # 应该生成 10-3 = 7 个序列
            self.assertEqual(X.shape[0], 7)
            self.assertEqual(y.shape[0], 7)
    
    def test_edge_cases(self):
        """测试边界情况。"""
        # 测试空数据框
        empty_df = pd.DataFrame()
        preprocessor = FuturesDataPreprocessor()
        
        with self.assertRaises(Exception):
            preprocessor.clean_data(empty_df)
        
        # 测试只有必需列的最小数据框
        min_df = pd.DataFrame({
            'datetime': pd.date_range(start='2023-01-01', periods=3, freq='D'),
            'open': [100, 101, 102],
            'high': [105, 106, 107],
            'low': [95, 96, 97],
            'close': [103, 104, 105],
            'volume': [1000, 1100, 1200]
        })
        
        # 应该能够正常处理
        cleaned_data = preprocessor.clean_data(min_df)
        self.assertEqual(len(cleaned_data), 3)
        
        normalized_data, params = preprocessor.normalize_features(min_df)
        self.assertEqual(normalized_data.shape, min_df.shape)


if __name__ == '__main__':
    unittest.main()