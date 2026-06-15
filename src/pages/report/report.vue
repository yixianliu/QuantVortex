<template>
  <view class="container">
    <view class="header">
      <view class="header-left" @click="goBack">
        <text class="back-icon">‹</text>
      </view>
      <text class="header-title">{{ reportType === 'detailed' ? '详细分析报告' : '精选推荐报告' }}</text>
      <view class="header-right">
        <text class="refresh-icon" @click="refreshReport">🔄</text>
      </view>
    </view>

    <view v-if="loading" class="loading-container">
      <view class="loading-spinner"></view>
      <text class="loading-text">正在生成报告...</text>
    </view>

    <view v-else-if="error" class="error-container">
      <text class="error-icon">❌</text>
      <text class="error-text">{{ error }}</text>
      <view class="retry-btn" @click="refreshReport">重新生成</view>
    </view>

    <scroll-view v-else class="content" scroll-y>
      <view class="report-header">
        <view class="report-title-section">
          <text class="report-title">⭐ QI XING CAI</text>
          <text class="report-subtitle">七星彩数字概率分析系统</text>
        </view>
        <view class="report-meta">
          <view class="meta-item">
            <text class="meta-label">生成时间</text>
            <text class="meta-value">{{ report.generateTime }}</text>
          </view>
          <view class="meta-item">
            <text class="meta-label">分析期数</text>
            <text class="meta-value">{{ report.analyzedCount }} 期</text>
          </view>
        </view>
        <view class="report-confidence">
          <view class="confidence-item">
            <text class="confidence-label">准确率</text>
            <text class="confidence-value accuracy">{{ report.accuracy }}%</text>
          </view>
          <view class="confidence-item">
            <text class="confidence-label">置信度</text>
            <text class="confidence-value confidence">{{ report.confidence }}%</text>
          </view>
        </view>
      </view>

      <view class="recommendation-section">
        <view class="section-header">
          <text class="section-title">🎯 推荐号码</text>
        </view>
        <view class="recommendation-card">
          <view class="recommendation-numbers">
            <view class="main-recommend">
              <text class="main-label">主号码</text>
              <view class="main-numbers">
                <view v-for="(num, index) in recommendedMainNumbers" :key="index" class="recommend-num primary">
                  {{ num }}
                </view>
              </view>
            </view>
            <view class="special-recommend">
              <text class="special-label">特别号</text>
              <view class="recommend-num secondary">{{ report.recommendedNumbers.special_num }}</view>
            </view>
          </view>
          <view class="copy-btn" @click="copyRecommendNumbers">
            <text class="copy-icon">📋</text>
            <text class="copy-text">复制号码</text>
          </view>
        </view>
      </view>

      <view class="hot-cold-section">
        <view class="section-header">
          <text class="section-title">🔥 热号 / ❄️ 冷号</text>
        </view>
        <view class="hot-cold-grid">
          <view class="hot-cold-card hot">
            <text class="card-icon">🔥</text>
            <text class="card-title">热号 TOP5</text>
            <view class="card-numbers">
              <view v-for="(item, index) in report.analysis.hotNumbers.slice(0, 5)" :key="'hot-' + index" class="hot-cold-num">
                <text class="num-value">{{ item.num }}</text>
                <text class="num-count">({{ item.count }}次)</text>
              </view>
            </view>
            <text class="card-desc">近期出现频率最高的号码</text>
          </view>
          <view class="hot-cold-card cold">
            <text class="card-icon">❄️</text>
            <text class="card-title">冷号 TOP5</text>
            <view class="card-numbers">
              <view v-for="(item, index) in report.analysis.coldNumbers.slice(0, 5)" :key="'cold-' + index" class="hot-cold-num">
                <text class="num-value">{{ item.num }}</text>
                <text class="num-count">({{ item.count }}次)</text>
              </view>
            </view>
            <text class="card-desc">近期出现频率最低的号码</text>
          </view>
        </view>
      </view>

      <view class="distribution-section">
        <view class="section-header">
          <text class="section-title">📊 号码分布统计</text>
        </view>
        <view class="distribution-card">
          <view class="distribution-row">
            <view class="dist-item">
              <view class="dist-bar-container">
                <view class="dist-bar-wrapper">
                  <view class="dist-bar odd" :style="{ width: report.analysis.distribution.oddRate + '%' }"></view>
                </view>
                <text class="dist-percent">{{ report.analysis.distribution.oddRate }}%</text>
              </view>
              <text class="dist-label">奇数</text>
            </view>
            <view class="dist-item">
              <view class="dist-bar-container">
                <view class="dist-bar-wrapper">
                  <view class="dist-bar even" :style="{ width: report.analysis.distribution.evenRate + '%' }"></view>
                </view>
                <text class="dist-percent">{{ report.analysis.distribution.evenRate }}%</text>
              </view>
              <text class="dist-label">偶数</text>
            </view>
          </view>
          <view class="distribution-row">
            <view class="dist-item">
              <view class="dist-bar-container">
                <view class="dist-bar-wrapper">
                  <view class="dist-bar small" :style="{ width: report.analysis.distribution.smallRate + '%' }"></view>
                </view>
                <text class="dist-percent">{{ report.analysis.distribution.smallRate }}%</text>
              </view>
              <text class="dist-label">小号 (0-4)</text>
            </view>
            <view class="dist-item">
              <view class="dist-bar-container">
                <view class="dist-bar-wrapper">
                  <view class="dist-bar large" :style="{ width: report.analysis.distribution.largeRate + '%' }"></view>
                </view>
                <text class="dist-percent">{{ report.analysis.distribution.largeRate }}%</text>
              </view>
              <text class="dist-label">大号 (5-9)</text>
            </view>
          </view>
        </view>
      </view>

      <view v-if="reportType === 'detailed'" class="hezhi-section">
        <view class="section-header">
          <text class="section-title">📈 和值分析</text>
        </view>
        <view class="hezhi-card">
          <view class="hezhi-summary">
            <view class="hezhi-item">
              <text class="hezhi-label">平均和值</text>
              <text class="hezhi-value">{{ report.analysis.hezhi.hezhi_analysis.avg_hezhi }}</text>
            </view>
            <view class="hezhi-item">
              <text class="hezhi-label">理论均值</text>
              <text class="hezhi-value">{{ report.analysis.hezhi.hezhi_analysis.theory_avg }}</text>
            </view>
            <view class="hezhi-item">
              <text class="hezhi-label">偏差值</text>
              <text class="hezhi-value" :class="parseFloat(report.analysis.hezhi.hezhi_analysis.deviation_from_theory) > 0 ? 'positive' : 'negative'">
                {{ report.analysis.hezhi.hezhi_analysis.deviation_from_theory }}
              </text>
            </view>
          </view>
          <view class="hezhi-distribution">
            <text class="dist-title">和值区间分布</text>
            <view class="hezhi-bars">
              <view v-for="(value, key) in report.analysis.hezhi.hezhi_analysis.range_distribution" :key="key" class="hezhi-bar-item">
                <text class="bar-label">{{ key }}</text>
                <view class="bar-wrapper">
                  <view class="bar-fill" :style="{ width: value.probability + '%' }"></view>
                </view>
                <text class="bar-value">{{ value.probability }}%</text>
              </view>
            </view>
          </view>
        </view>
      </view>

      <view v-if="reportType === 'detailed'" class="span-section">
        <view class="section-header">
          <text class="section-title">📏 跨度分析</text>
        </view>
        <view class="span-card">
          <view class="span-summary">
            <view class="span-item">
              <text class="span-label">平均跨度</text>
              <text class="span-value">{{ report.analysis.span.span_analysis.avg_span }}</text>
            </view>
            <view class="span-item">
              <text class="span-label">最大跨度</text>
              <text class="span-value">{{ report.analysis.span.span_analysis.max_span }}</text>
            </view>
            <view class="span-item">
              <text class="span-label">最小跨度</text>
              <text class="span-value">{{ report.analysis.span.span_analysis.min_span }}</text>
            </view>
          </view>
          <view class="span-distribution">
            <text class="dist-title">跨度分布</text>
            <view class="span-grid">
              <view v-for="(value, key) in report.analysis.span.span_analysis.span_distribution" :key="key" class="span-cell">
                <text class="span-num">{{ key }}</text>
                <text class="span-prob">{{ value.probability }}%</text>
              </view>
            </view>
          </view>
        </view>
      </view>

      <view class="strategy-section">
        <view class="section-header">
          <text class="section-title">💡 投注策略</text>
        </view>
        <view class="strategy-list">
          <view v-for="(strategy, index) in report.analysis.strategy" :key="index" class="strategy-item">
            <text class="strategy-icon">{{ strategy.icon }}</text>
            <view class="strategy-content">
              <text class="strategy-title">{{ strategy.title }}</text>
              <text class="strategy-desc">{{ strategy.desc }}</text>
            </view>
          </view>
        </view>
      </view>

      <view class="disclaimer-section">
        <text class="disclaimer-title">⚠️ 免责声明</text>
        <text class="disclaimer-content">本分析报告仅供参考，不构成任何投资建议。彩票中奖号码完全随机，历史数据不代表未来结果。请理性购彩，量力而行。</text>
      </view>
    </scroll-view>
  </view>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { lotteryHistory } from '../../data/lotteryData.js'
import { generateDetailedReport, generateOptimalReport } from '../../utils/index.js'

const reportType = ref('detailed')
const selectedGroup = ref('qixingcai')
const loading = ref(true)
const error = ref('')
const report = ref({})

const historyData = computed(() => {
  return lotteryHistory[selectedGroup.value] || []
})

const recommendedMainNumbers = computed(() => {
  const nums = report.value.recommendedNumbers || {}
  return [nums.num1, nums.num2, nums.num3, nums.num4, nums.num5, nums.num6].filter(n => n !== undefined)
})

onMounted(() => {
  const pages = getCurrentPages()
  const currentPage = pages[pages.length - 1]
  const options = currentPage.$page?.options || {}
  
  if (options.type) {
    reportType.value = options.type
  }
  if (options.group) {
    selectedGroup.value = options.group
  }
  
  generateReport()
})

function generateReport() {
  loading.value = true
  error.value = ''
  
  setTimeout(() => {
    try {
      if (reportType.value === 'detailed') {
        report.value = generateDetailedReport(selectedGroup.value, historyData.value)
      } else {
        report.value = generateOptimalReport(selectedGroup.value, historyData.value)
      }
      loading.value = false
    } catch (e) {
      error.value = '报告生成失败，请重试'
      loading.value = false
    }
  }, 1500)
}

function refreshReport() {
  generateReport()
}

function goBack() {
  uni.navigateBack({
    fail: () => {
      uni.switchTab({
        url: '/pages/index/index'
      })
    }
  })
}

function copyRecommendNumbers() {
  const nums = recommendedMainNumbers.value.join(' ') + ' + ' + report.value.recommendedNumbers?.special_num
  uni.setClipboardData({
    data: nums,
    success: () => {
      uni.showToast({
        title: '复制成功',
        icon: 'success'
      })
    }
  })
}
</script>

<style lang="scss">
.container {
  min-height: 100vh;
  background: #F5F7FA;
}

.header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 60rpx 30rpx 30rpx;
  background: linear-gradient(135deg, #43A047, #2E7D32);
}

.header-left,
.header-right {
  width: 60rpx;
  height: 60rpx;
  display: flex;
  align-items: center;
  justify-content: center;
}

.back-icon {
  font-size: 48rpx;
  color: #fff;
  font-weight: bold;
}

.refresh-icon {
  font-size: 32rpx;
}

.header-title {
  font-size: 32rpx;
  font-weight: bold;
  color: #fff;
  letter-spacing: 2rpx;
}

.loading-container,
.error-container {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 200rpx 40rpx;
}

.loading-spinner {
  width: 80rpx;
  height: 80rpx;
  border: 8rpx solid #E8ECEF;
  border-top-color: #43A047;
  border-radius: 50%;
  animation: spin 1s linear infinite;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

.loading-text,
.error-text {
  margin-top: 32rpx;
  font-size: 28rpx;
  color: #666;
}

.error-icon {
  font-size: 80rpx;
  margin-bottom: 24rpx;
}

.retry-btn {
  margin-top: 32rpx;
  padding: 20rpx 48rpx;
  background: linear-gradient(135deg, #43A047, #2E7D32);
  color: #fff;
  font-size: 28rpx;
  font-weight: bold;
  border-radius: 40rpx;
}

.content {
  padding: 30rpx;
  padding-bottom: 60rpx;
}

.report-header {
  background: linear-gradient(135deg, #fff, #F8FAFC);
  border-radius: 24rpx;
  padding: 32rpx;
  margin-bottom: 30rpx;
  box-shadow: 0 4rpx 20rpx rgba(0, 0, 0, 0.05);
}

.report-title-section {
  text-align: center;
  padding-bottom: 24rpx;
  border-bottom: 2rpx dashed #E8ECEF;
}

.report-title {
  font-size: 36rpx;
  font-weight: bold;
  color: #43A047;
  display: block;
  letter-spacing: 4rpx;
}

.report-subtitle {
  font-size: 24rpx;
  color: #666;
  margin-top: 12rpx;
  display: block;
}

.report-meta {
  display: flex;
  justify-content: space-around;
  padding: 24rpx 0;
}

.meta-item {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8rpx;
}

.meta-label {
  font-size: 22rpx;
  color: #999;
}

.meta-value {
  font-size: 28rpx;
  font-weight: bold;
  color: #333;
}

.report-confidence {
  display: flex;
  justify-content: center;
  gap: 64rpx;
  padding-top: 20rpx;
  border-top: 2rpx dashed #E8ECEF;
}

.confidence-item {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8rpx;
}

.confidence-label {
  font-size: 22rpx;
  color: #999;
}

.confidence-value {
  font-size: 36rpx;
  font-weight: bold;
}

.confidence-value.accuracy {
  color: #43A047;
}

.confidence-value.confidence {
  color: #1E88E5;
}

.section-header {
  margin-bottom: 20rpx;
}

.section-title {
  font-size: 30rpx;
  font-weight: bold;
  color: #333;
  letter-spacing: 2rpx;
}

.recommendation-section,
.hot-cold-section,
.distribution-section,
.hezhi-section,
.span-section,
.strategy-section {
  margin-bottom: 30rpx;
}

.recommendation-card {
  background: linear-gradient(135deg, #fff, #F8FAFC);
  border-radius: 20rpx;
  padding: 32rpx;
  box-shadow: 0 4rpx 20rpx rgba(0, 0, 0, 0.05);
}

.recommendation-numbers {
  display: flex;
  justify-content: center;
  align-items: flex-end;
  gap: 32rpx;
  margin-bottom: 24rpx;
}

.main-recommend,
.special-recommend {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 16rpx;
}

.main-label,
.special-label {
  font-size: 22rpx;
  color: #999;
}

.main-numbers {
  display: flex;
  gap: 12rpx;
}

.recommend-num {
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

.recommend-num.primary {
  background: linear-gradient(145deg, #43A047, #2E7D32);
}

.recommend-num.secondary {
  background: linear-gradient(145deg, #FF9800, #F57C00);
}

.copy-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 12rpx;
  padding: 20rpx;
  background: rgba(67, 160, 71, 0.1);
  border-radius: 40rpx;
  margin-top: 20rpx;
}

.copy-icon {
  font-size: 28rpx;
}

.copy-text {
  font-size: 26rpx;
  color: #43A047;
  font-weight: 600;
}

.hot-cold-grid {
  display: flex;
  gap: 20rpx;
}

.hot-cold-card {
  flex: 1;
  background: #fff;
  border-radius: 20rpx;
  padding: 28rpx;
  box-shadow: 0 4rpx 20rpx rgba(0, 0, 0, 0.05);
}

.hot-cold-card.hot {
  border-top: 6rpx solid #FF9800;
  background: linear-gradient(145deg, #FFF8F0, #FFFAF5);
}

.hot-cold-card.cold {
  border-top: 6rpx solid #2196F3;
  background: linear-gradient(145deg, #F0F7FF, #F5FAFF);
}

.card-icon {
  font-size: 40rpx;
  display: block;
  text-align: center;
  margin-bottom: 12rpx;
}

.card-title {
  font-size: 26rpx;
  font-weight: bold;
  color: #333;
  text-align: center;
  display: block;
  margin-bottom: 20rpx;
}

.card-numbers {
  display: flex;
  flex-direction: column;
  gap: 12rpx;
}

.hot-cold-num {
  display: flex;
  align-items: center;
  gap: 12rpx;
}

.num-value {
  width: 48rpx;
  height: 48rpx;
  border-radius: 10rpx;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 24rpx;
  font-weight: bold;
  color: #fff;
}

.hot-cold-card.hot .num-value {
  background: linear-gradient(145deg, #FF9800, #F57C00);
}

.hot-cold-card.cold .num-value {
  background: linear-gradient(145deg, #2196F3, #1976D2);
}

.num-count {
  font-size: 22rpx;
  color: #666;
}

.card-desc {
  font-size: 20rpx;
  color: #999;
  text-align: center;
  display: block;
  margin-top: 16rpx;
  padding-top: 16rpx;
  border-top: 1rpx dashed #E0E0E0;
}

.distribution-card,
.hezhi-card,
.span-card {
  background: #fff;
  border-radius: 20rpx;
  padding: 28rpx;
  box-shadow: 0 4rpx 20rpx rgba(0, 0, 0, 0.05);
}

.distribution-row {
  display: flex;
  gap: 24rpx;
}

.dist-item {
  flex: 1;
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
  height: 20rpx;
  background: #E8ECEF;
  border-radius: 10rpx;
  overflow: hidden;
}

.dist-bar {
  height: 100%;
  border-radius: 10rpx;
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

.dist-percent {
  font-size: 24rpx;
  font-weight: bold;
  color: #333;
  min-width: 80rpx;
}

.dist-label {
  font-size: 22rpx;
  color: #666;
}

.hezhi-summary,
.span-summary {
  display: flex;
  justify-content: space-around;
  padding-bottom: 24rpx;
  border-bottom: 2rpx dashed #E8ECEF;
  margin-bottom: 24rpx;
}

.hezhi-item,
.span-item {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8rpx;
}

.hezhi-label,
.span-label {
  font-size: 22rpx;
  color: #999;
}

.hezhi-value,
.span-value {
  font-size: 32rpx;
  font-weight: bold;
  color: #333;
}

.hezhi-value.positive {
  color: #43A047;
}

.hezhi-value.negative {
  color: #E53935;
}

.dist-title {
  font-size: 26rpx;
  font-weight: bold;
  color: #333;
  margin-bottom: 20rpx;
  display: block;
}

.hezhi-bars {
  display: flex;
  flex-direction: column;
  gap: 16rpx;
}

.hezhi-bar-item {
  display: flex;
  align-items: center;
  gap: 12rpx;
}

.bar-label {
  font-size: 22rpx;
  color: #666;
  width: 80rpx;
}

.bar-wrapper {
  flex: 1;
  height: 16rpx;
  background: #E8ECEF;
  border-radius: 8rpx;
  overflow: hidden;
}

.bar-fill {
  height: 100%;
  background: linear-gradient(90deg, #43A047, #66BB6A);
  border-radius: 8rpx;
  transition: width 0.8s ease-out;
}

.bar-value {
  font-size: 22rpx;
  font-weight: bold;
  color: #333;
  min-width: 80rpx;
  text-align: right;
}

.span-grid {
  display: grid;
  grid-template-columns: repeat(5, 1fr);
  gap: 16rpx;
}

.span-cell {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8rpx;
  padding: 16rpx;
  background: #F8FAFC;
  border-radius: 12rpx;
}

.span-num {
  font-size: 28rpx;
  font-weight: bold;
  color: #333;
}

.span-prob {
  font-size: 20rpx;
  color: #666;
}

.strategy-list {
  background: #fff;
  border-radius: 20rpx;
  padding: 8rpx;
  box-shadow: 0 4rpx 20rpx rgba(0, 0, 0, 0.05);
}

.strategy-item {
  display: flex;
  align-items: flex-start;
  gap: 20rpx;
  padding: 20rpx;
  border-bottom: 1rpx dashed #E8ECEF;
}

.strategy-item:last-child {
  border-bottom: none;
}

.strategy-icon {
  font-size: 36rpx;
  flex-shrink: 0;
}

.strategy-content {
  flex: 1;
}

.strategy-title {
  font-size: 28rpx;
  font-weight: bold;
  color: #333;
  display: block;
  margin-bottom: 8rpx;
}

.strategy-desc {
  font-size: 24rpx;
  color: #666;
  line-height: 1.6;
}

.disclaimer-section {
  background: rgba(255, 152, 0, 0.1);
  border-radius: 16rpx;
  padding: 24rpx;
  margin-top: 40rpx;
}

.disclaimer-title {
  font-size: 24rpx;
  font-weight: bold;
  color: #F57C00;
  display: block;
  margin-bottom: 12rpx;
}

.disclaimer-content {
  font-size: 22rpx;
  color: #666;
  line-height: 1.8;
}
</style>