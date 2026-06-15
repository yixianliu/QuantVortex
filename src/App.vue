<script setup>
import { onLaunch, onShow, onHide } from '@dcloudio/uni-app';
import { useUserStore } from './store/user';

onLaunch(() => {
  const userStore = useUserStore();
  userStore.initUserStatus();
});

onShow(() => {
  const userStore = useUserStore();
  userStore.initUserStatus();
});

onHide(() => {
  console.log('App Hide');
});
</script>

<style lang="scss">
@import './uni.scss';

page {
	background-color: $uni-bg-color;
	font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
	font-size: $uni-font-size-base;
	color: $uni-text-color;
	line-height: 1.5;
	box-sizing: border-box;
}

view,
text {
	box-sizing: border-box;
}

.container {
	min-height: 100vh;
	background: $uni-bg-color;
}

.page-header {
	background: linear-gradient(135deg, $uni-color-primary, darken($uni-color-primary, 10%));
	padding: 80rpx 30rpx 30rpx;
	color: #fff;
}

.card {
	background: #fff;
	border-radius: $uni-border-radius-lg;
	padding: $uni-spacing-lg;
	margin-bottom: $uni-spacing-base;
	box-shadow: $uni-shadow-sm;
}

.btn-primary {
	background: linear-gradient(135deg, $uni-color-primary, darken($uni-color-primary, 10%));
	color: #fff;
	border: none;
	border-radius: 48rpx;
	padding: 24rpx 48rpx;
	font-size: $uni-font-size-lg;
	font-weight: bold;
	display: flex;
	align-items: center;
	justify-content: center;
}

.btn-secondary {
	background: $uni-bg-color-grey;
	color: $uni-text-color;
	border: none;
	border-radius: 48rpx;
	padding: 24rpx 48rpx;
	font-size: $uni-font-size-lg;
	font-weight: bold;
	display: flex;
	align-items: center;
	justify-content: center;
}

.ball {
	width: 72rpx;
	height: 72rpx;
	border-radius: 50%;
	display: flex;
	align-items: center;
	justify-content: center;
	font-size: $uni-font-size-lg;
	font-weight: bold;
	color: #fff;
}

.ball-red {
	background: linear-gradient(145deg, #e53935, #c62828);
}

.ball-blue {
	background: linear-gradient(145deg, #1e88e5, #1565c0);
}

.ball-green {
	background: linear-gradient(145deg, #43a047, #2e7d32);
}

.section-title {
	font-size: $uni-font-size-lg;
	font-weight: bold;
	color: $uni-text-color;
	margin-bottom: $uni-spacing-base;
	display: block;
}

.safe-area-bottom {
	padding-bottom: env(safe-area-inset-bottom);
}
</style>
