# Restricted Command Automation Design

## Background

DeckMind already has dedicated tools for common Steam Deck tasks: Flatpak
install/uninstall, pacman install, text file writes, file search, process
listing, Steam game launch, and user-level configuration. These tools reduce
manual work when the exact operation is modeled.

The current gap appears when a task needs a small command sequence that is not
yet modeled as a dedicated tool. In the Clash Verge case, DeckMind could find
the AppImage and write a download script, but it could not directly run the
download or mark the file executable. The user then had to copy or type
commands manually.

The user confirmed the desired direction: add restricted shell automation so
the user only needs to grant permission, not type commands.

## Goal

Add a constrained command execution capability that lets DeckMind perform
simple, user-level operational steps directly after user approval.

The primary success case is:

1. The user asks DeckMind to download or set up a user-space application.
2. DeckMind previews the command it intends to run.
3. The user grants permission with the existing confirmation flow.
4. DeckMind runs the command, validates the result, and reports the outcome.

## Non-Goals

- Do not expose arbitrary shell access to the model.
- Do not use `shell=True`.
- Do not support pipes, redirection, command substitution, shell expansion, or
  compound commands.
- Do not allow writes outside explicitly approved user-owned directories.
- Do not replace dedicated tools such as `install_flatpak` or `pacman_install`
  when those tools already cover the request.
- Do not accept or process credentials pasted into chat.

## Proposed Tool

Add a new tool named `run_command`.

The tool accepts an argv-style command:

```json
{
  "argv": ["curl", "-L", "-o", "~/Downloads/Clash.Verge.AppImage", "https://example.com/appimage"],
  "confirm": false
}
```

The implementation runs commands with `asyncio.create_subprocess_exec(*argv)`.
There is no shell parsing layer.

## Command Allowlist

The first implementation should allow only commands needed for the reported
workflow and adjacent user-level automation:

- `curl`: downloads and lightweight HTTP checks.
- `wget`: downloads when available and when its arguments pass validation.
- `chmod`: permission changes for files in approved user directories.
- `mkdir`: creating approved user directories.
- `file`: inspecting downloaded files.
- `which`: checking command availability.
- `systemctl --user`: managing user-level services only.

Dedicated package tools remain preferred:

- Use `install_flatpak` / `uninstall_flatpak` for Flatpak app management.
- Use `pacman_install` for pacman installs because it handles SteamOS
  read-only state and warning behavior.

## Path Policy

Commands that write or mutate files may only target approved user-owned
locations:

- `~/Downloads`
- `~/.deckmind`
- `~/.local/share/applications`
- `~/.config/systemd/user`
- `~/.config/autostart`
- `~/Documents`
- `~/Desktop`

The tool refuses paths containing sensitive fragments even inside approved
locations:

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

The tool expands `~` and checks normalized absolute paths before execution.
It refuses symlink targets for write or mutation operations.

## Risk Classification

Add `run_command` to the existing Executor risk system as destructive. The
tool follows the same two-step pattern as existing destructive tools:

1. `confirm=false`: validate arguments and return a dry-run preview.
2. `confirm=true`: execute only after the Executor asks for confirmation.

The Executor already supports `a=本会话此工具全允许`. That behavior should
apply to `run_command` so a user can approve a batch of related steps once per
session.

The tool itself also validates every command on both dry-run and execution.
Executor approval is not a substitute for allowlist and path validation.

## Command-Specific Rules

### `curl`

Allowed forms should cover downloads and header checks:

- `curl -L -o <approved-path> <http-url>`
- `curl -fL -o <approved-path> <http-url>`
- `curl -I <http-url>`
- `curl -L -I <http-url>`

Rules:

- URLs must use `http` or `https`.
- Output path must be inside an approved write directory.
- Refuse credential-like URLs containing obvious token parameters when
  practical, such as `token=`, `access_token=`, or `key=`.
- Set a reasonable timeout if the user did not provide one.
- Capture stdout/stderr tails, return code, elapsed time, and output file size.

### `wget`

Allowed form:

- `wget -O <approved-path> <http-url>`

Apply the same URL and output path rules as `curl`.

### `chmod`

Allowed form:

- `chmod +x <approved-path>`

Rules:

- Only allow adding executable permission.
- Refuse recursive mode.
- Refuse numeric or broad modes in the first version.
- Target must be a regular file in an approved write directory.

### `mkdir`

Allowed form:

- `mkdir -p <approved-directory>`

Rules:

- Directory must be inside an approved write directory.
- Refuse creation of sensitive or credential-like paths.

### `file`

Allowed form:

- `file <approved-readable-path>`

Rules:

- Read-only inspection only.
- Target must be in an approved read location.

### `which`

Allowed form:

- `which <command-name>`

Rules:

- Command name must be a simple executable name, not a path.

### `systemctl --user`

Allowed forms:

- `systemctl --user daemon-reload`
- `systemctl --user enable <unit>`
- `systemctl --user disable <unit>`
- `systemctl --user start <unit>`
- `systemctl --user stop <unit>`
- `systemctl --user status <unit>`

Rules:

- Only user-level systemd is allowed.
- System-level `systemctl` is refused.
- Unit names must be simple `.service` units, not paths.

## Clash Verge Flow

When the user asks DeckMind to download Clash Verge and a URL is known or
provided, the intended flow is:

1. Use `run_command` with `curl` and `confirm=false` to preview the download.
2. After user approval, run the download command.
3. Validate the downloaded file exists and has a plausible non-trivial size.
4. Use `run_command` with `chmod +x` and the same approval session when
   possible.
5. Optionally use `file` to inspect the result.
6. Report the final path and whether it is executable.

This turns the current "write a script and ask the user to run it" workflow
into "DeckMind runs the validated command after permission".

## Prompt Updates

Update `prompts/system_prompt.txt` to explain:

- Use dedicated tools first.
- Use `run_command` for small user-level command automation when no dedicated
  tool exists.
- Never ask the user to manually type a command that `run_command` can safely
  execute after permission.
- Never use `run_command` for credentials, arbitrary shell, sudo, pacman, or
  system-level changes.

## Testing

Add focused tests or verification scripts for:

- Allowed `curl -L -o ~/Downloads/name.AppImage <url>` dry-run validation.
- Refusal of shell metacharacters or compound commands.
- Refusal of writes outside approved directories.
- Refusal of sensitive path fragments.
- Refusal of `chmod -R` and numeric chmod modes.
- Refusal of system-level `systemctl`.
- Successful execution path with a harmless local command such as `which sh`
  or `mkdir -p ~/.deckmind/test-command-runner`.

If the project does not yet have a formal test harness, add lightweight unit
tests around the command validator first. The validator should be separated
from subprocess execution so most safety behavior is testable without running
external commands.

## Future Scope

The first implementation should keep the allowlist intentionally small. Future
commands can be added only when there is a concrete user workflow and a clear
validator for that command.
