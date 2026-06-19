<template>
  <view v-if="visible" class="modal-overlay" @click.self="handleClose">
    <view class="modal-container">
      <view class="modal-header">
        <view class="header-icon" :style="{ background: '#EFF6FF' }">
          <text class="icon-text" :style="{ color: '#3B82F6' }">D</text>
        </view>
        <text class="modal-title">欢迎使用</text>
        <text class="modal-subtitle">登录后解锁更多数据功能</text>
        <view class="close-btn" @click="handleClose">
          <text class="close-icon">×</text>
        </view>
      </view>

      <view class="modal-body">
        <view class="benefits-section">
          <view class="benefit-item" v-for="(item, index) in benefits" :key="index">
            <view class="benefit-icon-wrapper" :style="{ background: item.bgColor }">
              <text class="benefit-icon" :style="{ color: item.color }">{{ item.icon }}</text>
            </view>
            <view class="benefit-info">
              <text class="benefit-title">{{ item.title }}</text>
              <text class="benefit-desc">{{ item.desc }}</text>
            </view>
          </view>
        </view>

        <view class="login-actions">
          <button class="login-btn wechat" @click="handleWechatLogin">
            <view class="btn-icon-wrapper">
              <text class="btn-icon-text">W</text>
            </view>
            <view class="btn-content">
              <text class="btn-title">微信登录</text>
              <text class="btn-desc">安全快捷</text>
            </view>
            <text class="btn-arrow">›</text>
          </button>

          <view class="divider">
            <view class="divider-line"></view>
            <text class="divider-text">其他方式</text>
            <view class="divider-line"></view>
          </view>

          <button class="login-btn guest" @click="handleGuestLogin">
            <view class="btn-icon-wrapper guest-icon">
              <text class="btn-icon-text guest-icon-text">G</text>
            </view>
            <view class="btn-content">
              <text class="btn-title guest-title">游客模式</text>
              <text class="btn-desc guest-desc">有限体验</text>
            </view>
            <text class="btn-arrow guest-arrow">›</text>
          </button>
        </view>

        <view class="agreement-section">
          <view class="checkbox-wrapper" @click="agreed = !agreed">
            <view class="checkbox" :class="{ checked: agreed }">
              <text v-if="agreed" class="check-mark">✓</text>
            </view>
          </view>
          <view class="agreement-text">
            <text class="text-normal">我已阅读并同意</text>
            <text class="text-link" @click.stop="openAgreement">《用户协议》</text>
            <text class="text-normal">和</text>
            <text class="text-link" @click.stop="openPrivacy">《隐私政策》</text>
          </view>
        </view>
      </view>
    </view>
  </view>
</template>

<script setup>
import { ref } from 'vue'
import { useUserStore } from '@/store/user'

const props = defineProps({
  visible: {
    type: Boolean,
    default: false
  }
})

const emit = defineEmits(['close', 'login-success'])

const userStore = useUserStore()
const agreed = ref(false)

const benefits = [
  {
    icon: '📊',
    title: '数据分析',
    desc: '解锁详细统计报告',
    bgColor: '#EFF6FF',
    color: '#3B82F6'
  },
  {
    icon: '📈',
    title: '趋势追踪',
    desc: '实时掌握号码走势',
    bgColor: '#FEF3C7',
    color: '#D97706'
  },
  {
    icon: '⭐',
    title: '精选推荐',
    desc: '智能算法号码推荐',
    bgColor: '#F5F3FF',
    color: '#8B5CF6'
  }
]

function handleClose() {
  emit('close')
}

function handleWechatLogin() {
  if (!checkAgreement()) return

  // #ifdef MP-WEIXIN
  uni.showLoading({ title: '登录中...', mask: true })

  wx.login({
    success: (res) => {
      if (res.code) {
        setTimeout(() => {
          userStore.login({
            nickname: '微信用户',
            avatar: '',
            userId: `wx_${Date.now()}`
          })
          uni.hideLoading()
          emit('close')
          emit('login-success')
        }, 1200)
      }
    },
    fail: () => {
      uni.hideLoading()
      uni.showToast({
        title: '登录失败，请重试',
        icon: 'none'
      })
    }
  })
  // #endif

  // #ifndef MP-WEIXIN
  uni.showLoading({ title: '登录中...', mask: true })
  setTimeout(() => {
    userStore.login({
      nickname: '微信用户',
      avatar: '',
      userId: `wx_${Date.now()}`
    })
    uni.hideLoading()
    emit('close')
    emit('login-success')
  }, 1200)
  // #endif
}

function handleGuestLogin() {
  if (!checkAgreement()) return

  uni.showModal({
    title: '游客模式',
    content: '游客模式下部分高级功能将无法使用，建议登录以获得完整体验',
    confirmText: '继续体验',
    cancelText: '去登录',
    success: (res) => {
      if (res.confirm) {
        userStore.login({
          nickname: '游客',
          avatar: '',
          userId: `guest_${Date.now()}`
        })
        emit('close')
        emit('login-success')
      }
    }
  })
}

function checkAgreement() {
  if (!agreed.value) {
    uni.showToast({
      title: '请先同意用户协议',
      icon: 'none'
    })
    return false
  }
  return true
}

function openAgreement() {
  uni.showModal({
    title: '用户协议',
    content: '本应用提供的数据分析服务仅供参考，不构成任何投注建议。用户应理性使用，量力而行。',
    showCancel: false
  })
}

function openPrivacy() {
  uni.showModal({
    title: '隐私政策',
    content: '我们重视您的隐私保护。登录时获取的信息仅用于身份验证和提供个性化服务。',
    showCancel: false
  })
}
</script>

<style lang="scss" scoped>
.modal-overlay {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background: rgba(0, 0, 0, 0.5);
  display: flex;
  align-items: flex-end;
  justify-content: center;
  z-index: 1000;
}

.modal-container {
  width: 100%;
  max-height: 80vh;
  background: #fff;
  border-radius: 32rpx 32rpx 0 0;
  overflow: hidden;
}

.modal-header {
  padding: 48rpx 40rpx 32rpx;
  text-align: center;
  position: relative;
}

.header-icon {
  width: 100rpx;
  height: 100rpx;
  border-radius: 24rpx;
  display: flex;
  align-items: center;
  justify-content: center;
  margin: 0 auto 20rpx;
}

.icon-text {
  font-size: 48rpx;
  font-weight: bold;
}

.modal-title {
  font-size: 36rpx;
  font-weight: bold;
  color: #1F2937;
  display: block;
  margin-bottom: 8rpx;
}

.modal-subtitle {
  font-size: 26rpx;
  color: #6B7280;
  display: block;
}

.close-btn {
  position: absolute;
  top: 32rpx;
  right: 32rpx;
  width: 56rpx;
  height: 56rpx;
  border-radius: 50%;
  background: #F3F4F6;
  display: flex;
  align-items: center;
  justify-content: center;
}

.close-icon {
  font-size: 36rpx;
  color: #6B7280;
  line-height: 1;
}

.modal-body {
  padding: 0 40rpx 48rpx;
}

.benefits-section {
  display: flex;
  flex-direction: column;
  gap: 16rpx;
  margin-bottom: 32rpx;
}

.benefit-item {
  display: flex;
  align-items: center;
  gap: 16rpx;
  padding: 20rpx 24rpx;
  background: #FAFAFA;
  border-radius: 16rpx;
}

.benefit-icon-wrapper {
  width: 56rpx;
  height: 56rpx;
  border-radius: 14rpx;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.benefit-icon {
  font-size: 28rpx;
}

.benefit-info {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 4rpx;
}

.benefit-title {
  font-size: 28rpx;
  font-weight: 600;
  color: #374151;
}

.benefit-desc {
  font-size: 24rpx;
  color: #9CA3AF;
}

.login-actions {
  display: flex;
  flex-direction: column;
  gap: 20rpx;
  margin-bottom: 32rpx;
}

.login-btn {
  display: flex;
  align-items: center;
  gap: 20rpx;
  padding: 24rpx 28rpx;
  border-radius: 16rpx;
  border: none;
  background: #07C160;
  transition: all 0.2s ease;
}

.login-btn::after {
  border: none;
}

.login-btn:active {
  transform: scale(0.98);
  opacity: 0.9;
}

.login-btn.wechat {
  background: linear-gradient(135deg, #07C160, #05A54B);
}

.login-btn.guest {
  background: #F9FAFB;
  border: 2rpx solid #E5E7EB;
}

.btn-icon-wrapper {
  width: 56rpx;
  height: 56rpx;
  border-radius: 14rpx;
  background: rgba(255, 255, 255, 0.2);
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.guest-icon {
  background: #E5E7EB;
}

.btn-icon-text {
  font-size: 28rpx;
  font-weight: bold;
  color: #fff;
}

.guest-icon-text {
  color: #6B7280;
}

.btn-content {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 4rpx;
}

.btn-title {
  font-size: 28rpx;
  font-weight: bold;
  color: #fff;
}

.guest-title {
  color: #374151;
}

.btn-desc {
  font-size: 22rpx;
  color: rgba(255, 255, 255, 0.8);
}

.guest-desc {
  color: #9CA3AF;
}

.btn-arrow {
  font-size: 32rpx;
  color: rgba(255, 255, 255, 0.6);
}

.guest-arrow {
  color: #9CA3AF;
}

.divider {
  display: flex;
  align-items: center;
  gap: 16rpx;
}

.divider-line {
  flex: 1;
  height: 2rpx;
  background: #E5E7EB;
}

.divider-text {
  font-size: 22rpx;
  color: #9CA3AF;
}

.agreement-section {
  display: flex;
  align-items: flex-start;
  gap: 16rpx;
}

.checkbox-wrapper {
  padding: 8rpx;
}

.checkbox {
  width: 36rpx;
  height: 36rpx;
  border-radius: 8rpx;
  border: 2rpx solid #D1D5DB;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all 0.2s ease;
}

.checkbox.checked {
  background: #3B82F6;
  border-color: #3B82F6;
}

.check-mark {
  font-size: 22rpx;
  color: #fff;
  font-weight: bold;
}

.agreement-text {
  flex: 1;
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 4rpx;
}

.text-normal {
  font-size: 22rpx;
  color: #6B7280;
}

.text-link {
  font-size: 22rpx;
  color: #3B82F6;
}
</style>
