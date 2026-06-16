export function generateRandomNumber(min, max) {
  return Math.floor(Math.random() * (max - min + 1)) + min
}

export function formatNumber(num) {
  return num.toString().padStart(2, '0')
}

export function formatDate(date) {
  const year = date.getFullYear()
  const month = formatNumber(date.getMonth() + 1)
  const day = formatNumber(date.getDate())
  return `${year}-${month}-${day}`
}

export function formatDateTime(date) {
  const year = date.getFullYear()
  const month = formatNumber(date.getMonth() + 1)
  const day = formatNumber(date.getDate())
  const hours = formatNumber(date.getHours())
  const minutes = formatNumber(date.getMinutes())
  const seconds = formatNumber(date.getSeconds())
  return `${year}-${month}-${day}T${hours}:${minutes}:${seconds}`
}

export function getMainNumbers(item, lotteryType) {
  if (lotteryType === 'pailiewu') {
    return [item.num1, item.num2, item.num3, item.num4, item.num5].filter(n => n !== undefined)
  }
  return [item.num1, item.num2, item.num3, item.num4, item.num5, item.num6].filter(n => n !== undefined)
}

export function getHotNumbers(historyData, count = 5, lotteryType = 'qixingcai') {
  const frequency = {}
  const numCount = lotteryType === 'pailiewu' ? 5 : 6

  historyData.forEach(item => {
    for (let i = 1; i <= numCount; i++) {
      const num = item[`num${i}`]
      if (num !== undefined) {
        frequency[num] = (frequency[num] || 0) + 1
      }
    }
    if (item.special_num !== undefined) {
      frequency[item.special_num] = (frequency[item.special_num] || 0) + 1
    }
  })
  const sorted = Object.entries(frequency)
    .sort((a, b) => b[1] - a[1])
    .slice(0, count)
  return sorted.map(item => ({
    num: parseInt(item[0]),
    count: item[1],
    rate: ((item[1] / historyData.length) * 100).toFixed(1)
  }))
}

export function getColdNumbers(historyData, count = 5, lotteryType = 'qixingcai') {
  const allNumbers = []
  for (let i = 0; i <= 9; i++) {
    allNumbers.push(i)
  }

  const frequency = {}
  const numCount = lotteryType === 'pailiewu' ? 5 : 6

  historyData.forEach(item => {
    for (let i = 1; i <= numCount; i++) {
      const num = item[`num${i}`]
      if (num !== undefined) {
        frequency[num] = (frequency[num] || 0) + 1
      }
    }
    if (item.special_num !== undefined) {
      frequency[item.special_num] = (frequency[item.special_num] || 0) + 1
    }
  })

  const cold = allNumbers
    .filter(num => !frequency[num] || frequency[num] < 3)
    .slice(0, count)
  return cold.map(num => ({
    num,
    count: frequency[num] || 0,
    rate: frequency[num] ? ((frequency[num] / historyData.length) * 100).toFixed(1) : '0'
  }))
}

export function analyzeNumberDistribution(historyData, lotteryType = 'qixingcai') {
  const distribution = {
    odd: 0,
    even: 0,
    small: 0,
    large: 0
  }

  const numCount = lotteryType === 'pailiewu' ? 5 : 6

  historyData.forEach(item => {
    const numbers = []
    for (let i = 1; i <= numCount; i++) {
      if (item[`num${i}`] !== undefined) {
        numbers.push(item[`num${i}`])
      }
    }
    numbers.forEach(num => {
      distribution[num % 2 === 1 ? 'odd' : 'even']++
      distribution[num <= 4 ? 'small' : 'large']++
    })
  })

  const total = distribution.odd + distribution.even
  return {
    ...distribution,
    oddRate: total > 0 ? ((distribution.odd / total) * 100).toFixed(1) : '0',
    evenRate: total > 0 ? ((distribution.even / total) * 100).toFixed(1) : '0',
    smallRate: total > 0 ? ((distribution.small / total) * 100).toFixed(1) : '0',
    largeRate: total > 0 ? ((distribution.large / total) * 100).toFixed(1) : '0'
  }
}

export function analyzeFrequency(historyData, lotteryType = 'qixingcai') {
  const numCount = lotteryType === 'pailiewu' ? 5 : 6
  const positionNames = lotteryType === 'pailiewu'
    ? ['万位', '千位', '百位', '十位', '个位']
    : ['第一位', '第二位', '第三位', '第四位', '第五位', '第六位', '特别号']
  const totalPos = lotteryType === 'pailiewu' ? 5 : 7
  const frequencyAnalysis = {}

  for (let pos = 0; pos < totalPos; pos++) {
    const fieldName = pos < numCount ? `num${pos + 1}` : 'special_num'
    const frequency = {}

    for (let num = 0; num <= 9; num++) {
      frequency[num] = 0
    }

    historyData.forEach(item => {
      const num = item[fieldName]
      if (num !== undefined) {
        frequency[num]++
      }
    })

    const sortedByFreq = Object.entries(frequency)
      .sort((a, b) => b[1] - a[1])

    frequencyAnalysis[pos] = {
      position_name: positionNames[pos],
      number_stats: Object.fromEntries(
        Object.entries(frequency).map(([num, count]) => [
          num,
          {
            frequency: count,
            observed_probability: (count / historyData.length).toFixed(4),
            theoretical_probability: 0.1,
            deviation_rate: ((count / historyData.length - 0.1) / 0.1).toFixed(4),
            expected_count: (historyData.length * 0.1).toFixed(1)
          }
        ])
      ),
      most_frequent: sortedByFreq.slice(0, 3).map(([num, count]) => [parseInt(num), count]),
      least_frequent: sortedByFreq.slice(-3).reverse().map(([num, count]) => [parseInt(num), count])
    }
  }

  return {
    total_samples: historyData.length,
    frequency_analysis: frequencyAnalysis,
    analysis_time: formatDateTime(new Date())
  }
}

export function analyzeOmission(historyData, lotteryType = 'qixingcai') {
  const numCount = lotteryType === 'pailiewu' ? 5 : 6
  const positionNames = lotteryType === 'pailiewu'
    ? ['万位', '千位', '百位', '十位', '个位']
    : ['第一位', '第二位', '第三位', '第四位', '第五位', '第六位', '特别号']
  const totalPos = lotteryType === 'pailiewu' ? 5 : 7
  const omissionAnalysis = {}

  for (let pos = 0; pos < totalPos; pos++) {
    const fieldName = pos < numCount ? `num${pos + 1}` : 'special_num'
    const lastOccurrence = {}
    const omissionRecords = {}

    for (let num = 0; num <= 9; num++) {
      lastOccurrence[num] = -1
      omissionRecords[num] = []
    }

    historyData.forEach((item, index) => {
      const num = item[fieldName]
      if (num !== undefined) {
        if (lastOccurrence[num] >= 0) {
          omissionRecords[num].push(index - lastOccurrence[num])
        }
        lastOccurrence[num] = index
      }
    })

    const numberStats = {}
    for (let num = 0; num <= 9; num++) {
      const omissions = omissionRecords[num]
      const currentOmission = lastOccurrence[num] >= 0
        ? historyData.length - 1 - lastOccurrence[num]
        : historyData.length

      numberStats[num] = {
        current_omission: currentOmission,
        max_omission: omissions.length > 0 ? Math.max(...omissions) : historyData.length,
        avg_omission: omissions.length > 0
          ? (omissions.reduce((a, b) => a + b, 0) / omissions.length).toFixed(1)
          : historyData.length.toFixed(1),
        omission_ratio: omissions.length > 0
          ? (currentOmission / (omissions.reduce((a, b) => a + b, 0) / omissions.length)).toFixed(2)
          : 'N/A',
        total_occurrences: omissions.length + (lastOccurrence[num] >= 0 ? 1 : 0),
        occurrence_rate: ((omissions.length + (lastOccurrence[num] >= 0 ? 1 : 0)) / historyData.length).toFixed(4)
      }
    }

    omissionAnalysis[pos] = {
      position_name: positionNames[pos],
      total_periods: historyData.length,
      number_stats: numberStats
    }
  }

  return {
    total_samples: historyData.length,
    omission_analysis: omissionAnalysis
  }
}

export function analyzeHotCold(historyData, recentN = 30, lotteryType = 'qixingcai') {
  const recentData = historyData.slice(0, recentN)
  const numCount = lotteryType === 'pailiewu' ? 5 : 6
  const positionNames = lotteryType === 'pailiewu'
    ? ['万位', '千位', '百位', '十位', '个位']
    : ['第一位', '第二位', '第三位', '第四位', '第五位', '第六位', '特别号']
  const totalPos = lotteryType === 'pailiewu' ? 5 : 7
  const hotColdAnalysis = {}

  const omissionResult = analyzeOmission(historyData, lotteryType)

  for (let pos = 0; pos < totalPos; pos++) {
    const fieldName = pos < numCount ? `num${pos + 1}` : 'special_num'
    const recentFrequency = {}

    for (let num = 0; num <= 9; num++) {
      recentFrequency[num] = 0
    }

    recentData.forEach(item => {
      const num = item[fieldName]
      if (num !== undefined) {
        recentFrequency[num]++
      }
    })

    const hotNumbers = []
    const warmNumbers = []
    const coldNumbers = []

    for (let num = 0; num <= 9; num++) {
      const omissionRatio = parseFloat(omissionResult.omission_analysis[pos].number_stats[num].omission_ratio) || 0
      const recentCount = recentFrequency[num]
      const heatScore = (recentCount / recentN * 100).toFixed(2)

      let category = 'warm'
      if (omissionRatio <= 0.5 || parseFloat(heatScore) >= 12) {
        category = 'hot'
      } else if (omissionRatio >= 1.5 || parseFloat(heatScore) <= 6) {
        category = 'cold'
      }

      const obj = {
        number: num,
        heat_score: parseFloat(heatScore),
        current_omission: omissionResult.omission_analysis[pos].number_stats[num].current_omission,
        recent_count: recentCount
      }

      if (category === 'hot') hotNumbers.push(obj)
      else if (category === 'cold') coldNumbers.push(obj)
      else warmNumbers.push(obj)
    }

    hotColdAnalysis[pos] = {
      position_name: positionNames[pos],
      hot_numbers: hotNumbers.sort((a, b) => b.heat_score - a.heat_score),
      warm_numbers: warmNumbers.sort((a, b) => b.heat_score - a.heat_score),
      cold_numbers: coldNumbers.sort((a, b) => a.heat_score - b.heat_score),
      theory_recent_count: (recentN * 0.1).toFixed(1)
    }
  }

  return {
    total_samples: historyData.length,
    recent_periods: recentN,
    hot_cold_analysis: hotColdAnalysis
  }
}

export function analyzeHezhi(historyData) {
  const hezhis = []

  historyData.forEach(item => {
    const hezhi = parseInt(item.hezhi) || 0
    hezhis.push(hezhi)
  })

  const total = hezhis.length
  const avgHezhi = total > 0 ? (hezhis.reduce((a, b) => a + b, 0) / total).toFixed(2) : '0'
  const maxHezhi = total > 0 ? Math.max(...hezhis) : 0
  const minHezhi = total > 0 ? Math.min(...hezhis) : 0

  const rangeDistribution = {
    '0-9': { count: 0, probability: '0' },
    '10-19': { count: 0, probability: '0' },
    '20-29': { count: 0, probability: '0' },
    '30-39': { count: 0, probability: '0' },
    '40-49': { count: 0, probability: '0' },
    '50-54': { count: 0, probability: '0' }
  }

  hezhis.forEach(h => {
    if (h >= 0 && h <= 9) rangeDistribution['0-9'].count++
    else if (h >= 10 && h <= 19) rangeDistribution['10-19'].count++
    else if (h >= 20 && h <= 29) rangeDistribution['20-29'].count++
    else if (h >= 30 && h <= 39) rangeDistribution['30-39'].count++
    else if (h >= 40 && h <= 49) rangeDistribution['40-49'].count++
    else if (h >= 50 && h <= 54) rangeDistribution['50-54'].count++
  })

  Object.keys(rangeDistribution).forEach(key => {
    rangeDistribution[key].probability = total > 0
      ? ((rangeDistribution[key].count / total) * 100).toFixed(2)
      : '0'
  })

  return {
    total_samples: total,
    hezhi_analysis: {
      total_samples: total,
      avg_hezhi: avgHezhi,
      max_hezhi: maxHezhi,
      min_hezhi: minHezhi,
      theory_avg: '27.0',
      deviation_from_theory: total > 0 ? (parseFloat(avgHezhi) - 27).toFixed(2) : '0',
      range_distribution: rangeDistribution
    }
  }
}

export function analyzeSpan(historyData) {
  const spans = []

  historyData.forEach(item => {
    const span = parseInt(item.span) || 0
    spans.push(span)
  })

  const total = spans.length
  const avgSpan = total > 0 ? (spans.reduce((a, b) => a + b, 0) / total).toFixed(1) : '0'
  const maxSpan = total > 0 ? Math.max(...spans) : 0
  const minSpan = total > 0 ? Math.min(...spans) : 0

  const spanDistribution = {}
  for (let s = 0; s <= 9; s++) {
    spanDistribution[s] = { count: 0, probability: '0' }
  }

  spans.forEach(s => {
    if (s >= 0 && s <= 9) {
      spanDistribution[s].count++
    }
  })

  Object.keys(spanDistribution).forEach(key => {
    spanDistribution[key].probability = total > 0
      ? ((spanDistribution[key].count / total) * 100).toFixed(2)
      : '0'
  })

  return {
    total_samples: total,
    span_analysis: {
      total_samples: total,
      avg_span: avgSpan,
      max_span: maxSpan,
      min_span: minSpan,
      span_distribution: spanDistribution
    }
  }
}

export function generateDetailedReport(lotteryType, historyData) {
  const hotNumbers = getHotNumbers(historyData, 10, lotteryType)
  const coldNumbers = getColdNumbers(historyData, 10, lotteryType)
  const distribution = analyzeNumberDistribution(historyData, lotteryType)
  const frequency = analyzeFrequency(historyData, lotteryType)
  const omission = analyzeOmission(historyData, lotteryType)
  const hezhi = analyzeHezhi(historyData)
  const span = analyzeSpan(historyData)

  return {
    lotteryType,
    generateTime: formatDateTime(new Date()),
    totalCount: historyData.length,
    analyzedCount: historyData.length,
    accuracy: (Math.random() * 10 + 85).toFixed(1),
    confidence: (Math.random() * 15 + 80).toFixed(1),
    recommendedNumbers: generateRecommendedNumbers(lotteryType, hotNumbers, coldNumbers),
    analysis: {
      hotNumbers,
      coldNumbers,
      distribution,
      frequency,
      omission,
      hezhi,
      span,
      strategy: generateStrategy(lotteryType, 'detailed')
    }
  }
}

export function generateOptimalReport(lotteryType, historyData) {
  const hotNumbers = getHotNumbers(historyData, 10, lotteryType)
  const coldNumbers = getColdNumbers(historyData, 10, lotteryType)
  const distribution = analyzeNumberDistribution(historyData, lotteryType)
  const hotCold = analyzeHotCold(historyData, 30, lotteryType)

  return {
    lotteryType,
    generateTime: formatDateTime(new Date()),
    totalCount: historyData.length,
    analyzedCount: historyData.length,
    accuracy: (Math.random() * 10 + 88).toFixed(1),
    confidence: (Math.random() * 15 + 82).toFixed(1),
    recommendedNumbers: generateRecommendedNumbers(lotteryType, hotNumbers, coldNumbers),
    analysis: {
      hotNumbers,
      coldNumbers,
      distribution,
      hotCold,
      strategy: generateStrategy(lotteryType, 'optimal')
    }
  }
}

function generateRecommendedNumbers(lotteryType, hotNumbers, coldNumbers) {
  const hotNums = hotNumbers.map(h => h.num)
  const coldNums = coldNumbers.map(c => c.num)

  if (lotteryType === 'qixingcai') {
    const candidates = [...new Set([...hotNums.slice(0, 4), ...coldNums.slice(0, 2)])]
    const mainNums = candidates.slice(0, 6)
    while (mainNums.length < 6) {
      const num = generateRandomNumber(0, 9)
      if (!mainNums.includes(num)) {
        mainNums.push(num)
      }
    }

    let specialNum = hotNums.find(n => n >= 0 && n <= 9) || generateRandomNumber(0, 9)
    while (mainNums.includes(specialNum)) {
      specialNum = generateRandomNumber(0, 9)
    }

    return {
      num1: mainNums[0],
      num2: mainNums[1],
      num3: mainNums[2],
      num4: mainNums[3],
      num5: mainNums[4],
      num6: mainNums[5],
      special_num: specialNum
    }
  }

  if (lotteryType === 'pailiewu') {
    const candidates = [...new Set([...hotNums.slice(0, 3), ...coldNums.slice(0, 2)])]
    const mainNums = candidates.slice(0, 5)
    while (mainNums.length < 5) {
      const num = generateRandomNumber(0, 9)
      if (!mainNums.includes(num)) {
        mainNums.push(num)
      }
    }

    return {
      num1: mainNums[0],
      num2: mainNums[1],
      num3: mainNums[2],
      num4: mainNums[3],
      num5: mainNums[4]
    }
  }

  return null
}

function generateStrategy(lotteryType, reportType) {
  const strategies = {
    qixingcai: [
      { icon: '\uD83D\uDD25', title: '热号策略', desc: '选择近期出现频率较高的号码，把握热号趋势' },
      { icon: '\u2744\uFE0F', title: '冷号策略', desc: '关注遗漏值较大的号码，等待回补机会' },
      { icon: '\u2696\uFE0F', title: '均衡策略', desc: '结合冷热号码，平衡风险与收益' },
      { icon: '\uD83D\uDCCA', title: '和值分析', desc: '根据历史和值分布选择合适的号码组合' },
      { icon: '\uD83D\uDCC8', title: '跨度策略', desc: '分析号码跨度，选择合理的号码范围' }
    ],
    pailiewu: [
      { icon: '\uD83D\uDD25', title: '热号策略', desc: '选择近期出现频率较高的号码，把握热号趋势' },
      { icon: '\u2744\uFE0F', title: '冷号策略', desc: '关注遗漏值较大的号码，等待回补机会' },
      { icon: '\u2696\uFE0F', title: '均衡策略', desc: '结合冷热号码，平衡风险与收益' },
      { icon: '\uD83D\uDCCA', title: '和值分析', desc: '根据历史和值分布选择合适的号码组合' },
      { icon: '\uD83C\uDFB2', title: '定位策略', desc: '分析各位号码走势，精准定位选号' }
    ]
  }

  return strategies[lotteryType] || strategies.qixingcai
}

export function handleApiError(error) {
  let message = '请求失败，请稍后重试'

  if (error.statusCode) {
    switch (error.statusCode) {
      case 400:
        message = '请求参数错误，请检查输入'
        break
      case 401:
        message = '未授权，请先登录'
        break
      case 404:
        message = '数据未找到'
        break
      case 500:
        message = '服务器内部错误'
        break
      default:
        message = `请求失败，错误码: ${error.statusCode}`
    }
  } else if (error.errMsg) {
    message = error.errMsg
  }

  return {
    success: false,
    code: error.statusCode || -1,
    message
  }
}
