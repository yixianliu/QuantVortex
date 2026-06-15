"use strict";
const common_vendor = require("../../common/vendor.js");
const data_lotteryData = require("../../data/lotteryData.js");
const utils_index = require("../../utils/index.js");
const store_user = require("../../store/user.js");
if (!Math) {
  LoginModal();
}
const LoginModal = () => "../../components/LoginModal.js";
const _sfc_main = {
  __name: "index",
  setup(__props) {
    const userStore = store_user.useUserStore();
    const selectedGroup = common_vendor.ref("dataGroupA");
    const showLoginModal = common_vendor.ref(false);
    const showUserMenu = common_vendor.ref(false);
    const currentGroupInfo = common_vendor.computed(() => {
      return data_lotteryData.lotteryTypes.find((l) => l.id === selectedGroup.value) || data_lotteryData.lotteryTypes[0];
    });
    const historyData = common_vendor.computed(() => {
      return data_lotteryData.lotteryHistory[selectedGroup.value] || [];
    });
    const latestData = common_vendor.computed(() => {
      return historyData.value[0] || {};
    });
    const hotNumbers = common_vendor.computed(() => {
      return utils_index.getHotNumbers(historyData.value, 5);
    });
    const coldNumbers = common_vendor.computed(() => {
      return utils_index.getColdNumbers(historyData.value, 5);
    });
    const distribution = common_vendor.computed(() => {
      return utils_index.analyzeNumberDistribution(historyData.value);
    });
    const rulesList = common_vendor.computed(() => {
      return data_lotteryData.prizeLevels[selectedGroup.value] || [];
    });
    const displayHistory = common_vendor.computed(() => {
      return historyData.value.slice(1, 6);
    });
    common_vendor.onMounted(() => {
      userStore.initUserStatus();
    });
    function selectGroup(groupId) {
      selectedGroup.value = groupId;
    }
    function refreshData() {
      common_vendor.index.showToast({
        title: "DATA REFRESHED",
        icon: "success"
      });
    }
    function scrollToHistory() {
      common_vendor.index.showToast({
        title: "ALL RECORDS SHOWN",
        icon: "none"
      });
    }
    function generateReport(type) {
      if (!userStore.isLoggedIn) {
        showLoginModal.value = true;
        return;
      }
      common_vendor.index.navigateTo({
        url: `/pages/report/report?type=${type}&group=${selectedGroup.value}`
      });
    }
    function onLoginSuccess() {
      common_vendor.index.showToast({
        title: "登录成功",
        icon: "success"
      });
    }
    function handleUpgrade() {
      showUserMenu.value = false;
      common_vendor.index.navigateTo({
        url: `/pages/report/report?type=detailed&group=${selectedGroup.value}`
      });
    }
    function handleLogout() {
      common_vendor.index.showModal({
        title: "确认退出",
        content: "确定要退出登录吗？",
        success: (res) => {
          if (res.confirm) {
            userStore.logout();
            showUserMenu.value = false;
          }
        }
      });
    }
    return (_ctx, _cache) => {
      return common_vendor.e({
        a: common_vendor.unref(userStore).isLoggedIn
      }, common_vendor.unref(userStore).isLoggedIn ? common_vendor.e({
        b: common_vendor.t(common_vendor.unref(userStore).userInfo.nickname),
        c: common_vendor.unref(userStore).isPaid
      }, common_vendor.unref(userStore).isPaid ? {} : {}, {
        d: common_vendor.o(($event) => showUserMenu.value = true, "9a")
      }) : {
        e: common_vendor.o(($event) => showLoginModal.value = true, "e7")
      }, {
        f: common_vendor.f(common_vendor.unref(data_lotteryData.lotteryTypes), (group, k0, i0) => {
          return common_vendor.e({
            a: common_vendor.t(group.icon),
            b: group.bgColor,
            c: common_vendor.t(group.name),
            d: common_vendor.t(group.description),
            e: selectedGroup.value === group.id
          }, selectedGroup.value === group.id ? {} : {}, {
            f: group.id,
            g: selectedGroup.value === group.id ? 1 : "",
            h: selectedGroup.value === group.id ? group.color : "transparent",
            i: common_vendor.o(($event) => selectGroup(group.id), group.id)
          });
        }),
        g: common_vendor.t(currentGroupInfo.value.name),
        h: common_vendor.o(refreshData, "5b"),
        i: common_vendor.t(latestData.value.issue),
        j: common_vendor.t(latestData.value.date),
        k: selectedGroup.value === "dataGroupA"
      }, selectedGroup.value === "dataGroupA" ? {
        l: common_vendor.f(latestData.value.group1, (num, index, i0) => {
          return {
            a: common_vendor.t(num),
            b: "main-" + index
          };
        })
      } : selectedGroup.value === "dataGroupB" ? {
        n: common_vendor.f(latestData.value.group1, (num, index, i0) => {
          return {
            a: common_vendor.t(num),
            b: "main-" + index
          };
        }),
        o: common_vendor.t(latestData.value.group2)
      } : {}, {
        m: selectedGroup.value === "dataGroupB",
        p: common_vendor.f(hotNumbers.value, (item, index, i0) => {
          return {
            a: common_vendor.t(item.num),
            b: "hot-" + index
          };
        }),
        q: common_vendor.f(coldNumbers.value, (item, index, i0) => {
          return {
            a: common_vendor.t(item.num),
            b: "cold-" + index
          };
        }),
        r: distribution.value.oddRate + "%",
        s: common_vendor.t(distribution.value.oddRate),
        t: distribution.value.evenRate + "%",
        v: common_vendor.t(distribution.value.evenRate),
        w: distribution.value.smallRate + "%",
        x: common_vendor.t(distribution.value.smallRate),
        y: distribution.value.largeRate + "%",
        z: common_vendor.t(distribution.value.largeRate),
        A: common_vendor.f(rulesList.value, (rule, index, i0) => {
          return {
            a: common_vendor.t(rule.level),
            b: common_vendor.t(rule.match),
            c: common_vendor.t(rule.prize),
            d: common_vendor.t(rule.probability),
            e: index,
            f: index === 0 ? 1 : ""
          };
        }),
        B: common_vendor.o(scrollToHistory, "1f"),
        C: common_vendor.f(displayHistory.value, (item, index, i0) => {
          return common_vendor.e({
            a: common_vendor.t(item.issue)
          }, selectedGroup.value === "dataGroupA" ? {
            b: common_vendor.f(item.group1, (num, i, i1) => {
              return {
                a: common_vendor.t(num),
                b: i
              };
            })
          } : selectedGroup.value === "dataGroupB" ? {
            c: common_vendor.f(item.group1, (num, i, i1) => {
              return {
                a: common_vendor.t(num),
                b: i
              };
            }),
            d: common_vendor.t(item.group2)
          } : {}, {
            e: common_vendor.t(item.date),
            f: index
          });
        }),
        D: selectedGroup.value === "dataGroupA",
        E: selectedGroup.value === "dataGroupB",
        F: common_vendor.o(($event) => generateReport("detailed"), "6c"),
        G: common_vendor.o(($event) => generateReport("optimal"), "02"),
        H: common_vendor.o(($event) => showLoginModal.value = false, "67"),
        I: common_vendor.o(onLoginSuccess, "cd"),
        J: common_vendor.p({
          visible: showLoginModal.value
        }),
        K: showUserMenu.value
      }, showUserMenu.value ? common_vendor.e({
        L: !common_vendor.unref(userStore).isPaid
      }, !common_vendor.unref(userStore).isPaid ? {
        M: common_vendor.o(handleUpgrade, "15")
      } : {}, {
        N: common_vendor.o(handleLogout, "f6"),
        O: common_vendor.o(($event) => showUserMenu.value = false, "f3")
      }) : {});
    };
  }
};
wx.createPage(_sfc_main);
//# sourceMappingURL=../../../.sourcemap/mp-weixin/pages/index/index.js.map
