const BASE_URL = 'http://localhost:8000'

let isApiAvailable = true
let lastCheckTime = 0

export function setApiStatus(status) {
  isApiAvailable = status
}

export function getApiStatus() {
  return isApiAvailable
}

export async function request(options) {
  const { url, method = 'GET', data = {}, header = {}, timeout = 10000 } = options

  const defaultHeader = {
    'Content-Type': 'application/json',
    ...header
  }

  try {
    const response = await uni.request({
      url: `${BASE_URL}${url}`,
      method,
      data,
      header: defaultHeader,
      timeout
    })

    const { statusCode, data: resData } = response

    if (statusCode === 200) {
      if (resData.success === true) {
        return {
          success: true,
          data: resData.data,
          message: resData.message
        }
      } else {
        return {
          success: false,
          code: resData.code,
          message: resData.message
        }
      }
    } else {
      return {
        success: false,
        code: statusCode,
        message: `HTTP错误: ${statusCode}`
      }
    }
  } catch (error) {
    return {
      success: false,
      code: -1,
      message: error.errMsg || '网络请求失败'
    }
  }
}

export async function checkApiStatus() {
  const now = Date.now()
  if (now - lastCheckTime < 30000) {
    return isApiAvailable
  }

  lastCheckTime = now

  try {
    const result = await request({
      url: '/api/system/status',
      timeout: 5000
    })

    if (result.success && result.data?.status === 'healthy') {
      isApiAvailable = true
    } else {
      isApiAvailable = false
    }
  } catch {
    isApiAvailable = false
  }

  return isApiAvailable
}

export const api = {
  data: {
    list: (params = {}) => request({
      url: '/api/data/list',
      data: params
    }),
    get: (issue) => request({
      url: `/api/data/${issue}`
    }),
    summary: () => request({
      url: '/api/data/summary'
    }),
    crawl: (data) => request({
      url: '/api/data/crawl',
      method: 'POST',
      data
    }),
    add: (data) => request({
      url: '/api/data/',
      method: 'POST',
      data
    }),
    update: (issue, data) => request({
      url: `/api/data/${issue}`,
      method: 'PUT',
      data
    }),
    delete: (issue) => request({
      url: `/api/data/${issue}`,
      method: 'DELETE'
    }),
    trend: {
      list: (params = {}) => request({
        url: '/api/data/trend/list',
        data: params
      }),
      get: (issue) => request({
        url: `/api/data/trend/${issue}`
      }),
      add: (data) => request({
        url: '/api/data/trend',
        method: 'POST',
        data
      }),
      delete: (issue) => request({
        url: `/api/data/trend/${issue}`,
        method: 'DELETE'
      })
    }
  },

  analysis: {
    frequency: () => request({
      url: '/api/analysis/frequency'
    }),
    omission: () => request({
      url: '/api/analysis/omission'
    }),
    hotCold: (params = {}) => request({
      url: '/api/analysis/hot_cold',
      data: params
    }),
    hezhi: () => request({
      url: '/api/analysis/hezhi'
    }),
    span: () => request({
      url: '/api/analysis/span'
    }),
    comprehensive: () => request({
      url: '/api/analysis/comprehensive'
    }),
    positionAnalysis: () => request({
      url: '/api/analysis/position_analysis'
    }),
    oddEven: () => request({
      url: '/api/analysis/odd_even'
    }),
    bigSmall: () => request({
      url: '/api/analysis/big_small'
    }),
    path012: () => request({
      url: '/api/analysis/path_012'
    }),
    correlation: () => request({
      url: '/api/analysis/correlation'
    }),
    randomness: () => request({
      url: '/api/analysis/randomness'
    }),
    repeats: () => request({
      url: '/api/analysis/repeats'
    }),
    consecutive: () => request({
      url: '/api/analysis/consecutive'
    })
  },

  report: {
    list: (params = {}) => request({
      url: '/api/report/list',
      data: params
    }),
    detail: (reportId, userId) => request({
      url: `/api/report/${reportId}?user_id=${userId}`
    }),
    generate: (params = {}) => {
      const reportTypes = params.report_types || ['detailed', 'optimal']
      const useTrend = params.use_trend !== undefined ? params.use_trend : true
      const queryParams = new URLSearchParams()
      reportTypes.forEach(type => queryParams.append('report_types', type))
      queryParams.append('use_trend', useTrend)
      return request({
        url: `/api/report/generate?${queryParams.toString()}`,
        method: 'POST'
      })
    },
    generateHead4: (params = {}) => {
      const useTrend = params.use_trend !== undefined ? params.use_trend : true
      return request({
        url: `/api/report/generate-head4?use_trend=${useTrend}`,
        method: 'POST'
      })
    },
    addDetailed: (data) => request({
      url: '/api/report/detailed',
      method: 'POST',
      data
    }),
    addFinal: (data) => request({
      url: '/api/report/final',
      method: 'POST',
      data
    }),
    update: (reportId, data) => request({
      url: `/api/report/${reportId}`,
      method: 'PUT',
      data
    }),
    delete: (reportId) => request({
      url: `/api/report/${reportId}`,
      method: 'DELETE'
    }),
    summary: () => request({
      url: '/api/report/summary'
    })
  },

  auth: {
    login: (params) => {
      const queryParams = new URLSearchParams()
      Object.entries(params).forEach(([key, value]) => {
        if (value !== undefined && value !== null) {
          queryParams.append(key, value)
        }
      })
      return request({
        url: `/api/auth/login?${queryParams.toString()}`,
        method: 'POST'
      })
    },
    profile: (userId) => request({
      url: `/api/auth/profile?user_id=${userId}`
    }),
    payment: (params) => {
      const queryParams = new URLSearchParams()
      Object.entries(params).forEach(([key, value]) => {
        if (value !== undefined && value !== null) {
          queryParams.append(key, value)
        }
      })
      return request({
        url: `/api/auth/payment?${queryParams.toString()}`,
        method: 'POST'
      })
    },
    payments: (params) => {
      const queryParams = new URLSearchParams()
      Object.entries(params).forEach(([key, value]) => {
        if (value !== undefined && value !== null) {
          queryParams.append(key, value)
        }
      })
      return request({
        url: `/api/auth/payments?${queryParams.toString()}`
      })
    },
    paymentStatus: (userId, paymentType = 'report_view') => request({
      url: `/api/auth/payment-status?user_id=${userId}&payment_type=${paymentType}`
    })
  },

  system: {
    status: () => request({
      url: '/api/system/status'
    }),
    config: () => request({
      url: '/api/system/config'
    }),
    init: () => request({
      url: '/api/system/init',
      method: 'POST'
    }),
    clean: (confirm = false) => request({
      url: `/api/system/clean?confirm=${confirm}`,
      method: 'POST'
    }),
    logs: (params = {}) => {
      const queryParams = new URLSearchParams()
      Object.entries(params).forEach(([key, value]) => {
        if (value !== undefined && value !== null) {
          queryParams.append(key, value)
        }
      })
      return request({
        url: `/api/system/logs?${queryParams.toString()}`
      })
    }
  }
}

export default api
