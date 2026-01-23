"""Git repository management."""

from dataclasses import dataclass
from pathlib import Path

from git import Repo, InvalidGitRepositoryError
from git.exc import GitCommandError


@dataclass
class GitStatus:
    """Status of the git repository."""

    is_clean: bool
    modified_files: list[Path]
    untracked_files: list[Path]
    staged_files: list[Path]
    current_branch: str


class GitManager:
    """Manages git operations for refactoring."""

    def __init__(self, project_root: Path) -> None:
        self.project_root = project_root
        self._repo: Repo | None = None

    @property
    def repo(self) -> Repo:
        """Get or initialize the git repository."""
        if self._repo is None:
            try:
                self._repo = Repo(self.project_root)
            except InvalidGitRepositoryError:
                # Initialize a new repo if none exists
                self._repo = Repo.init(self.project_root)
        return self._repo

    def is_git_repo(self) -> bool:
        """Check if the project is a git repository."""
        try:
            _ = self.repo
            return True
        except Exception:
            return False

    def get_status(self) -> GitStatus:
        """Get the current status of the repository."""
        repo = self.repo

        modified = [Path(item.a_path) for item in repo.index.diff(None)]
        staged = [Path(item.a_path) for item in repo.index.diff("HEAD")]
        untracked = [Path(p) for p in repo.untracked_files]

        return GitStatus(
            is_clean=not repo.is_dirty(untracked_files=True),
            modified_files=modified,
            untracked_files=untracked,
            staged_files=staged,
            current_branch=repo.active_branch.name,
        )

    def create_checkpoint(self, message: str = "refactree: checkpoint before refactoring") -> str:
        """Create a checkpoint commit with all current changes.

        Returns the commit hash.
        """
        repo = self.repo

        # Stage all changes
        repo.git.add(A=True)

        # Check if there's anything to commit
        if not repo.index.diff("HEAD") and not repo.untracked_files:
            return repo.head.commit.hexsha

        # Create commit
        commit = repo.index.commit(message)
        return commit.hexsha

    def create_branch(self, branch_name: str) -> None:
        """Create and checkout a new branch."""
        repo = self.repo
        repo.git.checkout("-b", branch_name)

    def commit_refactoring(
        self,
        files: list[Path],
        message: str,
        auto_stage: bool = True,
    ) -> str | None:
        """Commit refactoring changes.

        Args:
            files: Files to include in the commit
            message: Commit message
            auto_stage: Whether to automatically stage the files

        Returns:
            Commit hash or None if nothing to commit
        """
        repo = self.repo

        if auto_stage:
            for file in files:
                try:
                    if file.exists():
                        repo.index.add([str(file)])
                    else:
                        # File was deleted
                        try:
                            repo.index.remove([str(file)])
                        except GitCommandError:
                            pass
                except GitCommandError:
                    pass

        # Check if there's anything to commit
        if not repo.index.diff("HEAD"):
            return None

        commit = repo.index.commit(f"refactree: {message}")
        return commit.hexsha

    def rollback_to_commit(self, commit_hash: str, hard: bool = False) -> None:
        """Rollback to a specific commit.

        Args:
            commit_hash: The commit to rollback to
            hard: If True, discard all changes. If False, keep changes unstaged.
        """
        repo = self.repo
        mode = "--hard" if hard else "--mixed"
        repo.git.reset(mode, commit_hash)

    def get_diff(self, file_path: Path | None = None) -> str:
        """Get the diff for staged changes."""
        repo = self.repo
        if file_path:
            return repo.git.diff("--cached", str(file_path))
        return repo.git.diff("--cached")

    def get_file_history(self, file_path: Path, max_commits: int = 10) -> list[dict]:
        """Get commit history for a specific file."""
        repo = self.repo
        commits = list(repo.iter_commits(paths=str(file_path), max_count=max_commits))

        return [
            {
                "hash": c.hexsha[:8],
                "message": c.message.strip(),
                "author": str(c.author),
                "date": c.committed_datetime.isoformat(),
            }
            for c in commits
        ]

    def stash_changes(self, message: str = "refactree: stashing changes") -> bool:
        """Stash current changes.

        Returns True if changes were stashed, False if nothing to stash.
        """
        repo = self.repo
        if repo.is_dirty(untracked_files=True):
            repo.git.stash("push", "-m", message, "-u")
            return True
        return False

    def pop_stash(self) -> bool:
        """Pop the most recent stash.

        Returns True if successful, False if no stash to pop.
        """
        repo = self.repo
        try:
            repo.git.stash("pop")
            return True
        except GitCommandError:
            return False

    def ensure_clean_working_tree(self, allow_stash: bool = True) -> str | None:
        """Ensure working tree is clean before refactoring.

        Args:
            allow_stash: If True, stash changes instead of failing

        Returns:
            Stash reference if changes were stashed, None otherwise

        Raises:
            RuntimeError if working tree is dirty and stash not allowed
        """
        status = self.get_status()
        if status.is_clean:
            return None

        if allow_stash:
            self.stash_changes()
            return "stash@{0}"

        raise RuntimeError(
            "Working tree has uncommitted changes. "
            "Please commit or stash them before refactoring."
        )
