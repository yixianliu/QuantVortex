<template>
  <view class="container">
    <view class="header">
      <view class="header-content">
        <view class="back-btn" @click="goBack">
          <text>←</text>
        </view>
        <text class="header-title">{{ reportType === 'detailed' ? '📋 DETAILED REPORT' : '🎯 OPTIMAL REPORT' }}</text>
        <view class="placeholder"></view>
      </view>
    </view>

    <view class="report-content">
      <view v-if="reportData.lotteryType" class="report-inner">
        <view class="report-header">
          <view class="header-info">
            <text class="report-type">{{ currentGroupInfo.name }}</text>
            <text class="generate-time">GENERATED: {{ reportData.generateTime }}</text>
          </view>
          <view class="report-badge" :class="reportType">
            {{ reportType === 'detailed' ? 'FULL ANALYSIS' : 'BEST CHOICE' }}
          </view>
        </view>

        <view class="summary-card">
          <text class="card-title">📊 DATA SUMMARY</text>
          <view class="summary-grid">
            <view class="summary-item">
              <text class="summary-value">{{ reportData.totalCount || 0 }}</text>
              <text class="summary-label">TOTAL</text>
            </view>
            <view class="summary-item">
              <text class="summary-value">{{ reportData.analyzedCount || 0 }}</text>
              <text class="summary-label">ANALYZED</text>
            </view>
            <view class="summary-item">
              <text class="summary-value">{{ reportData.accuracy || 0 }}%</text>
              <text class="summary-label">ACCURACY</text>
            </view>
            <view class="summary-item">
              <text class="summary-value">{{ reportData.confidence || 0 }}%</text>
              <text class="summary-label">CONFIDENCE</text>
            </view>
          </view>
        </view>

        <view class="analysis-card">
          <text class="card-title">🔥 HOT NUMBERS</text>
          <view class="analysis-content">
            <view class="number-list hot">
              <view v-for="(item, index) in reportData.analysis?.hotNumbers || []" :key="index" class="number-item">
                <view class="number-circle">{{ item.num }}</view>
                <view class="number-info">
                  <text class="number-count">FREQ: {{ item.count }}</text>
                  <text class="number-rate">{{ item.rate }}%</text>
                </view>
              </view>
            </view>
          </view>
        </view>

        <view class="analysis-card">
          <text class="card-title">❄️ COLD NUMBERS</text>
          <view class="analysis-content">
            <view class="number-list cold">
              <view v-for="(item, index) in reportData.analysis?.coldNumbers || []" :key="index" class="number-item">
                <view class="number-circle">{{ item.num }}</view>
                <view class="number-info">
                  <text class="number-count">FREQ: {{ item.count }}</text>
                  <text class="number-rate">{{ item.rate }}%</text>
                </view>
              </view>
            </view>
          </view>
        </view>

        <view class="distribution-card">
          <text class="card-title">📈 DISTRIBUTION</text>
          <view class="dist-section">
            <text class="dist-title">ODD / EVEN</text>
            <view class="dist-chart">
              <view class="dist-bar-wrapper">
                <view class="dist-bar odd" :style="{ width: (reportData.analysis?.distribution?.oddRate || 0) + '%' }"></view>
                <view class="dist-bar even" :style="{ width: (reportData.analysis?.distribution?.evenRate || 0) + '%' }"></view>
              </view>
              <view class="dist-labels">
                <text>ODD {{ reportData.analysis?.distribution?.oddRate || 0 }}%</text>
                <text>EVEN {{ reportData.analysis?.distribution?.evenRate || 0 }}%</text>
              </view>
            </view>
          </view>
          <view class="dist-section">
            <text class="dist-title">SMALL / LARGE</text>
            <view class="dist-chart">
              <view class="dist-bar-wrapper">
                <view class="dist-bar small" :style="{ width: (reportData.analysis?.distribution?.smallRate || 0) + '%' }"></view>
                <view class="dist-bar large" :style="{ width: (reportData.analysis?.distribution?.largeRate || 0) + '%' }"></view>
              </view>
              <view class="dist-labels">
                <text>SMALL {{ reportData.analysis?.distribution?.smallRate || 0 }}%</text>
                <text>LARGE {{ reportData.analysis?.distribution?.largeRate || 0 }}%</text>
              </view>
            </view>
          </view>
        </view>

        <view class="recommend-card">
          <view class="card-header">
            <text class="card-title">🎯 RECOMMENDED</text>
            <text class="recommend-tip">ANALYSIS RESULT</text>
          </view>
          <view class="recommend-numbers">
            <template v-if="selectedGroup === 'dataGroupA'">
              <view class="num-group">
                <text class="group-label">GROUP 1</text>
                <view class="num-row">
                  <view v-for="(num, index) in reportData.recommendedNumbers?.group1 || []" :key="index" class="num-box primary">
                    {{ num }}
                  </view>
                </view>
              </view>
              <view class="num-group">
                <text class="group-label">GROUP 2</text>
                <view class="num-row">
                  <view class="num-box secondary">{{ reportData.recommendedNumbers?.group2 || '-' }}</view>
                </view>
              </view>
            </template>
            <template v-else-if="selectedGroup === 'dataGroupB'">
              <view class="num-group">
                <text class="group-label">GROUP 1</text>
                <view class="num-row">
                  <view v-for="(num, index) in reportData.recommendedNumbers?.group1 || []" :key="index" class="num-box primary">
                    {{ num }}
                  </view>
                </view>
              </view>
              <view class="num-group">
                <text class="group-label">GROUP 2</text>
                <view class="num-row">
                  <view v-for="(num, index) in reportData.recommendedNumbers?.group2 || []" :key="index" class="num-box secondary">{{ num }}</view>
                </view>
              </view>
            </template>
            <template v-else-if="selectedGroup === 'dataGroupC'">
              <view class="num-group">
                <text class="group-label">TRIPLE CODE</text>
                <view class="num-row">
                  <view class="triple-num-box">
                    <text class="triple-label">H</text>
                    <view class="num-box triple">{{ reportData.recommendedNumbers?.num1 ?? '-' }}</view>
                  </view>
                  <view class="triple-num-box">
                    <text class="triple-label">T</text>
                    <view class="num-box triple">{{ reportData.recommendedNumbers?.num2 ?? '-' }}</view>
                  </view>
                  <view class="triple-num-box">
                    <text class="triple-label">U</text>
                    <view class="num-box triple">{{ reportData.recommendedNumbers?.num3 ?? '-' }}</view>
                  </view>
                </view>
              </view>
            </template>
          </view>
        </view>

        <view class="strategy-card">
          <text class="card-title">💡 STRATEGY</text>
          <view class="strategy-content">
            <view v-for="(item, index) in reportData.analysis?.strategy || []" :key="index" class="strategy-item">
              <view class="strategy-icon">{{ item.icon }}</view>
              <view class="strategy-info">
                <text class="strategy-title">{{ item.title }}</text>
                <text class="strategy-desc">{{ item.desc }}</text>
              </view>
            </view>
          </view>
        </view>
      </view>
      
      <view v-else class="loading-state">
        <text class="loading-text">LOADING DATA...</text>
      </view>

      <view class="footer-space"></view>
    </view>

    <view class="bottom-actions">
      <view class="action-btn copy" @click="copyNumbers">
        <text class="btn-icon">📋</text>
        <text class="btn-text">COPY</text>
      </view>
      <view class="action-btn share" @click="shareReport">
        <text class="btn-icon">📤</text>
        <text class="btn-text">SHARE</text>
      </view>
    </view>
  </view>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { lotteryTypes, lotteryHistory } from '../../data/lotteryData.js'
import { generateDetailedReport, generateOptimalReport } from '../../utils/index.js'

const reportType = ref('detailed')
const selectedGroup = ref('dataGroupA')
const reportData = ref({})

const currentGroupInfo = computed(() => {
  return lotteryTypes.find(l => l.id === selectedGroup.value) || lotteryTypes[0]
})

onMounted(() => {
  const pages = getCurrentPages()
  const currentPage = pages[pages.length - 1]
  const options = currentPage.options || {}
  
  if (options.type) {
    reportType.value = options.type
  }
  if (options.group) {
    selectedGroup.value = options.group
  }
  
  loadReportData()
})

function loadReportData() {
  const history = lotteryHistory[selectedGroup.value] || []
  
  if (reportType.value === 'detailed') {
    reportData.value = generateDetailedReport(selectedGroup.value, history)
  } else {
    reportData.value = generateOptimalReport(selectedGroup.value, history)
  }
}

function goBack() {
  const pages = getCurrentPages()
  if (pages.length > 1) {
    uni.navigateBack({
      fail: () => {
        uni.reLaunch({
          url: '/pages/index/index'
        })
      }
    })
  } else {
    uni.reLaunch({
      url: '/pages/index/index'
    })
  }
}

function copyNumbers() {
  let numbersText = ''
  
  if (selectedGroup.value === 'dataGroupA') {
    numbersText = `GROUP1: ${reportData.value.recommendedNumbers.group1.join(' ')} | GROUP2: ${reportData.value.recommendedNumbers.group2}`
  } else if (selectedGroup.value === 'dataGroupB') {
    numbersText = `GROUP1: ${reportData.value.recommendedNumbers.group1.join(' ')} | GROUP2: ${reportData.value.recommendedNumbers.group2.join(' ')}`
  } else if (selectedGroup.value === 'dataGroupC') {
    numbersText = `${reportData.value.recommendedNumbers.num1} ${reportData.value.recommendedNumbers.num2} ${reportData.value.recommendedNumbers.num3}`
  }
  
  uni.setClipboardData({
    data: numbersText,
    success: () => {
      uni.showToast({
        title: 'COPIED SUCCESS',
        icon: 'success'
      })
    }
  })
}

function shareReport() {
  uni.showToast({
    title: 'SHARE FUNCTION',
    icon: 'none'
  })
  
  // #ifdef MP-WEIXIN
  uni.showShareMenu({
    withShareTicket: true
  })
  // #endif
}
</script>

<style lang="scss">
.container {
  min-height: 100vh;
  background: linear-gradient(180deg, #1E88E5 0%, #F5F7FA 30%);
}

.loading-state {
  display: flex;
  justify-content: center;
  align-items: center;
  padding: 100rpx 0;
}

.loading-text {
  font-size: 28rpx;
  color: #999;
  letter-spacing: 2rpx;
}

.header {
  padding: 80rpx 30rpx 30rpx;
  background: rgba(255, 255, 255, 0.95);
}

.header-content {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.back-btn {
  width: 72rpx;
  height: 72rpx;
  border-radius: 50%;
  background: #F0F0F0;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 36rpx;
  color: #333;
}

.header-title {
  font-size: 34rpx;
  font-weight: bold;
  color: #333;
  letter-spacing: 2rpx;
}

.placeholder {
  width: 72rpx;
}

.report-content {
  padding: 30rpx;
}

.report-header {
  background: #fff;
  border-radius: 20rpx;
  padding: 30rpx;
  margin-bottom: 30rpx;
  display: flex;
  justify-content: space-between;
  align-items: center;
  box-shadow: 0 4rpx 20rpx rgba(0, 0, 0, 0.05);
}

.header-info {
  display: flex;
  flex-direction: column;
  gap: 8rpx;
}

.report-type {
  font-size: 36rpx;
  font-weight: bold;
  color: #1E88E5;
}

.generate-time {
  font-size: 24rpx;
  color: #999;
}

.report-badge {
  padding: 12rpx 24rpx;
  border-radius: 30rpx;
  font-size: 22rpx;
  font-weight: bold;
  color: #fff;
}

.report-badge.detailed {
  background: linear-gradient(135deg, #1E88E5, #1565C0);
}

.report-badge.optimal {
  background: linear-gradient(135deg, #43A047, #2E7D32);
}

.summary-card, .analysis-card, .distribution-card, .recommend-card, .strategy-card {
  background: #fff;
  border-radius: 20rpx;
  padding: 30rpx;
  margin-bottom: 30rpx;
  box-shadow: 0 4rpx 20rpx rgba(0, 0, 0, 0.05);
}

.card-title {
  font-size: 30rpx;
  font-weight: bold;
  color: #333;
  margin-bottom: 24rpx;
  display: block;
  letter-spacing: 1rpx;
}

.summary-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 20rpx;
}

.summary-item {
  text-align: center;
  padding: 20rpx;
  background: #F8FAFC;
  border-radius: 16rpx;
}

.summary-value {
  font-size: 36rpx;
  font-weight: bold;
  color: #1E88E5;
  display: block;
}

.summary-label {
  font-size: 20rpx;
  color: #999;
  margin-top: 8rpx;
  display: block;
  letter-spacing: 0.5rpx;
}

.analysis-content {
  background: #F8FAFC;
  border-radius: 16rpx;
  padding: 20rpx;
}

.number-list {
  display: flex;
  flex-wrap: wrap;
  gap: 16rpx;
}

.number-item {
  display: flex;
  align-items: center;
  gap: 12rpx;
  padding: 12rpx 16rpx;
  background: #fff;
  border-radius: 12rpx;
  flex: 0 0 calc(50% - 8rpx);
  box-sizing: border-box;
}

.number-circle {
  width: 56rpx;
  height: 56rpx;
  border-radius: 50%;
  background: linear-gradient(145deg, #1E88E5, #1565C0);
  color: #fff;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 26rpx;
  font-weight: bold;
}

.number-list.cold .number-circle {
  background: linear-gradient(145deg, #2196F3, #1976D2);
}

.number-info {
  flex: 1;
}

.number-count, .number-rate {
  font-size: 20rpx;
  color: #666;
  display: block;
}

.dist-section {
  margin-bottom: 30rpx;
}

.dist-section:last-child {
  margin-bottom: 0;
}

.dist-title {
  font-size: 24rpx;
  color: #666;
  margin-bottom: 16rpx;
  display: block;
}

.dist-chart {
  background: #F8FAFC;
  border-radius: 12rpx;
  padding: 20rpx;
}

.dist-bar-container {
  display: flex;
  height: 32rpx;
  border-radius: 16rpx;
  overflow: hidden;
  margin-bottom: 12rpx;
}

.dist-bar-wrapper {
  flex: 1;
  height: 16rpx;
  background: #E8ECEF;
  border-radius: 8rpx;
  overflow: hidden;
  display: flex;
}

.dist-bar {
  height: 100%;
  transition: width 0.5s;
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

.dist-labels {
  display: flex;
  justify-content: space-between;
  font-size: 20rpx;
  color: #999;
}

.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 24rpx;
}

.recommend-tip {
  font-size: 22rpx;
  color: #999;
}

.recommend-numbers {
  background: #F8FAFC;
  border-radius: 16rpx;
  padding: 24rpx;
}

.num-group {
  margin-bottom: 20rpx;
}

.num-group:last-child {
  margin-bottom: 0;
}

.group-label {
  font-size: 24rpx;
  color: #666;
  margin-bottom: 16rpx;
  display: block;
}

.num-row {
  display: flex;
  justify-content: center;
  gap: 16rpx;
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

.triple-num-box {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8rpx;
}

.triple-label {
  font-size: 20rpx;
  color: #666;
  font-weight: bold;
}

.strategy-content {
  display: flex;
  flex-direction: column;
  gap: 20rpx;
}

.strategy-item {
  display: flex;
  align-items: flex-start;
  gap: 16rpx;
  padding: 20rpx;
  background: #F8FAFC;
  border-radius: 16rpx;
}

.strategy-icon {
  font-size: 36rpx;
}

.strategy-info {
  flex: 1;
}

.strategy-title {
  font-size: 26rpx;
  font-weight: bold;
  color: #333;
  display: block;
  margin-bottom: 8rpx;
}

.strategy-desc {
  font-size: 22rpx;
  color: #666;
  line-height: 1.6;
}

.footer-space {
  height: 140rpx;
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

.action-btn.copy {
  background: linear-gradient(135deg, #1E88E5, #1565C0);
}

.action-btn.share {
  background: linear-gradient(135deg, #7B1FA2, #5E1B89);
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
