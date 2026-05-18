# 受限命令自动化设计

## 背景

DeckMind 目前已经有一批面向 Steam Deck 的专用工具：Flatpak 安装/卸载、pacman
安装、文本文件写入、文件搜索、进程列表、Steam 游戏启动，以及用户级配置管理。
当用户需求正好落在这些工具覆盖范围内时，DeckMind 可以直接执行，减少手动操作。

现在的缺口出现在另一类任务：用户要做的是一小段命令流程，但这段流程还没有被封装成专用工具。
以 Clash Verge 为例，DeckMind 可以找到 AppImage，也可以写下载脚本，但不能直接运行下载命令或给文件加执行权限。
用户最后仍然要复制或手动输入命令。

用户已确认期望方向：增加“受限 shell 自动化”，让用户只需要授权，不需要自己敲命令。

## 目标

新增一个受约束的命令执行能力，让 DeckMind 可以在用户授权后，直接完成简单的用户级操作步骤。

主要成功场景：

1. 用户要求 DeckMind 下载或设置一个用户空间应用。
2. DeckMind 预览将要执行的命令。
3. 用户通过现有确认流程授权。
4. DeckMind 执行命令、校验结果，并向用户报告最终状态。

## 非目标

- 不向模型开放任意 shell。
- 不使用 `shell=True`。
- 不支持管道、重定向、命令替换、shell 展开或复合命令。
- 不允许写入明确批准目录之外的位置。
- 当 `install_flatpak`、`pacman_install` 等专用工具已经覆盖需求时，不用通用命令工具替代它们。
- 不接受或处理用户粘贴到聊天里的凭据。

## 新增工具

新增工具：`run_command`。

工具接收 argv 形式的命令：

```json
{
  "argv": ["curl", "-L", "-o", "~/Downloads/Clash.Verge.AppImage", "https://example.com/appimage"],
  "confirm": false
}
```

实现上使用 `asyncio.create_subprocess_exec(*argv)` 执行命令，不经过 shell 解析层。

## 命令白名单

第一版只允许覆盖当前反馈和相邻用户级自动化所需的命令：

- `curl`：下载文件和轻量 HTTP 检查。
- `wget`：在可用且参数通过校验时下载文件。
- `chmod`：修改批准目录内文件的权限。
- `mkdir`：创建批准目录内的用户目录。
- `file`：检查已下载文件的类型。
- `which`：检查命令是否存在。
- `systemctl --user`：只管理用户级 systemd 服务。

已有专用工具仍然优先：

- Flatpak 应用管理继续使用 `install_flatpak` / `uninstall_flatpak`。
- pacman 安装继续使用 `pacman_install`，因为它已经处理 SteamOS 只读状态和风险提示。

## 路径策略

会写入或修改文件的命令，只能作用在以下用户拥有的位置：

- `~/Downloads`
- `~/.deckmind`
- `~/.local/share/applications`
- `~/.config/systemd/user`
- `~/.config/autostart`
- `~/Documents`
- `~/Desktop`

即使路径位于批准目录内，只要包含下列敏感片段也必须拒绝：

- `/.ssh`
- `/.gnupg`
- `/.aws`
- `/.docker`
- `/.kube`
- `password`
- `credential`
- `secret`
- `token`
- `id_rsa`
- `id_ed25519`

工具需要展开 `~`，并在执行前检查规范化后的绝对路径。对于写入或修改操作，目标如果是符号链接则拒绝。

## 风险分级

将 `run_command` 加入现有 Executor 风险体系，归类为 destructive。工具沿用现有破坏性工具的两步流程：

1. `confirm=false`：校验参数并返回 dry-run 预览。
2. `confirm=true`：Executor 向用户确认后才执行。

现有 Executor 已支持 `a=本会话此工具全允许`。这个行为也应适用于 `run_command`，
这样用户可以对同一批相关步骤做一次会话级授权。

工具本身仍然必须在 dry-run 和实际执行前都做 allowlist 与路径校验。Executor 授权不能替代工具内部校验。

## 命令级规则

### `curl`

允许形式覆盖下载和 header 检查：

- `curl -L -o <批准路径> <http-url>`
- `curl -fL -o <批准路径> <http-url>`
- `curl -I <http-url>`
- `curl -L -I <http-url>`

规则：

- URL 必须使用 `http` 或 `https`。
- 输出路径必须位于批准的写入目录内。
- 在可行范围内拒绝明显携带凭据的 URL 参数，例如 `token=`、`access_token=`、`key=`。
- 如果用户没有提供超时参数，工具应设置合理超时。
- 返回 stdout/stderr 尾部、返回码、耗时，以及输出文件大小。

### `wget`

允许形式：

- `wget -O <批准路径> <http-url>`

使用与 `curl` 相同的 URL 和输出路径规则。

### `chmod`

允许形式：

- `chmod +x <批准路径>`

规则：

- 第一版只允许增加可执行权限。
- 拒绝递归模式。
- 拒绝数字权限或过宽权限模式。
- 目标必须是批准写入目录内的普通文件。

### `mkdir`

允许形式：

- `mkdir -p <批准目录>`

规则：

- 目录必须位于批准写入目录内。
- 拒绝创建敏感或凭据相关路径。

### `file`

允许形式：

- `file <批准读取路径>`

规则：

- 只做只读检查。
- 目标必须位于批准读取位置内。

### `which`

允许形式：

- `which <命令名>`

规则：

- 命令名必须是简单可执行文件名，不能是路径。

### `systemctl --user`

允许形式：

- `systemctl --user daemon-reload`
- `systemctl --user enable <unit>`
- `systemctl --user disable <unit>`
- `systemctl --user start <unit>`
- `systemctl --user stop <unit>`
- `systemctl --user status <unit>`

规则：

- 只允许用户级 systemd。
- 拒绝系统级 `systemctl`。
- unit 名必须是简单的 `.service` 单元名，不能是路径。

## Clash Verge 流程

当用户要求 DeckMind 下载 Clash Verge，并且下载 URL 已知或由用户提供时，预期流程如下：

1. 使用 `run_command` 调用 `curl`，并以 `confirm=false` 预览下载命令。
2. 用户授权后执行下载命令。
3. 校验下载文件存在，并且大小不是明显异常的小文件。
4. 尽可能复用同一次会话授权，使用 `run_command` 执行 `chmod +x`。
5. 可选使用 `file` 检查下载结果。
6. 告诉用户最终路径，以及文件是否已经可执行。

这会把当前“写脚本让用户手动运行”的流程，变成“DeckMind 在校验命令后，获得授权并直接执行”。

## Prompt 更新

更新 `prompts/system_prompt.txt`，说明：

- 优先使用专用工具。
- 当没有专用工具覆盖时，用 `run_command` 执行小型用户级命令自动化。
- 如果 `run_command` 能在授权后安全执行，就不要要求用户手动输入命令。
- 不要把 `run_command` 用于凭据、任意 shell、sudo、pacman 或系统级变更。

## 测试

增加聚焦测试或验证脚本，覆盖：

- 允许 `curl -L -o ~/Downloads/name.AppImage <url>` 的 dry-run 校验。
- 拒绝 shell 元字符或复合命令。
- 拒绝写入批准目录之外的位置。
- 拒绝敏感路径片段。
- 拒绝 `chmod -R` 和数字 chmod 模式。
- 拒绝系统级 `systemctl`。
- 使用无害本地命令验证成功执行路径，例如 `which sh` 或 `mkdir -p ~/.deckmind/test-command-runner`。

如果项目还没有正式测试框架，先为命令校验器增加轻量单元测试。校验器应和 subprocess 执行分离，
这样大部分安全行为都可以在不实际运行外部命令的情况下测试。

## 未来范围

第一版应保持命令白名单足够小。未来只有在出现具体用户工作流，并且能为新命令写出清晰校验器时，
才扩展新的命令。
