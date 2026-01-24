"""Enhanced interactive mode for refactoring."""

from pathlib import Path
from typing import Optional

from rich.console import Console
from rich.prompt import Prompt, Confirm
from rich.table import Table
from rich.panel import Panel

from refactree.models import RefactorOperation, RefactorPlan, Symbol
from refactree.refactor import RefactorStrategy


console = Console()


class InteractiveRefactorSession:
    """Interactive session for refactoring with user-defined groups and targets."""
    
    def __init__(
        self,
        symbols: dict[str, Symbol],
        initial_plan: RefactorPlan,
        strategy: RefactorStrategy,
    ) -> None:
        self.symbols = symbols
        self.plan = initial_plan
        self.strategy = strategy
        self.user_groups: dict[str, list[str]] = {}  # group_name -> [symbol_names]
        self.user_targets: dict[str, Path] = {}  # group_name -> target_module
        self.filtered_operations: set[int] = set()  # Operation indices to exclude
        
    def run(self) -> RefactorPlan:
        """Run interactive session and return modified plan."""
        console.print("\n[bold cyan]Interactive Refactoring Mode[/bold cyan]\n")
        
        while True:
            self._show_menu()
            choice = Prompt.ask("\n[cyan]Choose an option[/cyan]", default="1")
            
            if choice == "1":
                self._show_plan()
            elif choice == "2":
                self._define_group()
            elif choice == "3":
                self._define_target()
            elif choice == "4":
                self._filter_operations()
            elif choice == "5":
                self._preview_changes()
            elif choice == "6":
                self._adjust_parameters()
            elif choice == "7":
                return self._apply_changes()
            elif choice == "8":
                if Confirm.ask("Exit without applying changes?"):
                    raise KeyboardInterrupt()
            else:
                console.print("[yellow]Invalid choice[/yellow]")
    
    def _show_menu(self) -> None:
        """Display interactive menu."""
        menu = Table.grid(padding=(0, 2))
        menu.add_row("1", "Show current plan")
        menu.add_row("2", "Define symbol group")
        menu.add_row("3", "Define target module for group")
        menu.add_row("4", "Filter operations (include/exclude)")
        menu.add_row("5", "Preview changes")
        menu.add_row("6", "Adjust strategy parameters")
        menu.add_row("7", "Apply changes")
        menu.add_row("8", "Exit")
        
        console.print(Panel(menu, title="[bold]Interactive Menu[/bold]", border_style="cyan"))
    
    def _show_plan(self) -> None:
        """Show current refactoring plan."""
        console.print(f"\n[bold]Current Plan ({self.strategy.value}):[/bold]\n")
        
        table = Table()
        table.add_column("#", style="cyan")
        table.add_column("Symbol", style="green")
        table.add_column("From", style="yellow")
        table.add_column("To", style="blue")
        table.add_column("Reason", style="dim")
        
        for i, op in enumerate(self.plan.operations):
            if i in self.filtered_operations:
                continue
            table.add_row(
                str(i + 1),
                op.symbol.name,
                str(op.source_module),
                str(op.target_module),
                op.reason,
            )
        
        console.print(table)
        console.print(f"\n[dim]Total operations: {len(self.plan.operations) - len(self.filtered_operations)}[/dim]")
    
    def _define_group(self) -> None:
        """Define a group of symbols."""
        console.print("\n[bold]Define Symbol Group[/bold]\n")
        
        # Show available symbols
        symbol_list = list(self.symbols.keys())[:20]  # Limit display
        console.print("[dim]Available symbols (showing first 20):[/dim]")
        for i, sym_name in enumerate(symbol_list, 1):
            console.print(f"  {i}. {sym_name}")
        
        group_name = Prompt.ask("\n[cyan]Group name[/cyan]")
        symbol_input = Prompt.ask(
            "[cyan]Symbol names (comma-separated)[/cyan]",
            default="",
        )
        
        if symbol_input:
            symbol_names = [s.strip() for s in symbol_input.split(",")]
            # Validate symbols exist
            valid_symbols = [
                name for name in symbol_names
                if name in self.symbols
            ]
            
            if valid_symbols:
                self.user_groups[group_name] = valid_symbols
                console.print(f"[green]Group '{group_name}' created with {len(valid_symbols)} symbols[/green]")
            else:
                console.print("[yellow]No valid symbols found[/yellow]")
    
    def _define_target(self) -> None:
        """Define target module for a group."""
        console.print("\n[bold]Define Target Module[/bold]\n")
        
        if not self.user_groups:
            console.print("[yellow]No groups defined. Define a group first.[/yellow]")
            return
        
        console.print("Available groups:")
        for i, group_name in enumerate(self.user_groups.keys(), 1):
            console.print(f"  {i}. {group_name}")
        
        group_name = Prompt.ask("[cyan]Group name[/cyan]")
        
        if group_name not in self.user_groups:
            console.print("[yellow]Group not found[/yellow]")
            return
        
        target_path = Prompt.ask("[cyan]Target module path[/cyan]")
        
        try:
            target = Path(target_path)
            self.user_targets[group_name] = target
            console.print(f"[green]Target '{target}' set for group '{group_name}'[/green]")
        except Exception as e:
            console.print(f"[red]Invalid path: {e}[/red]")
    
    def _filter_operations(self) -> None:
        """Filter operations (include/exclude)."""
        console.print("\n[bold]Filter Operations[/bold]\n")
        
        self._show_plan()
        
        action = Prompt.ask(
            "[cyan]Action[/cyan]",
            choices=["include", "exclude", "clear"],
            default="exclude",
        )
        
        if action == "clear":
            self.filtered_operations.clear()
            console.print("[green]All filters cleared[/green]")
            return
        
        op_indices = Prompt.ask(
            "[cyan]Operation numbers (comma-separated)[/cyan]",
            default="",
        )
        
        if op_indices:
            try:
                indices = [int(i.strip()) - 1 for i in op_indices.split(",")]
                if action == "exclude":
                    self.filtered_operations.update(indices)
                    console.print(f"[green]Excluded {len(indices)} operations[/green]")
                else:  # include
                    self.filtered_operations.difference_update(indices)
                    console.print(f"[green]Included {len(indices)} operations[/green]")
            except ValueError:
                console.print("[red]Invalid operation numbers[/red]")
    
    def _preview_changes(self) -> None:
        """Preview before/after module structure."""
        console.print("\n[bold]Preview Changes[/bold]\n")
        
        # Group operations by target module
        by_target: dict[Path, list[RefactorOperation]] = {}
        for i, op in enumerate(self.plan.operations):
            if i in self.filtered_operations:
                continue
            if op.target_module not in by_target:
                by_target[op.target_module] = []
            by_target[op.target_module].append(op)
        
        # Show before/after
        before_table = Table(title="Before")
        before_table.add_column("Module", style="yellow")
        before_table.add_column("Symbols", style="green")
        
        after_table = Table(title="After")
        after_table.add_column("Module", style="blue")
        after_table.add_column("Symbols", style="green")
        
        # Collect before state
        before_modules: dict[Path, list[str]] = {}
        for op in self.plan.operations:
            if op.source_module not in before_modules:
                before_modules[op.source_module] = []
            before_modules[op.source_module].append(op.symbol.name)
        
        # Show before
        for module, symbols in before_modules.items():
            before_table.add_row(str(module), ", ".join(symbols[:5]))
        
        # Show after
        for module, ops in by_target.items():
            symbols = [op.symbol.name for op in ops]
            after_table.add_row(str(module), ", ".join(symbols[:5]))
        
        console.print(before_table)
        console.print("\n")
        console.print(after_table)
    
    def _adjust_parameters(self) -> None:
        """Adjust strategy parameters."""
        console.print("\n[bold]Adjust Parameters[/bold]\n")
        console.print("[yellow]Parameter adjustment not yet implemented[/yellow]")
        console.print("[dim]This would allow adjusting thresholds, weights, etc.[/dim]")
    
    def _apply_changes(self) -> RefactorPlan:
        """Apply user changes and return modified plan."""
        # Filter operations
        filtered_ops = [
            op for i, op in enumerate(self.plan.operations)
            if i not in self.filtered_operations
        ]
        
        # Apply user-defined groups and targets
        # This would modify operations based on user_groups and user_targets
        # For now, just return filtered plan
        
        modified_plan = RefactorPlan(
            operations=filtered_ops,
            import_updates=self.plan.import_updates,
            validation_required=self.plan.validation_required,
        )
        
        console.print("[green]Changes applied to plan[/green]")
        return modified_plan

