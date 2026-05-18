# steamdeck-agent

> [English README](README.md)

一个极简、不依赖任何 Agent 框架的 **LLM Agent 运行时**，面向 Linux / Steam Deck。
整个 Runtime Loop 只有几十行，全部集中在 [`runtime/agent.py`](runtime/agent.py)，
目标是**让你能在一杯咖啡的时间内读懂一个 Agent 到底是怎么工作的**。

## 架构

```
            ┌─────────────────────────────────────────────┐
            │                  Agent.handle()             │
            │                                             │
  用户 ──▶  │  Planner ──function_call──▶ Executor ──▶ tool │
            │     ▲                            │           │
            │     └──function_call_output──────┘           │
            │            (循环直到 final_answer)            │
            └─────────────────────────────────────────────┘
```

- **Planner**（[`runtime/planner.py`](runtime/planner.py)）—— 向 LLM 发一次请求，
  拿到模型想调用的下一个工具。
- **Executor**（[`runtime/executor.py`](runtime/executor.py)）—— 在工具注册表里
  找到对应实现并执行。
- **Agent**（[`runtime/agent.py`](runtime/agent.py)）—— 把上面两者串起来：
  把工具结果喂回 LLM，直到模型调用 `final_answer` 或达到 `MAX_STEPS` 上限。
- **Tools**（[`tools/*.py`](tools/)）—— 真正干活的代码（Steam、系统、宏）。
  添加新工具 = 在 [`tools/__init__.py`](tools/__init__.py) 里加一条注册。
- **Memory**（[`memory/session.py`](memory/session.py)）—— 滚动窗口式的最近对话记录。

更详细的可视化架构图见 [docs/architecture.html](docs/architecture.html)（用浏览器打开）。

## 通用安装（任何 Linux / macOS 开发机）

依赖：Python 3.11+ 和 [uv](https://docs.astral.sh/uv/)。

```bash
git clone https://github.com/Hurtblack/DeckMind.git
cd DeckMind
uv sync                                # 自动建虚拟环境并装依赖
# 或者：uv pip install -r requirements.txt
```

## 在 Steam Deck 上安装

> ⚠️ 在**桌面模式**（KDE）下安装；跑通之后再用"非 Steam 游戏"的方式加进库，
> 这样在游戏模式也能启动。

### 1. 切到桌面模式

按电源键 → **Switch to Desktop**。

### 2. 设置 sudo 密码（首次必须）

打开 **Konsole**（应用菜单 → System → Konsole），运行：

```bash
passwd
```

SteamOS 出厂没有 sudo 密码，必须先自己设一个，否则后面装东西会失败。

### 3. 安装 uv

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
source $HOME/.cargo/env
```

uv 装在 `~/.local/bin`，SteamOS 大版本更新清空 `/usr` 时不会丢。如果哪天发现
uv 不见了，重新跑这条命令即可。

### 4. 把项目拷到 Deck 上

二选一：

```bash
# A. 从 GitHub 克隆
cd ~ && git clone https://github.com/Hurtblack/DeckMind.git

# B. 从另一台电脑用 scp 传（这条命令在你的电脑上跑，不是在 Deck 上）
scp -r DeckMind deck@<Deck-的-IP>:/home/deck/
```

### 5. 安装依赖

```bash
cd ~/DeckMind
uv sync
```

### 6. 配置 API Key（持久化）

把 key 写进 `~/.bashrc`，以后开终端自动加载：

```bash
echo 'export LLM_PROVIDER=deepseek'   >> ~/.bashrc
echo 'export DEEPSEEK_API_KEY=sk-...' >> ~/.bashrc
source ~/.bashrc
```

（用其他厂商就改对应的 env，见下面"选择 LLM 服务商"那一节。）

### 7. 跑起来

```bash
cd ~/DeckMind
uv run python main.py
```

试几条：

```
you> 查看当前电量
you> 把音量调到 30%
you> 打开 CS2
```

### 8. 添加为"非 Steam 游戏"，从游戏模式启动

游戏模式没有终端 UI，但可以把 Agent 包成一个启动脚本、加进 Steam 库，
之后它就和普通游戏一样能从游戏模式启动栏点开。

**8.1 写启动脚本**

```bash
cat > ~/DeckMind/run-agent.sh <<'EOF'
#!/bin/bash
# SteamDeckAgent 启动器 —— 开一个 Konsole 窗口运行 REPL
cd "$(dirname "$0")"

# 加载 ~/.bashrc 中的 API key，让子进程能看到这些环境变量
source "$HOME/.bashrc"

# --hold 让窗口在 agent 退出后保留，方便看错误信息
konsole --hold -e bash -c "uv run python main.py"
EOF

chmod +x ~/DeckMind/run-agent.sh
```

**8.2 加进 Steam**

1. 打开 Steam 客户端（桌面模式）
2. 左下角：**添加游戏 → 添加非 Steam 游戏...**
3. 点**浏览**，进入 `/home/deck/DeckMind/`，把文件类型筛选改为
   *所有文件*，选 `run-agent.sh`
4. 确认后会出现一个名叫 `run-agent.sh` 的库项 —— 右键 → 属性，
   重命名成 `SteamDeckAgent`

**8.3 使用**

- **桌面模式**：双击库项 → 弹出 Konsole 跑 REPL
- **游戏模式**：像启动游戏一样启动它 → SteamOS 会切到一个桌面浮层运行
  Konsole。用屏幕键盘（`STEAM + X`）或者外接蓝牙键盘输入

> 屏幕键盘打字非常慢。如果你打算在游戏模式高频使用，强烈建议配一个小蓝牙键盘。

### Steam Deck 已知的两个限制

- **宏（`press_key`、`start_key_loop`）** 当前后端是 `pynput`，只支持 X11。
  SteamOS 桌面模式是 KDE on Wayland，游戏模式是 Gamescope（也算 Wayland），
  按键注入会静默失效（API 返回 `ok: true` 但游戏里没反应）。
  解决办法是换成 `ydotool` —— 这个改动很小，集中在
  [tools/macro_tool.py](tools/macro_tool.py) 一个文件，需要的话提个 issue。
- **启动游戏** 要求 Steam 客户端已经在跑。游戏模式下它一直在跑；桌面模式记得
  先打开 Steam。
- **电池设备** Deck 上是 `BAT1`（不是 `BAT0`），代码会自动识别两种。

## 选择 LLM 服务商

通过环境变量 `LLM_PROVIDER` 选后端，每家用各自的 API key：

| 服务商 | `LLM_PROVIDER` | API Key 环境变量 | 默认模型 |
|---|---|---|---|
| OpenAI（Responses API） | `openai`（默认） | `OPENAI_API_KEY` | `gpt-4o-mini` |
| OpenAI（Chat Completions） | `openai-chat` | `OPENAI_API_KEY` | `gpt-4o-mini` |
| **DeepSeek** | `deepseek` | `DEEPSEEK_API_KEY` | `deepseek-chat` |
| Moonshot (Kimi) | `moonshot` | `MOONSHOT_API_KEY` | `moonshot-v1-8k` |
| 通义千问 (Qwen) | `qwen` | `DASHSCOPE_API_KEY` | `qwen-plus` |

要换模型可以用 `LLM_MODEL=...` 覆盖默认值。

```bash
# 例子：OpenAI（默认）
export OPENAI_API_KEY=sk-...

# 例子：DeepSeek
export LLM_PROVIDER=deepseek
export DEEPSEEK_API_KEY=sk-...
# export LLM_MODEL=deepseek-reasoner   # 可选

# 例子：Kimi
export LLM_PROVIDER=moonshot
export MOONSHOT_API_KEY=sk-...
```

要加新的 OpenAI 兼容服务商，只需要往 [llm/__init__.py](llm/__init__.py) 的
`PROVIDERS` 表里加一行，Agent 本身不用动。

## 运行

```bash
uv run python main.py
```

## 内置工具

| 分组 | 工具 | 破坏性？ |
|---|---|---|
| Steam | `launch_game`、`close_game`、`list_running_games` | 否 |
| Steam | `install_game`、`uninstall_game` | **是（两步确认）** |
| 包管理 | `list_flatpak_apps`、`search_flatpak`、`disk_usage` | 否 |
| 包管理 | `install_flatpak`、`uninstall_flatpak` | **是（两步确认）** |
| 系统 | `get_battery`、`get_volume`、`set_volume` | 否 |
| 宏 | `press_key`、`start_key_loop`、`stop_all_macros` | 否 |
| Meta | `final_answer` | — |

### Runtime 权限闸门（代码层强制）

[`runtime/executor.py`](runtime/executor.py) 在每次调用工具**之前**做权限检查 ——
这是**代码层面**的限制，跟 system prompt 的约束相互独立，比它更硬。三档：

| 风险等级 | 行为 | 工具 |
|---|---|---|
| `safe`（安全） | 静默放行 | get_*、list_*、search_*、disk_usage、final_answer |
| `side_effect`（副作用） | 弹 `[y=允许 / n=拒绝 / a=本工具本会话全允许]` | set_volume、press_key、start_key_loop、stop_all_macros、launch_game、close_game |
| `destructive`（破坏性） | 永远在执行前询问用户。如果 LLM 跳过了推荐的 `confirm=false` dry-run 直接 confirm=true，会弹**加强版警告**告诉你预览被跳过了 | install_*、uninstall_* |

闸门**从不静默拒绝** —— 每个有风险的调用都会问你，最终决定权永远在你手里。

工具内的额外加固：

- **`close_game`** 如果 `process_name` 长度不到 3 个字符（会匹配太多进程），
  或包含黑名单子串（`steam`、`systemd`、`kwin`、`plasma`、`sshd`、`python` 等），
  会**额外弹一个警告询问** —— 你仍然可以同意继续，这只是警告不是拦截。

## 示例对话

```
you> 查看当前电量
  ▸ tool: get_battery({})
    ↳ {'ok': True, 'device': 'BAT1', 'percent': 78, 'status': 'Discharging'}
  ▸ tool: final_answer({'message': '当前电量 78%，正在放电。'})
bot> 当前电量 78%，正在放电。

you> 把音量调到 50%
  ▸ tool: set_volume({'percent': 50})
    ↳ {'ok': True, 'percent': 50, 'backend': 'wpctl'}
  ▸ tool: final_answer({'message': '已将音量调到 50%。'})
bot> 已将音量调到 50%。

you> 每隔 5 秒按一次空格键
  ▸ tool: start_key_loop({'key': 'space', 'interval_seconds': 5})
    ↳ {'ok': True, 'loop_id': 1, 'key': 'space', 'interval_seconds': 5, ...}
bot> 已启动后台宏：每 5 秒按一次空格。说"停止宏"即可取消。

you> 打开 CS2
  ▸ tool: launch_game({'game_name': 'cs2'})
    ↳ {'ok': True, 'game': 'cs2', 'app_id': '730', 'pid': 12345}
bot> 正在启动 CS2。

you> 帮我卸载 Dolphin 模拟器
  ▸ tool: list_flatpak_apps({})
    ↳ {'ok': True, 'count': 23, 'apps': [...,
         {'app_id': 'org.DolphinEmu.dolphin-emu', 'name': 'Dolphin', 'size': '412 MB'}]}
  ▸ tool: uninstall_flatpak({'app_id': 'org.DolphinEmu.dolphin-emu', 'confirm': False})
    ↳ {'ok': True, 'dry_run': True, 'size': '412 MB',
       'message': 'Will uninstall ... Ask the user to confirm...'}
  ▸ tool: final_answer({'message': '找到了 Dolphin (412 MB)。确认卸载吗？'})
bot> 找到了 Dolphin (412 MB)。确认卸载吗？

you> 确认
  ▸ tool: uninstall_flatpak({'app_id': 'org.DolphinEmu.dolphin-emu', 'confirm': True})
    ↳ {'ok': True, 'uninstalled': 'org.DolphinEmu.dolphin-emu', ...}
  ▸ tool: final_answer({'message': '已卸载 Dolphin，释放约 412 MB。'})
bot> 已卸载 Dolphin，释放约 412 MB。
```

## 一些说明与限制

- **启动 Steam 游戏** 优先使用 `steam://rungameid/<id>` URI；如果系统找不到
  `steam` 命令则返回 mock 结果，方便在 macOS / 普通开发机上调试 Loop 流程。
- **音量** 优先用 `wpctl`（PipeWire，SteamOS 3 默认），找不到时回退 `amixer`。
- **电池** 直接读 `/sys/class/power_supply/*/capacity`。
- **宏** 用 `pynput`。在无显示器或缺少输入权限的机器上会自动降级成只打日志的 mock。

## 添加一个新工具

1. 在 `tools/` 下任意位置写 `async def my_tool(...) -> dict`
2. 在 [`tools/__init__.py`](tools/__init__.py) 的 `TOOLS` 字典里加一条
   注册（包含 JSON Schema 参数描述）

加完之后，下次 LLM 调用 Planner 时就会自动看到这个工具，不用动 Agent 代码。
