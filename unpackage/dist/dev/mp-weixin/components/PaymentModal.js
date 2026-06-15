"use strict";
const common_vendor = require("../common/vendor.js");
const store_user = require("../store/user.js");
const _sfc_main = {
  __name: "PaymentModal",
  props: {
    visible: {
      type: Boolean,
      default: false
    }
  },
  emits: ["close", "pay-success"],
  setup(__props, { emit: __emit }) {
    const emit = __emit;
    const userStore = store_user.useUserStore();
    function handleClose() {
      emit("close");
    }
    function handlePayment() {
      common_vendor.index.showLoading({ title: "支付中..." });
      setTimeout(() => {
        userStore.pay();
        common_vendor.index.hideLoading();
        emit("close");
        emit("pay-success");
      }, 2e3);
    }
    return (_ctx, _cache) => {
      return common_vendor.e({
        a: __props.visible
      }, __props.visible ? {
        b: common_vendor.o(handleClose, "da"),
        c: common_vendor.o(handlePayment, "32"),
        d: common_vendor.o(handleClose, "e6"),
        e: common_vendor.o(handleClose, "dd")
      } : {});
    };
  }
};
const Component = /* @__PURE__ */ common_vendor._export_sfc(_sfc_main, [["__scopeId", "data-v-d0c78149"]]);
wx.createComponent(Component);
//# sourceMappingURL=../../.sourcemap/mp-weixin/components/PaymentModal.js.map
