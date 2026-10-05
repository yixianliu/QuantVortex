#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Simple test for design_system.py: ensure build_qss works for both themes
and that design_tokens returns dict.
"""

import sys
from pathlib import Path

# Add project root to sys.path
project_root = Path(r'D:\PythonProject\QuantVortex')
if str(project_root) not in sys.path:
    sys.path.append(str(project_root))

def test_import():
    try:
        from futures_quant.ui.design_system import (
            DESIGN, build_qss, design_tokens, apply_design
        )
        print("✅ Imports successful")
        return True
    except Exception as e:
        print(f"❌ Import failed: {e}")
        return False

def test_build_qss():
    try:
        from futures_quant.ui.design_system import build_qss
        qss_dark = build_qss("dark")
        qss_light = build_qss("light")
        if not qss_dark or not qss_light:
            print("❌ build_qss returned empty string")
            return False
        # Quick sanity: check that tokens are replaced
        if '$' in qss_dark or '$' in qss_light:
            print("❌ Unresolved tokens in QSS")
            print("Dark sample:", qss_doll[:200])
            return False
        print("✅ build_qss succeeded for both themes")
        print(f"   Dark QSS length: {len(qss_dark)}")
        print(f"   Light QSS length: {len(qss_light)}")
        return True
    except Exception as e:
        print(f"❌ build_qss error: {e}")
        return False

def test_design_tokens():
    try:
        from futures_quant.ui.design_system import design_tokens
        dt_dark = design_tokens("dark")
        dt_light = design_tokens("light")
        if not isinstance(dt_dark, dict) or not isinstance(dt_light, dict):
            print("❌ design_tokens did not return dict")
            return False
        # check some known keys
        for key in ("bg", "text", "up", "down"):
            if key not in dt_dark:
                print(f"❌ missing key {key} in dark tokens")
                return False
        print("✅ design_tokens works")
        return True
    except Exception as e:
        print(f"❌ design_tokens error: {e}")
        return False

def main():
    if not test_import():
        return 1
    ok = True
    ok = test_build_qss() and ok
    ok = test_design_tokens() and ok
    if ok:
        print("\n🎉 All design system tests passed.")
        return 0
    else:
        print("\n💥 Some tests failed.")
        return 1

if __name__ == '__main__':
    sys.exit(main())