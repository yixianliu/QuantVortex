<template>
  <view v-if="visible" class="modal-overlay" @click.self="handleClose">
    <view class="modal-container">
      <view class="modal-header">
        <view class="logo-icon">💎</view>
        <text class="modal-title">解锁完整报告</text>
        <text class="close-btn" @click="handleClose">×</text>
      </view>
      
      <view class="modal-body">
        <view class="pay-card">
          <view class="pay-icon">🔓</view>
          <text class="pay-title">升级为VIP会员</text>
          <text class="pay-desc">解锁完整数据分析报告，获取专业推荐</text>
          
          <view class="pay-benefits">
            <view class="benefit-item">
              <view class="benefit-check">✓</view>
              <view class="benefit-content">
                <text class="benefit-title">完整报告内容</text>
                <text class="benefit-desc">查看详细数据分析和推荐号码</text>
              </view>
            </view>
            <view class="benefit-item">
              <view class="benefit-check">✓</view>
              <view class="benefit-content">
                <text class="benefit-title">智能推荐算法</text>
                <text class="benefit-desc">基于大数据分析的精准推荐</text>
              </view>
            </view>
            <view class="benefit-item">
              <view class="benefit-check">✓</view>
              <view class="benefit-content">
                <text class="benefit-title">历史数据查询</text>
                <text class="benefit-desc">查看完整历史记录和趋势分析</text>
              </view>
            </view>
            <view class="benefit-item">
              <view class="benefit-check">✓</view>
              <view class="benefit-content">
                <text class="benefit-title">无广告体验</text>
                <text class="benefit-desc">纯净的数据分析环境</text>
              </view>
            </view>
          </view>
        </view>
        
        <view class="price-section">
          <view class="price-card">
            <view class="price-tag">限时优惠</view>
            <view class="price-main">
              <text class="price-symbol">¥</text>
              <text class="price-value">29</text>
              <text class="price-unit">/月</text>
            </view>
            <text class="price-original">原价 ¥59</text>
          </view>
        </view>
        
        <view class="pay-actions">
          <button class="pay-btn primary" @click="handlePayment">
            <text class="btn-icon">💳</text>
            <text class="btn-text">立即开通</text>
          </button>
          <button class="pay-btn secondary" @click="handleClose">
            <text class="btn-text">稍后再说</text>
          </button>
        </view>
        
        <view class="pay-tips">
          <text class="tips-text">支持微信支付 | 支付宝 | 银行卡</text>
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

const emit = defineEmits(['close', 'pay-success'])

const userStore = useUserStore()

function handleClose() {
  emit('close')
}

function handlePayment() {
  uni.showLoading({ title: '支付中...' })
  
  setTimeout(() => {
    userStore.pay()
    uni.hideLoading()
    emit('close')
    emit('pay-success')
  }, 2000)
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
  background: linear-gradient(135deg, #7B1FA2, #5E1B89);
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

.pay-card {
  text-align: center;
  margin-bottom: 32rpx;
}

.pay-icon {
  font-size: 80rpx;
  margin-bottom: 20rpx;
}

.pay-title {
  font-size: 32rpx;
  font-weight: bold;
  color: #333;
  display: block;
  margin-bottom: 12rpx;
}

.pay-desc {
  font-size: 26rpx;
  color: #999;
  display: block;
}

.pay-benefits {
  margin-top: 32rpx;
  padding-top: 24rpx;
  border-top: 2rpx solid #F0F0F0;
}

.benefit-item {
  display: flex;
  align-items: flex-start;
  gap: 16rpx;
  padding: 16rpx 0;
}

.benefit-check {
  width: 40rpx;
  height: 40rpx;
  border-radius: 50%;
  background: linear-gradient(135deg, #43A047, #2E7D32);
  color: #fff;
  font-size: 24rpx;
  font-weight: bold;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.benefit-content {
  flex: 1;
}

.benefit-title {
  font-size: 28rpx;
  font-weight: bold;
  color: #333;
  display: block;
}

.benefit-desc {
  font-size: 24rpx;
  color: #999;
  margin-top: 4rpx;
  display: block;
}

.price-section {
  margin-bottom: 32rpx;
}

.price-card {
  background: linear-gradient(145deg, #FFF8E1, #FFECB3);
  border-radius: 20rpx;
  padding: 32rpx;
  text-align: center;
  position: relative;
  border: 2rpx solid #FFC107;
}

.price-tag {
  position: absolute;
  top: -16rpx;
  left: 50%;
  transform: translateX(-50%);
  background: linear-gradient(135deg, #FF5722, #E64A19);
  color: #fff;
  font-size: 22rpx;
  font-weight: bold;
  padding: 8rpx 24rpx;
  border-radius: 20rpx;
}

.price-main {
  display: flex;
  align-items: baseline;
  justify-content: center;
}

.price-symbol {
  font-size: 32rpx;
  font-weight: bold;
  color: #E65100;
}

.price-value {
  font-size: 80rpx;
  font-weight: bold;
  color: #E65100;
  line-height: 1;
}

.price-unit {
  font-size: 28rpx;
  color: #E65100;
  margin-left: 8rpx;
}

.price-original {
  font-size: 24rpx;
  color: #999;
  text-decoration: line-through;
  margin-top: 8rpx;
  display: block;
}

.pay-actions {
  display: flex;
  flex-direction: column;
  gap: 16rpx;
}

.pay-btn {
  height: 96rpx;
  border-radius: 48rpx;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 12rpx;
  font-size: 28rpx;
  font-weight: bold;
  border: none;
  padding: 0;
}

.pay-btn.primary {
  background: linear-gradient(135deg, #FF5722, #E64A19);
  color: #fff;
}

.pay-btn.secondary {
  background: #F5F5F5;
  color: #666;
}

.btn-icon {
  font-size: 36rpx;
}

.btn-text {
  letter-spacing: 1rpx;
}

.pay-tips {
  text-align: center;
  margin-top: 24rpx;
}

.tips-text {
  font-size: 22rpx;
  color: #999;
}
</style>