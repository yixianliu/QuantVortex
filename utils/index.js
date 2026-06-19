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

export function getNumbersFromApiData(item, numberCount = 6, hasSpecial = true) {
  const nums = []
  for (let i = 1; i <= numberCount; i++) {
    if (item[`num${i}`] !== undefined) {
      nums.push(item[`num${i}`])
    }
  }
  return {
    main: nums,
    special: hasSpecial && item.special_num !== undefined ? item.special_num : null
  }
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

export function getStrategyList(lotteryType) {
  const strategies = {
    qixingcai: [
      { icon: '↑', title: '热号策略', desc: '选择近期出现频率较高的号码，把握数据趋势' },
      { icon: '↓', title: '冷号策略', desc: '关注遗漏值较大的号码，等待回补机会' },
      { icon: '◇', title: '均衡策略', desc: '结合冷热号码，平衡风险与收益' },
      { icon: 'Σ', title: '和值分析', desc: '根据历史和值分布选择合适的号码组合' },
      { icon: '↔', title: '跨度策略', desc: '分析号码跨度，选择合理的号码范围' }
    ],
    pailiewu: [
      { icon: '↑', title: '热号策略', desc: '选择近期出现频率较高的号码，把握数据趋势' },
      { icon: '↓', title: '冷号策略', desc: '关注遗漏值较大的号码，等待回补机会' },
      { icon: '◇', title: '均衡策略', desc: '结合冷热号码，平衡风险与收益' },
      { icon: 'Σ', title: '和值分析', desc: '根据历史和值分布选择合适的号码组合' },
      { icon: '×', title: '定位策略', desc: '分析各位号码走势，精准定位选号' }
    ]
  }

  return strategies[lotteryType] || strategies.qixingcai
}

  export function processHotColdNumbers(positionAnalysis) {
  if (!positionAnalysis) return { hotNumbers: [], coldNumbers: [] }

    const hotMap = {}
  const coldMap = {}
    
    Object.values(positionAnalysis).forEach(pos => {
    (pos.hot_numbers || []).forEach(num => {
        hotMap[num] = (hotMap[num] || 0) + 1
      })
        os.cold_numbers || []).forEach(num => {
        coldMap[num] = (coldMap[num] || 0) + 1
        })
          
        
    const hotNumbers = Object.entries(hotMap)
    .map(([num, count]) => ({ num: parseInt(num), count }))
      .sort((a, b) => b.count - a.count)
      
      nst coldNumbers = Object.entries(coldMap)
    .map(([num, count]) => ({ num: parseInt(num), count }))
      .sort((a, b) => a.count - b.count)
      
      turn { hotNumbers, coldNumbers }
}
    
  export function parseReportData(apiData) {
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
          
          zhi: null,
        span: null,
        strategy: getStrategyList('qixingcai')
        
        
      
    generatedReports.forEach(report => {
    if (report.type === 'optimal') {
        result.confidence = Math.round((report.confidence_score || 0) * 100)
        if (report.recommended_numbers) {
          const nums = report.recommended_numbers.split(',').map(n => parseInt(n.trim()))
          nums.forEach((num, index) => {
            if (index < 6) {
              result.recommendedNumbers[`num${index + 1}`] = num
            } else {
              result.recommendedNumbers.special_num = num
            }
              
            
          
        
      
    return result
}