#!/usr/bin/env python3
"""Run several goals in parallel, one git worktree + one Terminal tab + one Claude session each. You never type git.

  tools/goals.py start NAME "what to do"   # worktree + branch goal/NAME, links the ignored files, opens a Terminal tab
  tools/goals.py peek NAME [LINES]         # what that goal's Claude session shows right now (tmux capture)
  tools/goals.py send NAME "text"          # type into that goal's session and press Enter
  tools/goals.py watch                     # open a Terminal window attached to the tmux session (ctrl-b n/p switches goals)
  tools/goals.py list                      # goals, branches, commits ahead of main, uncommitted files
  tools/goals.py merge NAME                # commit what is left, merge into main (stops on conflicts), remove the worktree
  tools/goals.py drop NAME                 # throw the goal away (asks nothing: only use it on purpose)
Hardware goals (Jetson, toys) must take turns: only one session deploys. The worktree gets symlinks to offline/, .venv/,
brain/data/ and secrets.h from the main folder, so tests and the dashboard work there."""
import os
import subprocess
import sys
from pathlib import Path

MAIN = Path(__file__).resolve().parent.parent
WT = MAIN.parent / "sentient-goals"
import shutil
TMUX = shutil.which("tmux") or (str(Path.home() / ".local/bin/tmux") if (Path.home() / ".local/bin/tmux").exists() else None)
SESSION = "goals"
LINKS = ["offline", ".venv", "brain/data", "firmware/toy-client/secrets.h"]


def git(*a, cwd=MAIN, check=True):
    r = subprocess.run(["git", *a], cwd=cwd, capture_output=True, text=True)
    if check and r.returncode:
        sys.exit(f"git {' '.join(a)} failed:\n{r.stderr or r.stdout}")
    return r.stdout.strip()


def start(name, prompt):
    path, branch = WT / name, f"goal/{name}"
    if path.exists():
        sys.exit(f"goal {name} already exists at {path}")
    dirty = git("status", "--porcelain", "--untracked-files=no")
    if dirty:   # every goal starts from the same committed state
        git("add", "-u"); git("commit", "-m", "Checkpoint before starting goal " + name)
        print("committed the working tree as a checkpoint")
    WT.mkdir(exist_ok=True)
    git("worktree", "add", str(path), "-b", branch)
    for rel in LINKS:
        src, dst = MAIN / rel, path / rel
        if src.exists() and not dst.exists():
            dst.parent.mkdir(parents=True, exist_ok=True)
            os.symlink(src, dst)
    brief = (f"You are working on ONE goal in the git worktree {path} (branch {branch}). Goal: {prompt}\n"
             "Stay in this worktree. Commit your work to this branch as you go. Do not touch the Jetson or the toys unless the goal "
             "needs hardware and the user says it is your turn. Use subagents for independent subtasks. When done, report what you "
             "changed and which tests pass.")
    if TMUX:
        briefs = Path("/tmp") / f"goal-{name}.txt"
        briefs.write_text(brief)
        run = f"cd '{path}' && claude \"$(cat {briefs})\""
        if subprocess.run([TMUX, "has-session", "-t", SESSION], capture_output=True).returncode:
            subprocess.run([TMUX, "new-session", "-d", "-s", SESSION, "-n", name, "-x", "200", "-y", "50", run], check=True)
        else:
            subprocess.run([TMUX, "new-window", "-t", SESSION, "-n", name, run], check=True)
    else:
        cmd = f"cd '{path}' && claude {subprocess.list2cmdline([brief])!r}".replace('"', '\\"')
        subprocess.run(["osascript", "-e", f'tell application "Terminal"\nactivate\ndo script "{cmd}"\nend tell'], check=True)
    print(f"started {name}: {path}")


def tm(*a):
    return subprocess.run([TMUX, *a], capture_output=True, text=True)


def peek(name, lines=40):
    print(tm("capture-pane", "-p", "-t", f"{SESSION}:{name}", "-S", f"-{lines}").stdout.rstrip() or "(no such goal window)")


def send(name, text):
    tm("send-keys", "-t", f"{SESSION}:{name}", "-l", text); tm("send-keys", "-t", f"{SESSION}:{name}", "Enter")


def watch():
    subprocess.run(["osascript", "-e", f'tell application "Terminal"\nactivate\ndo script "{TMUX} attach -t {SESSION}"\nend tell'], check=True)


def listing():
    if not WT.exists():
        return print("no goals")
    for p in sorted(WT.iterdir()):
        if p.is_dir():
            ahead = git("rev-list", "--count", "main..HEAD", cwd=p)
            dirty = len(git("status", "--porcelain", "--untracked-files=no", cwd=p).splitlines())
            print(f"{p.name:20} goal/{p.name:18} {ahead} commits ahead, {dirty} uncommitted files")


def merge(name):
    path = WT / name
    if git("status", "--porcelain", "--untracked-files=no", cwd=path):
        git("add", "-u", cwd=path); git("commit", "-m", f"Goal {name}: remaining changes", cwd=path)
    if git("branch", "--show-current") != "main":
        sys.exit("the main folder is not on main")
    r = subprocess.run(["git", "merge", "--no-ff", f"goal/{name}", "-m", f"Merge goal {name}"], cwd=MAIN, capture_output=True, text=True)
    if r.returncode:
        subprocess.run(["git", "merge", "--abort"], cwd=MAIN)
        sys.exit("merge conflict, nothing changed:\n" + r.stdout[-800:])
    if TMUX:
        tm("kill-window", "-t", f"{SESSION}:{name}")
    git("worktree", "remove", "--force", str(path)); git("branch", "-d", f"goal/{name}")
    print(f"merged goal/{name} into main and removed its worktree")


def drop(name):
    if TMUX:
        tm("kill-window", "-t", f"{SESSION}:{name}")
    git("worktree", "remove", "--force", str(WT / name)); git("branch", "-D", f"goal/{name}")
    print("dropped", name)


if __name__ == "__main__":
    a = sys.argv[1:]
    {"start": lambda: start(a[1], a[2]), "list": listing, "merge": lambda: merge(a[1]), "drop": lambda: drop(a[1]), "peek": lambda: peek(a[1], *(a[2:3] or [40])), "send": lambda: send(a[1], a[2]), "watch": watch}.get(a[0] if a else "", lambda: print(__doc__))()
