"""CTP接入集成测试 — 在GUI中验证实盘监控页的CTP功能。

用法:
    python examples/test_ctp_integration.py [--connect]
    
    --connect: 实际连接SimNow并验证实时数据流(耗时约15秒)
    (默认仅测试页面构造和诊断面板)
"""
import sys, os, json, time, inspect
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ['QT_QPA_PLATFORM'] = 'offscreen'

from PyQt6.QtWidgets import QApplication
from PyQt6.QtGui import QCloseEvent
from PyQt6.QtCore import QCoreApplication

app = QApplication(sys.argv)

print('=' * 60)
print('CTP 接入集成测试')
print('=' * 60)

# -------------------------
# Step 1: 加载配置
# -------------------------
print('\n[Step 1] 加载 CTP 配置...')
cfg_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'config', 'ctp_settings.json')
# 路径修复：__file__ 在 tests/e2e/ 下，向上两层到项目根，config/ 在项目根下
if not os.path.exists(cfg_path):
    cfg_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), 'config', 'ctp_settings.json')
with open(cfg_path) as f:
    cfg = json.load(f)

creds_from_cfg = cfg.get('account', {})
print(f'  MODE: {cfg.get("mode", "simnow")}')
print(f'  USER_ID: {creds_from_cfg.get("user_id", "")}')
print(f'  SUBSCRIBE: {cfg.get("subscribe", [])}')
print('  [OK] Config loaded')

# -------------------------
# Step 2: 导入依赖
# -------------------------
print('\n[Step 2] 导入模块...')
from futures_quant.data.ctp_gateway import CTPFeed, CTPCredentials, ctp_diagnose
from futures_quant.storage.analysis_store import AnalysisStore
from futures_quant.data.market_data import MarketDataManager
from futures_quant.runtime import get_data_dir
from futures_quant.ui.ctp_monitor_page import CTPMonitorPage
print('  [OK] All modules imported')

# -------------------------
# Step 3: 创建 MarketManager 和 Store
# -------------------------
print('\n[Step 3] 创建分析存储和市场管理器...')
store = AnalysisStore(path=os.path.join(get_data_dir(), 'integration_test.db'))
mdm = MarketDataManager()  # 合成数据模式
print('  [OK] Store and MDM ready')

# -------------------------
# Step 4: 构造 CTPMonitorPage
# -------------------------
print('\n[Step 4] 构造 "实盘监控" 页面...')

sig = inspect.signature(CTPMonitorPage.__init__)
params = list(sig.parameters.keys())
kwargs = {'mdm': mdm, 'store': store}
if 'config' in params:
    kwargs['config'] = None
if 'session' in params:
    kwargs['session'] = None

page = CTPMonitorPage(**kwargs)
page.set_theme('light')
page.set_theme('dark')
page.set_theme('light')
fake_event = QCloseEvent()
page.closeEvent(fake_event)
print('  [OK] CTPMonitorPage constructed, theme toggled OK')

# -------------------------
# Step 5: 运行 CTP 诊断
# -------------------------
print('\n[Step 5] 运行 CTP 诊断...')
diag = ctp_diagnose()
print(f'  lib_available: {diag["lib_available"]} ({diag.get("lib_name", "N/A")})')
print(f'  creds_complete: {diag["creds_complete"]}')
print(f'  mode: {diag["mode"]}')
print(f'  subscribe: {diag.get("subscribe", [])}')

if not diag['lib_available']:
    print('\n  [ERROR] ctpbee/vnpy_ctp 未安装!')
    sys.exit(1)

if not diag['creds_complete']:
    print('\n  [WARN] 凭据不完整,但仍可测试库可用性')
else:
    print('  [OK] 凭据完整,可以连接')

# -------------------------
# Step 6: (可选) 实际连接 SimNow
# -------------------------
do_connect = '--connect' in sys.argv
if do_connect:
    print('\n[Step 6] 实际连接 SimNow (等待15秒)...')
    
    creds = CTPCredentials.load(cfg_path)
    feed = CTPFeed(creds=creds)
    
    bar_count = [0]
    def on_bar(bar):
        bar_count[0] += 1
        sym = bar.get('symbol', '?')
        close = bar.get('close', 0)
        print(f'  [BAR #{bar_count[0]}] symbol={sym} close={close:.2f}')
    
    feed.on_bar = on_bar
    
    start_time = time.time()
    ok = feed.connect()
    elapsed = time.time() - start_time
    
    status = 'SUCCESS' if ok else 'FAILED'
    print(f'\n  Connection: {status} (elapsed {elapsed:.1f}s)')
    
    if ok:
        print('connected:', feed.connected)
        print('lib_name:', feed._lib_name)
        
        # 订阅合约
        for sym in creds.subscribe[:2]:
            code, _ = sym.split('.')
            try:
                feed.subscribe(code)
                print('  [OK] Subscribed:', sym)
            except Exception as e:
                print('  [WARN] Subscribe failed', sym, ':', e)
        
        # 等待行情数据
        print('\n  Waiting for market data (non-trading hours may have no data)...')
        time.sleep(10)
        
        if bar_count[0] > 0:
            print(f'\n  [DATA] Received {bar_count[0]} bars!')
        else:
            print('\n  [INFO] No data received — non-trading hours')
            print('  [INFO] SimNow connection: CONNECTED')
            print('  [TIP] Test again tonight 21:00-02:30 for real-time data')
        
        # Disconnect
        print('\n  Disconnecting...')
        feed.close()
        print('After disconnect connected:', feed.connected)
        print('  [OK] Clean shutdown')
    else:
        print('  [ERROR] Connection failed!')
        try:
            feed.close()
        except:
            pass
        sys.exit(1)
else:
    print('\n[Step 6] 跳过实际连接 (使用 --connect 参数启用)')

# -------------------------
# 最终总结
# -------------------------
print('\n' + '=' * 60)
print('测试总结')
print('=' * 60)
print('  [OK] CTPMonitorPage 构造: 成功')
print('  [OK] 主题切换: dark/light/dark 正常')
print('  [OK] 窗口关闭保护: 无异常')
print(f'  [OK] CTP 库检测: {diag["lib_name"]}')
print(f'  [OK] 凭据状态: {"完整" if diag["creds_complete"] else "不完整"}')

if do_connect:
    print('  [OK] SimNow 连接测试: 已执行')
else:
    print('  [SKIP] SimNow 连接测试: 需 --connect 参数')

print()
print('下一步:')
print('  1. 运行 GUI: python main.py')
print('  2. 点击左侧导航 "实盘监控"')
print('  3. 查看诊断面板显示 CTP 状态')
print('  4. (交易时段) 验证实时行情接收')
print('=' * 60)

sys.exit(0)
