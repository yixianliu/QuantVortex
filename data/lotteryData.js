export const lotteryTypes = [
  {
    id: 'qixingcai',
    name: '七星彩',
    enName: 'QI XING CAI',
    icon: '\u2B50',
    description: '6位主号 + 1位特别号',
    color: '#43A047',
    bgColor: '#E8F5E9',
    gradient: 'linear-gradient(135deg, #43A047, #2E7D32)',
    numberCount: 6,
    hasSpecial: true
  },
  {
    id: 'pailiewu',
    name: '排列五',
    enName: 'PAI LIE WU',
    icon: '\uD83C\uDFB2',
    description: '5位直选号码',
    color: '#E53935',
    bgColor: '#FFEBEE',
    gradient: 'linear-gradient(135deg, #E53935, #C62828)',
    numberCount: 5,
    hasSpecial: false
  }
]

function calculateHezhi(numbers) {
  return numbers.reduce((sum, num) => sum + num, 0)
}

function calculateHezhiType(hezhi) {
  return hezhi % 2 === 0 ? '偶' : '奇'
}

function calculateOddEvenRatio(numbers) {
  const odd = numbers.filter(n => n % 2 === 1).length
  const even = numbers.length - odd
  return `${odd}:${even}`
}

function calculateOddEvenPattern(numbers) {
  return numbers.map(n => n % 2 === 1 ? 'O' : 'E').join('')
}

function calculateSpan(numbers) {
  const max = Math.max(...numbers)
  const min = Math.min(...numbers)
  return String(max - min)
}

function generateQixingCaiHistory() {
  const history = []
  const today = new Date()

  for (let i = 1; i <= 50; i++) {
    const date = new Date(today)
    date.setDate(date.getDate() - i)

    const num1 = Math.floor(Math.random() * 10)
    const num2 = Math.floor(Math.random() * 10)
    const num3 = Math.floor(Math.random() * 10)
    const num4 = Math.floor(Math.random() * 10)
    const num5 = Math.floor(Math.random() * 10)
    const num6 = Math.floor(Math.random() * 10)
    const special_num = Math.floor(Math.random() * 10)

    const mainNumbers = [num1, num2, num3, num4, num5, num6]
    const hezhi = calculateHezhi(mainNumbers)

    history.push({
      id: i,
      issue: `2026${String(i).padStart(3, '0')}`,
      draw_date: `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`,
      num1,
      num2,
      num3,
      num4,
      num5,
      num6,
      special_num,
      hezhi: String(hezhi),
      hezhi_type: calculateHezhiType(hezhi),
      odd_even_ratio: calculateOddEvenRatio(mainNumbers),
      odd_even_pattern: calculateOddEvenPattern(mainNumbers),
      span: calculateSpan(mainNumbers),
      created_at: `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}T20:30:00`,
      updated_at: `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}T20:30:00`
    })
  }
  return history
}

function generatePaiLieWuHistory() {
  const history = []
  const today = new Date()

  for (let i = 1; i <= 50; i++) {
    const date = new Date(today)
    date.setDate(date.getDate() - i)

    const num1 = Math.floor(Math.random() * 10)
    const num2 = Math.floor(Math.random() * 10)
    const num3 = Math.floor(Math.random() * 10)
    const num4 = Math.floor(Math.random() * 10)
    const num5 = Math.floor(Math.random() * 10)

    const mainNumbers = [num1, num2, num3, num4, num5]
    const hezhi = calculateHezhi(mainNumbers)

    history.push({
      id: i,
      issue: `2026${String(i).padStart(3, '0')}`,
      draw_date: `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`,
      num1,
      num2,
      num3,
      num4,
      num5,
      hezhi: String(hezhi),
      hezhi_type: calculateHezhiType(hezhi),
      odd_even_ratio: calculateOddEvenRatio(mainNumbers),
      odd_even_pattern: calculateOddEvenPattern(mainNumbers),
      span: calculateSpan(mainNumbers),
      created_at: `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}T20:30:00`,
      updated_at: `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}T20:30:00`
    })
  }
  return history
}

export const lotteryHistory = {
  qixingcai: generateQixingCaiHistory(),
  pailiewu: generatePaiLieWuHistory()
}

export const prizeLevels = {
  qixingcai: [
    { level: '一等奖', match: '6+1', prize: '最高500万', probability: '1/10,000,000' },
    { level: '二等奖', match: '6+0', prize: '50万', probability: '1/1,000,000' },
    { level: '三等奖', match: '5+1', prize: '5万', probability: '1/100,000' },
    { level: '四等奖', match: '5+0', prize: '5000', probability: '1/10,000' },
    { level: '五等奖', match: '4+1', prize: '200', probability: '1/1,000' },
    { level: '六等奖', match: '4+0/3+1', prize: '50', probability: '1/100' },
    { level: '七等奖', match: '3+0/2+1', prize: '5', probability: '1/10' }
  ],
  pailiewu: [
    { level: '一等奖', match: '5位全中', prize: '10万', probability: '1/100,000' },
    { level: '二等奖', match: '连续4位', prize: '5000', probability: '1/10,000' },
    { level: '三等奖', match: '连续3位', prize: '500', probability: '1/1,000' },
    { level: '四等奖', match: '连续2位', prize: '50', probability: '1/100' },
    { level: '五等奖', match: '中1位', prize: '5', probability: '1/10' }
  ]
}
