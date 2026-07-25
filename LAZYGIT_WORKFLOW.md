# Lazygit Commit-as-Diff Workflow

This repository uses ordinary Git with Lazygit as its interactive interface.
Each logical change is an individual Git commit, and each commit is reviewed
as the diff from its parent. Pull requests are not part of this workflow.

## Repository model

Work directly on the local `main` branch:

```text
origin/main
    |
    o  Commit A: one logical diff
    |
    o  Commit B: another logical diff
    |
    @  main — Commit C: another logical diff
```

Each commit should be independently understandable. Pushing `main` publishes
the commits without combining them into a pull-request-sized diff.

## Open Lazygit

From anywhere inside the repository, run:

```sh
lazygit
```

Press `?` in any panel to see the keys available in that context. Press `q`
to close the current view or exit.

Lazygit works directly with the repository's normal Git branches, index,
commits, and remotes. Commands run in Lazygit are immediately visible to the
Git CLI, and CLI commands are immediately visible in Lazygit.

## Begin a work session

Start with `main` attached and synchronized:

```sh
git switch main
git pull --rebase
lazygit
```

The local `main` branch should track `origin/main`. Avoid beginning new work
while `main` is behind the remote.

## Build one logical commit

In Lazygit's **Files** panel:

1. Select a changed file to inspect its diff.
2. Press `Space` to stage or unstage the complete file.
3. Enter the patch view when only part of a file belongs in the commit.
4. In patch view, press `Space` on a line, `v` to select a line range, or `a`
   to select the current hunk.
5. Review the staged diff.
6. Press `c` and write the commit message.

Staging is how changes are assigned to the next commit. Unstaged changes stay
in the working tree for a later commit.

A good commit:

- Contains one logical change.
- Has a message that explains the intent.
- Can be reviewed relative to its parent.
- Leaves the project in a coherent state when practical.

## Review a commit as a diff

In the **Commits** panel, select a commit. The diff panel shows the change
introduced by that commit relative to its parent.

The CLI equivalent is:

```sh
git show HEAD
```

For another commit:

```sh
git show <commit>
```

Review each local commit individually before pushing. Do not substitute one
cumulative `origin/main..HEAD` diff for per-commit review when commit
boundaries matter.

## Correct the latest commit

Stage the correction in the **Files** panel, then use Lazygit's amend action
for the latest commit. Use `?` to show the current panel's amend binding.

The CLI equivalent is:

```sh
git commit --amend
```

To retain the existing message:

```sh
git commit --amend --no-edit
```

## Correct an earlier local commit

Stage the correction, select the target in the **Commits** panel, and press
`Shift+A`. Lazygit amends that commit and rebases its descendants.

Only rewrite commits that have not been shared with other people.

## Reorder, combine, or edit commits

In the **Commits** panel, press `i` to begin an interactive rebase. Available
operations include:

- `s` — squash a commit into its predecessor.
- `f` — fix up a commit without preserving its message.
- `d` — drop a commit.
- `e` — stop and edit a commit.
- `Ctrl+K` / `Ctrl+J` — move a commit up or down.

Open the rebase actions menu and choose **Continue** when the plan is ready.
Lazygit also exposes many of these operations directly without first entering
interactive-rebase mode.

The CLI fallback is:

```sh
git rebase --interactive origin/main
```

## Sync before publishing

Fetch remote changes and rebase local commits on top:

```sh
git pull --rebase
```

If conflicts occur, resolve them in Lazygit or the editor, stage the resolved
files, and continue the rebase. The CLI continuation command is:

```sh
git rebase --continue
```

Review the history before publishing:

```sh
git log --oneline --decorate origin/main..HEAD
```

Then inspect every listed commit in Lazygit or with `git show`.

## Publish directly to `main`

Push the attached local branch:

```sh
git push origin main
```

This publishes each local commit as a separate Git commit. It does not create
a pull request. The push will fail if GitHub branch protection requires pull
requests or if another commit reached remote `main` first.

If the remote advanced, do not force-push shared `main`. Pull with rebase,
review the rewritten local commits, and push again:

```sh
git pull --rebase
git push origin main
```

## Recover from mistakes

Lazygit exposes undo and reflog operations through its menus. Before accepting
an unfamiliar recovery action, inspect the command Lazygit proposes.

Useful CLI recovery tools include:

```sh
# Inspect recent HEAD movements
git reflog

# Abort an in-progress rebase
git rebase --abort

# Uncommit the latest commit while preserving its changes
git reset --soft HEAD^

# Create a new commit that reverses an already-published commit
git revert <commit>
```

Do not use a destructive reset on shared or uncommitted work unless its exact
effect has been verified.

## Tool ownership

Lazygit and the Git CLI share the same native Git state, so switching between
them is normally safe. Do not run two state-changing operations
simultaneously, and finish an interrupted operation with the tool that started
it.

Sapling is not part of this workflow. Do not use `sl add`, `sl commit`,
`sl goto`, `sl rebase`, or `sl push` in this repository. Existing `.git/sl`
metadata can remain dormant; it does not affect ordinary Git or Lazygit.

## Daily summary

```sh
# Update and begin
git switch main
git pull --rebase
lazygit

# In Lazygit
# 1. Inspect changes.
# 2. Stage selected files, hunks, or lines.
# 3. Commit one logical change.
# 4. Review every commit relative to its parent.
# 5. Amend or interactively rebase local commits as needed.

# Publish
git log --oneline --decorate origin/main..HEAD
git push origin main
```
