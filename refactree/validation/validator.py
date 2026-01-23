"""Code validation using ruff and mypy."""

import subprocess
import json
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class ValidationIssue:
    """A single validation issue."""

    file: Path
    line: int
    column: int
    code: str
    message: str
    severity: str  # "error", "warning", "info"


@dataclass
class ValidationResult:
    """Result of running validation."""

    success: bool
    issues: list[ValidationIssue] = field(default_factory=list)
    tool: str = ""

    @property
    def error_count(self) -> int:
        return sum(1 for i in self.issues if i.severity == "error")

    @property
    def warning_count(self) -> int:
        return sum(1 for i in self.issues if i.severity == "warning")


class RuffValidator:
    """Validates Python code using ruff."""

    def __init__(self, project_root: Path) -> None:
        self.project_root = project_root

    def validate(self, files: list[Path] | None = None) -> ValidationResult:
        """Run ruff on specified files or entire project.

        Args:
            files: Specific files to check, or None for entire project

        Returns:
            ValidationResult with any issues found
        """
        cmd = ["ruff", "check", "--output-format=json"]

        if files:
            cmd.extend(str(f) for f in files)
        else:
            cmd.append(str(self.project_root))

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                cwd=self.project_root,
            )

            issues = self._parse_output(result.stdout)
            return ValidationResult(
                success=result.returncode == 0,
                issues=issues,
                tool="ruff",
            )

        except FileNotFoundError:
            return ValidationResult(
                success=False,
                issues=[
                    ValidationIssue(
                        file=Path(""),
                        line=0,
                        column=0,
                        code="E000",
                        message="ruff not found. Install with: pip install ruff",
                        severity="error",
                    )
                ],
                tool="ruff",
            )

    def fix(self, files: list[Path] | None = None) -> ValidationResult:
        """Run ruff with auto-fix on specified files."""
        cmd = ["ruff", "check", "--fix", "--output-format=json"]

        if files:
            cmd.extend(str(f) for f in files)
        else:
            cmd.append(str(self.project_root))

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                cwd=self.project_root,
            )

            issues = self._parse_output(result.stdout)
            return ValidationResult(
                success=result.returncode == 0,
                issues=issues,
                tool="ruff",
            )

        except FileNotFoundError:
            return ValidationResult(
                success=False,
                issues=[],
                tool="ruff",
            )

    def format_check(self, files: list[Path] | None = None) -> ValidationResult:
        """Check formatting with ruff format."""
        cmd = ["ruff", "format", "--check"]

        if files:
            cmd.extend(str(f) for f in files)
        else:
            cmd.append(str(self.project_root))

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                cwd=self.project_root,
            )

            issues = []
            if result.returncode != 0:
                # Parse which files need formatting
                for line in result.stdout.splitlines():
                    if line.strip():
                        issues.append(
                            ValidationIssue(
                                file=Path(line.strip()),
                                line=0,
                                column=0,
                                code="FORMAT",
                                message="File needs formatting",
                                severity="warning",
                            )
                        )

            return ValidationResult(
                success=result.returncode == 0,
                issues=issues,
                tool="ruff format",
            )

        except FileNotFoundError:
            return ValidationResult(success=False, issues=[], tool="ruff format")

    def _parse_output(self, output: str) -> list[ValidationIssue]:
        """Parse ruff JSON output into ValidationIssues."""
        if not output.strip():
            return []

        try:
            data = json.loads(output)
        except json.JSONDecodeError:
            return []

        issues = []
        for item in data:
            severity = "error" if item.get("code", "").startswith("E") else "warning"
            issues.append(
                ValidationIssue(
                    file=Path(item.get("filename", "")),
                    line=item.get("location", {}).get("row", 0),
                    column=item.get("location", {}).get("column", 0),
                    code=item.get("code", ""),
                    message=item.get("message", ""),
                    severity=severity,
                )
            )

        return issues


class MypyValidator:
    """Validates Python code using mypy."""

    def __init__(self, project_root: Path) -> None:
        self.project_root = project_root

    def validate(self, files: list[Path] | None = None) -> ValidationResult:
        """Run mypy on specified files or entire project.

        Args:
            files: Specific files to check, or None for entire project

        Returns:
            ValidationResult with any issues found
        """
        cmd = [
            "mypy",
            "--no-error-summary",
            "--show-column-numbers",
            "--show-error-codes",
        ]

        if files:
            cmd.extend(str(f) for f in files)
        else:
            cmd.append(str(self.project_root))

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                cwd=self.project_root,
            )

            issues = self._parse_output(result.stdout)
            return ValidationResult(
                success=result.returncode == 0,
                issues=issues,
                tool="mypy",
            )

        except FileNotFoundError:
            return ValidationResult(
                success=False,
                issues=[
                    ValidationIssue(
                        file=Path(""),
                        line=0,
                        column=0,
                        code="E000",
                        message="mypy not found. Install with: pip install mypy",
                        severity="error",
                    )
                ],
                tool="mypy",
            )

    def _parse_output(self, output: str) -> list[ValidationIssue]:
        """Parse mypy output into ValidationIssues."""
        issues = []

        for line in output.splitlines():
            line = line.strip()
            if not line or line.startswith("Found") or line.startswith("Success"):
                continue

            # Format: file:line:column: severity: message [code]
            parts = line.split(":", 3)
            if len(parts) < 4:
                continue

            try:
                file_path = Path(parts[0])
                line_no = int(parts[1])
                col = int(parts[2]) if parts[2].strip().isdigit() else 0
                rest = parts[3].strip()

                # Extract severity and message
                if rest.startswith("error:"):
                    severity = "error"
                    message = rest[6:].strip()
                elif rest.startswith("warning:"):
                    severity = "warning"
                    message = rest[8:].strip()
                elif rest.startswith("note:"):
                    severity = "info"
                    message = rest[5:].strip()
                else:
                    severity = "error"
                    message = rest

                # Extract code if present
                code = ""
                if "[" in message and message.endswith("]"):
                    code_start = message.rfind("[")
                    code = message[code_start + 1 : -1]
                    message = message[:code_start].strip()

                issues.append(
                    ValidationIssue(
                        file=file_path,
                        line=line_no,
                        column=col,
                        code=code,
                        message=message,
                        severity=severity,
                    )
                )
            except (ValueError, IndexError):
                continue

        return issues


class CombinedValidator:
    """Runs both ruff and mypy validation."""

    def __init__(self, project_root: Path) -> None:
        self.ruff = RuffValidator(project_root)
        self.mypy = MypyValidator(project_root)

    def validate(self, files: list[Path] | None = None) -> tuple[ValidationResult, ValidationResult]:
        """Run both validators and return results."""
        ruff_result = self.ruff.validate(files)
        mypy_result = self.mypy.validate(files)
        return ruff_result, mypy_result

    def validate_all(self, files: list[Path] | None = None) -> ValidationResult:
        """Run all validators and combine results."""
        ruff_result, mypy_result = self.validate(files)

        all_issues = ruff_result.issues + mypy_result.issues
        success = ruff_result.success and mypy_result.success

        return ValidationResult(
            success=success,
            issues=all_issues,
            tool="ruff+mypy",
        )
