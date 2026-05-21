# Capability Existing Tools Migration Design

## Scope

This phase extends the first Capability Registry implementation by registering a small set of existing DeckMind tools as capabilities:

- `audio.get_volume`
- `audio.set_volume`
- `steam.launch_game`
- `steam.close_game`

The goal is to make the registry useful for common system actions without rewriting the existing tool implementations.

This phase also improves `run_capability` permission handling so the Executor can use capability metadata instead of treating every `run_capability` call as one fixed risk level.

## Non-Goals

- Do not add default audio output device management.
- Do not add per-application volume controls.
- Do not migrate package, file, pacman, macro, Notion, or update tools.
- Do not remove the existing direct tool entries.
- Do not introduce external capability packs.
- Do not move Steam or volume implementation code out of `tools/`.

## Approach

Use adapter modules under `runtime.capabilities`.

`runtime/capabilities/audio.py` registers audio capabilities and delegates to `tools.system_tool`.

`runtime/capabilities/steam.py` registers Steam capabilities and delegates to `tools.steam_tool`.

The existing tool functions remain the source of behavior. Capability handlers are thin wrappers that provide stable capability names, metadata, argument schemas, risk levels, and confirmation semantics.

## Capability Metadata

### `audio.get_volume`

- Risk: `safe`
- Confirmation: not required
- Arguments: none
- Handler: delegates to `tools.system_tool.get_volume`

### `audio.set_volume`

- Risk: `side_effect`
- Confirmation: required
- Arguments:
  - `percent`: integer, 0 to 100
- Handler: delegates to `tools.system_tool.set_volume`

### `steam.launch_game`

- Risk: `side_effect`
- Confirmation: required
- Arguments:
  - `game_name`: string
- Handler: delegates to `tools.steam_tool.launch_game`

### `steam.close_game`

- Risk: `side_effect`
- Confirmation: required
- Arguments:
  - `process_name`: string
- Handler: delegates to `tools.steam_tool.close_game`

## Dynamic Risk Handling

The first implementation registered `run_capability` as `destructive` in the Executor. That works for dry-run compatibility, but it cannot express capability-level risk.

This phase changes Executor risk handling for `run_capability`:

1. If the called capability does not exist, `run_capability` executes without a permission prompt and returns `unknown_capability`.
2. If the capability risk is `safe`, `run_capability` executes without a permission prompt.
3. If the capability risk is `side_effect` and `confirm=false`, `run_capability` executes without a permission prompt and returns a preview.
4. If the capability risk is `side_effect` and `confirm=true`, the Executor requests user permission before executing.
5. If a future capability uses `destructive`, `confirm=false` remains a no-prompt preview and `confirm=true` requires permission.

The existing direct tools keep their current risk classifications. This avoids changing current user-facing behavior while allowing the capability path to become more precise.

## Registry Loading

`runtime.capabilities.registry` will register built-in capabilities from:

- `runtime.capabilities.bluetooth`
- `runtime.capabilities.audio`
- `runtime.capabilities.steam`

Duplicate names continue to raise `ValueError`.

## Tool Behavior

`tools.capability_tool.run_capability` keeps the same public signature:

```python
run_capability(name: str, args: dict[str, Any] | None = None, confirm: bool = False)
```

Non-safe capabilities still return a preview when `confirm=false`. The preview includes:

- capability name
- description
- risk
- confirmation requirement
- provided arguments

When `confirm=true`, `run_capability` passes arguments to the capability handler. If the handler accepts a `confirm` parameter, it receives the `confirm` value. Existing adapter handlers for audio and Steam do not need a `confirm` parameter because permission is enforced by `run_capability` plus the Executor before delegation.

## Prompt Update

The system prompt should tell the Agent:

- Use `run_capability` for registered audio and Steam game actions.
- Use `audio.get_volume` and `audio.set_volume` for volume.
- Use `steam.launch_game` and `steam.close_game` for game launch/close.
- Continue not falling back to shell for missing capabilities.

The direct tools remain available, but capability should be preferred for these registered actions.

## Testing

Add focused tests for:

1. Registry lists the new audio and Steam capabilities.
2. `audio.get_volume` executes as a safe capability without permission.
3. `audio.set_volume` returns dry-run preview when `confirm=false`.
4. `steam.launch_game` returns dry-run preview when `confirm=false`.
5. `run_capability(confirm=true)` asks permission when the target capability risk is `side_effect`.
6. Unknown capabilities still return structured `unknown_capability` without permission.
7. Existing direct tools remain registered.

Existing Bluetooth tests should continue to pass.

## Manual Verification

On a Steam Deck or Linux environment with the relevant backends:

1. Ask for current volume and confirm the Agent uses `audio.get_volume`.
2. Ask to set volume and confirm it previews first, then asks permission before executing.
3. Ask to launch a known Steam game and confirm it previews first, then asks permission before executing.
4. Ask to close a known game/process and confirm the same permission flow.

If real Steam or audio backends are unavailable, rely on unit tests and existing mock paths for implementation verification.
