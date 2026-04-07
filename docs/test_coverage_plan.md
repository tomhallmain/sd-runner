# Test Coverage Plan

## Current State

Four test files exist under `tests/`, all using `unittest.TestCase`. There is no
`conftest.py`, `pytest.ini`, or shared fixture infrastructure.

| File | Module Under Test | Coverage |
|---|---|---|
| `test_cache.py` | `utils.pickleable_cache.SizeAwarePicklableCache` | Size-aware eviction, LRU eviction |
| `test_get_random_words.py` | `sd_runner.concepts.Concepts.get_random_words` | Range, blacklist filtering, multiplier |
| `test_blacklist.py` | `sd_runner.blacklist.BlacklistItem`, `Blacklist` | Regex, word boundaries, serialization, first-run defaults |
| `test_adapter_sorting.py` | `sd_runner.adapter_sorting` | Recency sort, jitter, edge cases |

Everything else is untested. The sections below rank the gaps by criticality.

---

## Priority 1 — Unit Tests (Core Logic, No I/O or Qt)

These cover the most load-bearing, pure-logic paths that have no external
dependencies and are straightforward to test deterministically.

### 1.1 `sd_runner/resolution.py` — `Resolution`

Resolution selection is called on every generation run and feeds directly into
model output dimensions. Bugs here silently produce wrong-size images.

**Gaps to cover:**

| Method / Behaviour | Notes |
|---|---|
| `Resolution.get_resolution(tag, arch, group)` | All tag names (`square`, `portrait1–3`, `landscape1–3`) × all `ArchitectureType` values × both `ResolutionGroup` values; confirm W×H pairs are correct |
| `Resolution.get_resolutions(tag_str, ...)` | Comma-separated tag strings; `*`-suffix random-skip flag sets `random_skip=True`; duplicate tags |
| `Resolution.convert_for_model_type(arch)` | Cross-architecture conversion preserves aspect ratio; portrait stays portrait |
| `Resolution.find_matching_aspect_ratio_resolution(w, h, ...)` | Exact match, within-tolerance match, no-match fallback |
| `Resolution.get_tolerance_range(...)` | Boundary values, step size |
| `Resolution.should_be_randomly_skipped(chance)` | `chance=0` never skips; `chance=1` always skips; probabilistic middle |
| `Resolution.get_closest(w, h, ...)` | Nearest resolution returned; tie-breaking is stable |
| `aspect_ratio()`, `is_xl()`, `is_illustrious()` | Correct classification for known dimensions |
| `invert()` | Width and height swap; aspect ratio inverts |

### 1.2 `sd_runner/concepts.py` — `ConceptConfiguration` and `ConceptsFile`

These classes control how many concepts are sampled per category and manage
file-level read/write. `ConceptConfiguration` is serialised into user config.

**Gaps to cover:**

| Method / Behaviour | Notes |
|---|---|
| `ConceptConfiguration.from_tuple` | 2-tuple, 3-tuple (specific_chance), and kwargs override paths |
| `ConceptConfiguration.from_dict` / `to_dict` | Round-trip equality; unknown keys ignored |
| `ConceptConfiguration.get_adjusted_range(multiplier)` | `multiplier=0` returns `(0,0)`; `multiplier=1` identity; fractional scaling; ensures non-zero when original non-zero |
| `ConceptConfiguration.from_subcategory_list` | Weights sum to expected value; entries below threshold clipped |
| `weighted_sample_without_replacement(pop, weights, k)` | `k > len(pop)` raises or clamps; zero-weight items never selected; distribution over many trials |
| `sample(l, low, high)` | `low==high`, `low > high`, empty list, dict input |
| `ConceptsFile.load()` | Comment stripping (`#`), blank-line skipping, UTF-8 special chars |
| `ConceptsFile.save()` | Round-trip: load → modify → save → reload yields same concepts |
| `ConceptsFile.add_concept(concept)` | Duplicate rejected; new concept persisted after save |
| `Concepts.load(filename)` | Relative path resolution via `CONCEPTS_DIR`; missing file returns empty list without crash |

### 1.3 `sd_runner/prompter.py` — Prompt syntax parsing

The choice/expansion syntax (`[[a,b]]`, `$var`, `$$var`) is the primary feature
users interact with. Edge-case parsing bugs cause silent wrong output.

**Gaps to cover:**

| Method / Behaviour | Notes |
|---|---|
| `Prompter.apply_choices(text)` | `[[a,b,c]]` selects one option; weighted `[[a:2,b]]` correct distribution; nested `[[[a,b],[c,d]]]`; malformed unclosed bracket gracefully handled |
| `Prompter.apply_expansions(text, ...)` | `$var` expands and overwrites UI field; `$$var` expands only at generation time; unknown var left unchanged |
| `Prompter.emphasize(words, chance)` | `chance=0` no emphasis; `chance=1` all words emphasised; parenthesis wrapping is correct |
| Choice weight distribution | Over N trials, weighted options appear with expected frequencies (statistical test with generous tolerance) |
| Nested choice set | Inner choices resolved before outer; result always valid |

### 1.4 `utils/globals.py` — Enums

Enum helper methods are used throughout the codebase for UI display and serialisation.

**Gaps to cover:**

| Method / Behaviour | Notes |
|---|---|
| `PromptMode.display()` | All values return a non-empty string |
| `PromptMode.get(name)` | Case-insensitive lookup; unknown name returns `None` or raises consistently |
| `PromptMode.is_nsfw()` | `NSFW`, `NSFL` return `True`; all others `False` |
| `PromptMode.display_values()` | Returned list length matches enum member count |
| Same pattern for `BlacklistMode`, `BlacklistPromptMode`, `ModelBlacklistMode`, `ArchitectureType`, `ResolutionGroup`, `WorkflowType` | |

### 1.5 `sd_runner/gen_config.py` — `GenConfig`

`GenConfig` aggregates everything passed to the image generator. Bugs in its
helpers cause runs to use wrong architectures or skip validation silently.

**Gaps to cover:**

| Method / Behaviour | Notes |
|---|---|
| `is_xl()` | True only for SDXL/Illustrious architectures |
| `architecture_type()` | Correct `ArchitectureType` derived from model list |
| `prompts_match(prior_config)` | Same positive+negative → True; any difference → False; `None` prior → False |
| `validate()` | Missing required field returns `False`; valid config returns `True` |
| `is_redo_prompt()` | Detects redo markers in prompt string |
| `get_prompt_mode()` | Returns correct `PromptMode` from config state |

### 1.6 `utils/encryptor.py`

The blacklist is encrypted at rest. A regression here makes the default
blacklist unreadable for all new users.

**Gaps to cover:**

| Method / Behaviour | Notes |
|---|---|
| Encrypt → decrypt round-trip | Plaintext bytes survive a full cycle |
| Different keys produce different ciphertext | Ensures key material is used |
| Decrypting with wrong key raises / returns None | No silent data corruption |
| Empty plaintext | Edge case |

### 1.7 `utils/translations.py`

Broken translation lookup silently falls back to raw keys in the UI; harder
to notice and report.

**Gaps to cover:**

| Method / Behaviour | Notes |
|---|---|
| Known key in active locale returns translated string | |
| Unknown key falls back to the key itself (or English) without raising | |
| Locale switch between supported languages (`en`, `de`, `ja`, etc.) | |
| Unsupported locale falls back to English | |

---

## Priority 2 — Integration Tests (Multi-module, File System)

These tests cover interactions between modules and require temporary files.
They exercise real file I/O but do not need a running Qt application.

### 2.1 Concepts + Blacklist full pipeline

The interaction between `Concepts` sampling and `Blacklist.filter_concepts` is
the most used runtime path.

- Load a minimal real concept file from `concepts/` (e.g. `animals.txt`).
- Configure a `Blacklist` with several items.
- Call `Concepts.get_concept_map(category_states)` and then `get_random_words`.
- Assert blacklisted strings never appear in output over many iterations.
- Assert the count of returned words stays within the configured `(low, high)` range.
- Assert `filter_concepts` correctly splits into whitelist and filtered dicts for
  each `BlacklistMode` value.

### 2.2 Full prompt generation per `PromptMode`

- Instantiate a `Prompter` with a real `PrompterConfiguration`.
- Call `generate_prompt()` for every `PromptMode` value.
- Assert: non-empty positive string returned; prompt does not contain raw `$var`
  unexpanded; choice sets `[[...]]` are fully resolved; no unmatched brackets.
- For `FIXED` mode: assert positive equals the literal string provided.
- For `NSFW`/`NSFL` modes: assert the appropriate concept categories are consulted
  (via spy/mock on `Concepts.load`).

### 2.3 `ConceptsFile` load/save round-trip on disk

- Write a temp `.txt` file with known concepts and comment lines.
- Load with `ConceptsFile`, call `add_concept`, save, reload.
- Assert new concept is present; original concepts unchanged; comment lines stripped.
- Assert saving with zero-length list clears the file cleanly.

### 2.4 `SizeAwarePicklableCache` persistence across process boundary

Extend the existing `test_cache.py` with:

- Save cache to a temp file; reload via `load_or_create`; verify all items intact.
- Simulate the encrypted-blacklist read path: store an encrypted blob, reload,
  assert the same blob is returned.

### 2.5 `GenConfig` + `Resolution` workflow preparation

- Build a minimal valid `GenConfig` with a model and a resolution tag string.
- Call `prepare()` and assert `resolutions` list is populated with `Resolution`
  objects matching the tag.
- Test architecture-specific resolution scaling: SD 1.5 model → SD 1.5 dimensions;
  SDXL model → XL dimensions.
- Test `random_skip` flag from `*`-suffixed tag causes some resolutions to be
  skipped across repeated `should_be_randomly_skipped` calls.

### 2.6 `AdapterSorting` + real directory structure

Extend the existing `test_adapter_sorting.py`:

- Use actual `.safetensors` file creation in `tempfile` directories.
- Verify that a recency list containing a filename that no longer exists on disk
  does not crash the sort.
- Verify that mixed-architecture subdirectory structures (e.g. `Lora/SD1.5/`,
  `Lora/Flux/`) are handled correctly.

---

## Priority 3 — UI Tests (pytest-qt)

These require `pip install pytest-qt` and a display (or offscreen Qt backend via
`QT_QPA_PLATFORM=offscreen`). They should run in CI with `--co -q` to skip
when Qt is unavailable, controlled by a custom pytest marker.

Add to `conftest.py`:
```python
# conftest.py
import pytest

def pytest_configure(config):
    config.addinivalue_line("markers", "qt: requires PySide6 and pytest-qt")
```

And to `pytest.ini` (to be created):
```ini
[pytest]
testpaths = tests
markers =
    qt: requires PySide6 and pytest-qt (deselect with '-m "not qt"')
```

### 3.1 Main application window smoke test

```python
@pytest.mark.qt
def test_app_window_opens(qtbot):
    from ui_qt.app_window.app_window import AppWindow
    window = AppWindow()
    qtbot.addWidget(window)
    assert window.isVisible()  # or window.show() first
```

Extend to check:
- Key widget areas are present (prompt field, run button, mode selector).
- Window title is set.
- Window does not crash on `close()`.

### 3.2 Concept Editor window — CRUD operations

```python
@pytest.mark.qt
def test_concept_editor_add_delete(qtbot, tmp_path):
    # Point concepts dir at tmp_path with a test file
    ...
    from ui_qt.prompts.concept_editor_window import ConceptEditorWindow
    win = ConceptEditorWindow(...)
    qtbot.addWidget(win)
    # Add a concept via the UI
    qtbot.keyClicks(win.input_field, "test_concept")
    qtbot.mouseClick(win.add_button, Qt.LeftButton)
    assert "test_concept" in win.get_current_concepts()
    # Delete it
    ...
    assert "test_concept" not in win.get_current_concepts()
```

### 3.3 Blacklist window — add, toggle, remove

- Open `BlacklistWindow` (requires password bypass or fixture that skips auth).
- Add a new blacklist item via the UI fields.
- Toggle its enabled state.
- Verify `Blacklist.TAG_BLACKLIST` reflects the change.
- Remove the item; verify it is no longer in the list.

### 3.4 Prompt configuration window — load and apply preset

- Open `PromptConfigWindow`.
- Set a prompt mode via the mode dropdown.
- Confirm the prompter configuration object reflects the selected mode.
- Apply a preset; confirm the prompt text field updates.

### 3.5 Password dialog — correct and incorrect password

- Instantiate `PasswordDialog` with a known hash.
- Enter the correct password via `qtbot.keyClicks`; accept the dialog.
- Assert `dialog.result()` is `QDialog.Accepted`.
- Repeat with wrong password; assert dialog stays open or returns `Rejected`.

### 3.6 Models window — selection changes propagate

- Open `ModelsWindow`.
- Simulate selecting a model from the list.
- Confirm the selection is reflected in the associated `GenConfig` or signal.

---

## Priority 4 — Missing Test Infrastructure

Before writing the above tests, the following scaffolding should be added.

### 4.0 Cache and `app_info_cache` isolation

`SizeAwarePicklableCache` and `AppInfoCache` / `AppInfoCacheQt` persist state to
disk and hold class-level singletons, meaning tests that touch them can
contaminate each other or corrupt real user data on a developer machine.

A per-test isolation strategy (temp directory override + class-state reset) has
already been solved in a **separate reference project** that faced the same
problem. That strategy will be ported here once the reference project is
available. Until then:

- Tests that exercise `SizeAwarePicklableCache` directly (see existing
  `test_cache.py`) are acceptable because they construct isolated instances.
- **Do not** write new tests that call into `AppInfoCache`, `AppInfoCacheQt`,
  or any module that imports them at module level, until the isolation fixtures
  are in place.
- Mark any such tests `@pytest.mark.skip(reason="requires cache isolation fixtures")`
  as placeholders if needed.

### 4.1 `conftest.py`

```python
import os, tempfile, shutil, pytest
from sd_runner.blacklist import Blacklist

@pytest.fixture(autouse=True)
def reset_blacklist():
    """Restore Blacklist class state between tests."""
    original = list(Blacklist.TAG_BLACKLIST)
    yield
    Blacklist.TAG_BLACKLIST = original

@pytest.fixture
def tmp_concepts_dir(tmp_path):
    """Temp directory pre-populated with minimal concept files."""
    (tmp_path / "animals.txt").write_text("cat\ndog\n# comment\n")
    (tmp_path / "sfw_concepts.txt").write_text("abstract\nminimalism\n")
    yield tmp_path

@pytest.fixture
def concepts_dir_override(tmp_concepts_dir, monkeypatch):
    """Override the global CONCEPTS_DIR used by Concepts.load."""
    import sd_runner.concepts as concepts_module
    monkeypatch.setattr(concepts_module.Concepts, "CONCEPTS_DIR", str(tmp_concepts_dir))
    yield tmp_concepts_dir
```

### 4.2 `pytest.ini`

```ini
[pytest]
testpaths = tests
addopts = -v --tb=short
markers =
    qt: requires PySide6 and pytest-qt (deselect with '-m "not qt"')
    slow: long-running tests (deselect with '-m "not slow"')
```

### 4.3 CI environment variable for offscreen Qt

```bash
QT_QPA_PLATFORM=offscreen python -m pytest -m qt
```

Set this in any CI workflow file (GitHub Actions, etc.).

### 4.4 Seed control for probabilistic tests

Tests that rely on sampling (word selection, random skip, jitter) should pin
`random.seed()` at the start of the test and use generous tolerances, or use
the law of large numbers (N ≥ 10 000 iterations) to confirm distribution.

---

## Summary Prioritisation Table

| Rank | Area | Test Type | Effort | Risk if Untested |
|---|---|---|---|---|
| 1 | `Resolution` — tag parsing and architecture conversion | Unit | Low | Silent wrong image dimensions |
| 2 | `ConceptConfiguration` — serialisation round-trip | Unit | Low | User config corruption on upgrade |
| 3 | `Prompter` — choice/expansion syntax parser | Unit | Medium | Wrong prompts, unexpanded variables |
| 4 | `GenConfig` — validation and architecture helpers | Unit | Low | Runs proceed with invalid config |
| 5 | `Encryptor` — encrypt/decrypt round-trip | Unit | Low | Blacklist unreadable for new users |
| 6 | `PromptMode` / enum helpers | Unit | Low | UI display or lookup silently broken |
| 7 | Concepts + Blacklist full pipeline | Integration | Medium | Blacklisted content leaks into prompts |
| 8 | Full prompt generation per `PromptMode` | Integration | Medium | Untested prompt paths produce garbage |
| 9 | `ConceptsFile` load/save on disk | Integration | Low | Concept editor corrupts files on save |
| 10 | `GenConfig` + `Resolution` workflow prep | Integration | Medium | Wrong resolution in actual runs |
| 11 | App window smoke test | UI (pytest-qt) | Medium | Regressions invisible until manual test |
| 12 | Concept editor CRUD | UI (pytest-qt) | High | File-editing UI silently corrupts data |
| 13 | Blacklist window add/toggle/remove | UI (pytest-qt) | High | Blacklist UI changes not persisted |
| 14 | Password dialog correct/wrong input | UI (pytest-qt) | Medium | Auth bypass or lockout regression |
| 15 | Prompt config window preset apply | UI (pytest-qt) | Medium | Presets silently not applied |
