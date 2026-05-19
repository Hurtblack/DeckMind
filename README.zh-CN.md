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
            │            (循环直到模型输出文本)              │
            └─────────────────────────────────────────────┘
```

- **Planner**（[`runtime/planner.py`](runtime/planner.py)）—— 向 LLM 发一次请求，
  拿到模型想调用的下一个工具。
- **Executor**（[`runtime/executor.py`](runtime/executor.py)）—— 在工具注册表里
  找到对应实现并执行。
- **Agent**（[`runtime/agent.py`](runtime/agent.py)）—— 把上面两者串起来：
  把工具结果喂回 LLM，直到模型输出自然语言文本或达到 `MAX_STEPS` 上限。
- **Tools**（[`tools/*.py`](tools/)）—— 真正干活的代码（Steam、系统、宏）。
  添加新工具 = 在 [`tools/__init__.py`](tools/__init__.py) 里加一条注册。
- **Memory**（[`memory/session.py`](memory/session.py)）—— 滚动窗口式的最近对话记录。

更详细的可视化架构图见 [docs/architecture.html](docs/architecture.html)（用浏览器打开）。

## 通用安装（任何 Linux / macOS 开发机）

依赖：Python 3.11+。

```bash
git clone https://github.com/Hurtblack/DeckMind.git
cd DeckMind
./install.sh                 # 自动装 uv + 依赖 + 设置 deckmind 命令
                             # 交互式问你 LLM API key（输入不回显）
```

之后新开终端跑 `deckmind` 就完事。脚本幂等，随时可重跑。
要全手动的话看下面 Steam Deck 那段拆解步骤。

## 在 Steam Deck 上安装

> ⚠️ 在**桌面模式**（KDE）下安装；跑通之后再用"非 Steam 游戏"的方式加进库，
> 这样在游戏模式也能启动。

**TL;DR 极速路径**：在 Konsole 里跑：

```bash
passwd                                                       # 首次必须，设 sudo 密码
cd ~ && git clone https://github.com/Hurtblack/DeckMind.git
cd ~/DeckMind && ./install.sh                                # 剩下全自动
```

新开一个 Konsole 窗口，输 `deckmind` 就跑起来了。下面那一长串手动步骤
其实就是 `install.sh` 干的事情拆开讲。

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
source $HOME/.local/bin/env
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
you› 查看当前电量
you› 把音量调到 30%
you› 打开 CS2
```

### 7b. （可选）压成一个命令

往 `~/.bashrc` 加两个小 shell 函数，以后任意目录敲 `deckmind` 就能启动：

```bash
echo 'deckmind() { (cd ~/DeckMind && uv run python ./main.py "$@"); }' >> ~/.bashrc
echo 'deckmind-update() { (cd ~/DeckMind && git pull && uv sync); }'   >> ~/.bashrc
source ~/.bashrc
```

之后日常就这样：

```bash
deckmind                 # 启动 agent
deckmind -v              # verbose / 开发者模式
deckmind-update          # 任意目录 git pull + uv sync
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

- **宏默认在 Deck 上不启用。** `pynput` 依赖的 `evdev` C 扩展需要内核头文件，
  而 SteamOS 的 `/usr` 是只读的、不带 headers，所以编译会失败。退一步即使装上
  了，pynput 也无法往 Wayland 会话（桌面模式 KDE Plasma、游戏模式 Gamescope）
  注入按键 —— 本来就是空转。所以 pynput 没装时，宏类工具会返回无害的 mock
  结果。真正要启用宏，把后端换成 `ydotool` —— 提个 issue / PR 即可，
  改动很小，就在 [tools/macro_tool.py](tools/macro_tool.py) 一个文件。
- **启动游戏** 要求 Steam 客户端已经在跑。游戏模式下它一直在跑；桌面模式记得
  先打开 Steam。
- **电池设备** Deck 上是 `BAT1`（不是 `BAT0`），代码会自动识别两种。

## 选择 LLM 服务商

通过环境变量 `LLM_PROVIDER` 选后端，每家用各自的 API key：

| 服务商 | `LLM_PROVIDER` | API Key 环境变量 | 默认模型 |
|---|---|---|---|
| OpenAI（Responses API） | `openai`（默认） | `OPENAI_API_KEY` | `gpt-4o-mini` |
| OpenAI（Chat Completions） | `openai-chat` | `OPENAI_API_KEY` | `gpt-4o-mini` |
| **DeepSeek** | `deepseek` | `DEEPSEEK_API_KEY` | `deepseek-v4-flash` |
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

## 内置工具（共 40 个）

| 分组 | 工具 | 风险 |
|---|---|---|
| Steam | `launch_game`、`close_game`、`list_running_games` | side-effect |
| Steam | `install_game`、`uninstall_game` | **destructive（两步确认）** |
| 包管理 | `list_flatpak_apps`、`search_flatpak`、`disk_usage` | safe |
| 包管理 | `install_flatpak`、`uninstall_flatpak` | **destructive（两步确认）** |
| Pacman / SteamOS | `pacman_search`、`steamos_lock_status`、`steamos_lock` | safe |
| Pacman / SteamOS | `steamos_unlock` | side-effect |
| Pacman / SteamOS | `pacman_install`、`set_pacman_mirror_china` | **destructive（两步确认）** |
| 系统 | `get_battery`、`get_volume` | safe |
| 系统 | `set_volume` | side-effect |
| 宏 | `press_key`、`start_key_loop`、`stop_all_macros` | side-effect |
| 文件 / 诊断 | `find_files`、`list_processes`、`read_text_file` | safe |
| 文件 / 诊断 | `write_text_file`、`run_command` | **destructive（两步确认）** |
| **画像** | `remember`、`forget`、`list_profile` | safe |
| **自更新** | `check_for_updates` | safe |
| **自更新** | `apply_update` | **destructive（两步确认）** |
| **Notion** | `notion_status`、`notion_databases`、`notion_set_default_database`、`notion_pages`、`notion_recent`、`notion_total` | safe |
| **Notion** | `notion_log_session`、`notion_create_page` | side-effect |

Agent 用一段自然语言回复来结束一轮 —— 不再有 `final_answer` 这种哨兵工具。

### Runtime 权限闸门（代码层强制）

[`runtime/executor.py`](runtime/executor.py) 在每次调用工具**之前**做权限检查 ——
这是**代码层面**的限制，跟 system prompt 的约束相互独立，比它更硬。三档：

| 风险等级 | 行为 | 工具 |
|---|---|---|
| `safe`（安全） | 静默放行 | get_*、list_*、search_*、disk_usage、find_files、list_processes、read_text_file、check_for_updates、remember/forget/list_profile、pacman_search、steamos_lock_status/lock、Notion 只读工具 |
| `side_effect`（副作用） | 弹 `[y=允许 / n=拒绝 / a=本工具本会话全允许]` | set_volume、press_key、start_key_loop、stop_all_macros、launch_game、close_game、steamos_unlock、notion_log_session、notion_create_page |
| `destructive`（破坏性） | `confirm=false` 是免费预览；`confirm=true` 执行前弹 `[y / n / a]` | install_*、uninstall_*、apply_update、pacman_install、set_pacman_mirror_china、write_text_file、run_command |

闸门默认**问而不拦**，最终决定权永远在你手里。`a`（全允许）在 side_effect 和
destructive 两种提示里都生效 —— 批量操作时按一次后就不再骚扰。

### 什么情况会硬拒绝并说明原因

有一小类操作真的会**搞坏正在运行的系统**，工具会直接拒绝并清楚说明原因（LLM
会把原因复述给你而不是装糊涂）：

- **`close_game`** 拒绝匹配以下任意一个的 `process_name`：
  `systemd`、`init`、`kernel`、`gamescope`、`kwin`、`plasma`、`kded`、`xorg`、
  `wayland`、`pipewire`、`pulseaudio`、`dbus`。每个都带一句原因
  （例如 "PID 1 / system init — 杀掉会导致整机崩溃"）。
- **`uninstall_flatpak`** 拒绝所有 Flatpak 共享运行时
  （`org.freedesktop.Platform`、`org.freedesktop.Sdk`、`org.kde.Platform`、
  `org.gnome.Platform` 及其 `.Sdk` / `.Locale` / `.GL.*` 等子 ID）。
  删掉它们会让系统上所有 Flatpak 应用一起挂掉。
- **`run_command`** 不使用 shell，并拒绝管道、重定向、`&&`、命令替换、
  `$` 展开等 shell 语法。高级模式仍然硬拒绝 `sudo`/`su`/`doas`、
  shell 和脚本解释器、`pacman`、`rm`、系统级 `systemctl`、`mkfs`、
  裸设备写入、关机和重启。
- **`write_text_file`** 只写入用户目录下的允许路径。`.env`、`token`、
  `secret`、`credential`、`password`、`~/.ssh` 这类敏感路径必须单独
  使用 `high_risk_confirm=true`，dry-run 也不会回显文件内容。这个保护的是
  本地预览和工具输出；如果你把真实 token 直接发到聊天里，配置的 LLM 服务商
  仍然可能看到。

其他情况 —— 哪怕看上去有点吓人，比如要 `kill` 一个叫 `bash` 的进程，
或者卸载某个第三方模拟器 —— 都只会走正常的询问流程交给你决定。

### 受限命令自动化

`run_command` 用来减少"请你自己去 Konsole 输入这条命令"的摩擦，覆盖小型
用户级自动化流程。它有两种模式：

- **普通白名单**：`curl`/`wget` 下载到允许的用户目录、`tar -xzf` 安全解压、
  `chmod +x`、`mkdir -p`、`launch_file`、`file`、`which`，以及简单的
  `systemctl --user` 操作。
- **高级模式**：普通白名单外的命令可以从受信任的可执行目录运行，但仍然是
  argv 形式，不经过 shell。高级模式必须先 dry-run，用户明确批准后，再用
  `high_risk_confirm=true` 执行。

支持的自动化示例：

```text
下载 AppImage：
run_command(["curl", "-L", "-o", "~/Downloads/App.AppImage", url])

解压用户态 tarball：
run_command(["tar", "-xzf", "~/Downloads/app.tar.gz", "-C", "~/Downloads"])

启动已批准的可执行文件：
run_command(["launch_file", "~/Downloads/App.AppImage"])

高级诊断：
run_command(["pgrep", "-a", "clash"], advanced=true)
```

它不是通用 root 终端。例如 `sudo npm i -g pnpm@9` 会被明确拒绝。

## 持久化用户画像

Agent **跨重启**记得你告诉它的事。存在 `~/.deckmind/profile.json`，
一个简单的 key→value JSON。每次启动时自动注入到 system prompt，所以
第一次说话之前 agent 就"认识你"了。

```text
you › 记住我叫 hurtblack，喜欢魂系游戏，周末才有时间玩
deckmind › 好的，记下来啦。

[exit，重新打开 deckmind，甚至重启 Deck]

you › 推荐一个我现在能玩的
deckmind › 看你喜欢魂系、加上时间紧 —— 试试 Sekiro，单局节奏快。
```

也可以直接 `nano ~/.deckmind/profile.json` 手动编辑，就是纯 JSON。

## 自我更新

Agent 可以自己从 GitHub 拉最新代码：

```
you › 检查更新           → 调用 check_for_updates（只读）
deckmind › 落后 3 个提交，新内容：...

you › 拉一下             → 调用 apply_update(confirm=false)
deckmind › 预览：从 abc → def，3 个提交。要执行吗？
you › 确认
deckmind › ✓ pull + uv sync 完成。退出后重启 agent 加载新代码。
```

安全约束：
- 只在项目目录内操作。
- 拉取的是本地配置的 `origin`（LLM 改不了 URL，工具签名不接受）。
- `git pull --ff-only`，历史分叉会大声报错而不是悄悄合并。
- 有未提交的**跟踪文件改动**时硬拒绝。未跟踪文件（如 `uv.lock`）不会
  阻塞，也不会被覆盖。

## Notion 日志

把游戏时长记录到你的 Notion 数据库。三步设置：

1. **拿 token** —— 在 https://www.notion.so/profile/integrations 建一个
   *Internal Integration*，复制那串 `ntn_…`。
2. **写到 env**（用 `nano ~/.bashrc`，**绝不要**把 token 输入到 agent
   或任何聊天 —— 会被发到 LLM 服务商的日志里）：
   ```bash
   export NOTION_API_KEY=ntn_xxxxx
   ```
   然后 `source ~/.bashrc` + 重启 `deckmind`。
3. **把数据库分享给 integration**（数据库右上 `⋯` → Connections →
   搜 DeckMind → 加进去）。

完事 —— **不需要 `NOTION_DATABASE_ID`**。你说"绑定 notion"时，
`notion_status` 会自动发现：

- **只分享了 1 个数据库** → 自动选中，存到 `~/.deckmind/notion.json`
- **分享了 2+ 个** → 列出来让你选，然后调 `notion_set_default_database`
- **一个都没分享** → 提示你先去 Notion 分享

字段按**类型匹配**，不按名字 —— 只要数据库有 Title + Number + Date
（外加可选的 Rich Text 当备注），不管字段叫啥都能用。

```
you › 记一笔我刚玩了 1 小时 Hades
deckmind › ✓ 已记录：Hades · 60 分钟 · 今天

you › 这周玩了多久
deckmind › 本周共 8.5 小时。排行：Hades 4h、Stardew 2h、CS2 1.5h。
```

## 运行时界面（UI）

```
you ›                  ← 亮青色粗体（你的输入）
deckmind ›             ← 亮绿色粗体（agent 回复，字逐字流式输出）
  · tool_name…         ← 暗黄色（quiet 模式的工具调用提示）
  ! refused: ...       ← 暗红色（只在出错/拒绝时出现）
  ↳ 耗时 1.8s  ·  本轮 提示 9,810 + 回复 192 tokens  ·  累计 ...  ·  模型 deepseek-chat
                       ← 暗灰色（每轮回答后的 footer）
```

- **流式输出**：模型生成一个字蹦一个字，不用等整段。
- **Footer**：墙上时钟耗时 + 本轮 token + 会话累计 + 模型名。
- **颜色**：尊重 `NO_COLOR` 环境变量；stdout 不是 TTY 时自动关闭
  （管道导出到文件不会被乱码污染）。
- **`-v` 参数**：verbose 模式显示完整的 `▸ tool: name({args})` 和
  原始结果字典。默认 quiet 模式只显示工具名。

## 示例对话

```text
you> 查看当前电量
  ▸ tool: get_battery({})
    ↳ {'ok': True, 'device': 'BAT1', 'percent': 78, 'status': 'Discharging'}
bot> 当前电量 78%，正在放电。

you> 把音量调到 50%
  ▸ tool: set_volume({'percent': 50})
    ↳ {'ok': True, 'percent': 50, 'backend': 'wpctl'}
bot> 已将音量调到 50%。

you> Clash Verge 下载好了，帮我解压并启动
  ▸ tool: find_files({'query': 'Clash.Verge', 'roots': ['~/Downloads']})
    ↳ {'ok': True, 'matches': ['~/Downloads/Clash.Verge_x64.app.tar.gz']}
  ▸ tool: run_command({'argv': ['tar', '-xzf', '~/Downloads/Clash.Verge_x64.app.tar.gz', '-C', '~/Downloads'], 'confirm': False})
    ↳ {'ok': True, 'dry_run': True, 'command': 'tar', 'output_path': '/home/deck/Downloads'}
bot> 找到了压缩包，也完成了安全检查。确认解压到 Downloads 吗？

you> 确认
  ▸ tool: run_command({'argv': ['tar', '-xzf', '~/Downloads/Clash.Verge_x64.app.tar.gz', '-C', '~/Downloads'], 'confirm': True})
    ↳ {'ok': True, 'command': 'tar', 'returncode': 0}
  ▸ tool: find_files({'query': 'clash-verge', 'roots': ['~/Downloads']})
    ↳ {'ok': True, 'matches': ['~/Downloads/Clash Verge/clash-verge']}
  ▸ tool: run_command({'argv': ['chmod', '+x', '~/Downloads/Clash Verge/clash-verge'], 'confirm': False})
    ↳ {'ok': True, 'dry_run': True, 'command': 'chmod'}
bot> 找到主程序 `~/Downloads/Clash Verge/clash-verge`。确认加执行权限并启动吗？

you> 可以
  ▸ tool: run_command({'argv': ['chmod', '+x', '~/Downloads/Clash Verge/clash-verge'], 'confirm': True})
    ↳ {'ok': True, 'command': 'chmod', 'returncode': 0}
  ▸ tool: run_command({'argv': ['launch_file', '~/Downloads/Clash Verge/clash-verge'], 'confirm': False})
    ↳ {'ok': True, 'dry_run': True, 'command': 'launch_file'}
  ▸ tool: run_command({'argv': ['launch_file', '~/Downloads/Clash Verge/clash-verge'], 'confirm': True})
    ↳ {'ok': True, 'command': 'launch_file', 'pid': 12345}
bot> Clash Verge 已启动。

you> 帮我看一下 Clash 进程在不在
  ▸ tool: run_command({'argv': ['pgrep', '-a', 'clash'], 'advanced': True, 'confirm': False})
    ↳ {'ok': True, 'dry_run': True, 'advanced': True, 'risk_level': 'high',
       'requires_high_risk_confirm': True}
bot> 这条命令不在普通白名单里，需要高风险确认。是否执行 `pgrep -a clash`？

you> 确认
  ▸ tool: run_command({'argv': ['pgrep', '-a', 'clash'], 'advanced': True, 'confirm': True, 'high_risk_confirm': True})
    ↳ {'ok': True, 'command': 'pgrep', 'stdout_tail': '12345 clash-verge\n'}
bot> Clash 正在运行：PID 12345，命令是 `clash-verge`。

you> 帮我卸载 Dolphin 模拟器
  ▸ tool: list_flatpak_apps({})
    ↳ {'ok': True, 'count': 23, 'apps': [...,
         {'app_id': 'org.DolphinEmu.dolphin-emu', 'name': 'Dolphin', 'size': '412 MB'}]}
  ▸ tool: uninstall_flatpak({'app_id': 'org.DolphinEmu.dolphin-emu', 'confirm': False})
    ↳ {'ok': True, 'dry_run': True, 'size': '412 MB',
       'message': 'Will uninstall ... Ask the user to confirm...'}
bot> 找到了 Dolphin (412 MB)。确认卸载吗？

you> 确认
  ▸ tool: uninstall_flatpak({'app_id': 'org.DolphinEmu.dolphin-emu', 'confirm': True})
    ↳ {'ok': True, 'uninstalled': 'org.DolphinEmu.dolphin-emu', ...}
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
