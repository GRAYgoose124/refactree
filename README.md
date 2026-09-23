# Refactree

Advanced Python file refactorer with AST analysis, dependency graphing, and intelligent code organization. Refactree helps you reorganize code by moving symbols between modules, splitting large files, and applying semantic or structural strategies—with optional interactive control and user-defined preferences.

## Installation

```bash
# With uv (recommended)
uv sync

# Or with pip
pip install -e .
```

Run via the project script:

```bash
uv run python main.py <command> [options]
# or, if installed: refactree <command> [options]
```

## Commands

### `decompose` — Turn a monolithic script into a package

The flagship operation: take one large file (say a 2000-line script) and split it into a
package whose modules are cohesive, whose cross-module interfaces are as narrow as possible,
and whose imports are acyclic. Behaviour is preserved and checked.

```bash
# Preview the plan (modules, cohesion, which names cross which boundary)
uv run refactree decompose big_script.py --dry-run

# Write big_script/ next to the file, verify it imports & lints, and compare runtime
# behaviour of `python big_script.py ARGS` vs `python -m big_script ARGS`
uv run refactree decompose big_script.py --run "--some --args"

# Replace the script with a thin shim that delegates to the package
uv run refactree decompose big_script.py --shim
```

How it works:

1. **Units** — every top-level statement becomes a unit (def/class/assignment/side-effect).
   Name resolution is scope-aware (locals, closures, comprehensions, class bodies, PEP 695
   type params), and references used only in annotations are tracked separately.
2. **Must-link constraints** — things that cannot be separated without changing semantics
   stay together: redefinitions, `global` writers and the state they rebind, module-level
   mutation (`REG[k] = ...`, `X += 1`), side-effect statements, and `globals()` injection
   with its consumers.
3. **Affinity graph** — weighted by references (damped for hubs and widely used
   utilities), inheritance/decorators, sibling subclasses, shared external imports and
   identifier vocabulary (IDF-weighted), the author's section-banner comments, and source
   locality.
4. **Clustering** — Louvain communities, then: import-cycle repair (push the minority
   direction's dependencies down, else merge), splitting of oversized modules, absorbing
   tiny ones, greedy refinement of *cohesion − λ·interface width*, and optional hoisting of
   widely shared constants into `constants.py`.
5. **Class decomposition** — classes longer than `--max-lines` are split into mixins by
   clustering methods on shared `self.` state, intra-class calls and vocabulary.
   `class Big(_BigParseMixin, _BigHelpMixin, Base)` keeps the MRO and zero-arg `super()`
   semantics intact; dunders, name-mangled access, `__class__`, methods reached through
   `super()` or referenced in the class body stay in the core class, and Enum / NamedTuple
   / TypedDict / Protocol / metaclass / `__slots__` classes are left alone.
6. **Emission** — modules in dependency order, only the imports each one uses, sibling
   imports as `from .x import ...`, annotation-only ones under `if TYPE_CHECKING:`,
   `__init__.py` re-exporting the original API (private names and `_`-aliased imports
   included, so `mock.patch("pkg._sys.exit")`-style code keeps working), `__main__.py`
   for the main guard.
   Comments and formatting of the original code are preserved verbatim.
7. **Verification** — import the package, check every public name is still exported,
   ruff for *new* undefined/unused/redefined names (diffed against the original), and
   optionally byte-compare stdout + exit code of original vs package.

Module names follow conventions (`cli`, `constants`, `errors`), then the author's section
banners, then the module's anchor class, then its most distinctive vocabulary (TF-IDF
against sibling modules, pluralized for families such as `actions`).

Clustering runs several independent starts (Louvain at different resolutions, each followed
by constrained local search) and keeps the best objective. As a sanity check, the
decomposed CPython `argparse` (4 giant classes split into mixins, 8 modules) passes
CPython's own `test_argparse` suite exactly like the original: 1845 tests, same results.

#### Benchmark

`python -m refactree.decompose.bench [--shuffle] [packages...]` flattens real
multi-module packages (json, email, http, unittest, click, yaml, ...) into single-file
monoliths, decomposes them, and scores agreement with the authors' original modules
(ARI / NMI). `--shuffle` randomizes statement order so source locality can't help. Use it
to evaluate any change to the weights or the optimizer.

Limitation: code that monkeypatches module globals of the original (e.g.
`mock.patch("script.helper")`) only affects the re-export in the package, not internal
references in the submodule that defines them.

Knobs: `--resolution` (higher → more, smaller modules), `--interface-penalty` (λ),
`--min-lines` / `--max-lines`, `--no-constants`, `--no-split-classes`.

### `analyze` — Inspect project structure and dependencies

Analyzes the project’s Python files and shows symbols, metrics, and optional refactoring suggestions.

```bash
# Analyze current directory
uv run python main.py analyze

# Analyze a specific path
uv run python main.py analyze path/to/project

# Show dependency details
uv run python main.py analyze --deps

# Show refactoring suggestions
uv run python main.py analyze --suggest

# Hide metrics
uv run python main.py analyze --no-metrics
```

| Option | Short | Description |
|--------|--------|-------------|
| `--deps` | `-d` | Show dependency details |
| `--metrics` / `--no-metrics` | `-m` / `-M` | Show or hide coupling/cohesion metrics |
| `--suggest` | `-s` | Show refactoring suggestions |

---

### `refactor` — Move symbols or apply automatic refactorings

Refactor by specifying a move, by choosing a strategy, or interactively.

**Manual move (single symbol):**

```bash
uv run python main.py refactor . --symbol MyClass --target path/to/target.py
uv run python main.py refactor . -s my_function -t utils/helpers.py
```

**Automatic refactoring with a strategy:**

```bash
# Use default "balanced" strategy
uv run python main.py refactor . --auto

# Choose a strategy
uv run python main.py refactor . --auto --strategy split-large-modules
uv run python main.py refactor . --auto --strategy semantic-grouping
uv run python main.py refactor . --auto -s concept-based --max-operations 15
```

**Interactive mode (choose from multiple strategies):**

```bash
uv run python main.py refactor . --interactive
# or
uv run python main.py refactor . -i
```

When you select a strategy, you can optionally enter enhanced interactive mode to define symbol groups, target modules, and filter operations.

**Dry run (no file changes):**

```bash
uv run python main.py refactor . --auto --dry-run
uv run python main.py refactor . -i -n
```

| Option | Short | Description |
|--------|--------|-------------|
| `--symbol` | `-s` | Symbol to move (class or function name) |
| `--target` | `-t` | Target module path |
| `--auto` | `-a` | Use automatic refactoring |
| `--strategy` | | Strategy name (see below) |
| `--interactive` | `-i` | Show strategies and let you choose |
| `--max-operations` | | Max operations per plan (default 20) |
| `--verbose` | `-v` | Extra diagnostic output |
| `--dry-run` | `-n` | Show plan only, no changes |
| `--no-validate` | | Skip ruff/mypy after refactoring |
| `--no-git` | | Skip git checkpoint and commit |

**Refactoring strategies:**

| Strategy | Description |
|----------|-------------|
| `balanced` | Default; mixes coupling, cohesion, and cycle avoidance |
| `minimize-coupling` | Prefer moves that reduce inter-module coupling |
| `maximize-cohesion` | Prefer moves that increase intra-module cohesion |
| `reduce-cycles` | Focus on breaking circular dependencies |
| `consolidate-modules` | Merge related modules when it makes sense |
| `semantic-grouping` | Group by semantic similarity (needs NLTK) |
| `concept-based` | Organize by domain/functionality concepts |
| `hybrid` | Combine structural and semantic analysis |
| `preference-weighted` | Apply rules/tags from `refactree.yaml` |
| `split-large-modules` | Split large files (>15 symbols) into focused modules |

---

### `validate` — Run ruff and mypy

Run ruff (lint/format) and mypy on the project.

```bash
uv run python main.py validate
uv run python main.py validate path/to/project

# Auto-fix ruff issues where possible
uv run python main.py validate --fix
```

| Option | Short | Description |
|--------|--------|-------------|
| `--fix` | `-f` | Apply ruff auto-fixes |

---

### `graph` — Export dependency graph (DOT)

Export the project’s dependency graph for visualization.

```bash
uv run python main.py graph
uv run python main.py graph -o my_graph.dot
```

| Option | Short | Description |
|--------|--------|-------------|
| `--output` | `-o` | Output file (default: `dependency_graph.dot`) |

Then: `dot -Tpng dependency_graph.dot -o graph.png`

---

### `split` — Split a single module

Split one large module using a chosen strategy (community, class, or type).

```bash
# Pass a .py file, not a directory
uv run python main.py split path/to/large_module.py
uv run python main.py split path/to/large_module.py --strategy class
uv run python main.py split path/to/large_module.py -s type --dry-run
```

| Option | Short | Description |
|--------|--------|-------------|
| `--strategy` | `-s` | `community`, `class`, or `type` |
| `--dry-run` | `-n` | Show plan only |

---

### `setup-nltk` — Download NLTK data for semantic analysis

Required for semantic strategies (`semantic-grouping`, `concept-based`, `hybrid`). Run once (or when NLTK data is missing).

```bash
uv run python main.py setup-nltk
```

---

## Configuration

Optional project config: `refactree.yaml` or `.refactree.yaml` in the project root. Copy from `refactree.yaml.example`.

**Example:**

```yaml
preferences:
  semantic:
    enabled: true
    weight: 0.4
    similarity_threshold: 0.6

  rules:
    - name: "Validators"
      pattern: "*Validator"
      target_module: "validation/"
      priority: 10

  tags:
    - name: "auth"
      keywords: ["auth", "login", "token"]
      target_module: "auth/"
```

- **semantic**: Enable/configure semantic analysis and hybrid weight.
- **rules**: Glob patterns + target module; higher `priority` wins.
- **tags**: Keyword-based suggestions for target modules.

---

## Development

```bash
uv sync
uv run ruff check .
uv run ruff format .
uv run mypy .
uv run pytest
```

---

## Summary

| Command | Purpose |
|---------|---------|
| `analyze` | Inspect structure, metrics, and suggestions |
| `refactor` | Move symbols or run automatic/interactive refactoring |
| `validate` | Run ruff and mypy |
| `graph` | Export dependency graph (DOT) |
| `split` | Split one module by strategy |
| `setup-nltk` | Install NLTK data for semantic strategies |

Use `uv run python main.py --help` and `uv run python main.py <command> --help` for full option lists.
