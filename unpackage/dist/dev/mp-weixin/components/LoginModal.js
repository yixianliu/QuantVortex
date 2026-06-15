"use strict";
const common_vendor = require("../common/vendor.js");
const store_user = require("../store/user.js");
const _sfc_main = {
  __name: "LoginModal",
  props: {
    visible: {
      type: Boolean,
      default: false
    }
  },
  emits: ["close", "login-success"],
  setup(__props, { emit: __emit }) {
    const emit = __emit;
    const userStore = store_user.useUserStore();
    function handleClose() {
      emit("close");
    }
    function handleWechatLogin() {
      common_vendor.index.showLoading({ title: "登录中..." });
      setTimeout(() => {
        common_vendor.wx$1.login({
          success: (res) => {
            if (res.code) {
              userStore.login({
                nickname: "微信用户",
                avatar: ""
              });
              common_vendor.index.hideLoading();
              emit("close");
              emit("login-success");
            }
          },
          fail: () => {
            common_vendor.index.hideLoading();
            common_vendor.index.showToast({
              title: "登录失败",
              icon: "none"
            });
          }
        });
      }, 1500);
    }
    function handlePhoneLogin() {
      common_vendor.index.showModal({
        title: "手机号登录",
        content: "请在后续版本中使用手机号登录功能",
        showCancel: false
      });
    }
    return (_ctx, _cache) => {
      return common_vendor.e({
        a: __props.visible
      }, __props.visible ? {
        b: common_vendor.o(handleClose, "b0"),
        c: common_vendor.o(handleWechatLogin, "07"),
        d: common_vendor.o(handlePhoneLogin, "25"),
        e: common_vendor.o(handleClose, "dd")
      } : {});
    };
  }
};
const Component = /* @__PURE__ */ common_vendor._export_sfc(_sfc_main, [["__scopeId", "data-v-a773d557"]]);
wx.createComponent(Component);
//# sourceMappingURL=../../.sourcemap/mp-weixin/components/LoginModal.js.map
