# steamdeck-agent

> [中文 README](README.zh-CN.md)

A minimal, framework-free LLM **agent runtime** for Linux / Steam Deck.
Built to be small enough to read in one sitting — the whole loop is in
[`runtime/agent.py`](runtime/agent.py).

## Architecture

```
            ┌─────────────────────────────────────────────┐
            │                  Agent.handle()             │
            │                                             │
  user ──▶  │  Planner ──function_call──▶ Executor ──▶ tool │
            │     ▲                            │           │
            │     └──function_call_output──────┘           │
            │            (loop until final_answer)         │
            └─────────────────────────────────────────────┘
```

- **Planner** (`runtime/planner.py`) — one call to OpenAI Responses API.
  Returns the next `function_call` the model wants to make.
- **Executor** (`runtime/executor.py`) — looks the tool up in the
  registry and awaits it.
- **Agent** (`runtime/agent.py`) — the runtime loop that wires them
  together, feeds tool results back, and stops on `final_answer` or
  after `MAX_STEPS` iterations.
- **Tools** (`tools/*.py`) — actual side-effecting code (Steam, system,
  macros). Add one by registering it in `tools/__init__.py`.
- **Memory** (`memory/session.py`) — bounded chat history.

## Install (any Linux / macOS dev machine)

Requires Python 3.11+ and [uv](https://docs.astral.sh/uv/).

```bash
git clone https://github.com/Hurtblack/DeckMind.git
cd DeckMind
uv sync                                # creates .venv, installs deps
# Or: uv pip install -r requirements.txt
```

## Install on a Steam Deck

> ⚠️ Install in **Desktop Mode** (KDE). Once it works, add it as a
> non-Steam game so you can launch it from Game Mode too.

### 1. Switch to Desktop Mode

Power button → **Switch to Desktop**.

### 2. Set a sudo password (first time only)

Open **Konsole** (Application menu → System → Konsole):

```bash
passwd
```

SteamOS ships with no sudo password — you must set one before installing
anything system-wide.

### 3. Install uv

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
source $HOME/.cargo/env
```

uv installs into `~/.local/bin`, which survives SteamOS read-only `/usr`
updates. If a major SteamOS update wipes it, rerun this command.

### 4. Get the project onto the Deck

Pick one:

```bash
# A. Clone from GitHub
cd ~ && git clone https://github.com/Hurtblack/DeckMind.git

# B. Copy from another machine via scp
#    (run this on your laptop, not the Deck)
scp -r DeckMind deck@<deck-ip>:/home/deck/
```

### 5. Install dependencies

```bash
cd ~/DeckMind
uv sync
```

### 6. Configure the API key (persistent)

```bash
echo 'export LLM_PROVIDER=deepseek'       >> ~/.bashrc
echo 'export DEEPSEEK_API_KEY=sk-...'     >> ~/.bashrc
source ~/.bashrc
```

(Use whichever provider you prefer — see the table below.)

### 7. Run

```bash
cd ~/DeckMind
uv run python main.py
```

Try:

```
you> 查看当前电量
you> 把音量调到 30%
you> 打开 CS2
```

### 8. Launch from Game Mode (add as a non-Steam game)

Game Mode has no terminal UI, but you can wrap the Agent in a launcher
script and add it to Steam as a non-Steam game. After that it shows up
in your library and you can start it from Game Mode's launcher.

**8.1 Create the launcher script**

```bash
cat > ~/DeckMind/run-agent.sh <<'EOF'
#!/bin/bash
# Launcher for SteamDeckAgent — opens a Konsole window that runs the REPL.
cd "$(dirname "$0")"

# Load API keys from ~/.bashrc so the env vars are visible to the agent.
source "$HOME/.bashrc"

# `-e` runs a command inside Konsole; the trailing `read` keeps the window
# open after the agent exits so you can see any error messages.
konsole --hold -e bash -c "uv run python main.py"
EOF

chmod +x ~/DeckMind/run-agent.sh
```

**8.2 Add it to Steam**

1. Open the Steam client (Desktop Mode).
2. Bottom-left: **Add a Game → Add a Non-Steam Game…**
3. Click **Browse**, navigate to `/home/deck/DeckMind/`, set the
   file filter to *All files*, and pick `run-agent.sh`.
4. Confirm. The entry now appears in your library as "run-agent.sh" —
   rename it to "SteamDeckAgent" (right-click → Properties).

**8.3 Use it**

- In **Desktop Mode**: double-click it in your library → a Konsole
  window opens with the REPL.
- In **Game Mode**: launch it like any game → SteamOS drops you into a
  desktop-like overlay running Konsole. Use the on-screen keyboard
  (`STEAM + X`) or a paired Bluetooth keyboard to type prompts.

> Tip: typing on the on-screen keyboard is slow. A small Bluetooth
> keyboard makes Game Mode usage actually pleasant.

### Known Steam Deck limitations

- **Macros (`press_key`, `start_key_loop`)** use `pynput`, which is X11-only.
  SteamOS uses Wayland (KDE on Wayland in Desktop Mode, Gamescope in Game
  Mode), so key injection into games will silently no-op. Workaround: swap
  the macro backend to `ydotool` (open an issue if you want this — it's a
  small change to [tools/macro_tool.py](tools/macro_tool.py)).
- **Steam launch** requires the `steam` client to be running. In Game Mode
  it always is; in Desktop Mode start Steam first.
- **Battery device** on the Deck is `BAT1` (not `BAT0`). The code
  auto-detects either.

## Configure — choose an LLM provider

Set `LLM_PROVIDER` to pick the backend. Each provider needs its own API key.

| Provider | `LLM_PROVIDER` | API-key env | Default model |
|---|---|---|---|
| OpenAI (Responses API) | `openai` *(default)* | `OPENAI_API_KEY` | `gpt-4o-mini` |
| OpenAI (Chat Completions) | `openai-chat` | `OPENAI_API_KEY` | `gpt-4o-mini` |
| **DeepSeek** | `deepseek` | `DEEPSEEK_API_KEY` | `deepseek-chat` |
| Moonshot (Kimi) | `moonshot` | `MOONSHOT_API_KEY` | `moonshot-v1-8k` |
| 通义千问 (Qwen) | `qwen` | `DASHSCOPE_API_KEY` | `qwen-plus` |

Override the model with `LLM_MODEL=...` if you don't want the default.

```bash
# Example: OpenAI (default)
export OPENAI_API_KEY=sk-...

# Example: DeepSeek
export LLM_PROVIDER=deepseek
export DEEPSEEK_API_KEY=sk-...
# export LLM_MODEL=deepseek-reasoner   # optional

# Example: Kimi
export LLM_PROVIDER=moonshot
export MOONSHOT_API_KEY=sk-...
```

Adding a new OpenAI-compatible provider = adding one entry to
`PROVIDERS` in [llm/__init__.py](llm/__init__.py). The Agent itself
does not change.

## Run

```bash
uv run python main.py
```

## Built-in tools

| Group | Tool | Destructive? |
|---|---|---|
| Steam | `launch_game`, `close_game`, `list_running_games` | no |
| Steam | `install_game`, `uninstall_game` | **yes (2-step confirm)** |
| Packages | `list_flatpak_apps`, `search_flatpak`, `disk_usage` | no |
| Packages | `install_flatpak`, `uninstall_flatpak` | **yes (2-step confirm)** |
| System | `get_battery`, `get_volume`, `set_volume` | no |
| Macro | `press_key`, `start_key_loop`, `stop_all_macros` | no |
| Meta | `final_answer` | — |

### Two-step confirmation

Any tool that installs or uninstalls software accepts a `confirm: bool`
argument. The agent always calls it twice:

1. **Preview turn** — `confirm=false`: the tool reports what *would*
   happen (app id, disk size, etc.) and the agent asks the user to
   approve.
2. **Execution turn** — on the user's "yes/确认" reply, the agent calls
   the same tool with `confirm=true`.

This makes it impossible for the agent to silently wipe an app — the
user always sees a preview and types an explicit confirmation first.

## Example session

```
you> 查看当前电量
  ▸ tool: get_battery({})
    ↳ {'ok': True, 'device': 'BAT1', 'percent': 78, 'status': 'Discharging'}
  ▸ tool: final_answer({'message': 'Battery: 78% (discharging).'})
bot> Battery: 78% (discharging).

you> 把音量调到 50%
  ▸ tool: set_volume({'percent': 50})
    ↳ {'ok': True, 'percent': 50, 'backend': 'wpctl'}
  ▸ tool: final_answer({'message': 'Volume set to 50%.'})
bot> Volume set to 50%.

you> 每隔 5 秒按一次空格键
  ▸ tool: start_key_loop({'key': 'space', 'interval_seconds': 5})
    ↳ {'ok': True, 'loop_id': 1, 'key': 'space', 'interval_seconds': 5, ...}
bot> Started a loop pressing 'space' every 5s. Say "stop macros" to cancel.

you> 打开 CS2
  ▸ tool: launch_game({'game_name': 'cs2'})
    ↳ {'ok': True, 'game': 'cs2', 'app_id': '730', 'pid': 12345}
bot> Launching CS2.

you> 帮我卸载 Dolphin 模拟器
  ▸ tool: list_flatpak_apps({})
    ↳ {'ok': True, 'count': 23, 'apps': [...,
         {'app_id': 'org.DolphinEmu.dolphin-emu', 'name': 'Dolphin', 'size': '412 MB'}]}
  ▸ tool: uninstall_flatpak({'app_id': 'org.DolphinEmu.dolphin-emu', 'confirm': False})
    ↳ {'ok': True, 'dry_run': True, 'app_id': 'org.DolphinEmu.dolphin-emu',
       'size': '412 MB', 'message': 'Will uninstall ... Ask the user to confirm...'}
  ▸ tool: final_answer({'message': '找到了 Dolphin (412 MB)。确认卸载吗？'})
bot> 找到了 Dolphin (412 MB)。确认卸载吗？

you> 确认
  ▸ tool: uninstall_flatpak({'app_id': 'org.DolphinEmu.dolphin-emu', 'confirm': True})
    ↳ {'ok': True, 'uninstalled': 'org.DolphinEmu.dolphin-emu', ...}
  ▸ tool: final_answer({'message': '已卸载 Dolphin，释放约 412 MB。'})
bot> 已卸载 Dolphin，释放约 412 MB。
```

## Notes & limitations

- **Steam launch** uses the `steam://rungameid/<id>` URI when the
  `steam` binary is on `PATH`; otherwise it returns a mock result so
  you can still test the loop on macOS/dev machines.
- **Volume** prefers `wpctl` (PipeWire — SteamOS 3 default) and falls
  back to `amixer`.
- **Battery** reads `/sys/class/power_supply/*/capacity`.
- **Macros** use `pynput`. On a headless box or without input
  permissions the calls degrade to a mock that just logs.

## Adding a tool

1. Write an `async def my_tool(...) -> dict` somewhere under `tools/`.
2. Add an entry to `TOOLS` in `tools/__init__.py` with its JSON schema.

That's it — the planner will see it on the next turn.
