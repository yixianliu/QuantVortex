const BASE_URL = 'https://api.example.com/lottery'

const ERROR_CODES = {
  400: '请求参数错误，请检查输入',
  401: '未授权，请先登录',
  403: '权限不足，无法访问',
  404: '数据未找到',
  408: '请求超时，请重试',
  500: '服务器内部错误',
  502: '网关错误',
  503: '服务暂时不可用',
  504: '网关超时'
}

const BUSINESS_CODES = {
  'L001': '期号不存在',
  'L002': '数据解析失败',
  'L003': '分析参数错误',
  'L004': '用户未登录',
  'L005': 'VIP权限不足',
  'L006': '请求频率过高',
  'L007': '数据同步中，请稍后',
  'L008': '历史数据不足'
}

function showErrorToast(message) {
  uni.showToast({
    title: message,
    icon: 'none',
    duration: 3000
  })
}

function showLoading(title = '加载中...') {
  uni.showLoading({
    title,
    mask: true
  })
}

function hideLoading() {
  uni.hideLoading()
}

function handleError(error) {
  let message = '请求失败，请稍后重试'
  
  if (error.statusCode) {
    message = ERROR_CODES[error.statusCode] || `请求失败，错误码: ${error.statusCode}`
  } else if (error.errMsg) {
    message = error.errMsg
  }
  
  showErrorToast(message)
  
  return {
    success: false,
    code: error.statusCode || -1,
    message,
    data: null
  }
}

function handleBusinessError(code, message) {
  const businessMessage = BUSINESS_CODES[code] || message || '业务处理失败'
  
  showErrorToast(businessMessage)
  
  return {
    success: false,
    code,
    message: businessMessage,
    data: null
  }
}

async function request(options) {
  const { 
    url, 
    method = 'GET', 
    data = {}, 
    header = {}, 
    showLoading: showLoad = true,
    handleError: handleErr = true 
  } = options

  if (showLoad) {
    showLoading()
  }

  const defaultHeader = {
    'Content-Type': 'application/json',
    'Accept': 'application/json'
  }

  const token = uni.getStorageSync('token')
  if (token) {
    defaultHeader['Authorization'] = `Bearer ${token}`
  }

  return new Promise((resolve) => {
    uni.request({
      url: BASE_URL + url,
      method,
      data,
      header: { ...defaultHeader, ...header },
      timeout: 30000,
      success: (response) => {
        if (showLoad) {
          hideLoading()
        }

        const { statusCode, data: responseData } = response

        if (statusCode === 200) {
          if (responseData.success === false) {
            if (handleErr) {
              const result = handleBusinessError(responseData.code, responseData.message)
              resolve(result)
            } else {
              resolve(responseData)
            }
          } else {
            resolve({
              success: true,
              code: responseData.code || 200,
              message: responseData.message || '请求成功',
              data: responseData.data || responseData
            })
          }
        } else {
          if (handleErr) {
            const result = handleError({ statusCode })
            resolve(result)
          } else {
            resolve({
              success: false,
              code: statusCode,
              message: ERROR_CODES[statusCode] || '请求失败',
              data: null
            })
          }
        }
      },
      fail: (error) => {
        if (showLoad) {
          hideLoading()
        }

        if (handleErr) {
          const result = handleError(error)
          resolve(result)
        } else {
          resolve({
            success: false,
            code: error.statusCode || -1,
            message: error.errMsg || '请求失败',
            data: null
          })
        }
      }
    })
  })
}

export const api = {
  get(url, data = {}, options = {}) {
    return request({
      url,
      method: 'GET',
      data,
      ...options
    })
  },

  post(url, data = {}, options = {}) {
    return request({
      url,
      method: 'POST',
      data,
      ...options
    })
  },

  put(url, data = {}, options = {}) {
    return request({
      url,
      method: 'PUT',
      data,
      ...options
    })
  },

  delete(url, data = {}, options = {}) {
    return request({
      url,
      method: 'DELETE',
      data,
      ...options
    })
  }
}

export const lotteryApi = {
  async getLatestDraw(lotteryType = 'qixingcai') {
    return api.get('/draw/latest', { lottery_type: lotteryType })
  },

  async getDrawHistory(lotteryType = 'qixingcai', page = 1, size = 20) {
    return api.get('/draw/history', { lottery_type: lotteryType, page, size })
  },

  async getDrawByIssue(lotteryType, issue) {
    return api.get('/draw/issue', { lottery_type: lotteryType, issue })
  },

  async getHotNumbers(lotteryType = 'qixingcai', count = 10) {
    return api.get('/analysis/hot-numbers', { lottery_type: lotteryType, count })
  },

  async getColdNumbers(lotteryType = 'qixingcai', count = 10) {
    return api.get('/analysis/cold-numbers', { lottery_type: lotteryType, count })
  },

  async getFrequencyAnalysis(lotteryType = 'qixingcai') {
    return api.get('/analysis/frequency', { lottery_type: lotteryType })
  },

  async getOmissionAnalysis(lotteryType = 'qixingcai') {
    return api.get('/analysis/omission', { lottery_type: lotteryType })
  },

  async getHotColdAnalysis(lotteryType = 'qixingcai', recentN = 30) {
    return api.get('/analysis/hot-cold', { lottery_type: lotteryType, recent_n: recentN })
  },

  async getHezhiAnalysis(lotteryType = 'qixingcai') {
    return api.get('/analysis/hezhi', { lottery_type: lotteryType })
  },

  async getSpanAnalysis(lotteryType = 'qixingcai') {
    return api.get('/analysis/span', { lottery_type: lotteryType })
  },

  async generateDetailedReport(lotteryType = 'qixingcai') {
    return api.post('/report/detailed', { lottery_type: lotteryType })
  },

  async generateOptimalReport(lotteryType = 'qixingcai') {
    return api.post('/report/optimal', { lottery_type: lotteryType })
  },

  async login(phone, password) {
    return api.post('/auth/login', { phone, password }, { showLoading: true })
  },

  async register(phone, password, nickname) {
    return api.post('/auth/register', { phone, password, nickname }, { showLoading: true })
  },

  async getUserInfo() {
    return api.get('/user/info')
  },

  async upgradeToVip() {
    return api.post('/user/upgrade-vip')
  }
}

export { showErrorToast, showLoading, hideLoading, ERROR_CODES, BUSINESS_CODES }