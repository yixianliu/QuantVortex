"use strict";
Object.defineProperty(exports, Symbol.toStringTag, { value: "Module" });
const common_vendor = require("./common/vendor.js");
const store_user = require("./store/user.js");
if (!Math) {
  "./pages/index/index.js";
  "./pages/report/report.js";
}
const _sfc_main = {
  __name: "App",
  setup(__props) {
    common_vendor.onLaunch(() => {
      const userStore = store_user.useUserStore();
      userStore.initUserStatus();
    });
    common_vendor.onShow(() => {
      const userStore = store_user.useUserStore();
      userStore.initUserStatus();
    });
    common_vendor.onHide(() => {
      common_vendor.index.__f__("log", "at App.vue:16", "App Hide");
    });
    return () => {
    };
  }
};
function createApp() {
  const app = common_vendor.createSSRApp(_sfc_main);
  const pinia = common_vendor.createPinia();
  app.use(pinia);
  return {
    app
  };
}
createApp().app.mount("#app");
exports.createApp = createApp;
//# sourceMappingURL=../.sourcemap/mp-weixin/app.js.map
