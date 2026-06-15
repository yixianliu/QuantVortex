"use strict";
const common_vendor = require("../common/vendor.js");
const useUserStore = common_vendor.defineStore("user", () => {
  const isLoggedIn = common_vendor.ref(false);
  const isPaid = common_vendor.ref(false);
  const userInfo = common_vendor.ref({
    userId: "",
    nickname: "",
    avatar: ""
  });
  const userStatus = common_vendor.computed(() => {
    if (!isLoggedIn.value)
      return "unlogged";
    if (!isPaid.value)
      return "logged_unpaid";
    return "logged_paid";
  });
  function login(userData = {}) {
    isLoggedIn.value = true;
    userInfo.value = {
      userId: userData.userId || `user_${Date.now()}`,
      nickname: userData.nickname || "用户",
      avatar: userData.avatar || ""
    };
    common_vendor.index.setStorageSync("isLoggedIn", true);
    common_vendor.index.setStorageSync("userInfo", JSON.stringify(userInfo.value));
    common_vendor.index.showToast({
      title: "登录成功",
      icon: "success"
    });
  }
  function logout() {
    isLoggedIn.value = false;
    isPaid.value = false;
    userInfo.value = { userId: "", nickname: "", avatar: "" };
    common_vendor.index.removeStorageSync("isLoggedIn");
    common_vendor.index.removeStorageSync("userInfo");
    common_vendor.index.removeStorageSync("isPaid");
    common_vendor.index.showToast({
      title: "已退出登录",
      icon: "none"
    });
  }
  function pay() {
    isPaid.value = true;
    common_vendor.index.setStorageSync("isPaid", true);
    common_vendor.index.showToast({
      title: "购买成功",
      icon: "success"
    });
  }
  function initUserStatus() {
    const storedLoggedIn = common_vendor.index.getStorageSync("isLoggedIn");
    const storedUserInfo = common_vendor.index.getStorageSync("userInfo");
    const storedIsPaid = common_vendor.index.getStorageSync("isPaid");
    if (storedLoggedIn) {
      isLoggedIn.value = true;
      try {
        userInfo.value = JSON.parse(storedUserInfo) || { userId: "", nickname: "", avatar: "" };
      } catch {
        userInfo.value = { userId: "", nickname: "", avatar: "" };
      }
    }
    if (storedIsPaid) {
      isPaid.value = true;
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
  };
});
exports.useUserStore = useUserStore;
//# sourceMappingURL=../../.sourcemap/mp-weixin/store/user.js.map
