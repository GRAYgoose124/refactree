# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Refactree is an advanced Python file refactorer that uses AST analysis, dependency graphing, ruff, and mypy to intelligently reorganize Python codebases. It provides a CLI interface for both automatic organization suggestions and user-specified refactoring schemes. Git integration manages working directory state automatically.

## Development Commands

```bash
# Install dependencies
uv sync

# Run the CLI
uv run python main.py

# Linting and formatting
uv run ruff check .
uv run ruff format .

# Type checking
uv run mypy .

# Run tests
uv run pytest

# Run a single test
uv run pytest tests/test_file.py::test_name -v
```

## Architecture

The system operates in phases:

1. **Analysis Phase**: Parse Python files into AST, build dependency graph (imports, function calls, class inheritance), identify module boundaries
2. **Suggestion Phase**: Apply heuristics to suggest optimal organization based on coupling/cohesion metrics
3. **User Specification Phase**: Accept user-defined organization schemes via CLI or config
4. **Refactoring Phase**: Execute moves/renames while updating all import statements and references
5. **Validation Phase**: Run ruff and mypy to verify refactored code correctness
6. **Git Phase**: Stage and commit changes with descriptive messages

### Key Design Decisions

- Use `ast` module for Python parsing (not regex-based)
- Dependency graph stored as directed graph for cycle detection
- All file operations go through a transaction layer that can rollback on validation failure
- Git operations are atomic per refactoring operation
