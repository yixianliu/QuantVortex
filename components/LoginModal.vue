<template>
  <view v-if="visible" class="modal-overlay" @click.self="handleClose">
    <view class="modal-container">
      <view class="modal-header">
        <view class="logo-icon">🔐</view>
        <text class="modal-title">用户登录</text>
        <text class="close-btn" @click="handleClose">×</text>
      </view>
      
      <view class="modal-body">
        <view class="login-card">
          <view class="login-icon">👤</view>
          <text class="login-title">欢迎使用数据分析平台</text>
          <text class="login-desc">登录后可查看报告列表，解锁更多功能</text>
          
          <view class="login-benefits">
            <view class="benefit-item">
              <text class="benefit-icon">📋</text>
              <text class="benefit-text">查看报告列表</text>
            </view>
            <view class="benefit-item">
              <text class="benefit-icon">📊</text>
              <text class="benefit-text">数据统计分析</text>
            </view>
            <view class="benefit-item">
              <text class="benefit-icon">💾</text>
              <text class="benefit-text">保存分析记录</text>
            </view>
          </view>
        </view>
        
        <view class="login-actions">
          <button class="login-btn wechat" @click="handleWechatLogin">
            <text class="btn-icon">💬</text>
            <text class="btn-text">微信快捷登录</text>
          </button>
          <button class="login-btn phone" @click="handlePhoneLogin">
            <text class="btn-icon">📱</text>
            <text class="btn-text">手机号登录</text>
          </button>
        </view>
        
        <view class="login-tips">
          <text class="tips-text">登录即表示同意</text>
          <text class="tips-link">《用户协议》</text>
          <text class="tips-text">和</text>
          <text class="tips-link">《隐私政策》</text>
        </view>
      </view>
    </view>
  </view>
</template>

<script setup>
import { useUserStore } from '../store/user'

defineProps({
  visible: {
    type: Boolean,
    default: false
  }
})

const emit = defineEmits(['close', 'login-success'])

const userStore = useUserStore()

function handleClose() {
  emit('close')
}

function handleWechatLogin() {
  uni.showLoading({ title: '登录中...' })
  
  setTimeout(() => {
    // #ifdef MP-WEIXIN
    wx.login({
      success: (res) => {
        if (res.code) {
          userStore.login({
            nickname: '微信用户',
            avatar: ''
          })
          uni.hideLoading()
          emit('close')
          emit('login-success')
        }
      },
      fail: () => {
        uni.hideLoading()
        uni.showToast({
          title: '登录失败',
          icon: 'none'
        })
      }
    })
    // #endif
    // #ifndef MP-WEIXIN
    userStore.login({
      nickname: '访客用户',
      avatar: ''
    })
    uni.hideLoading()
    emit('close')
    emit('login-success')
    // #endif
  }, 1500)
}

function handlePhoneLogin() {
  uni.showModal({
    title: '手机号登录',
    content: '请在后续版本中使用手机号登录功能',
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
  background: rgba(0, 0, 0, 0.6);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1000;
  animation: fadeIn 0.3s ease;
}

@keyframes fadeIn {
  from { opacity: 0; }
  to { opacity: 1; }
}

.modal-container {
  width: 85%;
  max-width: 640rpx;
  background: #fff;
  border-radius: 32rpx;
  overflow: hidden;
  animation: slideUp 0.3s ease;
}

@keyframes slideUp {
  from { 
    opacity: 0;
    transform: translateY(40rpx);
  }
  to { 
    opacity: 1;
    transform: translateY(0);
  }
}

.modal-header {
  background: linear-gradient(135deg, #1E88E5, #1565C0);
  padding: 40rpx 30rpx;
  display: flex;
  align-items: center;
  justify-content: center;
  position: relative;
}

.logo-icon {
  font-size: 48rpx;
  margin-right: 16rpx;
}

.modal-title {
  font-size: 36rpx;
  font-weight: bold;
  color: #fff;
  letter-spacing: 2rpx;
}

.close-btn {
  position: absolute;
  right: 30rpx;
  font-size: 48rpx;
  color: rgba(255, 255, 255, 0.8);
  line-height: 1;
}

.modal-body {
  padding: 40rpx 30rpx;
}

.login-card {
  text-align: center;
  margin-bottom: 36rpx;
}

.login-icon {
  font-size: 80rpx;
  margin-bottom: 20rpx;
}

.login-title {
  font-size: 32rpx;
  font-weight: bold;
  color: #333;
  display: block;
  margin-bottom: 12rpx;
}

.login-desc {
  font-size: 26rpx;
  color: #999;
  display: block;
}

.login-benefits {
  display: flex;
  justify-content: space-around;
  margin-top: 32rpx;
  padding-top: 24rpx;
  border-top: 2rpx solid #F0F0F0;
}

.benefit-item {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8rpx;
}

.benefit-icon {
  font-size: 36rpx;
}

.benefit-text {
  font-size: 22rpx;
  color: #666;
}

.login-actions {
  display: flex;
  flex-direction: column;
  gap: 20rpx;
}

.login-btn {
  height: 96rpx;
  border-radius: 48rpx;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 12rpx;
  font-size: 28rpx;
  font-weight: bold;
  color: #fff;
  border: none;
  padding: 0;
}

.login-btn.wechat {
  background: linear-gradient(135deg, #4CAF50, #388E3C);
}

.login-btn.phone {
  background: linear-gradient(135deg, #1E88E5, #1565C0);
}

.btn-icon {
  font-size: 36rpx;
}

.btn-text {
  letter-spacing: 1rpx;
}

.login-tips {
  display: flex;
  align-items: center;
  justify-content: center;
  margin-top: 32rpx;
  gap: 8rpx;
}

.tips-text {
  font-size: 22rpx;
  color: #999;
}

.tips-link {
  font-size: 22rpx;
  color: #1E88E5;
}
</style>