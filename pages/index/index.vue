<template>
  <view class="container">
    <!-- 顶部导航 -->
    <view class="header" :style="{ background: headerBg }">
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
            <view v-if="selectedGroup === lottery.id" class="tab-indicator" :style="{ background: currentGroupInfo.color }"></view>
          </view>
        </view>
        <view class="lottery-subtitle">{{ currentGroupInfo.description }}</view>
      </view>

      <!-- 用户状态 -->
      <view class="user-status-bar">
        <view v-if="userStore.isLoggedIn" class="user-info" @click="showUserMenu = true">
          <view class="user-avatar" :style="{ background: currentGroupInfo.gradient }">
            <text class="avatar-text">{{ userStore.userInfo.nickname?.charAt(0) || 'U' }}</text>
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

    <!-- 加载状态 -->
    <view v-if="isLoading" class="loading-section">
      <view class="loading-spinner">
        <view class="spinner"></view>
      </view>
      <text class="loading-text">数据加载中...</text>
    </view>

    <!-- 最新开奖数据 -->
    <view v-else class="current-data-section">
      <view class="section-header">
        <view class="section-title-wrapper">
          <view class="title-bar" :style="{ background: currentGroupInfo.color }"></view>
          <text class="section-title">最新数据</text>
        </view>
        <view class="refresh-btn" @click="refreshData">
          <text class="refresh-icon" :class="{ spinning: isRefreshing }">⟳</text>
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

        <!-- 数据展示 - 数字方块代替圆球 -->
        <view class="result-numbers">
          <view
            v-for="(num, index) in mainNumbers"
            :key="'main-' + index"
            class="num-block"
            :style="{ background: index < 3 ? currentGroupInfo.gradient : `linear-gradient(135deg, ${currentGroupInfo.color}CC, ${currentGroupInfo.color}88)` }"
            @click="highlightBlock(index)"
            :class="{ 'block-active': activeBlock === index }"
          >
            <text class="block-number">{{ num }}</text>
          </view>
          <view v-if="currentGroupInfo.hasSpecial" class="special-divider">
            <text class="divider-text">+</text>
          </view>
          <view
            v-if="currentGroupInfo.hasSpecial"
            class="num-block special"
            :style="{ background: 'linear-gradient(135deg, #6366F1, #4F46E5)' }"
            @click="highlightBlock('special')"
            :class="{ 'block-active': activeBlock === 'special' }"
          >
            <text class="block-number">{{ latestData.special_num }}</text>
          </view>
        </view>

        <view class="result-stats">
          <view class="stat-item" v-for="(stat, idx) in statsList" :key="idx">
            <view class="stat-icon-wrapper" :style="{ background: stat.bgColor }">
              <text class="stat-icon-text" :style="{ color: stat.color }">{{ stat.icon }}</text>
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
    <view v-if="!isLoading && analysisData" class="stats-section">
      <view class="section-header">
        <view class="section-title-wrapper">
          <view class="title-bar" :style="{ background: currentGroupInfo.color }"></view>
          <text class="section-title">数据分析</text>
        </view>
      </view>

      <view class="stats-grid">
        <view class="stat-card hot" @click="toggleCard('hot')">
          <view class="card-header">
            <view class="card-icon-wrapper hot-icon" :style="{ background: '#FEF3C7' }">
              <text class="card-icon-text" :style="{ color: '#D97706' }">HOT</text>
            </view>
            <text class="card-label">高频号码</text>
          </view>
          <view class="card-numbers">
            <view
              v-for="(item, index) in hotNumbers"
              :key="'hot-' + index"
              class="card-num"
            >
              <text class="num-value" :style="{ background: '#F59E0B' }">{{ item.num }}</text>
              <view class="num-bar" :style="{ width: (item.count / hotNumbers[0].count * 100) + '%' }"></view>
            </view>
          </view>
        </view>

        <view class="stat-card cold" @click="toggleCard('cold')">
          <view class="card-header">
            <view class="card-icon-wrapper cold-icon" :style="{ background: '#DBEAFE' }">
              <text class="card-icon-text" :style="{ color: '#2563EB' }">LOW</text>
            </view>
            <text class="card-label">低频号码</text>
          </view>
          <view class="card-numbers">
            <view
              v-for="(item, index) in coldNumbers"
              :key="'cold-' + index"
              class="card-num"
            >
              <text class="num-value" :style="{ background: '#3B82F6' }">{{ item.num }}</text>
              <view class="num-bar cold-bar" :style="{ width: Math.max(20, item.count * 15) + '%' }"></view>
            </view>
          </view>
        </view>
      </view>

      <!-- 号码分布 -->
      <view class="distribution-card">
        <view class="dist-header">
          <text class="dist-title">号码分布</text>
          <view class="dist-legend">
            <view class="dist-legend-item">
              <view class="legend-dot odd" :style="{ background: '#EF4444' }"></view>
              <text class="legend-label">奇数</text>
            </view>
            <view class="dist-legend-item">
              <view class="legend-dot even" :style="{ background: '#3B82F6' }"></view>
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
                  :style="{ width: item.value + '%', background: item.color }"
                ></view>
              </view>
              <text class="dist-value">{{ item.value }}%</text>
            </view>
            <text class="dist-label">{{ item.label }}</text>
          </view>
        </view>
      </view>
    </view>

    <!-- 历史记录 -->
    <view v-if="!isLoading && historyData.length > 0" class="history-section">
      <view class="section-header">
        <view class="section-title-wrapper">
          <view class="title-bar" :style="{ background: currentGroupInfo.color }"></view>
          <text class="section-title">历史数据</text>
        </view>
        <view class="more-btn" @click="scrollToHistory">
          <text class="more-text">更多</text>
          <text class="more-icon">›</text>
        </view>
      </view>
      <view class="history-list">
        <view
          v-for="(item, index) in displayHistory"
          :key="index"
          class="history-item"
        >
          <view class="history-left">
            <text class="history-session">{{ item.issue }}</text>
            <text class="history-date">{{ item.draw_date }}</text>
          </view>
          <view class="history-numbers">
            <view
              v-for="(num, i) in getMainNumbersFromData(item)"
              :key="i"
              class="mini-block"
              :style="{ background: currentGroupInfo.gradient }"
            >{{ num }}</view>
            <view
              v-if="currentGroupInfo.hasSpecial"
              class="mini-block special"
              :style="{ background: 'linear-gradient(135deg, #6366F1, #4F46E5)' }"
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
    <view v-if="!isLoading" class="bottom-actions">
      <view class="action-btn detailed" :style="{ background: currentGroupInfo.bgColor, borderColor: currentGroupInfo.color }" @click="generateReport('detailed')">
        <text class="btn-icon" :style="{ color: currentGroupInfo.color }">&#x25A0;</text>
        <text class="btn-text" :style="{ color: currentGroupInfo.color }">详细报告</text>
      </view>
      <view class="action-btn optimal" :style="{ background: currentGroupInfo.gradient }" @click="generateReport('optimal')">
        <text class="btn-icon">&#x25B6;</text>
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
          <view class="menu-vip" v-if="userStore.isPaid">VIP</view>
        </view>
        <view class="menu-list">
          <view v-if="!userStore.isPaid" class="menu-item" @click="handleUpgrade">
            <view class="menu-item-icon" :style="{ background: '#FEF3C7' }">
              <text style="font-size: 32rpx; color: #D97706;">&#x2605;</text>
            </view>
            <text class="menu-text">升级VIP会员</text>
            <text class="menu-arrow">&#x203A;</text>
          </view>
          <view class="menu-item" @click="handleLogout">
            <view class="menu-item-icon" :style="{ background: '#FEE2E2' }">
              <text style="font-size: 32rpx; color: #DC2626;">&#x2715;</text>
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
import { lotteryTypes, prizeLevels } from '@/data/lotteryData.js'
import { api, checkApiStatus, setApiStatus } from '@/api/index.js'
import { useUserStore } from '@/store/user'
import { processHotColdNumbers } from '@/utils/index.js'
import LoginModal from '@/components/LoginModal.vue'

const userStore = useUserStore()
const selectedGroup = ref('qixingcai')
const showLoginModal = ref(false)
const showUserMenu = ref(false)
const isRefreshing = ref(false)
const isLoading = ref(true)
const activeBlock = ref(-1)
const hoveredRule = ref(-1)

const historyData = ref([])
const analysisData = ref(null)
const hotColdData = ref({ hotNumbers: [], coldNumbers: [] })

const currentGroupInfo = computed(() => {
  return lotteryTypes.find(l => l.id === selectedGroup.value) || lotteryTypes[0]
})

const headerBg = computed(() => currentGroupInfo.value.gradient)

const latestData = computed(() => {
  return historyData.value[0] || {}
})

const mainNumbers = computed(() => {
  return getMainNumbersFromData(latestData.value)
})

const hotNumbers = computed(() => {
  return hotColdData.value.hotNumbers.slice(0, 5)
})

const coldNumbers = computed(() => {
  return hotColdData.value.coldNumbers.slice(0, 5)
})

const distribution = computed(() => {
  return analysisData.value?.distribution || {
    oddRate: '50',
    evenRate: '50',
    smallRate: '50',
    largeRate: '50'
  }
})

const distributionList = computed(() => [
  { type: 'odd', label: '奇数', value: distribution.value.oddRate, color: '#EF4444' },
  { type: 'even', label: '偶数', value: distribution.value.evenRate, color: '#3B82F6' },
  { type: 'small', label: '小号', value: distribution.value.smallRate, color: '#8B5CF6' },
  { type: 'large', label: '大号', value: distribution.value.largeRate, color: '#10B981' }
])

const rulesList = computed(() => {
  return prizeLevels[selectedGroup.value] || []
})

const displayHistory = computed(() => {
  return historyData.value.slice(1, 6)
})

const statsList = computed(() => [
  {
    icon: 'Σ',
    label: '和值',
    value: latestData.value.hezhi || '-',
    color: latestData.value.hezhi_type === '奇' ? '#EF4444' : '#3B82F6',
    bgColor: latestData.value.hezhi_type === '奇' ? '#FEE2E2' : '#DBEAFE'
  },
  {
    icon: '◇',
    label: '奇偶',
    value: latestData.value.odd_even_ratio || '-',
    color: '#8B5CF6',
    bgColor: '#F5F3FF'
  },
  {
    icon: '↔',
    label: '跨度',
    value: latestData.value.span || '-',
    color: '#10B981',
    bgColor: '#D1FAE5'
  }
])

function getMainNumbersFromData(item) {
  if (!item) return []
  const numCount = currentGroupInfo.value.numberCount
  const nums = []
  for (let i = 1; i <= numCount; i++) {
    if (item[`num${i}`] !== undefined) {
      nums.push(item[`num${i}`])
    }
  }
  return nums
}

async function fetchData() {
  isLoading.value = true
  
  try {
    const isAvailable = await checkApiStatus()
    if (!isAvailable) {
      setApiStatus(false)
      uni.reLaunch({ url: '/pages/system-upgrade/system-upgrade' })
      return
    }

    const [dataResult, analysisResult] = await Promise.all([
      api.data.list({ page: 1, page_size: 20 }),
      api.analysis.comprehensive()
    ])

    if (dataResult.success && dataResult.data?.items) {
      historyData.value = dataResult.data.items
    }

    if (analysisResult.success && analysisResult.data) {
      const { hotNumbers, coldNumbers } = processHotColdNumbers(
        analysisResult.data.position_analysis_summary
      )
      
      hotColdData.value = { hotNumbers, coldNumbers }
      
      analysisData.value = {
        distribution: {
          oddRate: analysisResult.data.hezhi?.avg_hezhi ? '50' : '50',
          evenRate: analysisResult.data.hezhi?.avg_hezhi ? '50' : '50',
          smallRate: '50',
          largeRate: '50'
        }
      }
    }
  } catch (error) {
    console.error('fetchData error:', error)
    uni.showToast({
      title: '数据获取失败',
      icon: 'none'
    })
  } finally {
    isLoading.value = false
  }
}

function switchLottery(id) {
  if (selectedGroup.value === id) return
  selectedGroup.value = id
  fetchData()
  uni.showToast({
    title: `已切换至${currentGroupInfo.value.name}`,
    icon: 'none',
    duration: 1500
  })
}

function highlightBlock(index) {
  activeBlock.value = index
  setTimeout(() => {
    activeBlock.value = -1
  }, 200)
}

function toggleCard(type) {
  uni.vibrateShort && uni.vibrateShort({ type: 'light' })
}

async function refreshData() {
  isRefreshing.value = true
  await fetchData()
  isRefreshing.value = false
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

onMounted(() => {
  userStore.initUserStatus()
  fetchData()
})
</script>

<style lang="scss">
.container {
  min-height: 100vh;
  background: #F8FAFC;
  padding-bottom: 140rpx;
}

/* 头部 */
.header {
  padding: 100rpx 30rpx 40rpx;
  position: relative;
}

.header-content {
  position: relative;
  z-index: 2;
}

/* 标签切换 */
.lottery-tabs {
  display: flex;
  gap: 20rpx;
  margin-bottom: 16rpx;
}

.tab-item {
  display: flex;
  align-items: center;
  gap: 12rpx;
  padding: 16rpx 32rpx;
  border-radius: 16rpx;
  background: rgba(255, 255, 255, 0.2);
  transition: all 0.3s ease;
  position: relative;
}

.tab-item.active {
  background: rgba(255, 255, 255, 0.35);
  transform: scale(1.02);
}

.tab-icon {
  font-size: 28rpx;
  font-weight: bold;
  color: #fff;
}

.tab-name {
  font-size: 28rpx;
  font-weight: bold;
  color: #fff;
}

.tab-indicator {
  position: absolute;
  bottom: -6rpx;
  left: 50%;
  transform: translateX(-50%);
  width: 32rpx;
  height: 6rpx;
  border-radius: 3rpx;
}

.lottery-subtitle {
  font-size: 24rpx;
  color: rgba(255, 255, 255, 0.8);
}

/* 用户状态 */
.user-status-bar {
  position: absolute;
  top: 60rpx;
  right: 30rpx;
  z-index: 3;
}

.user-info {
  display: flex;
  align-items: center;
}

.user-avatar {
  width: 56rpx;
  height: 56rpx;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  box-shadow: 0 4rpx 12rpx rgba(0, 0, 0, 0.15);
}

.avatar-text {
  font-size: 24rpx;
  font-weight: bold;
  color: #fff;
}

.login-hint {
  display: flex;
  align-items: center;
  gap: 10rpx;
  background: rgba(255, 255, 255, 0.2);
  padding: 10rpx 20rpx;
  border-radius: 30rpx;
}

.login-avatar-placeholder {
  width: 44rpx;
  height: 44rpx;
  border-radius: 50%;
  border: 2rpx dashed rgba(255, 255, 255, 0.6);
  display: flex;
  align-items: center;
  justify-content: center;
}

.placeholder-icon {
  font-size: 24rpx;
  color: rgba(255, 255, 255, 0.8);
}

.login-text {
  font-size: 24rpx;
  color: #fff;
}

/* 加载状态 */
.loading-section {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 120rpx 0;
}

.loading-spinner {
  width: 80rpx;
  height: 80rpx;
  margin-bottom: 32rpx;
}

.spinner {
  width: 100%;
  height: 100%;
  border: 6rpx solid rgba(59, 130, 246, 0.1);
  border-top-color: #3B82F6;
  border-radius: 50%;
  animation: spin 1s linear infinite;
}

@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}

.loading-text {
  font-size: 28rpx;
  color: #9CA3AF;
}

/* 区块通用样式 */
.section-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 24rpx 30rpx;
}

.section-title-wrapper {
  display: flex;
  align-items: center;
  gap: 12rpx;
}

.title-bar {
  width: 8rpx;
  height: 32rpx;
  border-radius: 4rpx;
}

.section-title {
  font-size: 32rpx;
  font-weight: bold;
  color: #1F2937;
}

.refresh-btn {
  width: 64rpx;
  height: 64rpx;
  border-radius: 50%;
  background: #F3F4F6;
  display: flex;
  align-items: center;
  justify-content: center;
}

.refresh-icon {
  font-size: 32rpx;
  color: #6B7280;
  transition: transform 0.5s ease;
}

.refresh-icon.spinning {
  animation: spin 0.8s linear infinite;
}

/* 最新数据区块 */
.current-data-section {
  padding: 0 30rpx;
}

.latest-result {
  background: #fff;
  border-radius: 24rpx;
  padding: 32rpx;
  box-shadow: 0 4rpx 20rpx rgba(0, 0, 0, 0.05);
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
  font-size: 24rpx;
  color: #6B7280;
}

.result-session {
  font-size: 36rpx;
  font-weight: bold;
  color: #1F2937;
}

.result-date {
  font-size: 24rpx;
  color: #9CA3AF;
}

/* 数字方块 */
.result-numbers {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 16rpx;
  margin-bottom: 32rpx;
}

.num-block {
  width: 88rpx;
  height: 88rpx;
  border-radius: 16rpx;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all 0.2s ease;
  position: relative;
}

.num-block.special {
  width: 72rpx;
  height: 72rpx;
}

.num-block:active,
.num-block.block-active {
  transform: scale(1.1);
  box-shadow: 0 8rpx 24rpx rgba(0, 0, 0, 0.2);
}

.block-number {
  font-size: 36rpx;
  font-weight: bold;
  color: #fff;
}

.num-block.special .block-number {
  font-size: 28rpx;
}

.special-divider {
  width: 48rpx;
  height: 48rpx;
  display: flex;
  align-items: center;
  justify-content: center;
}

.divider-text {
  font-size: 24rpx;
  color: #9CA3AF;
}

/* 统计信息 */
.result-stats {
  display: flex;
  justify-content: space-around;
}

.stat-item {
  display: flex;
  align-items: center;
  gap: 12rpx;
}

.stat-icon-wrapper {
  width: 48rpx;
  height: 48rpx;
  border-radius: 12rpx;
  display: flex;
  align-items: center;
  justify-content: center;
}

.stat-icon-text {
  font-size: 24rpx;
  font-weight: bold;
}

.stat-info {
  display: flex;
  flex-direction: column;
  gap: 4rpx;
}

.stat-label {
  font-size: 22rpx;
  color: #9CA3AF;
}

.stat-value {
  font-size: 28rpx;
  font-weight: bold;
}

/* 数据统计区域 */
.stats-section {
  padding: 0 30rpx;
}

.stats-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 20rpx;
  margin-bottom: 20rpx;
}

.stat-card {
  background: #fff;
  border-radius: 20rpx;
  padding: 24rpx;
  box-shadow: 0 4rpx 20rpx rgba(0, 0, 0, 0.05);
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

.card-icon-text {
  font-size: 20rpx;
  font-weight: bold;
}

.card-label {
  font-size: 26rpx;
  font-weight: bold;
  color: #1F2937;
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
}

.num-value {
  width: 56rpx;
  height: 56rpx;
  border-radius: 12rpx;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 28rpx;
  font-weight: bold;
  color: #fff;
}

.num-bar {
  flex: 1;
  height: 8rpx;
  background: #FDE68A;
  border-radius: 4rpx;
  transition: width 0.5s ease;
}

.num-bar.cold-bar {
  background: #BFDBFE;
}

/* 号码分布卡片 */
.distribution-card {
  background: #fff;
  border-radius: 20rpx;
  padding: 24rpx;
  box-shadow: 0 4rpx 20rpx rgba(0, 0, 0, 0.05);
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
  color: #1F2937;
}

.dist-legend {
  display: flex;
  gap: 24rpx;
}

.dist-legend-item {
  display: flex;
  align-items: center;
  gap: 8rpx;
}

.legend-dot {
  width: 16rpx;
  height: 16rpx;
  border-radius: 50%;
}

.legend-label {
  font-size: 22rpx;
  color: #6B7280;
}

.distribution-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 24rpx;
}

.dist-item {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 12rpx;
}

.dist-bar-container {
  width: 100%;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8rpx;
}

.dist-bar-wrapper {
  width: 60rpx;
  height: 80rpx;
  background: #F3F4F6;
  border-radius: 8rpx;
  position: relative;
  display: flex;
  align-items: flex-end;
}

.dist-bar {
  width: 100%;
  border-radius: 8rpx;
  transition: height 0.5s ease;
}

.dist-value {
  font-size: 22rpx;
  color: #6B7280;
}

.dist-label {
  font-size: 24rpx;
  color: #374151;
}

/* 奖项规则区域 */
.rules-section {
  padding: 0 30rpx;
  margin-top: 20rpx;
}

.rules-table {
  background: #fff;
  border-radius: 20rpx;
  overflow: hidden;
  box-shadow: 0 4rpx 20rpx rgba(0, 0, 0, 0.05);
}

.rules-header-row {
  display: flex;
  padding: 24rpx 20rpx;
}

.rules-col-level {
  flex: 1;
  font-size: 26rpx;
  font-weight: bold;
  color: #fff;
  text-align: center;
}

.rules-col-match {
  flex: 3;
  font-size: 26rpx;
  font-weight: bold;
  color: #fff;
  text-align: center;
}

.rules-col-prize {
  flex: 2;
  font-size: 26rpx;
  font-weight: bold;
  color: #fff;
  text-align: center;
}

.rules-item-row {
  display: flex;
  padding: 20rpx 20rpx;
  border-bottom: 1rpx solid #F3F4F6;
  transition: background 0.2s ease;
}

.rules-item-row:last-child {
  border-bottom: none;
}

.rules-item-row.highlight-row {
  background: #F9FAFB;
}

.rules-level {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 8rpx 16rpx;
  border-radius: 8rpx;
}

.rules-level text {
  font-size: 24rpx;
  font-weight: bold;
}

.rules-match {
  flex: 3;
  font-size: 24rpx;
  color: #374151;
  display: flex;
  align-items: center;
  justify-content: center;
}

.rules-prize {
  flex: 2;
  font-size: 24rpx;
  font-weight: bold;
  display: flex;
  align-items: center;
  justify-content: center;
}

/* 历史记录区域 */
.history-section {
  padding: 0 30rpx;
  margin-top: 20rpx;
}

.more-btn {
  display: flex;
  align-items: center;
  gap: 8rpx;
}

.more-text {
  font-size: 24rpx;
  color: #6B7280;
}

.more-icon {
  font-size: 28rpx;
  color: #6B7280;
}

.history-list {
  background: #fff;
  border-radius: 20rpx;
  padding: 16rpx;
  box-shadow: 0 4rpx 20rpx rgba(0, 0, 0, 0.05);
}

.history-item {
  display: flex;
  align-items: center;
  padding: 20rpx 16rpx;
  border-bottom: 1rpx solid #F3F4F6;
}

.history-item:last-child {
  border-bottom: none;
}

.history-left {
  width: 120rpx;
  display: flex;
  flex-direction: column;
  gap: 8rpx;
}

.history-session {
  font-size: 26rpx;
  font-weight: bold;
  color: #1F2937;
}

.history-date {
  font-size: 22rpx;
  color: #9CA3AF;
}

.history-numbers {
  flex: 1;
  display: flex;
  justify-content: center;
  gap: 8rpx;
}

.mini-block {
  width: 48rpx;
  height: 48rpx;
  border-radius: 10rpx;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 22rpx;
  font-weight: bold;
  color: #fff;
}

.mini-block.special {
  width: 40rpx;
  height: 40rpx;
  font-size: 18rpx;
}

.history-info {
  width: 100rpx;
  display: flex;
  justify-content: flex-end;
}

.info-badge {
  padding: 8rpx 16rpx;
  border-radius: 20rpx;
}

/* 底部操作栏 */
.bottom-actions {
  position: fixed;
  bottom: 0;
  left: 0;
  right: 0;
  display: flex;
  gap: 20rpx;
  padding: 20rpx 30rpx;
  padding-bottom: calc(20rpx + env(safe-area-inset-bottom));
  background: #fff;
  box-shadow: 0 -4rpx 20rpx rgba(0, 0, 0, 0.05);
}

.action-btn {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 12rpx;
  height: 88rpx;
  border-radius: 44rpx;
  border: 2rpx solid transparent;
  transition: all 0.2s ease;
}

.action-btn:active {
  transform: scale(0.98);
  opacity: 0.9;
}

.btn-icon {
  font-size: 28rpx;
}

.btn-text {
  font-size: 28rpx;
  font-weight: bold;
  color: #fff;
}

.action-btn.detailed .btn-text {
  color: inherit;
}

/* 用户菜单 */
.user-menu-overlay {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background: rgba(0, 0, 0, 0.5);
  z-index: 1000;
  display: flex;
  align-items: flex-end;
}

.user-menu {
  width: 100%;
  background: #fff;
  border-radius: 32rpx 32rpx 0 0;
  overflow: hidden;
}

.menu-header {
  padding: 40rpx;
  text-align: center;
}

.menu-avatar {
  width: 100rpx;
  height: 100rpx;
  border-radius: 50%;
  background: rgba(255, 255, 255, 0.3);
  display: flex;
  align-items: center;
  justify-content: center;
  margin: 0 auto 16rpx;
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
  display: block;
  margin-bottom: 8rpx;
}

.menu-vip {
  display: inline-block;
  padding: 6rpx 20rpx;
  background: rgba(255, 255, 255, 0.3);
  border-radius: 20rpx;
  font-size: 22rpx;
  color: #fff;
  font-weight: bold;
}

.menu-list {
  padding: 20rpx;
}

.menu-item {
  display: flex;
  align-items: center;
  gap: 20rpx;
  padding: 24rpx 20rpx;
  border-radius: 16rpx;
  transition: background 0.2s ease;
}

.menu-item:active {
  background: #F3F4F6;
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
  color: #374151;
}

.menu-arrow {
  font-size: 32rpx;
  color: #9CA3AF;
}
</style>
