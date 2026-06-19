export const lotteryTypes = [
  {
    id: 'qixingcai',
    name: '七星彩',
    enName: 'DATA 7',
    icon: '7',
    description: '6位主号 + 1位特别号',
    color: '#3B82F6',
    bgColor: '#EFF6FF',
    gradient: 'linear-gradient(135deg, #3B82F6, #1D4ED8)',
    numberCount: 6,
    hasSpecial: true
  },
  {
    id: 'pailiewu',
    name: '排列五',
    enName: 'DATA 5',
    icon: '5',
    description: '5位直选号码',
    color: '#8B5CF6',
    bgColor: '#F5F3FF',
    gradient: 'linear-gradient(135deg, #8B5CF6, #6D28D9)',
    numberCount: 5,
    hasSpecial: false
  }
]

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
