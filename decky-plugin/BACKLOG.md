# DeckMind Plugin 部署体验改进待办

记录 2026-05-19 ~ 05-20 首次端到端部署时踩过的所有坑，按优先级排序。
目标：新用户在 Steam Deck 上点一次"安装 Runtime"就能从 0 到能聊天，不需要手动 Konsole 操作。

---

## 🔥 P0 - 必须修，否则新用户根本装不上

### #0 写入/控制类 tool "假成功"（CLI 跑同代码 OK）
**症状**（2026-05-20 实测）：
- ✅ 查询电池电量 → 正常返回（读 `/sys/class/power_supply/`，纯文件 IO）
- ❌ "打开游戏 xxx" → UI 显示成功，Steam 没反应
- ❌ "调高音量" → UI 显示成功，音量没变
- ✅ **同样的 runtime 在 Konsole 里 `python3 main.py` 跑，全部正常**

**根本原因**：plugin 后端是 `plugin_loader.service` 这个 systemd 服务启动的，
没继承用户登录时的图形会话环境。subprocess 调 steam/pactl/wpctl 时
`DBUS_SESSION_BUS_ADDRESS` / `WAYLAND_DISPLAY` / `XDG_RUNTIME_DIR` 都没设，
命令 exit 0 但 DBus 调用沉默失败 → 后端拿到 returncode=0 误以为成功。

**排查步骤**：
```bash
# 1. 看 plugin 后端实际拿到的环境变量
sudo cat /proc/$(pgrep -f 'plugins/DeckMind' | head -1)/environ | tr '\0' '\n' | grep -iE 'DBUS|DISPLAY|XDG'

# 2. 对比 Konsole 里 (deck 用户登录会话)
env | grep -iE 'DBUS|DISPLAY|XDG'
```
两者差异基本就是问题所在。

**修复方向**（按推荐度排序）：
1. **借用 deck 用户的 session bus**：tool 执行前，注入 `XDG_RUNTIME_DIR=/run/user/1000`
   和 `DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/1000/bus`（uid=1000 是 deck 默认）
2. **subprocess 真正校验执行效果**：调音量后 read back 验证，而非只看 returncode
3. **对 Steam 用 IPC 文件**：写 `~/.steam/steam/steam.pipe` 触发命令，绕开 DBus
4. **D-Bus 调 systemd --user**：用 `systemctl --user --machine=deck@.host` 套娃执行
5. **走 Decky 提供的 API**：Decky 本身可能有跨进程调用 Steam 的能力，调研

**实现：tool 执行前自动 patch 环境**
在 runtime/executor.py 或 tool 实现里加：
```python
def _user_session_env():
    env = os.environ.copy()
    env.setdefault("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")
    env.setdefault("DBUS_SESSION_BUS_ADDRESS", f"unix:path=/run/user/{os.getuid()}/bus")
    env.setdefault("DISPLAY", ":0")  # Game Mode 可能没 X，但桌面模式有
    env.setdefault("WAYLAND_DISPLAY", "wayland-0")
    return env
subprocess.run(cmd, env=_user_session_env(), ...)
```



### #1 自动检测 Decky 的 Python 版本，用对应 wheel 装 pydantic
**问题**：venv 用系统 Python（如 3.13），但 Decky Loader 内置 Python 是 3.11，
pydantic_core 的 .so 是 Python 版本绑定的，不兼容会报 `ModuleNotFoundError: No module named 'pydantic_core._pydantic_core'`。

**修复方案**：
- `installer._install_python_deps` 增加：
  1. 检测 Decky Python 版本（扫 `/tmp/_MEI*/` 或读 plugin_loader 进程的 `/proc/{pid}/exe` 找 libpython）
  2. pip install 时加 `--python-version {ver} --platform manylinux2014_x86_64 --only-binary :all:`
- 兜底：如果检测失败，按 3.11 装（覆盖目前已知 Decky Loader 主流版本）

**预期效果**：用户无需关心 Python 版本，installer 自动选对 wheel。

---

### #2 install_runtime 失败时 UI 仍能看到错误（目前可能被吞）
**问题**：install_async 异常虽然返回 `{ok: false, error}`，但 UI [index.tsx](src/index.tsx) 里 system message 区域显示空错误时不易察觉。
**修复方案**：
- 安装失败时，UI 显式弹 toaster.toast 标题红色 + 文案
- 错误超过 200 字符自动折叠，提供"展开/复制"

---

### #3 plugin 目录权限会被 Decky 反复以 root 写坏，导致后续 rsync 失败
**问题**：Decky Loader 服务以 root 跑，在某些状态下（特别是 install_runtime 过程中）写入 `/home/deck/homebrew/plugins/DeckMind/` 时会把文件 owner 改成 root。下次 deck 用户 rsync 时 `Permission denied`。

**修复方案**：
- 部署脚本默认带 `--rsync-path="sudo rsync"` 让 receiver side 以 root 写（需要 NOPASSWD 配置，或者用 ssh key + sudo）
- 或者：在 install_runtime 完成后 installer 自己 `os.chown` 一遍 plugin 目录回 deck
- 文档明确警告：手动操作 plugin 目录前必须 `sudo systemctl stop plugin_loader && sudo chown -R deck:deck`

---

## ⚡ P1 - 高频踩坑，体验问题

### #4 SteamOS PEP 668 + PyInstaller LD_LIBRARY_PATH 双重坑
**问题**：
- SteamOS 3.7+ 锁了系统 pip（PEP 668）
- Decky Loader 是 PyInstaller 单文件，启动时设 LD_LIBRARY_PATH 指向 `/tmp/_MEI*/`，导致 subprocess 调 git/curl 加载错版本 libssl

**当前状态**：已部分修复（`_clean_env` + venv 兜底，commit `8750e32` `5b87f0c`）

**还需要**：
- requirements.txt 增加 `--hash` 校验（防 venv 装到一半被中断 corrupt）
- 失败时清理 venv 残留再重试

---

### #5 GitHub Release 默认 URL 是 404
**问题**：`DEFAULT_RUNTIME_URL` 指向 `releases/latest/download/...`，但仓库还没发布过 release，新装用户直接 404。

**当前状态**：已改为 git clone 调试模式（commit `0d2d25d`）

**还需要**：
- 准备好发 v0.1.0 时，把 installer 的 mode 改回 release 下载（git clone 模式留作 fallback / dev 用）
- CI workflow 在 tag 时自动打包 `deckmind-runtime.tar.gz`

---

### #6 Decky plugin 加载时 sys.path 不含 plugin 目录
**问题**：`main.py` 里 `from config_store import CONFIG_STORE` 会 ModuleNotFoundError。
**当前状态**：已修（commit `ce39f24`，main.py 头部加 sys.path.insert）

**还需要**：
- 模板化：把 sys.path 注入逻辑封进一个 `_bootstrap_path.py`，main.py 只 import 它，更清晰

---

### #7 `_root` flag 让后端跑在 /root 而非 /home/deck，路径全错位
**问题**：默认模板用了 `_root`，但 DeckMind runtime 不需要硬件级权限。
**当前状态**：已去掉（commit `8ab5b34`）

**还需要**：
- README 里说明：什么场景需要 `_root`，什么场景不需要

---

## 💡 P2 - 体验优化（不影响功能）

### #8 install_runtime 没有进度反馈，用户不知道是卡了还是在跑
**问题**：git clone 几秒到几十秒；pip install 30-60 秒。UI 只显示"开始下载并安装 Runtime..."然后干等。

**修复方案**：
- 后端开 SSE / WebSocket 推 stage：`cloning → cloned → installing_deps → success`
- 或者：UI 轮询 `/install_status` RPC，返回当前阶段 + 进度
- 简单方案：每个阶段往 events 列表写一条，turn 风格的 polling

---

### #9 失败的 install_runtime 留下残骸（runtime.bak、半成品 venv）
**问题**：第一次装 OpenSSL 报错失败后，runtime_dir 留下了空目录或部分文件。再装一次会触发 `.bak` 备份机制，但旧 .bak 不会被清。
**修复方案**：
- installer 加 cleanup 接口；失败时回滚到上次成功的 .bak
- 状态显示"上次安装失败，已回滚到 commit xxx"

---

### #10 .vendor 复用机制 + 版本检测
**问题**：用户多次点"安装"会反复 pip install。如果网络慢很难受。
**修复方案**：
- pip install 前比对 `requirements.txt` hash 和 `.vendor/.req_hash`，没变就跳过
- 强制重装走 query string `?force=1`

---

### #11 UI 切换 provider 时没有提示是否需要新 API key
**问题**：从 deepseek 切到 openai，没设过 OpenAI key 直接发消息会拿到模糊的 `missing_api_key` 报错。
**修复方案**：
- StatusBar 的 API key 徽章跟当前 UI 选择的 provider 联动（而非已保存的 provider）
- 切到没 key 的 provider 时弹气泡："此 provider 缺 key，先配置"

---

### #12 对话历史不持久化
**问题**：plugin 重启后历史就没了；切到别的页面再回来也没了（state 在 React 内）。
**修复方案**：
- 后端 RuntimeSession 持久化最近 N 轮到 `~/.config/deckmind/history.jsonl`
- 前端启动时拉历史

---

### #13 安装/部署文档缺失
**问题**：当前 README 只说"用 git clone + decky CLI 装"，但 SteamOS 上要踩的所有坑（PEP 668、PyInstaller env、_root flag、Python 版本）都没文档。
**修复方案**：
- 新增 `docs/SETUP-STEAMDECK.md`：从零开始装的完整 walkthrough
- 故障排查清单（FAQ）：每个错误信息 → 对应原因 → 一行修复命令

---

## 🧰 P3 - 长期工程化

### #14 自动化测试
- plugin RPC 端到端测试（mock Decky 环境）
- installer 在容器里模拟 SteamOS 跑通完整 install 流程

### #15 CI/CD
- Tag 时自动：build plugin → 打 release zip → 上传 GitHub Release
- PR 触发 lint + type check（python: ruff/mypy；ts: tsc）

### #16 给所有用户用的"一键修复"脚本
**问题**：万一上面所有自动化都失败了，用户需要兜底的手动方案。
**方案**：发一个 `scripts/fix-deckmind.sh`，用户在 Konsole 一键跑：
```bash
curl -sSL https://raw.githubusercontent.com/Hurtblack/DeckMind/main/scripts/fix-deckmind.sh | bash
```
脚本做：chown 权限 → 重装 .vendor → 重装 plugin → 重启 Decky → 自检状态。

---

## 已解决（参考）

| Commit | 修复 |
|---|---|
| `8ab5b34` | 去掉 `_root` flag，runtime 放 deck 家目录 |
| `ad0751f` | 路径改 XDG 规范 `~/.local/share/deckmind/runtime/` |
| `f839e73` | install_runtime 异步化 + 超时 + 友好报错 |
| `0d2d25d` | install_runtime 改 git clone/pull 模式 |
| `c3066dc` | _run_turn 复用 agent + 真正切换 LLM + UI 自动保存 + 滚动 |
| `ce39f24` | main.py 显式注入 sys.path |
| `8750e32` | _clean_env 剥离 PyInstaller LD_LIBRARY_PATH |
| `f5f3bfa` | install_runtime 后自动 pip install 到 .vendor |
| `5b87f0c` | SteamOS PEP 668：自动 venv 兜底 |

---

## 后续动作建议

1. **立即做 #1**（pydantic 版本不匹配自动修复）- 不做新用户必踩
2. **做 #16 兜底脚本** - 万一自动化失败有救
3. **写 #13 文档** - 让用户知道踩到哪个坑、怎么自救
4. P2 的能做就做，做不了不影响新用户跑通
