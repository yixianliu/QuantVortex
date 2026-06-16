<template>
  <view class="container">
    <!-- 动态背景粒子 -->
    <view class="particles">
      <view v-for="n in 12" :key="n" class="particle" :style="particleStyle(n)"></view>
    </view>

    <!-- 顶部导航 -->
    <view class="header" :style="headerGradient">
      <view class="header-glow"></view>
      <view class="header-content">
        <view class="lottery-tabs">
          <view
            v-for="lottery in lotteryTypes"
            :key="lottery.id"
            class="tab-item"
            :class="{ active: selectedGroup === lottery.id }"
            @click="switchLottery(lottery.id)"
          >
            <text class="tab-icon">{{ lottery.icon }}</text>
            <text class="tab-name">{{ lottery.name }}</text>
            <view v-if="selectedGroup === lottery.id" class="tab-indicator"></view>
          </view>
        </view>
        <view class="lottery-subtitle">{{ currentGroupInfo.description }}</view>
      </view>

      <!-- 用户状态 -->
      <view class="user-status-bar">
        <view v-if="userStore.isLoggedIn" class="user-info" @click="showUserMenu = true">
          <view class="user-avatar">
            <text class="avatar-text">{{ userStore.userInfo.nickname?.charAt(0) || 'U' }}</text>
          </view>
          <view class="user-meta">
            <text class="user-name">{{ userStore.userInfo.nickname }}</text>
            <view class="vip-badge" v-if="userStore.isPaid">
              <text class="vip-icon">VIP</text>
            </view>
          </view>
        </view>
        <view v-else class="login-hint" @click="showLoginModal = true">
          <view class="login-avatar-placeholder">
            <text class="placeholder-icon">+</text>
          </view>
          <text class="login-text">登录</text>
        </view>
      </view>
    </view>

    <!-- 最新开奖结果 -->
    <view class="current-data-section card-3d">
      <view class="section-header">
        <view class="section-title-wrapper">
          <view class="title-dot" :style="{ background: currentGroupInfo.color }"></view>
          <text class="section-title">最新开奖结果</text>
        </view>
        <view class="refresh-btn" @click="refreshData">
          <text class="refresh-icon" :class="{ spinning: isRefreshing }">&#x21bb;</text>
          <text class="refresh-text">刷新</text>
        </view>
      </view>

      <view class="latest-result">
        <view class="result-header">
          <view class="result-session-wrapper">
            <text class="result-session-label">期号</text>
            <text class="result-session">{{ latestData.issue }}</text>
          </view>
          <text class="result-date">{{ latestData.draw_date }}</text>
        </view>

        <!-- 数字球动画展示 -->
        <view class="result-numbers">
          <view
            v-for="(num, index) in mainNumbers"
            :key="'main-' + index"
            class="num-ball"
            :class="['ball-animate-' + index, { 'ball-pop': ballPopIndex === index }]"
            :style="{ animationDelay: (index * 0.1) + 's', background: currentGroupInfo.gradient }"
            @click="popBall(index)"
          >
            <text class="ball-number">{{ num }}</text>
            <view class="ball-shine"></view>
          </view>
          <view v-if="currentGroupInfo.hasSpecial" class="special-divider">
            <text class="divider-text">+</text>
          </view>
          <view
            v-if="currentGroupInfo.hasSpecial"
            class="num-ball special"
            :class="{ 'ball-pop': ballPopIndex === 'special' }"
            @click="popBall('special')"
          >
            <text class="ball-number">{{ latestData.special_num }}</text>
            <view class="ball-shine"></view>
          </view>
        </view>

        <view class="result-stats">
          <view class="stat-item" v-for="(stat, idx) in statsList" :key="idx">
            <view class="stat-icon-wrapper" :style="{ background: stat.bgColor }">
              <text class="stat-icon-text">{{ stat.icon }}</text>
            </view>
            <view class="stat-info">
              <text class="stat-label">{{ stat.label }}</text>
              <text class="stat-value" :style="{ color: stat.color }">{{ stat.value }}</text>
            </view>
          </view>
        </view>
      </view>
    </view>

    <!-- 数据统计 -->
    <view class="stats-section card-3d">
      <view class="section-header">
        <view class="section-title-wrapper">
          <view class="title-dot" :style="{ background: currentGroupInfo.color }"></view>
          <text class="section-title">数据统计</text>
        </view>
      </view>

      <view class="stats-grid">
        <view class="stat-card hot" @click="shakeCard('hot')" :class="{ shake: shakingCard === 'hot' }">
          <view class="card-glow hot-glow"></view>
          <view class="card-header">
            <view class="card-icon-wrapper hot-icon">
              <text class="card-icon-text">&#x1F525;</text>
            </view>
            <text class="card-label">热号 TOP5</text>
          </view>
          <view class="card-numbers">
            <view
              v-for="(item, index) in hotNumbers"
              :key="'hot-' + index"
              class="card-num"
              :style="{ animationDelay: (index * 0.08) + 's' }"
            >
              <text class="num-value">{{ item.num }}</text>
              <view class="num-bar" :style="{ width: (item.count / hotNumbers[0].count * 100) + '%' }"></view>
            </view>
          </view>
          <view class="card-legend">
            <text class="legend-text">出现频率最高</text>
          </view>
        </view>

        <view class="stat-card cold" @click="shakeCard('cold')" :class="{ shake: shakingCard === 'cold' }">
          <view class="card-glow cold-glow"></view>
          <view class="card-header">
            <view class="card-icon-wrapper cold-icon">
              <text class="card-icon-text">&#x2744;&#xFE0F;</text>
            </view>
            <text class="card-label">冷号 TOP5</text>
          </view>
          <view class="card-numbers">
            <view
              v-for="(item, index) in coldNumbers"
              :key="'cold-' + index"
              class="card-num"
              :style="{ animationDelay: (index * 0.08) + 's' }"
            >
              <text class="num-value">{{ item.num }}</text>
              <view class="num-bar cold-bar" :style="{ width: Math.max(20, item.count * 15) + '%' }"></view>
            </view>
          </view>
          <view class="card-legend">
            <text class="legend-text">出现频率最低</text>
          </view>
        </view>
      </view>

      <!-- 号码分布 -->
      <view class="distribution-card">
        <view class="dist-header">
          <text class="dist-title">&#x1F4C8; 号码分布</text>
          <view class="dist-legend">
            <view class="dist-legend-item">
              <view class="legend-dot odd"></view>
              <text class="legend-label">奇数</text>
            </view>
            <view class="dist-legend-item">
              <view class="legend-dot even"></view>
              <text class="legend-label">偶数</text>
            </view>
          </view>
        </view>
        <view class="distribution-grid">
          <view class="dist-item" v-for="(item, idx) in distributionList" :key="idx">
            <view class="dist-bar-container">
              <view class="dist-bar-wrapper">
                <view
                  class="dist-bar"
                  :class="item.type"
                  :style="{ width: item.value + '%' }"
                ></view>
              </view>
              <text class="dist-value">{{ item.value }}%</text>
            </view>
            <text class="dist-label">{{ item.label }}</text>
          </view>
        </view>
      </view>
    </view>

    <!-- 中奖规则 -->
    <view class="rules-section card-3d">
      <view class="section-header">
        <view class="section-title-wrapper">
          <view class="title-dot" :style="{ background: currentGroupInfo.color }"></view>
          <text class="section-title">&#x1F4CB; 中奖规则</text>
        </view>
      </view>
      <view class="rules-table">
        <view class="rules-header-row">
          <text class="rules-col-level">等级</text>
          <text class="rules-col-match">中奖条件</text>
          <text class="rules-col-prize">奖金</text>
          <text class="rules-col-prob">概率</text>
        </view>
        <view
          v-for="(rule, index) in rulesList"
          :key="index"
          class="rules-item-row"
          :class="{ 'first-row': index === 0, 'highlight-row': hoveredRule === index }"
          @touchstart="hoveredRule = index"
          @touchend="hoveredRule = -1"
        >
          <view class="rules-level" :style="{ background: index === 0 ? currentGroupInfo.color : 'rgba(67, 160, 71, 0.1)' }">
            <text :style="{ color: index === 0 ? '#fff' : currentGroupInfo.color }">{{ rule.level }}</text>
          </view>
          <text class="rules-match">{{ rule.match }}</text>
          <text class="rules-prize" :style="{ color: currentGroupInfo.color }">{{ rule.prize }}</text>
          <text class="rules-prob">{{ rule.probability }}</text>
        </view>
      </view>
    </view>

    <!-- 历史记录 -->
    <view class="history-section card-3d">
      <view class="section-header">
        <view class="section-title-wrapper">
          <view class="title-dot" :style="{ background: currentGroupInfo.color }"></view>
          <text class="section-title">历史记录</text>
        </view>
        <view class="more-btn" @click="scrollToHistory">
          <text class="more-text">查看更多</text>
          <text class="more-icon">&#x203A;</text>
        </view>
      </view>
      <view class="history-list">
        <view
          v-for="(item, index) in displayHistory"
          :key="index"
          class="history-item"
          :class="{ 'item-slide': true }"
          :style="{ animationDelay: (index * 0.05) + 's' }"
        >
          <view class="history-left">
            <text class="history-session">{{ item.issue }}</text>
            <text class="history-date">{{ item.draw_date }}</text>
          </view>
          <view class="history-numbers">
            <view
              v-for="(num, i) in getMainNumbers(item, selectedGroup)"
              :key="i"
              class="mini-num"
              :style="{ background: currentGroupInfo.gradient }"
            >{{ num }}</view>
            <view
              v-if="currentGroupInfo.hasSpecial"
              class="mini-num special"
            >{{ item.special_num }}</view>
          </view>
          <view class="history-info">
            <view class="info-badge" :style="{ background: currentGroupInfo.bgColor }">
              <text :style="{ color: currentGroupInfo.color, fontSize: '20rpx' }">和值 {{ item.hezhi }}</text>
            </view>
          </view>
        </view>
      </view>
    </view>

    <!-- 底部操作栏 -->
    <view class="bottom-actions">
      <view class="action-btn detailed" @click="generateReport('detailed')">
        <view class="btn-glow"></view>
        <text class="btn-icon">&#x1F4CB;</text>
        <text class="btn-text">详细报告</text>
      </view>
      <view class="action-btn optimal" @click="generateReport('optimal')">
        <view class="btn-glow"></view>
        <text class="btn-icon">&#x1F3AF;</text>
        <text class="btn-text">精选推荐</text>
      </view>
    </view>

    <!-- 登录弹窗 -->
    <LoginModal :visible="showLoginModal" @close="showLoginModal = false" @login-success="onLoginSuccess" />

    <!-- 用户菜单 -->
    <view v-if="showUserMenu" class="user-menu-overlay" @click.self="showUserMenu = false">
      <view class="user-menu">
        <view class="menu-header" :style="{ background: currentGroupInfo.gradient }">
          <view class="menu-avatar">
            <text class="menu-avatar-text">{{ userStore.userInfo.nickname?.charAt(0) || 'U' }}</text>
          </view>
          <text class="menu-title">{{ userStore.userInfo.nickname }}</text>
          <view class="menu-vip" v-if="userStore.isPaid">VIP 会员</view>
        </view>
        <view class="menu-list">
          <view v-if="!userStore.isPaid" class="menu-item" @click="handleUpgrade">
            <view class="menu-item-icon" :style="{ background: '#FFF8E1' }">
              <text style="font-size: 32rpx;">&#x1F48E;</text>
            </view>
            <text class="menu-text">升级VIP会员</text>
            <text class="menu-arrow">&#x203A;</text>
          </view>
          <view class="menu-item" @click="handleLogout">
            <view class="menu-item-icon" :style="{ background: '#FFEBEE' }">
              <text style="font-size: 32rpx;">&#x1F6AA;</text>
            </view>
            <text class="menu-text">退出登录</text>
            <text class="menu-arrow">&#x203A;</text>
          </view>
        </view>
      </view>
    </view>
  </view>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { lotteryTypes, lotteryHistory, prizeLevels } from '@/data/lotteryData.js'
import { getHotNumbers, getColdNumbers, analyzeNumberDistribution, getMainNumbers } from '@/utils/index.js'
import { useUserStore } from '@/store/user'
import LoginModal from '@/components/LoginModal.vue'

const userStore = useUserStore()
const selectedGroup = ref('qixingcai')
const showLoginModal = ref(false)
const showUserMenu = ref(false)
const isRefreshing = ref(false)
const ballPopIndex = ref(-1)
const shakingCard = ref('')
const hoveredRule = ref(-1)

const currentGroupInfo = computed(() => {
  return lotteryTypes.find(l => l.id === selectedGroup.value) || lotteryTypes[0]
})

const headerGradient = computed(() => {
  return {
    background: currentGroupInfo.value.gradient
  }
})

const historyData = computed(() => {
  return lotteryHistory[selectedGroup.value] || []
})

const latestData = computed(() => {
  return historyData.value[0] || {}
})

const mainNumbers = computed(() => {
  return getMainNumbers(latestData.value, selectedGroup.value)
})

const hotNumbers = computed(() => {
  return getHotNumbers(historyData.value, 5, selectedGroup.value)
})

const coldNumbers = computed(() => {
  return getColdNumbers(historyData.value, 5, selectedGroup.value)
})

const distribution = computed(() => {
  return analyzeNumberDistribution(historyData.value, selectedGroup.value)
})

const distributionList = computed(() => [
  { type: 'odd', label: '奇数', value: distribution.value.oddRate },
  { type: 'even', label: '偶数', value: distribution.value.evenRate },
  { type: 'small', label: '小号', value: distribution.value.smallRate },
  { type: 'large', label: '大号', value: distribution.value.largeRate }
])

const rulesList = computed(() => {
  return prizeLevels[selectedGroup.value] || []
})

const displayHistory = computed(() => {
  return historyData.value.slice(1, 6)
})

const statsList = computed(() => [
  {
    icon: '&#x2211;',
    label: '和值',
    value: latestData.value.hezhi,
    color: latestData.value.hezhi_type === '奇' ? '#E53935' : '#1E88E5',
    bgColor: latestData.value.hezhi_type === '奇' ? '#FFEBEE' : '#E3F2FD'
  },
  {
    icon: '&#x26A1;',
    label: '奇偶比',
    value: latestData.value.odd_even_ratio,
    color: '#43A047',
    bgColor: '#E8F5E9'
  },
  {
    icon: '&#x1F4CF;',
    label: '跨度',
    value: latestData.value.span,
    color: '#FF9800',
    bgColor: '#FFF3E0'
  }
])

function particleStyle(n) {
  const size = 4 + Math.random() * 8
  const left = Math.random() * 100
  const delay = Math.random() * 8
  const duration = 6 + Math.random() * 6
  return {
    width: size + 'rpx',
    height: size + 'rpx',
    left: left + '%',
    animationDelay: delay + 's',
    animationDuration: duration + 's'
  }
}

function switchLottery(id) {
  if (selectedGroup.value === id) return
  selectedGroup.value = id
  uni.showToast({
    title: `已切换至${currentGroupInfo.value.name}`,
    icon: 'none',
    duration: 1500
  })
}

function popBall(index) {
  ballPopIndex.value = index
  setTimeout(() => {
    ballPopIndex.value = -1
  }, 300)
}

function shakeCard(type) {
  shakingCard.value = type
  setTimeout(() => {
    shakingCard.value = ''
  }, 500)
}

onMounted(() => {
  userStore.initUserStatus()
})

function refreshData() {
  isRefreshing.value = true
  setTimeout(() => {
    isRefreshing.value = false
    uni.showToast({
      title: '数据已刷新',
      icon: 'success'
    })
  }, 1000)
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
  background: linear-gradient(180deg, #1a1a2e 0%, #16213e 50%, #0f3460 100%);
  padding-bottom: 140rpx;
  position: relative;
  overflow: hidden;
}

/* 粒子背景 */
.particles {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  pointer-events: none;
  z-index: 0;
}

.particle {
  position: absolute;
  background: rgba(255, 255, 255, 0.3);
  border-radius: 50%;
  animation: float-up linear infinite;
}

@keyframes float-up {
  0% {
    transform: translateY(100vh) scale(0);
    opacity: 0;
  }
  10% {
    opacity: 1;
  }
  90% {
    opacity: 1;
  }
  100% {
    transform: translateY(-100rpx) scale(1);
    opacity: 0;
  }
}

/* 头部 */
.header {
  padding: 80rpx 30rpx 40rpx;
  position: relative;
  z-index: 1;
  overflow: hidden;
}

.header-glow {
  position: absolute;
  top: -100rpx;
  right: -100rpx;
  width: 400rpx;
  height: 400rpx;
  background: radial-gradient(circle, rgba(255,255,255,0.15) 0%, transparent 70%);
  border-radius: 50%;
}

.header-content {
  position: relative;
  z-index: 2;
}

/* 彩票切换标签 */
.lottery-tabs {
  display: flex;
  gap: 16rpx;
  margin-bottom: 16rpx;
}

.tab-item {
  display: flex;
  align-items: center;
  gap: 8rpx;
  padding: 16rpx 28rpx;
  border-radius: 40rpx;
  background: rgba(255, 255, 255, 0.1);
  backdrop-filter: blur(10rpx);
  border: 2rpx solid rgba(255, 255, 255, 0.15);
  transition: all 0.3s ease;
  position: relative;
}

.tab-item.active {
  background: rgba(255, 255, 255, 0.25);
  border-color: rgba(255, 255, 255, 0.4);
  transform: scale(1.05);
}

.tab-icon {
  font-size: 32rpx;
}

.tab-name {
  font-size: 28rpx;
  font-weight: bold;
  color: #fff;
}

.tab-indicator {
  position: absolute;
  bottom: -8rpx;
  left: 50%;
  transform: translateX(-50%);
  width: 24rpx;
  height: 6rpx;
  background: #fff;
  border-radius: 3rpx;
}

.lottery-subtitle {
  font-size: 24rpx;
  color: rgba(255, 255, 255, 0.7);
  margin-top: 8rpx;
}

/* 用户状态 */
.user-status-bar {
  position: absolute;
  top: 40rpx;
  right: 30rpx;
  z-index: 3;
}

.user-info {
  display: flex;
  align-items: center;
  gap: 12rpx;
  background: rgba(255, 255, 255, 0.15);
  backdrop-filter: blur(10rpx);
  padding: 8rpx 16rpx 8rpx 8rpx;
  border-radius: 40rpx;
  border: 1rpx solid rgba(255, 255, 255, 0.2);
}

.user-avatar {
  width: 48rpx;
  height: 48rpx;
  border-radius: 50%;
  background: linear-gradient(135deg, #FFD700, #FFA500);
  display: flex;
  align-items: center;
  justify-content: center;
}

.avatar-text {
  font-size: 24rpx;
  font-weight: bold;
  color: #fff;
}

.user-meta {
  display: flex;
  align-items: center;
  gap: 8rpx;
}

.user-name {
  font-size: 24rpx;
  color: #fff;
  font-weight: 600;
}

.vip-badge {
  background: linear-gradient(135deg, #FFD700, #FFA500);
  padding: 2rpx 10rpx;
  border-radius: 10rpx;
}

.vip-icon {
  font-size: 18rpx;
  font-weight: bold;
  color: #fff;
}

.login-hint {
  display: flex;
  align-items: center;
  gap: 8rpx;
  background: rgba(255, 255, 255, 0.15);
  backdrop-filter: blur(10rpx);
  padding: 8rpx 20rpx;
  border-radius: 40rpx;
  border: 1rpx solid rgba(255, 255, 255, 0.2);
}

.login-avatar-placeholder {
  width: 40rpx;
  height: 40rpx;
  border-radius: 50%;
  border: 2rpx dashed rgba(255, 255, 255, 0.5);
  display: flex;
  align-items: center;
  justify-content: center;
}

.placeholder-icon {
  font-size: 24rpx;
  color: rgba(255, 255, 255, 0.7);
  font-weight: bold;
}

.login-text {
  font-size: 24rpx;
  color: #fff;
}

/* 3D卡片效果 */
.card-3d {
  position: relative;
  z-index: 1;
  background: rgba(255, 255, 255, 0.95);
  margin: 0 30rpx 30rpx;
  border-radius: 24rpx;
  padding: 32rpx;
  box-shadow:
    0 8rpx 32rpx rgba(0, 0, 0, 0.15),
    0 2rpx 8rpx rgba(0, 0, 0, 0.1);
  backdrop-filter: blur(20rpx);
  transform: translateZ(0);
  transition: transform 0.3s ease, box-shadow 0.3s ease;
}

.card-3d:active {
  transform: scale(0.98) translateZ(0);
}

/* 区块标题 */
.section-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 24rpx;
}

.section-title-wrapper {
  display: flex;
  align-items: center;
  gap: 12rpx;
}

.title-dot {
  width: 12rpx;
  height: 12rpx;
  border-radius: 50%;
}

.section-title {
  font-size: 32rpx;
  font-weight: bold;
  color: #1a1a2e;
  letter-spacing: 2rpx;
}

/* 刷新按钮 */
.refresh-btn {
  display: flex;
  align-items: center;
  gap: 8rpx;
  padding: 8rpx 16rpx;
  background: rgba(67, 160, 71, 0.1);
  border-radius: 24rpx;
}

.refresh-icon {
  font-size: 28rpx;
  color: #43A047;
  transition: transform 0.3s ease;
}

.refresh-icon.spinning {
  animation: spin 1s linear infinite;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

.refresh-text {
  font-size: 24rpx;
  color: #43A047;
}

/* 最新开奖结果 */
.latest-result {
  text-align: center;
}

.result-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 32rpx;
}

.result-session-wrapper {
  display: flex;
  align-items: center;
  gap: 12rpx;
}

.result-session-label {
  font-size: 22rpx;
  color: #999;
  background: #F5F5F5;
  padding: 4rpx 12rpx;
  border-radius: 8rpx;
}

.result-session {
  font-size: 28rpx;
  font-weight: bold;
  color: #333;
}

.result-date {
  font-size: 24rpx;
  color: #999;
}

/* 数字球 */
.result-numbers {
  display: flex;
  justify-content: center;
  align-items: center;
  gap: 16rpx;
  flex-wrap: wrap;
  margin-bottom: 32rpx;
}

.num-ball {
  width: 84rpx;
  height: 84rpx;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  position: relative;
  box-shadow:
    0 6rpx 20rpx rgba(0, 0, 0, 0.2),
    inset 0 -4rpx 8rpx rgba(0, 0, 0, 0.1),
    inset 0 4rpx 8rpx rgba(255, 255, 255, 0.3);
  animation: ball-drop 0.6s ease-out forwards;
  opacity: 0;
  transform: translateY(-40rpx);
}

.num-ball.special {
  background: linear-gradient(145deg, #FF9800, #F57C00);
}

@keyframes ball-drop {
  0% {
    opacity: 0;
    transform: translateY(-40rpx) scale(0.5);
  }
  60% {
    transform: translateY(8rpx) scale(1.05);
  }
  100% {
    opacity: 1;
    transform: translateY(0) scale(1);
  }
}

.ball-number {
  font-size: 36rpx;
  font-weight: bold;
  color: #fff;
  z-index: 2;
}

.ball-shine {
  position: absolute;
  top: 12rpx;
  left: 16rpx;
  width: 24rpx;
  height: 16rpx;
  background: rgba(255, 255, 255, 0.4);
  border-radius: 50%;
  transform: rotate(-30deg);
}

.ball-pop {
  animation: ball-pop-anim 0.3s ease !important;
}

@keyframes ball-pop-anim {
  0% { transform: scale(1); }
  50% { transform: scale(1.2); }
  100% { transform: scale(1); }
}

.special-divider {
  display: flex;
  align-items: center;
  justify-content: center;
}

.divider-text {
  font-size: 32rpx;
  font-weight: bold;
  color: #FF9800;
}

/* 结果统计 */
.result-stats {
  display: flex;
  justify-content: center;
  gap: 32rpx;
  padding-top: 24rpx;
  border-top: 2rpx dashed #E8E8E8;
}

.stat-item {
  display: flex;
  align-items: center;
  gap: 12rpx;
}

.stat-icon-wrapper {
  width: 56rpx;
  height: 56rpx;
  border-radius: 16rpx;
  display: flex;
  align-items: center;
  justify-content: center;
}

.stat-icon-text {
  font-size: 28rpx;
}

.stat-info {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
}

.stat-label {
  font-size: 20rpx;
  color: #999;
}

.stat-value {
  font-size: 28rpx;
  font-weight: bold;
}

/* 统计卡片 */
.stats-grid {
  display: flex;
  gap: 20rpx;
  margin-bottom: 32rpx;
}

.stat-card {
  flex: 1;
  background: linear-gradient(145deg, #fff, #F8FAFC);
  border-radius: 20rpx;
  padding: 28rpx 20rpx;
  position: relative;
  overflow: hidden;
  box-shadow: 0 4rpx 16rpx rgba(0, 0, 0, 0.06);
  border: 2rpx solid #E8ECEF;
  transition: transform 0.2s ease;
}

.stat-card:active {
  transform: scale(0.96);
}

.stat-card.shake {
  animation: shake 0.5s ease;
}

@keyframes shake {
  0%, 100% { transform: translateX(0); }
  25% { transform: translateX(-8rpx); }
  75% { transform: translateX(8rpx); }
}

.card-glow {
  position: absolute;
  top: -50%;
  right: -50%;
  width: 200%;
  height: 200%;
  border-radius: 50%;
  opacity: 0.05;
}

.hot-glow {
  background: radial-gradient(circle, #FF9800 0%, transparent 70%);
}

.cold-glow {
  background: radial-gradient(circle, #2196F3 0%, transparent 70%);
}

.card-header {
  display: flex;
  align-items: center;
  gap: 12rpx;
  margin-bottom: 20rpx;
}

.card-icon-wrapper {
  width: 48rpx;
  height: 48rpx;
  border-radius: 12rpx;
  display: flex;
  align-items: center;
  justify-content: center;
}

.hot-icon {
  background: #FFF3E0;
}

.cold-icon {
  background: #E3F2FD;
}

.card-icon-text {
  font-size: 28rpx;
}

.card-label {
  font-size: 26rpx;
  font-weight: 600;
  color: #333;
}

.card-numbers {
  display: flex;
  flex-direction: column;
  gap: 12rpx;
}

.card-num {
  display: flex;
  align-items: center;
  gap: 12rpx;
  animation: slide-in-right 0.4s ease-out forwards;
  opacity: 0;
}

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

.num-value {
  width: 44rpx;
  height: 44rpx;
  border-radius: 10rpx;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 24rpx;
  font-weight: bold;
  color: #fff;
  background: linear-gradient(145deg, #43A047, #2E7D32);
  flex-shrink: 0;
}

.stat-card.hot .num-value {
  background: linear-gradient(145deg, #FF9800, #F57C00);
}

.stat-card.cold .num-value {
  background: linear-gradient(145deg, #2196F3, #1976D2);
}

.num-bar {
  height: 8rpx;
  background: linear-gradient(90deg, #FF9800, #FFB74D);
  border-radius: 4rpx;
  transition: width 0.8s ease-out;
}

.cold-bar {
  background: linear-gradient(90deg, #2196F3, #64B5F6);
}

.card-legend {
  margin-top: 16rpx;
  padding-top: 16rpx;
  border-top: 1rpx dashed #E0E0E0;
}

.legend-text {
  font-size: 20rpx;
  color: #999;
}

/* 分布卡片 */
.distribution-card {
  background: linear-gradient(145deg, #F8FAFC, #fff);
  border-radius: 20rpx;
  padding: 28rpx;
  border: 2rpx solid #E8ECEF;
}

.dist-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 24rpx;
}

.dist-title {
  font-size: 28rpx;
  font-weight: bold;
  color: #333;
}

.dist-legend {
  display: flex;
  gap: 16rpx;
}

.dist-legend-item {
  display: flex;
  align-items: center;
  gap: 6rpx;
}

.legend-dot {
  width: 12rpx;
  height: 12rpx;
  border-radius: 50%;
}

.legend-dot.odd {
  background: linear-gradient(135deg, #E53935, #EF5350);
}

.legend-dot.even {
  background: linear-gradient(135deg, #1E88E5, #64B5F6);
}

.legend-label {
  font-size: 20rpx;
  color: #666;
}

.distribution-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 24rpx;
}

.dist-item {
  display: flex;
  flex-direction: column;
  gap: 12rpx;
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
  transition: width 1s ease-out;
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
}

/* 规则表格 */
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
  transition: all 0.2s;
}

.rules-item-row:last-child {
  border-bottom: none;
}

.rules-item-row.first-row {
  background: #E8F5E9;
}

.rules-item-row.highlight-row {
  background: #F0F7FF;
  transform: scale(1.01);
}

.rules-level {
  flex: 0 0 100rpx;
  font-size: 22rpx;
  font-weight: bold;
  padding: 8rpx 12rpx;
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
  text-align: right;
}

.rules-prob {
  flex: 0 0 180rpx;
  font-size: 20rpx;
  color: #999;
  text-align: right;
}

/* 历史记录 */
.history-list {
  display: flex;
  flex-direction: column;
  gap: 16rpx;
}

.history-item {
  display: flex;
  align-items: center;
  gap: 16rpx;
  padding: 20rpx;
  background: #F8FAFC;
  border-radius: 16rpx;
  animation: slide-in-left 0.4s ease-out forwards;
  opacity: 0;
}

@keyframes slide-in-left {
  from {
    opacity: 0;
    transform: translateX(-20rpx);
  }
  to {
    opacity: 1;
    transform: translateX(0);
  }
}

.history-left {
  display: flex;
  flex-direction: column;
  gap: 4rpx;
  width: 140rpx;
  flex-shrink: 0;
}

.history-session {
  font-size: 24rpx;
  font-weight: bold;
  color: #333;
}

.history-date {
  font-size: 20rpx;
  color: #999;
}

.history-numbers {
  flex: 1;
  display: flex;
  justify-content: center;
  gap: 8rpx;
}

.mini-num {
  width: 44rpx;
  height: 44rpx;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 22rpx;
  font-weight: bold;
  color: #fff;
  box-shadow: 0 2rpx 8rpx rgba(0, 0, 0, 0.15);
}

.mini-num.special {
  background: linear-gradient(145deg, #FF9800, #F57C00);
}

.history-info {
  width: 120rpx;
  flex-shrink: 0;
  display: flex;
  justify-content: flex-end;
}

.info-badge {
  padding: 6rpx 12rpx;
  border-radius: 20rpx;
}

.more-btn {
  display: flex;
  align-items: center;
  gap: 4rpx;
}

.more-text {
  font-size: 24rpx;
  color: #43A047;
}

.more-icon {
  font-size: 28rpx;
  color: #43A047;
}

/* 底部操作 */
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
  box-shadow: 0 -4rpx 24rpx rgba(0, 0, 0, 0.1);
  backdrop-filter: blur(20rpx);
  z-index: 100;
}

.action-btn {
  flex: 1;
  min-width: 0;
  height: 96rpx;
  border-radius: 48rpx;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 12rpx;
  font-size: 28rpx;
  font-weight: bold;
  color: #fff;
  letter-spacing: 2rpx;
  overflow: hidden;
  position: relative;
  box-shadow: 0 6rpx 20rpx rgba(0, 0, 0, 0.2);
  transition: all 0.3s ease;
}

.action-btn:active {
  transform: scale(0.96);
  box-shadow: 0 2rpx 8rpx rgba(0, 0, 0, 0.15);
}

.btn-glow {
  position: absolute;
  top: -50%;
  left: -50%;
  width: 200%;
  height: 200%;
  background: radial-gradient(circle, rgba(255,255,255,0.2) 0%, transparent 60%);
  opacity: 0;
  transition: opacity 0.3s;
}

.action-btn:active .btn-glow {
  opacity: 1;
}

.action-btn.detailed {
  background: linear-gradient(135deg, #43A047, #2E7D32);
}

.action-btn.optimal {
  background: linear-gradient(135deg, #FF9800, #F57C00);
}

.btn-icon {
  font-size: 36rpx;
  flex-shrink: 0;
}

.btn-text {
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

/* 用户菜单 */
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
  animation: fade-in 0.3s ease;
}

@keyframes fade-in {
  from { opacity: 0; }
  to { opacity: 1; }
}

.user-menu {
  width: 420rpx;
  background: #fff;
  border-radius: 32rpx 0 0 32rpx;
  overflow: hidden;
  animation: slide-in-right-menu 0.3s ease;
}

@keyframes slide-in-right-menu {
  from { transform: translateX(100%); }
  to { transform: translateX(0); }
}

.menu-header {
  padding: 48rpx 32rpx;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 16rpx;
}

.menu-avatar {
  width: 96rpx;
  height: 96rpx;
  border-radius: 50%;
  background: rgba(255, 255, 255, 0.3);
  display: flex;
  align-items: center;
  justify-content: center;
  border: 3rpx solid rgba(255, 255, 255, 0.5);
}

.menu-avatar-text {
  font-size: 40rpx;
  font-weight: bold;
  color: #fff;
}

.menu-title {
  font-size: 32rpx;
  font-weight: bold;
  color: #fff;
}

.menu-vip {
  background: rgba(255, 215, 0, 0.9);
  color: #333;
  font-size: 22rpx;
  font-weight: bold;
  padding: 6rpx 20rpx;
  border-radius: 20rpx;
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

.menu-item-icon {
  width: 56rpx;
  height: 56rpx;
  border-radius: 14rpx;
  display: flex;
  align-items: center;
  justify-content: center;
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
    height: 84rpx;
    font-size: 24rpx;
    gap: 8rpx;
    letter-spacing: 1rpx;
  }

  .btn-icon {
    font-size: 30rpx;
  }

  .num-ball {
    width: 72rpx;
    height: 72rpx;
  }

  .ball-number {
    font-size: 30rpx;
  }
}

@media screen and (min-width: 414px) {
  .bottom-actions {
    padding: 24rpx 48rpx;
  }

  .action-btn {
    height: 100rpx;
    font-size: 30rpx;
    max-width: 320rpx;
  }
}
</style>
