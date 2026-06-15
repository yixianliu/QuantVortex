<template>
  <view class="container">
    <view class="header">
      <view class="header-content">
        <text class="header-title">⭐ QI XING CAI</text>
        <text class="header-subtitle">七星彩数字概率分析系统</text>
      </view>
      <view class="user-status-bar">
        <view v-if="userStore.isLoggedIn" class="user-info" @click="showUserMenu = true">
          <text class="user-name">{{ userStore.userInfo.nickname }}</text>
          <view class="vip-badge" v-if="userStore.isPaid">VIP</view>
        </view>
        <view v-else class="login-hint" @click="showLoginModal = true">
          <text class="login-text">🔐 请登录</text>
        </view>
      </view>
    </view>

    <view class="current-data-section">
      <view class="section-header">
        <text class="section-title">最新开奖结果</text>
        <text class="refresh-btn" @click="refreshData">🔄 刷新</text>
      </view>

      <view class="latest-result">
        <view class="result-header">
          <text class="result-session">期号: {{ latestData.issue }}</text>
          <text class="result-date">{{ latestData.draw_date }}</text>
        </view>
        <view class="result-numbers">
          <view class="main-numbers">
            <view v-for="(num, index) in mainNumbers" :key="'main-' + index" class="num-box primary">
              {{ num }}
            </view>
          </view>
          <view class="secondary-numbers">
            <view class="num-box secondary">{{ latestData.special_num }}</view>
          </view>
        </view>
        <view class="result-stats">
          <view class="stat-item">
            <text class="stat-label">和值</text>
            <text class="stat-value" :class="latestData.hezhi_type === '奇' ? 'odd' : 'even'">{{ latestData.hezhi }}</text>
          </view>
          <view class="stat-item">
            <text class="stat-label">奇偶比</text>
            <text class="stat-value">{{ latestData.odd_even_ratio }}</text>
          </view>
          <view class="stat-item">
            <text class="stat-label">跨度</text>
            <text class="stat-value">{{ latestData.span }}</text>
          </view>
        </view>
      </view>
    </view>

    <view class="stats-section">
      <view class="section-header">
        <text class="section-title">数据统计</text>
      </view>

      <view class="stats-grid">
        <view class="stat-card hot">
          <text class="stat-icon">🔥</text>
          <text class="stat-label">热号 TOP5</text>
          <view class="stat-values">
            <view v-for="(item, index) in hotNumbers" :key="'hot-' + index" class="stat-num">{{ item.num }}</view>
          </view>
          <view class="stat-legend">
            <text class="legend-text">出现频率最高</text>
          </view>
        </view>
        <view class="stat-card cold">
          <text class="stat-icon">❄️</text>
          <text class="stat-label">冷号 TOP5</text>
          <view class="stat-values">
            <view v-for="(item, index) in coldNumbers" :key="'cold-' + index" class="stat-num">{{ item.num }}</view>
          </view>
          <view class="stat-legend">
            <text class="legend-text">出现频率最低</text>
          </view>
        </view>
      </view>

      <view class="distribution-card">
        <text class="card-title">📈 号码分布</text>
        <view class="distribution-grid">
          <view class="dist-item">
            <view class="dist-bar-container">
              <view class="dist-bar-wrapper">
                <view class="dist-bar odd" :style="{ width: distribution.oddRate + '%' }"></view>
              </view>
              <text class="dist-value">{{ distribution.oddRate }}%</text>
            </view>
            <text class="dist-label">奇数</text>
          </view>
          <view class="dist-item">
            <view class="dist-bar-container">
              <view class="dist-bar-wrapper">
                <view class="dist-bar even" :style="{ width: distribution.evenRate + '%' }"></view>
              </view>
              <text class="dist-value">{{ distribution.evenRate }}%</text>
            </view>
            <text class="dist-label">偶数</text>
          </view>
          <view class="dist-item">
            <view class="dist-bar-container">
              <view class="dist-bar-wrapper">
                <view class="dist-bar small" :style="{ width: distribution.smallRate + '%' }"></view>
              </view>
              <text class="dist-value">{{ distribution.smallRate }}%</text>
            </view>
            <text class="dist-label">小号</text>
          </view>
          <view class="dist-item">
            <view class="dist-bar-container">
              <view class="dist-bar-wrapper">
                <view class="dist-bar large" :style="{ width: distribution.largeRate + '%' }"></view>
              </view>
              <text class="dist-value">{{ distribution.largeRate }}%</text>
            </view>
            <text class="dist-label">大号</text>
          </view>
        </view>
      </view>
    </view>

    <view class="rules-section">
      <view class="section-header">
        <text class="section-title">📋 中奖规则</text>
      </view>
      <view class="rules-table">
        <view class="rules-header-row">
          <text class="rules-col-level">等级</text>
          <text class="rules-col-match">中奖条件</text>
          <text class="rules-col-prize">奖金</text>
          <text class="rules-col-prob">概率</text>
        </view>
        <view v-for="(rule, index) in rulesList" :key="index" class="rules-item-row" :class="{ 'first-row': index === 0 }">
          <view class="rules-level">{{ rule.level }}</view>
          <text class="rules-match">{{ rule.match }}</text>
          <text class="rules-prize">{{ rule.prize }}</text>
          <text class="rules-prob">{{ rule.probability }}</text>
        </view>
      </view>
    </view>

    <view class="history-section">
      <view class="section-header">
        <text class="section-title">历史记录</text>
        <text class="more-btn" @click="scrollToHistory">查看更多</text>
      </view>
      <view class="history-list">
        <view v-for="(item, index) in displayHistory" :key="index" class="history-item">
          <text class="history-session">{{ item.issue }}</text>
          <view class="history-numbers">
            <view v-for="(num, i) in getMainNumbers(item)" :key="i" class="mini-num primary">{{ num }}</view>
            <view class="mini-num secondary">{{ item.special_num }}</view>
          </view>
          <view class="history-info">
            <text class="history-date">{{ item.draw_date }}</text>
            <text class="history-hezhi">和值: {{ item.hezhi }}</text>
          </view>
        </view>
      </view>
    </view>

    <view class="bottom-actions">
      <view class="action-btn detailed" @click="generateReport('detailed')">
        <text class="btn-icon">📋</text>
        <text class="btn-text">详细报告</text>
      </view>
      <view class="action-btn optimal" @click="generateReport('optimal')">
        <text class="btn-icon">🎯</text>
        <text class="btn-text">精选推荐</text>
      </view>
    </view>

    <LoginModal :visible="showLoginModal" @close="showLoginModal = false" @login-success="onLoginSuccess" />
    
    <view v-if="showUserMenu" class="user-menu-overlay" @click.self="showUserMenu = false">
      <view class="user-menu">
        <view class="menu-header">
          <text class="menu-title">用户菜单</text>
        </view>
        <view class="menu-list">
          <view v-if="!userStore.isPaid" class="menu-item" @click="handleUpgrade">
            <text class="menu-icon">💎</text>
            <text class="menu-text">升级VIP会员</text>
            <text class="menu-arrow">›</text>
          </view>
          <view class="menu-item" @click="handleLogout">
            <text class="menu-icon">🚪</text>
            <text class="menu-text">退出登录</text>
            <text class="menu-arrow">›</text>
          </view>
        </view>
      </view>
    </view>
  </view>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { lotteryTypes, lotteryHistory, prizeLevels } from '../../data/lotteryData.js'
import { getHotNumbers, getColdNumbers, analyzeNumberDistribution } from '../../utils/index.js'
import { useUserStore } from '../../store/user'
import LoginModal from '../../components/LoginModal.vue'

const userStore = useUserStore()
const selectedGroup = ref('qixingcai')
const showLoginModal = ref(false)
const showUserMenu = ref(false)

const currentGroupInfo = computed(() => {
  return lotteryTypes.find(l => l.id === selectedGroup.value) || lotteryTypes[0]
})

const historyData = computed(() => {
  return lotteryHistory[selectedGroup.value] || []
})

const latestData = computed(() => {
  return historyData.value[0] || {}
})

const mainNumbers = computed(() => {
  const data = latestData.value
  return [data.num1, data.num2, data.num3, data.num4, data.num5, data.num6].filter(n => n !== undefined)
})

const hotNumbers = computed(() => {
  return getHotNumbers(historyData.value, 5)
})

const coldNumbers = computed(() => {
  return getColdNumbers(historyData.value, 5)
})

const distribution = computed(() => {
  return analyzeNumberDistribution(historyData.value)
})

const rulesList = computed(() => {
  return prizeLevels[selectedGroup.value] || []
})

const displayHistory = computed(() => {
  return historyData.value.slice(1, 6)
})

function getMainNumbers(item) {
  return [item.num1, item.num2, item.num3, item.num4, item.num5, item.num6].filter(n => n !== undefined)
}

onMounted(() => {
  userStore.initUserStatus()
})

function refreshData() {
  uni.showToast({
    title: '数据已刷新',
    icon: 'success'
  })
}

function scrollToHistory() {
  uni.showToast({
    title: '显示全部记录',
    icon: 'none'
  })
}

function generateReport(type) {
  if (!userStore.isLoggedIn) {
    showLoginModal.value = true
    return
  }
  
  uni.navigateTo({
    url: `/pages/report/report?type=${type}&group=${selectedGroup.value}`
  })
}

function onLoginSuccess() {
  uni.showToast({
    title: '登录成功',
    icon: 'success'
  })
}

function handleUpgrade() {
  showUserMenu.value = false
  uni.navigateTo({
    url: `/pages/report/report?type=detailed&group=${selectedGroup.value}`
  })
}

function handleLogout() {
  uni.showModal({
    title: '确认退出',
    content: '确定要退出登录吗？',
    success: (res) => {
      if (res.confirm) {
        userStore.logout()
        showUserMenu.value = false
      }
    }
  })
}
</script>

<style lang="scss">
.container {
  min-height: 100vh;
  background: linear-gradient(180deg, #43A047 0%, #F5F7FA 30%);
  padding-bottom: 120rpx;
}

.header {
  padding: 100rpx 30rpx 60rpx;
  text-align: center;
}

.header-content {
  background: rgba(255, 255, 255, 0.95);
  border-radius: 20rpx;
  padding: 40rpx;
  box-shadow: 0 8rpx 32rpx rgba(0, 0, 0, 0.1);
}

.header-title {
  font-size: 44rpx;
  font-weight: bold;
  color: #43A047;
  display: block;
  letter-spacing: 4rpx;
}

.header-subtitle {
  font-size: 24rpx;
  color: #666;
  margin-top: 16rpx;
  display: block;
  letter-spacing: 2rpx;
}

.user-status-bar {
  margin-top: 24rpx;
  display: flex;
  justify-content: flex-end;
}

.user-info {
  display: flex;
  align-items: center;
  gap: 12rpx;
  background: rgba(255, 255, 255, 0.9);
  padding: 12rpx 24rpx;
  border-radius: 30rpx;
}

.user-name {
  font-size: 26rpx;
  color: #333;
}

.vip-badge {
  background: linear-gradient(135deg, #FFD700, #FFA500);
  color: #fff;
  font-size: 20rpx;
  font-weight: bold;
  padding: 4rpx 12rpx;
  border-radius: 12rpx;
}

.login-hint {
  background: rgba(255, 255, 255, 0.9);
  padding: 12rpx 24rpx;
  border-radius: 30rpx;
}

.login-text {
  font-size: 26rpx;
  color: #43A047;
}

.section-title {
  font-size: 30rpx;
  font-weight: bold;
  color: #333;
  margin-bottom: 20rpx;
  display: block;
  letter-spacing: 2rpx;
}

.section-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 0 30rpx;
  margin-bottom: 20rpx;
}

.refresh-btn,
.more-btn {
  font-size: 24rpx;
  color: #43A047;
  letter-spacing: 1rpx;
}

.current-data-section,
.stats-section,
.rules-section,
.history-section {
  background: #fff;
  margin: 0 30rpx 30rpx;
  border-radius: 20rpx;
  padding: 30rpx;
  box-shadow: 0 4rpx 20rpx rgba(0, 0, 0, 0.05);
}

.latest-result {
  text-align: center;
}

.result-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 30rpx;
}

.result-session {
  font-size: 28rpx;
  font-weight: bold;
  color: #333;
  letter-spacing: 1rpx;
}

.result-date {
  font-size: 24rpx;
  color: #999;
}

.result-numbers {
  display: flex;
  justify-content: center;
  align-items: center;
  gap: 16rpx;
  flex-wrap: wrap;
  margin-bottom: 24rpx;
}

.num-box {
  width: 72rpx;
  height: 72rpx;
  border-radius: 12rpx;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 32rpx;
  font-weight: bold;
  color: #fff;
}

.num-box.primary {
  background: linear-gradient(145deg, #43A047, #2E7D32);
}

.num-box.secondary {
  background: linear-gradient(145deg, #FF9800, #F57C00);
}

.main-numbers,
.secondary-numbers {
  display: flex;
  gap: 16rpx;
}

.secondary-numbers {
  margin-left: 20rpx;
}

.result-stats {
  display: flex;
  justify-content: center;
  gap: 48rpx;
  padding-top: 24rpx;
  border-top: 1rpx dashed #E0E0E0;
}

.stat-item {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8rpx;
}

.stat-label {
  font-size: 22rpx;
  color: #999;
}

.stat-value {
  font-size: 28rpx;
  font-weight: bold;
  color: #333;
}

.stat-value.odd {
  color: #E53935;
}

.stat-value.even {
  color: #1E88E5;
}

.stats-grid {
  display: flex;
  gap: 20rpx;
  margin-bottom: 30rpx;
}

.stat-card {
  flex: 1;
  background: linear-gradient(145deg, #fff, #F8FAFC);
  border-radius: 20rpx;
  padding: 28rpx 20rpx;
  text-align: center;
  box-shadow: 0 4rpx 16rpx rgba(0, 0, 0, 0.04);
  border: 2rpx solid #E8ECEF;
}

.stat-card.hot {
  border-top: 6rpx solid #FF9800;
  background: linear-gradient(145deg, #FFF8F0, #FFFAF5);
}

.stat-card.cold {
  border-top: 6rpx solid #2196F3;
  background: linear-gradient(145deg, #F0F7FF, #F5FAFF);
}

.stat-icon {
  font-size: 44rpx;
  display: block;
  margin-bottom: 12rpx;
}

.stat-label {
  font-size: 24rpx;
  font-weight: 600;
  color: #333;
  display: block;
  letter-spacing: 1rpx;
  margin-bottom: 20rpx;
}

.stat-values {
  display: flex;
  justify-content: center;
  gap: 10rpx;
  flex-wrap: wrap;
}

.stat-num {
  width: 56rpx;
  height: 56rpx;
  border-radius: 12rpx;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 26rpx;
  font-weight: bold;
  color: #fff;
  background: linear-gradient(145deg, #43A047, #2E7D32);
}

.stat-card.hot .stat-num {
  background: linear-gradient(145deg, #FF9800, #F57C00);
}

.stat-card.cold .stat-num {
  background: linear-gradient(145deg, #2196F3, #1976D2);
}

.stat-legend {
  margin-top: 16rpx;
  padding-top: 16rpx;
  border-top: 1rpx dashed #E0E0E0;
}

.legend-text {
  font-size: 20rpx;
  color: #999;
  letter-spacing: 0.5rpx;
}

.distribution-card {
  background: linear-gradient(145deg, #fff, #F8FAFC);
  border-radius: 20rpx;
  padding: 28rpx;
  border: 2rpx solid #E8ECEF;
}

.card-title {
  font-size: 28rpx;
  font-weight: bold;
  color: #333;
  margin-bottom: 24rpx;
  display: block;
  letter-spacing: 1rpx;
}

.distribution-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 24rpx;
}

.dist-item {
  display: flex;
  flex-direction: column;
  gap: 16rpx;
}

.dist-bar-container {
  display: flex;
  align-items: center;
  gap: 12rpx;
}

.dist-bar-wrapper {
  flex: 1;
  height: 16rpx;
  background: #E8ECEF;
  border-radius: 8rpx;
  overflow: hidden;
}

.dist-bar {
  height: 100%;
  border-radius: 8rpx;
  transition: width 0.8s ease-out;
}

.dist-bar.odd {
  background: linear-gradient(90deg, #E53935, #EF5350);
}

.dist-bar.even {
  background: linear-gradient(90deg, #1E88E5, #64B5F6);
}

.dist-bar.small {
  background: linear-gradient(90deg, #7B1FA2, #AB47BC);
}

.dist-bar.large {
  background: linear-gradient(90deg, #FF9800, #FFB74D);
}

.dist-value {
  font-size: 24rpx;
  font-weight: bold;
  color: #333;
  min-width: 80rpx;
  text-align: right;
}

.dist-label {
  font-size: 22rpx;
  color: #666;
  letter-spacing: 0.5rpx;
}

.rules-section {
  background: #fff;
  margin: 0 30rpx 30rpx;
  border-radius: 20rpx;
  padding: 30rpx;
  box-shadow: 0 4rpx 20rpx rgba(0, 0, 0, 0.05);
}

.rules-table {
  background: #F8FAFC;
  border-radius: 16rpx;
  overflow: hidden;
}

.rules-header-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 20rpx 24rpx;
  background: linear-gradient(135deg, #43A047, #2E7D32);
  color: #fff;
}
.rules-col-level,
.rules-col-match,
.rules-col-prize,
.rules-col-prob {
  font-size: 20rpx;
  font-weight: bold;
  letter-spacing: 1rpx;
}

.rules-col-level { flex: 0 0 100rpx; }
.rules-col-match { flex: 0 0 120rpx; text-align: center; }
.rules-col-prize { flex: 1; text-align: right; }
.rules-col-prob { flex: 0 0 180rpx; text-align: right; font-size: 18rpx; }

.rules-item-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 20rpx 24rpx;
  border-bottom: 1rpx solid #E8ECEF;
  transition: background 0.2s;
}

.rules-item-row:last-child {
  border-bottom: none;
}

.rules-item-row.first-row {
  background: #E8F5E9;
}

.rules-item-row:hover {
  background: #F0F7FF;
}

.rules-level {
  flex: 0 0 100rpx;
  font-size: 24rpx;
  font-weight: bold;
  color: #43A047;
  background: rgba(67, 160, 71, 0.1);
  padding: 8rpx 16rpx;
  border-radius: 8rpx;
  text-align: center;
}

.rules-match {
  flex: 0 0 120rpx;
  font-size: 22rpx;
  color: #666;
  text-align: center;
}

.rules-prize {
  flex: 1;
  font-size: 24rpx;
  font-weight: bold;
  color: #43A047;
  text-align: right;
}

.rules-prob {
  flex: 0 0 180rpx;
  font-size: 20rpx;
  color: #999;
  text-align: right;
}

.history-list {
  display: flex;
  flex-direction: column;
  gap: 16rpx;
}

.history-item {
  display: flex;
  align-items: center;
  gap: 20rpx;
  padding: 20rpx;
  background: #F8FAFC;
  border-radius: 12rpx;
}

.history-session {
  font-size: 24rpx;
  color: #999;
  width: 120rpx;
}

.history-numbers {
  flex: 1;
  display: flex;
  justify-content: center;
  gap: 8rpx;
}

.mini-num {
  width: 40rpx;
  height: 40rpx;
  border-radius: 8rpx;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 20rpx;
  font-weight: bold;
  color: #fff;
}

.mini-num.primary {
  background: #43A047;
}

.mini-num.secondary {
  background: #FF9800;
}

.history-info {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  gap: 8rpx;
  width: 120rpx;
}

.history-date {
  font-size: 20rpx;
  color: #999;
}

.history-hezhi {
  font-size: 20rpx;
  color: #666;
}

.bottom-actions {
  position: fixed;
  bottom: 0;
  left: 0;
  right: 0;
  display: flex;
  gap: 24rpx;
  padding: 20rpx 32rpx;
  padding-bottom: calc(20rpx + env(safe-area-inset-bottom));
  background: rgba(255, 255, 255, 0.98);
  box-shadow: 0 -4rpx 24rpx rgba(0, 0, 0, 0.08);
  backdrop-filter: blur(10px);
  z-index: 100;
}

.action-btn {
  flex: 1;
  min-width: 0;
  height: 88rpx;
  border-radius: 44rpx;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 10rpx;
  font-size: 26rpx;
  font-weight: bold;
  color: #fff;
  letter-spacing: 2rpx;
  overflow: hidden;
  box-shadow: 0 4rpx 16rpx rgba(0, 0, 0, 0.15);
  transition: all 0.3s ease;
}

.action-btn:active {
  transform: scale(0.96);
  box-shadow: 0 2rpx 8rpx rgba(0, 0, 0, 0.1);
}

.action-btn.detailed {
  background: linear-gradient(135deg, #43A047, #2E7D32);
}

.action-btn.optimal {
  background: linear-gradient(135deg, #FF9800, #F57C00);
}

.btn-icon {
  font-size: 34rpx;
  flex-shrink: 0;
}

.btn-text {
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.user-menu-overlay {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background: rgba(0, 0, 0, 0.5);
  z-index: 200;
  display: flex;
  justify-content: flex-end;
}

.user-menu {
  width: 400rpx;
  background: #fff;
  border-radius: 24rpx 0 0 24rpx;
  animation: slideIn 0.3s ease;
}

@keyframes slideIn {
  from { transform: translateX(100%); }
  to { transform: translateX(0); }
}

.menu-header {
  padding: 32rpx;
  border-bottom: 2rpx solid #F0F0F0;
}

.menu-title {
  font-size: 32rpx;
  font-weight: bold;
  color: #333;
}

.menu-list {
  padding: 16rpx 0;
}

.menu-item {
  display: flex;
  align-items: center;
  padding: 24rpx 32rpx;
  gap: 16rpx;
}

.menu-icon {
  font-size: 36rpx;
}

.menu-text {
  flex: 1;
  font-size: 28rpx;
  color: #333;
}

.menu-arrow {
  font-size: 36rpx;
  color: #999;
}

@media screen and (max-width: 375px) {
  .bottom-actions {
    gap: 16rpx;
    padding: 16rpx 20rpx;
  }
  
  .action-btn {
    height: 80rpx;
    font-size: 22rpx;
    gap: 8rpx;
    letter-spacing: 1rpx;
  }
  
  .btn-icon {
    font-size: 28rpx;
  }
}

@media screen and (min-width: 414px) {
  .bottom-actions {
    padding: 24rpx 48rpx;
  }
  
  .action-btn {
    height: 96rpx;
    font-size: 28rpx;
    max-width: 320rpx;
  }
}
</style>