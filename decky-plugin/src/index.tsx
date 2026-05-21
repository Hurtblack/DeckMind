import {
  ButtonItem,
  PanelSection,
  PanelSectionRow,
  staticClasses,
} from "@decky/ui";
import { callable, definePlugin, toaster } from "@decky/api";
import { useEffect, useMemo, useRef, useState } from "react";
import {
  FaBrain,
  FaCheckCircle,
  FaCopy,
  FaDownload,
  FaExclamationTriangle,
  FaKey,
  FaPaperPlane,
  FaSync,
  FaTerminal,
  FaTrash,
} from "react-icons/fa";

type RuntimeStatus = {
  ok: boolean;
  installed: boolean;
  runtime_dir: string;
  version: string | null;
  commit?: string | null;
  entrypoint: string;
  runtime_url?: string;
  repo_url?: string;
  branch?: string;
  config?: RuntimeConfig;
};

type BackendResult = {
  ok: boolean;
  installed?: boolean;
  runtime_dir?: string;
  version?: string | null;
  reply?: string;
  events?: RuntimeEvent[];
  missing_api_key?: string;
  error?: string;
  deps?: {
    ok?: boolean;
    error?: string;
  };
  plugin?: {
    ok: boolean;
    files?: number;
    note?: string;
    skipped?: string;
    error?: string;
  };
};

type RuntimeConfig = {
  ok: boolean;
  provider: string;
  model: string;
  has_api_key: boolean;
};

type FrontendAction = {
  type: "run_game" | "terminate_game";
  app_id?: string;
  game_id?: string;
  game?: string;
};

type ToolResult = {
  frontend_action?: FrontendAction;
  [key: string]: unknown;
};

type RuntimeEvent = {
  type: string;
  name?: string;
  risk?: string;
  decision?: string;
  result?: ToolResult;
};

type PermissionRequest = {
  request_id: string;
  name: string;
  arguments: Record<string, unknown>;
  risk: string;
  message: string;
};

type TurnState = {
  ok: boolean;
  turn_id: string;
  status: "running" | "waiting_permission" | "completed" | "failed";
  reply: string | null;
  error: string | null;
  model: string | null;
  events: RuntimeEvent[];
  permission_request: PermissionRequest | null;
};

type Message = {
  id: number;
  role: "user" | "assistant" | "system";
  text: string;
};

const getStatus = callable<[], RuntimeStatus>("status");
const getConfig = callable<[], RuntimeConfig>("get_config");
const saveConfig = callable<[config: Record<string, string>], RuntimeConfig>("save_config");
const installRuntime = callable<[], BackendResult>("install_runtime");

type InstallProgressEvent = {
  ts: number;
  stage: string;
  status: "start" | "ok" | "fail" | "skip" | "info" | "try";
  message: string;
  extra?: Record<string, unknown>;
};
const getInstallProgress = callable<
  [since: number],
  { events: InstallProgressEvent[]; total: number; running: boolean }
>("get_install_progress");

const STATUS_GLYPH: Record<InstallProgressEvent["status"], string> = {
  start: "▶",
  try: "·",
  info: "·",
  ok: "✓",
  fail: "✗",
  skip: "—",
};
const formatInstallEvent = (e: InstallProgressEvent): string => {
  const glyph = STATUS_GLYPH[e.status] ?? "·";
  const tail = e.message ? ` ${e.message}` : "";
  return `${glyph} [${e.stage}]${tail}`;
};
const startTurn = callable<[message: string], BackendResult & { turn_id?: string }>("start_turn");
const getTurn = callable<[turnId: string], TurnState>("get_turn");
const answerPermission = callable<
  [turnId: string, requestId: string, decision: string],
  BackendResult
>("answer_permission");
const resetSession = callable<
  [messages: Message[]],
  BackendResult & { remembered?: { key: string; value: string }[] }
>("reset_session");

const colors = {
  panel: "rgba(20, 23, 28, 0.72)",
  border: "rgba(255, 255, 255, 0.12)",
  muted: "rgba(232, 238, 246, 0.62)",
  text: "rgba(246, 248, 252, 0.96)",
  accent: "#66d9a8",
  warn: "#f6c177",
  danger: "#ff7b72",
};

const modelOptionsByProvider: Record<string, { label: string; value: string }[]> = {
  openai: [
    { label: "GPT-5.5", value: "gpt-5.5" },
    { label: "GPT-5.4 Mini", value: "gpt-5.4-mini" },
    { label: "GPT-5.4 Nano", value: "gpt-5.4-nano" },
    { label: "GPT-5.3 Codex", value: "gpt-5.3-codex" },
    { label: "GPT-4.1（兼容旧）", value: "gpt-4.1" },
    { label: "GPT-4o Mini（兼容旧）", value: "gpt-4o-mini" },
  ],
  "openai-chat": [
    { label: "GPT-5.5", value: "gpt-5.5" },
    { label: "GPT-5.4 Mini", value: "gpt-5.4-mini" },
    { label: "GPT-5.4 Nano", value: "gpt-5.4-nano" },
    { label: "GPT-4.1（兼容旧）", value: "gpt-4.1" },
    { label: "GPT-4o Mini（兼容旧）", value: "gpt-4o-mini" },
  ],
  anthropic: [
    { label: "Claude Opus 4.7", value: "claude-opus-4-7" },
    { label: "Claude Sonnet 4.6", value: "claude-sonnet-4-6" },
    { label: "Claude Haiku 4.5", value: "claude-haiku-4-5" },
  ],
  deepseek: [
    { label: "DeepSeek V4 Flash", value: "deepseek-v4-flash" },
    { label: "DeepSeek V4 Pro", value: "deepseek-v4-pro" },
    { label: "DeepSeek Chat（兼容，2026-07-24 弃用）", value: "deepseek-chat" },
    { label: "DeepSeek Reasoner（兼容，2026-07-24 弃用）", value: "deepseek-reasoner" },
  ],
  moonshot: [
    { label: "Kimi K2.6", value: "kimi-k2.6" },
    { label: "Kimi K2.5（多模态）", value: "kimi-k2.5" },
    { label: "Moonshot v1 8K（兼容旧）", value: "moonshot-v1-8k" },
    { label: "Moonshot v1 32K（兼容旧）", value: "moonshot-v1-32k" },
  ],
  "moonshot-global": [
    { label: "Kimi K2.6", value: "kimi-k2.6" },
    { label: "Kimi K2.5（多模态）", value: "kimi-k2.5" },
    { label: "Moonshot v1 8K（兼容旧）", value: "moonshot-v1-8k" },
    { label: "Moonshot v1 32K（兼容旧）", value: "moonshot-v1-32k" },
  ],
  qwen: [
    { label: "Qwen Plus", value: "qwen-plus" },
    { label: "Qwen Turbo", value: "qwen-turbo" },
    { label: "Qwen Max", value: "qwen-max" },
  ],
};

function defaultModelForProvider(provider: string) {
  return modelOptionsByProvider[provider]?.[0]?.value ?? "";
}

function welcomeMessageForStatus(status: RuntimeStatus) {
  if (!status.installed) {
    return "先安装 DeckMind Runtime。安装完成后，这个面板会作为 Decky 里的 agent 入口。";
  }

  return "DeckMind Runtime 已就绪。输入指令即可开始。";
}

function nextId() {
  return Date.now() + Math.floor(Math.random() * 1000);
}

// 对话历史持久化到 localStorage，避免切走面板再切回 / Steam 重启就清空。
const HISTORY_KEY = "deckmind:chat-history";
const HISTORY_LIMIT = 200;

function loadHistory(): Message[] {
  try {
    const raw = window.localStorage.getItem(HISTORY_KEY);
    if (!raw) {
      return [];
    }
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed) ? (parsed as Message[]) : [];
  } catch {
    return [];
  }
}

function saveHistory(messages: Message[]) {
  try {
    window.localStorage.setItem(
      HISTORY_KEY,
      JSON.stringify(messages.slice(-HISTORY_LIMIT)),
    );
  } catch {
    /* 隐私模式 / 容量超限：丢历史不影响主流程 */
  }
}

async function copyToClipboard(text: string) {
  // 1) 优先用现代 API（部分 Steam CEF 上下文可用）
  try {
    if (typeof navigator !== "undefined" && navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(text);
      toaster.toast({ title: "DeckMind", body: "已复制到剪贴板" });
      return;
    }
  } catch {
    /* 落到下面的 fallback */
  }

  // 2) Fallback：隐藏 textarea + execCommand('copy')
  // Steam gamescope 的 CEF 常禁用 navigator.clipboard（非安全上下文），
  // 但老的 execCommand 仍可用。
  try {
    const ta = document.createElement("textarea");
    ta.value = text;
    ta.setAttribute("readonly", "");
    ta.style.position = "fixed";
    ta.style.top = "-9999px";
    ta.style.left = "-9999px";
    ta.style.opacity = "0";
    document.body.appendChild(ta);
    ta.focus();
    ta.select();
    ta.setSelectionRange(0, text.length);
    const ok = document.execCommand("copy");
    document.body.removeChild(ta);
    toaster.toast({
      title: "DeckMind",
      body: ok ? "已复制到剪贴板" : "复制失败，请手动选择文本",
    });
  } catch {
    toaster.toast({ title: "DeckMind", body: "复制失败，请手动选择文本" });
  }
}

// 通过 Steam 内部 API 执行前端动作（启动/关闭游戏），避免 steam:// URI 的确认弹窗。
// 返回人类可读的结果文案，供对话区显示。
function runFrontendAction(action: FrontendAction): string {
  // SteamClient 由 Steam 注入、@decky/ui 提供类型。其 Apps 上的具体方法签名
  // 在不同 Steam 版本间会变，这里用 any 调用以保持兼容。
  const apps = (SteamClient as unknown as { Apps?: Record<string, unknown> })?.Apps;
  if (!apps) {
    return "✗ 当前环境没有 SteamClient（可能不在 Steam 中运行），无法直接启动游戏";
  }
  const gameId = action.game_id ?? action.app_id;
  if (!gameId) {
    return "✗ 缺少 app_id / game_id，无法启动";
  }
  const label = action.game ?? gameId;
  // [DECKMIND-DIAG] 临时诊断：定位 "Unknown method" 报错来源。确认后删除。
  try {
    console.log("[DeckMind] runFrontendAction", {
      type: action.type,
      gameId,
      appsKeys: Object.keys(apps),
      RunGameType: typeof (apps as Record<string, unknown>).RunGame,
      RunGameSrc: String((apps as Record<string, unknown>).RunGame).slice(0, 300),
      TerminateAppType: typeof (apps as Record<string, unknown>).TerminateApp,
    });
  } catch (diagErr) {
    console.log("[DeckMind] diag dump failed", diagErr);
  }
  try {
    if (action.type === "run_game") {
      const run = apps.RunGame as
        | ((g: string, s: string, a: number, b: number) => void)
        | undefined;
      if (!run) {
        return "✗ SteamClient.Apps.RunGame 不可用";
      }
      run(gameId, "", -1, 100);
      return `▶ 已通过 Steam 启动「${label}」（appid ${gameId}）`;
    }
    if (action.type === "terminate_game") {
      const terminate = apps.TerminateApp as
        | ((g: string, force: boolean) => void)
        | undefined;
      if (!terminate) {
        return "✗ SteamClient.Apps.TerminateApp 不可用";
      }
      terminate(gameId, false);
      return `■ 已通过 Steam 关闭「${label}」`;
    }
    return `✗ 未知前端动作：${action.type}`;
  } catch (e) {
    // [DECKMIND-DIAG] 把完整 error 打到控制台（含 message / stack），
    // String(e) 只能拿到首行。确认后删除。
    const err = e as { name?: string; message?: string; stack?: string };
    console.error("[DeckMind] SteamClient call threw", {
      name: err?.name,
      message: err?.message,
      stack: err?.stack,
      raw: e,
    });
    const detail = err?.message ?? String(e);
    return `✗ 调用 SteamClient 失败：${detail}`;
  }
}

function messageStyle(role: Message["role"]) {
  const alignSelf = role === "user" ? "flex-end" : "flex-start";
  const background =
    role === "user"
      ? "rgba(102, 217, 168, 0.16)"
      : role === "system"
        ? "rgba(246, 193, 119, 0.12)"
        : "rgba(255, 255, 255, 0.08)";
  const borderColor =
    role === "system" ? "rgba(246, 193, 119, 0.28)" : colors.border;

  return {
    alignSelf,
    background,
    border: `1px solid ${borderColor}`,
    borderRadius: 8,
    color: colors.text,
    lineHeight: 1.35,
    maxWidth: "92%",
    padding: "8px 10px",
    whiteSpace: "pre-wrap" as const,
    wordBreak: "break-word" as const,
  };
}

function StatusBar({
  busy,
  config,
  configOpen,
  onRefresh,
  onToggleConfig,
  status,
}: {
  busy: boolean;
  config: RuntimeConfig | null;
  configOpen: boolean;
  onRefresh: () => void;
  onToggleConfig: () => void;
  status: RuntimeStatus | null;
}) {
  const installed = status?.installed === true;
  const runtimeLabel = status
    ? installed
      ? status.version ?? "unknown"
      : "未安装"
    : "检测中";
  const hasApiKey = Boolean(config?.has_api_key);

  const badgeStyle = (ok: boolean) => ({
    alignItems: "center" as const,
    background: ok ? "rgba(102, 217, 168, 0.09)" : "rgba(246, 193, 119, 0.09)",
    border: `1px solid ${ok ? "rgba(102, 217, 168, 0.25)" : "rgba(246, 193, 119, 0.25)"}`,
    borderRadius: 12,
    color: ok ? colors.accent : colors.warn,
    display: "inline-flex" as const,
    fontSize: 11,
    fontWeight: 600,
    gap: 4,
    padding: "3px 8px",
  });

  return (
    <div
      style={{
        alignItems: "center",
        background: "rgba(13, 17, 23, 0.88)",
        borderBottom: "1px solid rgba(255, 255, 255, 0.08)",
        cursor: busy ? "default" : "pointer",
        display: "flex",
        gap: 6,
        justifyContent: "flex-end",
        opacity: busy ? 0.72 : 1,
        padding: "8px 12px",
      }}
      onClick={() => {
        if (!busy) {
          onRefresh();
        }
      }}
      onKeyDown={(event) => {
        if (!busy && (event.key === "Enter" || event.key === " ")) {
          event.preventDefault();
          onRefresh();
        }
      }}
      role="button"
      tabIndex={0}
      aria-disabled={busy}
      aria-label="刷新 DeckMind 状态"
      title="点击刷新状态"
    >
      <div style={badgeStyle(installed)}>
        {installed ? <FaCheckCircle size={11} /> : <FaExclamationTriangle size={11} />}
        {runtimeLabel}
      </div>
      <div
        style={{ ...badgeStyle(hasApiKey), cursor: busy ? "default" : "pointer" }}
        onClick={(event) => {
          // Don't trigger the parent's onRefresh.
          event.stopPropagation();
          if (!busy) {
            onToggleConfig();
          }
        }}
        onKeyDown={(event) => {
          if (!busy && (event.key === "Enter" || event.key === " ")) {
            event.preventDefault();
            event.stopPropagation();
            onToggleConfig();
          }
        }}
        role="button"
        tabIndex={0}
        aria-pressed={configOpen}
        aria-label={hasApiKey ? "切换 provider / 模型 / API key" : "配置 provider 和 API key"}
        title={hasApiKey ? "点击切换 provider 或更换 API key" : "点击配置 API key"}
      >
        <FaKey size={11} />
        {hasApiKey ? config?.provider ?? "API" : "未配置"}
        <span style={{ opacity: 0.6, fontSize: 9, marginLeft: 2 }}>
          {configOpen ? "▴" : "▾"}
        </span>
      </div>
    </div>
  );
}

function RuntimeCard({
  busy,
  onInstall,
  onUpdate,
  onRefresh,
  status,
}: {
  busy: boolean;
  onInstall: () => void;
  onUpdate: () => void;
  onRefresh: () => void;
  status: RuntimeStatus | null;
}) {
  const installed = Boolean(status?.installed);
  const commit = status?.commit ?? null;
  const label = installed
    ? `已安装${commit ? ` · ${commit}` : ` ${status?.version ?? "unknown"}`}`
    : "未安装 Runtime";
  const detail = installed ? status?.runtime_dir : status?.runtime_url;

  return (
    <PanelSection title="Runtime">
      <PanelSectionRow>
        <div
          style={{
            background: colors.panel,
            border: `1px solid ${installed ? colors.border : colors.warn}`,
            borderRadius: 8,
            color: colors.text,
            display: "flex",
            flexDirection: "column",
            gap: 8,
            padding: 10,
          }}
        >
          <div style={{ alignItems: "center", display: "flex", gap: 8 }}>
            {installed ? <FaCheckCircle color={colors.accent} /> : <FaExclamationTriangle color={colors.warn} />}
            <strong>{label}</strong>
          </div>
          <div style={{ color: colors.muted, fontSize: 12, lineHeight: 1.35, wordBreak: "break-word" }}>
            {detail}
          </div>
        </div>
      </PanelSectionRow>
      <PanelSectionRow>
        <div style={{ display: "flex", flexDirection: "column", gap: 8, width: "100%" }}>
          {!installed && (
            <ButtonItem disabled={busy} layout="below" onClick={onInstall}>
              <span style={{ alignItems: "center", display: "inline-flex", gap: 8 }}>
                <FaDownload />
                安装 Runtime
              </span>
            </ButtonItem>
          )}
          {installed && (
            <ButtonItem disabled={busy} layout="below" onClick={onUpdate}>
              <span style={{ alignItems: "center", display: "inline-flex", gap: 8 }}>
                <FaDownload />
                更新 Runtime（git pull）
              </span>
            </ButtonItem>
          )}
          <ButtonItem disabled={busy} layout="below" onClick={onRefresh}>
            <span style={{ alignItems: "center", display: "inline-flex", gap: 8 }}>
              <FaSync />
              刷新状态
            </span>
          </ButtonItem>
        </div>
      </PanelSectionRow>
    </PanelSection>
  );
}

function ConfigCard({
  busy,
  config,
  onSaved,
  onApiKeySaved,
}: {
  busy: boolean;
  config: RuntimeConfig | null;
  onSaved: (config: RuntimeConfig) => void;
  onApiKeySaved?: () => void;
}) {
  const [provider, setProvider] = useState(config?.provider ?? "openai");
  const [model, setModel] = useState(config?.model ?? "");
  const [apiKey, setApiKey] = useState("");
  const modelOptions = modelOptionsByProvider[provider] ?? [];

  useEffect(() => {
    if (config) {
      setProvider(config.provider);
      setModel(config.model || defaultModelForProvider(config.provider));
    }
  }, [config]);

  useEffect(() => {
    if (!modelOptions.some((option) => option.value === model)) {
      setModel(defaultModelForProvider(provider));
    }
  }, [model, modelOptions, provider]);

  // 切下拉框立刻持久化，避免"改了 UI 但发消息时还是旧配置"
  const persistSelection = async (nextProvider: string, nextModel: string) => {
    const saved = await saveConfig({
      provider: nextProvider,
      model: nextModel,
      api_key: "",
    });
    onSaved(saved);
  };

  const updateProvider = (nextProvider: string) => {
    const nextModel = defaultModelForProvider(nextProvider);
    setProvider(nextProvider);
    setModel(nextModel);
    void persistSelection(nextProvider, nextModel);
  };

  const updateModel = (nextModel: string) => {
    setModel(nextModel);
    void persistSelection(provider, nextModel);
  };

  const persistApiKey = async () => {
    if (!apiKey.trim()) {
      return;
    }
    const saved = await saveConfig({ provider, model, api_key: apiKey });
    setApiKey("");
    onSaved(saved);
    onApiKeySaved?.();
  };

  return (
    <PanelSection title="配置">
      <PanelSectionRow>
        <div
          style={{
            background: colors.panel,
            border: `1px solid ${colors.border}`,
            borderRadius: 10,
            boxSizing: "border-box",
            display: "flex",
            flexDirection: "column",
            gap: 8,
            padding: 10,
            width: "100%",
          }}
        >
          <select
            disabled={busy}
            onChange={(event) => updateProvider(event.currentTarget.value)}
            style={{
              background: "rgba(0, 0, 0, 0.22)",
              border: `1px solid ${colors.border}`,
              borderRadius: 8,
              color: colors.text,
              minHeight: 36,
              padding: "7px 9px",
            }}
            value={provider}
          >
            <option value="openai">OpenAI</option>
            <option value="openai-chat">OpenAI Chat</option>
            <option value="anthropic">Anthropic (Claude)</option>
            <option value="deepseek">DeepSeek</option>
            <option value="moonshot">Moonshot 国内</option>
            <option value="moonshot-global">Moonshot 国际</option>
            <option value="qwen">Qwen</option>
          </select>
          <select
            disabled={busy}
            onChange={(event) => updateModel(event.currentTarget.value)}
            style={{
              background: "rgba(0, 0, 0, 0.22)",
              border: `1px solid ${colors.border}`,
              borderRadius: 8,
              boxSizing: "border-box",
              color: colors.text,
              minHeight: 36,
              padding: "7px 9px",
              width: "100%",
            }}
            value={model}
          >
            {modelOptions.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
          <input
            disabled={busy}
            onChange={(event) => setApiKey(event.currentTarget.value)}
            placeholder={config?.has_api_key ? "API key 已保存，留空不修改" : "输入 API key"}
            style={{
              background: "rgba(0, 0, 0, 0.22)",
              border: `1px solid ${config?.has_api_key ? colors.border : colors.warn}`,
              borderRadius: 8,
              boxSizing: "border-box",
              color: colors.text,
              minHeight: 36,
              padding: "7px 9px",
              width: "100%",
            }}
            type="password"
            value={apiKey}
          />
          <ButtonItem
            disabled={busy || !apiKey.trim()}
            layout="below"
            onClick={() => void persistApiKey()}
          >
            保存 API Key
          </ButtonItem>
        </div>
      </PanelSectionRow>
    </PanelSection>
  );
}

function Content() {
  const [status, setStatus] = useState<RuntimeStatus | null>(null);
  const [config, setConfig] = useState<RuntimeConfig | null>(null);
  const [busy, setBusy] = useState(false);
  const [draft, setDraft] = useState("");
  const [activeTurnId, setActiveTurnId] = useState<string | null>(null);
  const [permissionRequest, setPermissionRequest] = useState<PermissionRequest | null>(null);
  const seenEventCountRef = useRef(0);
  const [pollVersion, setPollVersion] = useState(0);
  const [messages, setMessages] = useState<Message[]>(() => loadHistory());
  const [configOpen, setConfigOpen] = useState(false);
  const messagesEndRef = useRef<HTMLDivElement | null>(null);

  const appendMessage = (role: Message["role"], text: string) => {
    setMessages((current) => [...current, { id: nextId(), role, text }]);
  };

  // 新消息后自动滚到底 + 持久化到 localStorage
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
    saveHistory(messages);
  }, [messages]);

  const refresh = async (): Promise<RuntimeStatus | null> => {
    try {
      const [latestStatus, latestConfig] = await Promise.all([
        getStatus(),
        getConfig(),
      ]);
      setStatus(latestStatus);
      setConfig(latestConfig);
      setMessages((current) =>
        current.length > 0
          ? current
          : [
              {
                id: 1,
                role: "assistant",
                text: welcomeMessageForStatus(latestStatus),
              },
            ],
      );
      return latestStatus;
    } catch (error) {
      const body = String(error);
      appendMessage("system", body);
      toaster.toast({ title: "DeckMind 状态读取失败", body });
      return null;
    }
  };

  useEffect(() => {
    void refresh();
  }, []);

  useEffect(() => {
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

        if (state.events.length > seenEventCountRef.current) {
          const newEvents = state.events.slice(seenEventCountRef.current);
          seenEventCountRef.current = state.events.length;

          // 后端 tool 返回的 frontend_action：用 SteamClient 在前端执行
          // （启动/关闭游戏走 Steam 内部调用，无确认弹窗）。
          for (const event of newEvents) {
            const action = event.result?.frontend_action;
            if (event.type === "tool_result" && action) {
              appendMessage("system", runFrontendAction(action));
            }
          }

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
      } catch (error) {
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
  }, [activeTurnId, pollVersion]);

  const runInstall = async (isUpdate = false) => {
    setBusy(true);
    let cursor = 0;
    let pollTimer: number | undefined;

    const drain = async (): Promise<void> => {
      try {
        const progress = await getInstallProgress(cursor);
        if (progress.events.length > 0) {
          cursor = progress.total;
          for (const ev of progress.events) {
            appendMessage("system", formatInstallEvent(ev));
          }
        }
      } catch {
        // RPC error during polling is non-fatal; the final result still
        // comes back via installRuntime().
      }
    };

    try {
      appendMessage(
        "system",
        isUpdate ? "▶ 正在更新 Runtime（git pull）..." : "▶ 开始下载并安装 Runtime...",
      );
      // Reset the backend cursor by reading total once before kicking off.
      try {
        const seed = await getInstallProgress(0);
        cursor = seed.total;
      } catch {
        /* first call may race with reset; safe to ignore */
      }
      pollTimer = window.setInterval(() => {
        void drain();
      }, 500);

      const result = await installRuntime();
      // Flush any events emitted between the last poll and finish.
      await drain();

      const latest = await refresh();
      if (result.ok) {
        const commit = latest?.commit ?? null;
        const deps = result.deps;
        const depsFailed = deps && deps.ok === false;
        appendMessage(
          depsFailed ? "system" : "assistant",
          depsFailed
            ? `Runtime 代码已更新${commit ? ` 到 ${commit}` : ""}，但依赖安装失败：${deps.error ?? "未知错误"}`
            : isUpdate
              ? `Runtime 已更新${commit ? ` 到 ${commit}` : ""}`
              : `Runtime 已安装到 ${result.runtime_dir ?? "本机目录"}`,
        );
        // 插件本体同步结果
        const plugin = result.plugin;
        if (plugin?.ok && plugin.files) {
          appendMessage(
            "system",
            `🔌 插件本体已同步（${plugin.files} 个文件）。${plugin.note ?? "请在 Decky 重载插件或重启 Steam 生效。"}`,
          );
        } else if (plugin && !plugin.ok) {
          appendMessage("system", `⚠ 插件同步失败：${plugin.error ?? plugin.skipped ?? "未知"}`);
        }
      } else {
        appendMessage("system", `✗ ${result.error ?? "Runtime 操作失败"}`);
      }
    } catch (error) {
      const body = String(error);
      appendMessage("system", `✗ ${body}`);
      toaster.toast({ title: "DeckMind 安装失败", body });
    } finally {
      if (pollTimer !== undefined) {
        window.clearInterval(pollTimer);
      }
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
      seenEventCountRef.current = 0;
      setPermissionRequest(null);
      const result = await startTurn(text);
      if (result.ok && result.turn_id) {
        setActiveTurnId(result.turn_id);
      } else if (result.error === "missing_api_key" && result.missing_api_key) {
        setBusy(false);
        appendMessage("system", `缺少 ${result.missing_api_key}，请保存 API key`);
      } else {
        setBusy(false);
        appendMessage("system", result.error ?? "Runtime 暂不可用");
      }
    } catch (error) {
      setBusy(false);
      appendMessage("system", String(error));
    }
  };

  const respondToPermission = async (decision: "allow" | "deny" | "allow_all") => {
    if (!activeTurnId || !permissionRequest) {
      return;
    }
    setBusy(true);
    const result = await answerPermission(
      activeTurnId,
      permissionRequest.request_id,
      decision,
    );
    if (result.ok) {
      appendMessage("system", `权限响应：${decision}`);
      setPermissionRequest(null);
      setPollVersion((value) => value + 1);
    } else {
      appendMessage("system", result.error ?? "权限响应失败");
      setBusy(false);
    }
  };

  const clearHistory = async () => {
    const currentMessages = messages;
    setMessages(
      status
        ? [{ id: nextId(), role: "assistant", text: welcomeMessageForStatus(status) }]
        : [],
    );
    setPermissionRequest(null);
    setActiveTurnId(null);
    seenEventCountRef.current = 0;
    try {
      const result = await resetSession(currentMessages);
      if (result.remembered && result.remembered.length > 0) {
        appendMessage(
          "system",
          `已开启新对话，并更新 ${result.remembered.length} 条长期偏好记忆。`,
        );
      }
    } catch (error) {
      appendMessage("system", `新对话已清空界面历史，但后端重置失败：${String(error)}`);
    }
  };

  const canSend = useMemo(
    () => Boolean(status?.installed) && draft.trim().length > 0 && !busy,
    [busy, draft, status?.installed],
  );

  // 未安装时强制显示（引导安装）；已安装时跟随配置面板展开，方便点"更新 Runtime"
  const shouldShowRuntimeCard = status?.installed === false || configOpen;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
      <div
        style={{
          position: "sticky",
          top: 0,
          zIndex: 20,
          background: "rgb(13, 17, 23)",
          display: "flex",
          alignItems: "stretch",
          gap: 6,
        }}
      >
        <div
          role="button"
          tabIndex={0}
          onClick={() => void clearHistory()}
          title="开启新对话"
          aria-label="开启新对话"
          style={{
            alignItems: "center",
            background: "rgba(255, 123, 114, 0.09)",
            border: "1px solid rgba(255, 123, 114, 0.25)",
            borderRadius: 8,
            color: colors.danger,
            cursor: "pointer",
            display: "inline-flex",
            fontSize: 11,
            fontWeight: 600,
            gap: 4,
            padding: "0 10px",
          }}
        >
          <FaTrash size={11} />
          新对话
        </div>
        <div style={{ flex: 1 }}>
          <StatusBar
            busy={busy}
            config={config}
            configOpen={configOpen}
            onRefresh={() => void refresh()}
            onToggleConfig={() => setConfigOpen((open) => !open)}
            status={status}
          />
        </div>
      </div>

      {shouldShowRuntimeCard && (
        <RuntimeCard
          busy={busy}
          onInstall={() => void runInstall(false)}
          onUpdate={() => void runInstall(true)}
          onRefresh={() => void refresh()}
          status={status}
        />
      )}

      {(!config?.has_api_key || configOpen) && (
        <ConfigCard
          busy={busy}
          config={config}
          onSaved={(saved) => {
            setConfig(saved);
            appendMessage("system", "配置已保存");
          }}
          onApiKeySaved={() => setConfigOpen(false)}
        />
      )}

      {permissionRequest && (
        <PanelSection title="需要确认">
          <PanelSectionRow>
            <div
              style={{
                background: "rgba(20, 23, 28, 0.94)",
                border: `1px solid rgba(246, 193, 119, 0.28)`,
                borderRadius: 10,
                color: colors.text,
                display: "flex",
                flexDirection: "column",
                overflow: "hidden",
              }}
            >
              <div style={{ display: "flex", flexDirection: "column", gap: 6, padding: 12 }}>
                <div style={{ fontWeight: 700 }}>{permissionRequest.name}</div>
                <div style={{ color: colors.muted, fontSize: 12, wordBreak: "break-word" }}>
                  {permissionRequest.message}
                </div>
                <div style={{ color: "rgba(232, 238, 246, 0.32)", fontSize: 11, wordBreak: "break-word" }}>
                  {JSON.stringify(permissionRequest.arguments)}
                </div>
              </div>
              <div
                style={{
                  borderTop: "1px solid rgba(246, 193, 119, 0.19)",
                  display: "flex",
                  gap: 6,
                  padding: 8,
                }}
              >
                <button
                  disabled={busy}
                  onClick={() => void respondToPermission("allow")}
                  style={{
                    background: "rgba(102, 217, 168, 0.15)",
                    border: "1px solid rgba(102, 217, 168, 0.31)",
                    borderRadius: 6,
                    color: colors.accent,
                    cursor: "pointer",
                    flex: 1,
                    fontSize: 13,
                    fontWeight: 600,
                    padding: "7px 0",
                  }}
                >
                  允许
                </button>
                <button
                  disabled={busy}
                  onClick={() => void respondToPermission("allow_all")}
                  style={{
                    background: "rgba(255, 255, 255, 0.06)",
                    border: "1px solid rgba(255, 255, 255, 0.12)",
                    borderRadius: 6,
                    color: "rgba(246, 248, 252, 0.82)",
                    cursor: "pointer",
                    flex: 1,
                    fontSize: 13,
                    padding: "7px 0",
                  }}
                >
                  本次
                </button>
                <button
                  disabled={busy}
                  onClick={() => void respondToPermission("deny")}
                  style={{
                    background: "rgba(255, 123, 114, 0.09)",
                    border: "1px solid rgba(255, 123, 114, 0.25)",
                    borderRadius: 6,
                    color: colors.danger,
                    cursor: "pointer",
                    flex: 1,
                    fontSize: 13,
                    fontWeight: 600,
                    padding: "7px 0",
                  }}
                >
                  拒绝
                </button>
              </div>
            </div>
          </PanelSectionRow>
        </PanelSection>
      )}

      <PanelSection title="对话">
        <PanelSectionRow>
          <div
            style={{
              display: "flex",
              flexDirection: "column",
              gap: 8,
              maxHeight: 320,
              minHeight: 160,
              overflowY: "auto",
              paddingRight: 2,
            }}
          >
            {messages.map((message) => (
              <div
                key={message.id}
                style={{ ...messageStyle(message.role), position: "relative" }}
              >
                <div
                  role="button"
                  tabIndex={0}
                  onClick={() => void copyToClipboard(message.text)}
                  title="复制这条消息"
                  style={{
                    position: "absolute",
                    top: 4,
                    right: 4,
                    display: "flex",
                    alignItems: "center",
                    gap: 4,
                    padding: "2px 6px",
                    borderRadius: 6,
                    cursor: "pointer",
                    background: "rgba(0, 0, 0, 0.28)",
                    color: colors.muted,
                    fontSize: 11,
                  }}
                >
                  <FaCopy size={10} />
                  复制
                </div>
                <div style={{ paddingRight: 52 }}>{message.text}</div>
              </div>
            ))}
            <div ref={messagesEndRef} />
          </div>
        </PanelSectionRow>
      </PanelSection>

      <PanelSection>
        <PanelSectionRow>
          <div style={{ display: "flex", flexDirection: "column", gap: 8, width: "100%" }}>
            <input
              disabled={!status?.installed || busy}
              onChange={(event) => setDraft(event.currentTarget.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter") {
                  void send();
                }
              }}
              placeholder={status?.installed ? "输入指令..." : "先安装 Runtime"}
              style={{
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
              }}
              type="text"
              value={draft}
            />
            <ButtonItem disabled={!canSend} layout="below" onClick={() => void send()}>
              <span style={{ alignItems: "center", display: "inline-flex", gap: 8 }}>
                <FaPaperPlane />
                发送
              </span>
            </ButtonItem>
          </div>
        </PanelSectionRow>
      </PanelSection>
    </div>
  );
}

export default definePlugin(() => ({
  name: "DeckMind",
  titleView: (
    <div className={staticClasses.Title} style={{ alignItems: "center", display: "flex", gap: 8 }}>
      <FaBrain />
      <span>DeckMind</span>
    </div>
  ),
  content: <Content />,
  icon: <FaTerminal />,
}));
