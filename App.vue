<script setup>
import { onLaunch, onShow, onHide } from '@dcloudio/uni-app';
import { useUserStore } from './store/user';
import { checkApiStatus, setApiStatus, getApiStatus } from './api/index.js';

onLaunch(async () => {
  const userStore = useUserStore();
  userStore.initUserStatus();
  
  await checkApiAndNavigate();
});

onShow(async () => {
  const userStore = useUserStore();
  userStore.initUserStatus();
  
  await checkApiAndNavigate();
});

onHide(() => {
  console.log('App Hide');
});

async function checkApiAndNavigate() {
  const isApiAvailable = await checkApiStatus();
  
  if (!isApiAvailable) {
    setApiStatus(false);
    const pages = getCurrentPages();
    const currentPage = pages[pages.length - 1];
    
    if (currentPage && currentPage.route !== 'pages/system-upgrade/system-upgrade') {
      uni.reLaunch({
        url: '/pages/system-upgrade/system-upgrade'
      });
    }
  } else {
    setApiStatus(true);
  }
}
</script>

<style lang="scss">
page {
	background-color: #F8FAFC;
	font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
	font-size: 28rpx;
	color: #1F2937;
	line-height: 1.5;
	box-sizing: border-box;
}

view,
text {
	box-sizing: border-box;
}

.container {
	min-height: 100vh;
	background: #F8FAFC;
}

.page-header {
	background: linear-gradient(135deg, #3B82F6, #1D4ED8);
	padding: 80rpx 30rpx 30rpx;
	color: #fff;
}

.card {
	background: #fff;
	border-radius: 16rpx;
	padding: 30rpx;
	margin-bottom: 20rpx;
	box-shadow: 0 2rpx 8rpx rgba(0, 0, 0, 0.05);
}

.btn-primary {
	background: linear-gradient(135deg, #3B82F6, #1D4ED8);
	color: #fff;
	border: none;
	border-radius: 48rpx;
	padding: 24rpx 48rpx;
	font-size: 32rpx;
	font-weight: bold;
	display: flex;
	align-items: center;
	justify-content: center;
}

.btn-secondary {
	background: #F8F9FA;
	color: #374151;
	border: none;
	border-radius: 48rpx;
	padding: 24rpx 48rpx;
	font-size: 32rpx;
	font-weight: bold;
	display: flex;
	align-items: center;
	justify-content: center;
}

.section-title {
	font-size: 32rpx;
	font-weight: bold;
	color: #1F2937;
	margin-bottom: 20rpx;
	display: block;
}

.safe-area-bottom {
	padding-bottom: env(safe-area-inset-bottom);
}
</style>
