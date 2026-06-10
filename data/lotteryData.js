export const lotteryTypes = [
  {
    id: 'dataGroupA',
    name: 'SHUANG SE QIU',
    icon: '📊',
    description: 'GROUP A: 1-33 SELECT 6, 1-16 SELECT 1',
    color: '#1E88E5',
    bgColor: '#E3F2FD'
  },
  {
    id: 'dataGroupB',
    name: 'DA LE TOU',
    icon: '📈',
    description: 'GROUP B: 1-35 SELECT 5, 1-12 SELECT 2',
    color: '#43A047',
    bgColor: '#E8F5E9'
  },
  {
    id: 'dataGroupC',
    name: 'FU CAI 3D',
    icon: '📉',
    description: 'GROUP C: HUNDRED, TENS, UNITS 0-9',
    color: '#7B1FA2',
    bgColor: '#F3E5F5'
  }
]

function generateDataGroupAHistory() {
  const history = []
  for (let i = 1; i <= 20; i++) {
    const group1 = []
    while (group1.length < 6) {
      const num = Math.floor(Math.random() * 33) + 1
      if (!group1.includes(num)) group1.push(num)
    }
    group1.sort((a, b) => a - b)
    history.push({
      issue: `2024${String(i).padStart(3, '0')}`,
      group1,
      group2: Math.floor(Math.random() * 16) + 1,
      date: `2024-${String(Math.floor(Math.random() * 12) + 1).padStart(2, '0')}-${String(Math.floor(Math.random() * 28) + 1).padStart(2, '0')}`
    })
  }
  return history
}

function generateDataGroupBHistory() {
  const history = []
  for (let i = 1; i <= 20; i++) {
    const group1 = []
    while (group1.length < 5) {
      const num = Math.floor(Math.random() * 35) + 1
      if (!group1.includes(num)) group1.push(num)
    }
    group1.sort((a, b) => a - b)
    const group2 = []
    while (group2.length < 2) {
      const num = Math.floor(Math.random() * 12) + 1
      if (!group2.includes(num)) group2.push(num)
    }
    group2.sort((a, b) => a - b)
    history.push({
      issue: `2024${String(i).padStart(3, '0')}`,
      group1,
      group2,
      date: `2024-${String(Math.floor(Math.random() * 12) + 1).padStart(2, '0')}-${String(Math.floor(Math.random() * 28) + 1).padStart(2, '0')}`
    })
  }
  return history
}

function generateDataGroupCHistory() {
  const history = []
  for (let i = 1; i <= 20; i++) {
    history.push({
      issue: `2024${String(i).padStart(3, '0')}`,
      num1: Math.floor(Math.random() * 10),
      num2: Math.floor(Math.random() * 10),
      num3: Math.floor(Math.random() * 10),
      date: `2024-${String(Math.floor(Math.random() * 12) + 1).padStart(2, '0')}-${String(Math.floor(Math.random() * 28) + 1).padStart(2, '0')}`
    })
  }
  return history
}

export const lotteryHistory = {
  dataGroupA: generateDataGroupAHistory(),
  dataGroupB: generateDataGroupBHistory(),
  dataGroupC: generateDataGroupCHistory()
}

export const prizeLevels = {
  dataGroupA: [
    { level: 'LEVEL 1', match: '6+1', prize: 'MAX 10,000,000', probability: '1/17,721,088' },
    { level: 'LEVEL 2', match: '6+0', prize: 'FLOATING', probability: '1/1,181,406' },
    { level: 'LEVEL 3', match: '5+1', prize: '3,000', probability: '1/109,389' },
    { level: 'LEVEL 4', match: '5+0/4+1', prize: '200', probability: '1/7,509' },
    { level: 'LEVEL 5', match: '4+0/3+1', prize: '10', probability: '1/542' },
    { level: 'LEVEL 6', match: '2+1/1+1/0+1', prize: '5', probability: '1/16' }
  ],
  dataGroupB: [
    { level: 'LEVEL 1', match: '5+2', prize: 'MAX 10,000,000', probability: '1/21,425,712' },
    { level: 'LEVEL 2', match: '5+1', prize: 'FLOATING', probability: '1/1,071,286' },
    { level: 'LEVEL 3', match: '5+0', prize: '10,000', probability: '1/476,127' },
    { level: 'LEVEL 4', match: '4+2', prize: '3,000', probability: '1/142,838' },
    { level: 'LEVEL 5', match: '4+1', prize: '500', probability: '1/14,284' },
    { level: 'LEVEL 6', match: '3+2/4+0', prize: '200', probability: '1/3,439' },
    { level: 'LEVEL 7', match: '3+1/2+2', prize: '10', probability: '1/830' },
    { level: 'LEVEL 8', match: '3+0/2+1/1+2/0+2', prize: '5', probability: '1/61' }
  ],
  dataGroupC: [
    { level: 'DIRECT', match: '3 MATCH', prize: '1,000', probability: '1/1,000' },
    { level: 'GROUP 3', match: '2 MATCH', prize: '320', probability: '1/333' },
    { level: 'GROUP 6', match: 'NO ORDER', prize: '160', probability: '1/167' }
  ]
}
