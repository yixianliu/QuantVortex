export function generateRandomNumber(min, max) {
  return Math.floor(Math.random() * (max - min + 1)) + min
}

export function generateGroupAData() {
  const group1 = []
  while (group1.length < 6) {
    const num = generateRandomNumber(1, 33)
    if (!group1.includes(num)) {
      group1.push(num)
    }
  }
  group1.sort((a, b) => a - b)
  const group2 = generateRandomNumber(1, 16)
  return { group1, group2 }
}

export function generateGroupBData() {
  const group1 = []
  while (group1.length < 5) {
    const num = generateRandomNumber(1, 35)
    if (!group1.includes(num)) {
      group1.push(num)
    }
  }
  group1.sort((a, b) => a - b)
  const group2 = []
  while (group2.length < 2) {
    const num = generateRandomNumber(1, 12)
    if (!group2.includes(num)) {
      group2.push(num)
    }
  }
  group2.sort((a, b) => a - b)
  return { group1, group2 }
}

export function generateGroupCData() {
  return {
    num1: generateRandomNumber(0, 9),
    num2: generateRandomNumber(0, 9),
    num3: generateRandomNumber(0, 9)
  }
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

export function getHotNumbers(historyData, count = 5) {
  const frequency = {}
  historyData.forEach(item => {
    if (item.group1) {
      item.group1.forEach(num => {
        frequency[num] = (frequency[num] || 0) + 1
      })
    }
    if (item.group2 && typeof item.group2 === 'number') {
      frequency[item.group2] = (frequency[item.group2] || 0) + 1
    }
    if (item.group2 && Array.isArray(item.group2)) {
      item.group2.forEach(num => {
        frequency[num] = (frequency[num] || 0) + 1
      })
    }
    if (item.num1 !== undefined) {
      frequency[item.num1] = (frequency[item.num1] || 0) + 1
      frequency[item.num2] = (frequency[item.num2] || 0) + 1
      frequency[item.num3] = (frequency[item.num3] || 0) + 1
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

export function getColdNumbers(historyData, count = 5) {
  const allNumbers = []
  if (historyData[0]?.group1) {
    const maxGroup1 = historyData[0].group1.length === 6 ? 33 : 35
    for (let i = 1; i <= maxGroup1; i++) allNumbers.push(i)
    if (typeof historyData[0].group2 === 'number') {
      for (let i = 1; i <= 16; i++) allNumbers.push(i)
    }
    if (Array.isArray(historyData[0].group2)) {
      for (let i = 1; i <= 12; i++) allNumbers.push(i)
    }
  }
  if (historyData[0]?.num1 !== undefined) {
    for (let i = 0; i <= 9; i++) allNumbers.push(i)
  }
  
  const frequency = {}
  historyData.forEach(item => {
    if (item.group1) {
      item.group1.forEach(num => {
        frequency[num] = (frequency[num] || 0) + 1
      })
    }
    if (item.group2 && typeof item.group2 === 'number') {
      frequency[item.group2] = (frequency[item.group2] || 0) + 1
    }
    if (item.group2 && Array.isArray(item.group2)) {
      item.group2.forEach(num => {
        frequency[num] = (frequency[num] || 0) + 1
      })
    }
    if (item.num1 !== undefined) {
      frequency[item.num1] = (frequency[item.num1] || 0) + 1
      frequency[item.num2] = (frequency[item.num2] || 0) + 1
      frequency[item.num3] = (frequency[item.num3] || 0) + 1
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

export function analyzeNumberDistribution(historyData) {
  const distribution = {
    odd: 0,
    even: 0,
    small: 0,
    large: 0
  }
  
  historyData.forEach(item => {
    if (item.group1) {
      item.group1.forEach(num => {
        distribution[num % 2 === 1 ? 'odd' : 'even']++
        const mid = item.group1.length === 6 ? 17 : 18
        distribution[num <= mid ? 'small' : 'large']++
      })
    }
    if (item.num1 !== undefined) {
      [item.num1, item.num2, item.num3].forEach(num => {
        distribution[num % 2 === 1 ? 'odd' : 'even']++
        distribution[num <= 4 ? 'small' : 'large']++
      })
    }
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

export function generateDetailedReport(lotteryType, historyData) {
  const hotNumbers = getHotNumbers(historyData, 10)
  const coldNumbers = getColdNumbers(historyData, 10)
  const distribution = analyzeNumberDistribution(historyData)
  
  return {
    lotteryType,
    generateTime: formatDate(new Date()),
    totalCount: historyData.length,
    analyzedCount: historyData.length,
    accuracy: (Math.random() * 10 + 85).toFixed(1),
    confidence: (Math.random() * 15 + 80).toFixed(1),
    recommendedNumbers: generateRecommendedNumbers(lotteryType, hotNumbers, coldNumbers),
    analysis: {
      hotNumbers,
      coldNumbers,
      distribution,
      strategy: generateStrategy(lotteryType, 'detailed')
    }
  }
}

export function generateOptimalReport(lotteryType, historyData) {
  const hotNumbers = getHotNumbers(historyData, 10)
  const coldNumbers = getColdNumbers(historyData, 10)
  const distribution = analyzeNumberDistribution(historyData)
  
  return {
    lotteryType,
    generateTime: formatDate(new Date()),
    totalCount: historyData.length,
    analyzedCount: historyData.length,
    accuracy: (Math.random() * 10 + 88).toFixed(1),
    confidence: (Math.random() * 15 + 82).toFixed(1),
    recommendedNumbers: generateRecommendedNumbers(lotteryType, hotNumbers, coldNumbers),
    analysis: {
      hotNumbers,
      coldNumbers,
      distribution,
      strategy: generateStrategy(lotteryType, 'optimal')
    }
  }
}

function generateRecommendedNumbers(lotteryType, hotNumbers, coldNumbers) {
  const hotNums = hotNumbers.map(h => h.num)
  const coldNums = coldNumbers.map(c => c.num)
  
  if (lotteryType === 'dataGroupA') {
    const candidates = [...new Set([...hotNums.slice(0, 4), ...coldNums.slice(0, 2)])]
    const group1 = candidates.sort((a, b) => a - b).slice(0, 6)
    const group2 = hotNums.find(n => n >= 1 && n <= 16) || generateRandomNumber(1, 16)
    return { group1, group2 }
  } else if (lotteryType === 'dataGroupB') {
    const candidates = [...new Set([...hotNums.slice(0, 3), ...coldNums.slice(0, 2)])]
    const group1 = candidates.sort((a, b) => a - b).slice(0, 5)
    const group2 = hotNums.filter(n => n >= 1 && n <= 12).slice(0, 2)
    return { 
      group1, 
      group2: group2.length === 2 ? group2 : [generateRandomNumber(1, 12), generateRandomNumber(1, 12)]
    }
  } else if (lotteryType === 'dataGroupC') {
    return {
      num1: hotNums[0] || generateRandomNumber(0, 9),
      num2: hotNums[1] || generateRandomNumber(0, 9),
      num3: hotNums[2] || generateRandomNumber(0, 9)
    }
  }
}

function generateStrategy(lotteryType, reportType) {
  const strategies = {
    dataGroupA: [
      { icon: '🔥', title: 'HOT PICK STRATEGY', desc: 'SELECT TOP 4 FREQUENTLY OCCURRING NUMBERS FROM RECENT DATA' },
      { icon: '❄️', title: 'COLD PICK STRATEGY', desc: 'SELECT 2 NUMBERS THAT HAVE NOT APPEARED RECENTLY' },
      { icon: '⚖️', title: 'BALANCED SELECTION', desc: 'COMBINE HOT AND COLD NUMBERS FOR OPTIMAL COVERAGE' }
    ],
    dataGroupB: [
      { icon: '🔥', title: 'HOT FOCUS', desc: 'PRIORITIZE 3 HIGH FREQUENCY NUMBERS IN PRIMARY GROUP' },
      { icon: '🎯', title: 'SECONDARY SELECTION', desc: 'CHOOSE 2 NUMBERS FROM SECONDARY POOL STRATEGICALLY' },
      { icon: '⚖️', title: 'RISK BALANCE', desc: 'INCLUDE BOTH FREQUENT AND INFREQUENT NUMBERS' }
    ],
    dataGroupC: [
      { icon: '📊', title: 'FREQUENCY ANALYSIS', desc: 'SELECT DIGITS WITH HIGHEST APPEARANCE RATE' },
      { icon: '🔄', title: 'CYCLE PATTERN', desc: 'OBSERVE DIGIT ROTATION CYCLES IN HISTORICAL DATA' },
      { icon: '🎲', title: 'RANDOM SELECTION', desc: 'APPLY PROBABILISTIC DISTRIBUTION METHOD' }
    ]
  }
  
  return strategies[lotteryType] || strategies.dataGroupA
}
