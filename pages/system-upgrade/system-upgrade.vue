<template>
  <view class="upgrade-container">
    <view class="upgrade-content">
      <view class="status-icon">
        <text class="icon-text">S</text>
      </view>
      <text class="title">系统维护中</text>
      <text class="subtitle">我们正在进行系统升级，以提供更好的服务</text>
      
      <view class="progress-section">
        <view class="progress-bar">
          <view class="progress-fill" :style="{ width: progressWidth }"></view>
        </view>
        <text class="progress-text">{{ progressText }}</text>
      </view>

      <view class="info-section">
        <view class="info-item">
          <view class="info-icon-wrapper">
            <text class="info-icon-text">⚙</text>
          </view>
          <view class="info-content">
            <text class="info-title">系统优化</text>
            <text class="info-desc">提升数据处理效率</text>
          </view>
        </view>
        <view class="info-item">
          <view class="info-icon-wrapper">
            <text class="info-icon-text">🔒</text>
          </view>
          <view class="info-content">
            <text class="info-title">安全升级</text>
            <text class="info-desc">增强数据安全防护</text>
          </view>
        </view>
        <view class="info-item">
          <view class="info-icon-wrapper">
            <text class="info-icon-text">Σ</text>
          </view>
          <view class="info-content">
            <text class="info-title">数据分析</text>
            <text class="info-desc">优化概率分析算法</text>
          </view>
        </view>
      </view>

      <view class="countdown-section">
        <text class="countdown-label">预计恢复时间</text>
        <view class="countdown">
          <view class="countdown-item">
            <text class="countdown-num">{{ countdown.hours }}</text>
            <text class="countdown-unit">时</text>
          </view>
          <text class="countdown-sep">:</text>
          <view class="countdown-item">
            <text class="countdown-num">{{ countdown.minutes }}</text>
            <text class="countdown-unit">分</text>
          </view>
          <text class="countdown-sep">:</text>
          <view class="countdown-item">
            <text class="countdown-num">{{ countdown.seconds }}</text>
            <text class="countdown-unit">秒</text>
          </view>
        </view>
      </view>

      <button class="retry-btn" @click="handleRetry">
        <text class="retry-text">点击重试</text>
      </button>

      <text class="tip-text">如有疑问，请联系客服</text>
    </view>
  </view>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { checkApiStatus, setApiStatus } from '@/api/index.js'

const progress = ref(0)
const countdown = ref({
  hours: '02',
  minutes: '30',
  seconds: '00'
})

let progressTimer = null
let countdownTimer = null

const progressWidth = computed(() => `${progress.value}%`)
const progressText = computed(() => `升级进度 ${progress.value}%`)

function formatNumber(num) {
  return num.toString().padStart(2, '0')
}

function startProgress() {
  progressTimer = setInterval(() => {
    if (progress.value < 90) {
      progress.value += Math.random() * 5
      if (progress.value > 90) progress.value = 90
    }
  }, 1000)
}

function startCountdown() {
  let totalSeconds = 2 * 3600 + 30 * 60
  
  countdownTimer = setInterval(() => {
    totalSeconds--
    if (totalSeconds <= 0) {
      totalSeconds = 0
    }
    
    const hours = Math.floor(totalSeconds / 3600)
    const minutes = Math.floor((totalSeconds % 3600) / 60)
    const seconds = totalSeconds % 60
    
    countdown.value = {
      hours: formatNumber(hours),
      minutes: formatNumber(minutes),
      seconds: formatNumber(seconds)
    }
  }, 1000)
}

async function handleRetry() {
  uni.showLoading({ title: '检测中...', mask: true })
  
  const isAvailable = await checkApiStatus()
  
  uni.hideLoading()
  
  if (isAvailable) {
    setApiStatus(true)
    uni.showToast({
      title: '系统已恢复',
      icon: 'success'
    })
    setTimeout(() => {
      uni.reLaunch({ url: '/pages/index/index' })
    }, 1500)
  } else {
    uni.showToast({
      title: '系统仍在维护中',
      icon: 'none'
    })
  }
}

onMounted(() => {
  startProgress()
  startCountdown()
})

onUnmounted(() => {
  if (progressTimer) clearInterval(progressTimer)
  if (countdownTimer) clearInterval(countdownTimer)
})
</script>

<style lang="scss" scoped>
.upgrade-container {
  min-height: 100vh;
  background: linear-gradient(135deg, #1F2937 0%, #111827 100%);
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 40rpx;
}

.upgrade-content {
  width: 100%;
  max-width: 600rpx;
  text-align: center;
}

.status-icon {
  width: 160rpx;
  height: 160rpx;
  border-radius: 40rpx;
  background: linear-gradient(135deg, #3B82F6, #1D4ED8);
  display: flex;
  align-items: center;
  justify-content: center;
  margin: 0 auto 40rpx;
  animation: pulse 2s ease-in-out infinite;
}

@keyframes pulse {
  0%, 100% {
    transform: scale(1);
    opacity: 1;
  }
  50% {
    transform: scale(1.05);
    opacity: 0.9;
  }
}

.icon-text {
  font-size: 72rpx;
  font-weight: bold;
  color: #fff;
}

.title {
  font-size: 48rpx;
  font-weight: bold;
  color: #fff;
  display: block;
  margin-bottom: 16rpx;
}

.subtitle {
  font-size: 28rpx;
  color: #9CA3AF;
  display: block;
  margin-bottom: 48rpx;
}

.progress-section {
  margin-bottom: 48rpx;
}

.progress-bar {
  width: 100%;
  height: 12rpx;
  background: rgba(255, 255, 255, 0.1);
  border-radius: 6rpx;
  overflow: hidden;
}

.progress-fill {
  height: 100%;
  background: linear-gradient(90deg, #3B82F6, #8B5CF6);
  border-radius: 6rpx;
  transition: width 0.3s ease;
}

.progress-text {
  font-size: 26rpx;
  color: #9CA3AF;
  display: block;
  margin-top: 12rpx;
}

.info-section {
  background: rgba(255, 255, 255, 0.05);
  border-radius: 20rpx;
  padding: 24rpx;
  margin-bottom: 48rpx;
}

.info-item {
  display: flex;
  align-items: center;
  gap: 20rpx;
  padding: 16rpx 0;
  
  &:not(:last-child) {
    border-bottom: 1rpx solid rgba(255, 255, 255, 0.05);
  }
}

.info-icon-wrapper {
  width: 64rpx;
  height: 64rpx;
  border-radius: 16rpx;
  background: rgba(59, 130, 246, 0.2);
  display: flex;
  align-items: center;
  justify-content: center;
}

.info-icon-text {
  font-size: 32rpx;
  color: #3B82F6;
}

.info-content {
  flex: 1;
  text-align: left;
}

.info-title {
  font-size: 28rpx;
  color: #fff;
  display: block;
}

.info-desc {
  font-size: 24rpx;
  color: #9CA3AF;
  display: block;
  margin-top: 4rpx;
}

.countdown-section {
  margin-bottom: 48rpx;
}

.countdown-label {
  font-size: 26rpx;
  color: #9CA3AF;
  display: block;
  margin-bottom: 20rpx;
}

.countdown {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 16rpx;
}

.countdown-item {
  display: flex;
  flex-direction: column;
  align-items: center;
  width: 100rpx;
  height: 120rpx;
  background: rgba(255, 255, 255, 0.08);
  border-radius: 16rpx;
  justify-content: center;
}

.countdown-num {
  font-size: 44rpx;
  font-weight: bold;
  color: #3B82F6;
  font-family: 'Courier New', monospace;
}

.countdown-unit {
  font-size: 22rpx;
  color: #9CA3AF;
  margin-top: 4rpx;
}

.countdown-sep {
  font-size: 36rpx;
  color: #3B82F6;
  font-weight: bold;
}

.retry-btn {
  width: 100%;
  height: 96rpx;
  background: linear-gradient(135deg, #3B82F6, #1D4ED8);
  border-radius: 48rpx;
  border: none;
  margin-bottom: 32rpx;
}

.retry-btn::after {
  border: none;
}

.retry-btn:active {
  opacity: 0.9;
  transform: scale(0.98);
}

.retry-text {
  font-size: 32rpx;
  font-weight: bold;
  color: #fff;
}

.tip-text {
  font-size: 24rpx;
  color: #6B7280;
}
</style>
