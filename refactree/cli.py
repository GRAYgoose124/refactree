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
from refactree.refactor import RefactorPlanner, RefactorExecutor
from refactree.validation import RuffValidator, MypyValidator, ValidationResult

app = typer.Typer(
    name="refactree",
    help="Advanced Python file refactorer with AST analysis and dependency graphing.",
    no_args_is_help=True,
)
console = Console(force_terminal=True)


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
    elif auto:
        # Automatic refactoring
        plan = planner.plan_auto_organize()
        if not plan.operations:
            console.print("[green]No refactoring needed - code is well organized![/green]")
            raise typer.Exit(0)
        console.print(f"[bold]Auto-generated plan with {len(plan.operations)} operations:[/bold]\n")
    else:
        console.print("[red]Error:[/red] Specify either --symbol/--target or --auto")
        raise typer.Exit(1)

    # Show plan
    for op in plan.operations:
        console.print(f"  Move [cyan]{op.symbol.name}[/cyan]: {op.source_module.name} -> {op.target_module.name}")
        console.print(f"    Reason: {op.reason}")

    if dry_run:
        console.print("\n[yellow]Dry run - no changes made[/yellow]")
        raise typer.Exit(0)

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
    project_root = module.parent

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


if __name__ == "__main__":
    app()
