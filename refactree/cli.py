"""Command-line interface for refactree."""

from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table
from rich.tree import Tree
from rich.panel import Panel
from rich import print as rprint

from refactree.analyzer import ASTParser, DependencyGraph, CouplingMetrics
from refactree.git import GitManager
from refactree.refactor import RefactorPlanner, RefactorExecutor, RefactorStrategy
from refactree.validation import RuffValidator, MypyValidator, ValidationResult
from refactree.preferences import load_preferences

app = typer.Typer(
    name="refactree",
    help="Advanced Python file refactorer with AST analysis and dependency graphing.",
    no_args_is_help=True,
)
console = Console(force_terminal=True)


def find_project_root(start_path: Path) -> Path:
    """Find the project root by looking for common markers like pyproject.toml, setup.py, or .git."""
    current = start_path.resolve()
    
    # If start_path is a file, start from its parent
    if current.is_file():
        current = current.parent
    
    # Walk up the directory tree looking for project markers
    markers = ["pyproject.toml", "setup.py", "setup.cfg", ".git"]
    for _ in range(10):  # Limit search depth
        for marker in markers:
            if (current / marker).exists():
                return current
        if current.parent == current:  # Reached filesystem root
            break
        current = current.parent
    
    # If no marker found, return the original directory
    return start_path.resolve() if start_path.is_dir() else start_path.resolve().parent


def print_validation_result(result: ValidationResult) -> None:
    """Print validation results to console."""
    if result.success:
        console.print(f"[green][OK][/green] {result.tool}: No issues found")
    else:
        console.print(f"[red][ERR][/red] {result.tool}: {result.error_count} errors, {result.warning_count} warnings")
        for issue in result.issues[:10]:  # Limit output
            color = "red" if issue.severity == "error" else "yellow"
            console.print(f"  [{color}]{issue.file}:{issue.line}:{issue.column}[/{color}] {issue.code}: {issue.message}")
        if len(result.issues) > 10:
            console.print(f"  ... and {len(result.issues) - 10} more issues")


@app.command()
def analyze(
    path: Path = typer.Argument(
        Path("."),
        help="Path to the Python project to analyze",
        exists=True,
    ),
    show_deps: bool = typer.Option(
        False,
        "--deps",
        "-d",
        help="Show dependency details",
    ),
    show_metrics: bool = typer.Option(
        True,
        "--metrics/--no-metrics",
        "-m/-M",
        help="Show coupling/cohesion metrics",
    ),
    suggest: bool = typer.Option(
        False,
        "--suggest",
        "-s",
        help="Show refactoring suggestions",
    ),
) -> None:
    """Analyze a Python project's structure and dependencies."""
    path = path.resolve()
    console.print(f"[bold]Analyzing:[/bold] {path}\n")

    # Parse the project
    parser = ASTParser(path)
    console.print("[dim]Parsing Python files...[/dim]")
    symbols, dependencies = parser.parse_project()

    console.print(f"Found [cyan]{len(symbols)}[/cyan] symbols in project\n")

    # Build dependency graph
    graph = DependencyGraph()
    graph.build(symbols, dependencies)

    # Show symbols by module
    analysis = graph.get_analysis_result()

    tree = Tree("[bold]Project Structure[/bold]")
    for module_path, symbol_names in sorted(analysis.modules.items()):
        module_branch = tree.add(f"[blue]{module_path.name}[/blue]")
        for name in sorted(symbol_names):
            qname = f"{module_path.stem}.{name}"
            if qname in symbols:
                sym = symbols[qname]
                icon = "[C]" if sym.symbol_type.value == "class" else "[F]"
                module_branch.add(f"{icon} {name}")

    console.print(tree)
    console.print()

    # Show dependencies if requested
    if show_deps:
        console.print("[bold]Dependencies:[/bold]")
        for dep in dependencies[:20]:  # Limit output
            console.print(f"  {dep.source} -> {dep.target} [{dep.edge_type.value}]")
        if len(dependencies) > 20:
            console.print(f"  ... and {len(dependencies) - 20} more")
        console.print()

    # Show cycles if any
    if analysis.cycles:
        console.print(f"[yellow]Warning: Found {len(analysis.cycles)} circular dependencies:[/yellow]")
        for cycle in analysis.cycles[:5]:
            console.print(f"  {' -> '.join(cycle)} -> {cycle[0]}")
        console.print()

    # Show metrics
    if show_metrics:
        metrics = CouplingMetrics(graph, symbols)
        project_metrics = metrics.calculate_project_metrics()

        table = Table(title="Project Metrics")
        table.add_column("Metric", style="cyan")
        table.add_column("Value", justify="right")

        table.add_row("Total Symbols", str(project_metrics.total_symbols))
        table.add_row("Total Modules", str(project_metrics.total_modules))
        table.add_row("Total Dependencies", str(project_metrics.total_edges))
        table.add_row("Avg Cohesion", f"{project_metrics.avg_cohesion:.2f}")
        table.add_row("Avg Coupling", f"{project_metrics.avg_coupling:.2f}")
        table.add_row("Avg Instability", f"{project_metrics.avg_instability:.2f}")
        table.add_row("Circular Dependencies", str(project_metrics.cycles_count))

        console.print(table)
        console.print()

    # Show suggestions
    if suggest:
        metrics = CouplingMetrics(graph, symbols)
        suggestions = metrics.suggest_moves(max_suggestions=5)

        if suggestions:
            console.print("[bold]Refactoring Suggestions:[/bold]")
            for qname, target, score in suggestions:
                console.print(f"  Move [cyan]{qname}[/cyan] -> [green]{target.name}[/green] (score: {score:.1%})")
        else:
            console.print("[green]No refactoring suggestions - code is well organized![/green]")


@app.command()
def refactor(
    path: Path = typer.Argument(
        Path("."),
        help="Path to the Python project",
        exists=True,
    ),
    symbol: Optional[str] = typer.Option(
        None,
        "--symbol",
        "-s",
        help="Symbol to move (class or function name)",
    ),
    target: Optional[Path] = typer.Option(
        None,
        "--target",
        "-t",
        help="Target module path",
    ),
    auto: bool = typer.Option(
        False,
        "--auto",
        "-a",
        help="Automatically apply suggested refactorings",
    ),
    strategy: Optional[str] = typer.Option(
        None,
        "--strategy",
        help="Refactoring strategy: minimize-coupling, maximize-cohesion, reduce-cycles, consolidate-modules, balanced, semantic-grouping, concept-based, hybrid, preference-weighted, split-large-modules",
    ),
    interactive: bool = typer.Option(
        False,
        "--interactive",
        "-i",
        help="Show multiple strategy options and let you choose",
    ),
    max_operations: int = typer.Option(
        20,
        "--max-operations",
        help="Maximum number of operations per plan",
    ),
    verbose: bool = typer.Option(
        False,
        "--verbose",
        "-v",
        help="Show detailed diagnostic information",
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        "-n",
        help="Show what would be done without making changes",
    ),
    no_validate: bool = typer.Option(
        False,
        "--no-validate",
        help="Skip validation after refactoring",
    ),
    no_git: bool = typer.Option(
        False,
        "--no-git",
        help="Skip git operations",
    ),
) -> None:
    """Refactor Python code by moving symbols between modules."""
    path = path.resolve()

    # Parse and analyze
    console.print(f"[bold]Analyzing:[/bold] {path}\n")

    parser = ASTParser(path)
    symbols, dependencies = parser.parse_project()

    graph = DependencyGraph()
    graph.build(symbols, dependencies)

    metrics = CouplingMetrics(graph, symbols)
    planner = RefactorPlanner(graph, symbols, metrics)

    # Create refactoring plan
    if symbol and target:
        # User-specified move
        try:
            plan = planner.plan_move_symbol(symbol, target.resolve())
            console.print(f"Planning to move [cyan]{symbol}[/cyan] to [green]{target}[/green]\n")
        except ValueError as e:
            console.print(f"[red]Error:[/red] {e}")
            raise typer.Exit(1)
    elif interactive:
        # Interactive mode: show multiple strategies
        console.print("[bold]Generating alternative refactoring plans...[/bold]\n")
        
        if verbose:
            # Show diagnostic info
            project_metrics = metrics.calculate_project_metrics()
            console.print(f"[dim]Project stats: {project_metrics.total_symbols} symbols, {project_metrics.total_modules} modules[/dim]")
            console.print(f"[dim]Cycles: {project_metrics.cycles_count}, Avg coupling: {project_metrics.avg_coupling:.2f}[/dim]\n")
            
            # Check what suggest_moves returns
            test_suggestions = metrics.suggest_moves(max_suggestions=10)
            console.print(f"[dim]Base suggestions found: {len(test_suggestions)}[/dim]")
            if test_suggestions:
                console.print("[dim]Sample suggestions:[/dim]")
                for qname, target, score in test_suggestions[:3]:
                    console.print(f"  [dim]• {qname} -> {target.name} (score: {score:.1%})[/dim]")
            console.print()
        
        alternative_plans = planner.generate_alternative_plans(max_operations_per_plan=max_operations)
        
        if not alternative_plans:
            console.print("[yellow]No refactoring suggestions found with current thresholds.[/yellow]")
            console.print("\n[dim]This could mean:[/dim]")
            console.print("  • Your code is well-organized (great!)")
            console.print("  • Symbols don't have strong coupling to other modules")
            console.print("  • All suggested moves would create import cycles")
            console.print("\n[dim]Try:[/dim]")
            console.print("  • Use [cyan]--max-operations[/cyan] to see more suggestions")
            console.print("  • Use [cyan]--verbose[/cyan] to see diagnostic information")
            console.print("  • Check specific modules with [cyan]analyze --suggest[/cyan]")
            console.print("  • Manually specify moves with [cyan]--symbol[/cyan] and [cyan]--target[/cyan]")
            raise typer.Exit(0)
        
        # Display all plans
        console.print("[bold]Available Refactoring Strategies:[/bold]\n")
        strategy_list = list(alternative_plans.keys())
        for i, (strat, alt_plan) in enumerate(alternative_plans.items(), 1):
            console.print(f"[cyan]{i}.[/cyan] [bold]{strat.value}[/bold] - {len(alt_plan.operations)} operations")
            # Show first few operations as preview
            for op in alt_plan.operations[:3]:
                console.print(f"     - {op.symbol.name}: {op.source_module.name} -> {op.target_module.name}")
            if len(alt_plan.operations) > 3:
                console.print(f"     ... and {len(alt_plan.operations) - 3} more")
            console.print()
        
        # Let user choose
        try:
            choice = typer.prompt(
                f"Select strategy (1-{len(strategy_list)}) or 'all' to see details",
                default="1",
            )
            
            if choice.lower() == "all":
                # Show all plans in detail
                for strat, alt_plan in alternative_plans.items():
                    console.print(f"\n[bold cyan]{'='*60}[/bold cyan]")
                    console.print(f"[bold]Strategy: {strat.value}[/bold] ({len(alt_plan.operations)} operations)\n")
                    for op in alt_plan.operations:
                        console.print(f"  Move [cyan]{op.symbol.name}[/cyan]: {op.source_module.name} -> {op.target_module.name}")
                        console.print(f"    Reason: {op.reason}")
                    console.print()
                
                choice = typer.prompt(
                    f"Select strategy to apply (1-{len(strategy_list)})",
                    type=int,
                )
            
            selected_strategy = strategy_list[int(choice) - 1]
            plan = alternative_plans[selected_strategy]
            console.print(f"\n[bold]Selected strategy: {selected_strategy.value}[/bold]\n")
            
            # Offer enhanced interactive mode
            if typer.confirm("\n[cyan]Enter enhanced interactive mode?[/cyan]", default=False):
                from refactree.interactive import InteractiveRefactorSession
                session = InteractiveRefactorSession(symbols, plan, selected_strategy)
                try:
                    plan = session.run()
                except KeyboardInterrupt:
                    console.print("\n[yellow]Interactive session cancelled.[/yellow]")
                    raise typer.Exit(0)
        except (ValueError, IndexError, KeyboardInterrupt):
            console.print("\n[yellow]Cancelled.[/yellow]")
            raise typer.Exit(0)
    elif auto:
        # Automatic refactoring with optional strategy
        strategy_enum = None
        if strategy:
            try:
                strategy_enum = RefactorStrategy(strategy)
            except ValueError:
                console.print(f"[red]Error:[/red] Unknown strategy '{strategy}'")
                console.print("Available strategies: minimize-coupling, maximize-cohesion, reduce-cycles, consolidate-modules, balanced")
                raise typer.Exit(1)
        else:
            strategy_enum = RefactorStrategy.BALANCED
        
        plan = planner.plan_auto_organize(strategy=strategy_enum, max_operations=max_operations)
        if not plan.operations:
            console.print("[green]No refactoring needed - code is well organized![/green]")
            raise typer.Exit(0)
        console.print(f"[bold]Auto-generated plan ({strategy_enum.value}) with {len(plan.operations)} operations:[/bold]\n")
    else:
        console.print("[red]Error:[/red] Specify either --symbol/--target, --auto, or --interactive")
        raise typer.Exit(1)

    # Show plan
    console.print("[bold]Refactoring Plan:[/bold]\n")
    for i, op in enumerate(plan.operations, 1):
        console.print(f"  {i}. Move [cyan]{op.symbol.name}[/cyan]: {op.source_module.name} -> {op.target_module.name}")
        console.print(f"     Reason: {op.reason}")

    if dry_run:
        console.print("\n[yellow]Dry run - no changes made[/yellow]")
        raise typer.Exit(0)

    # Allow selective application
    if interactive or typer.confirm("\nSelect specific operations to apply?", default=False):
        console.print("\n[bold]Select operations to apply (comma-separated numbers, or 'all'):[/bold]")
        selection = typer.prompt("Operations", default="all")
        
        if selection.lower() != "all":
            try:
                indices = [int(x.strip()) - 1 for x in selection.split(",")]
                selected_ops = [plan.operations[i] for i in indices if 0 <= i < len(plan.operations)]
                if selected_ops:
                    plan.operations = selected_ops
                    console.print(f"\n[green]Selected {len(selected_ops)} operations to apply[/green]\n")
                else:
                    console.print("[yellow]No valid operations selected, cancelling[/yellow]")
                    raise typer.Exit(0)
            except (ValueError, IndexError):
                console.print("[red]Invalid selection, applying all operations[/red]")

    # Confirm
    if not typer.confirm("\nProceed with refactoring?"):
        console.print("Cancelled.")
        raise typer.Exit(0)

    # Git operations
    git_manager = None
    checkpoint = None
    if not no_git:
        git_manager = GitManager(path)
        if git_manager.is_git_repo():
            checkpoint = git_manager.create_checkpoint()
            console.print(f"[dim]Created git checkpoint: {checkpoint[:8]}[/dim]")

    # Execute refactoring
    executor = RefactorExecutor(path, on_progress=lambda msg: console.print(f"[dim]{msg}[/dim]"))

    try:
        modified_files = executor.execute(plan)
        console.print(f"\n[green][OK][/green] Modified {len(modified_files)} files")

        # Validate
        if not no_validate:
            console.print("\n[bold]Validating changes...[/bold]")

            ruff = RuffValidator(path)
            ruff_result = ruff.validate(modified_files)
            print_validation_result(ruff_result)

            mypy = MypyValidator(path)
            mypy_result = mypy.validate(modified_files)
            print_validation_result(mypy_result)

            if not ruff_result.success or not mypy_result.success:
                if typer.confirm("\nValidation failed. Rollback changes?"):
                    executor.rollback()
                    if git_manager and checkpoint:
                        git_manager.rollback_to_commit(checkpoint, hard=True)
                    console.print("[yellow]Changes rolled back[/yellow]")
                    raise typer.Exit(1)

        # Git commit
        if git_manager and git_manager.is_git_repo():
            commit_msg = f"refactor: {plan.operations[0].reason}" if len(plan.operations) == 1 else f"refactor: reorganize {len(plan.operations)} symbols"
            commit_hash = git_manager.commit_refactoring(modified_files, commit_msg)
            if commit_hash:
                console.print(f"\n[green][OK][/green] Committed changes: {commit_hash[:8]}")

        console.print("\n[bold green]Refactoring complete![/bold green]")

    except Exception as e:
        console.print(f"\n[red]Error during refactoring:[/red] {e}")
        if git_manager and checkpoint:
            git_manager.rollback_to_commit(checkpoint, hard=True)
            console.print("[yellow]Changes rolled back to checkpoint[/yellow]")
        raise typer.Exit(1)


@app.command()
def validate(
    path: Path = typer.Argument(
        Path("."),
        help="Path to the Python project",
        exists=True,
    ),
    fix: bool = typer.Option(
        False,
        "--fix",
        "-f",
        help="Automatically fix ruff issues where possible",
    ),
) -> None:
    """Run ruff and mypy validation on the project."""
    path = path.resolve()

    console.print(f"[bold]Validating:[/bold] {path}\n")

    # Run ruff
    ruff = RuffValidator(path)
    if fix:
        ruff_result = ruff.fix()
        console.print("[dim]Applied ruff auto-fixes[/dim]")
    else:
        ruff_result = ruff.validate()
    print_validation_result(ruff_result)

    # Check formatting
    format_result = ruff.format_check()
    print_validation_result(format_result)

    # Run mypy
    mypy = MypyValidator(path)
    mypy_result = mypy.validate()
    print_validation_result(mypy_result)

    # Summary
    total_errors = ruff_result.error_count + mypy_result.error_count
    if total_errors == 0:
        console.print("\n[bold green]All validations passed![/bold green]")
    else:
        console.print(f"\n[bold red]Found {total_errors} total errors[/bold red]")
        raise typer.Exit(1)


@app.command()
def graph(
    path: Path = typer.Argument(
        Path("."),
        help="Path to the Python project",
        exists=True,
    ),
    output: Path = typer.Option(
        Path("dependency_graph.dot"),
        "--output",
        "-o",
        help="Output file for DOT graph",
    ),
) -> None:
    """Export dependency graph in DOT format for visualization."""
    path = path.resolve()

    parser = ASTParser(path)
    symbols, dependencies = parser.parse_project()

    graph = DependencyGraph()
    graph.build(symbols, dependencies)

    # Generate DOT format
    lines = ["digraph dependencies {", "  rankdir=LR;", "  node [shape=box];"]

    # Add nodes
    for qname, symbol in symbols.items():
        shape = "box" if symbol.symbol_type.value == "class" else "ellipse"
        color = "lightblue" if symbol.is_public else "lightgray"
        lines.append(f'  "{qname}" [shape={shape}, fillcolor={color}, style=filled];')

    # Add edges
    for dep in dependencies:
        style = "solid" if dep.edge_type.value == "inherits" else "dashed"
        lines.append(f'  "{dep.source}" -> "{dep.target}" [style={style}];')

    lines.append("}")

    output.write_text("\n".join(lines))
    console.print(f"[green][OK][/green] Exported graph to {output}")
    console.print("[dim]Visualize with: dot -Tpng dependency_graph.dot -o graph.png[/dim]")


@app.command()
def split(
    module: Path = typer.Argument(
        ...,
        help="Path to the module to split",
        exists=True,
    ),
    strategy: str = typer.Option(
        "community",
        "--strategy",
        "-s",
        help="Split strategy: community, class, or type",
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        "-n",
        help="Show what would be done without making changes",
    ),
) -> None:
    """Split a large module into smaller ones."""
    module = module.resolve()
    
    # Determine project root: find the actual project root by looking for markers
    if module.is_dir():
        # If a directory was passed, we need to find a specific module to split
        console.print(f"[red]Error:[/red] split command expects a Python file, not a directory")
        console.print(f"  Use: refactree split <path/to/module.py>")
        raise typer.Exit(1)
    
    # Find the project root by looking for project markers
    project_root = find_project_root(module)

    parser = ASTParser(project_root)
    symbols, dependencies = parser.parse_project()

    graph = DependencyGraph()
    graph.build(symbols, dependencies)

    metrics = CouplingMetrics(graph, symbols)
    planner = RefactorPlanner(graph, symbols, metrics)

    try:
        plan = planner.plan_split_module(module, strategy=strategy)
    except ValueError as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1)

    console.print(f"[bold]Split plan for {module.name} using '{strategy}' strategy:[/bold]\n")

    # Group by target module
    by_target: dict[Path, list] = {}
    for op in plan.operations:
        if op.target_module not in by_target:
            by_target[op.target_module] = []
        by_target[op.target_module].append(op.symbol.name)

    for target, symbols_list in by_target.items():
        console.print(f"  [green]{target.name}[/green]:")
        for sym in symbols_list:
            console.print(f"    - {sym}")

    if dry_run:
        console.print("\n[yellow]Dry run - no changes made[/yellow]")
        raise typer.Exit(0)

    if not typer.confirm("\nProceed with split?"):
        console.print("Cancelled.")
        raise typer.Exit(0)

    executor = RefactorExecutor(project_root, on_progress=lambda msg: console.print(f"[dim]{msg}[/dim]"))
    modified_files = executor.execute(plan)
    console.print(f"\n[green][OK][/green] Created {len(by_target)} new modules")


@app.command()
def decompose(
    script: Path = typer.Argument(..., help="Monolithic Python file to decompose", exists=True),
    out: Optional[Path] = typer.Option(
        None, "--out", "-o", help="Directory to create the package in (default: next to script)"
    ),
    package: Optional[str] = typer.Option(
        None, "--package", "-p", help="Package name (default: script name)"
    ),
    dry_run: bool = typer.Option(False, "--dry-run", "-n", help="Show the plan only"),
    resolution: float = typer.Option(
        1.5, "--resolution", "-r", help="Higher = more, smaller modules"
    ),
    min_lines: int = typer.Option(-1, "--min-lines", help="Smallest module (-1: auto)"),
    max_lines: int = typer.Option(400, "--max-lines", help="Soft cap on module size"),
    interface_penalty: float = typer.Option(
        1.0, "--interface-penalty", "-l", help="Cost of each name crossing a module boundary"
    ),
    constants: bool = typer.Option(
        True, "--constants/--no-constants", help="Hoist widely shared constants into constants.py"
    ),
    run_args: Optional[str] = typer.Option(
        None,
        "--run",
        help="Also run original and package with these args (shell-split) and compare stdout/rc",
    ),
    check: bool = typer.Option(True, "--check/--no-check", help="Import + lint the result"),
    history: bool = typer.Option(
        True, "--history/--no-history", help="Use git co-change (git blame) as a signal"
    ),
    split_classes: bool = typer.Option(
        True,
        "--split-classes/--no-split-classes",
        help="Split classes longer than --max-lines into behaviour-preserving mixins",
    ),
    shim: bool = typer.Option(
        False, "--shim", help="Replace the script with a thin shim that delegates to the package"
    ),
    force: bool = typer.Option(False, "--force", "-f", help="Overwrite an existing package dir"),
) -> None:
    """Decompose a monolithic script into a cohesive, loosely-coupled package.

    Top-level statements are clustered on a weighted dependency graph (references,
    inheritance, shared imports/vocabulary, source sections) to maximize cohesion while
    minimizing the names that cross module boundaries. Module imports are kept acyclic;
    annotation-only references become TYPE_CHECKING imports.
    """
    import shlex
    import shutil

    from refactree.decompose import ClusterConfig, build_plan, render, verify, write

    script = script.resolve()
    pkg = package or script.stem.replace("-", "_")
    out_dir = (out or script.parent).resolve()
    cfg = ClusterConfig(
        resolution=resolution,
        min_lines=min_lines,
        max_lines=max_lines,
        interface_penalty=interface_penalty,
        extract_constants=constants,
        split_classes=split_classes,
    )
    from refactree.decompose.history import blame_commits

    commits = blame_commits(script) if history else None
    if commits is not None:
        n_commits = len({c for c in commits if c})
        console.print(f"[dim]git history: {n_commits} commits touch this file[/dim]")
    plan = build_plan(script.read_text(), cfg, line_commits=commits)
    for cs in plan.class_splits:
        console.print(f"[bold]class {cs.cls}[/bold] split into mixins:")
        for mixin, methods in cs.mixins.items():
            console.print(f"  {mixin}: {', '.join(methods)}")
        if cs.pinned:
            console.print(f"  [dim]kept in {cs.cls}: {', '.join(cs.pinned)}[/dim]")

    table = Table(title=f"{script.name} -> {pkg}/")
    table.add_column("module", style="green")
    table.add_column("lines", justify="right")
    table.add_column("cohesion", justify="right")
    table.add_column("defines")
    table.add_column("imports from siblings")
    for m in plan.modules:
        defs = sorted(m.defines - plan.graph.deleted)
        shown = ", ".join(defs[:6]) + (f" (+{len(defs) - 6})" if len(defs) > 6 else "")
        deps = ", ".join(
            f"{k}({len(v)})" for k, v in sorted(m.imports_from.items())
        ) + "".join(f" {k}[T]" for k in sorted(m.type_imports_from.keys() - m.imports_from.keys()))
        table.add_row(m.name, str(m.lines), f"{m.cohesion:.2f}", shown, deps.strip() or "-")
    console.print(table)
    console.print(
        f"modules={len(plan.modules)}  modularity={plan.modularity:.3f}  "
        f"interface width={plan.interface_width} names  import cycles=0"
    )
    for m in plan.modules:
        if m.lines > max_lines:
            console.print(
                f"[yellow]note:[/yellow] {m.name} is {m.lines} lines; its core could not be "
                "split further without changing semantics"
            )

    if dry_run:
        raise typer.Exit(0)

    target = out_dir / pkg
    if target.exists():
        if not force:
            console.print(f"[red]Error:[/red] {target} exists (use --force)")
            raise typer.Exit(1)
        shutil.rmtree(target)
    files = render(plan, pkg)
    write(files, out_dir)
    console.print(f"[green][OK][/green] wrote {len(files)} files to {target}")

    if check:
        report = verify(
            out_dir,
            pkg,
            plan.exports,
            original=script,
            run_args=shlex.split(run_args) if run_args is not None and plan.main_units else None,
        )
        console.print(
            f"import: {'ok' if report.import_ok else '[red]FAILED[/red] ' + report.import_error}"
        )
        if report.missing_exports:
            console.print(f"[red]missing exports:[/red] {', '.join(report.missing_exports)}")
        for issue in report.lint_issues:
            console.print(f"[red]lint:[/red] {issue}")
        if report.run_match is not None:
            console.print(
                "behaviour: " + ("identical" if report.run_match else "[red]DIFFERS[/red]")
            )
            if not report.run_match:
                console.print(report.run_diff)
        if not report.ok:
            raise typer.Exit(1)

    if shim:
        lines = [f'"""Compatibility shim: the implementation now lives in the `{pkg}` package."""']
        lines.append(f"from {pkg} import *  # noqa: F401,F403")
        if plan.main_units:
            lines += ["", 'if __name__ == "__main__":', "    import runpy", "",
                      f'    runpy.run_module("{pkg}", run_name="__main__")']
        script.write_text("\n".join(lines) + "\n")
        console.print(f"[green][OK][/green] replaced {script.name} with a shim")


@app.command()
def setup_nltk() -> None:
    """Download required NLTK data for semantic analysis."""
    console.print("[bold]Setting up NLTK data for semantic analysis...[/bold]\n")
    
    try:
        import nltk
        from refactree.semantic.nlp_utils import _ensure_nltk_data
        
        if _ensure_nltk_data:
            console.print("[dim]Downloading NLTK data (this may take a few minutes)...[/dim]")
            try:
                _ensure_nltk_data()
                console.print("[green][OK][/green] NLTK data downloaded successfully!")
            except Exception as e:
                console.print(f"[yellow]Warning: Some data may not have downloaded: {e}[/yellow]")
                console.print("[dim]Trying manual download...[/dim]")
        else:
            console.print("[dim]Manual download mode...[/dim]")
        
        # Manual download as backup
        required_data = [
            ("punkt_tab", "tokenizers/punkt_tab"),
            ("punkt", "tokenizers/punkt"),  # Fallback
            ("stopwords", "corpora/stopwords"),
            ("wordnet", "corpora/wordnet"),
            ("averaged_perceptron_tagger", "taggers/averaged_perceptron_tagger"),
            ("omw-1.4", "corpora/omw-1.4"),
        ]
        
        for data_name, data_path in required_data:
            try:
                # Check if already exists
                nltk.data.find(data_path)
                console.print(f"[green][OK][/green] {data_name} already available")
            except LookupError:
                try:
                    console.print(f"[dim]Downloading {data_name}...[/dim]")
                    nltk.download(data_name, quiet=False)
                    console.print(f"[green][OK][/green] {data_name} downloaded")
                except Exception as e:
                    console.print(f"[yellow][WARN][/yellow] Could not download {data_name}: {e}")
        
        console.print("\n[green][OK][/green] NLTK setup complete!")
        console.print("[dim]You can now use semantic analysis strategies.[/dim]")
            
    except ImportError:
        console.print("[red]Error:[/red] NLTK is not installed. Install it with: uv add nltk")
        raise typer.Exit(1)
    except Exception as e:
        console.print(f"[red]Error:[/red] Failed to setup NLTK: {e}")
        raise typer.Exit(1)


if __name__ == "__main__":
    app()
