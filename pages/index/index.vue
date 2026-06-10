<template>
  <view class="container">
    <view class="header">
      <view class="header-content">
        <text class="header-title">📊 DATA ANALYSIS</text>
        <text class="header-subtitle">PROFESSIONAL DATA ANALYSIS PLATFORM</text>
      </view>
    </view>

    <view class="data-group-section">
      <text class="section-title">SELECT DATA GROUP</text>
      <view class="data-group-list">
        <view 
          v-for="group in lotteryTypes" 
          :key="group.id"
          class="data-group-item"
          :class="{ active: selectedGroup === group.id }"
          :style="{ borderColor: selectedGroup === group.id ? group.color : 'transparent' }"
          @click="selectGroup(group.id)"
        >
          <view class="group-icon" :style="{ backgroundColor: group.bgColor }">
            <text>{{ group.icon }}</text>
          </view>
          <view class="group-info">
            <text class="group-name">{{ group.name }}</text>
            <text class="group-desc">{{ group.description }}</text>
          </view>
          <view v-if="selectedGroup === group.id" class="check-icon">✓</view>
        </view>
      </view>
    </view>

    <view class="current-data-section">
      <view class="section-header">
        <text class="section-title">{{ currentGroupInfo.name }} DATA RESULT</text>
        <text class="refresh-btn" @click="refreshData">🔄 REFRESH</text>
      </view>
      
      <view class="latest-result">
        <view class="result-header">
          <text class="result-session">SESSION {{ latestData.issue }}</text>
          <text class="result-date">{{ latestData.date }}</text>
        </view>
        <view class="result-numbers">
          <template v-if="selectedGroup === 'dataGroupA'">
            <view class="main-numbers">
              <view v-for="(num, index) in latestData.group1" :key="'main-' + index" class="num-box primary">
                {{ num }}
              </view>
            </view>
            <view class="secondary-numbers">
              <view class="num-box secondary">{{ latestData.group2 }}</view>
            </view>
          </template>
          <template v-else-if="selectedGroup === 'dataGroupB'">
            <view class="main-numbers">
              <view v-for="(num, index) in latestData.group1" :key="'main-' + index" class="num-box primary">
                {{ num }}
              </view>
            </view>
            <view class="secondary-numbers">
              <view v-for="(num, index) in latestData.group2" :key="'sec-' + index" class="num-box secondary">{{ num }}</view>
            </view>
          </template>
          <template v-else-if="selectedGroup === 'dataGroupC'">
            <view class="triple-numbers">
              <view class="triple-item">
                <text class="triple-label">H</text>
                <view class="num-box triple">{{ latestData.num1 }}</view>
              </view>
              <view class="triple-item">
                <text class="triple-label">T</text>
                <view class="num-box triple">{{ latestData.num2 }}</view>
              </view>
              <view class="triple-item">
                <text class="triple-label">U</text>
                <view class="num-box triple">{{ latestData.num3 }}</view>
              </view>
            </view>
          </template>
        </view>
      </view>
    </view>

    <view class="stats-section">
      <view class="section-header">
        <text class="section-title">DATA STATISTICS</text>
      </view>
      
      <view class="stats-grid">
        <view class="stat-card hot">
          <text class="stat-icon">🔥</text>
          <text class="stat-label">HOT NUMBERS</text>
          <view class="stat-values">
            <view v-for="(item, index) in hotNumbers" :key="'hot-' + index" class="stat-num">{{ item.num }}</view>
          </view>
          <view class="stat-legend">
            <text class="legend-text">FREQUENCY TOP 5</text>
          </view>
        </view>
        <view class="stat-card cold">
          <text class="stat-icon">❄️</text>
          <text class="stat-label">COLD NUMBERS</text>
          <view class="stat-values">
            <view v-for="(item, index) in coldNumbers" :key="'cold-' + index" class="stat-num">{{ item.num }}</view>
          </view>
          <view class="stat-legend">
            <text class="legend-text">LOW FREQUENCY</text>
          </view>
        </view>
      </view>
      
      <view class="distribution-card">
        <text class="card-title">📈 NUMBER DISTRIBUTION</text>
        <view class="distribution-grid">
          <view class="dist-item">
            <view class="dist-bar-container">
              <view class="dist-bar-wrapper">
                <view class="dist-bar odd" :style="{ width: distribution.oddRate + '%' }"></view>
              </view>
              <text class="dist-value">{{ distribution.oddRate }}%</text>
            </view>
            <text class="dist-label">ODD</text>
          </view>
          <view class="dist-item">
            <view class="dist-bar-container">
              <view class="dist-bar-wrapper">
                <view class="dist-bar even" :style="{ width: distribution.evenRate + '%' }"></view>
              </view>
              <text class="dist-value">{{ distribution.evenRate }}%</text>
            </view>
            <text class="dist-label">EVEN</text>
          </view>
          <view class="dist-item">
            <view class="dist-bar-container">
              <view class="dist-bar-wrapper">
                <view class="dist-bar small" :style="{ width: distribution.smallRate + '%' }"></view>
              </view>
              <text class="dist-value">{{ distribution.smallRate }}%</text>
            </view>
            <text class="dist-label">SMALL</text>
          </view>
          <view class="dist-item">
            <view class="dist-bar-container">
              <view class="dist-bar-wrapper">
                <view class="dist-bar large" :style="{ width: distribution.largeRate + '%' }"></view>
              </view>
              <text class="dist-value">{{ distribution.largeRate }}%</text>
            </view>
            <text class="dist-label">LARGE</text>
          </view>
        </view>
      </view>
    </view>

    <view class="rules-section">
      <view class="section-header">
        <text class="section-title">📋 SCORING RULES</text>
      </view>
      <view class="rules-table">
        <view class="rules-header-row">
          <text class="rules-col-level">LEVEL</text>
          <text class="rules-col-match">MATCH</text>
          <text class="rules-col-prize">PRIZE</text>
          <text class="rules-col-prob">PROBABILITY</text>
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
        <text class="section-title">HISTORY RECORDS</text>
        <text class="more-btn" @click="scrollToHistory">VIEW MORE</text>
      </view>
      <view class="history-list">
        <view v-for="(item, index) in displayHistory" :key="index" class="history-item">
          <text class="history-session">{{ item.issue }}</text>
          <view class="history-numbers">
            <template v-if="selectedGroup === 'dataGroupA'">
              <view v-for="(num, i) in item.group1" :key="i" class="mini-num primary">{{ num }}</view>
              <view class="mini-num secondary">{{ item.group2 }}</view>
            </template>
            <template v-else-if="selectedGroup === 'dataGroupB'">
              <view v-for="(num, i) in item.group1" :key="i" class="mini-num primary">{{ num }}</view>
              <view v-for="(num, i) in item.group2" :key="i" class="mini-num secondary">{{ num }}</view>
            </template>
            <template v-else-if="selectedGroup === 'dataGroupC'">
              <view class="mini-num triple">{{ item.num1 }}</view>
              <view class="mini-num triple">{{ item.num2 }}</view>
              <view class="mini-num triple">{{ item.num3 }}</view>
            </template>
          </view>
          <text class="history-date">{{ item.date }}</text>
        </view>
      </view>
    </view>

    <view class="bottom-actions">
      <view class="action-btn detailed" @click="generateReport('detailed')">
        <text class="btn-icon">📋</text>
        <text class="btn-text">DETAILED</text>
      </view>
      <view class="action-btn optimal" @click="generateReport('optimal')">
        <text class="btn-icon">🎯</text>
        <text class="btn-text">OPTIMAL</text>
      </view>
    </view>
  </view>
</template>

<script setup>
import { ref, computed } from 'vue'
import { lotteryTypes, lotteryHistory, prizeLevels } from '../../data/lotteryData.js'
import { getHotNumbers, getColdNumbers, analyzeNumberDistribution } from '../../utils/index.js'

const selectedGroup = ref('dataGroupA')

const currentGroupInfo = computed(() => {
  return lotteryTypes.find(l => l.id === selectedGroup.value) || lotteryTypes[0]
})

const historyData = computed(() => {
  return lotteryHistory[selectedGroup.value] || []
})

const latestData = computed(() => {
  return historyData.value[0] || {}
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

function selectGroup(groupId) {
  selectedGroup.value = groupId
}

function refreshData() {
  uni.showToast({
    title: 'DATA REFRESHED',
    icon: 'success'
  })
}

function scrollToHistory() {
  uni.showToast({
    title: 'ALL RECORDS SHOWN',
    icon: 'none'
  })
}

function generateReport(type) {
  uni.navigateTo({
    url: `/pages/report/report?type=${type}&group=${selectedGroup.value}`
  })
}
</script>

<style lang="scss">
.container {
  min-height: 100vh;
  background: linear-gradient(180deg, #1E88E5 0%, #F5F7FA 30%);
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
  color: #1E88E5;
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

.data-group-section {
  padding: 0 30rpx;
  margin-bottom: 30rpx;
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

.refresh-btn, .more-btn {
  font-size: 24rpx;
  color: #1E88E5;
  letter-spacing: 1rpx;
}

.data-group-list {
  display: flex;
  flex-direction: column;
  gap: 20rpx;
}

.data-group-item {
  background: #fff;
  border-radius: 16rpx;
  padding: 24rpx;
  display: flex;
  align-items: center;
  gap: 20rpx;
  border: 3rpx solid transparent;
  transition: all 0.3s;
  box-shadow: 0 4rpx 16rpx rgba(0, 0, 0, 0.05);
}

.data-group-item.active {
  border-width: 3rpx;
  box-shadow: 0 4rpx 20rpx rgba(30, 136, 229, 0.2);
}

.group-icon {
  width: 80rpx;
  height: 80rpx;
  border-radius: 16rpx;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 40rpx;
}

.group-info {
  flex: 1;
}

.group-name {
  font-size: 30rpx;
  font-weight: bold;
  color: #333;
  display: block;
  letter-spacing: 1rpx;
}

.group-desc {
  font-size: 22rpx;
  color: #999;
  margin-top: 8rpx;
  display: block;
}

.check-icon {
  width: 48rpx;
  height: 48rpx;
  border-radius: 50%;
  background: #1E88E5;
  color: #fff;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 28rpx;
  font-weight: bold;
}

.current-data-section, .stats-section, .rules-section, .history-section {
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
  background: linear-gradient(145deg, #1E88E5, #1565C0);
}

.num-box.secondary {
  background: linear-gradient(145deg, #43A047, #2E7D32);
}

.num-box.triple {
  background: linear-gradient(145deg, #7B1FA2, #5E1B89);
  width: 80rpx;
  height: 80rpx;
}

.main-numbers, .secondary-numbers {
  display: flex;
  gap: 16rpx;
}

.secondary-numbers {
  margin-left: 20rpx;
}

.triple-numbers {
  display: flex;
  gap: 30rpx;
}

.triple-item {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 12rpx;
}

.triple-label {
  font-size: 22rpx;
  color: #666;
  font-weight: bold;
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
  background: linear-gradient(145deg, #1E88E5, #1565C0);
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
  background: linear-gradient(90deg, #1E88E5, #64B5F6);
}

.dist-bar.even {
  background: linear-gradient(90deg, #43A047, #81C784);
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
  background: linear-gradient(135deg, #1E88E5, #1565C0);
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

.rules-col-level { flex: 0 0 140rpx; }
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
  background: #FFF8E1;
}

.rules-item-row:hover {
  background: #F0F7FF;
}

.rules-level {
  flex: 0 0 140rpx;
  font-size: 24rpx;
  font-weight: bold;
  color: #1E88E5;
  background: rgba(30, 136, 229, 0.1);
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
  background: #1E88E5;
}

.mini-num.secondary {
  background: #43A047;
}

.mini-num.triple {
  background: #7B1FA2;
}

.history-date {
  font-size: 22rpx;
  color: #999;
  width: 120rpx;
  text-align: right;
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
  text-transform: uppercase;
  overflow: hidden;
  box-shadow: 0 4rpx 16rpx rgba(0, 0, 0, 0.15);
  transition: all 0.3s ease;
}

.action-btn:active {
  transform: scale(0.96);
  box-shadow: 0 2rpx 8rpx rgba(0, 0, 0, 0.1);
}

.action-btn.detailed {
  background: linear-gradient(135deg, #1E88E5, #1565C0);
}

.action-btn.optimal {
  background: linear-gradient(135deg, #43A047, #2E7D32);
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

/* 响应式适配 - 小屏幕设备 */
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

/* 响应式适配 - 大屏幕设备 */
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
