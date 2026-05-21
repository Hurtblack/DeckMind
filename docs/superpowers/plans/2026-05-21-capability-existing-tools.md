# Capability Existing Tools Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Register existing audio and Steam tools as capabilities, and make `run_capability` permission handling use capability metadata.

**Architecture:** Add focused adapter modules under `runtime.capabilities` that delegate to existing `tools.system_tool` and `tools.steam_tool` implementations. Extend the registry to load those adapters, then teach the Executor to classify `run_capability` calls from the target capability metadata instead of a fixed risk set entry.

**Tech Stack:** Python 3.11+, `unittest`, `unittest.mock.patch`, existing `Capability`, `CapabilityRegistry`, `ToolSpec`, and Executor permission provider flow.

---

## File Structure

- Create: `runtime/capabilities/audio.py`
  - Registers `audio.get_volume` and `audio.set_volume`, delegating to `tools.system_tool`.
- Create: `runtime/capabilities/steam.py`
  - Registers `steam.launch_game` and `steam.close_game`, delegating to `tools.steam_tool`.
- Modify: `runtime/capabilities/registry.py`
  - Imports and registers `audio.capabilities()` and `steam.capabilities()` in addition to Bluetooth.
- Modify: `runtime/executor.py`
  - Adds dynamic risk classification for `run_capability` based on `runtime.capabilities.registry.get_capability`.
  - Removes `run_capability` from the fixed `RISK_DESTRUCTIVE` set.
- Modify: `prompts/system_prompt.txt`
  - Tells the Agent to prefer capabilities for audio volume and Steam game launch/close.
- Modify: `tests/test_capability_registry.py`
  - Adds registry and tool-level tests for audio and Steam capabilities.
- Modify: `tests/test_runtime_interfaces.py`
  - Adds dynamic permission tests for safe, side-effect preview, side-effect confirmed, and unknown capability paths.

## Task 1: Add Registry And Tool Tests For Existing Tool Capabilities

**Files:**
- Modify: `tests/test_capability_registry.py`
- Create later: `runtime/capabilities/audio.py`
- Create later: `runtime/capabilities/steam.py`
- Modify later: `runtime/capabilities/registry.py`

- [ ] **Step 1: Add failing registry metadata tests**

Append these methods to `CapabilityRegistryTests` in `tests/test_capability_registry.py`:

```python
    def test_builtin_audio_capabilities_are_listed(self) -> None:
        names = {item["name"] for item in list_capabilities()}

        self.assertIn("audio.get_volume", names)
        self.assertIn("audio.set_volume", names)

    def test_builtin_steam_capabilities_are_listed(self) -> None:
        names = {item["name"] for item in list_capabilities()}

        self.assertIn("steam.launch_game", names)
        self.assertIn("steam.close_game", names)

    def test_existing_tool_capability_metadata(self) -> None:
        audio_set = get_capability("audio.set_volume")
        steam_launch = get_capability("steam.launch_game")

        self.assertIsNotNone(audio_set)
        self.assertIsNotNone(steam_launch)
        assert audio_set is not None
        assert steam_launch is not None

        self.assertEqual(audio_set.risk, "side_effect")
        self.assertTrue(audio_set.confirm_required)
        self.assertEqual(audio_set.args_schema["required"], ["percent"])
        self.assertEqual(steam_launch.risk, "side_effect")
        self.assertTrue(steam_launch.confirm_required)
        self.assertEqual(steam_launch.args_schema["required"], ["game_name"])
```

- [ ] **Step 2: Add failing tool behavior tests**

Append these methods to `CapabilityToolTests` in `tests/test_capability_registry.py`:

```python
    async def test_audio_get_volume_safe_capability_executes(self) -> None:
        from unittest.mock import patch

        from tools.capability_tool import run_capability

        async def fake_get_volume() -> dict[str, object]:
            return {"ok": True, "percent": 42, "backend": "fake"}

        with patch("tools.system_tool.get_volume", fake_get_volume):
            result = await run_capability("audio.get_volume")

        self.assertEqual(result, {"ok": True, "percent": 42, "backend": "fake"})

    async def test_audio_set_volume_without_confirm_returns_dry_run(self) -> None:
        from tools.capability_tool import run_capability

        result = await run_capability(
            "audio.set_volume",
            {"percent": 35},
            confirm=False,
        )

        self.assertTrue(result["ok"])
        self.assertTrue(result["dry_run"])
        self.assertEqual(result["capability"], "audio.set_volume")
        self.assertEqual(result["args"], {"percent": 35})

    async def test_steam_launch_game_without_confirm_returns_dry_run(self) -> None:
        from tools.capability_tool import run_capability

        result = await run_capability(
            "steam.launch_game",
            {"game_name": "hades"},
            confirm=False,
        )

        self.assertTrue(result["ok"])
        self.assertTrue(result["dry_run"])
        self.assertEqual(result["capability"], "steam.launch_game")
        self.assertEqual(result["args"], {"game_name": "hades"})

    async def test_steam_close_game_without_confirm_returns_dry_run(self) -> None:
        from tools.capability_tool import run_capability

        result = await run_capability(
            "steam.close_game",
            {"process_name": "Hades"},
            confirm=False,
        )

        self.assertTrue(result["ok"])
        self.assertTrue(result["dry_run"])
        self.assertEqual(result["capability"], "steam.close_game")
        self.assertEqual(result["args"], {"process_name": "Hades"})
```

- [ ] **Step 3: Run test to verify it fails**

Run:

```bash
python3 -m unittest tests.test_capability_registry -v
```

Expected: FAIL because `audio.*` and `steam.*` capabilities are not registered yet.

- [ ] **Step 4: Commit failing tests**

```bash
git add tests/test_capability_registry.py
git commit -m "添加现有工具 capability 测试"
```

## Task 2: Add Audio And Steam Capability Adapters

**Files:**
- Create: `runtime/capabilities/audio.py`
- Create: `runtime/capabilities/steam.py`
- Modify: `runtime/capabilities/registry.py`

- [ ] **Step 1: Create audio adapter module**

Create `runtime/capabilities/audio.py`:

```python
"""Audio capabilities backed by existing system tools."""

from __future__ import annotations

from typing import Any

from tools import system_tool

from .types import Capability


async def get_volume() -> dict[str, Any]:
    return await system_tool.get_volume()


async def set_volume(percent: int) -> dict[str, Any]:
    return await system_tool.set_volume(percent)


def capabilities() -> list[Capability]:
    return [
        Capability(
            name="audio.get_volume",
            description="Read current audio output volume as a percent.",
            args_schema={"type": "object", "properties": {}},
            risk="safe",
            confirm_required=False,
            handler=get_volume,
        ),
        Capability(
            name="audio.set_volume",
            description="Set audio output volume percentage.",
            args_schema={
                "type": "object",
                "properties": {
                    "percent": {
                        "type": "integer",
                        "minimum": 0,
                        "maximum": 100,
                    },
                },
                "required": ["percent"],
            },
            risk="side_effect",
            confirm_required=True,
            handler=set_volume,
        ),
    ]
```

- [ ] **Step 2: Create Steam adapter module**

Create `runtime/capabilities/steam.py`:

```python
"""Steam capabilities backed by existing Steam tools."""

from __future__ import annotations

from typing import Any

from tools import steam_tool

from .types import Capability


async def launch_game(game_name: str) -> dict[str, Any]:
    return await steam_tool.launch_game(game_name)


async def close_game(process_name: str) -> dict[str, Any]:
    return await steam_tool.close_game(process_name)


def capabilities() -> list[Capability]:
    return [
        Capability(
            name="steam.launch_game",
            description="Launch a Steam game by friendly name.",
            args_schema={
                "type": "object",
                "properties": {"game_name": {"type": "string"}},
                "required": ["game_name"],
            },
            risk="side_effect",
            confirm_required=True,
            handler=launch_game,
        ),
        Capability(
            name="steam.close_game",
            description="Close a running game process by process name.",
            args_schema={
                "type": "object",
                "properties": {"process_name": {"type": "string"}},
                "required": ["process_name"],
            },
            risk="side_effect",
            confirm_required=True,
            handler=close_game,
        ),
    ]
```

- [ ] **Step 3: Register audio and Steam capabilities**

Modify `runtime/capabilities/registry.py` imports:

```python
from . import audio, bluetooth, steam
```

Replace the built-in registration loop with:

```python
for module in (bluetooth, audio, steam):
    for capability in module.capabilities():
        _REGISTRY.register(capability)
```

- [ ] **Step 4: Run registry and tool tests**

Run:

```bash
python3 -m unittest tests.test_capability_registry -v
```

Expected: PASS.

- [ ] **Step 5: Run Bluetooth tests to catch registry import regressions**

Run:

```bash
python3 -m unittest tests.test_bluetooth_capability -v
```

Expected: PASS.

- [ ] **Step 6: Commit adapter implementation**

```bash
git add runtime/capabilities/audio.py runtime/capabilities/steam.py runtime/capabilities/registry.py tests/test_capability_registry.py
git commit -m "注册音量和 Steam capability"
```

## Task 3: Add Dynamic Executor Risk Tests

**Files:**
- Modify: `tests/test_runtime_interfaces.py`
- Modify later: `runtime/executor.py`

- [ ] **Step 1: Add failing dynamic risk tests**

Append these methods to `CapabilityExecutorRiskTests` in `tests/test_runtime_interfaces.py`:

```python
    async def test_run_safe_capability_executes_without_permission(self) -> None:
        provider = RecordingPermissionProvider("deny")
        executor = Executor(permission_provider=provider)

        with patch(
            "tools.system_tool.get_volume",
            return_value={"ok": True, "percent": 25, "backend": "fake"},
        ):
            result = await executor.run("run_capability", {"name": "audio.get_volume"})

        self.assertEqual(result, {"ok": True, "percent": 25, "backend": "fake"})
        self.assertEqual(provider.requests, [])

    async def test_run_side_effect_capability_confirm_true_requests_permission(self) -> None:
        provider = RecordingPermissionProvider("allow")
        executor = Executor(permission_provider=provider)

        with patch(
            "tools.system_tool.set_volume",
            return_value={"ok": True, "percent": 55, "backend": "fake", "verified": True},
        ):
            result = await executor.run(
                "run_capability",
                {
                    "name": "audio.set_volume",
                    "args": {"percent": 55},
                    "confirm": True,
                },
            )

        self.assertTrue(result["ok"])
        self.assertEqual(result["percent"], 55)
        self.assertEqual(len(provider.requests), 1)
        self.assertEqual(provider.requests[0].name, "run_capability")
        self.assertEqual(provider.requests[0].risk, "side_effect")

    async def test_run_side_effect_capability_confirm_true_denial_skips_execution(self) -> None:
        provider = RecordingPermissionProvider("deny")
        executor = Executor(permission_provider=provider)

        with patch("tools.system_tool.set_volume") as set_volume:
            result = await executor.run(
                "run_capability",
                {
                    "name": "audio.set_volume",
                    "args": {"percent": 55},
                    "confirm": True,
                },
            )

        self.assertFalse(result["ok"])
        self.assertTrue(result["denied"])
        set_volume.assert_not_called()
        self.assertEqual(len(provider.requests), 1)

    async def test_run_unknown_capability_does_not_request_permission(self) -> None:
        provider = RecordingPermissionProvider("deny")
        executor = Executor(permission_provider=provider)

        result = await executor.run(
            "run_capability",
            {"name": "wifi.switch_network", "confirm": True},
        )

        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "unknown_capability")
        self.assertEqual(provider.requests, [])
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
python3 -m unittest tests.test_runtime_interfaces.CapabilityExecutorRiskTests -v
```

Expected: FAIL because `run_capability` is still classified by the fixed destructive tool path.

- [ ] **Step 3: Commit failing tests**

```bash
git add tests/test_runtime_interfaces.py
git commit -m "添加 capability 动态权限测试"
```

## Task 4: Implement Dynamic Executor Risk Classification

**Files:**
- Modify: `runtime/executor.py`

- [ ] **Step 1: Import capability metadata lookup**

In `runtime/executor.py`, add this helper near `_risk_of`:

```python
def _capability_risk(arguments: dict[str, Any]) -> str:
    """Return risk for run_capability using target capability metadata."""
    name = arguments.get("name")
    if not isinstance(name, str):
        return "safe"

    from runtime.capabilities.registry import get_capability

    capability = get_capability(name)
    if capability is None:
        return "safe"
    return capability.risk
```

- [ ] **Step 2: Remove fixed destructive classification**

In `runtime/executor.py`, remove `"run_capability"` from `RISK_DESTRUCTIVE`.

- [ ] **Step 3: Apply dynamic risk before permission gate**

In `Executor.run`, immediately after:

```python
risk = _risk_of(name)
```

add:

```python
        if name == "run_capability":
            risk = _capability_risk(arguments)
```

- [ ] **Step 4: Preserve dry-run no-prompt behavior**

Keep the existing destructive branch unchanged:

```python
        elif risk == "destructive":
            confirm = bool(arguments.get("confirm", False))
            if confirm:
                ...
```

This means future destructive capabilities still preview without prompting when `confirm=false`.

The existing side-effect branch will prompt for `run_capability(confirm=true)` because side-effect tools do not have dry-run awareness. To preserve no-prompt preview for side-effect capabilities, add this at the top of the `elif risk == "side_effect":` branch:

```python
            if name == "run_capability" and not bool(arguments.get("confirm", False)):
                pass
            elif name not in self._allow_all:
                decision = await self._request_permission(
                    name=name,
                    arguments=arguments,
                    risk=risk,
                    message=(
                        f"    ⚠ side-effect: {name}({arguments})  "
                        f"[y=允许 / n=拒绝 / a=本会话此工具全允许] > "
                    ),
                )
                if decision == "allow_all":
                    self._allow_all.add(name)
                elif decision != "allow":
                    result = {"ok": False, "denied": True,
                              "reason": f"user rejected side-effect call to {name}"}
                    await self._emit({"type": "tool_result", "name": name, "result": result})
                    return result
```

Do not keep the old unguarded `elif risk == "side_effect"` body in addition to this replacement.

- [ ] **Step 5: Run dynamic risk tests**

Run:

```bash
python3 -m unittest tests.test_runtime_interfaces.CapabilityExecutorRiskTests -v
```

Expected: PASS.

- [ ] **Step 6: Run broader focused tests**

Run:

```bash
python3 -m unittest tests.test_capability_registry tests.test_bluetooth_capability tests.test_runtime_interfaces -v
```

Expected: PASS.

- [ ] **Step 7: Commit dynamic risk implementation**

```bash
git add runtime/executor.py tests/test_runtime_interfaces.py
git commit -m "按 capability 元数据判断权限风险"
```

## Task 5: Update Prompt For Audio And Steam Capabilities

**Files:**
- Modify: `prompts/system_prompt.txt`

- [ ] **Step 1: Update capability prompt text**

In `prompts/system_prompt.txt`, find the existing `- Capabilities:` section and update its final capability examples to:

```text
             For Bluetooth device listing, connecting, or disconnecting,
             use run_capability with bluetooth.get_devices,
             bluetooth.connect, or bluetooth.disconnect.

             For audio volume, use run_capability with audio.get_volume
             or audio.set_volume. For Steam game launch or close, use
             run_capability with steam.launch_game or steam.close_game.)
```

- [ ] **Step 2: Run prompt smoke tests**

Run:

```bash
python3 -m unittest tests.test_runtime_interfaces tests.test_capability_registry -v
```

Expected: PASS.

- [ ] **Step 3: Commit prompt update**

```bash
git add prompts/system_prompt.txt
git commit -m "提示词优先使用音量和 Steam capability"
```

## Task 6: Final Verification

**Files:**
- No new files.

- [ ] **Step 1: Run all focused capability tests**

Run:

```bash
python3 -m unittest tests.test_capability_registry tests.test_bluetooth_capability tests.test_runtime_interfaces -v
```

Expected: PASS.

- [ ] **Step 2: Run all unit tests**

Run:

```bash
python3 -m unittest discover -v
```

Expected: Existing suite may still fail on `tests.test_decky_plugin_runtime_client.DeckyPluginRuntimeSessionTests.test_each_turn_uses_its_own_permission_provider`, which was already failing before this phase. Any new failure in capability, executor, audio, or Steam tests must be fixed before completion.

- [ ] **Step 3: Inspect git status**

Run:

```bash
git status --short
```

Expected: no uncommitted changes.

- [ ] **Step 4: Manual verification note**

If running on a Steam Deck or Linux environment with working audio and Steam:

```text
Manual verification:
- audio.get_volume: pass/fail + note
- audio.set_volume: pass/fail + note
- steam.launch_game: pass/fail + note
- steam.close_game: pass/fail + note
```

If not running on a suitable environment, state that manual audio/Steam capability verification was not run.

## Self-Review Checklist

- Spec coverage:
  - `audio.get_volume`: Tasks 1-2, 6.
  - `audio.set_volume`: Tasks 1-2, 3-4, 6.
  - `steam.launch_game`: Tasks 1-2, 6.
  - `steam.close_game`: Tasks 1-2, 6.
  - Dynamic `run_capability` risk: Tasks 3-4.
  - Prompt update: Task 5.
  - Existing direct tools preserved: no direct tool entries are removed.
- Placeholder scan:
  - No placeholder markers or unspecified implementation steps remain.
- Type consistency:
  - Capability names match the design exactly.
  - `run_capability(name, args=None, confirm=False)` signature remains unchanged.
  - Adapter handler argument names match existing tool argument names.
