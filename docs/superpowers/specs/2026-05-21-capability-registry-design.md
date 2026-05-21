# Capability Registry 与蓝牙验证设计

## 背景

DeckMind 目前已经有一批直接注册给 LLM 的工具：Steam 游戏启动/关闭、系统音量、文件读写、Flatpak/pacman、受限命令执行等。
这些工具能解决具体问题，但随着 Steam Deck 系统能力继续扩展，会出现两个问题：

1. Agent 对“能做什么”的理解来自零散工具描述，缺少统一的能力目录。
2. 权限确认按工具名粗粒度处理，难以表达“同一个入口下不同能力有不同风险”。

用户期望的长期形态是：Agent 不直接拿 shell，也不靠临时命令拼装系统操作，而是调用受控能力。
这些能力可以被 Decky 插件 UI、Agent runtime 和未来的 skill / capability pack 复用。

本设计先做第一版骨架：引入 Capability Registry，并用一个真实蓝牙能力验证链路。

## 目标

第一版目标是建立一个最小但可扩展的能力层：

1. 新增 Capability Registry，统一描述能力名称、说明、参数、风险等级、确认策略和 handler。
2. 新增 Agent 工具入口 `list_capabilities` 和 `run_capability`。
3. 用 `bluetoothctl` 实现最小蓝牙能力，验证 Agent → Registry → Handler → Result 的完整链路。
4. 保持现有工具可用，不做大规模迁移。
5. 为后续 Skill Creation Loop / Capability Pack 留出数据结构和边界。

第一版不是完整系统控制平台。它只证明“能力注册、能力发现、能力执行、能力风险声明”这条路可行。

## 非目标

- 不实现 BlueZ DBus。
- 不实现蓝牙配对 `pair_bluetooth`。
- 不实现 TDP、GPU clock、CPU Boost、WiFi 或 systemd service 管理。
- 不实现 capability pack 安装、发布、签名或 marketplace。
- 不允许 Agent 自动生成 Python handler 并立即执行。
- 不把未知 capability 降级成 shell 或 `run_command`。
- 不移除或重写现有 `tools/*.py` 工具体系。

## 核心概念

### Capability

Capability 是一个可执行动作或查询。每个 capability 必须声明：

- `name`：稳定唯一名，例如 `bluetooth.get_devices`。
- `description`：给 Agent 和 UI 看的能力说明。
- `args_schema`：参数 schema，第一版沿用 `ToolSpec.parameters` 风格的 JSON Schema 子集。
- `risk`：`safe`、`side_effect` 或 `destructive`。
- `confirm_required`：是否需要用户确认。
- `handler`：实际执行函数。

第一版只支持内置 Python handler，不从外部目录动态加载 handler。

### Skill

Skill 是给 Agent 看的工作流知识，不等同于 capability。
Skill 可以教 Agent “遇到代理诊断问题时先查进程、再查端口、再查 Clash/Mihomo 控制接口”，但它不直接代表系统权限。

后续可以把一次成功对话沉淀成 `SKILL.md`，让 Agent 下次规划更完整。
真正执行系统动作时，仍然必须调用已注册 capability。

### Capability Pack

Capability Pack 是未来概念：一组 capability、说明文档、权限声明和可选 handler 的组合。
第一版只在设计中预留，不做安装或分享。

## 第一版能力范围

新增蓝牙能力：

| Capability | 风险 | 确认 | 说明 |
|---|---|---|---|
| `bluetooth.get_devices` | `safe` | 否 | 列出已知蓝牙设备及连接状态 |
| `bluetooth.connect` | `side_effect` | 是 | 连接指定蓝牙设备 |
| `bluetooth.disconnect` | `side_effect` | 是 | 断开指定蓝牙设备 |

暂不做 `bluetooth.pair`。配对涉及 PIN/passkey/agent 交互，用它验证第一版会把能力层设计和 BlueZ 交互复杂度绑在一起。

## 架构

新增一层 `runtime.capabilities`：

```text
用户请求
  ↓
Agent 选择 list_capabilities / run_capability
  ↓
tools.capability_tool
  ↓
runtime.capabilities.registry
  ↓
runtime.capabilities.bluetooth
  ↓
bluetoothctl
```

文件职责：

```text
runtime/capabilities/types.py
  定义 Capability、CapabilityResult、CapabilityRisk 等基础类型。

runtime/capabilities/registry.py
  管理内置 capability 注册、查找和列表输出。

runtime/capabilities/bluetooth.py
  蓝牙 capability handler 和 bluetoothctl 输出解析。

tools/capability_tool.py
  暴露给 Agent 的 list_capabilities / run_capability 工具。
```

第一版 registry 在进程启动时注册内置蓝牙能力。后续接入音量、游戏、TDP 时继续走同一注册接口。

## 权限与风险

现有 Executor 的风险模型保持不变：

- `safe`：直接执行。
- `side_effect`：询问用户，支持本会话允许同类操作。
- `destructive`：dry-run / confirm 双阶段。

`list_capabilities` 是 `safe`。

`run_capability` 本身不能用一个固定风险覆盖所有能力，因为不同 capability 风险不同。
第一版采用工具内部校验策略：

1. `run_capability` 先查 registry。
2. 如果 capability 不存在，返回 `unknown_capability`，不执行 fallback。
3. 如果 capability 是 `safe`，直接调用 handler。
4. 如果 capability 是 `side_effect` 且 `confirm=false`，返回 dry-run 预览。
5. 如果 capability 是 `side_effect` 且 `confirm=true`，由 Executor 对 `run_capability` 做用户确认，然后 handler 执行。

为了让 Executor 能正确拦截 `confirm=true` 的 `run_capability`，第一版把 `run_capability` 注册为 `destructive` 风险工具，但 `confirm=false` 只做预览。
这会比理想的能力级权限略粗，但与现有确认体系兼容，避免在第一版重写 Executor。

后续可以把 Executor 扩展为“按 capability metadata 动态决策风险”，让 `bluetooth.get_devices` 这类 `run_capability` 调用也能完全无确认。
第一版可通过单独的 `list_capabilities` 和 handler 内 dry-run 减少误确认。

## 蓝牙实现

第一版使用 `bluetoothctl`，不使用 shell：

```text
bluetoothctl devices
bluetoothctl info <MAC>
bluetoothctl connect <MAC>
bluetoothctl disconnect <MAC>
```

设备列表实现：

1. 调用 `bluetoothctl devices` 获取 MAC 和名称。
2. 对每个 MAC 调用 `bluetoothctl info <MAC>`。
3. 解析 `Paired`、`Trusted`、`Connected` 字段。
4. 返回结构化结果。

返回示例：

```json
{
  "ok": true,
  "devices": [
    {
      "address": "AA:BB:CC:DD:EE:FF",
      "name": "Xbox Wireless Controller",
      "paired": true,
      "trusted": true,
      "connected": false
    }
  ]
}
```

连接和断开实现：

1. 校验 MAC 地址格式。
2. `confirm=false` 时返回 dry-run：

```json
{
  "ok": true,
  "dry_run": true,
  "capability": "bluetooth.connect",
  "target": {
    "address": "AA:BB:CC:DD:EE:FF"
  }
}
```

3. `confirm=true` 时执行 `bluetoothctl connect <MAC>` 或 `disconnect <MAC>`。
4. 执行后读取 `bluetoothctl info <MAC>` 验证 `Connected` 状态。

## 未知 Capability

未知 capability 是新需求入口，不是执行入口。

`run_capability` 对未知能力只返回：

```json
{
  "ok": false,
  "error": "unknown_capability",
  "capability": "wifi.switch_network",
  "suggestions": ["list_capabilities"]
}
```

Agent 可以基于这个结果告诉用户“当前还没有这个能力”，并建议进入设计流程。
它不得自动降级调用 shell，也不得临时拼命令替代缺失 capability。

## Skill Creation Loop 预留

用户希望后续能在一次问题解决后，让 Agent 把成功路径沉淀成类似 Hermes 的 skill。
本设计把这个能力放入后续阶段，不进入第一版实现。

目标形态：

```text
用户：把刚才排查代理的流程保存成 skill
  ↓
Agent 总结成功路径
  ↓
生成 ~/.deckmind/skills/proxy-diagnostics/SKILL.md
  ↓
下次类似问题自动加载该 skill
```

约束：

- 自动生成的 skill 只包含 Markdown 工作流、检查顺序、安全规则和可复用提示。
- 自动生成的 composite skill 只能编排已有 capability。
- 不允许自动生成 primitive Python handler 并立即启用。
- 新 primitive capability 仍然需要开发流程、代码审查和测试。

代理诊断类 skill 可以让 Agent 思考更全，例如固定检查代理进程、常见端口、Clash/Mihomo API、系统代理设置和节点状态。
但真正切换节点、改配置、重启服务时，仍要调用受控 capability。

## Prompt 更新

系统提示词需要新增：

- 优先使用 `list_capabilities` 了解可用能力。
- 执行系统动作优先使用 `run_capability`，而不是临时 shell。
- 遇到未知 capability 时，向用户说明当前能力缺口，不要自动降级成命令执行。
- Skill 是工作流知识，Capability 是可执行动作；不能把 skill 当权限入口。

## 测试

第一版测试聚焦在不依赖真实蓝牙硬件的部分：

1. Registry 能列出内置蓝牙 capability。
2. Registry 对未知 capability 返回明确错误。
3. `bluetoothctl devices` 输出解析正确。
4. `bluetoothctl info` 输出解析正确。
5. 蓝牙 MAC 地址校验拒绝非法输入。
6. `bluetooth.connect` / `bluetooth.disconnect` 的 dry-run 不调用 subprocess。
7. `run_capability` 对 side-effect capability 在 `confirm=false` 时返回预览。

真实 Steam Deck 上的手动验证：

1. 列出已配对蓝牙设备。
2. 连接一个已配对设备。
3. 断开该设备。
4. 验证 Decky UI 能显示 permission request 并继续 turn。

## 未来扩展

后续按风险从低到高扩展：

1. 把现有 `get_volume`、`set_volume`、`launch_game`、`close_game` 逐步注册为 capability。
2. 增加 `audio.*` capability，支持默认输出设备和应用音量。
3. 增加 `skill_create_from_session`，把对话成功路径保存为 `SKILL.md`。
4. 增加本地 user capability pack 发现机制，但默认禁用。
5. 增加 BlueZ DBus 实现，替代 `bluetoothctl` 解析。
6. 增加 TDP/GPU/CPU/WiFi 能力，并使用更严格的风险分级。

