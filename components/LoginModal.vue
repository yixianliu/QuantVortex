<template>
  <view v-if="visible" class="modal-overlay" @click.self="handleClose">
    <view class="modal-container">
      <!-- 顶部装饰 -->
      <view class="modal-decoration">
        <view class="deco-circle c1"></view>
        <view class="deco-circle c2"></view>
        <view class="deco-circle c3"></view>
      </view>

      <view class="modal-header">
        <view class="header-icon">
          <view class="icon-ring"></view>
          <text class="icon-text">&#x1F510;</text>
        </view>
        <text class="modal-title">欢迎登录</text>
        <text class="modal-subtitle">登录解锁更多专业分析功能</text>
        <text class="close-btn" @click="handleClose">&#x2715;</text>
      </view>

      <view class="modal-body">
        <!-- 登录权益 -->
        <view class="benefits-section">
          <view class="benefit-item" v-for="(item, index) in benefits" :key="index">
            <view class="benefit-icon-wrapper" :style="{ background: item.bgColor }">
              <text class="benefit-icon">{{ item.icon }}</text>
            </view>
            <view class="benefit-info">
              <text class="benefit-title">{{ item.title }}</text>
              <text class="benefit-desc">{{ item.desc }}</text>
            </view>
          </view>
        </view>

        <!-- 登录按钮区域 -->
        <view class="login-actions">
          <!-- 微信一键登录 -->
          <button
            class="login-btn wechat"
            open-type="getPhoneNumber"
            @getphonenumber="handleWechatPhoneLogin"
            @click="handleWechatLogin"
          >
            <view class="btn-shine"></view>
            <view class="btn-icon-wrapper">
              <text class="btn-icon">&#x1F4AC;</text>
            </view>
            <view class="btn-content">
              <text class="btn-title">微信一键登录</text>
              <text class="btn-desc">安全快捷，无需注册</text>
            </view>
            <view class="btn-arrow">&#x203A;</view>
          </button>

          <!-- 分割线 -->
          <view class="divider">
            <view class="divider-line"></view>
            <text class="divider-text">其他方式</text>
            <view class="divider-line"></view>
          </view>

          <!-- 游客模式 -->
          <button class="login-btn guest" @click="handleGuestLogin">
            <view class="btn-icon-wrapper guest-icon">
              <text class="btn-icon">&#x1F464;</text>
            </view>
            <view class="btn-content">
              <text class="btn-title">游客体验</text>
              <text class="btn-desc">部分功能受限</text>
            </view>
            <view class="btn-arrow">&#x203A;</view>
          </button>
        </view>

        <!-- 协议提示 -->
        <view class="agreement-section">
          <view class="checkbox-wrapper" @click="agreed = !agreed">
            <view class="checkbox" :class="{ checked: agreed }">
              <text v-if="agreed" class="check-mark">&#x2713;</text>
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
const isLoggingIn = ref(false)

const benefits = [
  {
    icon: '\uD83D\uDCCA',
    title: '专业数据分析',
    desc: '解锁详细统计报告',
    bgColor: '#E3F2FD'
  },
  {
    icon: '\uD83D\uDD25',
    title: '热冷号追踪',
    desc: '实时掌握号码走势',
    bgColor: '#FFF3E0'
  },
  {
    icon: '\uD83C\uDFAF',
    title: '智能推荐',
    desc: 'AI算法精选号码',
    bgColor: '#E8F5E9'
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
        // 模拟获取用户信息
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
  // H5/APP 环境模拟登录
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

function handleWechatPhoneLogin(e) {
  if (!checkAgreement()) return

  // #ifdef MP-WEIXIN
  if (e.detail.errMsg === 'getPhoneNumber:ok') {
    uni.showLoading({ title: '登录中...', mask: true })

    wx.login({
      success: (res) => {
        if (res.code) {
          setTimeout(() => {
            userStore.login({
              nickname: '微信用户',
              avatar: '',
              userId: `wx_${Date.now()}`,
              phone: '138****8888'
            })
            uni.hideLoading()
            emit('close')
            emit('login-success')
          }, 1200)
        }
      }
    })
  }
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
    // 抖动效果
    const checkbox = document?.querySelector?.('.checkbox-wrapper')
    if (checkbox) {
      checkbox.classList.add('shake')
      setTimeout(() => checkbox.classList.remove('shake'), 500)
    }
    return false
  }
  return true
}

function openAgreement() {
  uni.showModal({
    title: '用户协议',
    content: '本应用提供的彩票数据分析服务仅供参考，不构成任何投注建议。用户应理性购彩，量力而行。使用本应用即表示您同意遵守相关法律法规。',
    showCancel: false
  })
}

function openPrivacy() {
  uni.showModal({
    title: '隐私政策',
    content: '我们重视您的隐私保护。登录时获取的信息仅用于身份验证和提供个性化服务，不会向第三方分享您的个人信息。',
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
  background: rgba(0, 0, 0, 0.65);
  display: flex;
  align-items: flex-end;
  justify-content: center;
  z-index: 1000;
  animation: fade-in 0.3s ease;
}

@keyframes fade-in {
  from { opacity: 0; }
  to { opacity: 1; }
}

.modal-container {
  width: 100%;
  max-height: 85vh;
  background: #fff;
  border-radius: 40rpx 40rpx 0 0;
  overflow: hidden;
  position: relative;
  animation: slide-up 0.35s cubic-bezier(0.16, 1, 0.3, 1);
}

@keyframes slide-up {
  from {
    transform: translateY(100%);
  }
  to {
    transform: translateY(0);
  }
}

/* 装饰圆圈 */
.modal-decoration {
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  height: 200rpx;
  overflow: hidden;
  pointer-events: none;
}

.deco-circle {
  position: absolute;
  border-radius: 50%;
  opacity: 0.08;
}

.deco-circle.c1 {
  width: 300rpx;
  height: 300rpx;
  background: #43A047;
  top: -150rpx;
  right: -80rpx;
}

.deco-circle.c2 {
  width: 200rpx;
  height: 200rpx;
  background: #1E88E5;
  top: -80rpx;
  left: -60rpx;
}

.deco-circle.c3 {
  width: 150rpx;
  height: 150rpx;
  background: #FF9800;
  top: 40rpx;
  right: 120rpx;
}

/* 头部 */
.modal-header {
  padding: 48rpx 40rpx 32rpx;
  text-align: center;
  position: relative;
}

.header-icon {
  width: 120rpx;
  height: 120rpx;
  margin: 0 auto 24rpx;
  position: relative;
  display: flex;
  align-items: center;
  justify-content: center;
}

.icon-ring {
  position: absolute;
  width: 100%;
  height: 100%;
  border-radius: 50%;
  border: 4rpx solid #E8F5E9;
  animation: pulse-ring 2s ease-out infinite;
}

@keyframes pulse-ring {
  0% {
    transform: scale(1);
    opacity: 1;
  }
  100% {
    transform: scale(1.3);
    opacity: 0;
  }
}

.icon-text {
  font-size: 56rpx;
  z-index: 2;
}

.modal-title {
  font-size: 40rpx;
  font-weight: bold;
  color: #1a1a2e;
  display: block;
  margin-bottom: 12rpx;
}

.modal-subtitle {
  font-size: 26rpx;
  color: #999;
  display: block;
}

.close-btn {
  position: absolute;
  top: 32rpx;
  right: 32rpx;
  width: 56rpx;
  height: 56rpx;
  border-radius: 50%;
  background: #F5F5F5;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 28rpx;
  color: #999;
  line-height: 1;
}

/* 权益列表 */
.modal-body {
  padding: 0 40rpx 48rpx;
}

.benefits-section {
  display: flex;
  flex-direction: column;
  gap: 20rpx;
  margin-bottom: 40rpx;
}

.benefit-item {
  display: flex;
  align-items: center;
  gap: 20rpx;
  padding: 20rpx 24rpx;
  background: #F8FAFC;
  border-radius: 16rpx;
  border: 1rpx solid #E8ECEF;
  animation: slide-in-right 0.4s ease-out forwards;
  opacity: 0;
}

.benefit-item:nth-child(1) { animation-delay: 0.1s; }
.benefit-item:nth-child(2) { animation-delay: 0.2s; }
.benefit-item:nth-child(3) { animation-delay: 0.3s; }

@keyframes slide-in-right {
  from {
    opacity: 0;
    transform: translateX(-20rpx);
  }
  to {
    opacity: 1;
    transform: translateX(0);
  }
}

.benefit-icon-wrapper {
  width: 64rpx;
  height: 64rpx;
  border-radius: 16rpx;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.benefit-icon {
  font-size: 32rpx;
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
  color: #333;
}

.benefit-desc {
  font-size: 24rpx;
  color: #999;
}

/* 登录按钮 */
.login-actions {
  display: flex;
  flex-direction: column;
  gap: 20rpx;
  margin-bottom: 32rpx;
}

.login-btn {
  position: relative;
  display: flex;
  align-items: center;
  gap: 20rpx;
  padding: 28rpx 32rpx;
  border-radius: 20rpx;
  border: none;
  overflow: hidden;
  transition: transform 0.2s ease;
}

.login-btn::after {
  border: none;
}

.login-btn:active {
  transform: scale(0.98);
}

.btn-shine {
  position: absolute;
  top: 0;
  left: -100%;
  width: 100%;
  height: 100%;
  background: linear-gradient(90deg, transparent, rgba(255,255,255,0.2), transparent);
  transition: left 0.5s;
}

.login-btn:active .btn-shine {
  left: 100%;
}

.login-btn.wechat {
  background: linear-gradient(135deg, #07C160, #05a350);
}

.login-btn.guest {
  background: #F5F7FA;
  border: 2rpx solid #E8ECEF;
}

.btn-icon-wrapper {
  width: 64rpx;
  height: 64rpx;
  border-radius: 16rpx;
  background: rgba(255, 255, 255, 0.2);
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.guest-icon {
  background: #E3F2FD;
}

.btn-icon {
  font-size: 32rpx;
}

.btn-content {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 4rpx;
}

.btn-title {
  font-size: 30rpx;
  font-weight: bold;
  color: #fff;
}

.login-btn.guest .btn-title {
  color: #333;
}

.btn-desc {
  font-size: 22rpx;
  color: rgba(255, 255, 255, 0.8);
}

.login-btn.guest .btn-desc {
  color: #999;
}

.btn-arrow {
  font-size: 36rpx;
  color: rgba(255, 255, 255, 0.6);
}

.login-btn.guest .btn-arrow {
  color: #999;
}

/* 分割线 */
.divider {
  display: flex;
  align-items: center;
  gap: 20rpx;
  padding: 8rpx 0;
}

.divider-line {
  flex: 1;
  height: 1rpx;
  background: #E8ECEF;
}

.divider-text {
  font-size: 22rpx;
  color: #999;
}

/* 协议 */
.agreement-section {
  display: flex;
  align-items: flex-start;
  gap: 12rpx;
  padding: 0 8rpx;
}

.checkbox-wrapper {
  padding: 4rpx;
}

.checkbox-wrapper.shake {
  animation: shake 0.5s ease;
}

@keyframes shake {
  0%, 100% { transform: translateX(0); }
  25% { transform: translateX(-6rpx); }
  75% { transform: translateX(6rpx); }
}

.checkbox {
  width: 36rpx;
  height: 36rpx;
  border-radius: 8rpx;
  border: 2rpx solid #ccc;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all 0.2s;
}

.checkbox.checked {
  background: #07C160;
  border-color: #07C160;
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
  gap: 4rpx;
  line-height: 1.6;
}

.text-normal {
  font-size: 22rpx;
  color: #999;
}

.text-link {
  font-size: 22rpx;
  color: #07C160;
  font-weight: 500;
}
</style>
