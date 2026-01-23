# TODO

## High Priority
- [ ] Implement `refactor` command execution
- [ ] Add import rewriting when moving symbols between modules
- [ ] Implement transaction layer for atomic file operations
- [ ] Add ruff validation after refactoring
- [ ] Add mypy validation after refactoring
- [ ] Git auto-commit after successful refactoring

## Medium Priority
- [ ] User-defined organization schemes via YAML/TOML config
- [ ] Interactive mode for approving refactoring suggestions
- [ ] Cycle detection and resolution suggestions
- [ ] Support for moving functions, not just classes
- [ ] Handle `__all__` exports properly

## Low Priority
- [ ] Visualization of dependency graph (graphviz export)
- [ ] Incremental analysis (cache AST between runs)
- [ ] Plugin system for custom refactoring rules
- [ ] IDE integration (LSP server)

## Known Limitations
- Does not handle dynamic imports (`importlib`, `__import__`)
- Does not track string-based attribute access (`getattr`)
- Assumes single-package projects for now
