# Agent Instructions

## Git and Lazygit workflow

This repository uses ordinary Git with Lazygit as the human interface. Each
logical change should be an individual commit that can be reviewed as the diff
from its parent. Pull requests are not the unit of change in this workflow.

Lazygit is interactive and intended for the human operator. Agents should use
non-interactive Git commands against the same native repository state. Do not
use Sapling (`sl`) in this repository.

## Before editing

Inspect the current branch, working tree, index, and relevant history:

```sh
git status --short --branch
git diff
git diff --cached
```

Treat all existing modifications and untracked files as user work unless the
task clearly establishes otherwise. Preserve them and work around unrelated
changes.

Do not use commands that can discard or conceal existing work, including:

```sh
git reset --hard
git checkout -- .
git clean
git stash
```

Do not switch branches, pull, rebase, amend, or otherwise rewrite history
unless the user requests it or it is an unavoidable, clearly in-scope part of
the requested Git operation.

## Editing and verification

Make narrowly scoped changes and inspect the resulting diff:

```sh
git diff -- path/to/changed-file
git status --short
```

Run tests and checks appropriate to the affected code. Report failures and
distinguish failures caused by the agent's changes from pre-existing failures.

Lazygit automatically reflects changes made through the filesystem or Git
CLI. It can remain open while an agent works, but the human and agent must not
perform simultaneous state-changing Git operations.

## Commits

Do not create a commit unless the user explicitly requests one.

When asked to commit:

1. Create one coherent, independently reviewable commit.
2. Stage only the files or patches that belong to the requested change.
3. Never use `git add .`, `git add -A`, or another broad staging command when
   unrelated work may exist.
4. Review the staged diff before committing.
5. Verify the resulting commit as a parent-relative diff.

Typical sequence:

```sh
git add -- path/to/file1 path/to/file2
git diff --cached
git diff --cached --check
git commit -m "Describe the logical change"
git show --stat --oneline HEAD
```

If a file contains both pre-existing user work and agent-authored changes, do
not stage the whole file. Isolate the intended patch safely or stop and ask
for direction.

Do not rewrite commits that may already be shared. Do not push unless the user
explicitly requests it.

## Remote operations

Before an explicitly requested synchronization or push, inspect the working
tree and remote relationship:

```sh
git status --short --branch
git fetch origin
git log --oneline --decorate origin/main..HEAD
```

This repository publishes commits directly to `main`. Before pushing, ensure
the local commits are based on the current `origin/main`. If the remote has
advanced, use a rebase only when the working state is safe and the user has
authorized the synchronization:

```sh
git pull --rebase
git log --oneline origin/main..HEAD
git push origin main
```

Never force-push shared `main`.

## Interrupted operations

Finish or abort an interrupted operation with the tool that started it. For
example, continue a Git rebase with:

```sh
git rebase --continue
```

Before attempting recovery, inspect `git status` and the reflog. Avoid
destructive recovery commands unless their exact targets and effects have been
verified and the user has authorized them.
