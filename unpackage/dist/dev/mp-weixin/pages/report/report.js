"use strict";
const common_vendor = require("../../common/vendor.js");
const data_lotteryData = require("../../data/lotteryData.js");
const utils_index = require("../../utils/index.js");
const store_user = require("../../store/user.js");
if (!Math) {
  (LoginModal + PaymentModal)();
}
const LoginModal = () => "../../components/LoginModal.js";
const PaymentModal = () => "../../components/PaymentModal.js";
const _sfc_main = {
  __name: "report",
  setup(__props) {
    const userStore = store_user.useUserStore();
    const reportType = common_vendor.ref("detailed");
    const selectedGroup = common_vendor.ref("dataGroupA");
    const reportData = common_vendor.ref({});
    const showLoginModal = common_vendor.ref(false);
    const showPaymentModal = common_vendor.ref(false);
    const currentGroupInfo = common_vendor.computed(() => {
      return data_lotteryData.lotteryTypes.find((l) => l.id === selectedGroup.value) || data_lotteryData.lotteryTypes[0];
    });
    const hasAccess = common_vendor.computed(() => {
      return userStore.isPaid;
    });
    const accessDeniedMessage = common_vendor.computed(() => {
      if (!userStore.isLoggedIn) {
        return "请先登录账号，登录后可查看报告列表";
      }
      return "您当前不是VIP会员，请升级VIP以解锁完整报告内容";
    });
    common_vendor.onMounted(() => {
      userStore.initUserStatus();
      const pages = getCurrentPages();
      const currentPage = pages[pages.length - 1];
      const options = currentPage.options || {};
      if (options.type) {
        reportType.value = options.type;
      }
      if (options.group) {
        selectedGroup.value = options.group;
      }
      loadReportData();
    });
    common_vendor.watch(() => userStore.isPaid, (newVal) => {
      if (newVal) {
        loadReportData();
      }
    });
    function loadReportData() {
      const history = data_lotteryData.lotteryHistory[selectedGroup.value] || [];
      if (reportType.value === "detailed") {
        reportData.value = utils_index.generateDetailedReport(selectedGroup.value, history);
      } else {
        reportData.value = utils_index.generateOptimalReport(selectedGroup.value, history);
      }
    }
    function goBack() {
      const pages = getCurrentPages();
      if (pages.length > 1) {
        common_vendor.index.navigateBack({
          fail: () => {
            common_vendor.index.reLaunch({
              url: "/pages/index/index"
            });
          }
        });
      } else {
        common_vendor.index.reLaunch({
          url: "/pages/index/index"
        });
      }
    }
    function copyNumbers() {
      let numbersText = "";
      if (selectedGroup.value === "dataGroupA") {
        numbersText = `GROUP1: ${reportData.value.recommendedNumbers.group1.join(" ")} | GROUP2: ${reportData.value.recommendedNumbers.group2}`;
      } else if (selectedGroup.value === "dataGroupB") {
        numbersText = `GROUP1: ${reportData.value.recommendedNumbers.group1.join(" ")} | GROUP2: ${reportData.value.recommendedNumbers.group2.join(" ")}`;
      } else if (selectedGroup.value === "dataGroupC") {
        numbersText = `${reportData.value.recommendedNumbers.num1} ${reportData.value.recommendedNumbers.num2} ${reportData.value.recommendedNumbers.num3}`;
      }
      common_vendor.index.setClipboardData({
        data: numbersText,
        success: () => {
          common_vendor.index.showToast({
            title: "COPIED SUCCESS",
            icon: "success"
          });
        }
      });
    }
    function shareReport() {
      common_vendor.index.showToast({
        title: "SHARE FUNCTION",
        icon: "none"
      });
      common_vendor.index.showShareMenu({
        withShareTicket: true
      });
    }
    function onLoginSuccess() {
      common_vendor.index.showToast({
        title: "登录成功",
        icon: "success"
      });
    }
    function onPaySuccess() {
      loadReportData();
      common_vendor.index.showToast({
        title: "解锁成功",
        icon: "success"
      });
    }
    return (_ctx, _cache) => {
      var _a, _b, _c, _d, _e, _f, _g, _h, _i, _j, _k, _l, _m, _n, _o, _p, _q, _r, _s, _t, _u, _v, _w, _x, _y, _z;
      return common_vendor.e({
        a: common_vendor.o(goBack, "76"),
        b: common_vendor.t(reportType.value === "detailed" ? "📋 DETAILED REPORT" : "🎯 OPTIMAL REPORT"),
        c: common_vendor.unref(userStore).isPaid
      }, common_vendor.unref(userStore).isPaid ? {} : {}, {
        d: hasAccess.value
      }, hasAccess.value ? common_vendor.e({
        e: reportData.value.lotteryType
      }, reportData.value.lotteryType ? common_vendor.e({
        f: common_vendor.t(currentGroupInfo.value.name),
        g: common_vendor.t(reportData.value.generateTime),
        h: common_vendor.t(reportType.value === "detailed" ? "FULL ANALYSIS" : "BEST CHOICE"),
        i: common_vendor.n(reportType.value),
        j: common_vendor.t(reportData.value.totalCount || 0),
        k: common_vendor.t(reportData.value.analyzedCount || 0),
        l: common_vendor.t(reportData.value.accuracy || 0),
        m: common_vendor.t(reportData.value.confidence || 0),
        n: common_vendor.f(((_a = reportData.value.analysis) == null ? void 0 : _a.hotNumbers) || [], (item, index, i0) => {
          return {
            a: common_vendor.t(item.num),
            b: common_vendor.t(item.count),
            c: common_vendor.t(item.rate),
            d: index
          };
        }),
        o: common_vendor.f(((_b = reportData.value.analysis) == null ? void 0 : _b.coldNumbers) || [], (item, index, i0) => {
          return {
            a: common_vendor.t(item.num),
            b: common_vendor.t(item.count),
            c: common_vendor.t(item.rate),
            d: index
          };
        }),
        p: (((_d = (_c = reportData.value.analysis) == null ? void 0 : _c.distribution) == null ? void 0 : _d.oddRate) || 0) + "%",
        q: (((_f = (_e = reportData.value.analysis) == null ? void 0 : _e.distribution) == null ? void 0 : _f.evenRate) || 0) + "%",
        r: common_vendor.t(((_h = (_g = reportData.value.analysis) == null ? void 0 : _g.distribution) == null ? void 0 : _h.oddRate) || 0),
        s: common_vendor.t(((_j = (_i = reportData.value.analysis) == null ? void 0 : _i.distribution) == null ? void 0 : _j.evenRate) || 0),
        t: (((_l = (_k = reportData.value.analysis) == null ? void 0 : _k.distribution) == null ? void 0 : _l.smallRate) || 0) + "%",
        v: (((_n = (_m = reportData.value.analysis) == null ? void 0 : _m.distribution) == null ? void 0 : _n.largeRate) || 0) + "%",
        w: common_vendor.t(((_p = (_o = reportData.value.analysis) == null ? void 0 : _o.distribution) == null ? void 0 : _p.smallRate) || 0),
        x: common_vendor.t(((_r = (_q = reportData.value.analysis) == null ? void 0 : _q.distribution) == null ? void 0 : _r.largeRate) || 0),
        y: selectedGroup.value === "dataGroupA"
      }, selectedGroup.value === "dataGroupA" ? {
        z: common_vendor.f(((_s = reportData.value.recommendedNumbers) == null ? void 0 : _s.group1) || [], (num, index, i0) => {
          return {
            a: common_vendor.t(num),
            b: index
          };
        }),
        A: common_vendor.t(((_t = reportData.value.recommendedNumbers) == null ? void 0 : _t.group2) || "-")
      } : selectedGroup.value === "dataGroupB" ? {
        C: common_vendor.f(((_u = reportData.value.recommendedNumbers) == null ? void 0 : _u.group1) || [], (num, index, i0) => {
          return {
            a: common_vendor.t(num),
            b: index
          };
        }),
        D: common_vendor.f(((_v = reportData.value.recommendedNumbers) == null ? void 0 : _v.group2) || [], (num, index, i0) => {
          return {
            a: common_vendor.t(num),
            b: index
          };
        })
      } : selectedGroup.value === "dataGroupC" ? {
        F: common_vendor.t(((_w = reportData.value.recommendedNumbers) == null ? void 0 : _w.num1) ?? "-"),
        G: common_vendor.t(((_x = reportData.value.recommendedNumbers) == null ? void 0 : _x.num2) ?? "-"),
        H: common_vendor.t(((_y = reportData.value.recommendedNumbers) == null ? void 0 : _y.num3) ?? "-")
      } : {}, {
        B: selectedGroup.value === "dataGroupB",
        E: selectedGroup.value === "dataGroupC",
        I: common_vendor.f(((_z = reportData.value.analysis) == null ? void 0 : _z.strategy) || [], (item, index, i0) => {
          return {
            a: common_vendor.t(item.icon),
            b: common_vendor.t(item.title),
            c: common_vendor.t(item.desc),
            d: index
          };
        })
      }) : {}) : common_vendor.e({
        J: common_vendor.t(accessDeniedMessage.value),
        K: !common_vendor.unref(userStore).isLoggedIn
      }, !common_vendor.unref(userStore).isLoggedIn ? {
        L: common_vendor.o(($event) => showLoginModal.value = true, "38")
      } : {
        M: common_vendor.o(($event) => showPaymentModal.value = true, "5b")
      }, {
        N: common_vendor.o(goBack, "22")
      }), {
        O: hasAccess.value
      }, hasAccess.value ? {
        P: common_vendor.o(copyNumbers, "a6"),
        Q: common_vendor.o(shareReport, "82")
      } : {}, {
        R: common_vendor.o(($event) => showLoginModal.value = false, "2b"),
        S: common_vendor.o(onLoginSuccess, "52"),
        T: common_vendor.p({
          visible: showLoginModal.value
        }),
        U: common_vendor.o(($event) => showPaymentModal.value = false, "1a"),
        V: common_vendor.o(onPaySuccess, "af"),
        W: common_vendor.p({
          visible: showPaymentModal.value
        })
      });
    };
  }
};
wx.createPage(_sfc_main);
//# sourceMappingURL=../../../.sourcemap/mp-weixin/pages/report/report.js.map
