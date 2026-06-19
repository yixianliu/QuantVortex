<template>
  <view class="container">
    <view class="header" :style="{ background: headerStyle.background }">
      <view class="header-left" @click="goBack">
        <text class="back-icon">‹</text>
      </view>
      <text class="header-title">{{ reportTitle }}</text>
      <view class="header-right">
        <text class="refresh-icon" :class="{ spinning: loading }" @click="refreshReport">⟳</text>
      </view>
    </view>

    <view v-if="loading" class="loading-container">
      <view class="loading-spinner" :style="{ borderTopColor: currentGroupInfo.color }"></view>
      <text class="loading-text">正在生成报告...</text>
      <view class="loading-progress">
        <view class="progress-bar" :style="{ width: progressWidth + '%', background: currentGroupInfo.color }"></view>
      </view>
    </view>

    <view v-else-if="error" class="error-container">
      <text class="error-icon">!</text>
      <text class="error-text">{{ error }}</text>
      <view class="retry-btn" :style="{ background: currentGroupInfo.gradient }" @click="refreshReport">重新生成</view>
    </view>

    <scroll-view v-else class="content" scroll-y>
      <view class="report-header">
        <view class="report-title-section">
          <view class="report-icon-wrapper" :style="{ background: currentGroupInfo.bgColor }">
            <text class="report-icon-text" :style="{ color: currentGroupInfo.color }">{{ currentGroupInfo.icon }}</text>
          </view>
          <text class="report-title">{{ currentGroupInfo.enName }}</text>
          <text class="report-subtitle">{{ currentGroupInfo.description }}</text>
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
            <view class="confidence-ring" :style="{ background: `conic-gradient(${currentGroupInfo.color} ${report.accuracy * 3.6}deg, #E8ECEF 0)` }">
              <view class="ring-inner">
                <text class="confidence-value" :style="{ color: currentGroupInfo.color }">{{ report.accuracy }}%</text>
              </view>
            </view>
            <text class="confidence-label">准确率</text>
          </view>
          <view class="confidence-item">
            <view class="confidence-ring" :style="{ background: `conic-gradient(#8B5CF6 ${report.confidence * 3.6}deg, #E8ECEF 0)` }">
              <view class="ring-inner">
                <text class="confidence-value" style="color: #8B5CF6">{{ report.confidence }}%</text>
              </view>
            </view>
            <text class="confidence-label">置信度</text>
          </view>
        </view>
      </view>

      <view class="recommendation-section">
        <view class="section-header">
          <view class="section-title-wrapper">
            <view class="title-bar" :style="{ background: currentGroupInfo.color }"></view>
            <text class="section-title">推荐号码</text>
          </view>
        </view>
        <view class="recommendation-card">
          <view class="recommendation-numbers">
            <view class="main-recommend">
              <text class="main-label">主号码</text>
              <view class="main-numbers">
                <view
                  v-for="(num, index) in recommendedMainNumbers"
                  :key="index"
                  class="recommend-block"
                  :style="{ background: index < 3 ? currentGroupInfo.gradient : `linear-gradient(135deg, ${currentGroupInfo.color}CC, ${currentGroupInfo.color}88)` }"
                >
                  <text class="recommend-num-text">{{ num }}</text>
                </view>
              </view>
            </view>
            <view v-if="currentGroupInfo.hasSpecial" class="special-recommend">
              <text class="special-label">特别号</text>
              <view class="recommend-block special" :style="{ background: 'linear-gradient(135deg, #6366F1, #4F46E5)' }">
                <text class="recommend-num-text">{{ report.recommendedNumbers?.special_num }}</text>
              </view>
            </view>
          </view>
          <view class="copy-btn" :style="{ background: currentGroupInfo.bgColor }" @click="copyRecommendNumbers">
            <text class="copy-icon" :style="{ color: currentGroupInfo.color }">⎘</text>
            <text class="copy-text" :style="{ color: currentGroupInfo.color }">复制号码</text>
          </view>
        </view>
      </view>

      <view class="hot-cold-section">
        <view class="section-header">
          <view class="section-title-wrapper">
            <view class="title-bar" :style="{ background: currentGroupInfo.color }"></view>
            <text class="section-title">号码频率</text>
          </view>
        </view>
        <view class="hot-cold-grid">
          <view class="hot-cold-card hot">
            <view class="card-header">
              <view class="card-icon-wrapper hot-icon" :style="{ background: '#FEF3C7' }">
                <text class="card-icon-text" :style="{ color: '#D97706' }">HOT</text>
              </view>
              <text class="card-title">高频号码</text>
            </view>
            <view class="card-numbers">
              <view
                v-for="(item, index) in report.analysis.hotNumbers.slice(0, 5)"
                :key="'hot-' + index"
                class="hot-cold-num"
              >
                <view class="num-block-small" :style="{ background: '#F59E0B' }">
                  <text class="num-block-text">{{ item.num }}</text>
                </view>
                <view class="num-info">
                  <text class="num-count">{{ item.count }}次</text>
                  <view class="num-mini-bar" :style="{ width: (item.count / report.analysis.hotNumbers[0].count * 100) + '%', background: '#F59E0B' }"></view>
                </view>
              </view>
            </view>
          </view>
          <view class="hot-cold-card cold">
            <view class="card-header">
              <view class="card-icon-wrapper cold-icon" :style="{ background: '#DBEAFE' }">
                <text class="card-icon-text" :style="{ color: '#2563EB' }">LOW</text>
              </view>
              <text class="card-title">低频号码</text>
            </view>
            <view class="card-numbers">
              <view
                v-for="(item, index) in report.analysis.coldNumbers.slice(0, 5)"
                :key="'cold-' + index"
                class="hot-cold-num"
              >
                <view class="num-block-small" :style="{ background: '#3B82F6' }">
                  <text class="num-block-text">{{ item.num }}</text>
                </view>
                <view class="num-info">
                  <text class="num-count">{{ item.count }}次</text>
                  <view class="num-mini-bar cold-bar" :style="{ width: Math.max(20, item.count * 15) + '%', background: '#3B82F6' }"></view>
                </view>
              </view>
            </view>
          </view>
        </view>
      </view>

      <view class="distribution-section">
        <view class="section-header">
          <view class="section-title-wrapper">
            <view class="title-bar" :style="{ background: currentGroupInfo.color }"></view>
            <text class="section-title">号码分布</text>
          </view>
        </view>
        <view class="distribution-card">
          <view class="distribution-row">
            <view class="dist-item" v-for="(item, idx) in distributionList" :key="idx">
              <view class="dist-bar-container">
                <view class="dist-bar-wrapper">
                  <view
                    class="dist-bar"
                    :style="{ width: item.value + '%', background: item.color }"
                  ></view>
                </view>
                <text class="dist-percent">{{ item.value }}%</text>
              </view>
              <text class="dist-label">{{ item.label }}</text>
            </view>
          </view>
        </view>
      </view>

      <view v-if="reportType === 'detailed'" class="hezhi-section">
        <view class="section-header">
          <view class="section-title-wrapper">
            <view class="title-bar" :style="{ background: currentGroupInfo.color }"></view>
            <text class="section-title">和值分析</text>
          </view>
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
              <text
                class="hezhi-value"
                :class="parseFloat(report.analysis.hezhi.hezhi_analysis.deviation_from_theory) > 0 ? 'positive' : 'negative'"
              >
                {{ report.analysis.hezhi.hezhi_analysis.deviation_from_theory }}
              </text>
            </view>
          </view>
          <view class="hezhi-distribution">
            <text class="dist-title">和值区间分布</text>
            <view class="hezhi-bars">
              <view
                v-for="(value, key) in report.analysis.hezhi.hezhi_analysis.range_distribution"
                :key="key"
                class="hezhi-bar-item"
              >
                <text class="bar-label">{{ key }}</text>
                <view class="bar-wrapper">
                  <view class="bar-fill" :style="{ width: value.probability + '%', background: currentGroupInfo.gradient }"></view>
                </view>
                <text class="bar-value">{{ value.probability }}%</text>
              </view>
            </view>
          </view>
        </view>
      </view>

      <view v-if="reportType === 'detailed'" class="span-section">
        <view class="section-header">
          <view class="section-title-wrapper">
            <view class="title-bar" :style="{ background: currentGroupInfo.color }"></view>
            <text class="section-title">跨度分析</text>
          </view>
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
              <view
                v-for="(value, key) in report.analysis.span.span_analysis.span_distribution"
                :key="key"
                class="span-cell"
              >
                <text class="span-num">{{ key }}</text>
                <view class="span-bar-wrapper">
                  <view class="span-bar" :style="{ height: value.probability + '%', background: currentGroupInfo.gradient }"></view>
                </view>
                <text class="span-prob">{{ value.probability }}%</text>
              </view>
            </view>
          </view>
        </view>
      </view>

      <view class="strategy-section">
        <view class="section-header">
          <view class="section-title-wrapper">
            <view class="title-bar" :style="{ background: currentGroupInfo.color }"></view>
            <text class="section-title">投注策略</text>
          </view>
        </view>
        <view class="strategy-list">
          <view
            v-for="(strategy, index) in report.analysis.strategy"
            :key="index"
            class="strategy-item"
          >
            <view class="strategy-icon-wrapper" :style="{ background: strategyBgColors[index % 4] }">
              <text class="strategy-icon" :style="{ color: strategyIconColors[index % 4] }">{{ strategy.icon }}</text>
            </view>
            <view class="strategy-content">
              <text class="strategy-title">{{ strategy.title }}</text>
              <text class="strategy-desc">{{ strategy.desc }}</text>
            </view>
          </view>
        </view>
      </view>

      <view class="disclaimer-section">
        <text class="disclaimer-icon">!</text>
        <text class="disclaimer-title">免责声明</text>
        <text class="disclaimer-content">本分析报告仅供参考，不构成任何投资建议。数据结果完全随机，历史数据不代表未来走势。请理性分析，谨慎决策。</text>
      </view>
    </scroll-view>
  </view>
</template>

<script setup>
import { ref, computed } from 'vue'
import { onLoad } from '@dcloudio/uni-app'
import { lotteryTypes } from '@/data/lotteryData.js'
import { api, checkApiStatus, setApiStatus } from '@/api/index.js'
import { getStrategyList } from '@/utils/index.js'

const reportType = ref('detailed')
const selectedGroup = ref('qixingcai')
const loading = ref(true)
const error = ref('')
const report = ref({})
const progressWidth = ref(0)

const currentGroupInfo = computed(() => {
  return lotteryTypes.find(l => l.id === selectedGroup.value) || lotteryTypes[0]
})

const headerStyle = computed(() => ({
  background: currentGroupInfo.value.gradient
}))

const reportTitle = computed(() => {
  return reportType.value === 'detailed' ? '详细分析报告' : '精选推荐报告'
})

const recommendedMainNumbers = computed(() => {
  const nums = report.value.recommendedNumbers || {}
  const count = currentGroupInfo.value.numberCount || 6
  const result = []
  for (let i = 1; i <= count; i++) {
    if (nums[`num${i}`] !== undefined) {
      result.push(nums[`num${i}`])
    }
  }
  return result
})

const distributionList = computed(() => {
  const dist = report.value.analysis?.distribution || {}
  return [
    { type: 'odd', label: '奇数', value: dist.oddRate, color: '#EF4444' },
    { type: 'even', label: '偶数', value: dist.evenRate, color: '#3B82F6' },
    { type: 'small', label: '小号', value: dist.smallRate, color: '#8B5CF6' },
    { type: 'large', label: '大号', value: dist.largeRate, color: '#10B981' }
  ]
})

const strategyBgColors = ['#EFF6FF', '#FEF3C7', '#F5F3FF', '#ECFDF5']
const strategyIconColors = ['#3B82F6', '#D97706', '#8B5CF6', '#10B981']

function parseApiReportData(apiData) {
  if (!apiData) return null

  const generatedReports = apiData.generated_reports || []
  const result = {
    generateTime: apiData.generated_at ? new Date(apiData.generated_at).toLocaleString('zh-CN') : '',
    analyzedCount: apiData.total_samples || 0,
    accuracy: 0,
    confidence: 0,
    recommendedNumbers: {},
    analysis: {
      hotNumbers: [],
      coldNumbers: [],
      distribution: {
        oddRate: '50',
        evenRate: '50',
        smallRate: '50',
        largeRate: '50'
      },
      hezhi: null,
      span: null,
      strategy: getStrategyList(selectedGroup.value)
    }
  }

  generatedReports.forEach(reportItem => {
    if (reportItem.type === 'optimal') {
      result.confidence = Math.round((reportItem.confidence_score || 0) * 100)
      if (reportItem.recommended_numbers) {
        const nums = reportItem.recommended_numbers.split(',').map(n => parseInt(n.trim()))
        nums.forEach((num, index) => {
          if (index < 6) {
            result.recommendedNumbers[`num${index + 1}`] = num
          } else {
            result.recommendedNumbers.special_num = num
          }
        })
      }
    }

    if (reportItem.analysis) {
      if (reportItem.analysis.hezhi) {
        result.analysis.hezhi = { hezhi_analysis: reportItem.analysis.hezhi }
      }
      if (reportItem.analysis.span) {
        result.analysis.span = { span_analysis: reportItem.analysis.span }
      }
      if (reportItem.analysis.position_analysis_summary) {
        const hotMap = {}
        const coldMap = {}
        Object.values(reportItem.analysis.position_analysis_summary).forEach(pos => {
          (pos.hot_numbers || []).forEach(num => { hotMap[num] = (hotMap[num] || 0) + 1 })
          (pos.cold_numbers || []).forEach(num => { coldMap[num] = (coldMap[num] || 0) + 1 })
        })
        result.analysis.hotNumbers = Object.entries(hotMap).map(([num, count]) => ({ num: parseInt(num), count })).sort((a, b) => b.count - a.count)
        result.analysis.coldNumbers = Object.entries(coldMap).map(([num, count]) => ({ num: parseInt(num), count })).sort((a, b) => a.count - b.count)
      }
    }
  })

  return result
}

onLoad((options) => {
  if (options?.type) {
    reportType.value = options.type
  }
  if (options?.group) {
    selectedGroup.value = options.group
  }
  generateReport()
})

async function generateReport() {
  loading.value = true
  error.value = ''
  progressWidth.value = 0

  const progressInterval = setInterval(() => {
    if (progressWidth.value < 90) {
      progressWidth.value += Math.random() * 15
    }
  }, 200)

  try {
    const isAvailable = await checkApiStatus()
    if (!isAvailable) {
      setApiStatus(false)
      uni.reLaunch({ url: '/pages/system-upgrade/system-upgrade' })
      return
    }

    const reportResult = await api.report.generate({
      report_types: [reportType.value],
      use_trend: true
    })

    clearInterval(progressInterval)
    progressWidth.value = 100

    if (reportResult.success && reportResult.data) {
      report.value = parseApiReportData(reportResult.data)
    } else {
      error.value = reportResult.message || '报告生成失败'
    }
  } catch (e) {
    clearInterval(progressInterval)
    error.value = '报告生成失败，请重试'
  } finally {
    loading.value = false
  }
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
  const nums = recommendedMainNumbers.value.join(' ')
  const special = report.value.recommendedNumbers?.special_num
  const text = special ? `${nums} + ${special}` : nums
  uni.setClipboardData({
    data: text,
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
  background: #F8FAFC;
}

.header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 100rpx 30rpx 30rpx;
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
  font-size: 36rpx;
  color: #fff;
  transition: transform 0.3s;
}

.refresh-icon.spinning {
  animation: spin 1s linear infinite;
}

@keyframes spin {
  to { transform: rotate(360deg); }
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
  border-radius: 50%;
  animation: spin 1s linear infinite;
}

.loading-text,
.error-text {
  margin-top: 32rpx;
  font-size: 28rpx;
  color: #666;
}

.loading-progress {
  width: 300rpx;
  height: 8rpx;
  background: #E8ECEF;
  border-radius: 4rpx;
  margin-top: 24rpx;
  overflow: hidden;
}

.progress-bar {
  height: 100%;
  border-radius: 4rpx;
  transition: width 0.3s ease;
}

.error-icon {
  width: 80rpx;
  height: 80rpx;
  border-radius: 50%;
  background: #FEE2E2;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 40rpx;
  font-weight: bold;
  color: #EF4444;
  margin-bottom: 24rpx;
}

.retry-btn {
  margin-top: 32rpx;
  padding: 20rpx 48rpx;
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
  background: #fff;
  border-radius: 24rpx;
  padding: 32rpx;
  margin-bottom: 30rpx;
  box-shadow: 0 2rpx 12rpx rgba(0, 0, 0, 0.04);
}

.report-title-section {
  text-align: center;
  padding-bottom: 24rpx;
  border-bottom: 2rpx solid #F3F4F6;
}

.report-icon-wrapper {
  width: 100rpx;
  height: 100rpx;
  border-radius: 24rpx;
  display: flex;
  align-items: center;
  justify-content: center;
  margin: 0 auto 16rpx;
}

.report-icon-text {
  font-size: 40rpx;
  font-weight: bold;
}

.report-title {
  font-size: 36rpx;
  font-weight: bold;
  color: #1F2937;
  display: block;
  letter-spacing: 4rpx;
}

.report-subtitle {
  font-size: 24rpx;
  color: #6B7280;
  margin-top: 8rpx;
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
  font-size: 24rpx;
  color: #6B7280;
}

.meta-value {
  font-size: 28rpx;
  font-weight: bold;
  color: #1F2937;
}

.report-confidence {
  display: flex;
  justify-content: space-around;
  padding-top: 24rpx;
  border-top: 2rpx solid #F3F4F6;
}

.confidence-item {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 16rpx;
}

.confidence-ring {
  width: 120rpx;
  height: 120rpx;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
}

.ring-inner {
  width: 90rpx;
  height: 90rpx;
  border-radius: 50%;
  background: #fff;
  display: flex;
  align-items: center;
  justify-content: center;
}

.confidence-value {
  font-size: 28rpx;
  font-weight: bold;
}

.confidence-label {
  font-size: 24rpx;
  color: #6B7280;
}

.section-header {
  display: flex;
  align-items: center;
  padding: 16rpx 0;
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
  font-size: 30rpx;
  font-weight: bold;
  color: #1F2937;
}

.recommendation-card {
  background: #fff;
  border-radius: 20rpx;
  padding: 24rpx;
  box-shadow: 0 2rpx 12rpx rgba(0, 0, 0, 0.04);
}

.recommendation-numbers {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  margin-bottom: 20rpx;
}

.main-recommend,
.special-recommend {
  display: flex;
  flex-direction: column;
  gap: 12rpx;
}

.main-label,
.special-label {
  font-size: 22rpx;
  color: #6B7280;
}

.main-numbers {
  display: flex;
  gap: 12rpx;
  flex-wrap: wrap;
}

.recommend-block {
  width: 72rpx;
  height: 72rpx;
  border-radius: 12rpx;
  display: flex;
  align-items: center;
  justify-content: center;
}

.recommend-block.special {
  width: 64rpx;
  height: 64rpx;
}

.recommend-num-text {
  font-size: 28rpx;
  font-weight: bold;
  color: #fff;
}

.copy-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8rpx;
  padding: 16rpx;
  border-radius: 12rpx;
}

.copy-icon {
  font-size: 28rpx;
}

.copy-text {
  font-size: 26rpx;
  font-weight: bold;
}

.hot-cold-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 20rpx;
}

.hot-cold-card {
  background: #fff;
  border-radius: 20rpx;
  padding: 24rpx;
  box-shadow: 0 2rpx 12rpx rgba(0, 0, 0, 0.04);
}

.card-header {
  display: flex;
  align-items: center;
  gap: 12rpx;
  margin-bottom: 20rpx;
}

.card-icon-wrapper {
  width: 44rpx;
  height: 44rpx;
  border-radius: 10rpx;
  display: flex;
  align-items: center;
  justify-content: center;
}

.card-icon-text {
  font-size: 18rpx;
  font-weight: bold;
}

.card-title {
  font-size: 26rpx;
  font-weight: bold;
  color: #1F2937;
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

.num-block-small {
  width: 48rpx;
  height: 48rpx;
  border-radius: 10rpx;
  display: flex;
  align-items: center;
  justify-content: center;
}

.num-block-text {
  font-size: 24rpx;
  font-weight: bold;
  color: #fff;
}

.num-info {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 6rpx;
}

.num-count {
  font-size: 20rpx;
  color: #6B7280;
}

.num-mini-bar {
  height: 6rpx;
  border-radius: 3rpx;
}

.num-mini-bar.cold-bar {
  background: #3B82F6;
}

.distribution-card {
  background: #fff;
  border-radius: 20rpx;
  padding: 24rpx;
  box-shadow: 0 2rpx 12rpx rgba(0, 0, 0, 0.04);
}

.distribution-row {
  display: flex;
  justify-content: space-between;
}

.dist-item {
  flex: 1;
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
  display: flex;
  align-items: flex-end;
}

.dist-bar {
  width: 100%;
  border-radius: 8rpx;
}

.dist-percent {
  font-size: 22rpx;
  color: #6B7280;
}

.dist-label {
  font-size: 24rpx;
  color: #374151;
}

.hezhi-card,
.span-card {
  background: #fff;
  border-radius: 20rpx;
  padding: 24rpx;
  margin-top: 20rpx;
  box-shadow: 0 2rpx 12rpx rgba(0, 0, 0, 0.04);
}

.hezhi-summary,
.span-summary {
  display: flex;
  justify-content: space-around;
  padding-bottom: 20rpx;
  border-bottom: 2rpx solid #F3F4F6;
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
  font-size: 24rpx;
  color: #6B7280;
}

.hezhi-value,
.span-value {
  font-size: 32rpx;
  font-weight: bold;
  color: #1F2937;
}

.hezhi-value.positive {
  color: #10B981;
}

.hezhi-value.negative {
  color: #EF4444;
}

.hezhi-distribution,
.span-distribution {
  padding-top: 20rpx;
}

.dist-title {
  font-size: 26rpx;
  font-weight: bold;
  color: #1F2937;
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
  gap: 16rpx;
}

.bar-label {
  width: 80rpx;
  font-size: 22rpx;
  color: #6B7280;
}

.bar-wrapper {
  flex: 1;
  height: 24rpx;
  background: #F3F4F6;
  border-radius: 12rpx;
  overflow: hidden;
}

.bar-fill {
  height: 100%;
  border-radius: 12rpx;
}

.bar-value {
  width: 80rpx;
  font-size: 22rpx;
  color: #6B7280;
  text-align: right;
}

.span-grid {
  display: flex;
  justify-content: space-between;
}

.span-cell {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8rpx;
}

.span-num {
  font-size: 24rpx;
  color: #374151;
}

.span-bar-wrapper {
  width: 30rpx;
  height: 100rpx;
  background: #F3F4F6;
  border-radius: 15rpx;
  display: flex;
  align-items: flex-end;
}

.span-bar {
  width: 100%;
  border-radius: 15rpx;
}

.span-prob {
  font-size: 18rpx;
  color: #6B7280;
}

.strategy-section {
  margin-top: 20rpx;
}

.strategy-list {
  display: flex;
  flex-direction: column;
  gap: 16rpx;
}

.strategy-item {
  background: #fff;
  border-radius: 16rpx;
  padding: 20rpx;
  display: flex;
  gap: 16rpx;
  box-shadow: 0 2rpx 12rpx rgba(0, 0, 0, 0.04);
}

.strategy-icon-wrapper {
  width: 56rpx;
  height: 56rpx;
  border-radius: 14rpx;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.strategy-icon {
  font-size: 28rpx;
  font-weight: bold;
}

.strategy-content {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 8rpx;
}

.strategy-title {
  font-size: 28rpx;
  font-weight: bold;
  color: #1F2937;
}

.strategy-desc {
  font-size: 24rpx;
  color: #6B7280;
  line-height: 1.5;
}

.disclaimer-section {
  background: #FEF3C7;
  border-radius: 16rpx;
  padding: 24rpx;
  margin-top: 30rpx;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 12rpx;
}

.disclaimer-icon {
  width: 48rpx;
  height: 48rpx;
  border-radius: 50%;
  background: #F59E0B;
  color: #fff;
  font-size: 24rpx;
  font-weight: bold;
  display: flex;
  align-items: center;
  justify-content: center;
}

.disclaimer-title {
  font-size: 28rpx;
  font-weight: bold;
  color: #D97706;
}

.disclaimer-content {
  font-size: 24rpx;
  color: #92400E;
  text-align: center;
  line-height: 1.6;
}
</style>
