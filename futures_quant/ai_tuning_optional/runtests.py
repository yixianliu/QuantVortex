#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
AI模型辅助调优处理模块测试运行器。
"""
import unittest
import sys
import os

# 添加项目路径到系统路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__)))

def run_tests():
    """运行所有测试。"""
    # 发现并运行所有测试
    loader = unittest.TestLoader()
    # M1-02：真实测试位于 ai/tuning/tests/tests/（原 start_dir 少一层，
    # 导致 discover 无法定位测试模块）。
    base_dir = os.path.dirname(__file__)
    start_dir = os.path.join(base_dir, 'tests', 'tests')
    if not os.path.isdir(start_dir):
        start_dir = os.path.join(base_dir, 'tests')
    suite = loader.discover(start_dir, pattern='test_*.py', top_level_dir=base_dir)
    
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    
    # 返回适当的退出码
    return 0 if result.wasSuccessful() else 1

if __name__ == '__main__':
    sys.exit(run_tests())