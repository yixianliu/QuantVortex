"use strict";
/**
* @vue/shared v3.4.21
* (c) 2018-present Yuxi (Evan) You and Vue contributors
* @license MIT
**/
function makeMap(str, expectsLowerCase) {
  const set2 = new Set(str.split(","));
  return expectsLowerCase ? (val) => set2.has(val.toLowerCase()) : (val) => set2.has(val);
}
const EMPTY_OBJ = Object.freeze({});
const EMPTY_ARR = Object.freeze([]);
const NOOP = () => {
};
const NO = () => false;
const isOn = (key) => key.charCodeAt(0) === 111 && key.charCodeAt(1) === 110 && // uppercase letter
(key.charCodeAt(2) > 122 || key.charCodeAt(2) < 97);
const isModelListener = (key) => key.startsWith("onUpdate:");
const extend = Object.assign;
const remove$1 = (arr, el) => {
  const i = arr.indexOf(el);
  if (i > -1) {
    arr.splice(i, 1);
  }
};
const hasOwnProperty$1 = Object.prototype.hasOwnProperty;
const hasOwn = (val, key) => hasOwnProperty$1.call(val, key);
const isArray = Array.isArray;
const isMap = (val) => toTypeString(val) === "[object Map]";
const isSet = (val) => toTypeString(val) === "[object Set]";
const isFunction = (val) => typeof val === "function";
const isString = (val) => typeof val === "string";
const isSymbol = (val) => typeof val === "symbol";
const isObject = (val) => val !== null && typeof val === "object";
const isPromise = (val) => {
  return (isObject(val) || isFunction(val)) && isFunction(val.then) && isFunction(val.catch);
};
const objectToString = Object.prototype.toString;
const toTypeString = (value) => objectToString.call(value);
const toRawType = (value) => {
  return toTypeString(value).slice(8, -1);
};
const isPlainObject$1 = (val) => toTypeString(val) === "[object Object]";
const isIntegerKey = (key) => isString(key) && key !== "NaN" && key[0] !== "-" && "" + parseInt(key, 10) === key;
const isReservedProp = /* @__PURE__ */ makeMap(
  // the leading comma is intentional so empty string "" is also included
  ",key,ref,ref_for,ref_key,onVnodeBeforeMount,onVnodeMounted,onVnodeBeforeUpdate,onVnodeUpdated,onVnodeBeforeUnmount,onVnodeUnmounted"
);
const isBuiltInDirective = /* @__PURE__ */ makeMap(
  "bind,cloak,else-if,else,for,html,if,model,on,once,pre,show,slot,text,memo"
);
const cacheStringFunction = (fn) => {
  const cache2 = /* @__PURE__ */ Object.create(null);
  return (str) => {
    const hit = cache2[str];
    return hit || (cache2[str] = fn(str));
  };
};
const camelizeRE = /-(\w)/g;
const camelize = cacheStringFunction((str) => {
  return str.replace(camelizeRE, (_, c) => c ? c.toUpperCase() : "");
});
const hyphenateRE = /\B([A-Z])/g;
const hyphenate = cacheStringFunction(
  (str) => str.replace(hyphenateRE, "-$1").toLowerCase()
);
const capitalize = cacheStringFunction((str) => {
  return str.charAt(0).toUpperCase() + str.slice(1);
});
const toHandlerKey = cacheStringFunction((str) => {
  const s2 = str ? `on${capitalize(str)}` : ``;
  return s2;
});
const hasChanged = (value, oldValue) => !Object.is(value, oldValue);
const invokeArrayFns$1 = (fns, arg) => {
  for (let i = 0; i < fns.length; i++) {
    fns[i](arg);
  }
};
const def = (obj, key, value) => {
  Object.defineProperty(obj, key, {
    configurable: true,
    enumerable: false,
    value
  });
};
const looseToNumber = (val) => {
  const n2 = parseFloat(val);
  return isNaN(n2) ? val : n2;
};
function normalizeClass(value) {
  let res = "";
  if (isString(value)) {
    res = value;
  } else if (isArray(value)) {
    for (let i = 0; i < value.length; i++) {
      const normalized = normalizeClass(value[i]);
      if (normalized) {
        res += normalized + " ";
      }
    }
  } else if (isObject(value)) {
    for (const name in value) {
      if (value[name]) {
        res += name + " ";
      }
    }
  }
  return res.trim();
}
const toDisplayString = (val) => {
  return isString(val) ? val : val == null ? "" : isArray(val) || isObject(val) && (val.toString === objectToString || !isFunction(val.toString)) ? JSON.stringify(val, replacer, 2) : String(val);
};
const replacer = (_key, val) => {
  if (val && val.__v_isRef) {
    return replacer(_key, val.value);
  } else if (isMap(val)) {
    return {
      [`Map(${val.size})`]: [...val.entries()].reduce(
        (entries, [key, val2], i) => {
          entries[stringifySymbol(key, i) + " =>"] = val2;
          return entries;
        },
        {}
      )
    };
  } else if (isSet(val)) {
    return {
      [`Set(${val.size})`]: [...val.values()].map((v) => stringifySymbol(v))
    };
  } else if (isSymbol(val)) {
    return stringifySymbol(val);
  } else if (isObject(val) && !isArray(val) && !isPlainObject$1(val)) {
    return String(val);
  }
  return val;
};
const stringifySymbol = (v, i = "") => {
  var _a;
  return isSymbol(v) ? `Symbol(${(_a = v.description) != null ? _a : i})` : v;
};
const LOCALE_ZH_HANS = "zh-Hans";
const LOCALE_ZH_HANT = "zh-Hant";
const LOCALE_EN = "en";
const LOCALE_FR = "fr";
const LOCALE_ES = "es";
function include(str, parts) {
  return !!parts.find((part) => str.indexOf(part) !== -1);
}
function startsWith(str, parts) {
  return parts.find((part) => str.indexOf(part) === 0);
}
function normalizeLocale(locale, messages) {
  if (!locale) {
    return;
  }
  locale = locale.trim().replace(/_/g, "-");
  if (messages && messages[locale]) {
    return locale;
  }
  locale = locale.toLowerCase();
  if (locale === "chinese") {
    return LOCALE_ZH_HANS;
  }
  if (locale.indexOf("zh") === 0) {
    if (locale.indexOf("-hans") > -1) {
      return LOCALE_ZH_HANS;
    }
    if (locale.indexOf("-hant") > -1) {
      return LOCALE_ZH_HANT;
    }
    if (include(locale, ["-tw", "-hk", "-mo", "-cht"])) {
      return LOCALE_ZH_HANT;
    }
    return LOCALE_ZH_HANS;
  }
  let locales = [LOCALE_EN, LOCALE_FR, LOCALE_ES];
  if (messages && Object.keys(messages).length > 0) {
    locales = Object.keys(messages);
  }
  const lang = startsWith(locale, locales);
  if (lang) {
    return lang;
  }
}
const SLOT_DEFAULT_NAME = "d";
const ON_SHOW = "onShow";
const ON_HIDE = "onHide";
const ON_LAUNCH = "onLaunch";
const ON_ERROR = "onError";
const ON_THEME_CHANGE = "onThemeChange";
const ON_PAGE_NOT_FOUND = "onPageNotFound";
const ON_UNHANDLE_REJECTION = "onUnhandledRejection";
const ON_LAST_PAGE_BACK_PRESS = "onLastPageBackPress";
const ON_EXIT = "onExit";
const ON_LOAD = "onLoad";
const ON_READY = "onReady";
const ON_UNLOAD = "onUnload";
const ON_INIT = "onInit";
const ON_SAVE_EXIT_STATE = "onSaveExitState";
const ON_UPLOAD_DOUYIN_VIDEO = "onUploadDouyinVideo";
const ON_LIVE_MOUNT = "onLiveMount";
const ON_TITLE_CLICK = "onTitleClick";
const ON_RESIZE = "onResize";
const ON_BACK_PRESS = "onBackPress";
const ON_PAGE_SCROLL = "onPageScroll";
const ON_TAB_ITEM_TAP = "onTabItemTap";
const ON_REACH_BOTTOM = "onReachBottom";
const ON_PULL_DOWN_REFRESH = "onPullDownRefresh";
const ON_SHARE_TIMELINE = "onShareTimeline";
const ON_SHARE_CHAT = "onShareChat";
const ON_COPY_URL = "onCopyUrl";
const ON_ADD_TO_FAVORITES = "onAddToFavorites";
const ON_SHARE_APP_MESSAGE = "onShareAppMessage";
const ON_NAVIGATION_BAR_BUTTON_TAP = "onNavigationBarButtonTap";
const ON_NAVIGATION_BAR_SEARCH_INPUT_CLICKED = "onNavigationBarSearchInputClicked";
const ON_NAVIGATION_BAR_SEARCH_INPUT_CHANGED = "onNavigationBarSearchInputChanged";
const ON_NAVIGATION_BAR_SEARCH_INPUT_CONFIRMED = "onNavigationBarSearchInputConfirmed";
const ON_NAVIGATION_BAR_SEARCH_INPUT_FOCUS_CHANGED = "onNavigationBarSearchInputFocusChanged";
const VIRTUAL_HOST_STYLE = "virtualHostStyle";
const VIRTUAL_HOST_CLASS = "virtualHostClass";
const VIRTUAL_HOST_HIDDEN = "virtualHostHidden";
const VIRTUAL_HOST_ID = "virtualHostId";
const customizeRE = /:/g;
function customizeEvent(str) {
  return camelize(str.replace(customizeRE, "-"));
}
function hasLeadingSlash(str) {
  return str.indexOf("/") === 0;
}
function addLeadingSlash(str) {
  return hasLeadingSlash(str) ? str : "/" + str;
}
const invokeArrayFns = (fns, arg) => {
  let ret;
  for (let i = 0; i < fns.length; i++) {
    ret = fns[i](arg);
  }
  return ret;
};
function once(fn, ctx = null) {
  let res;
  return (...args) => {
    if (fn) {
      res = fn.apply(ctx, args);
      fn = null;
    }
    return res;
  };
}
function getValueByDataPath(obj, path) {
  if (!isString(path)) {
    return;
  }
  path = path.replace(/\[(\d+)\]/g, ".$1");
  const parts = path.split(".");
  let key = parts[0];
  if (!obj) {
    obj = {};
  }
  if (parts.length === 1) {
    return obj[key];
  }
  return getValueByDataPath(obj[key], parts.slice(1).join("."));
}
const encode = encodeURIComponent;
function stringifyQuery(obj, encodeStr = encode) {
  const res = obj ? Object.keys(obj).map((key) => {
    let val = obj[key];
    if (typeof val === void 0 || val === null) {
      val = "";
    } else if (isPlainObject$1(val)) {
      val = JSON.stringify(val);
    }
    return encodeStr(key) + "=" + encodeStr(val);
  }).filter((x) => x.length > 0).join("&") : null;
  return res ? `?${res}` : "";
}
const PAGE_HOOKS = [
  ON_INIT,
  ON_LOAD,
  ON_SHOW,
  ON_HIDE,
  ON_UNLOAD,
  ON_RESIZE,
  ON_BACK_PRESS,
  ON_PAGE_SCROLL,
  ON_TAB_ITEM_TAP,
  ON_REACH_BOTTOM,
  ON_PULL_DOWN_REFRESH,
  ON_SHARE_TIMELINE,
  ON_SHARE_APP_MESSAGE,
  ON_SHARE_CHAT,
  ON_COPY_URL,
  ON_UPLOAD_DOUYIN_VIDEO,
  ON_LIVE_MOUNT,
  ON_TITLE_CLICK,
  ON_ADD_TO_FAVORITES,
  ON_SAVE_EXIT_STATE,
  ON_NAVIGATION_BAR_BUTTON_TAP,
  ON_NAVIGATION_BAR_SEARCH_INPUT_CLICKED,
  ON_NAVIGATION_BAR_SEARCH_INPUT_CHANGED,
  ON_NAVIGATION_BAR_SEARCH_INPUT_CONFIRMED,
  ON_NAVIGATION_BAR_SEARCH_INPUT_FOCUS_CHANGED
];
function isRootHook(name) {
  return PAGE_HOOKS.indexOf(name) > -1;
}
const UniLifecycleHooks = [
  ON_SHOW,
  ON_HIDE,
  ON_LAUNCH,
  ON_ERROR,
  ON_THEME_CHANGE,
  ON_PAGE_NOT_FOUND,
  ON_UNHANDLE_REJECTION,
  ON_EXIT,
  ON_INIT,
  ON_LOAD,
  ON_READY,
  ON_UNLOAD,
  ON_RESIZE,
  ON_BACK_PRESS,
  ON_PAGE_SCROLL,
  ON_TAB_ITEM_TAP,
  ON_REACH_BOTTOM,
  ON_PULL_DOWN_REFRESH,
  ON_SHARE_TIMELINE,
  ON_ADD_TO_FAVORITES,
  ON_SHARE_APP_MESSAGE,
  ON_SHARE_CHAT,
  ON_COPY_URL,
  ON_UPLOAD_DOUYIN_VIDEO,
  ON_LIVE_MOUNT,
  ON_TITLE_CLICK,
  ON_SAVE_EXIT_STATE,
  ON_NAVIGATION_BAR_BUTTON_TAP,
  ON_NAVIGATION_BAR_SEARCH_INPUT_CLICKED,
  ON_NAVIGATION_BAR_SEARCH_INPUT_CHANGED,
  ON_NAVIGATION_BAR_SEARCH_INPUT_CONFIRMED,
  ON_NAVIGATION_BAR_SEARCH_INPUT_FOCUS_CHANGED,
  ON_LAST_PAGE_BACK_PRESS
];
const MINI_PROGRAM_PAGE_RUNTIME_HOOKS = /* @__PURE__ */ (() => {
  return {
    onPageScroll: 1,
    onShareAppMessage: 1 << 1,
    onShareTimeline: 1 << 2,
    onShareChat: 1 << 3,
    onCopyUrl: 1 << 4,
    onUploadDouyinVideo: 1 << 5,
    onLiveMount: 1 << 6,
    onTitleClick: 1 << 7
  };
})();
function isUniLifecycleHook(name, value, checkType = true) {
  if (checkType && !isFunction(value)) {
    return false;
  }
  if (UniLifecycleHooks.indexOf(name) > -1) {
    return true;
  } else if (name.indexOf("on") === 0) {
    return true;
  }
  return false;
}
let vueApp;
const createVueAppHooks = [];
function onCreateVueApp(hook) {
  if (vueApp) {
    return hook(vueApp);
  }
  createVueAppHooks.push(hook);
}
function invokeCreateVueAppHook(app) {
  vueApp = app;
  createVueAppHooks.forEach((hook) => hook(app));
}
const invokeCreateErrorHandler = once((app, createErrorHandler2) => {
  return createErrorHandler2(app);
});
const E = function() {
};
E.prototype = {
  _id: 1,
  on: function(name, callback, ctx) {
    var e2 = this.e || (this.e = {});
    (e2[name] || (e2[name] = [])).push({
      fn: callback,
      ctx,
      _id: this._id
    });
    return this._id++;
  },
  once: function(name, callback, ctx) {
    var self2 = this;
    function listener() {
      self2.off(name, listener);
      callback.apply(ctx, arguments);
    }
    listener._ = callback;
    return this.on(name, listener, ctx);
  },
  emit: function(name) {
    var data = [].slice.call(arguments, 1);
    var evtArr = ((this.e || (this.e = {}))[name] || []).slice();
    var i = 0;
    var len = evtArr.length;
    for (i; i < len; i++) {
      evtArr[i].fn.apply(evtArr[i].ctx, data);
    }
    return this;
  },
  off: function(name, event) {
    var e2 = this.e || (this.e = {});
    var evts = e2[name];
    var liveEvents = [];
    if (evts && event) {
      for (var i = evts.length - 1; i >= 0; i--) {
        if (evts[i].fn === event || evts[i].fn._ === event || evts[i]._id === event) {
          evts.splice(i, 1);
          break;
        }
      }
      liveEvents = evts;
    }
    liveEvents.length ? e2[name] = liveEvents : delete e2[name];
    return this;
  }
};
var E$1 = E;
/**
* @dcloudio/uni-mp-vue v3.4.21
* (c) 2018-present Yuxi (Evan) You and Vue contributors
* @license MIT
**/
function warn$2(msg, ...args) {
  console.warn(`[Vue warn] ${msg}`, ...args);
}
let activeEffectScope;
class EffectScope {
  constructor(detached = false) {
    this.detached = detached;
    this._active = true;
    this.effects = [];
    this.cleanups = [];
    this.parent = activeEffectScope;
    if (!detached && activeEffectScope) {
      this.index = (activeEffectScope.scopes || (activeEffectScope.scopes = [])).push(
        this
      ) - 1;
    }
  }
  get active() {
    return this._active;
  }
  run(fn) {
    if (this._active) {
      const currentEffectScope = activeEffectScope;
      try {
        activeEffectScope = this;
        return fn();
      } finally {
        activeEffectScope = currentEffectScope;
      }
    } else {
      warn$2(`cannot run an inactive effect scope.`);
    }
  }
  /**
   * This should only be called on non-detached scopes
   * @internal
   */
  on() {
    activeEffectScope = this;
  }
  /**
   * This should only be called on non-detached scopes
   * @internal
   */
  off() {
    activeEffectScope = this.parent;
  }
  stop(fromParent) {
    if (this._active) {
      let i, l;
      for (i = 0, l = this.effects.length; i < l; i++) {
        this.effects[i].stop();
      }
      for (i = 0, l = this.cleanups.length; i < l; i++) {
        this.cleanups[i]();
      }
      if (this.scopes) {
        for (i = 0, l = this.scopes.length; i < l; i++) {
          this.scopes[i].stop(true);
        }
      }
      if (!this.detached && this.parent && !fromParent) {
        const last = this.parent.scopes.pop();
        if (last && last !== this) {
          this.parent.scopes[this.index] = last;
          last.index = this.index;
        }
      }
      this.parent = void 0;
      this._active = false;
    }
  }
}
function effectScope(detached) {
  return new EffectScope(detached);
}
function recordEffectScope(effect2, scope = activeEffectScope) {
  if (scope && scope.active) {
    scope.effects.push(effect2);
  }
}
function getCurrentScope() {
  return activeEffectScope;
}
function onScopeDispose(fn) {
  if (activeEffectScope) {
    activeEffectScope.cleanups.push(fn);
  } else {
    warn$2(
      `onScopeDispose() is called when there is no active effect scope to be associated with.`
    );
  }
}
let activeEffect;
class ReactiveEffect {
  constructor(fn, trigger2, scheduler, scope) {
    this.fn = fn;
    this.trigger = trigger2;
    this.scheduler = scheduler;
    this.active = true;
    this.deps = [];
    this._dirtyLevel = 4;
    this._trackId = 0;
    this._runnings = 0;
    this._shouldSchedule = false;
    this._depsLength = 0;
    recordEffectScope(this, scope);
  }
  get dirty() {
    if (this._dirtyLevel === 2 || this._dirtyLevel === 3) {
      this._dirtyLevel = 1;
      pauseTracking();
      for (let i = 0; i < this._depsLength; i++) {
        const dep = this.deps[i];
        if (dep.computed) {
          triggerComputed(dep.computed);
          if (this._dirtyLevel >= 4) {
            break;
          }
        }
      }
      if (this._dirtyLevel === 1) {
        this._dirtyLevel = 0;
      }
      resetTracking();
    }
    return this._dirtyLevel >= 4;
  }
  set dirty(v) {
    this._dirtyLevel = v ? 4 : 0;
  }
  run() {
    this._dirtyLevel = 0;
    if (!this.active) {
      return this.fn();
    }
    let lastShouldTrack = shouldTrack;
    let lastEffect = activeEffect;
    try {
      shouldTrack = true;
      activeEffect = this;
      this._runnings++;
      preCleanupEffect(this);
      return this.fn();
    } finally {
      postCleanupEffect(this);
      this._runnings--;
      activeEffect = lastEffect;
      shouldTrack = lastShouldTrack;
    }
  }
  stop() {
    var _a;
    if (this.active) {
      preCleanupEffect(this);
      postCleanupEffect(this);
      (_a = this.onStop) == null ? void 0 : _a.call(this);
      this.active = false;
    }
  }
}
function triggerComputed(computed2) {
  return computed2.value;
}
function preCleanupEffect(effect2) {
  effect2._trackId++;
  effect2._depsLength = 0;
}
function postCleanupEffect(effect2) {
  if (effect2.deps.length > effect2._depsLength) {
    for (let i = effect2._depsLength; i < effect2.deps.length; i++) {
      cleanupDepEffect(effect2.deps[i], effect2);
    }
    effect2.deps.length = effect2._depsLength;
  }
}
function cleanupDepEffect(dep, effect2) {
  const trackId = dep.get(effect2);
  if (trackId !== void 0 && effect2._trackId !== trackId) {
    dep.delete(effect2);
    if (dep.size === 0) {
      dep.cleanup();
    }
  }
}
let shouldTrack = true;
let pauseScheduleStack = 0;
const trackStack = [];
function pauseTracking() {
  trackStack.push(shouldTrack);
  shouldTrack = false;
}
function resetTracking() {
  const last = trackStack.pop();
  shouldTrack = last === void 0 ? true : last;
}
function pauseScheduling() {
  pauseScheduleStack++;
}
function resetScheduling() {
  pauseScheduleStack--;
  while (!pauseScheduleStack && queueEffectSchedulers.length) {
    queueEffectSchedulers.shift()();
  }
}
function trackEffect(effect2, dep, debuggerEventExtraInfo) {
  var _a;
  if (dep.get(effect2) !== effect2._trackId) {
    dep.set(effect2, effect2._trackId);
    const oldDep = effect2.deps[effect2._depsLength];
    if (oldDep !== dep) {
      if (oldDep) {
        cleanupDepEffect(oldDep, effect2);
      }
      effect2.deps[effect2._depsLength++] = dep;
    } else {
      effect2._depsLength++;
    }
    {
      (_a = effect2.onTrack) == null ? void 0 : _a.call(effect2, extend({ effect: effect2 }, debuggerEventExtraInfo));
    }
  }
}
const queueEffectSchedulers = [];
function triggerEffects(dep, dirtyLevel, debuggerEventExtraInfo) {
  var _a;
  pauseScheduling();
  for (const effect2 of dep.keys()) {
    let tracking;
    if (effect2._dirtyLevel < dirtyLevel && (tracking != null ? tracking : tracking = dep.get(effect2) === effect2._trackId)) {
      effect2._shouldSchedule || (effect2._shouldSchedule = effect2._dirtyLevel === 0);
      effect2._dirtyLevel = dirtyLevel;
    }
    if (effect2._shouldSchedule && (tracking != null ? tracking : tracking = dep.get(effect2) === effect2._trackId)) {
      {
        (_a = effect2.onTrigger) == null ? void 0 : _a.call(effect2, extend({ effect: effect2 }, debuggerEventExtraInfo));
      }
      effect2.trigger();
      if ((!effect2._runnings || effect2.allowRecurse) && effect2._dirtyLevel !== 2) {
        effect2._shouldSchedule = false;
        if (effect2.scheduler) {
          queueEffectSchedulers.push(effect2.scheduler);
        }
      }
    }
  }
  resetScheduling();
}
const createDep = (cleanup, computed2) => {
  const dep = /* @__PURE__ */ new Map();
  dep.cleanup = cleanup;
  dep.computed = computed2;
  return dep;
};
const targetMap = /* @__PURE__ */ new WeakMap();
const ITERATE_KEY = Symbol("iterate");
const MAP_KEY_ITERATE_KEY = Symbol("Map key iterate");
function track(target, type, key) {
  if (shouldTrack && activeEffect) {
    let depsMap = targetMap.get(target);
    if (!depsMap) {
      targetMap.set(target, depsMap = /* @__PURE__ */ new Map());
    }
    let dep = depsMap.get(key);
    if (!dep) {
      depsMap.set(key, dep = createDep(() => depsMap.delete(key)));
    }
    trackEffect(
      activeEffect,
      dep,
      {
        target,
        type,
        key
      }
    );
  }
}
function trigger(target, type, key, newValue, oldValue, oldTarget) {
  const depsMap = targetMap.get(target);
  if (!depsMap) {
    return;
  }
  let deps = [];
  if (type === "clear") {
    deps = [...depsMap.values()];
  } else if (key === "length" && isArray(target)) {
    const newLength = Number(newValue);
    depsMap.forEach((dep, key2) => {
      if (key2 === "length" || !isSymbol(key2) && key2 >= newLength) {
        deps.push(dep);
      }
    });
  } else {
    if (key !== void 0) {
      deps.push(depsMap.get(key));
    }
    switch (type) {
      case "add":
        if (!isArray(target)) {
          deps.push(depsMap.get(ITERATE_KEY));
          if (isMap(target)) {
            deps.push(depsMap.get(MAP_KEY_ITERATE_KEY));
          }
        } else if (isIntegerKey(key)) {
          deps.push(depsMap.get("length"));
        }
        break;
      case "delete":
        if (!isArray(target)) {
          deps.push(depsMap.get(ITERATE_KEY));
          if (isMap(target)) {
            deps.push(depsMap.get(MAP_KEY_ITERATE_KEY));
          }
        }
        break;
      case "set":
        if (isMap(target)) {
          deps.push(depsMap.get(ITERATE_KEY));
        }
        break;
    }
  }
  pauseScheduling();
  for (const dep of deps) {
    if (dep) {
      triggerEffects(
        dep,
        4,
        {
          target,
          type,
          key,
          newValue,
          oldValue,
          oldTarget
        }
      );
    }
  }
  resetScheduling();
}
function getDepFromReactive(object, key) {
  var _a;
  return (_a = targetMap.get(object)) == null ? void 0 : _a.get(key);
}
const isNonTrackableKeys = /* @__PURE__ */ makeMap(`__proto__,__v_isRef,__isVue`);
const builtInSymbols = new Set(
  /* @__PURE__ */ Object.getOwnPropertyNames(Symbol).filter((key) => key !== "arguments" && key !== "caller").map((key) => Symbol[key]).filter(isSymbol)
);
const arrayInstrumentations = /* @__PURE__ */ createArrayInstrumentations();
function createArrayInstrumentations() {
  const instrumentations = {};
  ["includes", "indexOf", "lastIndexOf"].forEach((key) => {
    instrumentations[key] = function(...args) {
      const arr = toRaw(this);
      for (let i = 0, l = this.length; i < l; i++) {
        track(arr, "get", i + "");
      }
      const res = arr[key](...args);
      if (res === -1 || res === false) {
        return arr[key](...args.map(toRaw));
      } else {
        return res;
      }
    };
  });
  ["push", "pop", "shift", "unshift", "splice"].forEach((key) => {
    instrumentations[key] = function(...args) {
      pauseTracking();
      pauseScheduling();
      const res = toRaw(this)[key].apply(this, args);
      resetScheduling();
      resetTracking();
      return res;
    };
  });
  return instrumentations;
}
function hasOwnProperty(key) {
  const obj = toRaw(this);
  track(obj, "has", key);
  return obj.hasOwnProperty(key);
}
class BaseReactiveHandler {
  constructor(_isReadonly = false, _isShallow = false) {
    this._isReadonly = _isReadonly;
    this._isShallow = _isShallow;
  }
  get(target, key, receiver) {
    const isReadonly2 = this._isReadonly, isShallow2 = this._isShallow;
    if (key === "__v_isReactive") {
      return !isReadonly2;
    } else if (key === "__v_isReadonly") {
      return isReadonly2;
    } else if (key === "__v_isShallow") {
      return isShallow2;
    } else if (key === "__v_raw") {
      if (receiver === (isReadonly2 ? isShallow2 ? shallowReadonlyMap : readonlyMap : isShallow2 ? shallowReactiveMap : reactiveMap).get(target) || // receiver is not the reactive proxy, but has the same prototype
      // this means the reciever is a user proxy of the reactive proxy
      Object.getPrototypeOf(target) === Object.getPrototypeOf(receiver)) {
        return target;
      }
      return;
    }
    const targetIsArray = isArray(target);
    if (!isReadonly2) {
      if (targetIsArray && hasOwn(arrayInstrumentations, key)) {
        return Reflect.get(arrayInstrumentations, key, receiver);
      }
      if (key === "hasOwnProperty") {
        return hasOwnProperty;
      }
    }
    const res = Reflect.get(target, key, receiver);
    if (isSymbol(key) ? builtInSymbols.has(key) : isNonTrackableKeys(key)) {
      return res;
    }
    if (!isReadonly2) {
      track(target, "get", key);
    }
    if (isShallow2) {
      return res;
    }
    if (isRef(res)) {
      return targetIsArray && isIntegerKey(key) ? res : res.value;
    }
    if (isObject(res)) {
      return isReadonly2 ? readonly(res) : reactive(res);
    }
    return res;
  }
}
class MutableReactiveHandler extends BaseReactiveHandler {
  constructor(isShallow2 = false) {
    super(false, isShallow2);
  }
  set(target, key, value, receiver) {
    let oldValue = target[key];
    if (!this._isShallow) {
      const isOldValueReadonly = isReadonly(oldValue);
      if (!isShallow(value) && !isReadonly(value)) {
        oldValue = toRaw(oldValue);
        value = toRaw(value);
      }
      if (!isArray(target) && isRef(oldValue) && !isRef(value)) {
        if (isOldValueReadonly) {
          return false;
        } else {
          oldValue.value = value;
          return true;
        }
      }
    }
    const hadKey = isArray(target) && isIntegerKey(key) ? Number(key) < target.length : hasOwn(target, key);
    const result = Reflect.set(target, key, value, receiver);
    if (target === toRaw(receiver)) {
      if (!hadKey) {
        trigger(target, "add", key, value);
      } else if (hasChanged(value, oldValue)) {
        trigger(target, "set", key, value, oldValue);
      }
    }
    return result;
  }
  deleteProperty(target, key) {
    const hadKey = hasOwn(target, key);
    const oldValue = target[key];
    const result = Reflect.deleteProperty(target, key);
    if (result && hadKey) {
      trigger(target, "delete", key, void 0, oldValue);
    }
    return result;
  }
  has(target, key) {
    const result = Reflect.has(target, key);
    if (!isSymbol(key) || !builtInSymbols.has(key)) {
      track(target, "has", key);
    }
    return result;
  }
  ownKeys(target) {
    track(
      target,
      "iterate",
      isArray(target) ? "length" : ITERATE_KEY
    );
    return Reflect.ownKeys(target);
  }
}
class ReadonlyReactiveHandler extends BaseReactiveHandler {
  constructor(isShallow2 = false) {
    super(true, isShallow2);
  }
  set(target, key) {
    {
      warn$2(
        `Set operation on key "${String(key)}" failed: target is readonly.`,
        target
      );
    }
    return true;
  }
  deleteProperty(target, key) {
    {
      warn$2(
        `Delete operation on key "${String(key)}" failed: target is readonly.`,
        target
      );
    }
    return true;
  }
}
const mutableHandlers = /* @__PURE__ */ new MutableReactiveHandler();
const readonlyHandlers = /* @__PURE__ */ new ReadonlyReactiveHandler();
const shallowReactiveHandlers = /* @__PURE__ */ new MutableReactiveHandler(
  true
);
const shallowReadonlyHandlers = /* @__PURE__ */ new ReadonlyReactiveHandler(true);
const toShallow = (value) => value;
const getProto = (v) => Reflect.getPrototypeOf(v);
function get$1(target, key, isReadonly2 = false, isShallow2 = false) {
  target = target["__v_raw"];
  const rawTarget = toRaw(target);
  const rawKey = toRaw(key);
  if (!isReadonly2) {
    if (hasChanged(key, rawKey)) {
      track(rawTarget, "get", key);
    }
    track(rawTarget, "get", rawKey);
  }
  const { has: has2 } = getProto(rawTarget);
  const wrap = isShallow2 ? toShallow : isReadonly2 ? toReadonly : toReactive;
  if (has2.call(rawTarget, key)) {
    return wrap(target.get(key));
  } else if (has2.call(rawTarget, rawKey)) {
    return wrap(target.get(rawKey));
  } else if (target !== rawTarget) {
    target.get(key);
  }
}
function has$1(key, isReadonly2 = false) {
  const target = this["__v_raw"];
  const rawTarget = toRaw(target);
  const rawKey = toRaw(key);
  if (!isReadonly2) {
    if (hasChanged(key, rawKey)) {
      track(rawTarget, "has", key);
    }
    track(rawTarget, "has", rawKey);
  }
  return key === rawKey ? target.has(key) : target.has(key) || target.has(rawKey);
}
function size$1(target, isReadonly2 = false) {
  target = target["__v_raw"];
  !isReadonly2 && track(toRaw(target), "iterate", ITERATE_KEY);
  return Reflect.get(target, "size", target);
}
function add$1(value) {
  value = toRaw(value);
  const target = toRaw(this);
  const proto = getProto(target);
  const hadKey = proto.has.call(target, value);
  if (!hadKey) {
    target.add(value);
    trigger(target, "add", value, value);
  }
  return this;
}
function set$1$1(key, value) {
  value = toRaw(value);
  const target = toRaw(this);
  const { has: has2, get: get2 } = getProto(target);
  let hadKey = has2.call(target, key);
  if (!hadKey) {
    key = toRaw(key);
    hadKey = has2.call(target, key);
  } else {
    checkIdentityKeys(target, has2, key);
  }
  const oldValue = get2.call(target, key);
  target.set(key, value);
  if (!hadKey) {
    trigger(target, "add", key, value);
  } else if (hasChanged(value, oldValue)) {
    trigger(target, "set", key, value, oldValue);
  }
  return this;
}
function deleteEntry(key) {
  const target = toRaw(this);
  const { has: has2, get: get2 } = getProto(target);
  let hadKey = has2.call(target, key);
  if (!hadKey) {
    key = toRaw(key);
    hadKey = has2.call(target, key);
  } else {
    checkIdentityKeys(target, has2, key);
  }
  const oldValue = get2 ? get2.call(target, key) : void 0;
  const result = target.delete(key);
  if (hadKey) {
    trigger(target, "delete", key, void 0, oldValue);
  }
  return result;
}
function clear() {
  const target = toRaw(this);
  const hadItems = target.size !== 0;
  const oldTarget = isMap(target) ? new Map(target) : new Set(target);
  const result = target.clear();
  if (hadItems) {
    trigger(target, "clear", void 0, void 0, oldTarget);
  }
  return result;
}
function createForEach(isReadonly2, isShallow2) {
  return function forEach(callback, thisArg) {
    const observed = this;
    const target = observed["__v_raw"];
    const rawTarget = toRaw(target);
    const wrap = isShallow2 ? toShallow : isReadonly2 ? toReadonly : toReactive;
    !isReadonly2 && track(rawTarget, "iterate", ITERATE_KEY);
    return target.forEach((value, key) => {
      return callback.call(thisArg, wrap(value), wrap(key), observed);
    });
  };
}
function createIterableMethod(method, isReadonly2, isShallow2) {
  return function(...args) {
    const target = this["__v_raw"];
    const rawTarget = toRaw(target);
    const targetIsMap = isMap(rawTarget);
    const isPair = method === "entries" || method === Symbol.iterator && targetIsMap;
    const isKeyOnly = method === "keys" && targetIsMap;
    const innerIterator = target[method](...args);
    const wrap = isShallow2 ? toShallow : isReadonly2 ? toReadonly : toReactive;
    !isReadonly2 && track(
      rawTarget,
      "iterate",
      isKeyOnly ? MAP_KEY_ITERATE_KEY : ITERATE_KEY
    );
    return {
      // iterator protocol
      next() {
        const { value, done } = innerIterator.next();
        return done ? { value, done } : {
          value: isPair ? [wrap(value[0]), wrap(value[1])] : wrap(value),
          done
        };
      },
      // iterable protocol
      [Symbol.iterator]() {
        return this;
      }
    };
  };
}
function createReadonlyMethod(type) {
  return function(...args) {
    {
      const key = args[0] ? `on key "${args[0]}" ` : ``;
      warn$2(
        `${capitalize(type)} operation ${key}failed: target is readonly.`,
        toRaw(this)
      );
    }
    return type === "delete" ? false : type === "clear" ? void 0 : this;
  };
}
function createInstrumentations() {
  const mutableInstrumentations2 = {
    get(key) {
      return get$1(this, key);
    },
    get size() {
      return size$1(this);
    },
    has: has$1,
    add: add$1,
    set: set$1$1,
    delete: deleteEntry,
    clear,
    forEach: createForEach(false, false)
  };
  const shallowInstrumentations2 = {
    get(key) {
      return get$1(this, key, false, true);
    },
    get size() {
      return size$1(this);
    },
    has: has$1,
    add: add$1,
    set: set$1$1,
    delete: deleteEntry,
    clear,
    forEach: createForEach(false, true)
  };
  const readonlyInstrumentations2 = {
    get(key) {
      return get$1(this, key, true);
    },
    get size() {
      return size$1(this, true);
    },
    has(key) {
      return has$1.call(this, key, true);
    },
    add: createReadonlyMethod("add"),
    set: createReadonlyMethod("set"),
    delete: createReadonlyMethod("delete"),
    clear: createReadonlyMethod("clear"),
    forEach: createForEach(true, false)
  };
  const shallowReadonlyInstrumentations2 = {
    get(key) {
      return get$1(this, key, true, true);
    },
    get size() {
      return size$1(this, true);
    },
    has(key) {
      return has$1.call(this, key, true);
    },
    add: createReadonlyMethod("add"),
    set: createReadonlyMethod("set"),
    delete: createReadonlyMethod("delete"),
    clear: createReadonlyMethod("clear"),
    forEach: createForEach(true, true)
  };
  const iteratorMethods = [
    "keys",
    "values",
    "entries",
    Symbol.iterator
  ];
  iteratorMethods.forEach((method) => {
    mutableInstrumentations2[method] = createIterableMethod(method, false, false);
    readonlyInstrumentations2[method] = createIterableMethod(method, true, false);
    shallowInstrumentations2[method] = createIterableMethod(method, false, true);
    shallowReadonlyInstrumentations2[method] = createIterableMethod(
      method,
      true,
      true
    );
  });
  return [
    mutableInstrumentations2,
    readonlyInstrumentations2,
    shallowInstrumentations2,
    shallowReadonlyInstrumentations2
  ];
}
const [
  mutableInstrumentations,
  readonlyInstrumentations,
  shallowInstrumentations,
  shallowReadonlyInstrumentations
] = /* @__PURE__ */ createInstrumentations();
function createInstrumentationGetter(isReadonly2, shallow) {
  const instrumentations = shallow ? isReadonly2 ? shallowReadonlyInstrumentations : shallowInstrumentations : isReadonly2 ? readonlyInstrumentations : mutableInstrumentations;
  return (target, key, receiver) => {
    if (key === "__v_isReactive") {
      return !isReadonly2;
    } else if (key === "__v_isReadonly") {
      return isReadonly2;
    } else if (key === "__v_raw") {
      return target;
    }
    return Reflect.get(
      hasOwn(instrumentations, key) && key in target ? instrumentations : target,
      key,
      receiver
    );
  };
}
const mutableCollectionHandlers = {
  get: /* @__PURE__ */ createInstrumentationGetter(false, false)
};
const shallowCollectionHandlers = {
  get: /* @__PURE__ */ createInstrumentationGetter(false, true)
};
const readonlyCollectionHandlers = {
  get: /* @__PURE__ */ createInstrumentationGetter(true, false)
};
const shallowReadonlyCollectionHandlers = {
  get: /* @__PURE__ */ createInstrumentationGetter(true, true)
};
function checkIdentityKeys(target, has2, key) {
  const rawKey = toRaw(key);
  if (rawKey !== key && has2.call(target, rawKey)) {
    const type = toRawType(target);
    warn$2(
      `Reactive ${type} contains both the raw and reactive versions of the same object${type === `Map` ? ` as keys` : ``}, which can lead to inconsistencies. Avoid differentiating between the raw and reactive versions of an object and only use the reactive version if possible.`
    );
  }
}
const reactiveMap = /* @__PURE__ */ new WeakMap();
const shallowReactiveMap = /* @__PURE__ */ new WeakMap();
const readonlyMap = /* @__PURE__ */ new WeakMap();
const shallowReadonlyMap = /* @__PURE__ */ new WeakMap();
function targetTypeMap(rawType) {
  switch (rawType) {
    case "Object":
    case "Array":
      return 1;
    case "Map":
    case "Set":
    case "WeakMap":
    case "WeakSet":
      return 2;
    default:
      return 0;
  }
}
function getTargetType(value) {
  return value["__v_skip"] || !Object.isExtensible(value) ? 0 : targetTypeMap(toRawType(value));
}
function reactive(target) {
  if (isReadonly(target)) {
    return target;
  }
  return createReactiveObject(
    target,
    false,
    mutableHandlers,
    mutableCollectionHandlers,
    reactiveMap
  );
}
function shallowReactive(target) {
  return createReactiveObject(
    target,
    false,
    shallowReactiveHandlers,
    shallowCollectionHandlers,
    shallowReactiveMap
  );
}
function readonly(target) {
  return createReactiveObject(
    target,
    true,
    readonlyHandlers,
    readonlyCollectionHandlers,
    readonlyMap
  );
}
function shallowReadonly(target) {
  return createReactiveObject(
    target,
    true,
    shallowReadonlyHandlers,
    shallowReadonlyCollectionHandlers,
    shallowReadonlyMap
  );
}
function createReactiveObject(target, isReadonly2, baseHandlers, collectionHandlers, proxyMap) {
  if (!isObject(target)) {
    {
      warn$2(`value cannot be made reactive: ${String(target)}`);
    }
    return target;
  }
  if (target["__v_raw"] && !(isReadonly2 && target["__v_isReactive"])) {
    return target;
  }
  const existingProxy = proxyMap.get(target);
  if (existingProxy) {
    return existingProxy;
  }
  const targetType = getTargetType(target);
  if (targetType === 0) {
    return target;
  }
  const proxy = new Proxy(
    target,
    targetType === 2 ? collectionHandlers : baseHandlers
  );
  proxyMap.set(target, proxy);
  return proxy;
}
function isReactive(value) {
  if (isReadonly(value)) {
    return isReactive(value["__v_raw"]);
  }
  return !!(value && value["__v_isReactive"]);
}
function isReadonly(value) {
  return !!(value && value["__v_isReadonly"]);
}
function isShallow(value) {
  return !!(value && value["__v_isShallow"]);
}
function isProxy(value) {
  return isReactive(value) || isReadonly(value);
}
function toRaw(observed) {
  const raw = observed && observed["__v_raw"];
  return raw ? toRaw(raw) : observed;
}
function markRaw(value) {
  if (Object.isExtensible(value)) {
    def(value, "__v_skip", true);
  }
  return value;
}
const toReactive = (value) => isObject(value) ? reactive(value) : value;
const toReadonly = (value) => isObject(value) ? readonly(value) : value;
const COMPUTED_SIDE_EFFECT_WARN = `Computed is still dirty after getter evaluation, likely because a computed is mutating its own dependency in its getter. State mutations in computed getters should be avoided.  Check the docs for more details: https://vuejs.org/guide/essentials/computed.html#getters-should-be-side-effect-free`;
class ComputedRefImpl {
  constructor(getter, _setter, isReadonly2, isSSR) {
    this.getter = getter;
    this._setter = _setter;
    this.dep = void 0;
    this.__v_isRef = true;
    this["__v_isReadonly"] = false;
    this.effect = new ReactiveEffect(
      () => getter(this._value),
      () => triggerRefValue(
        this,
        this.effect._dirtyLevel === 2 ? 2 : 3
      )
    );
    this.effect.computed = this;
    this.effect.active = this._cacheable = !isSSR;
    this["__v_isReadonly"] = isReadonly2;
  }
  get value() {
    const self2 = toRaw(this);
    if ((!self2._cacheable || self2.effect.dirty) && hasChanged(self2._value, self2._value = self2.effect.run())) {
      triggerRefValue(self2, 4);
    }
    trackRefValue(self2);
    if (self2.effect._dirtyLevel >= 2) {
      if (this._warnRecursive) {
        warn$2(COMPUTED_SIDE_EFFECT_WARN, `

getter: `, this.getter);
      }
      triggerRefValue(self2, 2);
    }
    return self2._value;
  }
  set value(newValue) {
    this._setter(newValue);
  }
  // #region polyfill _dirty for backward compatibility third party code for Vue <= 3.3.x
  get _dirty() {
    return this.effect.dirty;
  }
  set _dirty(v) {
    this.effect.dirty = v;
  }
  // #endregion
}
function computed$1(getterOrOptions, debugOptions, isSSR = false) {
  let getter;
  let setter;
  const onlyGetter = isFunction(getterOrOptions);
  if (onlyGetter) {
    getter = getterOrOptions;
    setter = () => {
      warn$2("Write operation failed: computed value is readonly");
    };
  } else {
    getter = getterOrOptions.get;
    setter = getterOrOptions.set;
  }
  const cRef = new ComputedRefImpl(getter, setter, onlyGetter || !setter, isSSR);
  if (debugOptions && !isSSR) {
    cRef.effect.onTrack = debugOptions.onTrack;
    cRef.effect.onTrigger = debugOptions.onTrigger;
  }
  return cRef;
}
function trackRefValue(ref2) {
  var _a;
  if (shouldTrack && activeEffect) {
    ref2 = toRaw(ref2);
    trackEffect(
      activeEffect,
      (_a = ref2.dep) != null ? _a : ref2.dep = createDep(
        () => ref2.dep = void 0,
        ref2 instanceof ComputedRefImpl ? ref2 : void 0
      ),
      {
        target: ref2,
        type: "get",
        key: "value"
      }
    );
  }
}
function triggerRefValue(ref2, dirtyLevel = 4, newVal) {
  ref2 = toRaw(ref2);
  const dep = ref2.dep;
  if (dep) {
    triggerEffects(
      dep,
      dirtyLevel,
      {
        target: ref2,
        type: "set",
        key: "value",
        newValue: newVal
      }
    );
  }
}
function isRef(r2) {
  return !!(r2 && r2.__v_isRef === true);
}
function ref(value) {
  return createRef(value, false);
}
function createRef(rawValue, shallow) {
  if (isRef(rawValue)) {
    return rawValue;
  }
  return new RefImpl(rawValue, shallow);
}
class RefImpl {
  constructor(value, __v_isShallow) {
    this.__v_isShallow = __v_isShallow;
    this.dep = void 0;
    this.__v_isRef = true;
    this._rawValue = __v_isShallow ? value : toRaw(value);
    this._value = __v_isShallow ? value : toReactive(value);
  }
  get value() {
    trackRefValue(this);
    return this._value;
  }
  set value(newVal) {
    const useDirectValue = this.__v_isShallow || isShallow(newVal) || isReadonly(newVal);
    newVal = useDirectValue ? newVal : toRaw(newVal);
    if (hasChanged(newVal, this._rawValue)) {
      this._rawValue = newVal;
      this._value = useDirectValue ? newVal : toReactive(newVal);
      triggerRefValue(this, 4, newVal);
    }
  }
}
function unref(ref2) {
  return isRef(ref2) ? ref2.value : ref2;
}
const shallowUnwrapHandlers = {
  get: (target, key, receiver) => unref(Reflect.get(target, key, receiver)),
  set: (target, key, value, receiver) => {
    const oldValue = target[key];
    if (isRef(oldValue) && !isRef(value)) {
      oldValue.value = value;
      return true;
    } else {
      return Reflect.set(target, key, value, receiver);
    }
  }
};
function proxyRefs(objectWithRefs) {
  return isReactive(objectWithRefs) ? objectWithRefs : new Proxy(objectWithRefs, shallowUnwrapHandlers);
}
function toRefs(object) {
  if (!isProxy(object)) {
    warn$2(`toRefs() expects a reactive object but received a plain one.`);
  }
  const ret = isArray(object) ? new Array(object.length) : {};
  for (const key in object) {
    ret[key] = propertyToRef(object, key);
  }
  return ret;
}
class ObjectRefImpl {
  constructor(_object, _key, _defaultValue) {
    this._object = _object;
    this._key = _key;
    this._defaultValue = _defaultValue;
    this.__v_isRef = true;
  }
  get value() {
    const val = this._object[this._key];
    return val === void 0 ? this._defaultValue : val;
  }
  set value(newVal) {
    this._object[this._key] = newVal;
  }
  get dep() {
    return getDepFromReactive(toRaw(this._object), this._key);
  }
}
class GetterRefImpl {
  constructor(_getter) {
    this._getter = _getter;
    this.__v_isRef = true;
    this.__v_isReadonly = true;
  }
  get value() {
    return this._getter();
  }
}
function toRef(source, key, defaultValue) {
  if (isRef(source)) {
    return source;
  } else if (isFunction(source)) {
    return new GetterRefImpl(source);
  } else if (isObject(source) && arguments.length > 1) {
    return propertyToRef(source, key, defaultValue);
  } else {
    return ref(source);
  }
}
function propertyToRef(source, key, defaultValue) {
  const val = source[key];
  return isRef(val) ? val : new ObjectRefImpl(source, key, defaultValue);
}
const stack = [];
function pushWarningContext(vnode) {
  stack.push(vnode);
}
function popWarningContext() {
  stack.pop();
}
function warn$1(msg, ...args) {
  pauseTracking();
  const instance2 = stack.length ? stack[stack.length - 1].component : null;
  const appWarnHandler = instance2 && instance2.appContext.config.warnHandler;
  const trace = getComponentTrace();
  if (appWarnHandler) {
    callWithErrorHandling(
      appWarnHandler,
      instance2,
      11,
      [
        msg + args.map((a) => {
          var _a, _b;
          return (_b = (_a = a.toString) == null ? void 0 : _a.call(a)) != null ? _b : JSON.stringify(a);
        }).join(""),
        instance2 && instance2.proxy,
        trace.map(
          ({ vnode }) => `at <${formatComponentName(instance2, vnode.type)}>`
        ).join("\n"),
        trace
      ]
    );
  } else {
    const warnArgs = [`[Vue warn]: ${msg}`, ...args];
    if (trace.length && // avoid spamming console during tests
    true) {
      warnArgs.push(`
`, ...formatTrace(trace));
    }
    console.warn(...warnArgs);
  }
  resetTracking();
}
function getComponentTrace() {
  let currentVNode = stack[stack.length - 1];
  if (!currentVNode) {
    return [];
  }
  const normalizedStack = [];
  while (currentVNode) {
    const last = normalizedStack[0];
    if (last && last.vnode === currentVNode) {
      last.recurseCount++;
    } else {
      normalizedStack.push({
        vnode: currentVNode,
        recurseCount: 0
      });
    }
    const parentInstance = currentVNode.component && currentVNode.component.parent;
    currentVNode = parentInstance && parentInstance.vnode;
  }
  return normalizedStack;
}
function formatTrace(trace) {
  const logs = [];
  trace.forEach((entry, i) => {
    logs.push(...i === 0 ? [] : [`
`], ...formatTraceEntry(entry));
  });
  return logs;
}
function formatTraceEntry({ vnode, recurseCount }) {
  const postfix = recurseCount > 0 ? `... (${recurseCount} recursive calls)` : ``;
  const isRoot = vnode.component ? vnode.component.parent == null : false;
  const open = ` at <${formatComponentName(
    vnode.component,
    vnode.type,
    isRoot
  )}`;
  const close = `>` + postfix;
  return vnode.props ? [open, ...formatProps(vnode.props), close] : [open + close];
}
function formatProps(props) {
  const res = [];
  const keys = Object.keys(props);
  keys.slice(0, 3).forEach((key) => {
    res.push(...formatProp(key, props[key]));
  });
  if (keys.length > 3) {
    res.push(` ...`);
  }
  return res;
}
function formatProp(key, value, raw) {
  if (isString(value)) {
    value = JSON.stringify(value);
    return raw ? value : [`${key}=${value}`];
  } else if (typeof value === "number" || typeof value === "boolean" || value == null) {
    return raw ? value : [`${key}=${value}`];
  } else if (isRef(value)) {
    value = formatProp(key, toRaw(value.value), true);
    return raw ? value : [`${key}=Ref<`, value, `>`];
  } else if (isFunction(value)) {
    return [`${key}=fn${value.name ? `<${value.name}>` : ``}`];
  } else {
    value = toRaw(value);
    return raw ? value : [`${key}=`, value];
  }
}
const ErrorTypeStrings = {
  ["sp"]: "serverPrefetch hook",
  ["bc"]: "beforeCreate hook",
  ["c"]: "created hook",
  ["bm"]: "beforeMount hook",
  ["m"]: "mounted hook",
  ["bu"]: "beforeUpdate hook",
  ["u"]: "updated",
  ["bum"]: "beforeUnmount hook",
  ["um"]: "unmounted hook",
  ["a"]: "activated hook",
  ["da"]: "deactivated hook",
  ["ec"]: "errorCaptured hook",
  ["rtc"]: "renderTracked hook",
  ["rtg"]: "renderTriggered hook",
  [0]: "setup function",
  [1]: "render function",
  [2]: "watcher getter",
  [3]: "watcher callback",
  [4]: "watcher cleanup function",
  [5]: "native event handler",
  [6]: "component event handler",
  [7]: "vnode hook",
  [8]: "directive hook",
  [9]: "transition hook",
  [10]: "app errorHandler",
  [11]: "app warnHandler",
  [12]: "ref function",
  [13]: "async component loader",
  [14]: "scheduler flush. This is likely a Vue internals bug. Please open an issue at https://github.com/vuejs/core ."
};
function callWithErrorHandling(fn, instance2, type, args) {
  try {
    return args ? fn(...args) : fn();
  } catch (err) {
    handleError$1(err, instance2, type);
  }
}
function callWithAsyncErrorHandling(fn, instance2, type, args) {
  if (isFunction(fn)) {
    const res = callWithErrorHandling(fn, instance2, type, args);
    if (res && isPromise(res)) {
      res.catch((err) => {
        handleError$1(err, instance2, type);
      });
    }
    return res;
  }
  const values = [];
  for (let i = 0; i < fn.length; i++) {
    values.push(callWithAsyncErrorHandling(fn[i], instance2, type, args));
  }
  return values;
}
function handleError$1(err, instance2, type, throwInDev = true) {
  const contextVNode = instance2 ? instance2.vnode : null;
  if (instance2) {
    let cur = instance2.parent;
    const exposedInstance = instance2.proxy;
    const errorInfo = ErrorTypeStrings[type] || type;
    while (cur) {
      const errorCapturedHooks = cur.ec;
      if (errorCapturedHooks) {
        for (let i = 0; i < errorCapturedHooks.length; i++) {
          if (errorCapturedHooks[i](err, exposedInstance, errorInfo) === false) {
            return;
          }
        }
      }
      cur = cur.parent;
    }
    const appErrorHandler = instance2.appContext.config.errorHandler;
    if (appErrorHandler) {
      callWithErrorHandling(
        appErrorHandler,
        null,
        10,
        [err, exposedInstance, errorInfo]
      );
      return;
    }
  }
  logError(err, type, contextVNode, throwInDev);
}
function logError(err, type, contextVNode, throwInDev = true) {
  {
    const info = ErrorTypeStrings[type] || type;
    if (contextVNode) {
      pushWarningContext(contextVNode);
    }
    warn$1(`Unhandled error${info ? ` during execution of ${info}` : ``}`);
    if (contextVNode) {
      popWarningContext();
    }
    if (throwInDev) {
      console.error(err);
    } else {
      console.error(err);
    }
  }
}
let isFlushing = false;
let isFlushPending = false;
const queue$1 = [];
let flushIndex = 0;
const pendingPostFlushCbs = [];
let activePostFlushCbs = null;
let postFlushIndex = 0;
const resolvedPromise = /* @__PURE__ */ Promise.resolve();
let currentFlushPromise = null;
const RECURSION_LIMIT = 100;
function nextTick$1(fn) {
  const p2 = currentFlushPromise || resolvedPromise;
  return fn ? p2.then(this ? fn.bind(this) : fn) : p2;
}
function findInsertionIndex(id) {
  let start = flushIndex + 1;
  let end = queue$1.length;
  while (start < end) {
    const middle = start + end >>> 1;
    const middleJob = queue$1[middle];
    const middleJobId = getId(middleJob);
    if (middleJobId < id || middleJobId === id && middleJob.pre) {
      start = middle + 1;
    } else {
      end = middle;
    }
  }
  return start;
}
function queueJob(job) {
  if (!queue$1.length || !queue$1.includes(
    job,
    isFlushing && job.allowRecurse ? flushIndex + 1 : flushIndex
  )) {
    if (job.id == null) {
      queue$1.push(job);
    } else {
      queue$1.splice(findInsertionIndex(job.id), 0, job);
    }
    queueFlush();
  }
}
function queueFlush() {
  if (!isFlushing && !isFlushPending) {
    isFlushPending = true;
    currentFlushPromise = resolvedPromise.then(flushJobs);
  }
}
function hasQueueJob(job) {
  return queue$1.indexOf(job) > -1;
}
function invalidateJob(job) {
  const i = queue$1.indexOf(job);
  if (i > flushIndex) {
    queue$1.splice(i, 1);
  }
}
function queuePostFlushCb(cb) {
  if (!isArray(cb)) {
    if (!activePostFlushCbs || !activePostFlushCbs.includes(
      cb,
      cb.allowRecurse ? postFlushIndex + 1 : postFlushIndex
    )) {
      pendingPostFlushCbs.push(cb);
    }
  } else {
    pendingPostFlushCbs.push(...cb);
  }
  queueFlush();
}
function flushPreFlushCbs(instance2, seen, i = isFlushing ? flushIndex + 1 : 0) {
  {
    seen = seen || /* @__PURE__ */ new Map();
  }
  for (; i < queue$1.length; i++) {
    const cb = queue$1[i];
    if (cb && cb.pre) {
      if (checkRecursiveUpdates(seen, cb)) {
        continue;
      }
      queue$1.splice(i, 1);
      i--;
      cb();
    }
  }
}
function flushPostFlushCbs(seen) {
  if (pendingPostFlushCbs.length) {
    const deduped = [...new Set(pendingPostFlushCbs)].sort(
      (a, b) => getId(a) - getId(b)
    );
    pendingPostFlushCbs.length = 0;
    if (activePostFlushCbs) {
      activePostFlushCbs.push(...deduped);
      return;
    }
    activePostFlushCbs = deduped;
    {
      seen = seen || /* @__PURE__ */ new Map();
    }
    for (postFlushIndex = 0; postFlushIndex < activePostFlushCbs.length; postFlushIndex++) {
      if (checkRecursiveUpdates(seen, activePostFlushCbs[postFlushIndex])) {
        continue;
      }
      activePostFlushCbs[postFlushIndex]();
    }
    activePostFlushCbs = null;
    postFlushIndex = 0;
  }
}
const getId = (job) => job.id == null ? Infinity : job.id;
const comparator = (a, b) => {
  const diff2 = getId(a) - getId(b);
  if (diff2 === 0) {
    if (a.pre && !b.pre)
      return -1;
    if (b.pre && !a.pre)
      return 1;
  }
  return diff2;
};
function flushJobs(seen) {
  isFlushPending = false;
  isFlushing = true;
  {
    seen = seen || /* @__PURE__ */ new Map();
  }
  queue$1.sort(comparator);
  const check = (job) => checkRecursiveUpdates(seen, job);
  try {
    for (flushIndex = 0; flushIndex < queue$1.length; flushIndex++) {
      const job = queue$1[flushIndex];
      if (job && job.active !== false) {
        if (check(job)) {
          continue;
        }
        callWithErrorHandling(job, null, 14);
      }
    }
  } finally {
    flushIndex = 0;
    queue$1.length = 0;
    flushPostFlushCbs(seen);
    isFlushing = false;
    currentFlushPromise = null;
    if (queue$1.length || pendingPostFlushCbs.length) {
      flushJobs(seen);
    }
  }
}
function checkRecursiveUpdates(seen, fn) {
  if (!seen.has(fn)) {
    seen.set(fn, 1);
  } else {
    const count = seen.get(fn);
    if (count > RECURSION_LIMIT) {
      const instance2 = fn.ownerInstance;
      const componentName = instance2 && getComponentName(instance2.type);
      handleError$1(
        `Maximum recursive updates exceeded${componentName ? ` in component <${componentName}>` : ``}. This means you have a reactive effect that is mutating its own dependencies and thus recursively triggering itself. Possible sources include component template, render function, updated hook or watcher source function.`,
        null,
        10
      );
      return true;
    } else {
      seen.set(fn, count + 1);
    }
  }
}
let devtools;
let buffer = [];
let devtoolsNotInstalled = false;
function emit$1(event, ...args) {
  if (devtools) {
    devtools.emit(event, ...args);
  } else if (!devtoolsNotInstalled) {
    buffer.push({ event, args });
  }
}
function setDevtoolsHook(hook, target) {
  var _a, _b;
  devtools = hook;
  if (devtools) {
    devtools.enabled = true;
    buffer.forEach(({ event, args }) => devtools.emit(event, ...args));
    buffer = [];
  } else if (
    // handle late devtools injection - only do this if we are in an actual
    // browser environment to avoid the timer handle stalling test runner exit
    // (#4815)
    typeof window !== "undefined" && // some envs mock window but not fully
    window.HTMLElement && // also exclude jsdom
    !((_b = (_a = window.navigator) == null ? void 0 : _a.userAgent) == null ? void 0 : _b.includes("jsdom"))
  ) {
    const replay = target.__VUE_DEVTOOLS_HOOK_REPLAY__ = target.__VUE_DEVTOOLS_HOOK_REPLAY__ || [];
    replay.push((newHook) => {
      setDevtoolsHook(newHook, target);
    });
    setTimeout(() => {
      if (!devtools) {
        target.__VUE_DEVTOOLS_HOOK_REPLAY__ = null;
        devtoolsNotInstalled = true;
        buffer = [];
      }
    }, 3e3);
  } else {
    devtoolsNotInstalled = true;
    buffer = [];
  }
}
function devtoolsInitApp(app, version2) {
  emit$1("app:init", app, version2, {
    Fragment,
    Text,
    Comment,
    Static
  });
}
const devtoolsComponentAdded = /* @__PURE__ */ createDevtoolsComponentHook(
  "component:added"
  /* COMPONENT_ADDED */
);
const devtoolsComponentUpdated = /* @__PURE__ */ createDevtoolsComponentHook(
  "component:updated"
  /* COMPONENT_UPDATED */
);
const _devtoolsComponentRemoved = /* @__PURE__ */ createDevtoolsComponentHook(
  "component:removed"
  /* COMPONENT_REMOVED */
);
const devtoolsComponentRemoved = (component) => {
  if (devtools && typeof devtools.cleanupBuffer === "function" && // remove the component if it wasn't buffered
  !devtools.cleanupBuffer(component)) {
    _devtoolsComponentRemoved(component);
  }
};
/*! #__NO_SIDE_EFFECTS__ */
// @__NO_SIDE_EFFECTS__
function createDevtoolsComponentHook(hook) {
  return (component) => {
    emit$1(
      hook,
      component.appContext.app,
      component.uid,
      // fixed by xxxxxx
      // 为 0 是 App，无 parent 是 Page 指向 App
      component.uid === 0 ? void 0 : component.parent ? component.parent.uid : 0,
      component
    );
  };
}
const devtoolsPerfStart = /* @__PURE__ */ createDevtoolsPerformanceHook(
  "perf:start"
  /* PERFORMANCE_START */
);
const devtoolsPerfEnd = /* @__PURE__ */ createDevtoolsPerformanceHook(
  "perf:end"
  /* PERFORMANCE_END */
);
function createDevtoolsPerformanceHook(hook) {
  return (component, type, time) => {
    emit$1(hook, component.appContext.app, component.uid, component, type, time);
  };
}
function devtoolsComponentEmit(component, event, params) {
  emit$1(
    "component:emit",
    component.appContext.app,
    component,
    event,
    params
  );
}
function emit(instance2, event, ...rawArgs) {
  if (instance2.isUnmounted)
    return;
  const props = instance2.vnode.props || EMPTY_OBJ;
  {
    const {
      emitsOptions,
      propsOptions: [propsOptions]
    } = instance2;
    if (emitsOptions) {
      if (!(event in emitsOptions) && true) {
        if (!propsOptions || !(toHandlerKey(event) in propsOptions)) {
          warn$1(
            `Component emitted event "${event}" but it is neither declared in the emits option nor as an "${toHandlerKey(event)}" prop.`
          );
        }
      } else {
        const validator = emitsOptions[event];
        if (isFunction(validator)) {
          const isValid = validator(...rawArgs);
          if (!isValid) {
            warn$1(
              `Invalid event arguments: event validation failed for event "${event}".`
            );
          }
        }
      }
    }
  }
  let args = rawArgs;
  const isModelListener2 = event.startsWith("update:");
  const modelArg = isModelListener2 && event.slice(7);
  if (modelArg && modelArg in props) {
    const modifiersKey = `${modelArg === "modelValue" ? "model" : modelArg}Modifiers`;
    const { number, trim } = props[modifiersKey] || EMPTY_OBJ;
    if (trim) {
      args = rawArgs.map((a) => isString(a) ? a.trim() : a);
    }
    if (number) {
      args = rawArgs.map(looseToNumber);
    }
  }
  {
    devtoolsComponentEmit(instance2, event, args);
  }
  {
    const lowerCaseEvent = event.toLowerCase();
    if (lowerCaseEvent !== event && props[toHandlerKey(lowerCaseEvent)]) {
      warn$1(
        `Event "${lowerCaseEvent}" is emitted in component ${formatComponentName(
          instance2,
          instance2.type
        )} but the handler is registered for "${event}". Note that HTML attributes are case-insensitive and you cannot use v-on to listen to camelCase events when using in-DOM templates. You should probably use "${hyphenate(
          event
        )}" instead of "${event}".`
      );
    }
  }
  let handlerName;
  let handler = props[handlerName = toHandlerKey(event)] || // also try camelCase event handler (#2249)
  props[handlerName = toHandlerKey(camelize(event))];
  if (!handler && isModelListener2) {
    handler = props[handlerName = toHandlerKey(hyphenate(event))];
  }
  if (handler) {
    callWithAsyncErrorHandling(
      handler,
      instance2,
      6,
      args
    );
  }
  const onceHandler = props[handlerName + `Once`];
  if (onceHandler) {
    if (!instance2.emitted) {
      instance2.emitted = {};
    } else if (instance2.emitted[handlerName]) {
      return;
    }
    instance2.emitted[handlerName] = true;
    callWithAsyncErrorHandling(
      onceHandler,
      instance2,
      6,
      args
    );
  }
}
function normalizeEmitsOptions(comp, appContext, asMixin = false) {
  const cache2 = appContext.emitsCache;
  const cached2 = cache2.get(comp);
  if (cached2 !== void 0) {
    return cached2;
  }
  const raw = comp.emits;
  let normalized = {};
  let hasExtends = false;
  if (!isFunction(comp)) {
    const extendEmits = (raw2) => {
      const normalizedFromExtend = normalizeEmitsOptions(raw2, appContext, true);
      if (normalizedFromExtend) {
        hasExtends = true;
        extend(normalized, normalizedFromExtend);
      }
    };
    if (!asMixin && appContext.mixins.length) {
      appContext.mixins.forEach(extendEmits);
    }
    if (comp.extends) {
      extendEmits(comp.extends);
    }
    if (comp.mixins) {
      comp.mixins.forEach(extendEmits);
    }
  }
  if (!raw && !hasExtends) {
    if (isObject(comp)) {
      cache2.set(comp, null);
    }
    return null;
  }
  if (isArray(raw)) {
    raw.forEach((key) => normalized[key] = null);
  } else {
    extend(normalized, raw);
  }
  if (isObject(comp)) {
    cache2.set(comp, normalized);
  }
  return normalized;
}
function isEmitListener(options, key) {
  if (!options || !isOn(key)) {
    return false;
  }
  key = key.slice(2).replace(/Once$/, "");
  return hasOwn(options, key[0].toLowerCase() + key.slice(1)) || hasOwn(options, hyphenate(key)) || hasOwn(options, key);
}
let currentRenderingInstance = null;
function setCurrentRenderingInstance(instance2) {
  const prev = currentRenderingInstance;
  currentRenderingInstance = instance2;
  instance2 && instance2.type.__scopeId || null;
  return prev;
}
const INITIAL_WATCHER_VALUE = {};
function watch(source, cb, options) {
  if (!isFunction(cb)) {
    warn$1(
      `\`watch(fn, options?)\` signature has been moved to a separate API. Use \`watchEffect(fn, options?)\` instead. \`watch\` now only supports \`watch(source, cb, options?) signature.`
    );
  }
  return doWatch(source, cb, options);
}
function doWatch(source, cb, {
  immediate,
  deep,
  flush: flush2,
  once: once2,
  onTrack,
  onTrigger
} = EMPTY_OBJ) {
  if (cb && once2) {
    const _cb = cb;
    cb = (...args) => {
      _cb(...args);
      unwatch();
    };
  }
  if (deep !== void 0 && typeof deep === "number") {
    warn$1(
      `watch() "deep" option with number value will be used as watch depth in future versions. Please use a boolean instead to avoid potential breakage.`
    );
  }
  if (!cb) {
    if (immediate !== void 0) {
      warn$1(
        `watch() "immediate" option is only respected when using the watch(source, callback, options?) signature.`
      );
    }
    if (deep !== void 0) {
      warn$1(
        `watch() "deep" option is only respected when using the watch(source, callback, options?) signature.`
      );
    }
    if (once2 !== void 0) {
      warn$1(
        `watch() "once" option is only respected when using the watch(source, callback, options?) signature.`
      );
    }
  }
  const warnInvalidSource = (s2) => {
    warn$1(
      `Invalid watch source: `,
      s2,
      `A watch source can only be a getter/effect function, a ref, a reactive object, or an array of these types.`
    );
  };
  const instance2 = currentInstance;
  const reactiveGetter = (source2) => deep === true ? source2 : (
    // for deep: false, only traverse root-level properties
    traverse(source2, deep === false ? 1 : void 0)
  );
  let getter;
  let forceTrigger = false;
  let isMultiSource = false;
  if (isRef(source)) {
    getter = () => source.value;
    forceTrigger = isShallow(source);
  } else if (isReactive(source)) {
    getter = () => reactiveGetter(source);
    forceTrigger = true;
  } else if (isArray(source)) {
    isMultiSource = true;
    forceTrigger = source.some((s2) => isReactive(s2) || isShallow(s2));
    getter = () => source.map((s2) => {
      if (isRef(s2)) {
        return s2.value;
      } else if (isReactive(s2)) {
        return reactiveGetter(s2);
      } else if (isFunction(s2)) {
        return callWithErrorHandling(s2, instance2, 2);
      } else {
        warnInvalidSource(s2);
      }
    });
  } else if (isFunction(source)) {
    if (cb) {
      getter = () => callWithErrorHandling(source, instance2, 2);
    } else {
      getter = () => {
        if (cleanup) {
          cleanup();
        }
        return callWithAsyncErrorHandling(
          source,
          instance2,
          3,
          [onCleanup]
        );
      };
    }
  } else {
    getter = NOOP;
    warnInvalidSource(source);
  }
  if (cb && deep) {
    const baseGetter = getter;
    getter = () => traverse(baseGetter());
  }
  let cleanup;
  let onCleanup = (fn) => {
    cleanup = effect2.onStop = () => {
      callWithErrorHandling(fn, instance2, 4);
      cleanup = effect2.onStop = void 0;
    };
  };
  let oldValue = isMultiSource ? new Array(source.length).fill(INITIAL_WATCHER_VALUE) : INITIAL_WATCHER_VALUE;
  const job = () => {
    if (!effect2.active || !effect2.dirty) {
      return;
    }
    if (cb) {
      const newValue = effect2.run();
      if (deep || forceTrigger || (isMultiSource ? newValue.some((v, i) => hasChanged(v, oldValue[i])) : hasChanged(newValue, oldValue)) || false) {
        if (cleanup) {
          cleanup();
        }
        callWithAsyncErrorHandling(cb, instance2, 3, [
          newValue,
          // pass undefined as the old value when it's changed for the first time
          oldValue === INITIAL_WATCHER_VALUE ? void 0 : isMultiSource && oldValue[0] === INITIAL_WATCHER_VALUE ? [] : oldValue,
          onCleanup
        ]);
        oldValue = newValue;
      }
    } else {
      effect2.run();
    }
  };
  job.allowRecurse = !!cb;
  let scheduler;
  if (flush2 === "sync") {
    scheduler = job;
  } else if (flush2 === "post") {
    scheduler = () => queuePostRenderEffect$1(job, instance2 && instance2.suspense);
  } else {
    job.pre = true;
    if (instance2)
      job.id = instance2.uid;
    scheduler = () => queueJob(job);
  }
  const effect2 = new ReactiveEffect(getter, NOOP, scheduler);
  const scope = getCurrentScope();
  const unwatch = () => {
    effect2.stop();
    if (scope) {
      remove$1(scope.effects, effect2);
    }
  };
  {
    effect2.onTrack = onTrack;
    effect2.onTrigger = onTrigger;
  }
  if (cb) {
    if (immediate) {
      job();
    } else {
      oldValue = effect2.run();
    }
  } else if (flush2 === "post") {
    queuePostRenderEffect$1(
      effect2.run.bind(effect2),
      instance2 && instance2.suspense
    );
  } else {
    effect2.run();
  }
  return unwatch;
}
function instanceWatch(source, value, options) {
  const publicThis = this.proxy;
  const getter = isString(source) ? source.includes(".") ? createPathGetter(publicThis, source) : () => publicThis[source] : source.bind(publicThis, publicThis);
  let cb;
  if (isFunction(value)) {
    cb = value;
  } else {
    cb = value.handler;
    options = value;
  }
  const reset = setCurrentInstance(this);
  const res = doWatch(getter, cb.bind(publicThis), options);
  reset();
  return res;
}
function createPathGetter(ctx, path) {
  const segments = path.split(".");
  return () => {
    let cur = ctx;
    for (let i = 0; i < segments.length && cur; i++) {
      cur = cur[segments[i]];
    }
    return cur;
  };
}
function traverse(value, depth, currentDepth = 0, seen) {
  if (!isObject(value) || value["__v_skip"]) {
    return value;
  }
  if (depth && depth > 0) {
    if (currentDepth >= depth) {
      return value;
    }
    currentDepth++;
  }
  seen = seen || /* @__PURE__ */ new Set();
  if (seen.has(value)) {
    return value;
  }
  seen.add(value);
  if (isRef(value)) {
    traverse(value.value, depth, currentDepth, seen);
  } else if (isArray(value)) {
    for (let i = 0; i < value.length; i++) {
      traverse(value[i], depth, currentDepth, seen);
    }
  } else if (isSet(value) || isMap(value)) {
    value.forEach((v) => {
      traverse(v, depth, currentDepth, seen);
    });
  } else if (isPlainObject$1(value)) {
    for (const key in value) {
      traverse(value[key], depth, currentDepth, seen);
    }
  }
  return value;
}
function validateDirectiveName(name) {
  if (isBuiltInDirective(name)) {
    warn$1("Do not use built-in directive ids as custom directive id: " + name);
  }
}
function createAppContext() {
  return {
    app: null,
    config: {
      isNativeTag: NO,
      performance: false,
      globalProperties: {},
      optionMergeStrategies: {},
      errorHandler: void 0,
      warnHandler: void 0,
      compilerOptions: {}
    },
    mixins: [],
    components: {},
    directives: {},
    provides: /* @__PURE__ */ Object.create(null),
    optionsCache: /* @__PURE__ */ new WeakMap(),
    propsCache: /* @__PURE__ */ new WeakMap(),
    emitsCache: /* @__PURE__ */ new WeakMap()
  };
}
let uid$1 = 0;
function createAppAPI(render, hydrate) {
  return function createApp2(rootComponent, rootProps = null) {
    if (!isFunction(rootComponent)) {
      rootComponent = extend({}, rootComponent);
    }
    if (rootProps != null && !isObject(rootProps)) {
      warn$1(`root props passed to app.mount() must be an object.`);
      rootProps = null;
    }
    const context = createAppContext();
    const installedPlugins = /* @__PURE__ */ new WeakSet();
    const app = context.app = {
      _uid: uid$1++,
      _component: rootComponent,
      _props: rootProps,
      _container: null,
      _context: context,
      _instance: null,
      version,
      get config() {
        return context.config;
      },
      set config(v) {
        {
          warn$1(
            `app.config cannot be replaced. Modify individual options instead.`
          );
        }
      },
      use(plugin2, ...options) {
        if (installedPlugins.has(plugin2)) {
          warn$1(`Plugin has already been applied to target app.`);
        } else if (plugin2 && isFunction(plugin2.install)) {
          installedPlugins.add(plugin2);
          plugin2.install(app, ...options);
        } else if (isFunction(plugin2)) {
          installedPlugins.add(plugin2);
          plugin2(app, ...options);
        } else {
          warn$1(
            `A plugin must either be a function or an object with an "install" function.`
          );
        }
        return app;
      },
      mixin(mixin) {
        {
          if (!context.mixins.includes(mixin)) {
            context.mixins.push(mixin);
          } else {
            warn$1(
              "Mixin has already been applied to target app" + (mixin.name ? `: ${mixin.name}` : "")
            );
          }
        }
        return app;
      },
      component(name, component) {
        {
          validateComponentName(name, context.config);
        }
        if (!component) {
          return context.components[name];
        }
        if (context.components[name]) {
          warn$1(`Component "${name}" has already been registered in target app.`);
        }
        context.components[name] = component;
        return app;
      },
      directive(name, directive) {
        {
          validateDirectiveName(name);
        }
        if (!directive) {
          return context.directives[name];
        }
        if (context.directives[name]) {
          warn$1(`Directive "${name}" has already been registered in target app.`);
        }
        context.directives[name] = directive;
        return app;
      },
      // fixed by xxxxxx
      mount() {
      },
      // fixed by xxxxxx
      unmount() {
      },
      provide(key, value) {
        if (key in context.provides) {
          warn$1(
            `App already provides property with key "${String(key)}". It will be overwritten with the new value.`
          );
        }
        context.provides[key] = value;
        return app;
      },
      runWithContext(fn) {
        const lastApp = currentApp;
        currentApp = app;
        try {
          return fn();
        } finally {
          currentApp = lastApp;
        }
      }
    };
    return app;
  };
}
let currentApp = null;
function provide(key, value) {
  if (!currentInstance) {
    {
      warn$1(`provide() can only be used inside setup().`);
    }
  } else {
    let provides = currentInstance.provides;
    const parentProvides = currentInstance.parent && currentInstance.parent.provides;
    if (parentProvides === provides) {
      provides = currentInstance.provides = Object.create(parentProvides);
    }
    provides[key] = value;
    if (currentInstance.type.mpType === "app") {
      currentInstance.appContext.app.provide(key, value);
    }
  }
}
function inject(key, defaultValue, treatDefaultAsFactory = false) {
  const instance2 = currentInstance || currentRenderingInstance;
  if (instance2 || currentApp) {
    const provides = instance2 ? instance2.parent == null ? instance2.vnode.appContext && instance2.vnode.appContext.provides : instance2.parent.provides : currentApp._context.provides;
    if (provides && key in provides) {
      return provides[key];
    } else if (arguments.length > 1) {
      return treatDefaultAsFactory && isFunction(defaultValue) ? defaultValue.call(instance2 && instance2.proxy) : defaultValue;
    } else {
      warn$1(`injection "${String(key)}" not found.`);
    }
  } else {
    warn$1(`inject() can only be used inside setup() or functional components.`);
  }
}
function hasInjectionContext() {
  return !!(currentInstance || currentRenderingInstance || currentApp);
}
const isKeepAlive = (vnode) => vnode.type.__isKeepAlive;
function onActivated(hook, target) {
  registerKeepAliveHook(hook, "a", target);
}
function onDeactivated(hook, target) {
  registerKeepAliveHook(hook, "da", target);
}
function registerKeepAliveHook(hook, type, target = currentInstance) {
  const wrappedHook = hook.__wdc || (hook.__wdc = () => {
    let current = target;
    while (current) {
      if (current.isDeactivated) {
        return;
      }
      current = current.parent;
    }
    return hook();
  });
  injectHook(type, wrappedHook, target);
  if (target) {
    let current = target.parent;
    while (current && current.parent) {
      if (isKeepAlive(current.parent.vnode)) {
        injectToKeepAliveRoot(wrappedHook, type, target, current);
      }
      current = current.parent;
    }
  }
}
function injectToKeepAliveRoot(hook, type, target, keepAliveRoot) {
  const injected = injectHook(
    type,
    hook,
    keepAliveRoot,
    true
    /* prepend */
  );
  onUnmounted(() => {
    remove$1(keepAliveRoot[type], injected);
  }, target);
}
function injectHook(type, hook, target = currentInstance, prepend = false) {
  if (target) {
    if (isRootHook(type)) {
      target = target.root;
    }
    const hooks = target[type] || (target[type] = []);
    const wrappedHook = hook.__weh || (hook.__weh = (...args) => {
      if (target.isUnmounted) {
        return;
      }
      pauseTracking();
      const reset = setCurrentInstance(target);
      const res = callWithAsyncErrorHandling(hook, target, type, args);
      reset();
      resetTracking();
      return res;
    });
    if (prepend) {
      hooks.unshift(wrappedHook);
    } else {
      hooks.push(wrappedHook);
    }
    return wrappedHook;
  } else {
    const apiName = toHandlerKey(
      (ErrorTypeStrings[type] || type.replace(/^on/, "")).replace(/ hook$/, "")
    );
    warn$1(
      `${apiName} is called when there is no active component instance to be associated with. Lifecycle injection APIs can only be used during execution of setup().`
    );
  }
}
const createHook = (lifecycle) => (hook, target = currentInstance) => (
  // post-create lifecycle registrations are noops during SSR (except for serverPrefetch)
  (!isInSSRComponentSetup || lifecycle === "sp") && injectHook(lifecycle, (...args) => hook(...args), target)
);
const onBeforeMount = createHook("bm");
const onMounted = createHook("m");
const onBeforeUpdate = createHook("bu");
const onUpdated = createHook("u");
const onBeforeUnmount = createHook("bum");
const onUnmounted = createHook("um");
const onServerPrefetch = createHook("sp");
const onRenderTriggered = createHook(
  "rtg"
);
const onRenderTracked = createHook(
  "rtc"
);
function onErrorCaptured(hook, target = currentInstance) {
  injectHook("ec", hook, target);
}
const getPublicInstance = (i) => {
  if (!i)
    return null;
  if (isStatefulComponent(i))
    return getExposeProxy(i) || i.proxy;
  return getPublicInstance(i.parent);
};
function getComponentInternalInstance(i) {
  return i;
}
const publicPropertiesMap = (
  // Move PURE marker to new line to workaround compiler discarding it
  // due to type annotation
  /* @__PURE__ */ extend(/* @__PURE__ */ Object.create(null), {
    // fixed by xxxxxx
    $: getComponentInternalInstance,
    // fixed by xxxxxx vue-i18n 在 dev 模式，访问了 $el，故模拟一个假的
    // $el: i => i.vnode.el,
    $el: (i) => i.__$el || (i.__$el = {}),
    $data: (i) => i.data,
    $props: (i) => shallowReadonly(i.props),
    $attrs: (i) => shallowReadonly(i.attrs),
    $slots: (i) => shallowReadonly(i.slots),
    $refs: (i) => shallowReadonly(i.refs),
    $parent: (i) => getPublicInstance(i.parent),
    $root: (i) => getPublicInstance(i.root),
    $emit: (i) => i.emit,
    $options: (i) => resolveMergedOptions(i),
    $forceUpdate: (i) => i.f || (i.f = () => {
      i.effect.dirty = true;
      queueJob(i.update);
    }),
    // $nextTick: i => i.n || (i.n = nextTick.bind(i.proxy!)),// fixed by xxxxxx
    $watch: (i) => instanceWatch.bind(i)
  })
);
const isReservedPrefix = (key) => key === "_" || key === "$";
const hasSetupBinding = (state2, key) => state2 !== EMPTY_OBJ && !state2.__isScriptSetup && hasOwn(state2, key);
const PublicInstanceProxyHandlers = {
  get({ _: instance2 }, key) {
    const { ctx, setupState, data, props, accessCache, type, appContext } = instance2;
    if (key === "__isVue") {
      return true;
    }
    let normalizedProps;
    if (key[0] !== "$") {
      const n2 = accessCache[key];
      if (n2 !== void 0) {
        switch (n2) {
          case 1:
            return setupState[key];
          case 2:
            return data[key];
          case 4:
            return ctx[key];
          case 3:
            return props[key];
        }
      } else if (hasSetupBinding(setupState, key)) {
        accessCache[key] = 1;
        return setupState[key];
      } else if (data !== EMPTY_OBJ && hasOwn(data, key)) {
        accessCache[key] = 2;
        return data[key];
      } else if (
        // only cache other properties when instance has declared (thus stable)
        // props
        (normalizedProps = instance2.propsOptions[0]) && hasOwn(normalizedProps, key)
      ) {
        accessCache[key] = 3;
        return props[key];
      } else if (ctx !== EMPTY_OBJ && hasOwn(ctx, key)) {
        accessCache[key] = 4;
        return ctx[key];
      } else if (shouldCacheAccess) {
        accessCache[key] = 0;
      }
    }
    const publicGetter = publicPropertiesMap[key];
    let cssModule, globalProperties;
    if (publicGetter) {
      if (key === "$attrs") {
        track(instance2, "get", key);
      } else if (key === "$slots") {
        track(instance2, "get", key);
      }
      return publicGetter(instance2);
    } else if (
      // css module (injected by vue-loader)
      (cssModule = type.__cssModules) && (cssModule = cssModule[key])
    ) {
      return cssModule;
    } else if (ctx !== EMPTY_OBJ && hasOwn(ctx, key)) {
      accessCache[key] = 4;
      return ctx[key];
    } else if (instance2.exposed && hasOwn(instance2.exposed, key)) {
      return instance2.exposed[key];
    } else if (
      // global properties
      globalProperties = appContext.config.globalProperties, hasOwn(globalProperties, key)
    ) {
      {
        return globalProperties[key];
      }
    } else if (currentRenderingInstance && (!isString(key) || // #1091 avoid internal isRef/isVNode checks on component instance leading
    // to infinite warning loop
    key.indexOf("__v") !== 0)) {
      if (data !== EMPTY_OBJ && isReservedPrefix(key[0]) && hasOwn(data, key)) {
        warn$1(
          `Property ${JSON.stringify(
            key
          )} must be accessed via $data because it starts with a reserved character ("$" or "_") and is not proxied on the render context.`
        );
      } else if (instance2 === currentRenderingInstance) {
        warn$1(
          `Property ${JSON.stringify(key)} was accessed during render but is not defined on instance.`
        );
      }
    }
  },
  set({ _: instance2 }, key, value) {
    const { data, setupState, ctx } = instance2;
    if (hasSetupBinding(setupState, key)) {
      setupState[key] = value;
      return true;
    } else if (setupState.__isScriptSetup && hasOwn(setupState, key)) {
      warn$1(`Cannot mutate <script setup> binding "${key}" from Options API.`);
      return false;
    } else if (data !== EMPTY_OBJ && hasOwn(data, key)) {
      data[key] = value;
      return true;
    } else if (hasOwn(instance2.props, key)) {
      warn$1(`Attempting to mutate prop "${key}". Props are readonly.`);
      return false;
    }
    if (key[0] === "$" && key.slice(1) in instance2) {
      warn$1(
        `Attempting to mutate public property "${key}". Properties starting with $ are reserved and readonly.`
      );
      return false;
    } else {
      if (key in instance2.appContext.config.globalProperties) {
        Object.defineProperty(ctx, key, {
          enumerable: true,
          configurable: true,
          value
        });
      } else {
        ctx[key] = value;
      }
    }
    return true;
  },
  has({
    _: { data, setupState, accessCache, ctx, appContext, propsOptions }
  }, key) {
    let normalizedProps;
    return !!accessCache[key] || data !== EMPTY_OBJ && hasOwn(data, key) || hasSetupBinding(setupState, key) || (normalizedProps = propsOptions[0]) && hasOwn(normalizedProps, key) || hasOwn(ctx, key) || hasOwn(publicPropertiesMap, key) || hasOwn(appContext.config.globalProperties, key);
  },
  defineProperty(target, key, descriptor) {
    if (descriptor.get != null) {
      target._.accessCache[key] = 0;
    } else if (hasOwn(descriptor, "value")) {
      this.set(target, key, descriptor.value, null);
    }
    return Reflect.defineProperty(target, key, descriptor);
  }
};
{
  PublicInstanceProxyHandlers.ownKeys = (target) => {
    warn$1(
      `Avoid app logic that relies on enumerating keys on a component instance. The keys will be empty in production mode to avoid performance overhead.`
    );
    return Reflect.ownKeys(target);
  };
}
function createDevRenderContext(instance2) {
  const target = {};
  Object.defineProperty(target, `_`, {
    configurable: true,
    enumerable: false,
    get: () => instance2
  });
  Object.keys(publicPropertiesMap).forEach((key) => {
    Object.defineProperty(target, key, {
      configurable: true,
      enumerable: false,
      get: () => publicPropertiesMap[key](instance2),
      // intercepted by the proxy so no need for implementation,
      // but needed to prevent set errors
      set: NOOP
    });
  });
  return target;
}
function exposePropsOnRenderContext(instance2) {
  const {
    ctx,
    propsOptions: [propsOptions]
  } = instance2;
  if (propsOptions) {
    Object.keys(propsOptions).forEach((key) => {
      Object.defineProperty(ctx, key, {
        enumerable: true,
        configurable: true,
        get: () => instance2.props[key],
        set: NOOP
      });
    });
  }
}
function exposeSetupStateOnRenderContext(instance2) {
  const { ctx, setupState } = instance2;
  Object.keys(toRaw(setupState)).forEach((key) => {
    if (!setupState.__isScriptSetup) {
      if (isReservedPrefix(key[0])) {
        warn$1(
          `setup() return property ${JSON.stringify(
            key
          )} should not start with "$" or "_" which are reserved prefixes for Vue internals.`
        );
        return;
      }
      Object.defineProperty(ctx, key, {
        enumerable: true,
        configurable: true,
        get: () => setupState[key],
        set: NOOP
      });
    }
  });
}
function normalizePropsOrEmits(props) {
  return isArray(props) ? props.reduce(
    (normalized, p2) => (normalized[p2] = null, normalized),
    {}
  ) : props;
}
function createDuplicateChecker() {
  const cache2 = /* @__PURE__ */ Object.create(null);
  return (type, key) => {
    if (cache2[key]) {
      warn$1(`${type} property "${key}" is already defined in ${cache2[key]}.`);
    } else {
      cache2[key] = type;
    }
  };
}
let shouldCacheAccess = true;
function applyOptions$1(instance2) {
  const options = resolveMergedOptions(instance2);
  const publicThis = instance2.proxy;
  const ctx = instance2.ctx;
  shouldCacheAccess = false;
  if (options.beforeCreate) {
    callHook$1(options.beforeCreate, instance2, "bc");
  }
  const {
    // state
    data: dataOptions,
    computed: computedOptions,
    methods,
    watch: watchOptions,
    provide: provideOptions,
    inject: injectOptions,
    // lifecycle
    created,
    beforeMount,
    mounted,
    beforeUpdate,
    updated,
    activated,
    deactivated,
    beforeDestroy,
    beforeUnmount,
    destroyed,
    unmounted,
    render,
    renderTracked,
    renderTriggered,
    errorCaptured,
    serverPrefetch,
    // public API
    expose,
    inheritAttrs,
    // assets
    components,
    directives,
    filters
  } = options;
  const checkDuplicateProperties = createDuplicateChecker();
  {
    const [propsOptions] = instance2.propsOptions;
    if (propsOptions) {
      for (const key in propsOptions) {
        checkDuplicateProperties("Props", key);
      }
    }
  }
  function initInjections() {
    if (injectOptions) {
      resolveInjections(injectOptions, ctx, checkDuplicateProperties);
    }
  }
  {
    initInjections();
  }
  if (methods) {
    for (const key in methods) {
      const methodHandler = methods[key];
      if (isFunction(methodHandler)) {
        {
          Object.defineProperty(ctx, key, {
            value: methodHandler.bind(publicThis),
            configurable: true,
            enumerable: true,
            writable: true
          });
        }
        {
          checkDuplicateProperties("Methods", key);
        }
      } else {
        warn$1(
          `Method "${key}" has type "${typeof methodHandler}" in the component definition. Did you reference the function correctly?`
        );
      }
    }
  }
  if (dataOptions) {
    if (!isFunction(dataOptions)) {
      warn$1(
        `The data option must be a function. Plain object usage is no longer supported.`
      );
    }
    const data = dataOptions.call(publicThis, publicThis);
    if (isPromise(data)) {
      warn$1(
        `data() returned a Promise - note data() cannot be async; If you intend to perform data fetching before component renders, use async setup() + <Suspense>.`
      );
    }
    if (!isObject(data)) {
      warn$1(`data() should return an object.`);
    } else {
      instance2.data = reactive(data);
      {
        for (const key in data) {
          checkDuplicateProperties("Data", key);
          if (!isReservedPrefix(key[0])) {
            Object.defineProperty(ctx, key, {
              configurable: true,
              enumerable: true,
              get: () => data[key],
              set: NOOP
            });
          }
        }
      }
    }
  }
  shouldCacheAccess = true;
  if (computedOptions) {
    for (const key in computedOptions) {
      const opt = computedOptions[key];
      const get2 = isFunction(opt) ? opt.bind(publicThis, publicThis) : isFunction(opt.get) ? opt.get.bind(publicThis, publicThis) : NOOP;
      if (get2 === NOOP) {
        warn$1(`Computed property "${key}" has no getter.`);
      }
      const set2 = !isFunction(opt) && isFunction(opt.set) ? opt.set.bind(publicThis) : () => {
        warn$1(
          `Write operation failed: computed property "${key}" is readonly.`
        );
      };
      const c2 = computed({
        get: get2,
        set: set2
      });
      Object.defineProperty(ctx, key, {
        enumerable: true,
        configurable: true,
        get: () => c2.value,
        set: (v) => c2.value = v
      });
      {
        checkDuplicateProperties("Computed", key);
      }
    }
  }
  if (watchOptions) {
    for (const key in watchOptions) {
      createWatcher(watchOptions[key], ctx, publicThis, key);
    }
  }
  function initProvides() {
    if (provideOptions) {
      const provides = isFunction(provideOptions) ? provideOptions.call(publicThis) : provideOptions;
      Reflect.ownKeys(provides).forEach((key) => {
        provide(key, provides[key]);
      });
    }
  }
  {
    initProvides();
  }
  {
    if (created) {
      callHook$1(created, instance2, "c");
    }
  }
  function registerLifecycleHook(register, hook) {
    if (isArray(hook)) {
      hook.forEach((_hook) => register(_hook.bind(publicThis)));
    } else if (hook) {
      register(hook.bind(publicThis));
    }
  }
  registerLifecycleHook(onBeforeMount, beforeMount);
  registerLifecycleHook(onMounted, mounted);
  registerLifecycleHook(onBeforeUpdate, beforeUpdate);
  registerLifecycleHook(onUpdated, updated);
  registerLifecycleHook(onActivated, activated);
  registerLifecycleHook(onDeactivated, deactivated);
  registerLifecycleHook(onErrorCaptured, errorCaptured);
  registerLifecycleHook(onRenderTracked, renderTracked);
  registerLifecycleHook(onRenderTriggered, renderTriggered);
  registerLifecycleHook(onBeforeUnmount, beforeUnmount);
  registerLifecycleHook(onUnmounted, unmounted);
  registerLifecycleHook(onServerPrefetch, serverPrefetch);
  if (isArray(expose)) {
    if (expose.length) {
      const exposed = instance2.exposed || (instance2.exposed = {});
      expose.forEach((key) => {
        Object.defineProperty(exposed, key, {
          get: () => publicThis[key],
          set: (val) => publicThis[key] = val
        });
      });
    } else if (!instance2.exposed) {
      instance2.exposed = {};
    }
  }
  if (render && instance2.render === NOOP) {
    instance2.render = render;
  }
  if (inheritAttrs != null) {
    instance2.inheritAttrs = inheritAttrs;
  }
  if (components)
    instance2.components = components;
  if (directives)
    instance2.directives = directives;
  if (instance2.ctx.$onApplyOptions) {
    instance2.ctx.$onApplyOptions(options, instance2, publicThis);
  }
}
function resolveInjections(injectOptions, ctx, checkDuplicateProperties = NOOP) {
  if (isArray(injectOptions)) {
    injectOptions = normalizeInject(injectOptions);
  }
  for (const key in injectOptions) {
    const opt = injectOptions[key];
    let injected;
    if (isObject(opt)) {
      if ("default" in opt) {
        injected = inject(
          opt.from || key,
          opt.default,
          true
        );
      } else {
        injected = inject(opt.from || key);
      }
    } else {
      injected = inject(opt);
    }
    if (isRef(injected)) {
      Object.defineProperty(ctx, key, {
        enumerable: true,
        configurable: true,
        get: () => injected.value,
        set: (v) => injected.value = v
      });
    } else {
      ctx[key] = injected;
    }
    {
      checkDuplicateProperties("Inject", key);
    }
  }
}
function callHook$1(hook, instance2, type) {
  callWithAsyncErrorHandling(
    isArray(hook) ? hook.map((h2) => h2.bind(instance2.proxy)) : hook.bind(instance2.proxy),
    instance2,
    type
  );
}
function createWatcher(raw, ctx, publicThis, key) {
  const getter = key.includes(".") ? createPathGetter(publicThis, key) : () => publicThis[key];
  if (isString(raw)) {
    const handler = ctx[raw];
    if (isFunction(handler)) {
      watch(getter, handler);
    } else {
      warn$1(`Invalid watch handler specified by key "${raw}"`, handler);
    }
  } else if (isFunction(raw)) {
    watch(getter, raw.bind(publicThis));
  } else if (isObject(raw)) {
    if (isArray(raw)) {
      raw.forEach((r2) => createWatcher(r2, ctx, publicThis, key));
    } else {
      const handler = isFunction(raw.handler) ? raw.handler.bind(publicThis) : ctx[raw.handler];
      if (isFunction(handler)) {
        watch(getter, handler, raw);
      } else {
        warn$1(`Invalid watch handler specified by key "${raw.handler}"`, handler);
      }
    }
  } else {
    warn$1(`Invalid watch option: "${key}"`, raw);
  }
}
function resolveMergedOptions(instance2) {
  const base = instance2.type;
  const { mixins, extends: extendsOptions } = base;
  const {
    mixins: globalMixins,
    optionsCache: cache2,
    config: { optionMergeStrategies }
  } = instance2.appContext;
  const cached2 = cache2.get(base);
  let resolved;
  if (cached2) {
    resolved = cached2;
  } else if (!globalMixins.length && !mixins && !extendsOptions) {
    {
      resolved = base;
    }
  } else {
    resolved = {};
    if (globalMixins.length) {
      globalMixins.forEach(
        (m2) => mergeOptions(resolved, m2, optionMergeStrategies, true)
      );
    }
    mergeOptions(resolved, base, optionMergeStrategies);
  }
  if (isObject(base)) {
    cache2.set(base, resolved);
  }
  return resolved;
}
function mergeOptions(to, from, strats, asMixin = false) {
  const { mixins, extends: extendsOptions } = from;
  if (extendsOptions) {
    mergeOptions(to, extendsOptions, strats, true);
  }
  if (mixins) {
    mixins.forEach(
      (m2) => mergeOptions(to, m2, strats, true)
    );
  }
  for (const key in from) {
    if (asMixin && key === "expose") {
      warn$1(
        `"expose" option is ignored when declared in mixins or extends. It should only be declared in the base component itself.`
      );
    } else {
      const strat = internalOptionMergeStrats[key] || strats && strats[key];
      to[key] = strat ? strat(to[key], from[key]) : from[key];
    }
  }
  return to;
}
const internalOptionMergeStrats = {
  data: mergeDataFn,
  props: mergeEmitsOrPropsOptions,
  emits: mergeEmitsOrPropsOptions,
  // objects
  methods: mergeObjectOptions,
  computed: mergeObjectOptions,
  // lifecycle
  beforeCreate: mergeAsArray$1,
  created: mergeAsArray$1,
  beforeMount: mergeAsArray$1,
  mounted: mergeAsArray$1,
  beforeUpdate: mergeAsArray$1,
  updated: mergeAsArray$1,
  beforeDestroy: mergeAsArray$1,
  beforeUnmount: mergeAsArray$1,
  destroyed: mergeAsArray$1,
  unmounted: mergeAsArray$1,
  activated: mergeAsArray$1,
  deactivated: mergeAsArray$1,
  errorCaptured: mergeAsArray$1,
  serverPrefetch: mergeAsArray$1,
  // assets
  components: mergeObjectOptions,
  directives: mergeObjectOptions,
  // watch
  watch: mergeWatchOptions,
  // provide / inject
  provide: mergeDataFn,
  inject: mergeInject
};
function mergeDataFn(to, from) {
  if (!from) {
    return to;
  }
  if (!to) {
    return from;
  }
  return function mergedDataFn() {
    return extend(
      isFunction(to) ? to.call(this, this) : to,
      isFunction(from) ? from.call(this, this) : from
    );
  };
}
function mergeInject(to, from) {
  return mergeObjectOptions(normalizeInject(to), normalizeInject(from));
}
function normalizeInject(raw) {
  if (isArray(raw)) {
    const res = {};
    for (let i = 0; i < raw.length; i++) {
      res[raw[i]] = raw[i];
    }
    return res;
  }
  return raw;
}
function mergeAsArray$1(to, from) {
  return to ? [...new Set([].concat(to, from))] : from;
}
function mergeObjectOptions(to, from) {
  return to ? extend(/* @__PURE__ */ Object.create(null), to, from) : from;
}
function mergeEmitsOrPropsOptions(to, from) {
  if (to) {
    if (isArray(to) && isArray(from)) {
      return [.../* @__PURE__ */ new Set([...to, ...from])];
    }
    return extend(
      /* @__PURE__ */ Object.create(null),
      normalizePropsOrEmits(to),
      normalizePropsOrEmits(from != null ? from : {})
    );
  } else {
    return from;
  }
}
function mergeWatchOptions(to, from) {
  if (!to)
    return from;
  if (!from)
    return to;
  const merged = extend(/* @__PURE__ */ Object.create(null), to);
  for (const key in from) {
    merged[key] = mergeAsArray$1(to[key], from[key]);
  }
  return merged;
}
function initProps$1(instance2, rawProps, isStateful, isSSR = false) {
  const props = {};
  const attrs = {};
  instance2.propsDefaults = /* @__PURE__ */ Object.create(null);
  setFullProps(instance2, rawProps, props, attrs);
  for (const key in instance2.propsOptions[0]) {
    if (!(key in props)) {
      props[key] = void 0;
    }
  }
  {
    validateProps(rawProps || {}, props, instance2);
  }
  if (isStateful) {
    instance2.props = isSSR ? props : shallowReactive(props);
  } else {
    if (!instance2.type.props) {
      instance2.props = attrs;
    } else {
      instance2.props = props;
    }
  }
  instance2.attrs = attrs;
}
function isInHmrContext(instance2) {
}
function updateProps(instance2, rawProps, rawPrevProps, optimized) {
  const {
    props,
    attrs,
    vnode: { patchFlag }
  } = instance2;
  const rawCurrentProps = toRaw(props);
  const [options] = instance2.propsOptions;
  let hasAttrsChanged = false;
  if (
    // always force full diff in dev
    // - #1942 if hmr is enabled with sfc component
    // - vite#872 non-sfc component used by sfc component
    !isInHmrContext() && (optimized || patchFlag > 0) && !(patchFlag & 16)
  ) {
    if (patchFlag & 8) {
      const propsToUpdate = instance2.vnode.dynamicProps;
      for (let i = 0; i < propsToUpdate.length; i++) {
        let key = propsToUpdate[i];
        if (isEmitListener(instance2.emitsOptions, key)) {
          continue;
        }
        const value = rawProps[key];
        if (options) {
          if (hasOwn(attrs, key)) {
            if (value !== attrs[key]) {
              attrs[key] = normalizeInheritAttrsValue(instance2, key, value);
              hasAttrsChanged = true;
            }
          } else {
            const camelizedKey = camelize(key);
            props[camelizedKey] = resolvePropValue$1(
              options,
              rawCurrentProps,
              camelizedKey,
              value,
              instance2,
              false
            );
          }
        } else {
          if (value !== attrs[key]) {
            attrs[key] = normalizeInheritAttrsValue(instance2, key, value);
            hasAttrsChanged = true;
          }
        }
      }
    }
  } else {
    if (setFullProps(instance2, rawProps, props, attrs)) {
      hasAttrsChanged = true;
    }
    let kebabKey;
    for (const key in rawCurrentProps) {
      if (!rawProps || // for camelCase
      !hasOwn(rawProps, key) && // it's possible the original props was passed in as kebab-case
      // and converted to camelCase (#955)
      ((kebabKey = hyphenate(key)) === key || !hasOwn(rawProps, kebabKey))) {
        if (options) {
          if (rawPrevProps && // for camelCase
          (rawPrevProps[key] !== void 0 || // for kebab-case
          rawPrevProps[kebabKey] !== void 0)) {
            props[key] = resolvePropValue$1(
              options,
              rawCurrentProps,
              key,
              void 0,
              instance2,
              true
            );
          }
        } else {
          delete props[key];
        }
      }
    }
    if (attrs !== rawCurrentProps) {
      for (const key in attrs) {
        if (!rawProps || !hasOwn(rawProps, key) && true) {
          delete attrs[key];
          hasAttrsChanged = true;
        }
      }
    }
  }
  if (hasAttrsChanged) {
    trigger(instance2, "set", "$attrs");
  }
  {
    validateProps(rawProps || {}, props, instance2);
  }
}
function setFullProps(instance2, rawProps, props, attrs) {
  const [options, needCastKeys] = instance2.propsOptions;
  let hasAttrsChanged = false;
  let rawCastValues;
  if (rawProps) {
    for (let key in rawProps) {
      if (isReservedProp(key)) {
        continue;
      }
      const value = rawProps[key];
      let camelKey;
      if (options && hasOwn(options, camelKey = camelize(key))) {
        if (!needCastKeys || !needCastKeys.includes(camelKey)) {
          {
            props[camelKey] = value;
          }
        } else {
          (rawCastValues || (rawCastValues = {}))[camelKey] = value;
        }
      } else if (!isEmitListener(instance2.emitsOptions, key)) {
        if (!(key in attrs) || value !== attrs[key]) {
          attrs[key] = normalizeInheritAttrsValue(instance2, key, value);
          hasAttrsChanged = true;
        }
      }
    }
  }
  if (needCastKeys) {
    const rawCurrentProps = toRaw(props);
    const castValues = rawCastValues || EMPTY_OBJ;
    for (let i = 0; i < needCastKeys.length; i++) {
      const key = needCastKeys[i];
      props[key] = resolvePropValue$1(
        options,
        rawCurrentProps,
        key,
        castValues[key],
        instance2,
        !hasOwn(castValues, key)
      );
    }
  }
  return hasAttrsChanged;
}
function normalizeInheritAttrsValue(instance2, key, value) {
  return value;
}
function resolvePropValue$1(options, props, key, value, instance2, isAbsent) {
  const result = _resolvePropValue(
    options,
    props,
    key,
    value,
    instance2,
    isAbsent
  );
  return result;
}
function _resolvePropValue(options, props, key, value, instance2, isAbsent) {
  const opt = options[key];
  if (opt != null) {
    const hasDefault = hasOwn(opt, "default");
    if (hasDefault && value === void 0) {
      const defaultValue = opt.default;
      if (opt.type !== Function && !opt.skipFactory && isFunction(defaultValue)) {
        const { propsDefaults } = instance2;
        if (key in propsDefaults) {
          value = propsDefaults[key];
        } else {
          const reset = setCurrentInstance(instance2);
          value = propsDefaults[key] = defaultValue.call(
            null,
            props
          );
          reset();
        }
      } else {
        value = defaultValue;
      }
    }
    if (opt[
      0
      /* shouldCast */
    ]) {
      if (isAbsent && !hasDefault) {
        value = false;
      } else if (opt[
        1
        /* shouldCastTrue */
      ] && (value === "" || value === hyphenate(key))) {
        value = true;
      }
    }
  }
  return value;
}
function normalizePropsOptions(comp, appContext, asMixin = false) {
  const cache2 = appContext.propsCache;
  const cached2 = cache2.get(comp);
  if (cached2) {
    return cached2;
  }
  const raw = comp.props;
  const normalized = {};
  const needCastKeys = [];
  let hasExtends = false;
  if (!isFunction(comp)) {
    const extendProps = (raw2) => {
      hasExtends = true;
      const [props, keys] = normalizePropsOptions(raw2, appContext, true);
      extend(normalized, props);
      if (keys)
        needCastKeys.push(...keys);
    };
    if (!asMixin && appContext.mixins.length) {
      appContext.mixins.forEach(extendProps);
    }
    if (comp.extends) {
      extendProps(comp.extends);
    }
    if (comp.mixins) {
      comp.mixins.forEach(extendProps);
    }
  }
  if (!raw && !hasExtends) {
    if (isObject(comp)) {
      cache2.set(comp, EMPTY_ARR);
    }
    return EMPTY_ARR;
  }
  if (isArray(raw)) {
    for (let i = 0; i < raw.length; i++) {
      if (!isString(raw[i])) {
        warn$1(`props must be strings when using array syntax.`, raw[i]);
      }
      const normalizedKey = camelize(raw[i]);
      if (validatePropName(normalizedKey)) {
        normalized[normalizedKey] = EMPTY_OBJ;
      }
    }
  } else if (raw) {
    if (!isObject(raw)) {
      warn$1(`invalid props options`, raw);
    }
    for (const key in raw) {
      const normalizedKey = camelize(key);
      if (validatePropName(normalizedKey)) {
        const opt = raw[key];
        const prop = normalized[normalizedKey] = isArray(opt) || isFunction(opt) ? { type: opt } : extend({}, opt);
        if (prop) {
          const booleanIndex = getTypeIndex(Boolean, prop.type);
          const stringIndex = getTypeIndex(String, prop.type);
          prop[
            0
            /* shouldCast */
          ] = booleanIndex > -1;
          prop[
            1
            /* shouldCastTrue */
          ] = stringIndex < 0 || booleanIndex < stringIndex;
          if (booleanIndex > -1 || hasOwn(prop, "default")) {
            needCastKeys.push(normalizedKey);
          }
        }
      }
    }
  }
  const res = [normalized, needCastKeys];
  if (isObject(comp)) {
    cache2.set(comp, res);
  }
  return res;
}
function validatePropName(key) {
  if (key[0] !== "$" && !isReservedProp(key)) {
    return true;
  } else {
    warn$1(`Invalid prop name: "${key}" is a reserved property.`);
  }
  return false;
}
function getType$1(ctor) {
  if (ctor === null) {
    return "null";
  }
  if (typeof ctor === "function") {
    return ctor.name || "";
  } else if (typeof ctor === "object") {
    const name = ctor.constructor && ctor.constructor.name;
    return name || "";
  }
  return "";
}
function isSameType(a, b) {
  return getType$1(a) === getType$1(b);
}
function getTypeIndex(type, expectedTypes) {
  if (isArray(expectedTypes)) {
    return expectedTypes.findIndex((t2) => isSameType(t2, type));
  } else if (isFunction(expectedTypes)) {
    return isSameType(expectedTypes, type) ? 0 : -1;
  }
  return -1;
}
function validateProps(rawProps, props, instance2) {
  const resolvedValues = toRaw(props);
  const options = instance2.propsOptions[0];
  for (const key in options) {
    let opt = options[key];
    if (opt == null)
      continue;
    validateProp$1(
      key,
      resolvedValues[key],
      opt,
      shallowReadonly(resolvedValues),
      !hasOwn(rawProps, key) && !hasOwn(rawProps, hyphenate(key))
    );
  }
}
function validateProp$1(name, value, prop, props, isAbsent) {
  const { type, required, validator, skipCheck } = prop;
  if (required && isAbsent) {
    warn$1('Missing required prop: "' + name + '"');
    return;
  }
  if (value == null && !required) {
    return;
  }
  if (type != null && type !== true && !skipCheck) {
    let isValid = false;
    const types = isArray(type) ? type : [type];
    const expectedTypes = [];
    for (let i = 0; i < types.length && !isValid; i++) {
      const { valid, expectedType } = assertType$1(value, types[i]);
      expectedTypes.push(expectedType || "");
      isValid = valid;
    }
    if (!isValid) {
      warn$1(getInvalidTypeMessage$1(name, value, expectedTypes));
      return;
    }
  }
  if (validator && !validator(value, props)) {
    warn$1('Invalid prop: custom validator check failed for prop "' + name + '".');
  }
}
const isSimpleType$1 = /* @__PURE__ */ makeMap(
  "String,Number,Boolean,Function,Symbol,BigInt"
);
function assertType$1(value, type) {
  let valid;
  const expectedType = getType$1(type);
  if (isSimpleType$1(expectedType)) {
    const t2 = typeof value;
    valid = t2 === expectedType.toLowerCase();
    if (!valid && t2 === "object") {
      valid = value instanceof type;
    }
  } else if (expectedType === "Object") {
    valid = isObject(value);
  } else if (expectedType === "Array") {
    valid = isArray(value);
  } else if (expectedType === "null") {
    valid = value === null;
  } else {
    valid = value instanceof type;
  }
  return {
    valid,
    expectedType
  };
}
function getInvalidTypeMessage$1(name, value, expectedTypes) {
  if (expectedTypes.length === 0) {
    return `Prop type [] for prop "${name}" won't match anything. Did you mean to use type Array instead?`;
  }
  let message = `Invalid prop: type check failed for prop "${name}". Expected ${expectedTypes.map(capitalize).join(" | ")}`;
  const expectedType = expectedTypes[0];
  const receivedType = toRawType(value);
  const expectedValue = styleValue$1(value, expectedType);
  const receivedValue = styleValue$1(value, receivedType);
  if (expectedTypes.length === 1 && isExplicable$1(expectedType) && !isBoolean$1(expectedType, receivedType)) {
    message += ` with value ${expectedValue}`;
  }
  message += `, got ${receivedType} `;
  if (isExplicable$1(receivedType)) {
    message += `with value ${receivedValue}.`;
  }
  return message;
}
function styleValue$1(value, type) {
  if (type === "String") {
    return `"${value}"`;
  } else if (type === "Number") {
    return `${Number(value)}`;
  } else {
    return `${value}`;
  }
}
function isExplicable$1(type) {
  const explicitTypes = ["string", "number", "boolean"];
  return explicitTypes.some((elem) => type.toLowerCase() === elem);
}
function isBoolean$1(...args) {
  return args.some((elem) => elem.toLowerCase() === "boolean");
}
let supported;
let perf;
function startMeasure(instance2, type) {
  if (instance2.appContext.config.performance && isSupported()) {
    perf.mark(`vue-${type}-${instance2.uid}`);
  }
  {
    devtoolsPerfStart(instance2, type, isSupported() ? perf.now() : Date.now());
  }
}
function endMeasure(instance2, type) {
  if (instance2.appContext.config.performance && isSupported()) {
    const startTag = `vue-${type}-${instance2.uid}`;
    const endTag = startTag + `:end`;
    perf.mark(endTag);
    perf.measure(
      `<${formatComponentName(instance2, instance2.type)}> ${type}`,
      startTag,
      endTag
    );
    perf.clearMarks(startTag);
    perf.clearMarks(endTag);
  }
  {
    devtoolsPerfEnd(instance2, type, isSupported() ? perf.now() : Date.now());
  }
}
function isSupported() {
  if (supported !== void 0) {
    return supported;
  }
  if (typeof window !== "undefined" && window.performance) {
    supported = true;
    perf = window.performance;
  } else {
    supported = false;
  }
  return supported;
}
const queuePostRenderEffect$1 = queuePostFlushCb;
const Fragment = Symbol.for("v-fgt");
const Text = Symbol.for("v-txt");
const Comment = Symbol.for("v-cmt");
const Static = Symbol.for("v-stc");
function isVNode(value) {
  return value ? value.__v_isVNode === true : false;
}
const InternalObjectKey = `__vInternal`;
function guardReactiveProps(props) {
  if (!props)
    return null;
  return isProxy(props) || InternalObjectKey in props ? extend({}, props) : props;
}
const emptyAppContext = createAppContext();
let uid = 0;
function createComponentInstance(vnode, parent, suspense) {
  const type = vnode.type;
  const appContext = (parent ? parent.appContext : vnode.appContext) || emptyAppContext;
  const instance2 = {
    uid: uid++,
    vnode,
    type,
    parent,
    appContext,
    root: null,
    // to be immediately set
    next: null,
    subTree: null,
    // will be set synchronously right after creation
    effect: null,
    update: null,
    // will be set synchronously right after creation
    scope: new EffectScope(
      true
      /* detached */
    ),
    render: null,
    proxy: null,
    exposed: null,
    exposeProxy: null,
    withProxy: null,
    provides: parent ? parent.provides : Object.create(appContext.provides),
    accessCache: null,
    renderCache: [],
    // local resolved assets
    components: null,
    directives: null,
    // resolved props and emits options
    propsOptions: normalizePropsOptions(type, appContext),
    emitsOptions: normalizeEmitsOptions(type, appContext),
    // emit
    emit: null,
    // to be set immediately
    emitted: null,
    // props default value
    propsDefaults: EMPTY_OBJ,
    // inheritAttrs
    inheritAttrs: type.inheritAttrs,
    // state
    ctx: EMPTY_OBJ,
    data: EMPTY_OBJ,
    props: EMPTY_OBJ,
    attrs: EMPTY_OBJ,
    slots: EMPTY_OBJ,
    refs: EMPTY_OBJ,
    setupState: EMPTY_OBJ,
    setupContext: null,
    attrsProxy: null,
    slotsProxy: null,
    // suspense related
    suspense,
    suspenseId: suspense ? suspense.pendingId : 0,
    asyncDep: null,
    asyncResolved: false,
    // lifecycle hooks
    // not using enums here because it results in computed properties
    isMounted: false,
    isUnmounted: false,
    isDeactivated: false,
    bc: null,
    c: null,
    bm: null,
    m: null,
    bu: null,
    u: null,
    um: null,
    bum: null,
    da: null,
    a: null,
    rtg: null,
    rtc: null,
    ec: null,
    sp: null,
    // fixed by xxxxxx 用于存储uni-app的元素缓存
    $uniElements: /* @__PURE__ */ new Map(),
    $templateUniElementRefs: [],
    $templateUniElementStyles: {},
    $eS: {},
    $eA: {}
  };
  {
    instance2.ctx = createDevRenderContext(instance2);
  }
  instance2.root = parent ? parent.root : instance2;
  instance2.emit = emit.bind(null, instance2);
  if (vnode.ce) {
    vnode.ce(instance2);
  }
  return instance2;
}
let currentInstance = null;
const getCurrentInstance = () => currentInstance || currentRenderingInstance;
let internalSetCurrentInstance;
let setInSSRSetupState;
{
  internalSetCurrentInstance = (i) => {
    currentInstance = i;
  };
  setInSSRSetupState = (v) => {
    isInSSRComponentSetup = v;
  };
}
const setCurrentInstance = (instance2) => {
  const prev = currentInstance;
  internalSetCurrentInstance(instance2);
  instance2.scope.on();
  return () => {
    instance2.scope.off();
    internalSetCurrentInstance(prev);
  };
};
const unsetCurrentInstance = () => {
  currentInstance && currentInstance.scope.off();
  internalSetCurrentInstance(null);
};
const isBuiltInTag = /* @__PURE__ */ makeMap("slot,component");
function validateComponentName(name, { isNativeTag }) {
  if (isBuiltInTag(name) || isNativeTag(name)) {
    warn$1(
      "Do not use built-in or reserved HTML elements as component id: " + name
    );
  }
}
function isStatefulComponent(instance2) {
  return instance2.vnode.shapeFlag & 4;
}
let isInSSRComponentSetup = false;
function setupComponent(instance2, isSSR = false) {
  isSSR && setInSSRSetupState(isSSR);
  const {
    props
    /*, children*/
  } = instance2.vnode;
  const isStateful = isStatefulComponent(instance2);
  initProps$1(instance2, props, isStateful, isSSR);
  const setupResult = isStateful ? setupStatefulComponent(instance2, isSSR) : void 0;
  isSSR && setInSSRSetupState(false);
  return setupResult;
}
function setupStatefulComponent(instance2, isSSR) {
  const Component2 = instance2.type;
  {
    if (Component2.name) {
      validateComponentName(Component2.name, instance2.appContext.config);
    }
    if (Component2.components) {
      const names = Object.keys(Component2.components);
      for (let i = 0; i < names.length; i++) {
        validateComponentName(names[i], instance2.appContext.config);
      }
    }
    if (Component2.directives) {
      const names = Object.keys(Component2.directives);
      for (let i = 0; i < names.length; i++) {
        validateDirectiveName(names[i]);
      }
    }
    if (Component2.compilerOptions && isRuntimeOnly()) {
      warn$1(
        `"compilerOptions" is only supported when using a build of Vue that includes the runtime compiler. Since you are using a runtime-only build, the options should be passed via your build tool config instead.`
      );
    }
  }
  instance2.accessCache = /* @__PURE__ */ Object.create(null);
  instance2.proxy = markRaw(new Proxy(instance2.ctx, PublicInstanceProxyHandlers));
  {
    exposePropsOnRenderContext(instance2);
  }
  const { setup } = Component2;
  if (setup) {
    const setupContext = instance2.setupContext = setup.length > 1 ? createSetupContext(instance2) : null;
    const reset = setCurrentInstance(instance2);
    pauseTracking();
    const setupResult = callWithErrorHandling(
      setup,
      instance2,
      0,
      [
        shallowReadonly(instance2.props),
        setupContext
      ]
    );
    resetTracking();
    reset();
    if (isPromise(setupResult)) {
      setupResult.then(unsetCurrentInstance, unsetCurrentInstance);
      {
        warn$1(
          `setup() returned a Promise, but the version of Vue you are using does not support it yet.`
        );
      }
    } else {
      handleSetupResult(instance2, setupResult, isSSR);
    }
  } else {
    finishComponentSetup(instance2, isSSR);
  }
}
function handleSetupResult(instance2, setupResult, isSSR) {
  if (isFunction(setupResult)) {
    {
      instance2.render = setupResult;
    }
  } else if (isObject(setupResult)) {
    if (isVNode(setupResult)) {
      warn$1(
        `setup() should not return VNodes directly - return a render function instead.`
      );
    }
    {
      instance2.devtoolsRawSetupState = setupResult;
    }
    instance2.setupState = proxyRefs(setupResult);
    {
      exposeSetupStateOnRenderContext(instance2);
    }
  } else if (setupResult !== void 0) {
    warn$1(
      `setup() should return an object. Received: ${setupResult === null ? "null" : typeof setupResult}`
    );
  }
  finishComponentSetup(instance2, isSSR);
}
let compile;
const isRuntimeOnly = () => !compile;
function finishComponentSetup(instance2, isSSR, skipOptions) {
  const Component2 = instance2.type;
  if (!instance2.render) {
    instance2.render = Component2.render || NOOP;
  }
  {
    const reset = setCurrentInstance(instance2);
    pauseTracking();
    try {
      applyOptions$1(instance2);
    } finally {
      resetTracking();
      reset();
    }
  }
  if (!Component2.render && instance2.render === NOOP && !isSSR) {
    if (Component2.template) {
      warn$1(
        `Component provided template option but runtime compilation is not supported in this build of Vue. Configure your bundler to alias "vue" to "vue/dist/vue.esm-bundler.js".`
      );
    } else {
      warn$1(`Component is missing template or render function.`);
    }
  }
}
function getAttrsProxy(instance2) {
  return instance2.attrsProxy || (instance2.attrsProxy = new Proxy(
    instance2.attrs,
    {
      get(target, key) {
        track(instance2, "get", "$attrs");
        return target[key];
      },
      set() {
        warn$1(`setupContext.attrs is readonly.`);
        return false;
      },
      deleteProperty() {
        warn$1(`setupContext.attrs is readonly.`);
        return false;
      }
    }
  ));
}
function getSlotsProxy(instance2) {
  return instance2.slotsProxy || (instance2.slotsProxy = new Proxy(instance2.slots, {
    get(target, key) {
      track(instance2, "get", "$slots");
      return target[key];
    }
  }));
}
function createSetupContext(instance2) {
  const expose = (exposed) => {
    {
      if (instance2.exposed) {
        warn$1(`expose() should be called only once per setup().`);
      }
      if (exposed != null) {
        let exposedType = typeof exposed;
        if (exposedType === "object") {
          if (isArray(exposed)) {
            exposedType = "array";
          } else if (isRef(exposed)) {
            exposedType = "ref";
          }
        }
        if (exposedType !== "object") {
          warn$1(
            `expose() should be passed a plain object, received ${exposedType}.`
          );
        }
      }
    }
    instance2.exposed = exposed || {};
  };
  {
    return Object.freeze({
      get attrs() {
        return getAttrsProxy(instance2);
      },
      get slots() {
        return getSlotsProxy(instance2);
      },
      get emit() {
        return (event, ...args) => instance2.emit(event, ...args);
      },
      expose
    });
  }
}
function getExposeProxy(instance2) {
  if (instance2.exposed) {
    return instance2.exposeProxy || (instance2.exposeProxy = new Proxy(proxyRefs(markRaw(instance2.exposed)), {
      get(target, key) {
        if (key in target) {
          return target[key];
        }
        return instance2.proxy[key];
      },
      has(target, key) {
        return key in target || key in publicPropertiesMap;
      }
    }));
  }
}
const classifyRE = /(?:^|[-_])(\w)/g;
const classify = (str) => str.replace(classifyRE, (c2) => c2.toUpperCase()).replace(/[-_]/g, "");
function getComponentName(Component2, includeInferred = true) {
  return isFunction(Component2) ? Component2.displayName || Component2.name : Component2.name || includeInferred && Component2.__name;
}
function formatComponentName(instance2, Component2, isRoot = false) {
  let name = getComponentName(Component2);
  if (!name && Component2.__file) {
    const match = Component2.__file.match(/([^/\\]+)\.\w+$/);
    if (match) {
      name = match[1];
    }
  }
  if (!name && instance2 && instance2.parent) {
    const inferFromRegistry = (registry2) => {
      for (const key in registry2) {
        if (registry2[key] === Component2) {
          return key;
        }
      }
    };
    name = inferFromRegistry(
      instance2.components || instance2.parent.type.components
    ) || inferFromRegistry(instance2.appContext.components);
  }
  return name ? classify(name) : isRoot ? `App` : `Anonymous`;
}
const computed = (getterOrOptions, debugOptions) => {
  const c2 = computed$1(getterOrOptions, debugOptions, isInSSRComponentSetup);
  {
    const i = getCurrentInstance();
    if (i && i.appContext.config.warnRecursiveComputed) {
      c2._warnRecursive = true;
    }
  }
  return c2;
};
const version = "3.4.21";
const warn = warn$1;
function unwrapper(target) {
  return unref(target);
}
const ARRAYTYPE = "[object Array]";
const OBJECTTYPE = "[object Object]";
function diff(current, pre) {
  const result = {};
  syncKeys(current, pre);
  _diff(current, pre, "", result);
  return result;
}
function syncKeys(current, pre) {
  current = unwrapper(current);
  if (current === pre)
    return;
  const rootCurrentType = toTypeString(current);
  const rootPreType = toTypeString(pre);
  if (rootCurrentType == OBJECTTYPE && rootPreType == OBJECTTYPE) {
    for (let key in pre) {
      const currentValue = current[key];
      if (currentValue === void 0) {
        current[key] = null;
      } else {
        syncKeys(currentValue, pre[key]);
      }
    }
  } else if (rootCurrentType == ARRAYTYPE && rootPreType == ARRAYTYPE) {
    if (current.length >= pre.length) {
      pre.forEach((item, index2) => {
        syncKeys(current[index2], item);
      });
    }
  }
}
function _diff(current, pre, path, result) {
  current = unwrapper(current);
  if (current === pre)
    return;
  const rootCurrentType = toTypeString(current);
  const rootPreType = toTypeString(pre);
  if (rootCurrentType == OBJECTTYPE) {
    if (rootPreType != OBJECTTYPE || Object.keys(current).length < Object.keys(pre).length) {
      setResult(result, path, current);
    } else {
      for (let key in current) {
        const currentValue = unwrapper(current[key]);
        const preValue = pre[key];
        const currentType = toTypeString(currentValue);
        const preType = toTypeString(preValue);
        if (currentType != ARRAYTYPE && currentType != OBJECTTYPE) {
          if (currentValue != preValue) {
            setResult(
              result,
              (path == "" ? "" : path + ".") + key,
              currentValue
            );
          }
        } else if (currentType == ARRAYTYPE) {
          if (preType != ARRAYTYPE) {
            setResult(
              result,
              (path == "" ? "" : path + ".") + key,
              currentValue
            );
          } else {
            if (currentValue.length < preValue.length) {
              setResult(
                result,
                (path == "" ? "" : path + ".") + key,
                currentValue
              );
            } else {
              currentValue.forEach((item, index2) => {
                _diff(
                  item,
                  preValue[index2],
                  (path == "" ? "" : path + ".") + key + "[" + index2 + "]",
                  result
                );
              });
            }
          }
        } else if (currentType == OBJECTTYPE) {
          if (preType != OBJECTTYPE || Object.keys(currentValue).length < Object.keys(preValue).length) {
            setResult(
              result,
              (path == "" ? "" : path + ".") + key,
              currentValue
            );
          } else {
            for (let subKey in currentValue) {
              _diff(
                currentValue[subKey],
                preValue[subKey],
                (path == "" ? "" : path + ".") + key + "." + subKey,
                result
              );
            }
          }
        }
      }
    }
  } else if (rootCurrentType == ARRAYTYPE) {
    if (rootPreType != ARRAYTYPE) {
      setResult(result, path, current);
    } else {
      if (current.length < pre.length) {
        setResult(result, path, current);
      } else {
        current.forEach((item, index2) => {
          _diff(item, pre[index2], path + "[" + index2 + "]", result);
        });
      }
    }
  } else {
    setResult(result, path, current);
  }
}
function setResult(result, k, v) {
  result[k] = v;
}
function hasComponentEffect(instance2) {
  return queue$1.includes(instance2.update);
}
function flushCallbacks(instance2) {
  const ctx = instance2.ctx;
  const callbacks = ctx.__next_tick_callbacks;
  if (callbacks && callbacks.length) {
    const copies = callbacks.slice(0);
    callbacks.length = 0;
    for (let i = 0; i < copies.length; i++) {
      copies[i]();
    }
  }
}
function nextTick(instance2, fn) {
  const ctx = instance2.ctx;
  if (!ctx.__next_tick_pending && !hasComponentEffect(instance2)) {
    return nextTick$1(fn && fn.bind(instance2.proxy));
  }
  let _resolve;
  if (!ctx.__next_tick_callbacks) {
    ctx.__next_tick_callbacks = [];
  }
  ctx.__next_tick_callbacks.push(() => {
    if (fn) {
      callWithErrorHandling(
        fn.bind(instance2.proxy),
        instance2,
        14
      );
    } else if (_resolve) {
      _resolve(instance2.proxy);
    }
  });
  return new Promise((resolve2) => {
    _resolve = resolve2;
  });
}
function clone(src, seen) {
  src = unwrapper(src);
  const type = typeof src;
  if (type === "object" && src !== null) {
    let copy = seen.get(src);
    if (typeof copy !== "undefined") {
      return copy;
    }
    if (isArray(src)) {
      const len = src.length;
      copy = new Array(len);
      seen.set(src, copy);
      for (let i = 0; i < len; i++) {
        copy[i] = clone(src[i], seen);
      }
    } else {
      copy = {};
      seen.set(src, copy);
      for (const name in src) {
        if (hasOwn(src, name)) {
          copy[name] = clone(src[name], seen);
        }
      }
    }
    return copy;
  }
  if (type !== "symbol") {
    return src;
  }
}
function deepCopy(src) {
  return clone(src, typeof WeakMap !== "undefined" ? /* @__PURE__ */ new WeakMap() : /* @__PURE__ */ new Map());
}
function getMPInstanceData(instance2, keys) {
  const data = instance2.data;
  const ret = /* @__PURE__ */ Object.create(null);
  keys.forEach((key) => {
    ret[key] = data[key];
  });
  return ret;
}
function patch(instance2, data, oldData) {
  if (!data) {
    return;
  }
  data = deepCopy(data);
  data.$eS = instance2.$eS || {};
  data.$eA = instance2.$eA || {};
  const ctx = instance2.ctx;
  const mpType = ctx.mpType;
  if (mpType === "page" || mpType === "component") {
    data.r0 = 1;
    const mpInstance = ctx.$scope;
    const keys = Object.keys(data);
    const diffData = diff(data, oldData || getMPInstanceData(mpInstance, keys));
    if (Object.keys(diffData).length) {
      ctx.__next_tick_pending = true;
      mpInstance.setData(diffData, () => {
        ctx.__next_tick_pending = false;
        flushCallbacks(instance2);
      });
      flushPreFlushCbs();
    } else {
      flushCallbacks(instance2);
    }
  }
}
function initAppConfig(appConfig) {
  appConfig.globalProperties.$nextTick = function $nextTick(fn) {
    return nextTick(this.$, fn);
  };
}
function onApplyOptions(options, instance2, publicThis) {
  instance2.appContext.config.globalProperties.$applyOptions(
    options,
    instance2,
    publicThis
  );
  const computedOptions = options.computed;
  if (computedOptions) {
    const keys = Object.keys(computedOptions);
    if (keys.length) {
      const ctx = instance2.ctx;
      if (!ctx.$computedKeys) {
        ctx.$computedKeys = [];
      }
      ctx.$computedKeys.push(...keys);
    }
  }
  delete instance2.ctx.$onApplyOptions;
}
function setRef$1(instance2, isUnmount = false) {
  const {
    setupState,
    $templateRefs,
    $templateUniElementRefs,
    ctx: { $scope, $mpPlatform }
  } = instance2;
  if (!$scope || !$templateRefs && !$templateUniElementRefs) {
    return;
  }
  if (isUnmount) {
    if ($mpPlatform !== "mp-alipay") {
      $templateRefs && $templateRefs.forEach(
        (templateRef) => setTemplateRef(templateRef, null, setupState)
      );
    }
    $templateUniElementRefs && $templateUniElementRefs.forEach(
      (templateRef) => setTemplateRef(templateRef, null, setupState)
    );
    return;
  }
  const check = $mpPlatform === "mp-baidu" || $mpPlatform === "mp-toutiao";
  const doSetByRefs = (refs) => {
    if (refs.length === 0) {
      return [];
    }
    const mpComponents = (
      // 字节小程序 selectAllComponents 可能返回 null
      // https://github.com/dcloudio/uni-app/issues/3954
      ($scope.selectAllComponents(".r") || []).concat(
        $scope.selectAllComponents(".r-i-f") || []
      )
    );
    return refs.filter((templateRef) => {
      const refValue = findComponentPublicInstance(mpComponents, templateRef.i);
      if (check && refValue === null) {
        return true;
      }
      setTemplateRef(templateRef, refValue, setupState);
      return false;
    });
  };
  const doSet = () => {
    if ($templateRefs) {
      const refs = doSetByRefs($templateRefs);
      if (refs.length && instance2.proxy && instance2.proxy.$scope) {
        instance2.proxy.$scope.setData({ r1: 1 }, () => {
          doSetByRefs(refs);
        });
      }
    }
  };
  if ($mpPlatform !== "mp-alipay") {
    if ($scope._$setRef) {
      $scope._$setRef(doSet);
    } else {
      nextTick(instance2, doSet);
    }
  }
  if ($templateUniElementRefs && $templateUniElementRefs.length) {
    nextTick(instance2, () => {
      $templateUniElementRefs.forEach((templateRef) => {
        if (isArray(templateRef.v)) {
          templateRef.v.forEach((v) => {
            setTemplateRef(templateRef, v, setupState);
          });
        } else {
          setTemplateRef(templateRef, templateRef.v, setupState);
        }
      });
    });
  }
}
function toSkip(value) {
  if (isObject(value)) {
    markRaw(value);
  }
  return value;
}
function findComponentPublicInstance(mpComponents, id) {
  const mpInstance = mpComponents.find(
    (com) => com && (com.properties || com.props).uI === id
  );
  if (mpInstance) {
    const vm = mpInstance.$vm;
    if (vm) {
      return getExposeProxy(vm.$) || vm;
    }
    return toSkip(mpInstance);
  }
  return null;
}
function setTemplateRef({ r: r2, f: f2 }, refValue, setupState) {
  if (isFunction(r2)) {
    r2(refValue, {});
  } else {
    const _isString = isString(r2);
    const _isRef = isRef(r2);
    if (_isString || _isRef) {
      if (f2) {
        if (!_isRef) {
          return;
        }
        if (!isArray(r2.value)) {
          r2.value = [];
        }
        const existing = r2.value;
        if (existing.indexOf(refValue) === -1) {
          existing.push(refValue);
          if (!refValue) {
            return;
          }
          if (refValue.$) {
            onBeforeUnmount(() => remove$1(existing, refValue), refValue.$);
          }
        }
      } else if (_isString) {
        if (hasOwn(setupState, r2)) {
          setupState[r2] = refValue;
        }
      } else if (isRef(r2)) {
        r2.value = refValue;
      } else {
        warnRef(r2);
      }
    } else {
      warnRef(r2);
    }
  }
}
function warnRef(ref2) {
  warn("Invalid template ref type:", ref2, `(${typeof ref2})`);
}
const queuePostRenderEffect = queuePostFlushCb;
function mountComponent(initialVNode, options) {
  const instance2 = initialVNode.component = createComponentInstance(initialVNode, options.parentComponent, null);
  instance2.renderer = options.mpType ? options.mpType : "component";
  {
    instance2.ctx.$onApplyOptions = onApplyOptions;
    instance2.ctx.$children = [];
  }
  if (options.mpType === "app") {
    instance2.render = NOOP;
  }
  if (options.onBeforeSetup) {
    options.onBeforeSetup(instance2, options);
  }
  {
    pushWarningContext(initialVNode);
    startMeasure(instance2, `mount`);
  }
  {
    startMeasure(instance2, `init`);
  }
  setupComponent(instance2);
  {
    endMeasure(instance2, `init`);
  }
  {
    if (options.parentComponent && instance2.proxy) {
      options.parentComponent.ctx.$children.push(getExposeProxy(instance2) || instance2.proxy);
    }
  }
  setupRenderEffect(instance2);
  {
    popWarningContext();
    endMeasure(instance2, `mount`);
  }
  return instance2.proxy;
}
const getFunctionalFallthrough = (attrs) => {
  let res;
  for (const key in attrs) {
    if (key === "class" || key === "style" || isOn(key)) {
      (res || (res = {}))[key] = attrs[key];
    }
  }
  return res;
};
function clearTemplateRefs(templateRefs) {
  if (!templateRefs) {
    return [];
  }
  return templateRefs.filter((templateRef) => {
    const v = templateRef.v;
    if (v && typeof v === "object" && ["UNI-LOADING-ELEMENT", "UNI-CLOUD-DB-ELEMENT"].includes(v.nodeName)) {
      return true;
    }
    return false;
  });
}
function renderComponentRoot(instance2) {
  const {
    type: Component2,
    vnode,
    proxy,
    withProxy,
    props,
    propsOptions: [propsOptions],
    slots,
    attrs,
    emit: emit2,
    render,
    renderCache,
    data,
    setupState,
    ctx,
    uid: uid2,
    appContext: {
      app: {
        config: {
          globalProperties: { pruneComponentPropsCache: pruneComponentPropsCache2 }
        }
      }
    },
    inheritAttrs
  } = instance2;
  instance2.$uniElementIds = /* @__PURE__ */ new Map();
  instance2.$templateRefs = clearTemplateRefs(
    instance2.$templateRefs || []
  );
  instance2.$templateUniElementRefs = clearTemplateRefs(
    instance2.$templateUniElementRefs || []
  );
  instance2.$templateUniElementStyles = {};
  instance2.$ei = 0;
  pruneComponentPropsCache2(uid2);
  instance2.__counter = instance2.__counter === 0 ? 1 : 0;
  let result;
  const prev = setCurrentRenderingInstance(instance2);
  try {
    if (vnode.shapeFlag & 4) {
      fallthroughAttrs(inheritAttrs, props, propsOptions, attrs);
      const proxyToUse = withProxy || proxy;
      result = render.call(
        proxyToUse,
        proxyToUse,
        renderCache,
        props,
        setupState,
        data,
        ctx
      );
    } else {
      fallthroughAttrs(
        inheritAttrs,
        props,
        propsOptions,
        Component2.props ? attrs : getFunctionalFallthrough(attrs)
      );
      const render2 = Component2;
      result = render2.length > 1 ? render2(props, { attrs, slots, emit: emit2 }) : render2(
        props,
        null
        /* we know it doesn't need it */
      );
    }
  } catch (err) {
    handleError$1(err, instance2, 1);
    result = false;
  }
  setRef$1(instance2);
  setCurrentRenderingInstance(prev);
  return result;
}
function fallthroughAttrs(inheritAttrs, props, propsOptions, fallthroughAttrs2) {
  if (props && fallthroughAttrs2 && inheritAttrs !== false) {
    const keys = Object.keys(fallthroughAttrs2).filter(
      (key) => key !== "class" && key !== "style"
    );
    if (!keys.length) {
      return;
    }
    if (propsOptions && keys.some(isModelListener)) {
      keys.forEach((key) => {
        if (!isModelListener(key) || !(key.slice(9) in propsOptions)) {
          props[key] = fallthroughAttrs2[key];
        }
      });
    } else {
      keys.forEach((key) => props[key] = fallthroughAttrs2[key]);
    }
  }
}
const updateComponentPreRender = (instance2) => {
  pauseTracking();
  flushPreFlushCbs();
  resetTracking();
};
function componentUpdateScopedSlotsFn() {
  const scopedSlotsData = this.$scopedSlotsData;
  if (!scopedSlotsData || scopedSlotsData.length === 0) {
    return;
  }
  const mpInstance = this.ctx.$scope;
  const oldData = mpInstance.data;
  const diffData = /* @__PURE__ */ Object.create(null);
  scopedSlotsData.forEach(({ path, index: index2, data }) => {
    const oldScopedSlotData = getValueByDataPath(oldData, path);
    const diffPath = isString(index2) ? `${path}.${index2}` : `${path}[${index2}]`;
    if (typeof oldScopedSlotData === "undefined" || typeof oldScopedSlotData[index2] === "undefined") {
      diffData[diffPath] = data;
    } else {
      const diffScopedSlotData = diff(
        data,
        oldScopedSlotData[index2]
      );
      Object.keys(diffScopedSlotData).forEach((name) => {
        diffData[diffPath + "." + name] = diffScopedSlotData[name];
      });
    }
  });
  scopedSlotsData.length = 0;
  if (Object.keys(diffData).length) {
    mpInstance.setData(diffData);
  }
}
function toggleRecurse({ effect: effect2, update }, allowed) {
  effect2.allowRecurse = update.allowRecurse = allowed;
}
function setupRenderEffect(instance2) {
  const updateScopedSlots = componentUpdateScopedSlotsFn.bind(
    instance2
  );
  instance2.$updateScopedSlots = () => nextTick$1(() => queueJob(updateScopedSlots));
  const componentUpdateFn = () => {
    if (!instance2.isMounted) {
      onBeforeUnmount(() => {
        setRef$1(instance2, true);
      }, instance2);
      {
        startMeasure(instance2, `patch`);
      }
      patch(instance2, renderComponentRoot(instance2));
      {
        endMeasure(instance2, `patch`);
      }
      {
        devtoolsComponentAdded(instance2);
      }
    } else {
      const { next, bu, u } = instance2;
      {
        pushWarningContext(next || instance2.vnode);
      }
      toggleRecurse(instance2, false);
      updateComponentPreRender();
      if (bu) {
        invokeArrayFns$1(bu);
      }
      toggleRecurse(instance2, true);
      {
        startMeasure(instance2, `patch`);
      }
      patch(instance2, renderComponentRoot(instance2));
      {
        endMeasure(instance2, `patch`);
      }
      if (u) {
        queuePostRenderEffect(u);
      }
      {
        devtoolsComponentUpdated(instance2);
      }
      {
        popWarningContext();
      }
    }
  };
  const effect2 = instance2.effect = new ReactiveEffect(
    componentUpdateFn,
    NOOP,
    () => queueJob(update),
    instance2.scope
    // track it in component's effect scope
  );
  const update = instance2.update = () => {
    if (effect2.dirty) {
      effect2.run();
    }
  };
  update.id = instance2.uid;
  toggleRecurse(instance2, true);
  {
    effect2.onTrack = instance2.rtc ? (e2) => invokeArrayFns$1(instance2.rtc, e2) : void 0;
    effect2.onTrigger = instance2.rtg ? (e2) => invokeArrayFns$1(instance2.rtg, e2) : void 0;
    update.ownerInstance = instance2;
  }
  {
    update();
  }
}
function unmountComponent(instance2) {
  const { bum, scope, update, um } = instance2;
  if (bum) {
    invokeArrayFns$1(bum);
  }
  {
    const parentInstance = instance2.parent;
    if (parentInstance) {
      const $children = parentInstance.ctx.$children;
      const target = getExposeProxy(instance2) || instance2.proxy;
      const index2 = $children.indexOf(target);
      if (index2 > -1) {
        $children.splice(index2, 1);
      }
    }
  }
  scope.stop();
  if (update) {
    update.active = false;
  }
  if (um) {
    queuePostRenderEffect(um);
  }
  queuePostRenderEffect(() => {
    instance2.isUnmounted = true;
  });
  {
    devtoolsComponentRemoved(instance2);
  }
}
const oldCreateApp = createAppAPI();
function getTarget() {
  if (typeof window !== "undefined") {
    return window;
  }
  if (typeof globalThis !== "undefined") {
    return globalThis;
  }
  if (typeof global !== "undefined") {
    return global;
  }
  if (typeof my !== "undefined") {
    return my;
  }
}
function createVueApp(rootComponent, rootProps = null) {
  const target = getTarget();
  target.__VUE__ = true;
  {
    setDevtoolsHook(target.__VUE_DEVTOOLS_GLOBAL_HOOK__, target);
  }
  const app = oldCreateApp(rootComponent, rootProps);
  const appContext = app._context;
  initAppConfig(appContext.config);
  const createVNode2 = (initialVNode) => {
    initialVNode.appContext = appContext;
    initialVNode.shapeFlag = 6;
    return initialVNode;
  };
  const createComponent2 = function createComponent22(initialVNode, options) {
    return mountComponent(createVNode2(initialVNode), options);
  };
  const destroyComponent = function destroyComponent2(component) {
    return component && unmountComponent(component.$);
  };
  app.mount = function mount() {
    rootComponent.render = NOOP;
    const instance2 = mountComponent(
      createVNode2({ type: rootComponent }),
      {
        mpType: "app",
        mpInstance: null,
        parentComponent: null,
        slots: [],
        props: null
      }
    );
    app._instance = instance2.$;
    {
      devtoolsInitApp(app, version);
    }
    instance2.$app = app;
    instance2.$createComponent = createComponent2;
    instance2.$destroyComponent = destroyComponent;
    appContext.$appInstance = instance2;
    return instance2;
  };
  app.unmount = function unmount() {
    warn(`Cannot unmount an app.`);
  };
  return app;
}
function injectLifecycleHook(name, hook, publicThis, instance2) {
  if (isFunction(hook)) {
    injectHook(name, hook.bind(publicThis), instance2);
  }
}
function initHooks$1(options, instance2, publicThis) {
  const mpType = options.mpType || publicThis.$mpType;
  if (!mpType || mpType === "component" || // instance.renderer 标识页面是否作为组件渲染
  mpType === "page" && instance2.renderer === "component") {
    return;
  }
  Object.keys(options).forEach((name) => {
    if (isUniLifecycleHook(name, options[name], false)) {
      const hooks = options[name];
      if (isArray(hooks)) {
        hooks.forEach((hook) => injectLifecycleHook(name, hook, publicThis, instance2));
      } else {
        injectLifecycleHook(name, hooks, publicThis, instance2);
      }
    }
  });
}
function applyOptions$2(options, instance2, publicThis) {
  initHooks$1(options, instance2, publicThis);
}
function set$2(target, key, val) {
  return target[key] = val;
}
function $callMethod(method, ...args) {
  const fn = this[method];
  if (fn) {
    return fn(...args);
  }
  console.error(`method ${method} not found`);
  return null;
}
function createErrorHandler(app) {
  const userErrorHandler = app.config.errorHandler;
  return function errorHandler(err, instance2, info) {
    if (userErrorHandler) {
      userErrorHandler(err, instance2, info);
    }
    const appInstance = app._instance;
    if (!appInstance || !appInstance.proxy) {
      throw err;
    }
    if (appInstance[ON_ERROR]) {
      {
        appInstance.proxy.$callHook(ON_ERROR, err);
      }
    } else {
      logError(err, info, instance2 ? instance2.$.vnode : null, false);
    }
  };
}
function mergeAsArray(to, from) {
  return to ? [...new Set([].concat(to, from))] : from;
}
function initOptionMergeStrategies(optionMergeStrategies) {
  UniLifecycleHooks.forEach((name) => {
    optionMergeStrategies[name] = mergeAsArray;
  });
}
let realAtob;
const b64 = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/=";
const b64re = /^(?:[A-Za-z\d+/]{4})*?(?:[A-Za-z\d+/]{2}(?:==)?|[A-Za-z\d+/]{3}=?)?$/;
if (typeof atob !== "function") {
  realAtob = function(str) {
    str = String(str).replace(/[\t\n\f\r ]+/g, "");
    if (!b64re.test(str)) {
      throw new Error("Failed to execute 'atob' on 'Window': The string to be decoded is not correctly encoded.");
    }
    str += "==".slice(2 - (str.length & 3));
    var bitmap;
    var result = "";
    var r1;
    var r2;
    var i = 0;
    for (; i < str.length; ) {
      bitmap = b64.indexOf(str.charAt(i++)) << 18 | b64.indexOf(str.charAt(i++)) << 12 | (r1 = b64.indexOf(str.charAt(i++))) << 6 | (r2 = b64.indexOf(str.charAt(i++)));
      result += r1 === 64 ? String.fromCharCode(bitmap >> 16 & 255) : r2 === 64 ? String.fromCharCode(bitmap >> 16 & 255, bitmap >> 8 & 255) : String.fromCharCode(bitmap >> 16 & 255, bitmap >> 8 & 255, bitmap & 255);
    }
    return result;
  };
} else {
  realAtob = atob;
}
function b64DecodeUnicode(str) {
  return decodeURIComponent(realAtob(str).split("").map(function(c2) {
    return "%" + ("00" + c2.charCodeAt(0).toString(16)).slice(-2);
  }).join(""));
}
function getCurrentUserInfo() {
  const token = index.getStorageSync("uni_id_token") || "";
  const tokenArr = token.split(".");
  if (!token || tokenArr.length !== 3) {
    return {
      uid: null,
      role: [],
      permission: [],
      tokenExpired: 0
    };
  }
  let userInfo;
  try {
    userInfo = JSON.parse(b64DecodeUnicode(tokenArr[1]));
  } catch (error) {
    throw new Error("获取当前用户信息出错，详细错误信息为：" + error.message);
  }
  userInfo.tokenExpired = userInfo.exp * 1e3;
  delete userInfo.exp;
  delete userInfo.iat;
  return userInfo;
}
function uniIdMixin(globalProperties) {
  globalProperties.uniIDHasRole = function(roleId) {
    const { role } = getCurrentUserInfo();
    return role.indexOf(roleId) > -1;
  };
  globalProperties.uniIDHasPermission = function(permissionId) {
    const { permission } = getCurrentUserInfo();
    return this.uniIDHasRole("admin") || permission.indexOf(permissionId) > -1;
  };
  globalProperties.uniIDTokenValid = function() {
    const { tokenExpired } = getCurrentUserInfo();
    return tokenExpired > Date.now();
  };
}
function initApp(app) {
  const appConfig = app.config;
  appConfig.errorHandler = invokeCreateErrorHandler(app, createErrorHandler);
  initOptionMergeStrategies(appConfig.optionMergeStrategies);
  const globalProperties = appConfig.globalProperties;
  {
    uniIdMixin(globalProperties);
  }
  {
    globalProperties.$set = set$2;
    globalProperties.$applyOptions = applyOptions$2;
    globalProperties.$callMethod = $callMethod;
  }
  {
    index.invokeCreateVueAppHook(app);
  }
}
const propsCaches = /* @__PURE__ */ Object.create(null);
function renderProps(props) {
  const { uid: uid2, __counter } = getCurrentInstance();
  const propsId = (propsCaches[uid2] || (propsCaches[uid2] = [])).push(guardReactiveProps(props)) - 1;
  return uid2 + "," + propsId + "," + __counter;
}
function pruneComponentPropsCache(uid2) {
  delete propsCaches[uid2];
}
function findComponentPropsData(up) {
  if (!up) {
    return;
  }
  const [uid2, propsId] = up.split(",");
  if (!propsCaches[uid2]) {
    return;
  }
  return propsCaches[uid2][parseInt(propsId)];
}
var plugin = {
  install(app) {
    initApp(app);
    app.config.globalProperties.pruneComponentPropsCache = pruneComponentPropsCache;
    const oldMount = app.mount;
    app.mount = function mount(rootContainer) {
      const instance2 = oldMount.call(app, rootContainer);
      const createApp2 = getCreateApp();
      if (createApp2) {
        createApp2(instance2);
      } else {
        if (typeof createMiniProgramApp !== "undefined") {
          createMiniProgramApp(instance2);
        }
      }
      return instance2;
    };
  }
};
function getCreateApp() {
  const method = "createApp";
  if (typeof global !== "undefined" && typeof global[method] !== "undefined") {
    return global[method];
  } else if (typeof my !== "undefined") {
    return my[method];
  }
}
function vOn(value, key) {
  const instance2 = getCurrentInstance();
  const ctx = instance2.ctx;
  const extraKey = typeof key !== "undefined" && (ctx.$mpPlatform === "mp-weixin" || ctx.$mpPlatform === "mp-qq" || ctx.$mpPlatform === "mp-xhs") && (isString(key) || typeof key === "number") ? "_" + key : "";
  const name = "e" + instance2.$ei++ + extraKey;
  const mpInstance = ctx.$scope;
  if (!value) {
    delete mpInstance[name];
    return name;
  }
  const existingInvoker = mpInstance[name];
  if (existingInvoker) {
    existingInvoker.value = value;
  } else {
    mpInstance[name] = createInvoker(value, instance2);
  }
  return name;
}
function createInvoker(initialValue, instance2) {
  const invoker = (e2) => {
    patchMPEvent(e2);
    let args = [e2];
    if (instance2 && instance2.ctx.$getTriggerEventDetail) {
      if (typeof e2.detail === "number") {
        e2.detail = instance2.ctx.$getTriggerEventDetail(e2.detail);
      }
    }
    if (e2.detail && e2.detail.__args__) {
      args = e2.detail.__args__;
    }
    const eventValue = invoker.value;
    const invoke = () => callWithAsyncErrorHandling(patchStopImmediatePropagation(e2, eventValue), instance2, 5, args);
    const eventTarget = e2.target;
    const eventSync = eventTarget ? eventTarget.dataset ? String(eventTarget.dataset.eventsync) === "true" : false : false;
    if (bubbles.includes(e2.type) && !eventSync) {
      setTimeout(invoke);
    } else {
      const res = invoke();
      if (e2.type === "input" && (isArray(res) || isPromise(res))) {
        return;
      }
      return res;
    }
  };
  invoker.value = initialValue;
  return invoker;
}
const bubbles = [
  // touch事件暂不做延迟，否则在 Android 上会影响性能，比如一些拖拽跟手手势等
  // 'touchstart',
  // 'touchmove',
  // 'touchcancel',
  // 'touchend',
  "tap",
  "longpress",
  "longtap",
  "transitionend",
  "animationstart",
  "animationiteration",
  "animationend",
  "touchforcechange"
];
function patchMPEvent(event, instance2) {
  if (event.type && event.target) {
    event.preventDefault = NOOP;
    event.stopPropagation = NOOP;
    event.stopImmediatePropagation = NOOP;
    if (!hasOwn(event, "detail")) {
      event.detail = {};
    }
    if (hasOwn(event, "markerId")) {
      event.detail = typeof event.detail === "object" ? event.detail : {};
      event.detail.markerId = event.markerId;
    }
    if (isPlainObject$1(event.detail) && hasOwn(event.detail, "checked") && !hasOwn(event.detail, "value")) {
      event.detail.value = event.detail.checked;
    }
    if (isPlainObject$1(event.detail)) {
      event.target = extend({}, event.target, event.detail);
    }
  }
}
function patchStopImmediatePropagation(e2, value) {
  if (isArray(value)) {
    const originalStop = e2.stopImmediatePropagation;
    e2.stopImmediatePropagation = () => {
      originalStop && originalStop.call(e2);
      e2._stopped = true;
    };
    return value.map((fn) => (e3) => !e3._stopped && fn(e3));
  } else {
    return value;
  }
}
function vFor(source, renderItem) {
  let ret;
  if (isArray(source) || isString(source)) {
    ret = new Array(source.length);
    for (let i = 0, l = source.length; i < l; i++) {
      ret[i] = renderItem(source[i], i, i);
    }
  } else if (typeof source === "number") {
    if (!Number.isInteger(source)) {
      warn(`The v-for range expect an integer value but got ${source}.`);
      return [];
    }
    ret = new Array(source);
    for (let i = 0; i < source; i++) {
      ret[i] = renderItem(i + 1, i, i);
    }
  } else if (isObject(source)) {
    if (source[Symbol.iterator]) {
      ret = Array.from(source, (item, i) => renderItem(item, i, i));
    } else {
      const keys = Object.keys(source);
      ret = new Array(keys.length);
      for (let i = 0, l = keys.length; i < l; i++) {
        const key = keys[i];
        ret[i] = renderItem(source[key], key, i);
      }
    }
  } else {
    ret = [];
  }
  return ret;
}
const o = (value, key) => vOn(value, key);
const f = (source, renderItem) => vFor(source, renderItem);
const e = (target, ...sources) => extend(target, ...sources);
const n$1 = (value) => normalizeClass(value);
const t = (val) => toDisplayString(val);
const p = (props) => renderProps(props);
function createApp$1(rootComponent, rootProps = null) {
  rootComponent && (rootComponent.mpType = "app");
  return createVueApp(rootComponent, rootProps).use(plugin);
}
const createSSRApp = createApp$1;
function getLocaleLanguage$1() {
  var _a;
  let localeLanguage = "";
  {
    const appBaseInfo = ((_a = wx.getAppBaseInfo) === null || _a === void 0 ? void 0 : _a.call(wx)) || wx.getSystemInfoSync();
    const language = appBaseInfo && appBaseInfo.language ? appBaseInfo.language : LOCALE_EN;
    localeLanguage = normalizeLocale(language) || LOCALE_EN;
  }
  return localeLanguage;
}
function validateProtocolFail(name, msg) {
  console.warn(`${name}: ${msg}`);
}
function validateProtocol(name, data, protocol, onFail) {
  if (!onFail) {
    onFail = validateProtocolFail;
  }
  for (const key in protocol) {
    const errMsg = validateProp(key, data[key], protocol[key], !hasOwn(data, key));
    if (isString(errMsg)) {
      onFail(name, errMsg);
    }
  }
}
function validateProtocols(name, args, protocol, onFail) {
  if (!protocol) {
    return;
  }
  if (!isArray(protocol)) {
    return validateProtocol(name, args[0] || /* @__PURE__ */ Object.create(null), protocol, onFail);
  }
  const len = protocol.length;
  const argsLen = args.length;
  for (let i = 0; i < len; i++) {
    const opts = protocol[i];
    const data = /* @__PURE__ */ Object.create(null);
    if (argsLen > i) {
      data[opts.name] = args[i];
    }
    validateProtocol(name, data, { [opts.name]: opts }, onFail);
  }
}
function validateProp(name, value, prop, isAbsent) {
  if (!isPlainObject$1(prop)) {
    prop = { type: prop };
  }
  const { type, required, validator } = prop;
  if (required && isAbsent) {
    return 'Missing required args: "' + name + '"';
  }
  if (value == null && !required) {
    return;
  }
  if (type != null) {
    let isValid = false;
    const types = isArray(type) ? type : [type];
    const expectedTypes = [];
    for (let i = 0; i < types.length && !isValid; i++) {
      const { valid, expectedType } = assertType(value, types[i]);
      expectedTypes.push(expectedType || "");
      isValid = valid;
    }
    if (!isValid) {
      return getInvalidTypeMessage(name, value, expectedTypes);
    }
  }
  if (validator) {
    return validator(value);
  }
}
const isSimpleType = /* @__PURE__ */ makeMap("String,Number,Boolean,Function,Symbol");
function assertType(value, type) {
  let valid;
  const expectedType = getType(type);
  if (isSimpleType(expectedType)) {
    const t2 = typeof value;
    valid = t2 === expectedType.toLowerCase();
    if (!valid && t2 === "object") {
      valid = value instanceof type;
    }
  } else if (expectedType === "Object") {
    valid = isObject(value);
  } else if (expectedType === "Array") {
    valid = isArray(value);
  } else {
    {
      valid = value instanceof type;
    }
  }
  return {
    valid,
    expectedType
  };
}
function getInvalidTypeMessage(name, value, expectedTypes) {
  let message = `Invalid args: type check failed for args "${name}". Expected ${expectedTypes.map(capitalize).join(", ")}`;
  const expectedType = expectedTypes[0];
  const receivedType = toRawType(value);
  const expectedValue = styleValue(value, expectedType);
  const receivedValue = styleValue(value, receivedType);
  if (expectedTypes.length === 1 && isExplicable(expectedType) && !isBoolean(expectedType, receivedType)) {
    message += ` with value ${expectedValue}`;
  }
  message += `, got ${receivedType} `;
  if (isExplicable(receivedType)) {
    message += `with value ${receivedValue}.`;
  }
  return message;
}
function getType(ctor) {
  const match = ctor && ctor.toString().match(/^\s*function (\w+)/);
  return match ? match[1] : "";
}
function styleValue(value, type) {
  if (type === "String") {
    return `"${value}"`;
  } else if (type === "Number") {
    return `${Number(value)}`;
  } else {
    return `${value}`;
  }
}
function isExplicable(type) {
  const explicitTypes = ["string", "number", "boolean"];
  return explicitTypes.some((elem) => type.toLowerCase() === elem);
}
function isBoolean(...args) {
  return args.some((elem) => elem.toLowerCase() === "boolean");
}
function tryCatch(fn) {
  return function() {
    try {
      return fn.apply(fn, arguments);
    } catch (e2) {
      console.error(e2);
    }
  };
}
let invokeCallbackId = 1;
const invokeCallbacks = {};
function addInvokeCallback(id, name, callback, keepAlive = false) {
  invokeCallbacks[id] = {
    name,
    keepAlive,
    callback
  };
  return id;
}
function invokeCallback(id, res, extras) {
  if (typeof id === "number") {
    const opts = invokeCallbacks[id];
    if (opts) {
      if (!opts.keepAlive) {
        delete invokeCallbacks[id];
      }
      return opts.callback(res, extras);
    }
  }
  return res;
}
const API_SUCCESS = "success";
const API_FAIL = "fail";
const API_COMPLETE = "complete";
function getApiCallbacks(args) {
  const apiCallbacks = {};
  for (const name in args) {
    const fn = args[name];
    if (isFunction(fn)) {
      apiCallbacks[name] = tryCatch(fn);
      delete args[name];
    }
  }
  return apiCallbacks;
}
function normalizeErrMsg(errMsg, name) {
  if (!errMsg || errMsg.indexOf(":fail") === -1) {
    return name + ":ok";
  }
  return name + errMsg.substring(errMsg.indexOf(":fail"));
}
function createAsyncApiCallback(name, args = {}, { beforeAll, beforeSuccess } = {}) {
  if (!isPlainObject$1(args)) {
    args = {};
  }
  const { success, fail, complete } = getApiCallbacks(args);
  const hasSuccess = isFunction(success);
  const hasFail = isFunction(fail);
  const hasComplete = isFunction(complete);
  const callbackId = invokeCallbackId++;
  addInvokeCallback(callbackId, name, (res) => {
    res = res || {};
    res.errMsg = normalizeErrMsg(res.errMsg, name);
    isFunction(beforeAll) && beforeAll(res);
    if (res.errMsg === name + ":ok") {
      isFunction(beforeSuccess) && beforeSuccess(res, args);
      hasSuccess && success(res);
    } else {
      hasFail && fail(res);
    }
    hasComplete && complete(res);
  });
  return callbackId;
}
const HOOK_SUCCESS = "success";
const HOOK_FAIL = "fail";
const HOOK_COMPLETE = "complete";
const globalInterceptors = {};
const scopedInterceptors = {};
function wrapperHook(hook, params) {
  return function(data) {
    return hook(data, params) || data;
  };
}
function queue(hooks, data, params) {
  let promise = false;
  for (let i = 0; i < hooks.length; i++) {
    const hook = hooks[i];
    if (promise) {
      promise = Promise.resolve(wrapperHook(hook, params));
    } else {
      const res = hook(data, params);
      if (isPromise(res)) {
        promise = Promise.resolve(res);
      }
      if (res === false) {
        return {
          then() {
          },
          catch() {
          }
        };
      }
    }
  }
  return promise || {
    then(callback) {
      return callback(data);
    },
    catch() {
    }
  };
}
function wrapperOptions(interceptors2, options = {}) {
  [HOOK_SUCCESS, HOOK_FAIL, HOOK_COMPLETE].forEach((name) => {
    const hooks = interceptors2[name];
    if (!isArray(hooks)) {
      return;
    }
    const oldCallback = options[name];
    options[name] = function callbackInterceptor(res) {
      queue(hooks, res, options).then((res2) => {
        return isFunction(oldCallback) && oldCallback(res2) || res2;
      });
    };
  });
  return options;
}
function wrapperReturnValue(method, returnValue) {
  const returnValueHooks = [];
  if (isArray(globalInterceptors.returnValue)) {
    returnValueHooks.push(...globalInterceptors.returnValue);
  }
  const interceptor2 = scopedInterceptors[method];
  if (interceptor2 && isArray(interceptor2.returnValue)) {
    returnValueHooks.push(...interceptor2.returnValue);
  }
  returnValueHooks.forEach((hook) => {
    returnValue = hook(returnValue) || returnValue;
  });
  return returnValue;
}
function getApiInterceptorHooks(method) {
  const interceptor2 = /* @__PURE__ */ Object.create(null);
  Object.keys(globalInterceptors).forEach((hook) => {
    if (hook !== "returnValue") {
      interceptor2[hook] = globalInterceptors[hook].slice();
    }
  });
  const scopedInterceptor = scopedInterceptors[method];
  if (scopedInterceptor) {
    Object.keys(scopedInterceptor).forEach((hook) => {
      if (hook !== "returnValue") {
        interceptor2[hook] = (interceptor2[hook] || []).concat(scopedInterceptor[hook]);
      }
    });
  }
  return interceptor2;
}
function invokeApi(method, api, options, params) {
  const interceptor2 = getApiInterceptorHooks(method);
  if (interceptor2 && Object.keys(interceptor2).length) {
    if (isArray(interceptor2.invoke)) {
      const res = queue(interceptor2.invoke, options);
      return res.then((options2) => {
        return api(wrapperOptions(getApiInterceptorHooks(method), options2), ...params);
      });
    } else {
      return api(wrapperOptions(interceptor2, options), ...params);
    }
  }
  return api(options, ...params);
}
function hasCallback(args) {
  if (isPlainObject$1(args) && [API_SUCCESS, API_FAIL, API_COMPLETE].find((cb) => isFunction(args[cb]))) {
    return true;
  }
  return false;
}
function handlePromise(promise) {
  return promise;
}
function promisify$1(name, fn) {
  return (args = {}, ...rest) => {
    if (hasCallback(args)) {
      return wrapperReturnValue(name, invokeApi(name, fn, extend({}, args), rest));
    }
    return wrapperReturnValue(name, handlePromise(new Promise((resolve, reject) => {
      invokeApi(name, fn, extend({}, args, { success: resolve, fail: reject }), rest);
    })));
  };
}
function formatApiArgs(args, options) {
  args[0];
  {
    return;
  }
}
function invokeSuccess(id, name, res) {
  const result = {
    errMsg: name + ":ok"
  };
  return invokeCallback(id, extend(res || {}, result));
}
function invokeFail(id, name, errMsg, errRes = {}) {
  const errMsgPrefix = name + ":fail";
  let apiErrMsg = "";
  if (!errMsg) {
    apiErrMsg = errMsgPrefix;
  } else if (errMsg.indexOf(errMsgPrefix) === 0) {
    apiErrMsg = errMsg;
  } else {
    apiErrMsg = errMsgPrefix + " " + errMsg;
  }
  {
    delete errRes.errCode;
  }
  let res = extend({ errMsg: apiErrMsg }, errRes);
  return invokeCallback(id, res);
}
function beforeInvokeApi(name, args, protocol, options) {
  {
    validateProtocols(name, args, protocol);
  }
  const errMsg = formatApiArgs(args);
  if (errMsg) {
    return errMsg;
  }
}
function parseErrMsg(errMsg) {
  if (!errMsg || isString(errMsg)) {
    return errMsg;
  }
  if (errMsg.stack) {
    if (typeof globalThis === "undefined" || !globalThis.harmonyChannel) {
      console.error(errMsg.message + "\n" + errMsg.stack);
    }
    return errMsg.message;
  }
  return errMsg;
}
function wrapperTaskApi(name, fn, protocol, options) {
  return (args) => {
    const id = createAsyncApiCallback(name, args, options);
    const errMsg = beforeInvokeApi(name, [args], protocol);
    if (errMsg) {
      return invokeFail(id, name, errMsg);
    }
    return fn(args, {
      resolve: (res) => invokeSuccess(id, name, res),
      reject: (errMsg2, errRes) => invokeFail(id, name, parseErrMsg(errMsg2), errRes)
    });
  };
}
function wrapperSyncApi(name, fn, protocol, options) {
  return (...args) => {
    const errMsg = beforeInvokeApi(name, args, protocol);
    if (errMsg) {
      throw new Error(errMsg);
    }
    return fn.apply(null, args);
  };
}
function wrapperAsyncApi(name, fn, protocol, options) {
  return wrapperTaskApi(name, fn, protocol, options);
}
function defineSyncApi(name, fn, protocol, options) {
  return wrapperSyncApi(name, fn, protocol);
}
function defineAsyncApi(name, fn, protocol, options) {
  return promisify$1(name, wrapperAsyncApi(name, fn, protocol, options));
}
const API_UPX2PX = "upx2px";
const Upx2pxProtocol = [
  {
    name: "upx",
    type: [Number, String],
    required: true
  }
];
const EPS = 1e-4;
const BASE_DEVICE_WIDTH = 750;
let isIOS = false;
let deviceWidth = 0;
let deviceDPR = 0;
function checkDeviceWidth() {
  var _a, _b;
  let windowWidth, pixelRatio, platform;
  {
    const windowInfo = ((_a = wx.getWindowInfo) === null || _a === void 0 ? void 0 : _a.call(wx)) || wx.getSystemInfoSync();
    const deviceInfo = ((_b = wx.getDeviceInfo) === null || _b === void 0 ? void 0 : _b.call(wx)) || wx.getSystemInfoSync();
    windowWidth = windowInfo.windowWidth;
    pixelRatio = windowInfo.pixelRatio;
    platform = deviceInfo.platform;
  }
  deviceWidth = windowWidth;
  deviceDPR = pixelRatio;
  isIOS = platform === "ios";
}
const upx2px = defineSyncApi(API_UPX2PX, (number, newDeviceWidth) => {
  if (deviceWidth === 0) {
    checkDeviceWidth();
  }
  number = Number(number);
  if (number === 0) {
    return 0;
  }
  let width = newDeviceWidth || deviceWidth;
  let result = number / BASE_DEVICE_WIDTH * width;
  if (result < 0) {
    result = -result;
  }
  result = Math.floor(result + EPS);
  if (result === 0) {
    if (deviceDPR === 1 || !isIOS) {
      result = 1;
    } else {
      result = 0.5;
    }
  }
  return number < 0 ? -result : result;
}, Upx2pxProtocol);
function __f__(type, filename, ...args) {
  if (filename) {
    args.push(filename);
  }
  console[type].apply(console, args);
}
const API_ADD_INTERCEPTOR = "addInterceptor";
const API_REMOVE_INTERCEPTOR = "removeInterceptor";
const AddInterceptorProtocol = [
  {
    name: "method",
    type: [String, Object],
    required: true
  }
];
const RemoveInterceptorProtocol = AddInterceptorProtocol;
function mergeInterceptorHook(interceptors2, interceptor2) {
  Object.keys(interceptor2).forEach((hook) => {
    if (isFunction(interceptor2[hook])) {
      interceptors2[hook] = mergeHook(interceptors2[hook], interceptor2[hook]);
    }
  });
}
function removeInterceptorHook(interceptors2, interceptor2) {
  if (!interceptors2 || !interceptor2) {
    return;
  }
  Object.keys(interceptor2).forEach((name) => {
    const hooks = interceptors2[name];
    const hook = interceptor2[name];
    if (isArray(hooks) && isFunction(hook)) {
      remove$1(hooks, hook);
    }
  });
}
function mergeHook(parentVal, childVal) {
  const res = childVal ? parentVal ? parentVal.concat(childVal) : isArray(childVal) ? childVal : [childVal] : parentVal;
  return res ? dedupeHooks(res) : res;
}
function dedupeHooks(hooks) {
  const res = [];
  for (let i = 0; i < hooks.length; i++) {
    if (res.indexOf(hooks[i]) === -1) {
      res.push(hooks[i]);
    }
  }
  return res;
}
const addInterceptor = defineSyncApi(API_ADD_INTERCEPTOR, (method, interceptor2) => {
  if (isString(method) && isPlainObject$1(interceptor2)) {
    mergeInterceptorHook(scopedInterceptors[method] || (scopedInterceptors[method] = {}), interceptor2);
  } else if (isPlainObject$1(method)) {
    mergeInterceptorHook(globalInterceptors, method);
  }
}, AddInterceptorProtocol);
const removeInterceptor = defineSyncApi(API_REMOVE_INTERCEPTOR, (method, interceptor2) => {
  if (isString(method)) {
    if (isPlainObject$1(interceptor2)) {
      removeInterceptorHook(scopedInterceptors[method], interceptor2);
    } else {
      delete scopedInterceptors[method];
    }
  } else if (isPlainObject$1(method)) {
    removeInterceptorHook(globalInterceptors, method);
  }
}, RemoveInterceptorProtocol);
const interceptors = {};
const API_ON = "$on";
const OnProtocol = [
  {
    name: "event",
    type: String,
    required: true
  },
  {
    name: "callback",
    type: Function,
    required: true
  }
];
const API_ONCE = "$once";
const OnceProtocol = OnProtocol;
const API_OFF = "$off";
const OffProtocol = [
  {
    name: "event",
    type: [String, Array]
  },
  {
    name: "callback",
    type: [Function, Number]
  }
];
const API_EMIT = "$emit";
const EmitProtocol = [
  {
    name: "event",
    type: String,
    required: true
  }
];
class EventBus {
  constructor() {
    this.$emitter = new E$1();
  }
  on(name, callback) {
    return this.$emitter.on(name, callback);
  }
  once(name, callback) {
    return this.$emitter.once(name, callback);
  }
  off(name, callback) {
    if (!name) {
      this.$emitter.e = {};
      return;
    }
    this.$emitter.off(name, callback);
  }
  emit(name, ...args) {
    this.$emitter.emit(name, ...args);
  }
}
const eventBus = new EventBus();
const $on = defineSyncApi(API_ON, (name, callback) => {
  eventBus.on(name, callback);
  return () => eventBus.off(name, callback);
}, OnProtocol);
const $once = defineSyncApi(API_ONCE, (name, callback) => {
  eventBus.once(name, callback);
  return () => eventBus.off(name, callback);
}, OnceProtocol);
const $off = defineSyncApi(API_OFF, (name, callback) => {
  if (!isArray(name))
    name = name ? [name] : [];
  name.forEach((n2) => {
    eventBus.off(n2, callback);
  });
}, OffProtocol);
const $emit = defineSyncApi(API_EMIT, (name, ...args) => {
  eventBus.emit(name, ...args);
}, EmitProtocol);
let cid;
let cidErrMsg;
let enabled;
function normalizePushMessage(message) {
  try {
    return JSON.parse(message);
  } catch (e2) {
  }
  return message;
}
function invokePushCallback(args) {
  if (args.type === "enabled") {
    enabled = true;
  } else if (args.type === "clientId") {
    cid = args.cid;
    cidErrMsg = args.errMsg;
    invokeGetPushCidCallbacks(cid, args.errMsg);
  } else if (args.type === "pushMsg") {
    const message = {
      type: "receive",
      data: normalizePushMessage(args.message)
    };
    for (let i = 0; i < onPushMessageCallbacks.length; i++) {
      const callback = onPushMessageCallbacks[i];
      callback(message);
      if (message.stopped) {
        break;
      }
    }
  } else if (args.type === "click") {
    onPushMessageCallbacks.forEach((callback) => {
      callback({
        type: "click",
        data: normalizePushMessage(args.message)
      });
    });
  }
}
const getPushCidCallbacks = [];
function invokeGetPushCidCallbacks(cid2, errMsg) {
  getPushCidCallbacks.forEach((callback) => {
    callback(cid2, errMsg);
  });
  getPushCidCallbacks.length = 0;
}
const API_GET_PUSH_CLIENT_ID = "getPushClientId";
const getPushClientId$1 = defineAsyncApi(API_GET_PUSH_CLIENT_ID, (_, { resolve, reject }) => {
  Promise.resolve().then(() => {
    if (typeof enabled === "undefined") {
      enabled = false;
      cid = "";
      cidErrMsg = "uniPush is not enabled";
    }
    getPushCidCallbacks.push((cid2, errMsg) => {
      if (cid2) {
        resolve({ cid: cid2 });
      } else {
        reject(errMsg);
      }
    });
    if (typeof cid !== "undefined") {
      invokeGetPushCidCallbacks(cid, cidErrMsg);
    }
  });
});
const onPushMessageCallbacks = [];
const onPushMessage = (fn) => {
  if (onPushMessageCallbacks.indexOf(fn) === -1) {
    onPushMessageCallbacks.push(fn);
  }
};
const offPushMessage = (fn) => {
  if (!fn) {
    onPushMessageCallbacks.length = 0;
  } else {
    const index2 = onPushMessageCallbacks.indexOf(fn);
    if (index2 > -1) {
      onPushMessageCallbacks.splice(index2, 1);
    }
  }
};
const SYNC_API_RE = /^\$|__f__|getLocale|setLocale|sendNativeEvent|restoreGlobal|requireGlobal|getCurrentSubNVue|getMenuButtonBoundingClientRect|^report|interceptors|Interceptor$|getSubNVueById|requireNativePlugin|upx2px|rpx2px|hideKeyboard|canIUse|^create|Sync$|Manager$|base64ToArrayBuffer|arrayBufferToBase64|getDeviceInfo|getAppBaseInfo|getWindowInfo|getSystemSetting|getAppAuthorizeSetting/;
const CONTEXT_API_RE = /^create|Manager$/;
const CONTEXT_API_RE_EXC = ["createBLEConnection"];
const TASK_APIS = ["request", "downloadFile", "uploadFile", "connectSocket"];
const ASYNC_API = ["createBLEConnection"];
const CALLBACK_API_RE = /^on|^off/;
function isContextApi(name) {
  return CONTEXT_API_RE.test(name) && CONTEXT_API_RE_EXC.indexOf(name) === -1;
}
function isSyncApi(name) {
  return SYNC_API_RE.test(name) && ASYNC_API.indexOf(name) === -1;
}
function isCallbackApi(name) {
  return CALLBACK_API_RE.test(name) && name !== "onPush";
}
function isTaskApi(name) {
  return TASK_APIS.indexOf(name) !== -1;
}
function shouldPromise(name) {
  if (isContextApi(name) || isSyncApi(name) || isCallbackApi(name)) {
    return false;
  }
  return true;
}
if (!Promise.prototype.finally) {
  Promise.prototype.finally = function(onfinally) {
    const promise = this.constructor;
    return this.then((value) => promise.resolve(onfinally && onfinally()).then(() => value), (reason) => promise.resolve(onfinally && onfinally()).then(() => {
      throw reason;
    }));
  };
}
function promisify(name, api) {
  if (!shouldPromise(name)) {
    return api;
  }
  if (!isFunction(api)) {
    return api;
  }
  return function promiseApi(options = {}, ...rest) {
    if (isFunction(options.success) || isFunction(options.fail) || isFunction(options.complete)) {
      return wrapperReturnValue(name, invokeApi(name, api, extend({}, options), rest));
    }
    return wrapperReturnValue(name, handlePromise(new Promise((resolve, reject) => {
      invokeApi(name, api, extend({}, options, {
        success: resolve,
        fail: reject
      }), rest);
    })));
  };
}
const CALLBACKS = ["success", "fail", "cancel", "complete"];
function initWrapper(protocols2) {
  function processCallback(methodName, method, returnValue) {
    return function(res) {
      return method(processReturnValue(methodName, res, returnValue));
    };
  }
  function processArgs(methodName, fromArgs, argsOption = {}, returnValue = {}, keepFromArgs = false) {
    if (isPlainObject$1(fromArgs)) {
      const toArgs = keepFromArgs === true ? fromArgs : {};
      if (isFunction(argsOption)) {
        argsOption = argsOption(fromArgs, toArgs) || {};
      }
      for (const key in fromArgs) {
        if (hasOwn(argsOption, key)) {
          let keyOption = argsOption[key];
          if (isFunction(keyOption)) {
            keyOption = keyOption(fromArgs[key], fromArgs, toArgs);
          }
          if (!keyOption) {
            console.warn(`微信小程序 ${methodName} 暂不支持 ${key}`);
          } else if (isString(keyOption)) {
            toArgs[keyOption] = fromArgs[key];
          } else if (isPlainObject$1(keyOption)) {
            toArgs[keyOption.name ? keyOption.name : key] = keyOption.value;
          }
        } else if (CALLBACKS.indexOf(key) !== -1) {
          const callback = fromArgs[key];
          if (isFunction(callback)) {
            toArgs[key] = processCallback(methodName, callback, returnValue);
          }
        } else {
          if (!keepFromArgs && !hasOwn(toArgs, key)) {
            toArgs[key] = fromArgs[key];
          }
        }
      }
      return toArgs;
    } else if (isFunction(fromArgs)) {
      if (isFunction(argsOption)) {
        argsOption(fromArgs, {});
      }
      fromArgs = processCallback(methodName, fromArgs, returnValue);
    }
    return fromArgs;
  }
  function processReturnValue(methodName, res, returnValue, keepReturnValue = false) {
    if (isFunction(protocols2.returnValue)) {
      res = protocols2.returnValue(methodName, res);
    }
    const realKeepReturnValue = keepReturnValue || false;
    return processArgs(methodName, res, returnValue, {}, realKeepReturnValue);
  }
  return function wrapper(methodName, method) {
    const hasProtocol = hasOwn(protocols2, methodName);
    if (!hasProtocol && typeof wx[methodName] !== "function") {
      return method;
    }
    const needWrapper = hasProtocol || isFunction(protocols2.returnValue) || isContextApi(methodName) || isTaskApi(methodName);
    const hasMethod = hasProtocol || isFunction(method);
    if (!hasProtocol && !method) {
      return function() {
        console.error(`微信小程序 暂不支持${methodName}`);
      };
    }
    if (!needWrapper || !hasMethod) {
      return method;
    }
    const protocol = protocols2[methodName];
    return function(arg1, arg2) {
      let options = protocol || {};
      if (isFunction(protocol)) {
        options = protocol(arg1);
      }
      arg1 = processArgs(methodName, arg1, options.args, options.returnValue);
      const args = [arg1];
      if (typeof arg2 !== "undefined") {
        args.push(arg2);
      }
      const returnValue = wx[options.name || methodName].apply(wx, args);
      if (isContextApi(methodName) || isTaskApi(methodName)) {
        if (returnValue && !returnValue.__v_skip) {
          returnValue.__v_skip = true;
        }
      }
      if (isSyncApi(methodName)) {
        return processReturnValue(methodName, returnValue, options.returnValue, isContextApi(methodName));
      }
      return returnValue;
    };
  };
}
const getLocale = () => {
  const app = isFunction(getApp) && getApp({ allowDefault: true });
  if (app && app.$vm) {
    return app.$vm.$locale;
  }
  return getLocaleLanguage$1();
};
const setLocale = (locale) => {
  const app = isFunction(getApp) && getApp();
  if (!app) {
    return false;
  }
  const oldLocale = app.$vm.$locale;
  if (oldLocale !== locale) {
    app.$vm.$locale = locale;
    onLocaleChangeCallbacks.forEach((fn) => fn({ locale }));
    return true;
  }
  return false;
};
const onLocaleChangeCallbacks = [];
const onLocaleChange = (fn) => {
  if (onLocaleChangeCallbacks.indexOf(fn) === -1) {
    onLocaleChangeCallbacks.push(fn);
  }
};
if (typeof global !== "undefined") {
  global.getLocale = getLocale;
}
const UUID_KEY = "__DC_STAT_UUID";
let deviceId;
function useDeviceId(global2 = wx) {
  return function addDeviceId(_, toRes) {
    deviceId = deviceId || global2.getStorageSync(UUID_KEY);
    if (!deviceId) {
      deviceId = Date.now() + "" + Math.floor(Math.random() * 1e7);
      wx.setStorage({
        key: UUID_KEY,
        data: deviceId
      });
    }
    toRes.deviceId = deviceId;
  };
}
function addSafeAreaInsets(fromRes, toRes) {
  if (fromRes.safeArea) {
    const safeArea = fromRes.safeArea;
    toRes.safeAreaInsets = {
      top: safeArea.top,
      left: safeArea.left,
      right: fromRes.windowWidth - safeArea.right,
      bottom: fromRes.screenHeight - safeArea.bottom
    };
  }
}
function getOSInfo(system, platform) {
  let osName = "";
  let osVersion = "";
  if (platform && false) {
    osName = platform;
    osVersion = system;
    system = `${osName} ${osVersion}`;
  } else {
    {
      osName = platform;
    }
    osVersion = system.split(" ")[1] || "";
  }
  osName = osName.toLowerCase();
  switch (osName) {
    case "harmony":
    case "ohos":
    case "openharmonyos":
    case "openharmony":
      osName = "harmonyos";
      break;
    case "iphone os":
      osName = "ios";
      break;
    case "mac":
    case "darwin":
      osName = "macos";
      break;
    case "windows_nt":
      osName = "windows";
      break;
  }
  return {
    osName,
    osVersion,
    system
  };
}
function getPlatform$1(platform) {
  platform = platform.toLowerCase();
  {
    if (platform === "ohos") {
      platform = "harmonyos";
    }
  }
  return platform;
}
function populateParameters(fromRes, toRes) {
  const { brand = "", model = "", system = "", language = "", theme, version: version2, platform, fontSizeSetting, SDKVersion, pixelRatio, deviceOrientation } = fromRes;
  const { osName, osVersion, system: updatedSystem } = getOSInfo(system, platform);
  let hostVersion = version2;
  let deviceType = getGetDeviceType(fromRes, model);
  let deviceBrand = getDeviceBrand(brand);
  let _hostName = getHostName(fromRes);
  let _deviceOrientation = deviceOrientation;
  let _devicePixelRatio = pixelRatio;
  let _SDKVersion = SDKVersion;
  const hostLanguage = (language || "").replace(/_/g, "-");
  const parameters = {
    appId: "__UNI__4FA356E",
    appName: "LuckyNumber-Miniui",
    appVersion: "1.0.0",
    appVersionCode: "100",
    appLanguage: getAppLanguage(hostLanguage),
    uniCompileVersion: "5.13",
    uniCompilerVersion: "5.13",
    uniRuntimeVersion: "5.13",
    uniPlatform: "mp-weixin",
    deviceBrand,
    deviceModel: model,
    deviceType,
    devicePixelRatio: _devicePixelRatio,
    deviceOrientation: _deviceOrientation,
    osName,
    osVersion,
    hostTheme: theme,
    hostVersion,
    hostLanguage,
    hostName: _hostName,
    hostSDKVersion: _SDKVersion,
    hostFontSizeSetting: fontSizeSetting,
    windowTop: 0,
    windowBottom: 0,
    platform: getPlatform$1(platform),
    system: updatedSystem,
    // TODO
    osLanguage: void 0,
    osTheme: void 0,
    ua: void 0,
    hostPackageName: void 0,
    browserName: void 0,
    browserVersion: void 0,
    isUniAppX: false
  };
  extend(toRes, parameters);
}
function getGetDeviceType(fromRes, model) {
  const platform = fromRes.platform || "";
  let deviceType = fromRes.deviceType || "phone";
  {
    const deviceTypeMaps = {
      ipad: "pad",
      windows: "pc",
      mac: "pc",
      linux: "pc",
      pc: "pc"
    };
    const deviceTypeMapsKeys = Object.keys(deviceTypeMaps);
    const _model = model.toLowerCase();
    for (let index2 = 0; index2 < deviceTypeMapsKeys.length; index2++) {
      const _m = deviceTypeMapsKeys[index2];
      if (_model.indexOf(_m) !== -1) {
        deviceType = deviceTypeMaps[_m];
        break;
      }
    }
  }
  {
    if (platform === "ohos_pc") {
      deviceType = "pc";
    }
  }
  return deviceType;
}
function getDeviceBrand(brand) {
  let deviceBrand = brand;
  if (deviceBrand) {
    deviceBrand = deviceBrand.toLowerCase();
  }
  return deviceBrand;
}
function getAppLanguage(defaultLanguage) {
  return getLocale ? getLocale() : defaultLanguage;
}
function getHostName(fromRes) {
  const _platform = "WeChat";
  let _hostName = fromRes.hostName || _platform;
  {
    if (fromRes.environment) {
      _hostName = fromRes.environment;
    } else if (fromRes.host && fromRes.host.env) {
      _hostName = fromRes.host.env;
    }
  }
  return _hostName;
}
const getSystemInfo$1 = {
  returnValue: (fromRes, toRes) => {
    addSafeAreaInsets(fromRes, toRes);
    useDeviceId()(fromRes, toRes);
    populateParameters(fromRes, toRes);
  }
};
const getSystemInfoSync = getSystemInfo$1;
const redirectTo = {};
const previewImage = {
  args(fromArgs, toArgs) {
    let currentIndex = parseInt(fromArgs.current);
    if (isNaN(currentIndex)) {
      return;
    }
    const urls = fromArgs.urls;
    if (!isArray(urls)) {
      return;
    }
    const len = urls.length;
    if (!len) {
      return;
    }
    if (currentIndex < 0) {
      currentIndex = 0;
    } else if (currentIndex >= len) {
      currentIndex = len - 1;
    }
    if (currentIndex > 0) {
      toArgs.current = urls[currentIndex];
      toArgs.urls = urls.filter((item, index2) => index2 < currentIndex ? item !== urls[currentIndex] : true);
    } else {
      toArgs.current = urls[0];
    }
    return {
      indicator: false,
      loop: false
    };
  }
};
const showActionSheet = {
  args(fromArgs, toArgs) {
    toArgs.alertText = fromArgs.title;
  }
};
const getDeviceInfo = {
  returnValue: (fromRes, toRes) => {
    const { brand, model, system = "", platform = "" } = fromRes;
    let deviceType = getGetDeviceType(fromRes, model);
    let deviceBrand = getDeviceBrand(brand);
    useDeviceId()(fromRes, toRes);
    const { osName, osVersion } = getOSInfo(system, platform);
    toRes = extend(toRes, {
      deviceType,
      deviceBrand,
      deviceModel: model,
      osName,
      osVersion,
      platform: getPlatform$1(platform)
    });
  }
};
const getAppBaseInfo = {
  returnValue: (fromRes, toRes) => {
    const { version: version2, language, SDKVersion, theme } = fromRes;
    let _hostName = getHostName(fromRes);
    let hostLanguage = (language || "").replace(/_/g, "-");
    const parameters = {
      appId: "__UNI__4FA356E",
      appName: "LuckyNumber-Miniui",
      appVersion: "1.0.0",
      appVersionCode: "100",
      appLanguage: getAppLanguage(hostLanguage),
      hostVersion: version2,
      hostLanguage,
      hostName: _hostName,
      hostSDKVersion: SDKVersion,
      hostTheme: theme,
      isUniAppX: false,
      uniPlatform: "mp-weixin",
      uniCompileVersion: "5.13",
      uniCompilerVersion: "5.13",
      uniRuntimeVersion: "5.13"
    };
    try {
      if (typeof wx.getAccountInfoSync === "function") {
        parameters.packagename = wx.getAccountInfoSync().miniProgram.appId;
      }
    } catch (error) {
    }
    extend(toRes, parameters);
  }
};
const getWindowInfo = {
  returnValue: (fromRes, toRes) => {
    addSafeAreaInsets(fromRes, toRes);
    toRes = extend(toRes, {
      windowTop: 0,
      windowBottom: 0
    });
  }
};
const getAppAuthorizeSetting = {
  returnValue: function(fromRes, toRes) {
    const { locationReducedAccuracy } = fromRes;
    toRes.locationAccuracy = "unsupported";
    if (locationReducedAccuracy === true) {
      toRes.locationAccuracy = "reduced";
    } else if (locationReducedAccuracy === false) {
      toRes.locationAccuracy = "full";
    }
  }
};
const onError = {
  args(fromArgs) {
    const app = getApp({ allowDefault: true }) || {};
    if (!app.$vm) {
      if (!wx.$onErrorHandlers) {
        wx.$onErrorHandlers = [];
      }
      wx.$onErrorHandlers.push(fromArgs);
    } else {
      injectHook(ON_ERROR, fromArgs, app.$vm.$);
    }
  }
};
const offError = {
  args(fromArgs) {
    const app = getApp({ allowDefault: true }) || {};
    if (!app.$vm) {
      if (!wx.$onErrorHandlers) {
        return;
      }
      const index2 = wx.$onErrorHandlers.findIndex((fn) => fn === fromArgs);
      if (index2 !== -1) {
        wx.$onErrorHandlers.splice(index2, 1);
      }
    } else if (fromArgs.__weh) {
      const onErrors = app.$vm.$[ON_ERROR];
      if (onErrors) {
        const index2 = onErrors.indexOf(fromArgs.__weh);
        if (index2 > -1) {
          onErrors.splice(index2, 1);
        }
      }
    }
  }
};
const onSocketOpen = {
  args() {
    if (wx.__uni_console__) {
      if (wx.__uni_console_warned__) {
        return;
      }
      wx.__uni_console_warned__ = true;
      console.warn(`开发模式下小程序日志回显会使用 socket 连接，为了避免冲突，建议使用 SocketTask 的方式去管理 WebSocket 或手动关闭日志回显功能。[详情](https://uniapp.dcloud.net.cn/tutorial/run/mp-log.html)`);
    }
  }
};
const onSocketMessage = onSocketOpen;
const baseApis = {
  $on,
  $off,
  $once,
  $emit,
  upx2px,
  rpx2px: upx2px,
  interceptors,
  addInterceptor,
  removeInterceptor,
  onCreateVueApp,
  invokeCreateVueAppHook,
  getLocale,
  setLocale,
  onLocaleChange,
  getPushClientId: getPushClientId$1,
  onPushMessage,
  offPushMessage,
  invokePushCallback,
  __f__
};
function initUni(api, protocols2, platform = wx) {
  const wrapper = initWrapper(protocols2);
  const UniProxyHandlers = {
    get(target, key) {
      if (hasOwn(target, key)) {
        return target[key];
      }
      if (hasOwn(api, key)) {
        return promisify(key, api[key]);
      }
      if (hasOwn(baseApis, key)) {
        return promisify(key, baseApis[key]);
      }
      return promisify(key, wrapper(key, platform[key]));
    }
  };
  return new Proxy({}, UniProxyHandlers);
}
function initGetProvider(providers) {
  return function getProvider2({ service, success, fail, complete }) {
    let res;
    if (providers[service]) {
      res = {
        errMsg: "getProvider:ok",
        service,
        provider: providers[service]
      };
      isFunction(success) && success(res);
    } else {
      res = {
        errMsg: "getProvider:fail:服务[" + service + "]不存在"
      };
      isFunction(fail) && fail(res);
    }
    isFunction(complete) && complete(res);
  };
}
const objectKeys = [
  "qy",
  "env",
  "error",
  "version",
  "lanDebug",
  "cloud",
  "serviceMarket",
  "router",
  "worklet",
  "__webpack_require_UNI_MP_PLUGIN__"
];
const singlePageDisableKey = ["lanDebug", "router", "worklet"];
const launchOption = wx.getLaunchOptionsSync ? wx.getLaunchOptionsSync() : null;
function isWxKey(key) {
  if (launchOption && launchOption.scene === 1154 && singlePageDisableKey.includes(key)) {
    return false;
  }
  return objectKeys.indexOf(key) > -1 || typeof wx[key] === "function";
}
function initWx() {
  const newWx = {};
  for (const key in wx) {
    if (isWxKey(key)) {
      newWx[key] = wx[key];
    }
  }
  if (typeof globalThis !== "undefined" && typeof requireMiniProgram === "undefined") {
    globalThis.wx = newWx;
  }
  return newWx;
}
const mocks$1 = ["__route__", "__wxExparserNodeId__", "__wxWebviewId__"];
const getProvider = initGetProvider({
  oauth: ["weixin"],
  share: ["weixin"],
  payment: ["wxpay"],
  push: ["weixin"]
});
function initComponentMocks(component) {
  const res = /* @__PURE__ */ Object.create(null);
  mocks$1.forEach((name) => {
    res[name] = component[name];
  });
  return res;
}
function createSelectorQuery() {
  const query = wx$2.createSelectorQuery();
  const oldIn = query.in;
  query.in = function newIn(component) {
    if (component.$scope) {
      return oldIn.call(this, component.$scope);
    }
    return oldIn.call(this, initComponentMocks(component));
  };
  return query;
}
const wx$2 = initWx();
if (!wx$2.getAppBaseInfo || !wx$2.getAppBaseInfo()) {
  wx$2.getAppBaseInfo = wx$2.getSystemInfoSync;
}
if (!wx$2.getWindowInfo || !wx$2.getWindowInfo()) {
  wx$2.getWindowInfo = wx$2.getSystemInfoSync;
}
if (!wx$2.getDeviceInfo || !wx$2.getDeviceInfo()) {
  wx$2.getDeviceInfo = wx$2.getSystemInfoSync;
}
let baseInfo = wx$2.getAppBaseInfo && wx$2.getAppBaseInfo();
if (!baseInfo) {
  baseInfo = wx$2.getSystemInfoSync();
}
const host = baseInfo ? baseInfo.host : null;
const shareVideoMessage = host && host.env === "SAAASDK" ? wx$2.miniapp.shareVideoMessage : wx$2.shareVideoMessage;
var shims = /* @__PURE__ */ Object.freeze({
  __proto__: null,
  createSelectorQuery,
  getProvider,
  shareVideoMessage
});
const compressImage = {
  args(fromArgs, toArgs) {
    if (fromArgs.compressedHeight && !toArgs.compressHeight) {
      toArgs.compressHeight = fromArgs.compressedHeight;
    }
    if (fromArgs.compressedWidth && !toArgs.compressWidth) {
      toArgs.compressWidth = fromArgs.compressedWidth;
    }
  }
};
var protocols = /* @__PURE__ */ Object.freeze({
  __proto__: null,
  compressImage,
  getAppAuthorizeSetting,
  getAppBaseInfo,
  getDeviceInfo,
  getSystemInfo: getSystemInfo$1,
  getSystemInfoSync,
  getWindowInfo,
  offError,
  onError,
  onSocketMessage,
  onSocketOpen,
  previewImage,
  redirectTo,
  showActionSheet
});
const wx$1 = initWx();
var index = initUni(shims, protocols, wx$1);
function currentPageCaptureScreenshot(fullPage, callback) {
  var _a;
  const pages = getCurrentPages();
  const currentPage = pages[pages.length - 1];
  (_a = currentPage.vm) === null || _a === void 0 ? void 0 : _a.$viewToTempFilePath({
    wholeContent: fullPage,
    overwrite: true,
    success: (res) => {
      const fileManager = index.getFileSystemManager();
      fileManager.readFile({
        encoding: "base64",
        filePath: res.tempFilePath,
        success(readFileRes) {
          callback(readFileRes.data, "");
        },
        fail(err) {
          callback("", `captureScreenshot fail: ${JSON.stringify(err)}`);
        }
      });
    },
    fail: (err) => {
      callback("", `captureScreenshot fail: ${JSON.stringify(err)}`);
    }
  });
}
function initRuntimeSocket(hosts, port, id) {
  if (hosts == "" || port == "" || id == "")
    return Promise.resolve(null);
  return hosts.split(",").reduce((promise, host2) => {
    return promise.then((socket) => {
      if (socket != null)
        return Promise.resolve(socket);
      return tryConnectSocket(host2, port, id);
    });
  }, Promise.resolve(null));
}
const SOCKET_TIMEOUT = 500;
function tryConnectSocket(host2, port, id) {
  return new Promise((resolve, reject) => {
    const socket = index.connectSocket({
      url: `ws://${host2}:${port}/${id}`,
      multiple: true,
      // 支付宝小程序 是否开启多实例
      fail() {
        resolve(null);
      }
    });
    const timer = setTimeout(() => {
      socket.close({
        code: 1006,
        reason: "connect timeout"
      });
      resolve(null);
    }, SOCKET_TIMEOUT);
    socket.onOpen((e2) => {
      clearTimeout(timer);
      resolve(socket);
    });
    socket.onClose((e2) => {
      clearTimeout(timer);
      resolve(null);
    });
    socket.onError((e2) => {
      clearTimeout(timer);
      resolve(null);
    });
    socket.onMessage((result) => {
      const message = JSON.parse(result.data);
      if (message["type"] == "screencap") {
        const id2 = message["id"];
        currentPageCaptureScreenshot(message.fullPage, (base64, error) => {
          socket.send({
            data: JSON.stringify({
              id: id2,
              base64,
              error
            })
          });
        });
      }
      resolve(null);
    });
  });
}
const CONSOLE_TYPES = ["log", "warn", "error", "info", "debug"];
const originalConsole = /* @__PURE__ */ CONSOLE_TYPES.reduce((methods, type) => {
  methods[type] = console[type].bind(console);
  return methods;
}, {});
let sendError = null;
const errorQueue = /* @__PURE__ */ new Set();
const errorExtra = {};
function sendErrorMessages(errors) {
  if (sendError == null) {
    errors.forEach((error) => {
      errorQueue.add(error);
    });
    return;
  }
  const data = errors.map((err) => {
    if (typeof err === "string") {
      return err;
    }
    const isPromiseRejection = err && "promise" in err && "reason" in err;
    const prefix = isPromiseRejection ? "UnhandledPromiseRejection: " : "";
    if (isPromiseRejection) {
      err = err.reason;
    }
    if (err instanceof Error && err.stack) {
      if (err.message && !err.stack.includes(err.message)) {
        return `${prefix}${err.message}
${err.stack}`;
      }
      return `${prefix}${err.stack}`;
    }
    if (typeof err === "object" && err !== null) {
      try {
        return prefix + JSON.stringify(err);
      } catch (err2) {
        return prefix + String(err2);
      }
    }
    return prefix + String(err);
  }).filter(Boolean);
  if (data.length > 0) {
    sendError(JSON.stringify(Object.assign({
      type: "error",
      data
    }, errorExtra)));
  }
}
function setSendError(value, extra = {}) {
  sendError = value;
  Object.assign(errorExtra, extra);
  if (value != null && errorQueue.size > 0) {
    const errors = Array.from(errorQueue);
    errorQueue.clear();
    sendErrorMessages(errors);
  }
}
function initOnError() {
  function onError2(error) {
    try {
      if (typeof PromiseRejectionEvent !== "undefined" && error instanceof PromiseRejectionEvent && error.reason instanceof Error && error.reason.message && error.reason.message.includes(`Cannot create property 'errMsg' on string 'taskId`)) {
        return;
      }
      if (true) {
        originalConsole.error(error);
      }
      sendErrorMessages([error]);
    } catch (err) {
      originalConsole.error(err);
    }
  }
  if (typeof index !== "undefined") {
    if (typeof index.onError === "function") {
      index.onError(onError2);
    }
    if (typeof index.onUnhandledRejection === "function") {
      index.onUnhandledRejection(onError2);
    }
  }
  return function offError2() {
    if (typeof index !== "undefined") {
      if (typeof index.offError === "function") {
        index.offError(onError2);
      }
      if (typeof index.offUnhandledRejection === "function") {
        index.offUnhandledRejection(onError2);
      }
    }
  };
}
function formatMessage(type, args) {
  try {
    return {
      type,
      args: formatArgs(args)
    };
  } catch (e2) {
  }
  return {
    type,
    args: []
  };
}
function formatArgs(args) {
  return args.map((arg) => formatArg(arg));
}
function formatArg(arg, depth = 0) {
  if (depth >= 7) {
    return {
      type: "object",
      value: "[Maximum depth reached]"
    };
  }
  const type = typeof arg;
  switch (type) {
    case "string":
      return formatString(arg);
    case "number":
      return formatNumber(arg);
    case "boolean":
      return formatBoolean(arg);
    case "object":
      try {
        return formatObject(arg, depth);
      } catch (e2) {
        return {
          type: "object",
          value: {
            properties: []
          }
        };
      }
    case "undefined":
      return formatUndefined();
    case "function":
      return formatFunction(arg);
    case "symbol": {
      return formatSymbol(arg);
    }
    case "bigint":
      return formatBigInt(arg);
  }
}
function formatFunction(value) {
  return {
    type: "function",
    value: `function ${value.name}() {}`
  };
}
function formatUndefined() {
  return {
    type: "undefined"
  };
}
function formatBoolean(value) {
  return {
    type: "boolean",
    value: String(value)
  };
}
function formatNumber(value) {
  return {
    type: "number",
    value: String(value)
  };
}
function formatBigInt(value) {
  return {
    type: "bigint",
    value: String(value)
  };
}
function formatString(value) {
  return {
    type: "string",
    value
  };
}
function formatSymbol(value) {
  return {
    type: "symbol",
    value: value.description
  };
}
function formatObject(value, depth) {
  if (value === null) {
    return {
      type: "null"
    };
  }
  {
    if (isComponentPublicInstance(value)) {
      return formatComponentPublicInstance(value, depth);
    }
    if (isComponentInternalInstance(value)) {
      return formatComponentInternalInstance(value, depth);
    }
    if (isUniElement(value)) {
      return formatUniElement(value, depth);
    }
    if (isCSSStyleDeclaration(value)) {
      return formatCSSStyleDeclaration(value, depth);
    }
  }
  if (Array.isArray(value)) {
    return {
      type: "object",
      subType: "array",
      value: {
        properties: value.map((v, i) => formatArrayElement(v, i, depth + 1))
      }
    };
  }
  if (value instanceof Set) {
    return {
      type: "object",
      subType: "set",
      className: "Set",
      description: `Set(${value.size})`,
      value: {
        entries: Array.from(value).map((v) => formatSetEntry(v, depth + 1))
      }
    };
  }
  if (value instanceof Map) {
    return {
      type: "object",
      subType: "map",
      className: "Map",
      description: `Map(${value.size})`,
      value: {
        entries: Array.from(value.entries()).map((v) => formatMapEntry(v, depth + 1))
      }
    };
  }
  if (value instanceof Promise) {
    return {
      type: "object",
      subType: "promise",
      value: {
        properties: []
      }
    };
  }
  if (value instanceof RegExp) {
    return {
      type: "object",
      subType: "regexp",
      value: String(value),
      className: "Regexp"
    };
  }
  if (value instanceof Date) {
    return {
      type: "object",
      subType: "date",
      value: String(value),
      className: "Date"
    };
  }
  if (value instanceof Error) {
    return {
      type: "object",
      subType: "error",
      value: value.message || String(value),
      className: value.name || "Error"
    };
  }
  let className = void 0;
  {
    const constructor = value.constructor;
    if (constructor) {
      if (constructor.get$UTSMetadata$) {
        className = constructor.get$UTSMetadata$().name;
      }
    }
  }
  let entries = Object.entries(value);
  if (isHarmonyBuilderParams(value)) {
    entries = entries.filter(([key]) => key !== "modifier" && key !== "nodeContent");
  }
  return {
    type: "object",
    className,
    value: {
      properties: entries.map((entry) => formatObjectProperty(entry[0], entry[1], depth + 1))
    }
  };
}
function isHarmonyBuilderParams(value) {
  return value.modifier && value.modifier._attribute && value.nodeContent;
}
function isComponentPublicInstance(value) {
  return value.$ && isComponentInternalInstance(value.$);
}
function isComponentInternalInstance(value) {
  return value.type && value.uid != null && value.appContext;
}
function formatComponentPublicInstance(value, depth) {
  return {
    type: "object",
    className: "ComponentPublicInstance",
    value: {
      properties: Object.entries(value.$.type).map(([name, value2]) => formatObjectProperty(name, value2, depth + 1))
    }
  };
}
function formatComponentInternalInstance(value, depth) {
  return {
    type: "object",
    className: "ComponentInternalInstance",
    value: {
      properties: Object.entries(value.type).map(([name, value2]) => formatObjectProperty(name, value2, depth + 1))
    }
  };
}
function isUniElement(value) {
  return value.style && value.tagName != null && value.nodeName != null;
}
function formatUniElement(value, depth) {
  return {
    type: "object",
    // 非 x 没有 UniElement 的概念
    // className: 'UniElement',
    value: {
      properties: Object.entries(value).filter(([name]) => [
        "id",
        "tagName",
        "nodeName",
        "dataset",
        "offsetTop",
        "offsetLeft",
        "style"
      ].includes(name)).map(([name, value2]) => formatObjectProperty(name, value2, depth + 1))
    }
  };
}
function isCSSStyleDeclaration(value) {
  return typeof value.getPropertyValue === "function" && typeof value.setProperty === "function" && value.$styles;
}
function formatCSSStyleDeclaration(style, depth) {
  return {
    type: "object",
    value: {
      properties: Object.entries(style.$styles).map(([name, value]) => formatObjectProperty(name, value, depth + 1))
    }
  };
}
function formatObjectProperty(name, value, depth) {
  const result = formatArg(value, depth);
  result.name = name;
  return result;
}
function formatArrayElement(value, index2, depth) {
  const result = formatArg(value, depth);
  result.name = `${index2}`;
  return result;
}
function formatSetEntry(value, depth) {
  return {
    value: formatArg(value, depth)
  };
}
function formatMapEntry(value, depth) {
  return {
    key: formatArg(value[0], depth),
    value: formatArg(value[1], depth)
  };
}
let sendConsole = null;
const messageQueue = [];
const messageExtra = {};
const EXCEPTION_BEGIN_MARK = "---BEGIN:EXCEPTION---";
const EXCEPTION_END_MARK = "---END:EXCEPTION---";
function sendConsoleMessages(messages) {
  if (sendConsole == null) {
    messageQueue.push(...messages);
    return;
  }
  sendConsole(JSON.stringify(Object.assign({
    type: "console",
    data: messages
  }, messageExtra)));
}
function setSendConsole(value, extra = {}) {
  sendConsole = value;
  Object.assign(messageExtra, extra);
  if (value != null && messageQueue.length > 0) {
    const messages = messageQueue.slice();
    messageQueue.length = 0;
    sendConsoleMessages(messages);
  }
}
const atFileRegex = /^\s*at\s+[\w/./-]+:\d+$/;
function rewriteConsole() {
  function wrapConsole(type) {
    return function(...args) {
      {
        const originalArgs = [...args];
        if (originalArgs.length) {
          const maybeAtFile = originalArgs[originalArgs.length - 1];
          if (typeof maybeAtFile === "string" && atFileRegex.test(maybeAtFile)) {
            originalArgs.pop();
          }
        }
        originalConsole[type](...originalArgs);
      }
      if (type === "error" && args.length === 1) {
        const arg = args[0];
        if (typeof arg === "string" && arg.startsWith(EXCEPTION_BEGIN_MARK)) {
          const startIndex = EXCEPTION_BEGIN_MARK.length;
          const endIndex = arg.length - EXCEPTION_END_MARK.length;
          sendErrorMessages([arg.slice(startIndex, endIndex)]);
          return;
        } else if (arg instanceof Error) {
          sendErrorMessages([arg]);
          return;
        }
      }
      sendConsoleMessages([formatMessage(type, args)]);
    };
  }
  if (isConsoleWritable()) {
    CONSOLE_TYPES.forEach((type) => {
      console[type] = wrapConsole(type);
    });
    return function restoreConsole() {
      CONSOLE_TYPES.forEach((type) => {
        console[type] = originalConsole[type];
      });
    };
  } else {
    {
      if (typeof index !== "undefined" && index.__f__) {
        const oldLog = index.__f__;
        if (oldLog) {
          index.__f__ = function(...args) {
            const [type, filename, ...rest] = args;
            oldLog(type, "", ...rest);
            sendConsoleMessages([formatMessage(type, [...rest, filename])]);
          };
          return function restoreConsole() {
            index.__f__ = oldLog;
          };
        }
      }
    }
  }
  return function restoreConsole() {
  };
}
function isConsoleWritable() {
  const value = console.log;
  const sym = Symbol();
  try {
    console.log = sym;
  } catch (ex) {
    return false;
  }
  const isWritable = console.log === sym;
  console.log = value;
  return isWritable;
}
function initRuntimeSocketService() {
  const hosts = "192.168.0.100,192.168.253.1,192.168.150.1,127.0.0.1,172.24.16.1,172.23.224.1";
  const port = "8090";
  const id = "mp-weixin_8HGDQF";
  const lazy = typeof swan !== "undefined";
  let restoreError = lazy ? () => {
  } : initOnError();
  let restoreConsole = lazy ? () => {
  } : rewriteConsole();
  return Promise.resolve().then(() => {
    if (lazy) {
      restoreError = initOnError();
      restoreConsole = rewriteConsole();
    }
    return initRuntimeSocket(hosts, port, id).then((socket) => {
      if (!socket) {
        restoreError();
        restoreConsole();
        originalConsole.error(wrapError("开发模式下日志通道建立 socket 连接失败。"));
        {
          originalConsole.error(wrapError("小程序平台，请勾选不校验合法域名配置。"));
        }
        originalConsole.error(wrapError("如果是运行到真机，请确认手机与电脑处于同一网络。"));
        return false;
      }
      {
        initMiniProgramGlobalFlag();
      }
      socket.onClose(() => {
        {
          originalConsole.error(wrapError("开发模式下日志通道 socket 连接关闭，请在 HBuilderX 中重新运行。"));
        }
        restoreError();
        restoreConsole();
      });
      setSendConsole((data) => {
        socket.send({
          data
        });
      });
      setSendError((data) => {
        socket.send({
          data
        });
      });
      return true;
    });
  });
}
const ERROR_CHAR = "‌";
function wrapError(error) {
  return `${ERROR_CHAR}${error}${ERROR_CHAR}`;
}
function initMiniProgramGlobalFlag() {
  if (typeof wx$1 !== "undefined") {
    wx$1.__uni_console__ = true;
  } else if (typeof my !== "undefined") {
    my.__uni_console__ = true;
  } else if (typeof tt !== "undefined") {
    tt.__uni_console__ = true;
  } else if (typeof swan !== "undefined") {
    swan.__uni_console__ = true;
  } else if (typeof qq !== "undefined") {
    qq.__uni_console__ = true;
  } else if (typeof ks !== "undefined") {
    ks.__uni_console__ = true;
  } else if (typeof jd !== "undefined") {
    jd.__uni_console__ = true;
  } else if (typeof xhs !== "undefined") {
    xhs.__uni_console__ = true;
  } else if (typeof has !== "undefined") {
    has.__uni_console__ = true;
  } else if (typeof qa !== "undefined") {
    qa.__uni_console__ = true;
  }
}
initRuntimeSocketService();
const _export_sfc = (sfc, props) => {
  const target = sfc.__vccOpts || sfc;
  for (const [key, val] of props) {
    target[key] = val;
  }
  return target;
};
function initVueIds(vueIds, mpInstance) {
  if (!vueIds) {
    return;
  }
  const ids = vueIds.split(",");
  const len = ids.length;
  if (len === 1) {
    mpInstance._$vueId = ids[0];
  } else if (len === 2) {
    mpInstance._$vueId = ids[0];
    mpInstance._$vuePid = ids[1];
  }
}
const EXTRAS = ["externalClasses"];
function initExtraOptions(miniProgramComponentOptions, vueOptions) {
  EXTRAS.forEach((name) => {
    if (hasOwn(vueOptions, name)) {
      miniProgramComponentOptions[name] = vueOptions[name];
    }
  });
}
const WORKLET_RE = /_(.*)_worklet_factory_/;
function initWorkletMethods(mpMethods, vueMethods) {
  if (vueMethods) {
    Object.keys(vueMethods).forEach((name) => {
      const matches = name.match(WORKLET_RE);
      if (matches) {
        const workletName = matches[1];
        mpMethods[name] = vueMethods[name];
        mpMethods[workletName] = vueMethods[workletName];
      }
    });
  }
}
function initWxsCallMethods(methods, wxsCallMethods) {
  if (!isArray(wxsCallMethods)) {
    return;
  }
  wxsCallMethods.forEach((callMethod) => {
    methods[callMethod] = function(args) {
      return this.$vm[callMethod](args);
    };
  });
}
function selectAllComponents(mpInstance, selector, $refs) {
  const components = mpInstance.selectAllComponents(selector);
  components.forEach((component) => {
    const ref2 = component.properties.uR;
    $refs[ref2] = component.$vm || component;
  });
}
function initRefs(instance2, mpInstance) {
  Object.defineProperty(instance2, "refs", {
    get() {
      const $refs = {};
      selectAllComponents(mpInstance, ".r", $refs);
      const forComponents = mpInstance.selectAllComponents(".r-i-f");
      forComponents.forEach((component) => {
        const ref2 = component.properties.uR;
        if (!ref2) {
          return;
        }
        if (!$refs[ref2]) {
          $refs[ref2] = [];
        }
        $refs[ref2].push(component.$vm || component);
      });
      return $refs;
    }
  });
}
function findVmByVueId(instance2, vuePid) {
  const $children = instance2.$children;
  for (let i = $children.length - 1; i >= 0; i--) {
    const childVm = $children[i];
    if (childVm.$scope._$vueId === vuePid) {
      return childVm;
    }
  }
  let parentVm;
  for (let i = $children.length - 1; i >= 0; i--) {
    parentVm = findVmByVueId($children[i], vuePid);
    if (parentVm) {
      return parentVm;
    }
  }
}
function getLocaleLanguage() {
  var _a;
  let localeLanguage = "";
  {
    const appBaseInfo = ((_a = wx.getAppBaseInfo) === null || _a === void 0 ? void 0 : _a.call(wx)) || wx.getSystemInfoSync();
    const language = appBaseInfo && appBaseInfo.language ? appBaseInfo.language : LOCALE_EN;
    localeLanguage = normalizeLocale(language) || LOCALE_EN;
  }
  return localeLanguage;
}
const MP_METHODS = [
  "createSelectorQuery",
  "createIntersectionObserver",
  "selectAllComponents",
  "selectComponent"
];
function createEmitFn(oldEmit, ctx) {
  return function emit2(event, ...args) {
    const scope = ctx.$scope;
    if (scope && event) {
      const detail = { __args__: args };
      {
        scope.triggerEvent(event, detail);
      }
    }
    return oldEmit.apply(this, [event, ...args]);
  };
}
function initBaseInstance(instance2, options) {
  const ctx = instance2.ctx;
  ctx.mpType = options.mpType;
  ctx.$mpType = options.mpType;
  ctx.$mpPlatform = "mp-weixin";
  ctx.$scope = options.mpInstance;
  {
    Object.defineProperties(ctx, {
      // only id
      [VIRTUAL_HOST_ID]: {
        get() {
          const id = this.$scope.data[VIRTUAL_HOST_ID];
          return id === void 0 ? "" : id;
        }
      }
    });
  }
  ctx.$mp = {};
  {
    ctx._self = {};
  }
  instance2.slots = {};
  if (isArray(options.slots) && options.slots.length) {
    options.slots.forEach((name) => {
      instance2.slots[name] = true;
    });
    if (instance2.slots[SLOT_DEFAULT_NAME]) {
      instance2.slots.default = true;
    }
  }
  ctx.getOpenerEventChannel = function() {
    {
      return options.mpInstance.getOpenerEventChannel();
    }
  };
  ctx.$hasHook = hasHook;
  ctx.$callHook = callHook;
  instance2.emit = createEmitFn(instance2.emit, ctx);
}
function initComponentInstance(instance2, options) {
  initBaseInstance(instance2, options);
  const ctx = instance2.ctx;
  MP_METHODS.forEach((method) => {
    ctx[method] = function(...args) {
      const mpInstance = ctx.$scope;
      if (mpInstance && mpInstance[method]) {
        return mpInstance[method].apply(mpInstance, args);
      }
    };
  });
}
function initMocks(instance2, mpInstance, mocks2) {
  const ctx = instance2.ctx;
  mocks2.forEach((mock) => {
    if (hasOwn(mpInstance, mock)) {
      instance2[mock] = ctx[mock] = mpInstance[mock];
    }
  });
}
function hasHook(name) {
  const hooks = this.$[name];
  if (hooks && hooks.length) {
    return true;
  }
  return false;
}
function callHook(name, args) {
  if (name === "mounted") {
    callHook.call(this, "bm");
    this.$.isMounted = true;
    name = "m";
  }
  const hooks = this.$[name];
  return hooks && invokeArrayFns(hooks, args);
}
const PAGE_INIT_HOOKS = [
  ON_LOAD,
  ON_SHOW,
  ON_HIDE,
  ON_UNLOAD,
  ON_RESIZE,
  ON_TAB_ITEM_TAP,
  ON_REACH_BOTTOM,
  ON_PULL_DOWN_REFRESH,
  ON_ADD_TO_FAVORITES
  // 'onReady', // lifetimes.ready
  // 'onPageScroll', // 影响性能，开发者手动注册
  // 'onShareTimeline', // 右上角菜单，开发者手动注册
  // 'onShareAppMessage' // 右上角菜单，开发者手动注册
];
function findHooks(vueOptions, hooks = /* @__PURE__ */ new Set()) {
  if (vueOptions) {
    Object.keys(vueOptions).forEach((name) => {
      if (isUniLifecycleHook(name, vueOptions[name])) {
        hooks.add(name);
      }
    });
    {
      const { extends: extendsOptions, mixins } = vueOptions;
      if (mixins) {
        mixins.forEach((mixin) => findHooks(mixin, hooks));
      }
      if (extendsOptions) {
        findHooks(extendsOptions, hooks);
      }
    }
  }
  return hooks;
}
function initHook(mpOptions, hook, excludes) {
  if (excludes.indexOf(hook) === -1 && !hasOwn(mpOptions, hook)) {
    mpOptions[hook] = function(args) {
      return this.$vm && this.$vm.$callHook(hook, args);
    };
  }
}
const EXCLUDE_HOOKS = [ON_READY];
function initHooks(mpOptions, hooks, excludes = EXCLUDE_HOOKS) {
  hooks.forEach((hook) => initHook(mpOptions, hook, excludes));
}
function initUnknownHooks(mpOptions, vueOptions, excludes = EXCLUDE_HOOKS) {
  findHooks(vueOptions).forEach((hook) => initHook(mpOptions, hook, excludes));
}
function initRuntimeHooks(mpOptions, runtimeHooks) {
  if (!runtimeHooks) {
    return;
  }
  const hooks = Object.keys(MINI_PROGRAM_PAGE_RUNTIME_HOOKS);
  hooks.forEach((hook) => {
    if (runtimeHooks & MINI_PROGRAM_PAGE_RUNTIME_HOOKS[hook]) {
      initHook(mpOptions, hook, []);
    }
  });
}
const findMixinRuntimeHooks = /* @__PURE__ */ once(() => {
  const runtimeHooks = [];
  const app = isFunction(getApp) && getApp({ allowDefault: true });
  if (app && app.$vm && app.$vm.$) {
    const mixins = app.$vm.$.appContext.mixins;
    if (isArray(mixins)) {
      const hooks = Object.keys(MINI_PROGRAM_PAGE_RUNTIME_HOOKS);
      mixins.forEach((mixin) => {
        hooks.forEach((hook) => {
          if (hasOwn(mixin, hook) && !runtimeHooks.includes(hook)) {
            runtimeHooks.push(hook);
          }
        });
      });
    }
  }
  return runtimeHooks;
});
function initMixinRuntimeHooks(mpOptions) {
  initHooks(mpOptions, findMixinRuntimeHooks());
}
const HOOKS = [
  ON_SHOW,
  ON_HIDE,
  ON_ERROR,
  ON_THEME_CHANGE,
  ON_PAGE_NOT_FOUND,
  ON_UNHANDLE_REJECTION
];
function parseApp(instance2, parseAppOptions) {
  const internalInstance = instance2.$;
  const appOptions = {
    globalData: instance2.$options && instance2.$options.globalData || {},
    $vm: instance2,
    // mp-alipay 组件 data 初始化比 onLaunch 早，提前挂载
    onLaunch(options) {
      this.$vm = instance2;
      const ctx = internalInstance.ctx;
      if (this.$vm && ctx.$scope && ctx.$callHook) {
        return;
      }
      initBaseInstance(internalInstance, {
        mpType: "app",
        mpInstance: this,
        slots: []
      });
      ctx.globalData = this.globalData;
      instance2.$callHook(ON_LAUNCH, options);
    }
  };
  const onErrorHandlers = wx.$onErrorHandlers;
  if (onErrorHandlers) {
    onErrorHandlers.forEach((fn) => {
      injectHook(ON_ERROR, fn, internalInstance);
    });
    onErrorHandlers.length = 0;
  }
  initLocale(instance2);
  const vueOptions = instance2.$.type;
  initHooks(appOptions, HOOKS);
  initUnknownHooks(appOptions, vueOptions);
  {
    const methods = vueOptions.methods;
    methods && extend(appOptions, methods);
  }
  return appOptions;
}
function initCreateApp(parseAppOptions) {
  return function createApp2(vm) {
    return App(parseApp(vm));
  };
}
function initCreateSubpackageApp(parseAppOptions) {
  return function createApp2(vm) {
    const appOptions = parseApp(vm);
    const app = isFunction(getApp) && getApp({
      allowDefault: true
    });
    if (!app)
      return;
    vm.$.ctx.$scope = app;
    const globalData = app.globalData;
    if (globalData) {
      Object.keys(appOptions.globalData).forEach((name) => {
        if (!hasOwn(globalData, name)) {
          globalData[name] = appOptions.globalData[name];
        }
      });
    }
    Object.keys(appOptions).forEach((name) => {
      if (!hasOwn(app, name)) {
        app[name] = appOptions[name];
      }
    });
    initAppLifecycle(appOptions, vm);
  };
}
function initAppLifecycle(appOptions, vm) {
  if (isFunction(appOptions.onLaunch)) {
    const args = wx.getLaunchOptionsSync && wx.getLaunchOptionsSync();
    appOptions.onLaunch(args);
  }
  if (isFunction(appOptions.onShow) && wx.onAppShow) {
    wx.onAppShow((args) => {
      vm.$callHook("onShow", args);
    });
  }
  if (isFunction(appOptions.onHide) && wx.onAppHide) {
    wx.onAppHide((args) => {
      vm.$callHook("onHide", args);
    });
  }
}
function initLocale(appVm) {
  const locale = ref(getLocaleLanguage());
  Object.defineProperty(appVm, "$locale", {
    get() {
      return locale.value;
    },
    set(v) {
      locale.value = v;
    }
  });
}
const builtInProps = [
  // 百度小程序,快手小程序自定义组件不支持绑定动态事件，动态dataset，故通过props传递事件信息
  // event-opts
  "eO",
  // 组件 ref
  "uR",
  // 组件 ref-in-for
  "uRIF",
  // 组件 id
  "uI",
  // 组件类型 m: 小程序组件
  "uT",
  // 组件 props
  "uP",
  // 小程序不能直接定义 $slots 的 props，所以通过 vueSlots 转换到 $slots
  "uS"
];
function initDefaultProps(options, isBehavior = false) {
  const properties = {};
  if (!isBehavior) {
    let observerSlots = function(newVal) {
      const $slots = /* @__PURE__ */ Object.create(null);
      newVal && newVal.forEach((slotName) => {
        $slots[slotName] = true;
      });
      this.setData({
        $slots
      });
    };
    builtInProps.forEach((name) => {
      properties[name] = {
        type: null,
        value: ""
      };
    });
    properties.uS = {
      type: null,
      value: []
    };
    {
      properties.uS.observer = observerSlots;
    }
  }
  if (options.behaviors) {
    if (options.behaviors.includes("wx://form-field")) {
      if (!options.properties || !options.properties.name) {
        properties.name = {
          type: null,
          value: ""
        };
      }
      if (!options.properties || !options.properties.value) {
        properties.value = {
          type: null,
          value: ""
        };
      }
    }
  }
  return properties;
}
function initVirtualHostProps(options) {
  const properties = {};
  {
    if (options && options.virtualHost) {
      properties[VIRTUAL_HOST_STYLE] = {
        type: null,
        value: ""
      };
      properties[VIRTUAL_HOST_CLASS] = {
        type: null,
        value: ""
      };
      properties[VIRTUAL_HOST_HIDDEN] = {
        type: null,
        value: ""
      };
      properties[VIRTUAL_HOST_ID] = {
        type: null,
        value: ""
      };
    }
  }
  return properties;
}
function initProps(mpComponentOptions) {
  if (!mpComponentOptions.properties) {
    mpComponentOptions.properties = {};
  }
  extend(mpComponentOptions.properties, initDefaultProps(mpComponentOptions), initVirtualHostProps(mpComponentOptions.options));
}
const PROP_TYPES = [String, Number, Boolean, Object, Array, null];
function parsePropType(type, defaultValue) {
  if (isArray(type) && type.length === 1) {
    return type[0];
  }
  return type;
}
function normalizePropType(type, defaultValue) {
  const res = parsePropType(type);
  return PROP_TYPES.indexOf(res) !== -1 ? res : null;
}
function initPageProps({ properties }, rawProps) {
  if (isArray(rawProps)) {
    rawProps.forEach((key) => {
      properties[key] = {
        type: String,
        value: ""
      };
    });
  } else if (isPlainObject$1(rawProps)) {
    Object.keys(rawProps).forEach((key) => {
      const opts = rawProps[key];
      if (isPlainObject$1(opts)) {
        let value = opts.default;
        if (isFunction(value)) {
          value = value();
        }
        const type = opts.type;
        opts.type = normalizePropType(type);
        properties[key] = {
          type: opts.type,
          value
        };
      } else {
        properties[key] = {
          type: normalizePropType(opts)
        };
      }
    });
  }
}
function findPropsData(properties, isPage2) {
  return (isPage2 ? findPagePropsData(properties) : findComponentPropsData(resolvePropValue(properties.uP))) || {};
}
function findPagePropsData(properties) {
  const propsData = {};
  if (isPlainObject$1(properties)) {
    Object.keys(properties).forEach((name) => {
      if (builtInProps.indexOf(name) === -1) {
        propsData[name] = resolvePropValue(properties[name]);
      }
    });
  }
  return propsData;
}
function initFormField(vm) {
  const vueOptions = vm.$options;
  if (isArray(vueOptions.behaviors) && vueOptions.behaviors.includes("uni://form-field")) {
    vm.$watch("modelValue", () => {
      vm.$scope && vm.$scope.setData({
        name: vm.name,
        value: vm.modelValue
      });
    }, {
      immediate: true
    });
  }
}
function resolvePropValue(prop) {
  return prop;
}
function initData(_) {
  return {};
}
function initPropsObserver(componentOptions) {
  const observe = function observe2() {
    const up = this.properties.uP;
    if (!up) {
      return;
    }
    if (this.$vm) {
      updateComponentProps(resolvePropValue(up), this.$vm.$);
    } else if (resolvePropValue(this.properties.uT) === "m") {
      updateMiniProgramComponentProperties(resolvePropValue(up), this);
    } else
      ;
  };
  {
    if (!componentOptions.observers) {
      componentOptions.observers = {};
    }
    componentOptions.observers.uP = observe;
  }
}
function updateMiniProgramComponentProperties(up, mpInstance) {
  const prevProps = mpInstance.properties;
  const nextProps = findComponentPropsData(up) || {};
  if (hasPropsChanged(prevProps, nextProps, false)) {
    mpInstance.setData(nextProps);
  }
}
function updateComponentProps(up, instance2) {
  const prevProps = toRaw(instance2.props);
  const nextProps = findComponentPropsData(up) || {};
  if (hasPropsChanged(prevProps, nextProps)) {
    updateProps(instance2, nextProps, prevProps, false);
    if (hasQueueJob(instance2.update)) {
      invalidateJob(instance2.update);
    }
    {
      instance2.update();
    }
  }
}
function hasPropsChanged(prevProps, nextProps, checkLen = true) {
  const nextKeys = Object.keys(nextProps);
  if (checkLen && nextKeys.length !== Object.keys(prevProps).length) {
    return true;
  }
  for (let i = 0; i < nextKeys.length; i++) {
    const key = nextKeys[i];
    if (nextProps[key] !== prevProps[key]) {
      return true;
    }
  }
  return false;
}
function initBehaviors(vueOptions) {
  const vueBehaviors = vueOptions.behaviors;
  let vueProps = vueOptions.props;
  if (!vueProps) {
    vueOptions.props = vueProps = [];
  }
  const behaviors = [];
  if (isArray(vueBehaviors)) {
    vueBehaviors.forEach((behavior) => {
      behaviors.push(behavior.replace("uni://", "wx://"));
      if (behavior === "uni://form-field") {
        if (isArray(vueProps)) {
          vueProps.push("name");
          vueProps.push("modelValue");
        } else {
          vueProps.name = {
            type: String,
            default: ""
          };
          vueProps.modelValue = {
            type: [String, Number, Boolean, Array, Object, Date],
            default: ""
          };
        }
      }
    });
  }
  return behaviors;
}
function applyOptions(componentOptions, vueOptions) {
  componentOptions.data = initData();
  componentOptions.behaviors = initBehaviors(vueOptions);
}
function parseComponent(vueOptions, { parse, mocks: mocks2, isPage: isPage2, isPageInProject, initRelation: initRelation2, handleLink: handleLink2, initLifetimes: initLifetimes2 }) {
  vueOptions = vueOptions.default || vueOptions;
  const options = {
    multipleSlots: true,
    // styleIsolation: 'apply-shared',
    addGlobalClass: true,
    pureDataPattern: /^uP$/
  };
  if (isArray(vueOptions.mixins)) {
    vueOptions.mixins.forEach((item) => {
      if (isObject(item.options)) {
        extend(options, item.options);
      }
    });
  }
  if (vueOptions.options) {
    extend(options, vueOptions.options);
  }
  const mpComponentOptions = {
    options,
    lifetimes: initLifetimes2({ mocks: mocks2, isPage: isPage2, initRelation: initRelation2, vueOptions }),
    pageLifetimes: {
      show() {
        this.$vm && this.$vm.$callHook("onPageShow");
      },
      hide() {
        this.$vm && this.$vm.$callHook("onPageHide");
      },
      resize(size2) {
        this.$vm && this.$vm.$callHook("onPageResize", size2);
      }
    },
    methods: {
      __l: handleLink2
    }
  };
  {
    applyOptions(mpComponentOptions, vueOptions);
  }
  initProps(mpComponentOptions);
  initPropsObserver(mpComponentOptions);
  initExtraOptions(mpComponentOptions, vueOptions);
  initWxsCallMethods(mpComponentOptions.methods, vueOptions.wxsCallMethods);
  {
    initWorkletMethods(mpComponentOptions.methods, vueOptions.methods);
  }
  if (parse) {
    parse(mpComponentOptions, { handleLink: handleLink2 });
  }
  return mpComponentOptions;
}
function initCreateComponent(parseOptions2) {
  return function createComponent2(vueComponentOptions) {
    return Component(parseComponent(vueComponentOptions, parseOptions2));
  };
}
let $createComponentFn;
let $destroyComponentFn;
function getAppVm() {
  return getApp().$vm;
}
function $createComponent(initialVNode, options) {
  if (!$createComponentFn) {
    $createComponentFn = getAppVm().$createComponent;
  }
  const proxy = $createComponentFn(initialVNode, options);
  return getExposeProxy(proxy.$) || proxy;
}
function $destroyComponent(instance2) {
  if (!$destroyComponentFn) {
    $destroyComponentFn = getAppVm().$destroyComponent;
  }
  return $destroyComponentFn(instance2);
}
function parsePage(vueOptions, parseOptions2) {
  const { parse, mocks: mocks2, isPage: isPage2, initRelation: initRelation2, handleLink: handleLink2, initLifetimes: initLifetimes2 } = parseOptions2;
  const miniProgramPageOptions = parseComponent(vueOptions, {
    mocks: mocks2,
    isPage: isPage2,
    isPageInProject: true,
    initRelation: initRelation2,
    handleLink: handleLink2,
    initLifetimes: initLifetimes2
  });
  initPageProps(miniProgramPageOptions, (vueOptions.default || vueOptions).props);
  const methods = miniProgramPageOptions.methods;
  methods.onLoad = function(query) {
    {
      this.options = query;
    }
    this.$page = {
      fullPath: addLeadingSlash(this.route + stringifyQuery(query))
    };
    return this.$vm && this.$vm.$callHook(ON_LOAD, query);
  };
  initHooks(methods, PAGE_INIT_HOOKS);
  {
    initUnknownHooks(methods, vueOptions);
  }
  initRuntimeHooks(methods, vueOptions.__runtimeHooks);
  initMixinRuntimeHooks(methods);
  parse && parse(miniProgramPageOptions, { handleLink: handleLink2 });
  return miniProgramPageOptions;
}
function initCreatePage(parseOptions2) {
  return function createPage2(vuePageOptions) {
    return Component(parsePage(vuePageOptions, parseOptions2));
  };
}
function initCreatePluginApp(parseAppOptions) {
  return function createApp2(vm) {
    initAppLifecycle(parseApp(vm), vm);
  };
}
const MPPage = Page;
const MPComponent = Component;
function initTriggerEvent(mpInstance) {
  const oldTriggerEvent = mpInstance.triggerEvent;
  const newTriggerEvent = function(event, ...args) {
    return oldTriggerEvent.apply(mpInstance, [
      customizeEvent(event),
      ...args
    ]);
  };
  try {
    mpInstance.triggerEvent = newTriggerEvent;
  } catch (error) {
    mpInstance._triggerEvent = newTriggerEvent;
  }
}
function initMiniProgramHook(name, options, isComponent) {
  const oldHook = options[name];
  if (!oldHook) {
    options[name] = function() {
      initTriggerEvent(this);
    };
  } else {
    options[name] = function(...args) {
      initTriggerEvent(this);
      return oldHook.apply(this, args);
    };
  }
}
Page = function(options) {
  initMiniProgramHook(ON_LOAD, options);
  return MPPage(options);
};
Component = function(options) {
  initMiniProgramHook("created", options);
  const isVueComponent = options.properties && options.properties.uP;
  if (!isVueComponent) {
    initProps(options);
    initPropsObserver(options);
  }
  return MPComponent(options);
};
function initLifetimes({ mocks: mocks2, isPage: isPage2, initRelation: initRelation2, vueOptions }) {
  return {
    attached() {
      let properties = this.properties;
      initVueIds(properties.uI, this);
      const relationOptions = {
        vuePid: this._$vuePid
      };
      initRelation2(this, relationOptions);
      const mpInstance = this;
      const isMiniProgramPage = isPage2(mpInstance);
      let propsData = properties;
      this.$vm = $createComponent({
        type: vueOptions,
        props: findPropsData(propsData, isMiniProgramPage)
      }, {
        mpType: isMiniProgramPage ? "page" : "component",
        mpInstance,
        slots: properties.uS || {},
        // vueSlots
        parentComponent: relationOptions.parent && relationOptions.parent.$,
        onBeforeSetup(instance2, options) {
          initRefs(instance2, mpInstance);
          initMocks(instance2, mpInstance, mocks2);
          initComponentInstance(instance2, options);
        }
      });
      if (!isMiniProgramPage) {
        initFormField(this.$vm);
      }
    },
    ready() {
      if (this.$vm) {
        {
          this.$vm.$callHook("mounted");
          this.$vm.$callHook(ON_READY);
        }
      }
    },
    detached() {
      if (this.$vm) {
        pruneComponentPropsCache(this.$vm.$.uid);
        $destroyComponent(this.$vm);
      }
    }
  };
}
const mocks = ["__route__", "__wxExparserNodeId__", "__wxWebviewId__"];
function isPage(mpInstance) {
  return !!mpInstance.route;
}
function initRelation(mpInstance, detail) {
  mpInstance.triggerEvent("__l", detail);
}
function handleLink(event) {
  const detail = event.detail || event.value;
  const vuePid = detail.vuePid;
  let parentVm;
  if (vuePid) {
    parentVm = findVmByVueId(this.$vm, vuePid);
  }
  if (!parentVm) {
    parentVm = this.$vm;
  }
  detail.parent = parentVm;
}
var parseOptions = /* @__PURE__ */ Object.freeze({
  __proto__: null,
  handleLink,
  initLifetimes,
  initRelation,
  isPage,
  mocks
});
const createApp = initCreateApp();
const createPage = initCreatePage(parseOptions);
const createComponent = initCreateComponent(parseOptions);
const createPluginApp = initCreatePluginApp();
const createSubpackageApp = initCreateSubpackageApp();
{
  wx.createApp = global.createApp = createApp;
  wx.createPage = createPage;
  wx.createComponent = createComponent;
  wx.createPluginApp = global.createPluginApp = createPluginApp;
  wx.createSubpackageApp = global.createSubpackageApp = createSubpackageApp;
}
const createLifeCycleHook = (lifecycle, flag = 0) => (hook, target = getCurrentInstance()) => {
  !isInSSRComponentSetup && injectHook(lifecycle, hook, target);
};
const onShow = /* @__PURE__ */ createLifeCycleHook(
  ON_SHOW,
  1 | 2
  /* HookFlags.PAGE */
);
const onHide = /* @__PURE__ */ createLifeCycleHook(
  ON_HIDE,
  1 | 2
  /* HookFlags.PAGE */
);
const onLaunch = /* @__PURE__ */ createLifeCycleHook(
  ON_LAUNCH,
  1
  /* HookFlags.APP */
);
var isVue2 = false;
function set$1(target, key, val) {
  if (Array.isArray(target)) {
    target.length = Math.max(target.length, key);
    target.splice(key, 1, val);
    return val;
  }
  target[key] = val;
  return val;
}
function del(target, key) {
  if (Array.isArray(target)) {
    target.splice(key, 1);
    return;
  }
  delete target[key];
}
/*!
 * pinia v2.1.7
 * (c) 2023 Eduardo San Martin Morote
 * @license MIT
 */
let activePinia;
const setActivePinia = (pinia) => activePinia = pinia;
const piniaSymbol = Symbol("pinia");
function isPlainObject(o2) {
  return o2 && typeof o2 === "object" && Object.prototype.toString.call(o2) === "[object Object]" && typeof o2.toJSON !== "function";
}
var MutationType;
(function(MutationType2) {
  MutationType2["direct"] = "direct";
  MutationType2["patchObject"] = "patch object";
  MutationType2["patchFunction"] = "patch function";
})(MutationType || (MutationType = {}));
const IS_CLIENT = typeof window !== "undefined";
const USE_DEVTOOLS = IS_CLIENT;
const componentStateTypes = [];
const getStoreType = (id) => "🍍 " + id;
function addStoreToDevtools(app, store) {
  if (!componentStateTypes.includes(getStoreType(store.$id))) {
    componentStateTypes.push(getStoreType(store.$id));
  }
}
function patchActionForGrouping(store, actionNames, wrapWithProxy) {
  const actions = actionNames.reduce((storeActions, actionName) => {
    storeActions[actionName] = toRaw(store)[actionName];
    return storeActions;
  }, {});
  for (const actionName in actions) {
    store[actionName] = function() {
      const trackedStore = wrapWithProxy ? new Proxy(store, {
        get(...args) {
          return Reflect.get(...args);
        },
        set(...args) {
          return Reflect.set(...args);
        }
      }) : store;
      const retValue = actions[actionName].apply(trackedStore, arguments);
      return retValue;
    };
  }
}
function devtoolsPlugin({ app, store, options }) {
  if (store.$id.startsWith("__hot:")) {
    return;
  }
  store._isOptionsAPI = !!options.state;
  patchActionForGrouping(store, Object.keys(options.actions), store._isOptionsAPI);
  const originalHotUpdate = store._hotUpdate;
  toRaw(store)._hotUpdate = function(newStore) {
    originalHotUpdate.apply(this, arguments);
    patchActionForGrouping(store, Object.keys(newStore._hmrPayload.actions), !!store._isOptionsAPI);
  };
  addStoreToDevtools(
    app,
    // FIXME: is there a way to allow the assignment from Store<Id, S, G, A> to StoreGeneric?
    store
  );
}
function createPinia() {
  const scope = effectScope(true);
  const state2 = scope.run(() => ref({}));
  let _p = [];
  let toBeInstalled = [];
  const pinia = markRaw({
    install(app) {
      setActivePinia(pinia);
      {
        pinia._a = app;
        app.provide(piniaSymbol, pinia);
        app.config.globalProperties.$pinia = pinia;
        toBeInstalled.forEach((plugin2) => _p.push(plugin2));
        toBeInstalled = [];
      }
    },
    use(plugin2) {
      if (!this._a && !isVue2) {
        toBeInstalled.push(plugin2);
      } else {
        _p.push(plugin2);
      }
      return this;
    },
    _p,
    // it's actually undefined here
    // @ts-expect-error
    _a: null,
    _e: scope,
    _s: /* @__PURE__ */ new Map(),
    state: state2
  });
  if (USE_DEVTOOLS && typeof Proxy !== "undefined") {
    pinia.use(devtoolsPlugin);
  }
  return pinia;
}
function patchObject(newState, oldState) {
  for (const key in oldState) {
    const subPatch = oldState[key];
    if (!(key in newState)) {
      continue;
    }
    const targetValue = newState[key];
    if (isPlainObject(targetValue) && isPlainObject(subPatch) && !isRef(subPatch) && !isReactive(subPatch)) {
      newState[key] = patchObject(targetValue, subPatch);
    } else {
      {
        newState[key] = subPatch;
      }
    }
  }
  return newState;
}
const noop = () => {
};
function addSubscription(subscriptions, callback, detached, onCleanup = noop) {
  subscriptions.push(callback);
  const removeSubscription = () => {
    const idx = subscriptions.indexOf(callback);
    if (idx > -1) {
      subscriptions.splice(idx, 1);
      onCleanup();
    }
  };
  if (!detached && getCurrentScope()) {
    onScopeDispose(removeSubscription);
  }
  return removeSubscription;
}
function triggerSubscriptions(subscriptions, ...args) {
  subscriptions.slice().forEach((callback) => {
    callback(...args);
  });
}
const fallbackRunWithContext = (fn) => fn();
function mergeReactiveObjects(target, patchToApply) {
  if (target instanceof Map && patchToApply instanceof Map) {
    patchToApply.forEach((value, key) => target.set(key, value));
  }
  if (target instanceof Set && patchToApply instanceof Set) {
    patchToApply.forEach(target.add, target);
  }
  for (const key in patchToApply) {
    if (!patchToApply.hasOwnProperty(key))
      continue;
    const subPatch = patchToApply[key];
    const targetValue = target[key];
    if (isPlainObject(targetValue) && isPlainObject(subPatch) && target.hasOwnProperty(key) && !isRef(subPatch) && !isReactive(subPatch)) {
      target[key] = mergeReactiveObjects(targetValue, subPatch);
    } else {
      target[key] = subPatch;
    }
  }
  return target;
}
const skipHydrateSymbol = Symbol("pinia:skipHydration");
function shouldHydrate(obj) {
  return !isPlainObject(obj) || !obj.hasOwnProperty(skipHydrateSymbol);
}
const { assign } = Object;
function isComputed(o2) {
  return !!(isRef(o2) && o2.effect);
}
function createOptionsStore(id, options, pinia, hot) {
  const { state: state2, actions, getters } = options;
  const initialState = pinia.state.value[id];
  let store;
  function setup() {
    if (!initialState && !hot) {
      {
        pinia.state.value[id] = state2 ? state2() : {};
      }
    }
    const localState = hot ? (
      // use ref() to unwrap refs inside state TODO: check if this is still necessary
      toRefs(ref(state2 ? state2() : {}).value)
    ) : toRefs(pinia.state.value[id]);
    return assign(localState, actions, Object.keys(getters || {}).reduce((computedGetters, name) => {
      if (name in localState) {
        console.warn(`[🍍]: A getter cannot have the same name as another state property. Rename one of them. Found with "${name}" in store "${id}".`);
      }
      computedGetters[name] = markRaw(computed(() => {
        setActivePinia(pinia);
        const store2 = pinia._s.get(id);
        return getters[name].call(store2, store2);
      }));
      return computedGetters;
    }, {}));
  }
  store = createSetupStore(id, setup, options, pinia, hot, true);
  return store;
}
function createSetupStore($id, setup, options = {}, pinia, hot, isOptionsStore) {
  let scope;
  const optionsForPlugin = assign({ actions: {} }, options);
  if (!pinia._e.active) {
    throw new Error("Pinia destroyed");
  }
  const $subscribeOptions = {
    deep: true
    // flush: 'post',
  };
  {
    $subscribeOptions.onTrigger = (event) => {
      if (isListening) {
        debuggerEvents = event;
      } else if (isListening == false && !store._hotUpdating) {
        if (Array.isArray(debuggerEvents)) {
          debuggerEvents.push(event);
        } else {
          console.error("🍍 debuggerEvents should be an array. This is most likely an internal Pinia bug.");
        }
      }
    };
  }
  let isListening;
  let isSyncListening;
  let subscriptions = [];
  let actionSubscriptions = [];
  let debuggerEvents;
  const initialState = pinia.state.value[$id];
  if (!isOptionsStore && !initialState && !hot) {
    {
      pinia.state.value[$id] = {};
    }
  }
  const hotState = ref({});
  let activeListener;
  function $patch(partialStateOrMutator) {
    let subscriptionMutation;
    isListening = isSyncListening = false;
    {
      debuggerEvents = [];
    }
    if (typeof partialStateOrMutator === "function") {
      partialStateOrMutator(pinia.state.value[$id]);
      subscriptionMutation = {
        type: MutationType.patchFunction,
        storeId: $id,
        events: debuggerEvents
      };
    } else {
      mergeReactiveObjects(pinia.state.value[$id], partialStateOrMutator);
      subscriptionMutation = {
        type: MutationType.patchObject,
        payload: partialStateOrMutator,
        storeId: $id,
        events: debuggerEvents
      };
    }
    const myListenerId = activeListener = Symbol();
    nextTick$1().then(() => {
      if (activeListener === myListenerId) {
        isListening = true;
      }
    });
    isSyncListening = true;
    triggerSubscriptions(subscriptions, subscriptionMutation, pinia.state.value[$id]);
  }
  const $reset = isOptionsStore ? function $reset2() {
    const { state: state2 } = options;
    const newState = state2 ? state2() : {};
    this.$patch(($state) => {
      assign($state, newState);
    });
  } : (
    /* istanbul ignore next */
    () => {
      throw new Error(`🍍: Store "${$id}" is built using the setup syntax and does not implement $reset().`);
    }
  );
  function $dispose() {
    scope.stop();
    subscriptions = [];
    actionSubscriptions = [];
    pinia._s.delete($id);
  }
  function wrapAction(name, action) {
    return function() {
      setActivePinia(pinia);
      const args = Array.from(arguments);
      const afterCallbackList = [];
      const onErrorCallbackList = [];
      function after(callback) {
        afterCallbackList.push(callback);
      }
      function onError2(callback) {
        onErrorCallbackList.push(callback);
      }
      triggerSubscriptions(actionSubscriptions, {
        args,
        name,
        store,
        after,
        onError: onError2
      });
      let ret;
      try {
        ret = action.apply(this && this.$id === $id ? this : store, args);
      } catch (error) {
        triggerSubscriptions(onErrorCallbackList, error);
        throw error;
      }
      if (ret instanceof Promise) {
        return ret.then((value) => {
          triggerSubscriptions(afterCallbackList, value);
          return value;
        }).catch((error) => {
          triggerSubscriptions(onErrorCallbackList, error);
          return Promise.reject(error);
        });
      }
      triggerSubscriptions(afterCallbackList, ret);
      return ret;
    };
  }
  const _hmrPayload = /* @__PURE__ */ markRaw({
    actions: {},
    getters: {},
    state: [],
    hotState
  });
  const partialStore = {
    _p: pinia,
    // _s: scope,
    $id,
    $onAction: addSubscription.bind(null, actionSubscriptions),
    $patch,
    $reset,
    $subscribe(callback, options2 = {}) {
      const removeSubscription = addSubscription(subscriptions, callback, options2.detached, () => stopWatcher());
      const stopWatcher = scope.run(() => watch(() => pinia.state.value[$id], (state2) => {
        if (options2.flush === "sync" ? isSyncListening : isListening) {
          callback({
            storeId: $id,
            type: MutationType.direct,
            events: debuggerEvents
          }, state2);
        }
      }, assign({}, $subscribeOptions, options2)));
      return removeSubscription;
    },
    $dispose
  };
  const store = reactive(assign(
    {
      _hmrPayload,
      _customProperties: markRaw(/* @__PURE__ */ new Set())
      // devtools custom properties
    },
    partialStore
    // must be added later
    // setupStore
  ));
  pinia._s.set($id, store);
  const runWithContext = pinia._a && pinia._a.runWithContext || fallbackRunWithContext;
  const setupStore = runWithContext(() => pinia._e.run(() => (scope = effectScope()).run(setup)));
  for (const key in setupStore) {
    const prop = setupStore[key];
    if (isRef(prop) && !isComputed(prop) || isReactive(prop)) {
      if (hot) {
        set$1(hotState.value, key, toRef(setupStore, key));
      } else if (!isOptionsStore) {
        if (initialState && shouldHydrate(prop)) {
          if (isRef(prop)) {
            prop.value = initialState[key];
          } else {
            mergeReactiveObjects(prop, initialState[key]);
          }
        }
        {
          pinia.state.value[$id][key] = prop;
        }
      }
      {
        _hmrPayload.state.push(key);
      }
    } else if (typeof prop === "function") {
      const actionValue = hot ? prop : wrapAction(key, prop);
      {
        setupStore[key] = actionValue;
      }
      {
        _hmrPayload.actions[key] = prop;
      }
      optionsForPlugin.actions[key] = prop;
    } else {
      if (isComputed(prop)) {
        _hmrPayload.getters[key] = isOptionsStore ? (
          // @ts-expect-error
          options.getters[key]
        ) : prop;
        if (IS_CLIENT) {
          const getters = setupStore._getters || // @ts-expect-error: same
          (setupStore._getters = markRaw([]));
          getters.push(key);
        }
      }
    }
  }
  {
    assign(store, setupStore);
    assign(toRaw(store), setupStore);
  }
  Object.defineProperty(store, "$state", {
    get: () => hot ? hotState.value : pinia.state.value[$id],
    set: (state2) => {
      if (hot) {
        throw new Error("cannot set hotState");
      }
      $patch(($state) => {
        assign($state, state2);
      });
    }
  });
  {
    store._hotUpdate = markRaw((newStore) => {
      store._hotUpdating = true;
      newStore._hmrPayload.state.forEach((stateKey) => {
        if (stateKey in store.$state) {
          const newStateTarget = newStore.$state[stateKey];
          const oldStateSource = store.$state[stateKey];
          if (typeof newStateTarget === "object" && isPlainObject(newStateTarget) && isPlainObject(oldStateSource)) {
            patchObject(newStateTarget, oldStateSource);
          } else {
            newStore.$state[stateKey] = oldStateSource;
          }
        }
        set$1(store, stateKey, toRef(newStore.$state, stateKey));
      });
      Object.keys(store.$state).forEach((stateKey) => {
        if (!(stateKey in newStore.$state)) {
          del(store, stateKey);
        }
      });
      isListening = false;
      isSyncListening = false;
      pinia.state.value[$id] = toRef(newStore._hmrPayload, "hotState");
      isSyncListening = true;
      nextTick$1().then(() => {
        isListening = true;
      });
      for (const actionName in newStore._hmrPayload.actions) {
        const action = newStore[actionName];
        set$1(store, actionName, wrapAction(actionName, action));
      }
      for (const getterName in newStore._hmrPayload.getters) {
        const getter = newStore._hmrPayload.getters[getterName];
        const getterValue = isOptionsStore ? (
          // special handling of options api
          computed(() => {
            setActivePinia(pinia);
            return getter.call(store, store);
          })
        ) : getter;
        set$1(store, getterName, getterValue);
      }
      Object.keys(store._hmrPayload.getters).forEach((key) => {
        if (!(key in newStore._hmrPayload.getters)) {
          del(store, key);
        }
      });
      Object.keys(store._hmrPayload.actions).forEach((key) => {
        if (!(key in newStore._hmrPayload.actions)) {
          del(store, key);
        }
      });
      store._hmrPayload = newStore._hmrPayload;
      store._getters = newStore._getters;
      store._hotUpdating = false;
    });
  }
  if (USE_DEVTOOLS) {
    const nonEnumerable = {
      writable: true,
      configurable: true,
      // avoid warning on devtools trying to display this property
      enumerable: false
    };
    ["_p", "_hmrPayload", "_getters", "_customProperties"].forEach((p2) => {
      Object.defineProperty(store, p2, assign({ value: store[p2] }, nonEnumerable));
    });
  }
  pinia._p.forEach((extender) => {
    if (USE_DEVTOOLS) {
      const extensions = scope.run(() => extender({
        store,
        app: pinia._a,
        pinia,
        options: optionsForPlugin
      }));
      Object.keys(extensions || {}).forEach((key) => store._customProperties.add(key));
      assign(store, extensions);
    } else {
      assign(store, scope.run(() => extender({
        store,
        app: pinia._a,
        pinia,
        options: optionsForPlugin
      })));
    }
  });
  if (store.$state && typeof store.$state === "object" && typeof store.$state.constructor === "function" && !store.$state.constructor.toString().includes("[native code]")) {
    console.warn(`[🍍]: The "state" must be a plain object. It cannot be
	state: () => new MyClass()
Found in store "${store.$id}".`);
  }
  if (initialState && isOptionsStore && options.hydrate) {
    options.hydrate(store.$state, initialState);
  }
  isListening = true;
  isSyncListening = true;
  return store;
}
function defineStore(idOrOptions, setup, setupOptions) {
  let id;
  let options;
  const isSetupStore = typeof setup === "function";
  if (typeof idOrOptions === "string") {
    id = idOrOptions;
    options = isSetupStore ? setupOptions : setup;
  } else {
    options = idOrOptions;
    id = idOrOptions.id;
    if (typeof id !== "string") {
      throw new Error(`[🍍]: "defineStore()" must be passed a store id as its first argument.`);
    }
  }
  function useStore(pinia, hot) {
    const hasContext = hasInjectionContext();
    pinia = // in test mode, ignore the argument provided as we can always retrieve a
    // pinia instance with getActivePinia()
    pinia || (hasContext ? inject(piniaSymbol, null) : null);
    if (pinia)
      setActivePinia(pinia);
    if (!activePinia) {
      throw new Error(`[🍍]: "getActivePinia()" was called but there was no active Pinia. Are you trying to use a store before calling "app.use(pinia)"?
See https://pinia.vuejs.org/core-concepts/outside-component-usage.html for help.
This will fail in production.`);
    }
    pinia = activePinia;
    if (!pinia._s.has(id)) {
      if (isSetupStore) {
        createSetupStore(id, setup, options, pinia);
      } else {
        createOptionsStore(id, options, pinia);
      }
      {
        useStore._pinia = pinia;
      }
    }
    const store = pinia._s.get(id);
    if (hot) {
      const hotId = "__hot:" + id;
      const newStore = isSetupStore ? createSetupStore(hotId, setup, options, pinia, true) : createOptionsStore(hotId, assign({}, options), pinia, true);
      hot._hotUpdate(newStore);
      delete pinia.state.value[hotId];
      pinia._s.delete(hotId);
    }
    if (IS_CLIENT) {
      const currentInstance2 = getCurrentInstance();
      if (currentInstance2 && currentInstance2.proxy && // avoid adding stores that are just built for hot module replacement
      !hot) {
        const vm = currentInstance2.proxy;
        const cache2 = "_pStores" in vm ? vm._pStores : vm._pStores = {};
        cache2[id] = store;
      }
    }
    return store;
  }
  useStore.$id = id;
  return useStore;
}
const LT = {
  Launch: "1",
  Hide: "3",
  Page: "11",
  Event: "21",
  Error: "31",
  Push: "101"
};
const CST = {
  ColdLaunch: 1,
  BackgroundTimeout: 2,
  PageInactiveTimeout: 3
};
const IEY = {
  No: 0,
  Yes: 1
};
function toIey(input) {
  if (input === true || input === 1 || input === "1")
    return IEY.Yes;
  return IEY.No;
}
function __awaiter(thisArg, _arguments, P, generator) {
  function adopt(value) {
    return value instanceof P ? value : new P(function(resolve) {
      resolve(value);
    });
  }
  return new (P || (P = Promise))(function(resolve, reject) {
    function fulfilled(value) {
      try {
        step(generator.next(value));
      } catch (e2) {
        reject(e2);
      }
    }
    function rejected(value) {
      try {
        step(generator["throw"](value));
      } catch (e2) {
        reject(e2);
      }
    }
    function step(result) {
      result.done ? resolve(result.value) : adopt(result.value).then(fulfilled, rejected);
    }
    step((generator = generator.apply(thisArg, _arguments || [])).next());
  });
}
typeof SuppressedError === "function" ? SuppressedError : function(error, suppressed, message) {
  var e2 = new Error(message);
  return e2.name = "SuppressedError", e2.error = error, e2.suppressed = suppressed, e2;
};
const DEFAULT_MAX_LENGTH = 4096;
const TRUNCATED_SUFFIX = "…[truncated]";
function safeStringify(value, max = DEFAULT_MAX_LENGTH) {
  var _a;
  if (value === void 0)
    return "";
  let raw;
  if (typeof value === "string") {
    raw = value;
  } else {
    const seen = /* @__PURE__ */ new WeakSet();
    try {
      raw = (_a = JSON.stringify(value, (_key, val) => {
        if (typeof val === "object" && val !== null) {
          if (seen.has(val))
            return "[Circular]";
          seen.add(val);
        }
        if (typeof val === "bigint")
          return val.toString();
        if (typeof val === "function")
          return `[Function ${val.name || "anonymous"}]`;
        return val;
      })) !== null && _a !== void 0 ? _a : "";
    } catch (e2) {
      raw = `[Unserializable: ${e2.message}]`;
    }
  }
  if (raw.length > max) {
    return raw.slice(0, Math.max(0, max - TRUNCATED_SUFFIX.length)) + TRUNCATED_SUFFIX;
  }
  return raw;
}
function tryRun(fn, fallback) {
  try {
    return fn();
  } catch (_a) {
    return fallback;
  }
}
function withRetry(fn, opts) {
  return __awaiter(this, void 0, void 0, function* () {
    var _a;
    const total = Math.max(1, Math.floor(opts.times));
    const sleep = (_a = opts.sleep) !== null && _a !== void 0 ? _a : defaultSleep;
    let lastErr;
    for (let attempt = 1; attempt <= total; attempt++) {
      try {
        return yield fn();
      } catch (e2) {
        lastErr = e2;
        if (attempt >= total)
          break;
        yield sleep(opts.baseDelayMs * Math.pow(2, attempt - 1));
      }
    }
    throw lastErr;
  });
}
function defaultSleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}
function isUsableUniRuntime(candidate) {
  if (candidate == null || typeof candidate !== "object")
    return false;
  const u = candidate;
  return typeof u.getStorageSync === "function" || typeof u.onCreateVueApp === "function" || typeof u.request === "function" || typeof u.onAppShow === "function";
}
function getModuleUniCandidate() {
  if (typeof index === "undefined" || index == null || typeof index !== "object") {
    return void 0;
  }
  return index;
}
function getWindowObject() {
  try {
    const w = Function('return typeof window !== "undefined" ? window : undefined')();
    return w != null ? w : void 0;
  } catch (_a) {
    return void 0;
  }
}
function getGlobalObject() {
  if (typeof globalThis !== "undefined" && globalThis != null) {
    return globalThis;
  }
  if (typeof global !== "undefined" && global != null) {
    return global;
  }
  if (typeof self !== "undefined" && self != null) {
    return self;
  }
  const win = getWindowObject();
  if (win)
    return win;
  return {};
}
function buildInjectedUniRuntime() {
  try {
    const out = {};
    const pick = (name, fn) => {
      if (typeof fn === "function")
        out[name] = fn;
    };
    pick("getStorageSync", index.getStorageSync);
    pick("setStorageSync", index.setStorageSync);
    pick("removeStorageSync", index.removeStorageSync);
    pick("getSystemInfoSync", index.getSystemInfoSync);
    pick("getDeviceInfo", index.getDeviceInfo);
    pick("getAppBaseInfo", index.getAppBaseInfo);
    pick("getWindowInfo", index.getWindowInfo);
    pick("getNetworkType", index.getNetworkType);
    pick("request", index.request);
    pick("onAppShow", index.onAppShow);
    pick("offAppShow", index.offAppShow);
    pick("onAppHide", index.onAppHide);
    pick("offAppHide", index.offAppHide);
    pick("onAppLaunch", index.onAppLaunch);
    pick("offAppLaunch", index.offAppLaunch);
    pick("getLaunchOptionsSync", index.getLaunchOptionsSync);
    pick("addInterceptor", index.addInterceptor);
    pick("removeInterceptor", index.removeInterceptor);
    pick("getPushClientId", index.getPushClientId);
    pick("getAccountInfoSync", index.getAccountInfoSync);
    pick("onCreateVueApp", index.onCreateVueApp);
    return Object.keys(out).length > 0 ? out : void 0;
  } catch (_e) {
    return void 0;
  }
}
function probeUniRuntime() {
  const globalThisAvailable = typeof globalThis !== "undefined";
  const g = getGlobalObject();
  const globalUni = g.uni;
  const globalThisHasUni = globalUni != null && typeof globalUni === "object";
  const globalThisUniStub = globalThisHasUni && !isUsableUniRuntime(globalUni);
  const moduleUni = getModuleUniCandidate();
  const moduleUniDefined = moduleUni != null;
  if (isUsableUniRuntime(globalUni)) {
    return {
      resolved: true,
      source: "globalThis",
      globalThisHasUni: true,
      globalThisUniStub: false,
      moduleUniDefined,
      globalThisAvailable,
      uni: globalUni
    };
  }
  if (isUsableUniRuntime(moduleUni)) {
    return {
      resolved: true,
      source: "module",
      globalThisHasUni,
      globalThisUniStub,
      moduleUniDefined: true,
      globalThisAvailable,
      uni: moduleUni
    };
  }
  const injectedUni = buildInjectedUniRuntime();
  if (isUsableUniRuntime(injectedUni)) {
    return {
      resolved: true,
      source: "injected",
      globalThisHasUni,
      globalThisUniStub,
      moduleUniDefined,
      globalThisAvailable,
      uni: injectedUni
    };
  }
  return {
    resolved: false,
    source: "none",
    globalThisHasUni,
    globalThisUniStub,
    moduleUniDefined,
    globalThisAvailable,
    uni: void 0
  };
}
function resolveUniRuntime() {
  const probe = probeUniRuntime();
  return probe.resolved ? probe.uni : void 0;
}
const TAG = "[uni统计 2.0]";
let runtimeDebug;
let muteNonDebug;
function preferSingleLineConsole() {
  return isAndroidOrIosRuntime();
}
function isAndroidOrIosRuntime() {
  var _a, _b, _c, _d, _e, _f, _g, _h;
  const raw = (_a = "mp-weixin") !== null && _a !== void 0 ? _a : "";
  const g = getGlobalObject();
  if (raw === "app" || raw === "app-plus" || raw === "app-harmony") {
    const n2 = (_d = (_c = (_b = g.plus) === null || _b === void 0 ? void 0 : _b.os) === null || _c === void 0 ? void 0 : _c.name) === null || _d === void 0 ? void 0 : _d.toLowerCase();
    if (!n2)
      return false;
    if (n2.includes("android"))
      return true;
    if (n2 === "ios" || n2.includes("iphone"))
      return true;
    return false;
  }
  if (raw.startsWith("mp-")) {
    try {
      const p2 = (_h = (_g = (_f = (_e = g.uni) === null || _e === void 0 ? void 0 : _e.getSystemInfoSync) === null || _f === void 0 ? void 0 : _f.call(_e)) === null || _g === void 0 ? void 0 : _g.platform) === null || _h === void 0 ? void 0 : _h.toLowerCase();
      return p2 === "android" || p2 === "ios";
    } catch (_j) {
      return false;
    }
  }
  return false;
}
function stringifyObjectArgForNative(value) {
  if (value === null || value === void 0)
    return value;
  if (typeof value !== "object")
    return value;
  if (value instanceof Error)
    return `${value.name}: ${value.message}`;
  return safeStringify(value);
}
function formatLogArgForNativeConsole(value) {
  if (value === null)
    return "null";
  if (value === void 0)
    return "undefined";
  if (typeof value === "string")
    return value;
  if (typeof value === "number" || typeof value === "boolean") {
    return String(value);
  }
  if (typeof value === "bigint")
    return String(value);
  if (typeof value === "symbol") {
    try {
      return value.toString();
    } catch (_a) {
      return "?";
    }
  }
  if (typeof value === "function") {
    const fn = value;
    return `[Function ${fn.name || "anonymous"}]`;
  }
  if (typeof value === "object") {
    if (value instanceof Error)
      return `${value.name}: ${value.message}`;
    return safeStringify(value);
  }
  return String(value);
}
function isNonDebugMuted() {
  if (muteNonDebug !== void 0)
    return muteNonDebug;
  return false;
}
function setMuteNonDebug(value) {
  muteNonDebug = value;
}
function emitConsole(method, args) {
  if (method !== "log" && isNonDebugMuted())
    return;
  const fn = console[method];
  if (!preferSingleLineConsole()) {
    fn.call(console, TAG, ...args);
    return;
  }
  const mapped = isAndroidOrIosRuntime() ? args.map(stringifyObjectArgForNative) : args;
  if (mapped.length === 0) {
    fn.call(console, TAG);
    return;
  }
  const body = mapped.map(formatLogArgForNativeConsole).join(" ");
  fn.call(console, `${TAG} ${body}`);
}
function isDebug() {
  if (runtimeDebug !== void 0)
    return runtimeDebug;
  const v = "false";
  return v === true;
}
function setDebug(value) {
  runtimeDebug = value;
}
const logger = {
  debug(...args) {
    if (!isDebug())
      return;
    emitConsole("log", args);
  },
  info(...args) {
    emitConsole("info", args);
  },
  warn(...args) {
    emitConsole("warn", args);
  },
  error(...args) {
    emitConsole("error", args);
  },
  setDebug,
  isDebug,
  setMuteNonDebug
};
const NAMESPACE_ROOT = "UNI_STAT_DATA";
const LEGACY_NAMESPACE_ROOT = "$$STAT__DBDATA";
const cache = /* @__PURE__ */ new Map();
const knownKeys = /* @__PURE__ */ new Set();
function fullKey(key) {
  const appid = "__UNI__4FA356E";
  return `${NAMESPACE_ROOT}:${appid}:${key}`;
}
function getUni$9() {
  const raw = resolveUniRuntime();
  const u = raw != null && typeof raw === "object" ? raw : void 0;
  if (!u || typeof u.getStorageSync !== "function") {
    throw new Error("[uni统计 2.0] uni storage API is not available");
  }
  return u;
}
function get(key) {
  const fk = fullKey(key);
  if (cache.has(fk))
    return cache.get(fk);
  try {
    const raw = getUni$9().getStorageSync(fk);
    if (raw === "" || raw === null || raw === void 0) {
      cache.set(fk, void 0);
      return void 0;
    }
    cache.set(fk, raw);
    knownKeys.add(fk);
    return raw;
  } catch (_a) {
    return void 0;
  }
}
function safeRead(key) {
  const fk = fullKey(key);
  if (cache.has(fk))
    return { ok: true, value: cache.get(fk) };
  try {
    const raw = getUni$9().getStorageSync(fk);
    if (raw === "" || raw === null || raw === void 0) {
      cache.set(fk, void 0);
      return { ok: true, value: void 0 };
    }
    cache.set(fk, raw);
    knownKeys.add(fk);
    return { ok: true, value: raw };
  } catch (_a) {
    return { ok: false, value: void 0 };
  }
}
function set(key, value) {
  const fk = fullKey(key);
  if (value === void 0) {
    remove(key);
    return;
  }
  cache.set(fk, value);
  knownKeys.add(fk);
  try {
    getUni$9().setStorageSync(fk, value);
  } catch (_a) {
  }
}
function remove(key) {
  const fk = fullKey(key);
  cache.set(fk, void 0);
  try {
    getUni$9().removeStorageSync(fk);
  } catch (_a) {
  }
}
function batchGet(keys) {
  const out = {};
  for (const k of keys)
    out[k] = get(k);
  return out;
}
function batchSet(entries) {
  for (const k of Object.keys(entries))
    set(k, entries[k]);
}
function clearNamespace() {
  let uni2;
  try {
    uni2 = getUni$9();
  } catch (_a) {
  }
  for (const fk of Array.from(knownKeys)) {
    try {
      uni2 === null || uni2 === void 0 ? void 0 : uni2.removeStorageSync(fk);
    } catch (_b) {
    }
    cache.set(fk, void 0);
  }
  knownKeys.clear();
}
function __resetCache() {
  cache.clear();
  knownKeys.clear();
}
const storage = {
  get,
  set,
  remove,
  safeRead,
  batchGet,
  batchSet,
  clearNamespace,
  __resetCache
};
const KEY_FVTS = "visit:fvts";
const KEY_LVTS = "visit:lvts";
const KEY_TVC = "visit:tvc";
const EMPTY_SNAPSHOT = {
  fvts: 0,
  lvts: 0,
  tvc: 0,
  isNewUser: true,
  degraded: false
};
let loaded = null;
let pending = null;
let pendingRenewal = null;
let committed = null;
let lastBuilt = null;
let buildCalledInProcess = false;
function toNum(v) {
  if (typeof v === "number" && Number.isFinite(v) && v >= 0)
    return v;
  if (typeof v === "string" && v.length > 0) {
    const n2 = Number(v);
    if (Number.isFinite(n2) && n2 >= 0)
      return n2;
  }
  return 0;
}
function isLikelyFreshDevice(snap) {
  return snap.fvts === 0 && snap.lvts === 0 && snap.tvc === 0;
}
function isTrustworthyNewUser(snap) {
  if (!snap.isNewUser)
    return false;
  return !snap.degraded || isLikelyFreshDevice(snap);
}
function loadVisitSnapshot() {
  const fvtsR = storage.safeRead(KEY_FVTS);
  const lvtsR = storage.safeRead(KEY_LVTS);
  const tvcR = storage.safeRead(KEY_TVC);
  const degraded = !fvtsR.ok || !lvtsR.ok || !tvcR.ok;
  const fvts = toNum(fvtsR.value);
  const lvts = toNum(lvtsR.value);
  const tvc = toNum(tvcR.value);
  const snapshot = {
    fvts,
    lvts,
    tvc,
    isNewUser: lvts === 0,
    degraded
  };
  if (degraded) {
    const likelyFresh = fvts === 0 && lvts === 0 && tvc === 0 && snapshot.isNewUser;
    if (!likelyFresh) {
      logger.warn("[uni统计 2.0] visit snapshot degraded; some storage keys read failed");
    }
  }
  loaded = snapshot;
  return snapshot;
}
function ensureLoaded() {
  if (!loaded)
    loaded = EMPTY_SNAPSHOT;
  return loaded;
}
function persistNewUserBaseline(now) {
  storage.set(KEY_FVTS, now);
  storage.set(KEY_LVTS, now);
  storage.set(KEY_TVC, 1);
  const baseline = {
    fvts: now,
    lvts: now,
    tvc: 1,
    isNewUser: false,
    degraded: false
  };
  loaded = baseline;
  committed = baseline;
}
function buildVisitFields(now) {
  const snap = ensureLoaded();
  if (buildCalledInProcess && lastBuilt) {
    logger.warn("[uni统计 2.0] buildVisitFields() called twice in same process; returning cached fields");
    return Object.assign({}, lastBuilt);
  }
  buildCalledInProcess = true;
  if (isTrustworthyNewUser(snap)) {
    pending = { fvts: now, lvts: 0, tvc: 1, now };
    persistNewUserBaseline(now);
  } else if (snap.isNewUser) {
    logger.warn("[uni统计 2.0] visit degraded: lvts 读取失败但检测到历史数据，按老用户处理以避免新增虚高");
    const fvts = snap.fvts > 0 ? snap.fvts : now;
    pending = { fvts, lvts: fvts, tvc: snap.tvc + 1, now };
  } else {
    pending = {
      fvts: snap.fvts,
      lvts: snap.lvts,
      tvc: snap.tvc + 1,
      now
    };
  }
  lastBuilt = { fvts: pending.fvts, lvts: pending.lvts, tvc: pending.tvc };
  return Object.assign({}, lastBuilt);
}
function buildVisitFieldsForSessionRenewal(now) {
  let fvts;
  let lvts;
  let tvc;
  if (committed) {
    fvts = committed.fvts;
    lvts = committed.lvts;
    tvc = committed.tvc + 1;
  } else if (lastBuilt) {
    fvts = lastBuilt.fvts;
    lvts = lastBuilt.lvts !== 0 ? lastBuilt.lvts : lastBuilt.fvts;
    tvc = lastBuilt.tvc;
  } else {
    const snap = ensureLoaded();
    if (isTrustworthyNewUser(snap)) {
      fvts = now;
      lvts = 0;
      tvc = 1;
      persistNewUserBaseline(now);
    } else if (snap.isNewUser) {
      fvts = snap.fvts > 0 ? snap.fvts : now;
      lvts = fvts;
      tvc = snap.tvc + 1;
    } else {
      fvts = snap.fvts;
      lvts = snap.lvts;
      tvc = snap.tvc + 1;
    }
  }
  pendingRenewal = { fvts, lvts, tvc, now };
  return { fvts, lvts, tvc };
}
function commitVisitOnAck(now) {
  if (pending) {
    const snap = ensureLoaded();
    const newFvts2 = snap.fvts === 0 ? now : snap.fvts;
    const newLvts2 = now;
    const newTvc2 = pending.tvc;
    storage.set(KEY_FVTS, newFvts2);
    storage.set(KEY_LVTS, newLvts2);
    storage.set(KEY_TVC, newTvc2);
    committed = {
      fvts: newFvts2,
      lvts: newLvts2,
      tvc: newTvc2,
      isNewUser: false,
      degraded: false
    };
    loaded = committed;
    pending = null;
    return;
  }
  if (!pendingRenewal)
    return;
  const newFvts = pendingRenewal.fvts;
  const newLvts = now;
  const newTvc = pendingRenewal.tvc;
  storage.set(KEY_FVTS, newFvts);
  storage.set(KEY_LVTS, newLvts);
  storage.set(KEY_TVC, newTvc);
  committed = {
    fvts: newFvts,
    lvts: newLvts,
    tvc: newTvc,
    isNewUser: false,
    degraded: false
  };
  loaded = committed;
  pendingRenewal = null;
}
function rollbackPendingVisit() {
  pending = null;
  pendingRenewal = null;
}
const KEY_ENTRY = "session:entryRoute";
let cached$3;
let entryDeparted = false;
function markEntryPage(route) {
  if (!route)
    return;
  const existing = getEntryRoute();
  if (existing)
    return;
  storage.set(KEY_ENTRY, route);
  cached$3 = route;
}
function getEntryRoute() {
  if (cached$3 !== void 0)
    return cached$3 || void 0;
  const r = storage.safeRead(KEY_ENTRY);
  if (!r.ok)
    return void 0;
  if (typeof r.value === "string" && r.value.length > 0) {
    cached$3 = r.value;
    return r.value;
  }
  cached$3 = "";
  return void 0;
}
function isEntry(route) {
  if (!route)
    return false;
  const entry = getEntryRoute();
  return entry === route;
}
function isEntryForIey(route) {
  if (entryDeparted)
    return false;
  return isEntry(route);
}
function markEntryDeparted() {
  entryDeparted = true;
}
function clearEntry() {
  cached$3 = "";
  entryDeparted = false;
  storage.remove(KEY_ENTRY);
}
let titleMapCache;
function getVue3TitleMap() {
  if (titleMapCache)
    return titleMapCache;
  titleMapCache = {};
  try {
    const raw = '{"pages/index/index":"DATA ANALYSIS","pages/report/report":"REPORT"}';
    if (typeof raw !== "string" || !raw)
      ;
    const parsed = JSON.parse(raw);
    if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) {
      titleMapCache = parsed;
    }
  } catch (_a) {
    titleMapCache = {};
  }
  return titleMapCache;
}
function getTitleMap() {
  let map = {};
  map = getVue3TitleMap();
  return map;
}
function getPagesJsonNavigationTitle(routePath) {
  if (!routePath || typeof routePath !== "string")
    return "";
  const pathOnly = routePath.split("?")[0].trim();
  if (!pathOnly)
    return "";
  const map = getTitleMap();
  let result = "";
  const keys = [pathOnly];
  if (pathOnly.startsWith("/")) {
    keys.push(pathOnly.slice(1));
  } else {
    keys.push(`/${pathOnly}`);
  }
  for (const k of keys) {
    const v = map[k];
    if (typeof v === "string" && v.length > 0) {
      result = v;
      break;
    }
  }
  return result;
}
const state$2 = { page: "", config: "", report: "" };
function setPageTitle(title) {
  state$2.page = typeof title === "string" ? title : "";
}
function setConfigTitle(title) {
  state$2.config = typeof title === "string" ? title : "";
}
function setReportTitle(title) {
  state$2.report = typeof title === "string" ? title : "";
}
function getCurrentTitle() {
  return { ttn: state$2.page, ttpj: state$2.config, ttc: state$2.report };
}
function clearPageTitle() {
  state$2.page = "";
}
function nowMs() {
  return Date.now();
}
function nowSec() {
  return Math.floor(Date.now() / 1e3);
}
function clampUrlrefStaySec(deltaSec) {
  const d = deltaSec > 0 ? deltaSec : 0;
  return d < 1 ? 1 : d;
}
function normalizeStatOsP(info) {
  var _a, _b, _c, _d, _e;
  const fromToken = (raw) => {
    const s2 = raw.toLowerCase().trim();
    if (!s2)
      return "";
    if (s2 === "devtools")
      return "";
    if (s2 === "android")
      return "android";
    if (s2 === "ios" || s2 === "iphone")
      return "ios";
    if (s2.includes("android"))
      return "android";
    if (s2.includes("iphone") || s2 === "iphone os" || /\bios\b/.test(s2))
      return "ios";
    if (s2.includes("harmony") || s2 === "ohos" || s2 === "openharmony")
      return "harmonyos";
    if (s2.includes("windows") || s2 === "windows_nt")
      return "windows";
    if (s2 === "mac" || s2 === "darwin" || s2.includes("mac os") || s2 === "macos")
      return "macos";
    if (s2.includes("linux") && !s2.includes("android"))
      return "linux";
    return "";
  };
  const p0 = fromToken((_a = info.platform) !== null && _a !== void 0 ? _a : "");
  if (p0)
    return p0;
  const p1 = fromToken((_b = info.osName) !== null && _b !== void 0 ? _b : "");
  if (p1)
    return p1;
  const sys = ((_c = info.system) !== null && _c !== void 0 ? _c : "").toLowerCase();
  if (sys.includes("android"))
    return "android";
  if (sys.includes("iphone") || /\bios\b/.test(sys))
    return "ios";
  if (sys.includes("harmony") || sys.includes("ohos"))
    return "harmonyos";
  if (sys.includes("windows"))
    return "windows";
  if (sys.includes("mac os") || sys.includes("darwin"))
    return "macos";
  if (sys.includes("linux"))
    return "linux";
  const plus = getGlobalObject().plus;
  const p2 = fromToken((_e = (_d = plus === null || plus === void 0 ? void 0 : plus.os) === null || _d === void 0 ? void 0 : _d.name) !== null && _e !== void 0 ? _e : "");
  if (p2)
    return p2;
  return "";
}
function uniPlatformMpAliRaw() {
  const parts = ["y", "a", "p", "mp-ali"];
  return [...parts].reverse().join("");
}
const PLATFORM_MAP = {
  app: "n",
  "app-plus": "n",
  "app-harmony": "n",
  "mp-harmony": "mhm",
  h5: "h5",
  "mp-weixin": "wx",
  [uniPlatformMpAliRaw()]: "ali",
  "mp-baidu": "bd",
  "mp-toutiao": "tt",
  "mp-qq": "qq",
  "mp-kuaishou": "ks",
  "mp-lark": "lark",
  "mp-xhs": "xhs",
  "mp-jd": "jd",
  "quickapp-native": "qn",
  "quickapp-webview": "qw"
};
function getRawPlatform() {
  var _a;
  return (_a = "mp-weixin") !== null && _a !== void 0 ? _a : "";
}
function getPlatform() {
  var _a;
  const raw = getRawPlatform();
  const mapped = PLATFORM_MAP[raw];
  if (!mapped)
    return "unknown";
  if (mapped === "ali") {
    const my2 = getGlobalObject().my;
    if (((_a = my2 === null || my2 === void 0 ? void 0 : my2.env) === null || _a === void 0 ? void 0 : _a.clientName) === "dingtalk")
      return "dt";
    return "ali";
  }
  return mapped;
}
function isApp() {
  const raw = getRawPlatform();
  return raw === "app" || raw === "app-plus" || raw === "app-harmony";
}
function isMp() {
  return getRawPlatform().startsWith("mp-");
}
function isH5() {
  return getRawPlatform() === "h5";
}
function isNvue() {
  return Boolean(getGlobalObject().__NVUE__);
}
const STORAGE_KEY_UUID = "device:uuid";
const WEB_UUID_KEY = "__DC_STAT_UUID";
let cachedUuid = null;
function preferGetDeviceInfoDeviceIdFirst() {
  if (isApp() || isH5())
    return true;
  return getRawPlatform() === "mp-weixin";
}
function readSysDeviceId() {
  const root = resolveUniRuntime();
  const u = root != null && typeof root === "object" ? root : void 0;
  if (!u || typeof u.getSystemInfoSync !== "function")
    return "";
  return tryRun(() => {
    var _a;
    return (_a = u.getSystemInfoSync().deviceId) !== null && _a !== void 0 ? _a : "";
  }, "");
}
function readGetDeviceInfoDeviceId() {
  const root = resolveUniRuntime();
  const u = root != null && typeof root === "object" ? root : void 0;
  if (!u || typeof u.getDeviceInfo !== "function")
    return "";
  return tryRun(() => {
    var _a;
    return (_a = u.getDeviceInfo().deviceId) !== null && _a !== void 0 ? _a : "";
  }, "");
}
function generateAnonUuid() {
  const ms = nowMs();
  const rnd = Math.floor(Math.random() * 1e6).toString().padStart(6, "0");
  return `${ms}${rnd}`;
}
function persistUuid(uuid) {
  tryRun(() => storage.set(STORAGE_KEY_UUID, uuid), void 0);
}
function getWebLocalStorage() {
  return tryRun(() => {
    const g = getGlobalObject();
    if (g.navigator && g.navigator.cookieEnabled === false)
      return void 0;
    const ls = g.localStorage;
    if (ls && typeof ls.getItem === "function" && typeof ls.setItem === "function") {
      return ls;
    }
    return void 0;
  }, void 0);
}
function readWebDeviceId() {
  const ls = getWebLocalStorage();
  if (!ls)
    return "";
  return tryRun(() => {
    const v = ls.getItem(WEB_UUID_KEY);
    return typeof v === "string" ? v : "";
  }, "");
}
function writeWebDeviceId(uuid) {
  const ls = getWebLocalStorage();
  if (!ls)
    return;
  tryRun(() => ls.setItem(WEB_UUID_KEY, uuid), void 0);
}
function resolveDeviceIdFromUni() {
  if (preferGetDeviceInfoDeviceIdFirst()) {
    const fromDeviceInfo = readGetDeviceInfoDeviceId();
    if (fromDeviceInfo)
      return fromDeviceInfo;
  }
  return readSysDeviceId();
}
function getUuid() {
  if (cachedUuid)
    return cachedUuid;
  if (isH5()) {
    const fromWeb = readWebDeviceId();
    if (fromWeb) {
      cachedUuid = fromWeb;
      return cachedUuid;
    }
  }
  const fromDevice = resolveDeviceIdFromUni();
  if (fromDevice) {
    persistUuid(fromDevice);
    if (isH5())
      writeWebDeviceId(fromDevice);
    cachedUuid = fromDevice;
    return cachedUuid;
  }
  const storedRead = storage.safeRead(STORAGE_KEY_UUID);
  if (storedRead.ok) {
    const stored = storedRead.value;
    if (typeof stored === "string" && stored.length > 0) {
      if (stored.startsWith("device-anon-")) {
        const upgraded = generateAnonUuid();
        persistUuid(upgraded);
        if (isH5())
          writeWebDeviceId(upgraded);
        cachedUuid = upgraded;
        return cachedUuid;
      }
      cachedUuid = stored;
      return cachedUuid;
    }
    const generated = generateAnonUuid();
    persistUuid(generated);
    if (isH5())
      writeWebDeviceId(generated);
    cachedUuid = generated;
    return cachedUuid;
  }
  const ephemeral = generateAnonUuid();
  if (isH5()) {
    writeWebDeviceId(ephemeral);
    cachedUuid = ephemeral;
    return cachedUuid;
  }
  return ephemeral;
}
const SUFFIX_HEAD_LEN = 8;
const SUFFIX_TAIL_LEN = 4;
function randomPart(len) {
  const r = Math.random().toString(36).slice(2, 2 + len);
  return r.length >= len ? r : r.padEnd(len, "0");
}
function sessionInstanceSuffix() {
  return `${randomPart(SUFFIX_HEAD_LEN)}-${randomPart(SUFFIX_TAIL_LEN)}`;
}
function anonNumericBody() {
  const ms = nowMs();
  const rnd = Math.floor(Math.random() * 1e6).toString().padStart(6, "0");
  return `${ms}${rnd}`;
}
function genSid(uuid) {
  if (uuid && uuid.length > 0) {
    return `${uuid}-${sessionInstanceSuffix()}`;
  }
  return `${anonNumericBody()}-${sessionInstanceSuffix()}`;
}
const KEY_SID = "session:id";
const KEY_SST = "session:start";
const KEY_SCT = "session:sct";
const KEY_SEQ = "session:seq";
const KEY_LAST_ACTIVE = "session:lastActive";
const KEY_BG_TS = "session:bgTs";
const KEY_LAST_SCENE = "session:lastScene";
const DEFAULT_CONFIG = {
  backgroundTimeoutSec: 300,
  pageInactiveTimeoutSec: 1800
};
let config$1 = Object.assign({}, DEFAULT_CONFIG);
let cached$2 = null;
function configure$1(c) {
  config$1 = Object.assign({}, DEFAULT_CONFIG, c);
}
function readNum(key) {
  const r = storage.safeRead(key);
  if (!r.ok)
    return 0;
  const v = r.value;
  if (typeof v === "number" && Number.isFinite(v) && v >= 0)
    return v;
  if (typeof v === "string" && v.length > 0) {
    const n2 = Number(v);
    if (Number.isFinite(n2) && n2 >= 0)
      return n2;
  }
  return 0;
}
function readStr(key) {
  const r = storage.safeRead(key);
  if (!r.ok)
    return "";
  return typeof r.value === "string" ? r.value : "";
}
function elapsedNonNeg(now, from) {
  const diff2 = now - from;
  return diff2 > 0 ? diff2 : 0;
}
function loadFromStorage() {
  const sid = readStr(KEY_SID);
  if (!sid)
    return null;
  return {
    sid,
    sst: readNum(KEY_SST),
    sct: readNum(KEY_SCT) || CST.ColdLaunch,
    seq: readNum(KEY_SEQ),
    lastActive: readNum(KEY_LAST_ACTIVE),
    bgTs: readNum(KEY_BG_TS),
    lastScene: readStr(KEY_LAST_SCENE)
  };
}
function ensureCache() {
  if (cached$2 !== null)
    return cached$2;
  cached$2 = loadFromStorage();
  return cached$2;
}
function createNew(now, sct, scene) {
  const sid = genSid(getUuid());
  const next = {
    sid,
    sst: now,
    sct,
    seq: 0,
    lastActive: now,
    bgTs: 0,
    lastScene: scene
  };
  storage.set(KEY_SID, sid);
  storage.set(KEY_SST, now);
  storage.set(KEY_SCT, sct);
  storage.set(KEY_SEQ, 0);
  storage.set(KEY_LAST_ACTIVE, now);
  storage.set(KEY_BG_TS, 0);
  storage.set(KEY_LAST_SCENE, scene);
  cached$2 = next;
  return next;
}
function ensureSession(t2, ctx) {
  const { now, scene = "" } = ctx;
  const snap = ensureCache();
  if (t2 === "cold_launch") {
    const created = createNew(now, CST.ColdLaunch, scene);
    return { snapshot: created, isNew: true, cst: CST.ColdLaunch };
  }
  if (!snap) {
    const created = createNew(now, CST.ColdLaunch, scene);
    return { snapshot: created, isNew: true, cst: CST.ColdLaunch };
  }
  if (t2 === "app_show") {
    const enterCandidates = [];
    if (ctx.backgroundEnteredAt && ctx.backgroundEnteredAt > 0) {
      enterCandidates.push(ctx.backgroundEnteredAt);
    }
    if (snap.bgTs > 0) {
      enterCandidates.push(snap.bgTs);
    }
    const enterTs = enterCandidates.length > 0 ? Math.min(...enterCandidates) : 0;
    const elapsed2 = enterTs > 0 ? elapsedNonNeg(now, enterTs) : elapsedNonNeg(now, snap.lastActive);
    const sceneChanged = !!scene && !!snap.lastScene && scene !== snap.lastScene;
    const fromBackground = enterTs > 0;
    if (sceneChanged || fromBackground && elapsed2 >= config$1.backgroundTimeoutSec) {
      const created = createNew(now, CST.BackgroundTimeout, scene);
      return { snapshot: created, isNew: true, cst: CST.BackgroundTimeout };
    }
    touch(now);
    storage.set(KEY_BG_TS, 0);
    if (cached$2)
      cached$2.bgTs = 0;
    return { snapshot: cached$2, isNew: false, cst: 0 };
  }
  if (t2 === "wx_scene_changed") {
    if (scene && scene !== snap.lastScene) {
      const created = createNew(now, CST.BackgroundTimeout, scene);
      return { snapshot: created, isNew: true, cst: CST.BackgroundTimeout };
    }
    return { snapshot: snap, isNew: false, cst: 0 };
  }
  const elapsed = elapsedNonNeg(now, snap.lastActive);
  if (elapsed >= config$1.pageInactiveTimeoutSec) {
    const created = createNew(now, CST.PageInactiveTimeout, scene || snap.lastScene);
    return { snapshot: created, isNew: true, cst: CST.PageInactiveTimeout };
  }
  touch(now);
  return { snapshot: cached$2, isNew: false, cst: 0 };
}
function markBackground(now) {
  if (!cached$2)
    cached$2 = loadFromStorage();
  if (!cached$2)
    return;
  storage.set(KEY_BG_TS, now);
  cached$2.bgTs = now;
}
function touch(now) {
  if (!cached$2)
    cached$2 = loadFromStorage();
  if (!cached$2)
    return;
  storage.set(KEY_LAST_ACTIVE, now);
  cached$2.lastActive = now;
}
function nextSeq() {
  if (!cached$2)
    cached$2 = loadFromStorage();
  if (!cached$2)
    return 0;
  const next = cached$2.seq + 1;
  cached$2.seq = next;
  storage.set(KEY_SEQ, next);
  return next;
}
function getSnapshot() {
  return ensureCache();
}
function syncLastScene(scene) {
  if (!scene)
    return;
  if (!cached$2)
    cached$2 = loadFromStorage();
  if (!cached$2)
    return;
  storage.set(KEY_LAST_SCENE, scene);
  cached$2.lastScene = scene;
}
function getPageVmType(vm) {
  var _a, _b, _c, _d, _e, _f, _g, _h;
  if (!vm)
    return null;
  const internalMpType = (_c = (_b = (_a = vm.$) === null || _a === void 0 ? void 0 : _a.type) === null || _b === void 0 ? void 0 : _b.mpType) !== null && _c !== void 0 ? _c : (_d = vm.type) === null || _d === void 0 ? void 0 : _d.mpType;
  if (vm.mpType === "page" || vm.$mpType === "page" || ((_e = vm.$mp) === null || _e === void 0 ? void 0 : _e.mpType) === "page" || ((_f = vm.$options) === null || _f === void 0 ? void 0 : _f.mpType) === "page" || internalMpType === "page") {
    return "page";
  }
  if (vm.mpType === "app" || vm.$mpType === "app" || ((_g = vm.$mp) === null || _g === void 0 ? void 0 : _g.mpType) === "app" || ((_h = vm.$options) === null || _h === void 0 ? void 0 : _h.mpType) === "app" || internalMpType === "app") {
    return "app";
  }
  return null;
}
function getTopPageVm() {
  var _a;
  const fn = getGlobalObject().getCurrentPages;
  if (typeof fn !== "function")
    return void 0;
  const pages = tryRun(() => fn(), []) || [];
  if (!Array.isArray(pages) || pages.length === 0)
    return void 0;
  const top = pages[pages.length - 1];
  return (_a = top === null || top === void 0 ? void 0 : top.$vm) !== null && _a !== void 0 ? _a : top;
}
function getCurrentRoute(pageVm) {
  var _a, _b, _c, _d, _e, _f, _g, _h, _j, _k, _l;
  const vm = pageVm !== null && pageVm !== void 0 ? pageVm : getTopPageVm();
  if (!vm)
    return "";
  if (getPlatform() === "bd") {
    const r = (_e = (_c = (_b = (_a = vm.$mp) === null || _a === void 0 ? void 0 : _a.page) === null || _b === void 0 ? void 0 : _b.is) !== null && _c !== void 0 ? _c : (_d = vm.$scope) === null || _d === void 0 ? void 0 : _d.is) !== null && _e !== void 0 ? _e : "";
    if (r)
      return r;
  }
  return (_l = (_h = (_f = vm.route) !== null && _f !== void 0 ? _f : (_g = vm.$scope) === null || _g === void 0 ? void 0 : _g.route) !== null && _h !== void 0 ? _h : (_k = (_j = vm.$mp) === null || _j === void 0 ? void 0 : _j.page) === null || _k === void 0 ? void 0 : _k.route) !== null && _l !== void 0 ? _l : "";
}
function getCurrentRouteWithQuery(pageVm) {
  var _a, _b;
  const vm = pageVm !== null && pageVm !== void 0 ? pageVm : getTopPageVm();
  if (!vm)
    return "";
  const page = (_a = vm.$page) !== null && _a !== void 0 ? _a : (_b = vm.$scope) === null || _b === void 0 ? void 0 : _b.$page;
  if (page) {
    if (page.fullPath && page.fullPath !== "/")
      return page.fullPath;
    if (page.route)
      return page.route;
  }
  return getCurrentRoute(vm);
}
function getUni$8() {
  const u = resolveUniRuntime();
  return u != null && typeof u === "object" ? u : void 0;
}
function getLaunchScene(override) {
  if (override !== void 0 && override !== null && override !== "") {
    return String(override);
  }
  const u = getUni$8();
  if (typeof (u === null || u === void 0 ? void 0 : u.getLaunchOptionsSync) !== "function")
    return "";
  if (!isMp())
    return "";
  return tryRun(() => {
    const opts = u.getLaunchOptionsSync();
    const scene = opts === null || opts === void 0 ? void 0 : opts.scene;
    return scene === void 0 || scene === null ? "" : String(scene);
  }, "");
}
function getUni$7() {
  const u = resolveUniRuntime();
  return u != null && typeof u === "object" ? u : void 0;
}
function getPushClientId(opts = {}) {
  const { enabled: enabled2 = false, timeoutMs = 3e3 } = opts;
  return new Promise((resolve) => {
    if (!enabled2) {
      resolve({ ok: false, cid: "", reason: "disabled" });
      return;
    }
    const u = getUni$7();
    if (!u || typeof u.getPushClientId !== "function") {
      resolve({ ok: false, cid: "", reason: "unsupported" });
      return;
    }
    let settled = false;
    const finish = (r) => {
      if (settled)
        return;
      settled = true;
      resolve(r);
    };
    const timer = setTimeout(() => finish({ ok: false, cid: "", reason: "timeout" }), timeoutMs);
    tryRun(() => u.getPushClientId({
      success: (res) => {
        clearTimeout(timer);
        const cid2 = typeof (res === null || res === void 0 ? void 0 : res.cid) === "string" ? res.cid : "";
        if (!cid2) {
          finish({ ok: false, cid: "", reason: "fail" });
          return;
        }
        finish({ ok: true, cid: cid2 });
      },
      fail: () => {
        clearTimeout(timer);
        finish({ ok: false, cid: "", reason: "fail" });
      }
    }), void 0);
  });
}
const EMPTY_TITLE_SNAP = { ttn: "", ttpj: "", ttc: "" };
const state$1 = {
  lastRoute: "",
  lastRouteFull: "",
  beforeLastRoute: "",
  beforeLastRouteFull: "",
  lastRouteEnterTime: 0,
  lastPageTitleSnap: Object.assign({}, EMPTY_TITLE_SNAP),
  lastIey: false,
  prevIey: false,
  isHide: false,
  wasBackgrounded: false,
  pendingBackgroundResume: false,
  backgroundEnteredAt: 0,
  suppressNextPageLogAfterResume: false,
  backgroundResumeLt1At: 0
};
const BACKGROUND_RESUME_DEBOUNCE_SEC = 1;
const BACKGROUND_RESUME_LT1_DEDUP_SEC = 3;
const PAGE_APP_HIDE_DEFER_MS = 120;
let pageAppHideDeferTimer;
function shouldEarlyConsumeBackgroundResumeInMixin() {
  return !shouldBindUniAppLifecycle();
}
function markBackgroundResumeLt1Emitted(now) {
  state$1.backgroundResumeLt1At = now;
}
function shouldSkipDuplicateBackgroundResumeLt1(now) {
  return state$1.backgroundResumeLt1At > 0 && now - state$1.backgroundResumeLt1At <= BACKGROUND_RESUME_LT1_DEDUP_SEC;
}
function cancelPageAppHideDefer() {
  if (pageAppHideDeferTimer !== void 0) {
    clearTimeout(pageAppHideDeferTimer);
    pageAppHideDeferTimer = void 0;
  }
}
function tryAppHideFromPageOnHideWhenH5Hidden(app, opts) {
  var _a;
  if (!isH5())
    return;
  if (state$1.pendingBackgroundResume)
    return;
  const vis = (_a = globalThis.document) === null || _a === void 0 ? void 0 : _a.visibilityState;
  if (vis === "hidden") {
    handleAppHide(app, opts);
  }
}
function tryAppHideFromPageOnHideWhenMpDefer(app, opts) {
  if (isH5())
    return;
  if (state$1.pendingBackgroundResume)
    return;
  cancelPageAppHideDefer();
  pageAppHideDeferTimer = setTimeout(() => {
    pageAppHideDeferTimer = void 0;
    if (state$1.pendingBackgroundResume)
      return;
    handleAppHide(app, opts);
  }, PAGE_APP_HIDE_DEFER_MS);
}
function tryVue3AppHideFromPageOnHide(app, opts) {
  if (state$1.pendingBackgroundResume)
    return;
  if (isH5()) {
    tryAppHideFromPageOnHideWhenH5Hidden(app, opts);
    return;
  }
  tryAppHideFromPageOnHideWhenMpDefer(app, opts);
}
function safeCollector(app) {
  return app.getCollector();
}
function normalizePathForEntryMark(raw) {
  var _a;
  if (!raw || typeof raw !== "string")
    return "";
  const noQuery = (_a = raw.split("?")[0]) !== null && _a !== void 0 ? _a : "";
  return noQuery.startsWith("/") ? noQuery.slice(1) : noQuery;
}
function reportNewSession(c, _cst, scene, now, attachVisit, url = "") {
  let visit;
  if (attachVisit && !firstVisitEmittedInProcess) {
    firstVisitEmittedInProcess = true;
    visit = tryRun(() => buildVisitFields(now), void 0);
  } else {
    visit = tryRun(() => buildVisitFieldsForSessionRenewal(now), void 0);
  }
  const payload = {
    lt: LT.Launch,
    t: now,
    sc: scene,
    visit
  };
  if (url)
    payload.url = url;
  c.report(payload);
}
let firstVisitEmittedInProcess = false;
let titleSnapGeneration = 0;
function scheduleDeferredTitleSnapshot() {
  const gen = titleSnapGeneration;
  const run = typeof queueMicrotask === "function" ? queueMicrotask : (fn) => {
    void Promise.resolve().then(fn);
  };
  run(() => {
    tryRun(() => {
      if (gen !== titleSnapGeneration)
        return;
      state$1.lastPageTitleSnap = Object.assign({}, getCurrentTitle());
    }, void 0);
  });
}
function handleLaunch(app, options = {}, opts = {}) {
  const c = safeCollector(app);
  if (!c)
    return;
  const now = nowSec();
  const scene = tryRun(() => getLaunchScene(options.scene), "");
  const result = tryRun(() => ensureSession("cold_launch", { now, scene }), null);
  if (!result)
    return;
  tryRun(() => clearEntry(), void 0);
  const url = options.path || "";
  const entryKey = normalizePathForEntryMark(url);
  if (entryKey) {
    tryRun(() => markEntryPage(entryKey), void 0);
  }
  reportNewSession(c, result.cst || CST.ColdLaunch, scene, now, true, url);
  if (opts.enablePush) {
    void getPushClientId({ enabled: true, timeoutMs: opts.pushTimeoutMs }).then((r) => {
      if (!r.ok || !r.cid)
        return;
      const c2 = safeCollector(app);
      if (!c2)
        return;
      c2.report({ lt: LT.Push, cid: r.cid, t: nowSec() });
    }).catch((e2) => logger.warn("[uni统计 2.0] push cid fetch failed", e2));
  }
}
function tryConsumeBackgroundResume(app, options = {}, _opts = {}, _from = "unknown") {
  if (!state$1.pendingBackgroundResume) {
    return false;
  }
  const bgEnterAt = state$1.backgroundEnteredAt;
  if (bgEnterAt <= 0) {
    return false;
  }
  const c = safeCollector(app);
  if (!c) {
    return false;
  }
  const now = nowSec();
  const elapsed = now - bgEnterAt;
  if (elapsed < BACKGROUND_RESUME_DEBOUNCE_SEC) {
    state$1.suppressNextPageLogAfterResume = true;
    return true;
  }
  state$1.wasBackgrounded = false;
  state$1.suppressNextPageLogAfterResume = true;
  state$1.lastRouteEnterTime = now;
  const scene = tryRun(() => getLaunchScene(options.scene), "");
  const result = tryRun(() => ensureSession("app_show", {
    now,
    scene,
    backgroundEnteredAt: bgEnterAt
  }), null);
  state$1.pendingBackgroundResume = false;
  state$1.backgroundEnteredAt = 0;
  if (!result || !result.isNew) {
    return true;
  }
  tryRun(() => clearEntry(), void 0);
  const url = options.path || state$1.lastRoute || "";
  const entryKey = normalizePathForEntryMark(url);
  if (entryKey) {
    tryRun(() => markEntryPage(entryKey), void 0);
  }
  reportNewSession(c, result.cst || CST.BackgroundTimeout, scene, now, false, url);
  markBackgroundResumeLt1Emitted(now);
  void c.flush(true).catch((e2) => logger.warn("[uni统计 2.0] flush after new session (app_show) failed", e2));
  return true;
}
function handleAppShow(app, options = {}, opts = {}) {
  if (tryConsumeBackgroundResume(app, options, opts, "handleAppShow"))
    return;
  const c = safeCollector(app);
  if (!c)
    return;
  const now = nowSec();
  const scene = tryRun(() => getLaunchScene(options.scene), "");
  if (shouldSkipDuplicateBackgroundResumeLt1(now)) {
    tryRun(() => syncLastScene(scene), void 0);
    return;
  }
  const result = tryRun(() => ensureSession("app_show", { now, scene }), null);
  if (!result || !result.isNew) {
    return;
  }
  tryRun(() => clearEntry(), void 0);
  const url = options.path || state$1.lastRoute || "";
  const entryKey = normalizePathForEntryMark(url);
  if (entryKey) {
    tryRun(() => markEntryPage(entryKey), void 0);
  }
  reportNewSession(c, result.cst || CST.BackgroundTimeout, scene, now, false, url);
  markBackgroundResumeLt1Emitted(now);
  void c.flush(true).catch((e2) => logger.warn("[uni统计 2.0] flush after new session (app_show) failed", e2));
}
function handleAppHide(app, opts = {}) {
  if (state$1.pendingBackgroundResume)
    return;
  const c = safeCollector(app);
  if (!c)
    return;
  const now = nowSec();
  state$1.wasBackgrounded = true;
  state$1.pendingBackgroundResume = true;
  state$1.backgroundEnteredAt = now;
  tryRun(() => markBackground(now), void 0);
  const deltaStay = state$1.lastRouteEnterTime > 0 ? now - state$1.lastRouteEnterTime : 0;
  const stayed = clampUrlrefStaySec(deltaStay);
  if (state$1.lastRoute && opts.enablePageLog !== false) {
    const exitedUrl = state$1.lastRouteFull || state$1.lastRoute;
    const ref2 = state$1.beforeLastRouteFull || state$1.beforeLastRoute || "";
    const snap = state$1.lastPageTitleSnap;
    const payload = {
      lt: LT.Page,
      t: now,
      url: exitedUrl,
      urlref_ts: stayed,
      iey: state$1.lastIey,
      ppiey: state$1.prevIey,
      ttn: snap.ttn,
      ttpj: snap.ttpj,
      ttc: snap.ttc
    };
    if (ref2)
      payload.urlref = ref2;
    c.report(payload);
    if (state$1.lastIey) {
      tryRun(() => markEntryDeparted(), void 0);
      state$1.lastIey = false;
    }
  }
  c.report({
    lt: LT.Hide,
    t: now,
    urlref: state$1.lastRoute,
    urlref_ts: stayed
  });
  void c.flush(true).catch((e2) => logger.warn("[uni统计 2.0] flush on hide failed", e2));
}
function handlePageShow(app, vm, opts = {}) {
  const c = safeCollector(app);
  if (!c)
    return;
  if (state$1.pendingBackgroundResume && shouldEarlyConsumeBackgroundResumeInMixin()) {
    tryConsumeBackgroundResume(app, {}, opts, "handlePageShow");
  }
  const now = nowSec();
  const route = tryRun(() => getCurrentRoute(vm), "");
  const url = tryRun(() => getCurrentRouteWithQuery(vm), "") || route;
  if (!route && !url)
    return;
  const result = tryRun(() => ensureSession("page_show", { now }), null);
  if (!result)
    return;
  tryRun(() => setReportTitle(""), void 0);
  tryRun(() => setConfigTitle(getPagesJsonNavigationTitle(route)), void 0);
  if (result.isNew) {
    tryRun(() => clearEntry(), void 0);
  }
  if (route) {
    tryRun(() => markEntryPage(route), void 0);
  }
  if (result.isNew) {
    reportNewSession(c, result.cst || CST.PageInactiveTimeout, "", now, false, url);
  }
  const shouldSuppressPageLog = state$1.suppressNextPageLogAfterResume;
  if (state$1.lastRoute && opts.enablePageLog !== false && !shouldSuppressPageLog) {
    const deltaStay = state$1.lastRouteEnterTime > 0 ? now - state$1.lastRouteEnterTime : 0;
    const stayed = clampUrlrefStaySec(deltaStay);
    const exitedUrl = state$1.lastRouteFull || state$1.lastRoute;
    const ref2 = state$1.beforeLastRouteFull || state$1.beforeLastRoute || "";
    const snap = state$1.lastPageTitleSnap;
    const payload = {
      lt: LT.Page,
      t: now,
      url: exitedUrl,
      urlref_ts: stayed,
      // 离开页是否入口页 / urlref 指向页是否入口页（进入新页前状态尚未被本轮覆盖）。
      iey: state$1.lastIey,
      ppiey: state$1.prevIey
    };
    if (ref2)
      payload.urlref = ref2;
    payload.ttn = snap.ttn;
    payload.ttpj = snap.ttpj;
    payload.ttc = snap.ttc;
    c.report(payload);
    if (state$1.lastIey) {
      tryRun(() => markEntryDeparted(), void 0);
    }
  }
  state$1.beforeLastRoute = state$1.lastRoute;
  state$1.beforeLastRouteFull = state$1.lastRouteFull;
  state$1.prevIey = state$1.lastIey;
  state$1.lastIey = !!route && tryRun(() => isEntryForIey(route), false);
  state$1.lastRoute = route;
  state$1.lastRouteFull = url;
  state$1.lastRouteEnterTime = now;
  state$1.suppressNextPageLogAfterResume = false;
  scheduleDeferredTitleSnapshot();
  state$1.isHide = false;
  if (result.isNew) {
    void c.flush(true).catch((e2) => logger.warn("[uni统计 2.0] flush after new session (page_show) failed", e2));
  }
}
function handlePageHide(app, _vm) {
  const c = safeCollector(app);
  if (!c)
    return;
  state$1.isHide = true;
  titleSnapGeneration++;
  state$1.lastPageTitleSnap = Object.assign({}, getCurrentTitle());
  tryRun(() => clearPageTitle(), void 0);
}
const rethrownErrors = typeof WeakSet === "function" ? /* @__PURE__ */ new WeakSet() : (
  // 极端环境降级：has=false 永不命中，add=noop；本模块只用 has/add 两个方法，
  // 其它方法（delete / [Symbol.toStringTag]）调用方不依赖，类型断言即可。
  {
    has: () => false,
    add: () => rethrownErrors
  }
);
function handleError(app, e2) {
  const isObj = typeof e2 === "object" && e2 !== null;
  if (isObj && rethrownErrors.has(e2))
    return;
  if (isObj)
    rethrownErrors.add(e2);
  try {
    app.reportError(e2);
  } catch (err) {
    logger.warn("[uni统计 2.0] handleError failed", err);
  }
  if (isMp()) {
    return;
  }
  tryRun(() => {
    setTimeout(() => {
      throw e2;
    }, 0);
  }, void 0);
}
function getUni$6() {
  const u = resolveUniRuntime();
  return u != null && typeof u === "object" ? u : void 0;
}
function shouldMixinDispatchAppLifecycle() {
  let result = isH5() || getPlatform() === "n" || isNvue();
  result = isH5() || getPlatform() === "n" || isNvue();
  return result;
}
function shouldBindUniAppLifecycle() {
  let result = !isH5() && getPlatform() !== "n" && !isNvue();
  result = !isH5() && getPlatform() !== "n" && !isNvue();
  return result;
}
const uniAppHookRegistry = {
  showBound: false,
  hideBound: false,
  appShowCb: void 0,
  appHideCb: void 0
};
function tryBindUniAppLifecycle(app, opts = {}) {
  if (!shouldBindUniAppLifecycle())
    return false;
  const u = getUni$6();
  if (!u)
    return false;
  if (!uniAppHookRegistry.showBound && typeof u.onAppShow === "function") {
    uniAppHookRegistry.appShowCb = (e2) => handleAppShow(app, e2 !== null && e2 !== void 0 ? e2 : {}, opts);
    tryRun(() => u.onAppShow(uniAppHookRegistry.appShowCb), void 0);
    uniAppHookRegistry.showBound = true;
  }
  if (!uniAppHookRegistry.hideBound && typeof u.onAppHide === "function") {
    uniAppHookRegistry.appHideCb = () => handleAppHide(app, opts);
    tryRun(() => u.onAppHide(uniAppHookRegistry.appHideCb), void 0);
    uniAppHookRegistry.hideBound = true;
  }
  return uniAppHookRegistry.showBound && uniAppHookRegistry.hideBound;
}
function unbindUniAppLifecycle() {
  if (!uniAppHookRegistry.showBound && !uniAppHookRegistry.hideBound)
    return;
  const cur = getUni$6();
  if (uniAppHookRegistry.showBound && uniAppHookRegistry.appShowCb && (cur === null || cur === void 0 ? void 0 : cur.offAppShow)) {
    tryRun(() => cur.offAppShow(uniAppHookRegistry.appShowCb), void 0);
  }
  if (uniAppHookRegistry.hideBound && uniAppHookRegistry.appHideCb && (cur === null || cur === void 0 ? void 0 : cur.offAppHide)) {
    tryRun(() => cur.offAppHide(uniAppHookRegistry.appHideCb), void 0);
  }
  uniAppHookRegistry.showBound = false;
  uniAppHookRegistry.hideBound = false;
  uniAppHookRegistry.appShowCb = void 0;
  uniAppHookRegistry.appHideCb = void 0;
}
function bindLifecycle(app, opts = {}) {
  let bound = true;
  const mixin = {
    onLaunch(options = {}) {
      handleLaunch(app, options, opts);
    },
    onLoad() {
    },
    onShow() {
      const vmType = getPageVmType(this);
      cancelPageAppHideDefer();
      if (state$1.pendingBackgroundResume && shouldEarlyConsumeBackgroundResumeInMixin()) {
        tryConsumeBackgroundResume(app, {}, opts, "mixin.onShow");
      }
      state$1.isHide = false;
      if (vmType === "page") {
        handlePageShow(app, this, opts);
      }
      if (shouldMixinDispatchAppLifecycle() && vmType === "app") {
        handleAppShow(app, {}, opts);
      }
    },
    onHide() {
      state$1.isHide = true;
      if (getPageVmType(this) === "page") {
        handlePageHide(app);
        tryVue3AppHideFromPageOnHide(app, opts);
      }
      if (shouldMixinDispatchAppLifecycle() && getPageVmType(this) === "app" && !state$1.pendingBackgroundResume) {
        handleAppHide(app, opts);
      }
    },
    onUnload() {
      if (state$1.isHide) {
        state$1.isHide = false;
        return;
      }
      handlePageHide(app);
    },
    onError(e2) {
      handleError(app, e2);
    }
  };
  if (shouldBindUniAppLifecycle()) {
    tryBindUniAppLifecycle(app, opts);
  }
  return {
    mixin,
    tryBindUniAppHooks: () => shouldBindUniAppLifecycle() && tryBindUniAppLifecycle(app, opts),
    unbind() {
      if (!bound)
        return;
      bound = false;
      unbindUniAppLifecycle();
    }
  };
}
const STAT_VERSION_PUBLIC = "5.13";
const STAT_URL = "https://tongji.dcloud.io/uni/stat";
const STAT_H5_URL = "https://tongji.dcloud.io/uni/stat.gif";
const REPORT_INTERVAL_SEC = 10;
const HTTP_MAX_RETRIES = 3;
const CLOUD_MAX_RETRIES = 2;
const IMAGE_MAX_RETRIES = 2;
const RETRY_BASE_DELAY_MS = 1e3;
const MP_WEIXIN_USE_PRELOAD_ASSETS_REPORT = true;
const MP_WEIXIN_PRELOAD_TIMEOUT_MS = 3e4;
const MP_WEIXIN_PRELOAD_FIRST_FLUSH_DELAY_MS = 2e3;
const SINGLE_EVENT_MAX_BYTES = 4 * 1024;
const BATCH_REQUESTS_MAX_BYTES = 4 * 1024;
const BATCH_MAX_EVENTS = 30;
const QUEUE_MAX_EVENTS = 1e3;
const RETRY_MAX_ATTEMPTS = 5;
const IMAGE_REPORT_DEFAULTS = {
  host: "https://tongji-collector.dcloud.net.cn",
  /** 正式环境 */
  projectId: "964f0397-af5d-45bf-99d6-8fb3500d7849",
  topicId: "8563e231-f4cd-4ab0-8870-917e4b04e810"
  // 以下为历史测试环境（已停用，勿删便于回切排查）
  // projectId: '9fad19a2-b7f1-47f5-87ff-8621f545ab61',
  // topicId: '99b55c91-ed80-406e-b205-e9d18aca744d',
};
function getAppId$1() {
  var _a;
  return (_a = "__UNI__4FA356E") !== null && _a !== void 0 ? _a : "";
}
function assertCloudResultOk(res) {
  if (!res || typeof res !== "object")
    return;
  const r = res;
  if (r.success === false) {
    throw new Error("cloud receiver reported success=false");
  }
  if (typeof r.errCode === "number" && r.errCode !== 0) {
    throw new Error("cloud receiver reported errCode=" + String(r.errCode));
  }
}
function resolveSpace(injected) {
  if (injected)
    return injected;
  const raw = resolveUniRuntime();
  const u = raw != null && typeof raw === "object" ? raw : void 0;
  return u === null || u === void 0 ? void 0 : u.__stat_uniCloud_space;
}
function createCloudChannel(opts = {}) {
  var _a, _b;
  const receiverName = (_a = opts.receiverName) !== null && _a !== void 0 ? _a : "uni-stat-receiver";
  const maxRetries = (_b = opts.maxRetries) !== null && _b !== void 0 ? _b : CLOUD_MAX_RETRIES;
  function getReceiver() {
    const space = resolveSpace(opts.uniCloudSpace);
    if (!space || typeof space.importObject !== "function")
      return void 0;
    try {
      return space.importObject(receiverName, { customUI: true });
    } catch (e2) {
      logger.warn("[uni统计 2.0] cloud importObject threw", e2);
      return void 0;
    }
  }
  function once2(payload) {
    const receiver = getReceiver();
    if (!receiver || typeof receiver.report !== "function") {
      return Promise.reject(new Error("uniCloud space unavailable"));
    }
    return Promise.resolve(receiver.report(payload)).then((res) => {
      assertCloudResultOk(res);
    });
  }
  return {
    name: "2.0",
    available() {
      const space = resolveSpace(opts.uniCloudSpace);
      return !!(space && typeof space.importObject === "function");
    },
    send(payload) {
      return __awaiter(this, void 0, void 0, function* () {
        try {
          yield withRetry(() => once2(payload), {
            times: maxRetries,
            baseDelayMs: RETRY_BASE_DELAY_MS,
            sleep: opts.sleep
          });
        } catch (e2) {
          logger.warn("[uni统计 2.0] 统计上报失败（云函数已重试）", e2);
          throw e2;
        }
      });
    }
  };
}
function getActionLabel(lt) {
  switch (lt) {
    case LT.Launch:
      return "应用启动";
    case LT.Hide:
      return "应用进入后台";
    case LT.Page:
      return "页面切换";
    case LT.Event:
      return "事件触发";
    case LT.Error:
      return "应用错误";
    case LT.Push:
      return "PUSH 设备标识";
    default:
      return `未知事件 (lt=${String(lt !== null && lt !== void 0 ? lt : "?")})`;
  }
}
function bucketSize(bucket) {
  let n2 = 0;
  for (const lt of Object.keys(bucket)) {
    const arr = bucket[lt];
    if (Array.isArray(arr))
      n2 += arr.length;
  }
  return n2;
}
function bucketSummary(bucket) {
  const parts = [];
  for (const lt of Object.keys(bucket)) {
    const arr = bucket[lt];
    if (Array.isArray(arr) && arr.length > 0) {
      parts.push(`lt=${lt}×${arr.length}`);
    }
  }
  return parts.join(", ") || "<空>";
}
function logCollect(data) {
  if (!logger.isDebug())
    return;
  const lt = data.lt;
  const label = getActionLabel(lt);
  logger.debug(`=== 统计数据采集：${label} (lt=${String(lt !== null && lt !== void 0 ? lt : "?")}) ===`);
  logger.debug(data);
  logger.debug("=== 采集结束 ===");
}
function logBoot(info) {
  if (!logger.isDebug())
    return;
  const timeoutParts = [];
  if (info.backgroundTimeoutSec != null) {
    timeoutParts.push(`后台超时(新会话): ${info.backgroundTimeoutSec}s`);
  }
  if (info.pageInactiveTimeoutSec != null) {
    timeoutParts.push(`前台无操作超时: ${info.pageInactiveTimeoutSec}s`);
  }
  const timeoutSeg = timeoutParts.length > 0 ? ` | ${timeoutParts.join(" | ")}` : "";
  const lines = [
    "=== uni统计 2.0 已启用 ===",
    `上报间隔: ${info.reportIntervalSec}s${timeoutSeg} | 应用APPID: ${info.ak || "<未注入>"}${info.appName ? ` | 应用名: ${info.appName}` : ""}${info.vueMode ? ` | ${info.vueMode}` : ""}`
  ];
  if (info.debugFromManifest) {
    lines.push("调试模式：已从 manifest.uniStatistics.debug 自动开启");
  }
  lines.push("=== 后续将在每次采集 / 上报时输出过程日志 ===");
  logger.debug(lines.join("\n"));
}
function logReportStart(info) {
  if (!logger.isDebug())
    return;
  const total = bucketSize(info.bucket);
  const summary = bucketSummary(info.bucket);
  logger.debug(`=== 准备上报：共 ${total} 条事件 (${summary}) ===`);
}
function logReportFailureReason(info) {
  if (!logger.isDebug())
    return;
  logger.debug(`原因: ${describeError(info.error)}`);
  if (info.persistedId) {
    logger.debug(`已暂存重试队列 [retryId=${info.persistedId}]，下次启动自动续传`);
  } else {
    logger.debug("未能写入重试队列：本批数据已丢弃");
  }
}
function logReportSummary(info) {
  if (!logger.isDebug())
    return;
  if (info.failedCount === 0) {
    logger.debug(`=== 上报成功： ${info.okCount} 条事件已送达, 用时 ${info.elapsedMs}ms ===`);
  } else if (info.okCount === 0) {
    logger.debug(`=== 上报失败： ${info.failedCount} 条事件未送达, 用时 ${info.elapsedMs}ms ===`);
  } else {
    logger.debug(`=== 上报完成：成功 ${info.okCount} 条，失败 ${info.failedCount} 条，用时 ${info.elapsedMs}ms ===`);
  }
}
function logNoChannel(info) {
  if (!logger.isDebug())
    return;
  logger.debug(`=== 上报跳过：当前无可用通道，已回滚 ${bucketSize(info.bucket)} 条事件入队 ===`);
}
function logRecoverStart(count) {
  if (!logger.isDebug())
    return;
  logger.debug(`=== 冷启续传：发现 ${count} 条历史 payload，开始逐条重发 ===`);
}
function logRecoverItem(info) {
  if (!logger.isDebug())
    return;
  if (info.ok) {
    logger.debug(`续传成功 (${info.index}/${info.total})`);
  } else {
    logger.debug(`续传失败 (${info.index}/${info.total})：${describeError(info.error)}`);
  }
}
function describeError(e2) {
  if (!e2)
    return "<无错误对象>";
  if (e2 instanceof Error) {
    return `${e2.name}: ${e2.message}`;
  }
  if (typeof e2 === "string")
    return e2;
  return safeStringify(e2) || String(e2);
}
function omitEmptyStringFieldsForUpload(data) {
  const out = {};
  for (const key of Object.keys(data)) {
    const v = data[key];
    if (v === "")
      continue;
    out[key] = v;
  }
  return out;
}
const LT_ORDER = {
  "1": 1,
  "11": 2,
  "21": 3,
  "31": 4,
  "101": 5,
  "3": 100
};
const UNKNOWN_LT_WEIGHT = 50;
function handleData(buckets) {
  return JSON.stringify(flatten(buckets));
}
function flatten(buckets) {
  const ltKeys = Object.keys(buckets);
  ltKeys.sort((a, b) => weightOf(a) - weightOf(b));
  const out = [];
  for (let i = 0; i < ltKeys.length; i++) {
    const lt = ltKeys[i];
    const list = buckets[lt];
    if (!list || list.length === 0)
      continue;
    for (let j = 0; j < list.length; j++)
      out.push(list[j]);
  }
  return out;
}
function weightOf(lt) {
  const w = LT_ORDER[lt];
  return typeof w === "number" ? w : UNKNOWN_LT_WEIGHT;
}
function chunkEvents(events, opts = {}) {
  var _a, _b;
  const maxEvents2 = (_a = opts.maxEvents) !== null && _a !== void 0 ? _a : Infinity;
  const maxBytes = (_b = opts.maxBytes) !== null && _b !== void 0 ? _b : Infinity;
  const out = [];
  if (!Array.isArray(events) || events.length === 0)
    return out;
  const safeMaxEvents = maxEvents2 > 0 ? maxEvents2 : Infinity;
  const safeMaxBytes = maxBytes > 0 ? maxBytes : Infinity;
  let cur = [];
  let curBytes = 2;
  for (let i = 0; i < events.length; i++) {
    const e2 = events[i];
    let s2 = "";
    try {
      s2 = JSON.stringify(e2);
    } catch (_c) {
      continue;
    }
    const inc = cur.length === 0 ? s2.length : s2.length + 1;
    const wouldExceed = cur.length >= safeMaxEvents || cur.length > 0 && curBytes + inc > safeMaxBytes;
    if (wouldExceed) {
      out.push(cur);
      cur = [];
      curBytes = 2;
    }
    cur.push(e2);
    curBytes += cur.length === 1 ? s2.length : s2.length + 1;
  }
  if (cur.length > 0)
    out.push(cur);
  return out;
}
function handleDataChunked(buckets, opts = {}) {
  const events = flatten(buckets);
  if (events.length === 0)
    return [];
  const chunks = chunkEvents(events, opts);
  const out = [];
  for (let i = 0; i < chunks.length; i++) {
    out.push(JSON.stringify(chunks[i]));
  }
  return out;
}
class PermanentChannelError extends Error {
  constructor(message) {
    super(message);
    this.permanent = true;
    this.name = "PermanentChannelError";
    Object.setPrototypeOf(this, PermanentChannelError.prototype);
  }
}
function isPermanentChannelError(err) {
  if (!err || typeof err !== "object")
    return false;
  if (err instanceof PermanentChannelError)
    return true;
  const e2 = err;
  if (e2.name === "PermanentChannelError")
    return true;
  if (e2.permanent === true)
    return true;
  return false;
}
function defaultGenPayloadId(nowMs2) {
  return "p-" + nowMs2.toString(36) + "-" + Math.random().toString(36).slice(2, 6);
}
function createCollector(deps) {
  let firstFlushDone = false;
  let deferredFlushTimer = null;
  function cancelDeferredFlush() {
    if (deferredFlushTimer == null)
      return;
    clearTimeout(deferredFlushTimer);
    deferredFlushTimer = null;
  }
  function triggerAutoFlush() {
    var _a;
    const deferMs = Math.max(0, Math.floor((_a = deps.firstFlushDeferMs) !== null && _a !== void 0 ? _a : 0));
    if (!firstFlushDone && deferMs > 0) {
      if (deferredFlushTimer != null)
        return;
      deferredFlushTimer = setTimeout(() => {
        deferredFlushTimer = null;
        firstFlushDone = true;
        void flushImpl(false).catch((e2) => logger.warn("[uni统计 2.0] auto-flush failed", e2));
      }, deferMs);
      return;
    }
    firstFlushDone = true;
    void flushImpl(false).catch((e2) => logger.warn("[uni统计 2.0] auto-flush failed", e2));
  }
  function report(input) {
    tryRun(() => {
      const t2 = typeof input.t === "number" ? input.t : deps.nowSec();
      const snap = deps.session.getSnapshot();
      let sessionForCtx;
      if (snap) {
        const seq = deps.session.nextSeq();
        sessionForCtx = Object.assign({}, snap, { seq });
      }
      if (snap && input.lt === LT.Event && deps.session.touch) {
        deps.session.touch(t2);
      }
      const ctx = Object.assign({}, input, {
        t: t2,
        session: sessionForCtx
      });
      const data = deps.builder.build(ctx);
      logCollect(data);
      deps.queue.enqueue(omitEmptyStringFieldsForUpload(data));
      if (deps.queue.shouldFlush()) {
        triggerAutoFlush();
      }
    }, void 0);
  }
  function flushImpl() {
    return __awaiter(this, arguments, void 0, function* (force = false) {
      var _a, _b, _c, _d, _e;
      if (!deps.queue.shouldFlush(force))
        return;
      const snapshot = deps.queue.flush();
      if (!snapshot)
        return;
      const channel = deps.selectChannel();
      if (!channel) {
        logger.warn("[uni统计 2.0] 无可用上报线路，本批已回滚队列");
        logNoChannel({ bucket: snapshot });
        deps.queue.rollback(snapshot);
        return;
      }
      const globalMaxBytes = (_b = (_a = deps.batchLimits) === null || _a === void 0 ? void 0 : _a.maxBytes) !== null && _b !== void 0 ? _b : BATCH_REQUESTS_MAX_BYTES;
      const channelMaxBytes = typeof channel.maxRequestBytes === "function" ? channel.maxRequestBytes() : Number.POSITIVE_INFINITY;
      const limits = {
        maxEvents: (_d = (_c = deps.batchLimits) === null || _c === void 0 ? void 0 : _c.maxEvents) !== null && _d !== void 0 ? _d : BATCH_MAX_EVENTS,
        maxBytes: Math.min(globalMaxBytes, channelMaxBytes)
      };
      const chunks = handleDataChunked(snapshot, limits);
      if (chunks.length === 0) {
        logger.warn("[uni统计 2.0] flush 切片结果为空，已回滚队列", snapshot);
        deps.queue.rollback(snapshot);
        return;
      }
      const startMs = deps.nowMs();
      let totalCount = 0;
      for (const lt of Object.keys(snapshot)) {
        const arr = snapshot[lt];
        if (Array.isArray(arr))
          totalCount += arr.length;
      }
      logReportStart({ channel: channel.name, bucket: snapshot });
      const hasLaunch = Array.isArray(snapshot["1"]) && snapshot["1"].length > 0;
      let okEvents = 0;
      let failedEvents = 0;
      let allOk = true;
      let firstChunkOk = true;
      for (let i = 0; i < chunks.length; i++) {
        const requests = chunks[i];
        const payload = {
          usv: deps.config.usv,
          t: deps.nowSec(),
          requests,
          _id: ((_e = deps.genPayloadId) !== null && _e !== void 0 ? _e : () => defaultGenPayloadId(deps.nowMs()))()
        };
        const sliceEvents = countEvents(requests);
        try {
          yield channel.send(payload);
          okEvents += sliceEvents;
        } catch (e2) {
          allOk = false;
          if (i === 0)
            firstChunkOk = false;
          failedEvents += sliceEvents;
          if (isPermanentChannelError(e2)) {
            logger.warn("[uni统计 2.0] 统计上报失败（本批已丢弃，不可重试）", e2, "sliceBytes=" + requests.length);
            logReportFailureReason({ error: e2, persistedId: void 0 });
            continue;
          }
          logger.warn("[uni统计 2.0] 统计上报失败（已暂存，下次启动自动重试）", e2);
          const id = deps.retry.persist(payload);
          if (!id) {
            logger.warn("[uni统计 2.0] 统计暂存重试失败（无 retryId），本批已丢弃");
          }
          logReportFailureReason({ error: e2, persistedId: id });
        }
      }
      const visitAccepted = hasLaunch ? firstChunkOk : allOk;
      if (visitAccepted) {
        tryRun(() => deps.visit.commitVisitOnAck(deps.nowSec()), void 0);
      } else {
        tryRun(() => deps.visit.rollbackPendingVisit(), void 0);
      }
      logReportSummary({
        channel: channel.name,
        okCount: okEvents,
        failedCount: failedEvents,
        elapsedMs: deps.nowMs() - startMs
      });
    });
  }
  function countEvents(requests) {
    try {
      const arr = JSON.parse(requests);
      return Array.isArray(arr) ? arr.length : 0;
    } catch (_a) {
      return 0;
    }
  }
  function recoverRetry() {
    return __awaiter(this, void 0, void 0, function* () {
      const items = deps.retry.loadAll();
      if (items.length === 0)
        return;
      const channel = deps.selectChannel();
      if (!channel) {
        logger.warn("[uni统计 2.0] 续传重试跳过：当前无可用上报线路");
        return;
      }
      logRecoverStart(items.length);
      let i = 0;
      for (const payload of items) {
        i++;
        try {
          yield channel.send(payload);
          if (payload._id)
            deps.retry.ack(payload._id);
          logRecoverItem({
            index: i,
            total: items.length,
            payloadId: payload._id,
            ok: true
          });
        } catch (e2) {
          if (isPermanentChannelError(e2)) {
            if (payload._id)
              deps.retry.ack(payload._id);
            logger.warn("[uni统计 2.0] 续传重试失败（不可重试，已从队列移除）", e2, "id=" + payload._id);
            logRecoverItem({
              index: i,
              total: items.length,
              payloadId: payload._id,
              ok: false,
              error: e2
            });
            continue;
          }
          if (payload._id && deps.retry.markAttempt) {
            deps.retry.markAttempt(payload._id);
          }
          logger.warn("[uni统计 2.0] 续传重试失败（保留队列，下次启动再试）", e2);
          logRecoverItem({
            index: i,
            total: items.length,
            payloadId: payload._id,
            ok: false,
            error: e2
          });
        }
      }
    });
  }
  function flush2() {
    return __awaiter(this, arguments, void 0, function* (force = false) {
      cancelDeferredFlush();
      firstFlushDone = true;
      return flushImpl(force);
    });
  }
  function destroy() {
    cancelDeferredFlush();
    firstFlushDone = true;
  }
  return { report, flush: flush2, recoverRetry, destroy };
}
function getUni$5() {
  const u = resolveUniRuntime();
  return u != null && typeof u === "object" ? u : void 0;
}
function toQuery(payload) {
  const out = [];
  out.push("usv=" + encodeURIComponent(String(payload.usv)));
  out.push("t=" + encodeURIComponent(String(payload.t)));
  out.push("requests=" + encodeURIComponent(payload.requests));
  return out.join("&");
}
function tryImageRequest(payload, h5Url = STAT_H5_URL) {
  const ImageCtor = getGlobalObject().Image;
  if (typeof ImageCtor !== "function")
    return false;
  return tryRun(() => {
    const img = new ImageCtor();
    img.src = h5Url + "?" + toQuery(payload);
    return true;
  }, false);
}
function createHttpChannel(opts = {}) {
  var _a, _b, _c, _d, _e;
  const url = (_a = opts.url) !== null && _a !== void 0 ? _a : STAT_URL;
  const h5Url = (_b = opts.h5Url) !== null && _b !== void 0 ? _b : STAT_H5_URL;
  const ut = (_c = opts.ut) !== null && _c !== void 0 ? _c : "";
  const timeoutMs = (_d = opts.timeoutMs) !== null && _d !== void 0 ? _d : 1e4;
  const maxRetries = (_e = opts.maxRetries) !== null && _e !== void 0 ? _e : HTTP_MAX_RETRIES;
  function once2(payload) {
    if (ut === "h5" && opts.preferImageOnH5 !== false) {
      if (tryImageRequest(payload, h5Url))
        return Promise.resolve();
    }
    const u = getUni$5();
    if (!u || typeof u.request !== "function") {
      return Promise.reject(new Error("uni.request unavailable"));
    }
    return new Promise((resolve, reject) => {
      let settled = false;
      const timer = setTimeout(() => {
        if (settled)
          return;
        settled = true;
        reject(new Error("http timeout"));
      }, timeoutMs);
      u.request({
        url,
        method: "POST",
        data: payload,
        timeout: timeoutMs,
        success: (res) => {
          var _a2;
          if (settled)
            return;
          settled = true;
          clearTimeout(timer);
          const code = (_a2 = res === null || res === void 0 ? void 0 : res.statusCode) !== null && _a2 !== void 0 ? _a2 : 0;
          if (code >= 200 && code < 300)
            resolve();
          else
            reject(new Error("http status " + code));
        },
        fail: (e2) => {
          if (settled)
            return;
          settled = true;
          clearTimeout(timer);
          reject(e2 instanceof Error ? e2 : new Error(String(e2)));
        }
      });
    });
  }
  return {
    name: "1.0",
    available() {
      const u = getUni$5();
      return !!(u && typeof u.request === "function");
    },
    send(payload) {
      return __awaiter(this, void 0, void 0, function* () {
        try {
          yield withRetry(() => once2(payload), {
            times: maxRetries,
            baseDelayMs: RETRY_BASE_DELAY_MS,
            sleep: opts.sleep
          });
        } catch (e2) {
          logger.warn("[uni统计 2.0] 统计上报失败（HTTP 已重试）", e2);
          throw e2;
        }
      });
    }
  };
}
const WEBTRACK_API_PATH = "/WebTrack";
const WEBTRACK_BEACON_PATH = "/WebTrack.gif";
function getUni$4() {
  const u = resolveUniRuntime();
  return u != null && typeof u === "object" ? u : void 0;
}
const REPORT_URL_BASE_OVERHEAD = 256;
const REPORT_ENCODE_RATIO = 3;
function buildStatReportUrl(payload, opts) {
  var _a;
  const t2 = ((_a = opts.nowMs) !== null && _a !== void 0 ? _a : () => Date.now())();
  const logs = encodeURIComponent(payload.requests);
  const host2 = opts.host.replace(/\/+$/, "");
  return host2 + opts.path + "?ProjectId=" + encodeURIComponent(opts.projectId) + "&TopicId=" + encodeURIComponent(opts.topicId) + "&Logs=" + logs + "&Source=webImg&Time=" + t2;
}
function summarizeHttpErrorBody(data, maxLen = 320) {
  if (data == null)
    return "";
  if (typeof data === "string") {
    return data.length <= maxLen ? data : data.slice(0, maxLen) + "…";
  }
  try {
    const s2 = JSON.stringify(data);
    return s2.length <= maxLen ? s2 : s2.slice(0, maxLen) + "…";
  } catch (_a) {
    return String(data).slice(0, maxLen);
  }
}
function imageBeaconAwait(url, ms) {
  const ImageCtor = getGlobalObject().Image;
  if (typeof ImageCtor !== "function") {
    return Promise.reject(new PermanentChannelError("当前环境无法完成统计上报"));
  }
  return new Promise((resolve, reject) => {
    let settled = false;
    const timer = setTimeout(() => {
      if (settled)
        return;
      settled = true;
      reject(new Error("统计上报超时"));
    }, ms);
    const img = new ImageCtor();
    img.onload = () => {
      if (settled)
        return;
      settled = true;
      clearTimeout(timer);
      resolve();
    };
    img.onerror = () => {
      if (settled)
        return;
      settled = true;
      clearTimeout(timer);
      resolve();
    };
    img.src = url;
  });
}
function fetchBeaconAwait(url, ms) {
  const g = getGlobalObject();
  const fetchFn = g.fetch;
  if (typeof fetchFn !== "function") {
    return Promise.reject(new Error("fetch unavailable"));
  }
  const controller = typeof g.AbortController === "function" ? new g.AbortController() : void 0;
  return new Promise((resolve, reject) => {
    let settled = false;
    const timer = setTimeout(() => {
      if (settled)
        return;
      settled = true;
      if (controller)
        tryRun(() => controller.abort(), void 0);
      reject(new Error("统计上报超时"));
    }, ms);
    fetchFn(url, {
      method: "GET",
      keepalive: true,
      credentials: "omit",
      signal: controller ? controller.signal : void 0
    }).then((res) => {
      if (settled)
        return;
      settled = true;
      clearTimeout(timer);
      if (res && res.ok) {
        resolve();
        return;
      }
      reject(new Error("统计上报 HTTP " + (res ? res.status : 0)));
    }, (e2) => {
      if (settled)
        return;
      settled = true;
      clearTimeout(timer);
      reject(e2 instanceof Error ? e2 : new Error(String(e2)));
    });
  });
}
function getWxPreloadAssets() {
  const wx2 = getGlobalObject().wx;
  return typeof (wx2 === null || wx2 === void 0 ? void 0 : wx2.preloadAssets) === "function" ? wx2.preloadAssets : void 0;
}
function formatWxPreloadFail(err) {
  if (err instanceof Error)
    return err;
  if (err != null && typeof err === "object" && "errMsg" in err) {
    const msg = err.errMsg;
    if (typeof msg === "string" && msg.length > 0)
      return new Error(msg);
  }
  if (err == null)
    return new Error("preloadAssets fail (empty err)");
  return new Error(String(err));
}
function mpWeixinPreloadAssetsBeaconAwait(url, ms, preload) {
  return new Promise((resolve, reject) => {
    let settled = false;
    const timer = setTimeout(() => {
      if (settled)
        return;
      settled = true;
      reject(new Error("统计上报超时(preloadAssets)"));
    }, ms);
    try {
      preload({
        data: [{ type: "image", src: url }],
        success: () => {
          if (settled)
            return;
          settled = true;
          clearTimeout(timer);
          resolve();
        },
        fail: (err) => {
          if (settled)
            return;
          settled = true;
          clearTimeout(timer);
          reject(formatWxPreloadFail(err));
        }
      });
    } catch (e2) {
      if (settled)
        return;
      settled = true;
      clearTimeout(timer);
      reject(e2 instanceof Error ? e2 : new Error(String(e2)));
    }
  });
}
function isMpWeixinPreloadEnabled(opts) {
  var _a, _b;
  const enabled2 = (_a = opts.mpWeixinPreloadReport) !== null && _a !== void 0 ? _a : MP_WEIXIN_USE_PRELOAD_ASSETS_REPORT;
  if (!enabled2)
    return false;
  const raw = (_b = opts.rawPlatform) !== null && _b !== void 0 ? _b : getRawPlatform();
  return raw === "mp-weixin";
}
function createImageChannel(opts = {}) {
  var _a, _b, _c, _d, _e, _f, _g;
  const host2 = (_a = opts.host) !== null && _a !== void 0 ? _a : IMAGE_REPORT_DEFAULTS.host;
  const projectId = (_b = opts.projectId) !== null && _b !== void 0 ? _b : IMAGE_REPORT_DEFAULTS.projectId;
  const topicId = (_c = opts.topicId) !== null && _c !== void 0 ? _c : IMAGE_REPORT_DEFAULTS.topicId;
  const timeoutMs = (_d = opts.timeoutMs) !== null && _d !== void 0 ? _d : 1e4;
  const maxRetries = (_e = opts.maxRetries) !== null && _e !== void 0 ? _e : IMAGE_MAX_RETRIES;
  const maxUrlLength = (_f = opts.maxUrlLength) !== null && _f !== void 0 ? _f : 6 * 1024;
  const preferBeacon = opts.preferImageBeacon !== false;
  const nowMs2 = opts.nowMs;
  const ut = (_g = opts.ut) !== null && _g !== void 0 ? _g : "";
  const isH52 = ut === "h5";
  const mpWeixinPreload = isMpWeixinPreloadEnabled(opts);
  function configured() {
    return !!(host2 && projectId && topicId);
  }
  const reportOpts = { host: host2, projectId, topicId, nowMs: nowMs2 };
  function preflightUrl(payload, path) {
    if (!configured()) {
      throw new PermanentChannelError("统计上报未配置：请设置 TLS host、projectId、topicId");
    }
    const url = buildStatReportUrl(payload, {
      host: reportOpts.host,
      projectId: reportOpts.projectId,
      topicId: reportOpts.topicId,
      nowMs: reportOpts.nowMs,
      path
    });
    if (url.length > maxUrlLength) {
      throw new PermanentChannelError("统计上报 URL 过长: " + url.length + " > " + maxUrlLength);
    }
    return url;
  }
  function webTrackGetViaRequest(url) {
    const u = getUni$4();
    if (!u || typeof u.request !== "function") {
      return Promise.reject(new PermanentChannelError("当前环境无法完成统计上报"));
    }
    return new Promise((resolve, reject) => {
      let settled = false;
      const timer = setTimeout(() => {
        if (settled)
          return;
        settled = true;
        reject(new Error("统计上报超时"));
      }, timeoutMs);
      u.request({
        url,
        method: "GET",
        timeout: timeoutMs,
        success: (res) => {
          var _a2;
          if (settled)
            return;
          settled = true;
          clearTimeout(timer);
          const code = (_a2 = res === null || res === void 0 ? void 0 : res.statusCode) !== null && _a2 !== void 0 ? _a2 : 0;
          if (code >= 200 && code < 300) {
            resolve();
            return;
          }
          const hint = summarizeHttpErrorBody(res === null || res === void 0 ? void 0 : res.data);
          reject(new Error(hint ? `统计上报 HTTP ${code}: ${hint}` : `统计上报 HTTP ${code}`));
        },
        fail: (e2) => {
          if (settled)
            return;
          settled = true;
          clearTimeout(timer);
          reject(e2 instanceof Error ? e2 : new Error(String(e2)));
        }
      });
    });
  }
  function onceH5(payload) {
    const g = getGlobalObject();
    const u = getUni$4();
    const hasRequest = !!(u && typeof u.request === "function");
    if (preferBeacon && typeof g.fetch === "function") {
      return fetchBeaconAwait(preflightUrl(payload, WEBTRACK_BEACON_PATH), timeoutMs);
    }
    if (hasRequest) {
      return webTrackGetViaRequest(preflightUrl(payload, WEBTRACK_API_PATH));
    }
    if (preferBeacon && typeof g.Image === "function") {
      return imageBeaconAwait(preflightUrl(payload, WEBTRACK_BEACON_PATH), timeoutMs);
    }
    return Promise.reject(new PermanentChannelError("当前环境无法完成统计上报"));
  }
  function onceMpWeixin(payload) {
    const preloadFn = getWxPreloadAssets();
    if (preloadFn) {
      return mpWeixinPreloadAssetsBeaconAwait(preflightUrl(payload, WEBTRACK_BEACON_PATH), MP_WEIXIN_PRELOAD_TIMEOUT_MS, preloadFn);
    }
    logger.warn("[uni统计 2.0] wx.preloadAssets 不可用，回退 uni.request GET /WebTrack");
    return webTrackGetViaRequest(preflightUrl(payload, WEBTRACK_API_PATH));
  }
  function dispatchReport(payload) {
    if (isH52)
      return onceH5(payload);
    if (mpWeixinPreload)
      return onceMpWeixin(payload);
    return webTrackGetViaRequest(preflightUrl(payload, WEBTRACK_API_PATH));
  }
  return {
    name: "image",
    available() {
      return configured();
    },
    maxRequestBytes() {
      const raw = (maxUrlLength - REPORT_URL_BASE_OVERHEAD) / REPORT_ENCODE_RATIO;
      return Math.max(512, Math.floor(raw));
    },
    send(payload) {
      return __awaiter(this, void 0, void 0, function* () {
        try {
          yield withRetry(() => dispatchReport(payload), {
            times: maxRetries,
            baseDelayMs: RETRY_BASE_DELAY_MS,
            sleep: opts.sleep
          });
        } catch (e2) {
          if (isPermanentChannelError(e2)) {
            logger.warn("[uni统计 2.0] 统计上报失败（不可重试）", e2);
          } else {
            logger.warn("[uni统计 2.0] 统计上报失败（已重试）", e2);
          }
          throw e2;
        }
      });
    }
  };
}
function s(v, def2 = "") {
  if (typeof v === "string")
    return v;
  if (typeof v === "number" && Number.isFinite(v))
    return String(v);
  return def2;
}
function n(v, def2 = 0) {
  if (typeof v === "number" && Number.isFinite(v))
    return v;
  if (typeof v === "string" && v.length > 0) {
    const x = Number(v);
    if (Number.isFinite(x))
      return x;
  }
  return def2;
}
function createStatDataBuilder(deps) {
  function baseFields() {
    var _a, _b, _c;
    const { config: config2, platform, system, locale, device, net, location, pkg, legacy, web } = deps;
    return {
      ak: s(config2.ak),
      usv: s(config2.usv),
      v: s((_a = config2.v) !== null && _a !== void 0 ? _a : system.appVersion),
      ch: s(config2.ch),
      ut: s(platform.ut),
      p: s((_b = platform.p) !== null && _b !== void 0 ? _b : system.osP),
      on: s(system.on),
      did: s(device.uuid),
      brand: s(system.brand),
      md: s(system.md),
      sv: s(system.sv),
      mpsdk: s(system.sdkVersion),
      mpv: s(system.mpvHostVersion),
      pr: n(locale.pr, 1),
      ww: n(locale.ww),
      wh: n(locale.wh),
      sw: n(locale.sw),
      sh: n(locale.sh),
      lang: s(locale.lang),
      net: s(net.net, "unknown"),
      lat: s(location.lat),
      lng: s(location.lng),
      mpn: s((_c = legacy === null || legacy === void 0 ? void 0 : legacy.mpn) !== null && _c !== void 0 ? _c : pkg.mpn),
      tdaid: s(pkg.tdaid),
      pkn: s(pkg.pkn),
      an: s(pkg.an),
      domain: s(web.domain)
    };
  }
  function sessionFields(ctx) {
    if (!ctx.session)
      return {};
    return {
      sid: ctx.session.sid,
      cst: ctx.session.sct
    };
  }
  function pageFields(ctx) {
    const out = {};
    if (ctx.url !== void 0)
      out.url = s(ctx.url);
    if (ctx.urlref !== void 0)
      out.urlref = s(ctx.urlref);
    if (ctx.urlref_ts !== void 0)
      out.urlref_ts = n(ctx.urlref_ts);
    if (ctx.ttn !== void 0)
      out.ttn = s(ctx.ttn);
    if (ctx.ttpj !== void 0)
      out.ttpj = s(ctx.ttpj);
    if (ctx.ttc !== void 0)
      out.ttc = s(ctx.ttc);
    return out;
  }
  function entryFields(ctx) {
    if (ctx.lt === "11") {
      return {
        iey: toIey(ctx.iey !== void 0 ? ctx.iey : false),
        ppiey: toIey(ctx.ppiey !== void 0 ? ctx.ppiey : false)
      };
    }
    return {};
  }
  function visitFields(ctx) {
    if (ctx.lt !== "1")
      return {};
    if (!ctx.visit)
      return {};
    return {
      fvts: ctx.visit.fvts,
      lvts: ctx.visit.lvts,
      tvc: ctx.visit.tvc
    };
  }
  function launchFields(ctx) {
    if (ctx.lt !== "1")
      return {};
    if (ctx.sc === void 0)
      return {};
    return { sc: s(ctx.sc) };
  }
  function errorFields(ctx) {
    if (ctx.lt !== "31" || !ctx.errMsg)
      return {};
    const ERR_MSG_MAX = 3 * 1024;
    const TRUNC_SUFFIX = "…[truncated]";
    let em = s(ctx.errMsg);
    if (em.length > ERR_MSG_MAX) {
      em = em.slice(0, ERR_MSG_MAX - TRUNC_SUFFIX.length) + TRUNC_SUFFIX;
    }
    return { em };
  }
  function pushFields(ctx) {
    if (ctx.lt !== "101" || !ctx.cid)
      return {};
    return { cid: s(ctx.cid) };
  }
  function build(ctx) {
    const safeCustom = {};
    if (ctx.custom) {
      const reserved = /* @__PURE__ */ new Set([
        "lt",
        "t",
        "sid",
        "cst",
        "did",
        "p",
        "on",
        "mpv",
        "domain",
        "fvts",
        "lvts",
        "tvc",
        "sc"
      ]);
      for (const k of Object.keys(ctx.custom)) {
        if (!reserved.has(k))
          safeCustom[k] = ctx.custom[k];
      }
    }
    const out = { lt: ctx.lt, t: n(ctx.t) };
    Object.assign(out, baseFields(), sessionFields(ctx), pageFields(ctx), entryFields(ctx), visitFields(ctx), launchFields(ctx), errorFields(ctx), pushFields(ctx), safeCustom);
    return out;
  }
  return { build };
}
let cachedStatic = null;
function getUni$3() {
  const u = resolveUniRuntime();
  return u != null && typeof u === "object" ? u : void 0;
}
function mergeWxHostSnapshots() {
  const raw = getRawPlatform();
  if (raw !== "mp-weixin" && raw !== "mp-qq")
    return null;
  const wxHost = getGlobalObject().wx;
  if (!wxHost)
    return null;
  const sync = typeof wxHost.getSystemInfoSync === "function" ? tryRun(() => wxHost.getSystemInfoSync(), null) : null;
  const device = typeof wxHost.getDeviceInfo === "function" ? tryRun(() => wxHost.getDeviceInfo(), null) : null;
  const appBase = typeof wxHost.getAppBaseInfo === "function" ? tryRun(() => wxHost.getAppBaseInfo(), null) : null;
  const windowInfo = typeof wxHost.getWindowInfo === "function" ? tryRun(() => wxHost.getWindowInfo(), null) : null;
  return mergeSystemSnapshots(sync, device, appBase, windowInfo);
}
function mergeSystemSnapshots(...parts) {
  const out = {};
  for (const p2 of parts) {
    if (!p2)
      continue;
    for (const k of Object.keys(p2)) {
      const v = p2[k];
      if (v !== void 0 && v !== null)
        out[k] = v;
    }
  }
  return out;
}
function mergedSystemInfo() {
  const u = getUni$3();
  const sync = u && typeof u.getSystemInfoSync === "function" ? tryRun(() => u.getSystemInfoSync(), null) : null;
  const device = u && typeof u.getDeviceInfo === "function" ? tryRun(() => u.getDeviceInfo(), null) : null;
  const appBase = u && typeof u.getAppBaseInfo === "function" ? tryRun(() => u.getAppBaseInfo(), null) : null;
  const windowInfo = u && typeof u.getWindowInfo === "function" ? tryRun(() => u.getWindowInfo(), null) : null;
  const fromUni = mergeSystemSnapshots(sync, device, appBase, windowInfo);
  const fromWx = mergeWxHostSnapshots();
  const merged = fromWx ? mergeSystemSnapshots(fromUni, fromWx) : fromUni;
  return merged;
}
function resolveUniConfigAppVersion() {
  return tryRun(() => {
    const cfg = getGlobalObject().__uniConfig;
    return typeof (cfg === null || cfg === void 0 ? void 0 : cfg.appVersion) === "string" ? cfg.appVersion : "";
  }, "");
}
function resolveBuildTimeAppVersion() {
  const raw = "1.0.0";
  return typeof raw === "string" ? raw : "";
}
function resolveAppVersionForStat(plus, sys) {
  var _a;
  const fromPlus = (_a = plus === null || plus === void 0 ? void 0 : plus.runtime) === null || _a === void 0 ? void 0 : _a.version;
  if (typeof fromPlus === "string" && fromPlus)
    return fromPlus;
  const fromSys = sys.appVersion;
  if (typeof fromSys === "string" && fromSys)
    return fromSys;
  const fromUniConfig = resolveUniConfigAppVersion();
  if (fromUniConfig)
    return fromUniConfig;
  return resolveBuildTimeAppVersion();
}
function buildOnForStat(sys) {
  const rom = typeof sys.romName === "string" ? sys.romName.trim() : "";
  if (rom) {
    const romVer = typeof sys.romVersion === "string" ? sys.romVersion.trim() : "";
    return romVer ? `${rom} ${romVer}`.trim() : rom;
  }
  return typeof sys.osName === "string" ? sys.osName.trim() : "";
}
function getSystemInfo() {
  var _a, _b, _c, _d, _e, _f, _g, _h, _j, _k, _l, _m, _o, _p, _q, _r, _s, _t;
  if (cachedStatic)
    return cachedStatic;
  const sys = mergedSystemInfo();
  const plus = getGlobalObject().plus;
  const appVersion = resolveAppVersionForStat(plus, sys);
  cachedStatic = {
    brand: (_b = (_a = sys.deviceBrand) !== null && _a !== void 0 ? _a : sys.brand) !== null && _b !== void 0 ? _b : "",
    md: (_d = (_c = sys.deviceModel) !== null && _c !== void 0 ? _c : sys.model) !== null && _d !== void 0 ? _d : "",
    sv: (_f = (_e = sys.osVersion) !== null && _e !== void 0 ? _e : sys.system) !== null && _f !== void 0 ? _f : "",
    v: (_h = (_g = sys.hostVersion) !== null && _g !== void 0 ? _g : sys.version) !== null && _h !== void 0 ? _h : "",
    ut: (_j = sys.deviceType) !== null && _j !== void 0 ? _j : "unknown",
    appVersion,
    appWgtVersion: (_p = (_o = (_l = (_k = plus === null || plus === void 0 ? void 0 : plus.runtime) === null || _k === void 0 ? void 0 : _k.appWgtVersion) !== null && _l !== void 0 ? _l : (_m = plus === null || plus === void 0 ? void 0 : plus.runtime) === null || _m === void 0 ? void 0 : _m.appWgtRevision) !== null && _o !== void 0 ? _o : sys.appWgtVersion) !== null && _p !== void 0 ? _p : "",
    mpvHostVersion: ((_r = (_q = sys.hostVersion) !== null && _q !== void 0 ? _q : sys.version) !== null && _r !== void 0 ? _r : "").trim(),
    on: buildOnForStat(sys),
    sdkVersion: (_t = (_s = sys.hostSDKVersion) !== null && _s !== void 0 ? _s : sys.SDKVersion) !== null && _t !== void 0 ? _t : "",
    statusBarHeight: typeof sys.statusBarHeight === "number" ? sys.statusBarHeight : 0,
    osP: normalizeStatOsP({
      platform: sys.platform,
      osName: sys.osName,
      system: sys.system
    })
  };
  return cachedStatic;
}
function getLocaleAndScreen() {
  var _a, _b;
  const sys = mergedSystemInfo();
  const prRaw = typeof sys.pixelRatio === "number" ? sys.pixelRatio : typeof sys.devicePixelRatio === "number" ? sys.devicePixelRatio : 1;
  return {
    lang: ((_b = (_a = sys.hostLanguage) !== null && _a !== void 0 ? _a : sys.language) !== null && _b !== void 0 ? _b : "").replace(/_/g, "-"),
    ww: typeof sys.windowWidth === "number" ? sys.windowWidth : 0,
    wh: typeof sys.windowHeight === "number" ? sys.windowHeight : 0,
    sw: typeof sys.screenWidth === "number" ? sys.screenWidth : 0,
    sh: typeof sys.screenHeight === "number" ? sys.screenHeight : 0,
    pr: prRaw > 0 ? prRaw : 1
  };
}
let cached$1 = null;
function getUni$2() {
  const u = resolveUniRuntime();
  return u != null && typeof u === "object" ? u : void 0;
}
function getPlus() {
  return getGlobalObject().plus;
}
function getMpTdaid(platform) {
  const u = getUni$2();
  switch (platform) {
    case "wx":
    case "qq": {
      if (typeof (u === null || u === void 0 ? void 0 : u.getAccountInfoSync) === "function") {
        const id = tryRun(() => {
          var _a, _b;
          return (_b = (_a = u.getAccountInfoSync().miniProgram) === null || _a === void 0 ? void 0 : _a.appId) !== null && _b !== void 0 ? _b : "";
        }, "");
        if (id)
          return id;
      }
      const wxHost = getGlobalObject().wx;
      if (typeof (wxHost === null || wxHost === void 0 ? void 0 : wxHost.getAccountInfoSync) === "function") {
        const id2 = tryRun(() => {
          var _a, _b;
          return (_b = (_a = wxHost.getAccountInfoSync().miniProgram) === null || _a === void 0 ? void 0 : _a.appId) !== null && _b !== void 0 ? _b : "";
        }, "");
        if (id2)
          return id2;
      }
      const envId = "__UNI__4FA356E";
      return typeof envId === "string" ? envId : "";
    }
    case "ali":
    case "dt": {
      const my2 = getGlobalObject().my;
      if (!my2)
        return "";
      const v1 = tryRun(() => {
        var _a, _b;
        return (_b = (_a = my2.getAppIdSync) === null || _a === void 0 ? void 0 : _a.call(my2)) !== null && _b !== void 0 ? _b : "";
      }, "");
      if (v1)
        return v1;
      return tryRun(() => {
        var _a, _b, _c;
        return (_c = (_b = (_a = my2.getAccountInfoSync) === null || _a === void 0 ? void 0 : _a.call(my2).miniProgram) === null || _b === void 0 ? void 0 : _b.appId) !== null && _c !== void 0 ? _c : "";
      }, "");
    }
    case "tt":
    case "lark": {
      const tt2 = getGlobalObject().tt;
      return tryRun(() => {
        var _a, _b, _c;
        return (_c = (_b = (_a = tt2 === null || tt2 === void 0 ? void 0 : tt2.getEnvInfoSync) === null || _a === void 0 ? void 0 : _a.call(tt2).microapp) === null || _b === void 0 ? void 0 : _b.appId) !== null && _c !== void 0 ? _c : "";
      }, "");
    }
    case "bd": {
      const swan2 = getGlobalObject().swan;
      return tryRun(() => {
        var _a, _b, _c;
        return (_c = (_b = (_a = swan2 === null || swan2 === void 0 ? void 0 : swan2.getEnvInfoSync) === null || _a === void 0 ? void 0 : _a.call(swan2).common) === null || _b === void 0 ? void 0 : _b.appKey) !== null && _c !== void 0 ? _c : "";
      }, "");
    }
    default:
      return "";
  }
}
function getAppPkn() {
  var _a, _b, _c;
  const plus = getPlus();
  if (!plus)
    return "";
  const osName = (_c = (_b = (_a = plus.os) === null || _a === void 0 ? void 0 : _a.name) === null || _b === void 0 ? void 0 : _b.toLowerCase()) !== null && _c !== void 0 ? _c : "";
  if (osName.includes("android")) {
    return tryRun(() => {
      var _a2, _b2, _c2, _d, _e;
      return (_e = (_d = (_c2 = (_b2 = (_a2 = plus.android) === null || _a2 === void 0 ? void 0 : _a2.runtimeMainActivity) === null || _b2 === void 0 ? void 0 : _b2.call(_a2)) === null || _c2 === void 0 ? void 0 : _c2.getPackageName) === null || _d === void 0 ? void 0 : _d.call(_c2)) !== null && _e !== void 0 ? _e : "";
    }, "");
  }
  if (osName === "ios" || osName === "iphone os") {
    const v = tryRun(() => {
      var _a2, _b2;
      return (_b2 = (_a2 = plus.ios) === null || _a2 === void 0 ? void 0 : _a2.bundleId) !== null && _b2 !== void 0 ? _b2 : "";
    }, "");
    return v || tryRun(() => {
      var _a2, _b2;
      return (_b2 = (_a2 = plus.runtime) === null || _a2 === void 0 ? void 0 : _a2.appid) !== null && _b2 !== void 0 ? _b2 : "";
    }, "");
  }
  return tryRun(() => {
    var _a2, _b2;
    return (_b2 = (_a2 = plus.runtime) === null || _a2 === void 0 ? void 0 : _a2.appid) !== null && _b2 !== void 0 ? _b2 : "";
  }, "");
}
function getAppName() {
  const plus = getPlus();
  if (!plus)
    return "";
  return tryRun(() => {
    var _a, _b;
    return (_b = (_a = plus.runtime) === null || _a === void 0 ? void 0 : _a.appname) !== null && _b !== void 0 ? _b : "";
  }, "") || tryRun(() => {
    var _a, _b;
    return (_b = (_a = plus.runtime) === null || _a === void 0 ? void 0 : _a.name) !== null && _b !== void 0 ? _b : "";
  }, "");
}
function getEnvAppName() {
  var _a;
  return (_a = "LuckyNumber-Miniui") !== null && _a !== void 0 ? _a : "";
}
function getH5AppName() {
  const env = getEnvAppName();
  if (env)
    return env;
  return tryRun(() => {
    var _a, _b;
    return (_b = (_a = getGlobalObject().document) === null || _a === void 0 ? void 0 : _a.title) !== null && _b !== void 0 ? _b : "";
  }, "");
}
function getPackageInfo() {
  if (cached$1)
    return cached$1;
  const platform = getPlatform();
  let mpn = "";
  let tdaid = "";
  let pkn = "";
  let an = "";
  if (isApp()) {
    tdaid = tryRun(() => {
      var _a, _b, _c;
      return (_c = (_b = (_a = getPlus()) === null || _a === void 0 ? void 0 : _a.runtime) === null || _b === void 0 ? void 0 : _b.appid) !== null && _c !== void 0 ? _c : "";
    }, "");
    pkn = getAppPkn() || tdaid;
    an = getAppName() || getEnvAppName();
    mpn = pkn || tdaid;
  } else if (isMp()) {
    tdaid = getMpTdaid(platform);
    pkn = "";
    an = getEnvAppName();
    mpn = tdaid || "__UNI__4FA356E";
  } else if (isH5()) {
    tdaid = "";
    pkn = "";
    an = getH5AppName();
    mpn = "";
  } else {
    tdaid = "";
    pkn = "";
    an = getEnvAppName();
    mpn = "";
  }
  cached$1 = { mpn, tdaid, pkn, an };
  return cached$1;
}
const EMPTY_WEB_INFO = { domain: "" };
let cached = null;
function readWebDomainFromLocation(loc) {
  const protocol = typeof loc.protocol === "string" ? loc.protocol.toLowerCase() : "";
  if (protocol !== "http:" && protocol !== "https:")
    return "";
  if (typeof loc.origin === "string" && loc.origin.trim()) {
    return loc.origin.trim();
  }
  const host2 = typeof loc.host === "string" && loc.host.trim() ? loc.host.trim() : typeof loc.hostname === "string" ? loc.hostname.trim() : "";
  if (!host2)
    return "";
  return `${protocol}//${host2}`;
}
function getWebInfo() {
  if (!isH5())
    return EMPTY_WEB_INFO;
  if (cached !== null)
    return cached;
  cached = tryRun(() => {
    const win = getGlobalObject();
    const loc = win.location;
    if (!loc)
      return EMPTY_WEB_INFO;
    return { domain: readWebDomainFromLocation(loc) };
  }, EMPTY_WEB_INFO);
  return cached;
}
const registry = /* @__PURE__ */ new Map();
const installedFanout = /* @__PURE__ */ new Map();
function add(api, handlers) {
  var _a;
  const set2 = (_a = registry.get(api)) !== null && _a !== void 0 ? _a : /* @__PURE__ */ new Set();
  set2.add(handlers);
  registry.set(api, set2);
  reinstall(api);
  return () => {
    const cur = registry.get(api);
    if (!cur)
      return;
    cur.delete(handlers);
    if (cur.size === 0) {
      registry.delete(api);
      const prev = installedFanout.get(api);
      installedFanout.delete(api);
      if (prev) {
        try {
          getUni$1().removeInterceptor(api, prev);
        } catch (_a2) {
        }
      }
    } else {
      reinstall(api);
    }
  };
}
function buildFanout(set2) {
  return {
    invoke(args) {
      let blocked = false;
      for (const h of set2) {
        if (!h.invoke)
          continue;
        const r = h.invoke(args);
        if (r === false)
          blocked = true;
      }
      return blocked ? false : void 0;
    },
    success(res) {
      var _a;
      for (const h of set2)
        (_a = h.success) === null || _a === void 0 ? void 0 : _a.call(h, res);
    },
    fail(err) {
      var _a;
      for (const h of set2)
        (_a = h.fail) === null || _a === void 0 ? void 0 : _a.call(h, err);
    },
    complete(res) {
      var _a;
      for (const h of set2)
        (_a = h.complete) === null || _a === void 0 ? void 0 : _a.call(h, res);
    },
    returnValue(res) {
      let v = res;
      for (const h of set2) {
        if (!h.returnValue)
          continue;
        v = h.returnValue(v);
      }
      return v;
    }
  };
}
function reinstall(api) {
  const set2 = registry.get(api);
  if (!set2 || set2.size === 0)
    return;
  const fanout = buildFanout(set2);
  try {
    const uni2 = getUni$1();
    const prev = installedFanout.get(api);
    if (prev) {
      try {
        uni2.removeInterceptor(api, prev);
      } catch (_a) {
      }
    }
    uni2.addInterceptor(api, fanout);
    installedFanout.set(api, fanout);
  } catch (_b) {
  }
}
function getUni$1() {
  const raw = resolveUniRuntime();
  const u = raw != null && typeof raw === "object" ? raw : void 0;
  if (!u)
    throw new Error("[uni统计 2.0] uni interceptor API is not available");
  return u;
}
function __reset() {
  registry.clear();
  installedFanout.clear();
}
const interceptor = { add, __reset };
function registerLoginInterceptor(reporter) {
  return interceptor.add("login", {
    complete() {
      reporter.report({ lt: LT.Event, custom: { e_n: "login" } });
    }
  });
}
function registerNavigationBarInterceptor() {
  return interceptor.add("setNavigationBarTitle", {
    invoke(args) {
      const a = args;
      if (a && "title" in a)
        setPageTitle(a.title);
    }
  });
}
function registerPaymentInterceptor(reporter) {
  return interceptor.add("requestPayment", {
    success() {
      reporter.report({ lt: LT.Event, custom: { e_n: "pay_success" } });
    },
    fail() {
      reporter.report({ lt: LT.Event, custom: { e_n: "pay_fail" } });
    }
  });
}
function registerShareInterceptor(reporter) {
  const fire = () => reporter.report({ lt: LT.Event, custom: { e_n: "share" } });
  return interceptor.add("share", {
    success() {
      fire();
    },
    fail() {
      fire();
    }
  });
}
function installAllInterceptors(reporter) {
  const unbinders = [
    registerLoginInterceptor(reporter),
    registerShareInterceptor(reporter),
    registerPaymentInterceptor(reporter),
    registerNavigationBarInterceptor()
  ];
  return () => {
    for (const u of unbinders) {
      try {
        u();
      } catch (_a) {
      }
    }
  };
}
const KEY_DONE = "migration:done";
const KEY_MAP = [
  ["__first__visit__time", "visit:fvts"],
  ["__last__visit__time", "visit:lvts"],
  ["__total__visit__count", "visit:tvc"]
];
function getAppId() {
  const id = "__UNI__4FA356E";
  if (id.length > 0)
    return id;
  return "default";
}
function readLegacyAggregate() {
  const u = resolveUniRuntime();
  if (!u || typeof u.getStorageSync !== "function")
    return null;
  const key = `${LEGACY_NAMESPACE_ROOT}:${getAppId()}`;
  const raw = tryRun(() => u.getStorageSync(key), null);
  if (raw && typeof raw === "object")
    return raw;
  return null;
}
let ran = false;
function migrateLegacyData() {
  if (ran)
    return false;
  ran = true;
  const doneR = storage.safeRead(KEY_DONE);
  if (doneR.ok && doneR.value)
    return false;
  const legacy = readLegacyAggregate();
  if (!legacy) {
    storage.set(KEY_DONE, 1);
    return false;
  }
  let migrated = 0;
  for (let i = 0; i < KEY_MAP.length; i++) {
    const [oldKey, newKey] = KEY_MAP[i];
    if (!(oldKey in legacy))
      continue;
    const value = legacy[oldKey];
    const existing = storage.safeRead(newKey);
    if (existing.ok && existing.value !== void 0)
      continue;
    storage.set(newKey, value);
    migrated++;
  }
  storage.set(KEY_DONE, 1);
  if (migrated > 0) {
    logger.info("[uni统计 2.0] migrated legacy keys", migrated);
  }
  return migrated > 0;
}
function selectChannel(opts) {
  var _a;
  const version2 = (_a = opts.version) !== null && _a !== void 0 ? _a : "image";
  const fallback = opts.fallbackToHttp !== false;
  if (version2 === "1") {
    if (opts.http && opts.http.available())
      return opts.http;
    return void 0;
  }
  if (version2 === "2") {
    if (opts.cloud && opts.cloud.available())
      return opts.cloud;
    if (!fallback) {
      logger.warn("[uni统计 2.0] 云函数上报不可用且已关闭 HTTP 兜底，本批已丢弃");
      return void 0;
    }
    if (opts.http && opts.http.available()) {
      logger.warn("[uni统计 2.0] 云函数上报不可用，已降级为 HTTP 上报");
      return opts.http;
    }
    logger.warn("[uni统计 2.0] 无可用上报线路");
    return void 0;
  }
  if (opts.image && opts.image.available())
    return opts.image;
  if (!fallback) {
    if (opts.image) {
      logger.warn("[uni统计 2.0] 统计上报线路不可用且已关闭 HTTP 兜底，本批已丢弃");
    }
    return void 0;
  }
  if (opts.http && opts.http.available()) {
    if (opts.image) {
      logger.warn("[uni统计 2.0] 统计上报线路不可用，已降级为 HTTP 上报");
    }
    return opts.http;
  }
  logger.warn("[uni统计 2.0] 无可用上报线路");
  return void 0;
}
const STORAGE_KEY$1 = "queue";
const DEFAULT_SINGLE_EVENT_MAX_BYTES = SINGLE_EVENT_MAX_BYTES;
const state = {
  bucket: {},
  lastFlushAt: 0
};
let intervalSec = REPORT_INTERVAL_SEC;
let singleEventMaxBytes = DEFAULT_SINGLE_EVENT_MAX_BYTES;
let maxEvents = QUEUE_MAX_EVENTS;
let restored = false;
let capacityWarned = false;
function configure(opts) {
  if (typeof opts.intervalSec === "number" && opts.intervalSec >= 0) {
    intervalSec = Math.floor(opts.intervalSec);
  }
  if (typeof opts.singleEventMaxBytes === "number" && opts.singleEventMaxBytes > 0) {
    singleEventMaxBytes = Math.floor(opts.singleEventMaxBytes);
  }
  if (typeof opts.maxEvents === "number" && opts.maxEvents > 0) {
    maxEvents = Math.floor(opts.maxEvents);
  }
}
function enforceCapacity() {
  let total = size();
  if (total <= maxEvents) {
    capacityWarned = false;
    return;
  }
  const dropped = total - maxEvents;
  while (total > maxEvents) {
    let largestLt = "";
    let largestLen = 0;
    for (const lt of Object.keys(state.bucket)) {
      const len = state.bucket[lt].length;
      if (len > largestLen) {
        largestLen = len;
        largestLt = lt;
      }
    }
    if (!largestLt || largestLen === 0)
      break;
    state.bucket[largestLt].shift();
    if (state.bucket[largestLt].length === 0)
      delete state.bucket[largestLt];
    total--;
  }
  if (!capacityWarned) {
    capacityWarned = true;
    logger.warn("[uni统计 2.0] 上报队列超过容量上限，已丢弃最旧事件", "dropped=" + dropped, "limit=" + maxEvents);
  }
}
function persistBucket() {
  if (Object.keys(state.bucket).length === 0) {
    storage.remove(STORAGE_KEY$1);
    return;
  }
  try {
    storage.set(STORAGE_KEY$1, state.bucket);
  } catch (e2) {
    logger.warn("[uni统计 2.0] queue persist failed", e2);
  }
}
function restoreOnce() {
  if (restored)
    return;
  restored = true;
  const raw = storage.safeRead(STORAGE_KEY$1);
  if (!raw.ok || !raw.value || typeof raw.value !== "object")
    return;
  const persisted = raw.value;
  for (const lt of Object.keys(persisted)) {
    const arr = persisted[lt];
    if (!Array.isArray(arr) || arr.length === 0)
      continue;
    if (!state.bucket[lt])
      state.bucket[lt] = [];
    state.bucket[lt].push(...arr);
  }
}
function enqueue(data) {
  var _a;
  if (!data || typeof data !== "object")
    return;
  const lt = String((_a = data.lt) !== null && _a !== void 0 ? _a : "");
  if (!lt) {
    logger.warn("[uni统计 2.0] enqueue dropped: missing lt", data);
    return;
  }
  let serialized = "";
  try {
    serialized = JSON.stringify(data);
  } catch (e2) {
    logger.warn("[uni统计 2.0] enqueue dropped: stringify failed", e2);
    return;
  }
  if (serialized.length > singleEventMaxBytes) {
    logger.warn("[uni统计 2.0] enqueue dropped: single event too large", "lt=" + lt, "bytes=" + serialized.length, "limit=" + singleEventMaxBytes);
    return;
  }
  restoreOnce();
  if (!state.bucket[lt])
    state.bucket[lt] = [];
  state.bucket[lt].push(data);
  enforceCapacity();
  persistBucket();
}
function shouldFlush(force = false) {
  if (force)
    return true;
  if (intervalSec <= 0)
    return true;
  const elapsedSec = (nowMs() - state.lastFlushAt) / 1e3;
  return elapsedSec >= intervalSec;
}
function flush() {
  restoreOnce();
  const lts = Object.keys(state.bucket);
  if (lts.length === 0)
    return void 0;
  const snapshot = state.bucket;
  state.bucket = {};
  state.lastFlushAt = nowMs();
  storage.remove(STORAGE_KEY$1);
  return snapshot;
}
function rollback(snapshot) {
  if (!snapshot)
    return;
  for (const lt of Object.keys(snapshot)) {
    const arr = snapshot[lt];
    if (!Array.isArray(arr) || arr.length === 0)
      continue;
    if (!state.bucket[lt])
      state.bucket[lt] = [];
    state.bucket[lt] = arr.concat(state.bucket[lt]);
  }
  enforceCapacity();
  persistBucket();
}
function size() {
  let n2 = 0;
  for (const lt of Object.keys(state.bucket)) {
    n2 += state.bucket[lt].length;
  }
  return n2;
}
const STORAGE_KEY = "retry:queue";
const DEFAULT_MAX_ITEMS = 50;
const DEFAULT_MAX_AGE_MS = 7 * 24 * 60 * 60 * 1e3;
const DEFAULT_MAX_ATTEMPTS = RETRY_MAX_ATTEMPTS;
const config = {
  maxItems: DEFAULT_MAX_ITEMS,
  maxAgeMs: DEFAULT_MAX_AGE_MS,
  maxAttempts: DEFAULT_MAX_ATTEMPTS
};
function readQueue() {
  const raw = storage.safeRead(STORAGE_KEY);
  if (!raw.ok || !Array.isArray(raw.value))
    return [];
  return raw.value.filter((it) => it && typeof it.id === "string" && it.payload && typeof it.payload === "object");
}
function writeQueue(items) {
  if (items.length === 0) {
    storage.remove(STORAGE_KEY);
    return;
  }
  storage.set(STORAGE_KEY, items);
}
function genId(payload) {
  if (payload._id)
    return payload._id;
  return "r-" + nowMs().toString(36) + "-" + Math.random().toString(36).slice(2, 6);
}
function persist(payload) {
  if (!payload)
    return void 0;
  const id = genId(payload);
  const items = readQueue();
  if (items.some((it) => it.id === id)) {
    return id;
  }
  const item = {
    id,
    payload: Object.assign({}, payload, { _id: id }),
    createdAt: nowMs(),
    attempts: 0
  };
  items.push(item);
  while (items.length > config.maxItems) {
    const dropped = items.shift();
    logger.warn("[uni统计 2.0] retry queue overflow, drop oldest", dropped === null || dropped === void 0 ? void 0 : dropped.id);
  }
  writeQueue(items);
  return id;
}
function loadAll() {
  const items = readQueue();
  if (items.length === 0)
    return [];
  const cutoff = nowMs() - config.maxAgeMs;
  const alive = [];
  for (const it of items) {
    if (it.createdAt < cutoff) {
      logger.warn("[uni统计 2.0] retry item expired, drop", it.id);
      continue;
    }
    alive.push(it);
  }
  if (alive.length !== items.length)
    writeQueue(alive);
  return alive.map((it) => it.payload);
}
function ack(id) {
  if (!id)
    return;
  const items = readQueue();
  const next = items.filter((it) => it.id !== id);
  if (next.length === items.length)
    return;
  writeQueue(next);
}
function markAttempt(id) {
  if (!id)
    return;
  const items = readQueue();
  let nextItems = null;
  for (let i = 0; i < items.length; i++) {
    const it = items[i];
    if (it.id !== id)
      continue;
    it.attempts++;
    if (it.attempts >= config.maxAttempts) {
      logger.warn("[uni统计 2.0] retry item exceeded maxAttempts, drop as dead letter", id, "attempts=" + it.attempts);
      nextItems = items.slice(0, i).concat(items.slice(i + 1));
    } else {
      nextItems = items;
    }
    break;
  }
  if (nextItems)
    writeQueue(nextItems);
}
let instance = null;
class StatApp {
  constructor() {
    this.installed = false;
    this.statVersion = "image";
  }
  static getInstance() {
    if (!instance)
      instance = new StatApp();
    return instance;
  }
  /**
   * 一次性装配。重复调用直接返回。
   *
   * @param config 业务配置；缺省值兼容私有版默认行为。
   * @param overrides 测试钩子。
   */
  install(config2 = {}, overrides = {}) {
    var _a, _b, _c, _d, _e;
    if (this.installed)
      return;
    const cfg = this.normalizeConfig(config2);
    this.config = cfg;
    this.statVersion = cfg.version;
    tryRun(() => configure$1({
      backgroundTimeoutSec: cfg.backgroundTimeoutSec,
      pageInactiveTimeoutSec: cfg.pageInactiveTimeoutSec
    }), void 0);
    tryRun(() => configure({ intervalSec: cfg.reportIntervalSec }), void 0);
    if (!overrides.skipMigration) {
      tryRun(() => migrateLegacyData(), false);
    }
    tryRun(() => loadVisitSnapshot(), void 0);
    this.httpChannel = (_b = (_a = overrides.channels) === null || _a === void 0 ? void 0 : _a.http) !== null && _b !== void 0 ? _b : createHttpChannel({ ut: getPlatform(), maxRetries: HTTP_MAX_RETRIES });
    if (overrides.channels && "cloud" in overrides.channels) {
      this.cloudChannel = (_c = overrides.channels.cloud) !== null && _c !== void 0 ? _c : void 0;
    } else if (this.statVersion === "2") {
      this.cloudChannel = createCloudChannel({ maxRetries: CLOUD_MAX_RETRIES });
    } else {
      this.cloudChannel = void 0;
    }
    if (overrides.channels && "image" in overrides.channels) {
      this.imageChannel = (_d = overrides.channels.image) !== null && _d !== void 0 ? _d : void 0;
    } else if (this.statVersion === "image") {
      this.imageChannel = createImageChannel({
        host: IMAGE_REPORT_DEFAULTS.host,
        projectId: IMAGE_REPORT_DEFAULTS.projectId,
        topicId: IMAGE_REPORT_DEFAULTS.topicId,
        maxRetries: IMAGE_MAX_RETRIES,
        ut: getPlatform(),
        rawPlatform: getRawPlatform()
      });
    } else {
      this.imageChannel = void 0;
    }
    this.collectorDeps = this.buildCollectorDeps(cfg, (_e = overrides.collectorDepsPatch) !== null && _e !== void 0 ? _e : {});
    this.collector = createCollector(this.collectorDeps);
    if (!overrides.skipInterceptors) {
      const c = this.collector;
      this.uninstallInterceptors = tryRun(() => installAllInterceptors({ report: (i) => c.report(i) }), void 0);
    }
    if (!overrides.skipRecoverRetry) {
      void this.collector.recoverRetry().catch((e2) => logger.warn("[uni统计 2.0] recoverRetry failed", e2));
    }
    this.installed = true;
  }
  /**
   * 业务侧 `uni.report(type, value)` 入口。
   *
   * 兼容私有版语义：
   *   - `type === 'title'` → 写 reportTitle，不发事件；下次 lt=11 / lt=3 携带 `ttc`。
   *   - 其他 type → 自定义事件 lt=21，custom `{ e_n: type, e_v: value }`。
   */
  report(type, value) {
    if (!this.installed || !this.collector)
      return;
    if (type === "title") {
      setReportTitle(value);
      return;
    }
    const ev = typeof value === "object" && value !== null ? tryRun(() => JSON.stringify(value), "") : value === void 0 ? "" : String(value);
    this.collector.report({
      lt: LT.Event,
      custom: { e_n: type, e_v: ev }
    });
  }
  /** 上报 onError 捕获的错误。 */
  reportError(err) {
    var _a;
    if (!this.installed || !this.collector)
      return;
    const errMsg = err instanceof Error ? `${err.name}: ${err.message}
${(_a = err.stack) !== null && _a !== void 0 ? _a : ""}` : typeof err === "string" ? err : tryRun(() => JSON.stringify(err), "");
    this.collector.report({ lt: LT.Error, errMsg });
  }
  /** 取 collector，供 lifecycleHooks 调度生命周期事件。 */
  getCollector() {
    return this.collector;
  }
  /** 取 deps（测试用）。 */
  getDeps() {
    return this.collectorDeps;
  }
  /** 是否已 install。 */
  isInstalled() {
    return this.installed;
  }
  /** 当前协议版本。 */
  getStatVersion() {
    return this.statVersion;
  }
  /** 当前生效配置（含默认值合并），测试用。 */
  getConfig() {
    return this.config;
  }
  /**
   * 卸载（测试 / hot reload）。
   *
   * 解绑全部拦截器、清空内部句柄。**不**清外部模块（queue/visit/session）状态，
   * 那些由各自的 `__reset*` 在测试 setup 中处理。
   */
  uninstall() {
    if (this.uninstallInterceptors) {
      tryRun(() => this.uninstallInterceptors(), void 0);
    }
    this.uninstallInterceptors = void 0;
    if (this.collector) {
      tryRun(() => this.collector.destroy(), void 0);
    }
    this.collector = void 0;
    this.collectorDeps = void 0;
    this.httpChannel = void 0;
    this.cloudChannel = void 0;
    this.imageChannel = void 0;
    this.config = void 0;
    this.installed = false;
  }
  normalizeConfig(c) {
    var _a, _b, _c, _d, _e;
    return {
      ak: (_a = c.ak) !== null && _a !== void 0 ? _a : getAppId$1(),
      v: c.v,
      ch: (_b = c.ch) !== null && _b !== void 0 ? _b : "",
      version: (_c = c.version) !== null && _c !== void 0 ? _c : "image",
      backgroundTimeoutSec: (_d = c.backgroundTimeoutSec) !== null && _d !== void 0 ? _d : 300,
      pageInactiveTimeoutSec: (_e = c.pageInactiveTimeoutSec) !== null && _e !== void 0 ? _e : 1800,
      reportIntervalSec: typeof c.reportIntervalSec === "number" ? c.reportIntervalSec : REPORT_INTERVAL_SEC,
      // collectItems 默认值与私有版严格对齐：push 默认关闭、页面日志默认开启
      enablePush: c.enablePush === true,
      enablePageLog: c.enablePageLog !== false
    };
  }
  /**
   * 构建 collector 依赖。所有 adapter 调用都包了 `tryRun`，避免单端缺失 API 导致
   * install 失败。
   */
  buildCollectorDeps(cfg, patch2) {
    const platformShort = getPlatform();
    const builder = createStatDataBuilder({
      config: { ak: cfg.ak, usv: STAT_VERSION_PUBLIC, v: cfg.v, ch: cfg.ch },
      platform: {
        ut: platformShort
      },
      system: tryRun(() => getSystemInfo(), {
        brand: "",
        md: "",
        sv: "",
        v: "",
        ut: "unknown",
        appVersion: "",
        appWgtVersion: "",
        mpvHostVersion: "",
        on: "",
        sdkVersion: "",
        statusBarHeight: 0,
        osP: ""
      }),
      locale: tryRun(() => getLocaleAndScreen(), {
        lang: "",
        ww: 0,
        wh: 0,
        sw: 0,
        sh: 0,
        pr: 1
      }),
      device: {
        // 惰性解析：每次 build 时再调 getUuid()，避免 install 过早（uni 运行时未就绪）冻结临时值。
        get uuid() {
          return tryRun(() => getUuid(), "");
        }
      },
      net: { net: "unknown", raw: "" },
      location: { lat: "", lng: "", ok: false },
      pkg: tryRun(() => getPackageInfo(), {
        mpn: "",
        tdaid: "",
        pkn: "",
        an: ""
      }),
      web: tryRun(() => getWebInfo(), { domain: "" })
    });
    const base = {
      builder,
      queue: {
        enqueue,
        flush,
        rollback,
        shouldFlush
      },
      serializer: { handleData },
      selectChannel: () => selectChannel({
        version: this.statVersion,
        http: this.httpChannel,
        cloud: this.cloudChannel,
        image: this.imageChannel
      }),
      retry: {
        persist,
        loadAll,
        ack,
        markAttempt
      },
      visit: {
        commitVisitOnAck,
        rollbackPendingVisit
      },
      session: {
        getSnapshot,
        nextSeq,
        touch
      },
      config: { usv: STAT_VERSION_PUBLIC },
      nowMs,
      nowSec,
      firstFlushDeferMs: getRawPlatform() === "mp-weixin" && MP_WEIXIN_USE_PRELOAD_ASSETS_REPORT ? MP_WEIXIN_PRELOAD_FIRST_FLUSH_DELAY_MS : 0
    };
    return Object.assign(base, patch2);
  }
}
function getStatApp() {
  return StatApp.getInstance();
}
function parseInjectedUniStatistics() {
  const raw = "{}";
  const trimmed = raw.trim();
  if (!trimmed || trimmed === "undefined")
    return void 0;
  try {
    const obj = JSON.parse(trimmed);
    if (!obj || typeof obj !== "object" || Array.isArray(obj))
      return void 0;
    return obj;
  } catch (_e) {
    return void 0;
  }
}
function readManifestStatConfig() {
  try {
    const obj = parseInjectedUniStatistics();
    if (!obj)
      return void 0;
    const cfg = {};
    if (obj.channelVersion != null) {
      const v = String(obj.channelVersion);
      if (v === "1" || v === "2" || v === "image")
        cfg.version = v;
    }
    const bg = pickPositiveNumber(obj.backgroundTimeout, obj.backgroundTimeoutSec);
    if (bg !== void 0)
      cfg.backgroundTimeoutSec = bg;
    const pi = pickPositiveNumber(obj.pageInactiveTimeout, obj.pageInactiveTimeoutSec);
    if (pi !== void 0)
      cfg.pageInactiveTimeoutSec = pi;
    const ri = pickNonNegativeNumber(obj.reportInterval, obj.reportIntervalSec);
    if (ri !== void 0)
      cfg.reportIntervalSec = ri;
    if (obj.collectItems && typeof obj.collectItems === "object") {
      const items = obj.collectItems;
      if (typeof items.uniPushClientID === "boolean") {
        cfg.enablePush = items.uniPushClientID;
      }
      if (typeof items.uniStatPageLog === "boolean") {
        cfg.enablePageLog = items.uniStatPageLog;
      }
    }
    if (typeof obj.ak === "string" && obj.ak)
      cfg.ak = obj.ak;
    if (typeof obj.v === "string")
      cfg.v = obj.v;
    if (typeof obj.ch === "string")
      cfg.ch = obj.ch;
    return Object.keys(cfg).length > 0 ? cfg : void 0;
  } catch (e2) {
    logger.warn("[uni统计 2.0] readManifestStatConfig failed", e2);
    return void 0;
  }
}
function normalizePositiveNumber(value) {
  if (typeof value === "number") {
    return value > 0 ? value : void 0;
  }
  if (typeof value === "string") {
    const t2 = value.trim();
    if (t2 === "")
      return void 0;
    const n2 = Number(t2);
    if (Number.isFinite(n2) && n2 > 0)
      return n2;
  }
  return void 0;
}
function normalizeNonNegativeNumber(value) {
  if (typeof value === "number") {
    return value >= 0 ? value : void 0;
  }
  if (typeof value === "string") {
    const t2 = value.trim();
    if (t2 === "")
      return void 0;
    const n2 = Number(t2);
    if (Number.isFinite(n2) && n2 >= 0)
      return n2;
  }
  return void 0;
}
function pickPositiveNumber(...candidates) {
  for (const c of candidates) {
    const n2 = normalizePositiveNumber(c);
    if (n2 !== void 0)
      return n2;
  }
  return void 0;
}
function pickNonNegativeNumber(...candidates) {
  for (const c of candidates) {
    const n2 = normalizeNonNegativeNumber(c);
    if (n2 !== void 0)
      return n2;
  }
  return void 0;
}
function getUni() {
  const u = resolveUniRuntime();
  return u != null && typeof u === "object" ? u : void 0;
}
const UNI_HOOK_RETRY_MAX = 20;
const UNI_HOOK_RETRY_MS = 50;
let vueMixinMounted = false;
let vueMixinRetryTimer;
let bootstrapped = false;
let uniHookRetryTimer;
function installPublicStat(opts = {}) {
  if (bootstrapped)
    return;
  bootstrapped = true;
  const fromManifest = readManifestStatConfig();
  const finalConfig = Object.assign({}, fromManifest, opts.config);
  const app = getStatApp();
  tryRun(() => app.install(finalConfig, opts.overrides), void 0);
  tryRun(() => {
    var _a, _b, _c;
    const cfgBoot = app.getConfig();
    const appName = "LuckyNumber-Miniui";
    const injected = parseInjectedUniStatistics();
    const bootBase = {
      channel: (_a = cfgBoot === null || cfgBoot === void 0 ? void 0 : cfgBoot.version) !== null && _a !== void 0 ? _a : "image",
      reportIntervalSec: (_b = cfgBoot === null || cfgBoot === void 0 ? void 0 : cfgBoot.reportIntervalSec) !== null && _b !== void 0 ? _b : 0,
      ak: (_c = cfgBoot === null || cfgBoot === void 0 ? void 0 : cfgBoot.ak) !== null && _c !== void 0 ? _c : "",
      appName,
      debugFromManifest: "false" === true
    };
    if (injected != null) {
      if (injected.backgroundTimeout != null || injected.backgroundTimeoutSec != null) {
        bootBase.backgroundTimeoutSec = cfgBoot === null || cfgBoot === void 0 ? void 0 : cfgBoot.backgroundTimeoutSec;
      }
      if (injected.pageInactiveTimeout != null || injected.pageInactiveTimeoutSec != null) {
        bootBase.pageInactiveTimeoutSec = cfgBoot === null || cfgBoot === void 0 ? void 0 : cfgBoot.pageInactiveTimeoutSec;
      }
    }
    logBoot(Object.assign({}, bootBase, { vueMode: "Vue3" }));
  }, void 0);
  const finishLifecycleInstall = () => {
    var _a, _b;
    const cfg = app.getConfig();
    const lifecycleOpts = Object.assign({}, {
      enablePush: (_a = cfg === null || cfg === void 0 ? void 0 : cfg.enablePush) !== null && _a !== void 0 ? _a : false,
      enablePageLog: (_b = cfg === null || cfg === void 0 ? void 0 : cfg.enablePageLog) !== null && _b !== void 0 ? _b : true
    }, opts.lifecycle);
    const { mixin, unbind } = bindLifecycle(app, lifecycleOpts);
    if (!opts.skipVueMixin) {
      tryRun(() => mountVueMixin(mixin), void 0);
    }
    if (!opts.skipUniReport) {
      tryRun(() => mountUniReport(app), void 0);
    }
    if (shouldBindUniAppLifecycle() && !tryBindUniAppLifecycle(app, lifecycleOpts)) {
      scheduleUniAppHookRetry(() => tryBindUniAppLifecycle(app, lifecycleOpts));
    }
  };
  finishLifecycleInstall();
}
function scheduleUniAppHookRetry(tryBind) {
  if (uniHookRetryTimer) {
    clearTimeout(uniHookRetryTimer);
    uniHookRetryTimer = void 0;
  }
  let attempts = 0;
  const tick = () => {
    if (tryBind())
      return;
    if (++attempts >= UNI_HOOK_RETRY_MAX) {
      logger.warn("[uni统计 2.0] Vue3 小程序：uni.onAppShow 暂不可用，应用前后台统计可能缺失");
      return;
    }
    uniHookRetryTimer = setTimeout(tick, UNI_HOOK_RETRY_MS);
  };
  uniHookRetryTimer = setTimeout(tick, UNI_HOOK_RETRY_MS);
}
function tryRegisterVueAppMixin(mixin) {
  try {
    ;
    index.onCreateVueApp((vueApp2) => {
      tryRun(() => vueApp2.mixin(mixin), void 0);
    });
    return true;
  } catch (_e) {
  }
  const u = getUni();
  if (u && typeof u.onCreateVueApp === "function") {
    u.onCreateVueApp((vueApp2) => {
      tryRun(() => vueApp2.mixin(mixin), void 0);
    });
    return true;
  }
  return false;
}
function mountVueMixin(mixin) {
  if (vueMixinMounted)
    return;
  if (tryRegisterVueAppMixin(mixin)) {
    vueMixinMounted = true;
    return;
  }
  scheduleVueAppMixinRetry(mixin);
}
function scheduleVueAppMixinRetry(mixin) {
  if (vueMixinMounted)
    return;
  if (vueMixinRetryTimer)
    return;
  let attempts = 0;
  const tick = () => {
    vueMixinRetryTimer = void 0;
    if (vueMixinMounted)
      return;
    if (tryRegisterVueAppMixin(mixin)) {
      vueMixinMounted = true;
      return;
    }
    if (++attempts >= UNI_HOOK_RETRY_MAX) {
      if (!vueMixinMounted) {
        logger.warn("[uni统计 2.0] Vue3: onCreateVueApp 在重试后仍不可用，页面级 mixin 未注入");
      }
      return;
    }
    vueMixinRetryTimer = setTimeout(tick, UNI_HOOK_RETRY_MS);
  };
  vueMixinRetryTimer = setTimeout(tick, UNI_HOOK_RETRY_MS);
}
function mountUniReport(app) {
  var _a;
  const g = getGlobalObject();
  const u = (_a = getUni()) !== null && _a !== void 0 ? _a : g.uni;
  if (!u || typeof u !== "object")
    return;
  u.report = (type, value) => {
    app.report(type, value);
  };
}
installPublicStat();
exports._export_sfc = _export_sfc;
exports.computed = computed;
exports.createPinia = createPinia;
exports.createSSRApp = createSSRApp;
exports.defineStore = defineStore;
exports.e = e;
exports.f = f;
exports.index = index;
exports.n = n$1;
exports.o = o;
exports.onHide = onHide;
exports.onLaunch = onLaunch;
exports.onMounted = onMounted;
exports.onShow = onShow;
exports.p = p;
exports.ref = ref;
exports.t = t;
exports.unref = unref;
exports.watch = watch;
exports.wx$1 = wx$1;
//# sourceMappingURL=../../.sourcemap/mp-weixin/common/vendor.js.map
