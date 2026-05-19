const manifest = {"name":"DeckMind"};
const API_VERSION = 2;
const internalAPIConnection = window.__DECKY_SECRET_INTERNALS_DO_NOT_USE_OR_YOU_WILL_BE_FIRED_deckyLoaderAPIInit;
if (!internalAPIConnection) {
    throw new Error('[@decky/api]: Failed to connect to the loader as as the loader API was not initialized. This is likely a bug in Decky Loader.');
}
let api;
try {
    api = internalAPIConnection.connect(API_VERSION, manifest.name);
}
catch {
    api = internalAPIConnection.connect(1, manifest.name);
    console.warn(`[@decky/api] Requested API version ${API_VERSION} but the running loader only supports version 1. Some features may not work.`);
}
if (api._version != API_VERSION) {
    console.warn(`[@decky/api] Requested API version ${API_VERSION} but the running loader only supports version ${api._version}. Some features may not work.`);
}
const callable = api.callable;
const toaster = api.toaster;
const definePlugin = (fn) => {
    return (...args) => {
        return fn(...args);
    };
};

var DefaultContext = {
  color: undefined,
  size: undefined,
  className: undefined,
  style: undefined,
  attr: undefined
};
var IconContext = SP_REACT.createContext && /*#__PURE__*/SP_REACT.createContext(DefaultContext);

var _excluded = ["attr", "size", "title"];
function _objectWithoutProperties(e, t) { if (null == e) return {}; var o, r, i = _objectWithoutPropertiesLoose(e, t); if (Object.getOwnPropertySymbols) { var n = Object.getOwnPropertySymbols(e); for (r = 0; r < n.length; r++) o = n[r], -1 === t.indexOf(o) && {}.propertyIsEnumerable.call(e, o) && (i[o] = e[o]); } return i; }
function _objectWithoutPropertiesLoose(r, e) { if (null == r) return {}; var t = {}; for (var n in r) if ({}.hasOwnProperty.call(r, n)) { if (-1 !== e.indexOf(n)) continue; t[n] = r[n]; } return t; }
function _extends() { return _extends = Object.assign ? Object.assign.bind() : function (n) { for (var e = 1; e < arguments.length; e++) { var t = arguments[e]; for (var r in t) ({}).hasOwnProperty.call(t, r) && (n[r] = t[r]); } return n; }, _extends.apply(null, arguments); }
function ownKeys(e, r) { var t = Object.keys(e); if (Object.getOwnPropertySymbols) { var o = Object.getOwnPropertySymbols(e); r && (o = o.filter(function (r) { return Object.getOwnPropertyDescriptor(e, r).enumerable; })), t.push.apply(t, o); } return t; }
function _objectSpread(e) { for (var r = 1; r < arguments.length; r++) { var t = null != arguments[r] ? arguments[r] : {}; r % 2 ? ownKeys(Object(t), true).forEach(function (r) { _defineProperty(e, r, t[r]); }) : Object.getOwnPropertyDescriptors ? Object.defineProperties(e, Object.getOwnPropertyDescriptors(t)) : ownKeys(Object(t)).forEach(function (r) { Object.defineProperty(e, r, Object.getOwnPropertyDescriptor(t, r)); }); } return e; }
function _defineProperty(e, r, t) { return (r = _toPropertyKey(r)) in e ? Object.defineProperty(e, r, { value: t, enumerable: true, configurable: true, writable: true }) : e[r] = t, e; }
function _toPropertyKey(t) { var i = _toPrimitive(t, "string"); return "symbol" == typeof i ? i : i + ""; }
function _toPrimitive(t, r) { if ("object" != typeof t || !t) return t; var e = t[Symbol.toPrimitive]; if (void 0 !== e) { var i = e.call(t, r); if ("object" != typeof i) return i; throw new TypeError("@@toPrimitive must return a primitive value."); } return ("string" === r ? String : Number)(t); }
function Tree2Element(tree) {
  return tree && tree.map((node, i) => /*#__PURE__*/SP_REACT.createElement(node.tag, _objectSpread({
    key: i
  }, node.attr), Tree2Element(node.child)));
}
function GenIcon(data) {
  return props => /*#__PURE__*/SP_REACT.createElement(IconBase, _extends({
    attr: _objectSpread({}, data.attr)
  }, props), Tree2Element(data.child));
}
function IconBase(props) {
  var elem = conf => {
    var {
        attr,
        size,
        title
      } = props,
      svgProps = _objectWithoutProperties(props, _excluded);
    var computedSize = size || conf.size || "1em";
    var className;
    if (conf.className) className = conf.className;
    if (props.className) className = (className ? className + " " : "") + props.className;
    return /*#__PURE__*/SP_REACT.createElement("svg", _extends({
      stroke: "currentColor",
      fill: "currentColor",
      strokeWidth: "0"
    }, conf.attr, attr, svgProps, {
      className: className,
      style: _objectSpread(_objectSpread({
        color: props.color || conf.color
      }, conf.style), props.style),
      height: computedSize,
      width: computedSize,
      xmlns: "http://www.w3.org/2000/svg"
    }), title && /*#__PURE__*/SP_REACT.createElement("title", null, title), props.children);
  };
  return IconContext !== undefined ? /*#__PURE__*/SP_REACT.createElement(IconContext.Consumer, null, conf => elem(conf)) : elem(DefaultContext);
}

// THIS FILE IS AUTO GENERATED
function FaTerminal (props) {
  return GenIcon({"attr":{"viewBox":"0 0 640 512"},"child":[{"tag":"path","attr":{"d":"M257.981 272.971L63.638 467.314c-9.373 9.373-24.569 9.373-33.941 0L7.029 444.647c-9.357-9.357-9.375-24.522-.04-33.901L161.011 256 6.99 101.255c-9.335-9.379-9.317-24.544.04-33.901l22.667-22.667c9.373-9.373 24.569-9.373 33.941 0L257.981 239.03c9.373 9.372 9.373 24.568 0 33.941zM640 456v-32c0-13.255-10.745-24-24-24H312c-13.255 0-24 10.745-24 24v32c0 13.255 10.745 24 24 24h304c13.255 0 24-10.745 24-24z"},"child":[]}]})(props);
}function FaSync (props) {
  return GenIcon({"attr":{"viewBox":"0 0 512 512"},"child":[{"tag":"path","attr":{"d":"M440.65 12.57l4 82.77A247.16 247.16 0 0 0 255.83 8C134.73 8 33.91 94.92 12.29 209.82A12 12 0 0 0 24.09 224h49.05a12 12 0 0 0 11.67-9.26 175.91 175.91 0 0 1 317-56.94l-101.46-4.86a12 12 0 0 0-12.57 12v47.41a12 12 0 0 0 12 12H500a12 12 0 0 0 12-12V12a12 12 0 0 0-12-12h-47.37a12 12 0 0 0-11.98 12.57zM255.83 432a175.61 175.61 0 0 1-146-77.8l101.8 4.87a12 12 0 0 0 12.57-12v-47.4a12 12 0 0 0-12-12H12a12 12 0 0 0-12 12V500a12 12 0 0 0 12 12h47.35a12 12 0 0 0 12-12.6l-4.15-82.57A247.17 247.17 0 0 0 255.83 504c121.11 0 221.93-86.92 243.55-201.82a12 12 0 0 0-11.8-14.18h-49.05a12 12 0 0 0-11.67 9.26A175.86 175.86 0 0 1 255.83 432z"},"child":[]}]})(props);
}function FaPaperPlane (props) {
  return GenIcon({"attr":{"viewBox":"0 0 512 512"},"child":[{"tag":"path","attr":{"d":"M476 3.2L12.5 270.6c-18.1 10.4-15.8 35.6 2.2 43.2L121 358.4l287.3-253.2c5.5-4.9 13.3 2.6 8.6 8.3L176 407v80.5c0 23.6 28.5 32.9 42.5 15.8L282 426l124.6 52.2c14.2 6 30.4-2.9 33-18.2l72-432C515 7.8 493.3-6.8 476 3.2z"},"child":[]}]})(props);
}function FaKey (props) {
  return GenIcon({"attr":{"viewBox":"0 0 512 512"},"child":[{"tag":"path","attr":{"d":"M512 176.001C512 273.203 433.202 352 336 352c-11.22 0-22.19-1.062-32.827-3.069l-24.012 27.014A23.999 23.999 0 0 1 261.223 384H224v40c0 13.255-10.745 24-24 24h-40v40c0 13.255-10.745 24-24 24H24c-13.255 0-24-10.745-24-24v-78.059c0-6.365 2.529-12.47 7.029-16.971l161.802-161.802C163.108 213.814 160 195.271 160 176 160 78.798 238.797.001 335.999 0 433.488-.001 512 78.511 512 176.001zM336 128c0 26.51 21.49 48 48 48s48-21.49 48-48-21.49-48-48-48-48 21.49-48 48z"},"child":[]}]})(props);
}function FaExclamationTriangle (props) {
  return GenIcon({"attr":{"viewBox":"0 0 576 512"},"child":[{"tag":"path","attr":{"d":"M569.517 440.013C587.975 472.007 564.806 512 527.94 512H48.054c-36.937 0-59.999-40.055-41.577-71.987L246.423 23.985c18.467-32.009 64.72-31.951 83.154 0l239.94 416.028zM288 354c-25.405 0-46 20.595-46 46s20.595 46 46 46 46-20.595 46-46-20.595-46-46-46zm-43.673-165.346l7.418 136c.347 6.364 5.609 11.346 11.982 11.346h48.546c6.373 0 11.635-4.982 11.982-11.346l7.418-136c.375-6.874-5.098-12.654-11.982-12.654h-63.383c-6.884 0-12.356 5.78-11.981 12.654z"},"child":[]}]})(props);
}function FaDownload (props) {
  return GenIcon({"attr":{"viewBox":"0 0 512 512"},"child":[{"tag":"path","attr":{"d":"M216 0h80c13.3 0 24 10.7 24 24v168h87.7c17.8 0 26.7 21.5 14.1 34.1L269.7 378.3c-7.5 7.5-19.8 7.5-27.3 0L90.1 226.1c-12.6-12.6-3.7-34.1 14.1-34.1H192V24c0-13.3 10.7-24 24-24zm296 376v112c0 13.3-10.7 24-24 24H24c-13.3 0-24-10.7-24-24V376c0-13.3 10.7-24 24-24h146.7l49 49c20.1 20.1 52.5 20.1 72.6 0l49-49H488c13.3 0 24 10.7 24 24zm-124 88c0-11-9-20-20-20s-20 9-20 20 9 20 20 20 20-9 20-20zm64 0c0-11-9-20-20-20s-20 9-20 20 9 20 20 20 20-9 20-20z"},"child":[]}]})(props);
}function FaCheckCircle (props) {
  return GenIcon({"attr":{"viewBox":"0 0 512 512"},"child":[{"tag":"path","attr":{"d":"M504 256c0 136.967-111.033 248-248 248S8 392.967 8 256 119.033 8 256 8s248 111.033 248 248zM227.314 387.314l184-184c6.248-6.248 6.248-16.379 0-22.627l-22.627-22.627c-6.248-6.249-16.379-6.249-22.628 0L216 308.118l-70.059-70.059c-6.248-6.248-16.379-6.248-22.628 0l-22.627 22.627c-6.248 6.248-6.248 16.379 0 22.627l104 104c6.249 6.249 16.379 6.249 22.628.001z"},"child":[]}]})(props);
}function FaBrain (props) {
  return GenIcon({"attr":{"viewBox":"0 0 576 512"},"child":[{"tag":"path","attr":{"d":"M208 0c-29.9 0-54.7 20.5-61.8 48.2-.8 0-1.4-.2-2.2-.2-35.3 0-64 28.7-64 64 0 4.8.6 9.5 1.7 14C52.5 138 32 166.6 32 200c0 12.6 3.2 24.3 8.3 34.9C16.3 248.7 0 274.3 0 304c0 33.3 20.4 61.9 49.4 73.9-.9 4.6-1.4 9.3-1.4 14.1 0 39.8 32.2 72 72 72 4.1 0 8.1-.5 12-1.2 9.6 28.5 36.2 49.2 68 49.2 39.8 0 72-32.2 72-72V64c0-35.3-28.7-64-64-64zm368 304c0-29.7-16.3-55.3-40.3-69.1 5.2-10.6 8.3-22.3 8.3-34.9 0-33.4-20.5-62-49.7-74 1-4.5 1.7-9.2 1.7-14 0-35.3-28.7-64-64-64-.8 0-1.5.2-2.2.2C422.7 20.5 397.9 0 368 0c-35.3 0-64 28.6-64 64v376c0 39.8 32.2 72 72 72 31.8 0 58.4-20.7 68-49.2 3.9.7 7.9 1.2 12 1.2 39.8 0 72-32.2 72-72 0-4.8-.5-9.5-1.4-14.1 29-12 49.4-40.6 49.4-73.9z"},"child":[]}]})(props);
}

const getStatus = callable("status");
const getConfig = callable("get_config");
const saveConfig = callable("save_config");
const installRuntime = callable("install_runtime");
const startTurn = callable("start_turn");
const getTurn = callable("get_turn");
const answerPermission = callable("answer_permission");
const colors = {
    panel: "rgba(20, 23, 28, 0.72)",
    border: "rgba(255, 255, 255, 0.12)",
    muted: "rgba(232, 238, 246, 0.62)",
    text: "rgba(246, 248, 252, 0.96)",
    accent: "#66d9a8",
    warn: "#f6c177",
    danger: "#ff7b72",
};
const modelOptionsByProvider = {
    openai: [
        { label: "GPT-4.1 Mini", value: "gpt-4.1-mini" },
        { label: "GPT-4.1", value: "gpt-4.1" },
        { label: "GPT-4o Mini", value: "gpt-4o-mini" },
    ],
    "openai-chat": [
        { label: "GPT-4.1 Mini", value: "gpt-4.1-mini" },
        { label: "GPT-4.1", value: "gpt-4.1" },
        { label: "GPT-4o Mini", value: "gpt-4o-mini" },
    ],
    deepseek: [
        { label: "DeepSeek V4 Flash", value: "deepseek-v4-flash" },
        { label: "DeepSeek V4 Pro", value: "deepseek-v4-pro" },
        { label: "DeepSeek Chat（兼容，2026-07-24 弃用）", value: "deepseek-chat" },
        { label: "DeepSeek Reasoner（兼容，2026-07-24 弃用）", value: "deepseek-reasoner" },
    ],
    moonshot: [
        { label: "Kimi K2", value: "kimi-k2-0711-preview" },
        { label: "Moonshot v1 8K", value: "moonshot-v1-8k" },
        { label: "Moonshot v1 32K", value: "moonshot-v1-32k" },
    ],
    qwen: [
        { label: "Qwen Plus", value: "qwen-plus" },
        { label: "Qwen Turbo", value: "qwen-turbo" },
        { label: "Qwen Max", value: "qwen-max" },
    ],
};
function defaultModelForProvider(provider) {
    return modelOptionsByProvider[provider]?.[0]?.value ?? "";
}
function welcomeMessageForStatus(status) {
    if (!status.installed) {
        return "先安装 DeckMind Runtime。安装完成后，这个面板会作为 Decky 里的 agent 入口。";
    }
    return "DeckMind Runtime 已就绪。输入指令即可开始。";
}
function nextId() {
    return Date.now() + Math.floor(Math.random() * 1000);
}
function messageStyle(role) {
    const alignSelf = role === "user" ? "flex-end" : "flex-start";
    const background = role === "user"
        ? "rgba(102, 217, 168, 0.16)"
        : role === "system"
            ? "rgba(246, 193, 119, 0.12)"
            : "rgba(255, 255, 255, 0.08)";
    const borderColor = role === "system" ? "rgba(246, 193, 119, 0.28)" : colors.border;
    return {
        alignSelf,
        background,
        border: `1px solid ${borderColor}`,
        borderRadius: 8,
        color: colors.text,
        lineHeight: 1.35,
        maxWidth: "92%",
        padding: "8px 10px",
        whiteSpace: "pre-wrap",
        wordBreak: "break-word",
    };
}
function StatusBar({ busy, config, onRefresh, status, }) {
    const installed = Boolean(status?.installed);
    const hasApiKey = Boolean(config?.has_api_key);
    const badgeStyle = (ok) => ({
        alignItems: "center",
        background: ok ? "rgba(102, 217, 168, 0.09)" : "rgba(246, 193, 119, 0.09)",
        border: `1px solid ${ok ? "rgba(102, 217, 168, 0.25)" : "rgba(246, 193, 119, 0.25)"}`,
        borderRadius: 12,
        color: ok ? colors.accent : colors.warn,
        display: "inline-flex",
        fontSize: 11,
        fontWeight: 600,
        gap: 4,
        padding: "3px 8px",
    });
    return (SP_JSX.jsxs("div", { style: {
            alignItems: "center",
            background: "rgba(13, 17, 23, 0.88)",
            borderBottom: "1px solid rgba(255, 255, 255, 0.08)",
            cursor: busy ? "default" : "pointer",
            display: "flex",
            gap: 6,
            justifyContent: "flex-end",
            opacity: busy ? 0.72 : 1,
            padding: "8px 12px",
        }, onClick: () => {
            if (!busy) {
                onRefresh();
            }
        }, onKeyDown: (event) => {
            if (!busy && (event.key === "Enter" || event.key === " ")) {
                event.preventDefault();
                onRefresh();
            }
        }, role: "button", tabIndex: 0, "aria-disabled": busy, "aria-label": "\u5237\u65B0 DeckMind \u72B6\u6001", title: "\u70B9\u51FB\u5237\u65B0\u72B6\u6001", children: [SP_JSX.jsxs("div", { style: badgeStyle(installed), children: [installed ? SP_JSX.jsx(FaCheckCircle, { size: 11 }) : SP_JSX.jsx(FaExclamationTriangle, { size: 11 }), installed ? status?.version ?? "unknown" : "未安装"] }), SP_JSX.jsxs("div", { style: badgeStyle(hasApiKey), children: [SP_JSX.jsx(FaKey, { size: 11 }), hasApiKey ? config?.provider ?? "API" : "未配置"] })] }));
}
function RuntimeCard({ busy, onInstall, onRefresh, status, }) {
    const installed = Boolean(status?.installed);
    const label = installed ? `已安装 ${status?.version ?? "unknown"}` : "未安装 Runtime";
    const detail = installed ? status?.runtime_dir : status?.runtime_url;
    return (SP_JSX.jsxs(DFL.PanelSection, { title: "Runtime", children: [SP_JSX.jsx(DFL.PanelSectionRow, { children: SP_JSX.jsxs("div", { style: {
                        background: colors.panel,
                        border: `1px solid ${installed ? colors.border : colors.warn}`,
                        borderRadius: 8,
                        color: colors.text,
                        display: "flex",
                        flexDirection: "column",
                        gap: 8,
                        padding: 10,
                    }, children: [SP_JSX.jsxs("div", { style: { alignItems: "center", display: "flex", gap: 8 }, children: [installed ? SP_JSX.jsx(FaCheckCircle, { color: colors.accent }) : SP_JSX.jsx(FaExclamationTriangle, { color: colors.warn }), SP_JSX.jsx("strong", { children: label })] }), SP_JSX.jsx("div", { style: { color: colors.muted, fontSize: 12, lineHeight: 1.35, wordBreak: "break-word" }, children: detail })] }) }), SP_JSX.jsx(DFL.PanelSectionRow, { children: SP_JSX.jsxs("div", { style: { display: "flex", flexDirection: "column", gap: 8, width: "100%" }, children: [!installed && (SP_JSX.jsx(DFL.ButtonItem, { disabled: busy, layout: "below", onClick: onInstall, children: SP_JSX.jsxs("span", { style: { alignItems: "center", display: "inline-flex", gap: 8 }, children: [SP_JSX.jsx(FaDownload, {}), "\u5B89\u88C5 Runtime"] }) })), SP_JSX.jsx(DFL.ButtonItem, { disabled: busy, layout: "below", onClick: onRefresh, children: SP_JSX.jsxs("span", { style: { alignItems: "center", display: "inline-flex", gap: 8 }, children: [SP_JSX.jsx(FaSync, {}), "\u5237\u65B0\u72B6\u6001"] }) })] }) })] }));
}
function ConfigCard({ busy, config, onSaved, }) {
    const [provider, setProvider] = SP_REACT.useState(config?.provider ?? "openai");
    const [model, setModel] = SP_REACT.useState(config?.model ?? "");
    const [apiKey, setApiKey] = SP_REACT.useState("");
    const modelOptions = modelOptionsByProvider[provider] ?? [];
    SP_REACT.useEffect(() => {
        if (config) {
            setProvider(config.provider);
            setModel(config.model || defaultModelForProvider(config.provider));
        }
    }, [config]);
    SP_REACT.useEffect(() => {
        if (!modelOptions.some((option) => option.value === model)) {
            setModel(defaultModelForProvider(provider));
        }
    }, [model, modelOptions, provider]);
    const updateProvider = (nextProvider) => {
        setProvider(nextProvider);
        setModel(defaultModelForProvider(nextProvider));
    };
    const persist = async () => {
        const saved = await saveConfig({ provider, model, api_key: apiKey });
        setApiKey("");
        onSaved(saved);
    };
    return (SP_JSX.jsx(DFL.PanelSection, { title: "\u914D\u7F6E", children: SP_JSX.jsx(DFL.PanelSectionRow, { children: SP_JSX.jsxs("div", { style: {
                    background: colors.panel,
                    border: `1px solid ${colors.border}`,
                    borderRadius: 10,
                    boxSizing: "border-box",
                    display: "flex",
                    flexDirection: "column",
                    gap: 8,
                    padding: 10,
                    width: "100%",
                }, children: [SP_JSX.jsxs("select", { disabled: busy, onChange: (event) => updateProvider(event.currentTarget.value), style: {
                            background: "rgba(0, 0, 0, 0.22)",
                            border: `1px solid ${colors.border}`,
                            borderRadius: 8,
                            color: colors.text,
                            minHeight: 36,
                            padding: "7px 9px",
                        }, value: provider, children: [SP_JSX.jsx("option", { value: "openai", children: "OpenAI" }), SP_JSX.jsx("option", { value: "openai-chat", children: "OpenAI Chat" }), SP_JSX.jsx("option", { value: "deepseek", children: "DeepSeek" }), SP_JSX.jsx("option", { value: "moonshot", children: "Moonshot" }), SP_JSX.jsx("option", { value: "qwen", children: "Qwen" })] }), SP_JSX.jsx("select", { disabled: busy, onChange: (event) => setModel(event.currentTarget.value), style: {
                            background: "rgba(0, 0, 0, 0.22)",
                            border: `1px solid ${colors.border}`,
                            borderRadius: 8,
                            boxSizing: "border-box",
                            color: colors.text,
                            minHeight: 36,
                            padding: "7px 9px",
                            width: "100%",
                        }, value: model, children: modelOptions.map((option) => (SP_JSX.jsx("option", { value: option.value, children: option.label }, option.value))) }), SP_JSX.jsx("input", { disabled: busy, onChange: (event) => setApiKey(event.currentTarget.value), placeholder: config?.has_api_key ? "API key 已保存，留空不修改" : "输入 API key", style: {
                            background: "rgba(0, 0, 0, 0.22)",
                            border: `1px solid ${config?.has_api_key ? colors.border : colors.warn}`,
                            borderRadius: 8,
                            boxSizing: "border-box",
                            color: colors.text,
                            minHeight: 36,
                            padding: "7px 9px",
                            width: "100%",
                        }, type: "password", value: apiKey }), SP_JSX.jsx(DFL.ButtonItem, { disabled: busy, layout: "below", onClick: () => void persist(), children: "\u4FDD\u5B58\u914D\u7F6E" })] }) }) }));
}
function Content() {
    const [status, setStatus] = SP_REACT.useState(null);
    const [config, setConfig] = SP_REACT.useState(null);
    const [busy, setBusy] = SP_REACT.useState(false);
    const [draft, setDraft] = SP_REACT.useState("");
    const [activeTurnId, setActiveTurnId] = SP_REACT.useState(null);
    const [permissionRequest, setPermissionRequest] = SP_REACT.useState(null);
    const [seenEventCount, setSeenEventCount] = SP_REACT.useState(0);
    const [pollVersion, setPollVersion] = SP_REACT.useState(0);
    const [messages, setMessages] = SP_REACT.useState([]);
    const appendMessage = (role, text) => {
        setMessages((current) => [...current, { id: nextId(), role, text }]);
    };
    const refresh = async () => {
        try {
            const [latestStatus, latestConfig] = await Promise.all([
                getStatus(),
                getConfig(),
            ]);
            setStatus(latestStatus);
            setConfig(latestConfig);
            setMessages((current) => current.length > 0
                ? current
                : [
                    {
                        id: 1,
                        role: "assistant",
                        text: welcomeMessageForStatus(latestStatus),
                    },
                ]);
        }
        catch (error) {
            const body = String(error);
            appendMessage("system", body);
            toaster.toast({ title: "DeckMind 状态读取失败", body });
        }
    };
    SP_REACT.useEffect(() => {
        void refresh();
    }, []);
    SP_REACT.useEffect(() => {
        if (!activeTurnId) {
            return;
        }
        let cancelled = false;
        const poll = async () => {
            try {
                const state = await getTurn(activeTurnId);
                if (cancelled) {
                    return;
                }
                if (state.events.length > seenEventCount) {
                    const newEvents = state.events.slice(seenEventCount);
                    setSeenEventCount(state.events.length);
                    const toolEvents = newEvents
                        .filter((event) => event.type === "tool_start" || event.type === "tool_result")
                        .map((event) => `${event.type}: ${event.name ?? ""}`)
                        .join("\n");
                    if (toolEvents) {
                        appendMessage("system", toolEvents);
                    }
                }
                if (state.status === "waiting_permission" && state.permission_request) {
                    setPermissionRequest(state.permission_request);
                    setBusy(false);
                    return;
                }
                if (state.status === "completed") {
                    setPermissionRequest(null);
                    setActiveTurnId(null);
                    setBusy(false);
                    if (state.reply) {
                        appendMessage("assistant", state.reply);
                    }
                    return;
                }
                if (state.status === "failed") {
                    setPermissionRequest(null);
                    setActiveTurnId(null);
                    setBusy(false);
                    appendMessage("system", state.error ?? "Runtime 执行失败");
                    return;
                }
            }
            catch (error) {
                if (!cancelled) {
                    setPermissionRequest(null);
                    setActiveTurnId(null);
                    setBusy(false);
                    appendMessage("system", String(error));
                }
                return;
            }
            window.setTimeout(() => void poll(), 500);
        };
        void poll();
        return () => {
            cancelled = true;
        };
    }, [activeTurnId, pollVersion, seenEventCount]);
    const runInstall = async () => {
        setBusy(true);
        try {
            appendMessage("system", "开始下载并安装 Runtime...");
            const result = await installRuntime();
            await refresh();
            if (result.ok) {
                appendMessage("assistant", `Runtime 已安装到 ${result.runtime_dir ?? "本机目录"}`);
            }
            else {
                appendMessage("system", result.error ?? "Runtime 安装失败");
            }
        }
        catch (error) {
            const body = String(error);
            appendMessage("system", body);
            toaster.toast({ title: "DeckMind 安装失败", body });
        }
        finally {
            setBusy(false);
        }
    };
    const send = async () => {
        const text = draft.trim();
        if (!text || busy) {
            return;
        }
        setDraft("");
        setBusy(true);
        appendMessage("user", text);
        try {
            setSeenEventCount(0);
            setPermissionRequest(null);
            const result = await startTurn(text);
            if (result.ok && result.turn_id) {
                setActiveTurnId(result.turn_id);
            }
            else if (result.error === "missing_api_key" && result.missing_api_key) {
                setBusy(false);
                appendMessage("system", `缺少 ${result.missing_api_key}，请保存 API key`);
            }
            else {
                setBusy(false);
                appendMessage("system", result.error ?? "Runtime 暂不可用");
            }
        }
        catch (error) {
            setBusy(false);
            appendMessage("system", String(error));
        }
    };
    const respondToPermission = async (decision) => {
        if (!activeTurnId || !permissionRequest) {
            return;
        }
        setBusy(true);
        const result = await answerPermission(activeTurnId, permissionRequest.request_id, decision);
        if (result.ok) {
            appendMessage("system", `权限响应：${decision}`);
            setPermissionRequest(null);
            setPollVersion((value) => value + 1);
        }
        else {
            appendMessage("system", result.error ?? "权限响应失败");
            setBusy(false);
        }
    };
    const canSend = SP_REACT.useMemo(() => Boolean(status?.installed) && draft.trim().length > 0 && !busy, [busy, draft, status?.installed]);
    const installed = Boolean(status?.installed);
    return (SP_JSX.jsxs("div", { style: { display: "flex", flexDirection: "column", gap: 10 }, children: [SP_JSX.jsx(StatusBar, { busy: busy, config: config, onRefresh: () => void refresh(), status: status }), !installed && (SP_JSX.jsx(RuntimeCard, { busy: busy, onInstall: () => void runInstall(), onRefresh: () => void refresh(), status: status })), SP_JSX.jsx(ConfigCard, { busy: busy, config: config, onSaved: (saved) => {
                    setConfig(saved);
                    appendMessage("system", "配置已保存");
                } }), permissionRequest && (SP_JSX.jsx(DFL.PanelSection, { title: "\u9700\u8981\u786E\u8BA4", children: SP_JSX.jsx(DFL.PanelSectionRow, { children: SP_JSX.jsxs("div", { style: {
                            background: "rgba(20, 23, 28, 0.94)",
                            border: `1px solid rgba(246, 193, 119, 0.28)`,
                            borderRadius: 10,
                            color: colors.text,
                            display: "flex",
                            flexDirection: "column",
                            overflow: "hidden",
                        }, children: [SP_JSX.jsxs("div", { style: { display: "flex", flexDirection: "column", gap: 6, padding: 12 }, children: [SP_JSX.jsx("div", { style: { fontWeight: 700 }, children: permissionRequest.name }), SP_JSX.jsx("div", { style: { color: colors.muted, fontSize: 12, wordBreak: "break-word" }, children: permissionRequest.message }), SP_JSX.jsx("div", { style: { color: "rgba(232, 238, 246, 0.32)", fontSize: 11, wordBreak: "break-word" }, children: JSON.stringify(permissionRequest.arguments) })] }), SP_JSX.jsxs("div", { style: {
                                    borderTop: "1px solid rgba(246, 193, 119, 0.19)",
                                    display: "flex",
                                    gap: 6,
                                    padding: 8,
                                }, children: [SP_JSX.jsx("button", { disabled: busy, onClick: () => void respondToPermission("allow"), style: {
                                            background: "rgba(102, 217, 168, 0.15)",
                                            border: "1px solid rgba(102, 217, 168, 0.31)",
                                            borderRadius: 6,
                                            color: colors.accent,
                                            cursor: "pointer",
                                            flex: 1,
                                            fontSize: 13,
                                            fontWeight: 600,
                                            padding: "7px 0",
                                        }, children: "\u5141\u8BB8" }), SP_JSX.jsx("button", { disabled: busy, onClick: () => void respondToPermission("allow_all"), style: {
                                            background: "rgba(255, 255, 255, 0.06)",
                                            border: "1px solid rgba(255, 255, 255, 0.12)",
                                            borderRadius: 6,
                                            color: "rgba(246, 248, 252, 0.82)",
                                            cursor: "pointer",
                                            flex: 1,
                                            fontSize: 13,
                                            padding: "7px 0",
                                        }, children: "\u672C\u6B21" }), SP_JSX.jsx("button", { disabled: busy, onClick: () => void respondToPermission("deny"), style: {
                                            background: "rgba(255, 123, 114, 0.09)",
                                            border: "1px solid rgba(255, 123, 114, 0.25)",
                                            borderRadius: 6,
                                            color: colors.danger,
                                            cursor: "pointer",
                                            flex: 1,
                                            fontSize: 13,
                                            fontWeight: 600,
                                            padding: "7px 0",
                                        }, children: "\u62D2\u7EDD" })] })] }) }) })), SP_JSX.jsx(DFL.PanelSection, { title: "\u5BF9\u8BDD", children: SP_JSX.jsx(DFL.PanelSectionRow, { children: SP_JSX.jsx("div", { style: {
                            display: "flex",
                            flexDirection: "column",
                            gap: 8,
                            maxHeight: 320,
                            minHeight: 160,
                            overflowY: "auto",
                            paddingRight: 2,
                        }, children: messages.map((message) => (SP_JSX.jsx("div", { style: messageStyle(message.role), children: message.text }, message.id))) }) }) }), SP_JSX.jsx(DFL.PanelSection, { children: SP_JSX.jsx(DFL.PanelSectionRow, { children: SP_JSX.jsxs("div", { style: { display: "flex", flexDirection: "column", gap: 8, width: "100%" }, children: [SP_JSX.jsx("input", { disabled: !status?.installed || busy, onChange: (event) => setDraft(event.currentTarget.value), onKeyDown: (event) => {
                                    if (event.key === "Enter") {
                                        void send();
                                    }
                                }, placeholder: status?.installed ? "输入指令..." : "先安装 Runtime", style: {
                                    background: "rgba(0, 0, 0, 0.22)",
                                    border: `1px solid ${colors.border}`,
                                    borderRadius: 8,
                                    boxSizing: "border-box",
                                    color: colors.text,
                                    fontSize: 14,
                                    minHeight: 38,
                                    outline: "none",
                                    padding: "8px 10px",
                                    width: "100%",
                                }, type: "text", value: draft }), SP_JSX.jsx(DFL.ButtonItem, { disabled: !canSend, layout: "below", onClick: () => void send(), children: SP_JSX.jsxs("span", { style: { alignItems: "center", display: "inline-flex", gap: 8 }, children: [SP_JSX.jsx(FaPaperPlane, {}), "\u53D1\u9001"] }) })] }) }) })] }));
}
var index = definePlugin(() => ({
    name: "DeckMind",
    titleView: (SP_JSX.jsxs("div", { className: DFL.staticClasses.Title, style: { alignItems: "center", display: "flex", gap: 8 }, children: [SP_JSX.jsx(FaBrain, {}), SP_JSX.jsx("span", { children: "DeckMind" })] })),
    content: SP_JSX.jsx(Content, {}),
    icon: SP_JSX.jsx(FaTerminal, {}),
}));

export { index as default };
//# sourceMappingURL=index.js.map
