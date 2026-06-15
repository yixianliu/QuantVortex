"use strict";
const lotteryTypes = [
  {
    id: "dataGroupA",
    name: "PAI LIE WU",
    icon: "🎯",
    description: "排列五: 5 NUMBERS 0-9",
    color: "#1E88E5",
    bgColor: "#E3F2FD"
  },
  {
    id: "dataGroupB",
    name: "QI XING CAI",
    icon: "⭐",
    description: "七星彩: 6 MAIN + 1 SPECIAL",
    color: "#43A047",
    bgColor: "#E8F5E9"
  }
];
function generateDataGroupAHistory() {
  const history = [];
  for (let i = 1; i <= 20; i++) {
    history.push({
      issue: `2024${String(i).padStart(3, "0")}`,
      group1: Array.from({ length: 5 }, () => Math.floor(Math.random() * 10)),
      date: `2024-${String(Math.floor(Math.random() * 12) + 1).padStart(2, "0")}-${String(Math.floor(Math.random() * 28) + 1).padStart(2, "0")}`
    });
  }
  return history;
}
function generateDataGroupBHistory() {
  const history = [];
  for (let i = 1; i <= 20; i++) {
    const group1 = Array.from({ length: 6 }, () => Math.floor(Math.random() * 10));
    history.push({
      issue: `2024${String(i).padStart(3, "0")}`,
      group1,
      group2: Math.floor(Math.random() * 10),
      date: `2024-${String(Math.floor(Math.random() * 12) + 1).padStart(2, "0")}-${String(Math.floor(Math.random() * 28) + 1).padStart(2, "0")}`
    });
  }
  return history;
}
const lotteryHistory = {
  dataGroupA: generateDataGroupAHistory(),
  dataGroupB: generateDataGroupBHistory()
};
const prizeLevels = {
  dataGroupA: [
    { level: "LEVEL 1", match: "5 MATCH", prize: "100,000", probability: "1/100,000" },
    { level: "LEVEL 2", match: "4 MATCH", prize: "3,000", probability: "1/10,000" },
    { level: "LEVEL 3", match: "3 MATCH", prize: "200", probability: "1/1,000" },
    { level: "LEVEL 4", match: "2 MATCH", prize: "10", probability: "1/100" }
  ],
  dataGroupB: [
    { level: "LEVEL 1", match: "6+1", prize: "MAX 5,000,000", probability: "1/10,000,000" },
    { level: "LEVEL 2", match: "6+0", prize: "500,000", probability: "1/1,000,000" },
    { level: "LEVEL 3", match: "5+1", prize: "50,000", probability: "1/100,000" },
    { level: "LEVEL 4", match: "5+0", prize: "5,000", probability: "1/10,000" },
    { level: "LEVEL 5", match: "4+1", prize: "200", probability: "1/1,000" },
    { level: "LEVEL 6", match: "4+0/3+1", prize: "50", probability: "1/100" },
    { level: "LEVEL 7", match: "3+0/2+1", prize: "5", probability: "1/10" }
  ]
};
exports.lotteryHistory = lotteryHistory;
exports.lotteryTypes = lotteryTypes;
exports.prizeLevels = prizeLevels;
//# sourceMappingURL=../../.sourcemap/mp-weixin/data/lotteryData.js.map
