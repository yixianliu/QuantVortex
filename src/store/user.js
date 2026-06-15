import { defineStore } from 'pinia'
import { ref, computed } from 'vue'

export const useUserStore = defineStore('user', () => {
  const isLoggedIn = ref(false)
  const isPaid = ref(false)
  const userInfo = ref({
    userId: '',
    nickname: '',
    avatar: ''
  })

  const userStatus = computed(() => {
    if (!isLoggedIn.value) return 'unlogged'
    if (!isPaid.value) return 'logged_unpaid'
    return 'logged_paid'
  })

  function login(userData = {}) {
    isLoggedIn.value = true
    userInfo.value = {
      userId: userData.userId || `user_${Date.now()}`,
      nickname: userData.nickname || '用户',
      avatar: userData.avatar || ''
    }
    uni.setStorageSync('isLoggedIn', true)
    uni.setStorageSync('userInfo', JSON.stringify(userInfo.value))
    uni.showToast({
      title: '登录成功',
      icon: 'success'
    })
  }

  function logout() {
    isLoggedIn.value = false
    isPaid.value = false
    userInfo.value = { userId: '', nickname: '', avatar: '' }
    uni.removeStorageSync('isLoggedIn')
    uni.removeStorageSync('userInfo')
    uni.removeStorageSync('isPaid')
    uni.showToast({
      title: '已退出登录',
      icon: 'none'
    })
  }

  function pay() {
    isPaid.value = true
    uni.setStorageSync('isPaid', true)
    uni.showToast({
      title: '购买成功',
      icon: 'success'
    })
  }

  function initUserStatus() {
    const storedLoggedIn = uni.getStorageSync('isLoggedIn')
    const storedUserInfo = uni.getStorageSync('userInfo')
    const storedIsPaid = uni.getStorageSync('isPaid')
    
    if (storedLoggedIn) {
      isLoggedIn.value = true
      try {
        userInfo.value = JSON.parse(storedUserInfo) || { userId: '', nickname: '', avatar: '' }
      } catch {
        userInfo.value = { userId: '', nickname: '', avatar: '' }
      }
    }
    
    if (storedIsPaid) {
      isPaid.value = true
    }
  }

  return {
    isLoggedIn,
    isPaid,
    userInfo,
    userStatus,
    login,
    logout,
    pay,
    initUserStatus
  }
})