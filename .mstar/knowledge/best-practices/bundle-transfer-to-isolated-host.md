---
module: host operations (pad → isolated compute host, git transfer over an air-gapped SSH hop)
date: 2026-09-25
problem_type: best_practice
category: best-practices
severity: medium
plan_id: 20260925-structure-tidy
applies_when:
  - moving commits or branches to a host that has no route to the git remote
  - driving a Windows/WSL host from the pad over a single SSH command channel
  - deciding where a large or batch artifact should land on the compute host
  - verifying that a pushed branch actually landed before declaring a transfer done
tags:
  - git-bundle
  - remote-access
  - wsl
  - verification
  - transfer
related_components:
  - workflows
  - scripts
---

# Move code to an isolated host as a bundle, and verify the refs it landed

## Context

The compute host (`192.168.3.21`, Windows + WSL2, AMD GPU) has **no route to GitHub**. The pad
does. Every change that has to run on the GPU host therefore travels as a **git bundle**: the pad
fetches/packs the refs into one file, encodes it as base64, and ships it through the same single
SSH command channel used for everything else. This doc is the working recipe plus the three places
it silently fails.

## Guidance

### 1. The channel

```bash
ssh -i /root/.ssh/id_ed25519 chosenecho@192.168.3.21 "wsl -e bash -s" <<'REMOTE'
# bash runs *inside* WSL here
REMOTE
```

- The remote shell that SSH lands in is **cmd.exe**, which does **not** support `;` as a command
  separator, and does not understand POSIX quoting. Never put shell logic in the `ssh` argument
  itself — one plain command only. Push all real work into the `"wsl -e bash -s"` + heredoc.
- Quote the heredoc delimiter (`<<'REMOTE'`, `<<'B64'`) so the pad does not expand `$` inside.
- One connection per unit of work; the channel is slow to set up and is not a shell you can keep
  interactive.

### 2. Why a bundle, not `git push`

There is no path from the host to the remote. Options considered and why the bundle won:

| Route | Verdict |
|---|---|
| `git push` from the host | impossible — no route to GitHub |
| `git clone` on the host from the pad | the pad is not a git server; would need extra daemons |
| rsync/scp the working tree | loses history and refs; cannot be `--ff-only` merged |
| **git bundle over the SSH channel** | **works, self-contained, verifies offline, one file** |

### 3. Push side (pad)

```bash
# pack the refs you intend to move (explicit refs, not --all)
git bundle create /tmp/sync.bundle refs/heads/main refs/heads/<branch> refs/remotes/origin/main
base64 -w0 /tmp/sync.bundle > /tmp/sync.b64
# then send as a quoted heredoc: base64 -d > /tmp/sync.bundle <<'B64' … B64
```

Keep it one file per transfer and name it after the transfer (`sync-all.bundle`), not after the
branch — the same file usually carries the local branch, its remote-tracking counterpart, and
`origin/*` in one go.

### 4. Receive side (host)

```bash
REPO=/root/workspace/bilibili-asr-archive
cd "$REPO"
git bundle verify /tmp/sync-all.bundle | tail -3            # must list the refs + "ok"
git fetch /tmp/sync-all.bundle "+refs/heads/*:refs/remotes/pad/*"
git fetch /tmp/sync-all.bundle "+refs/remotes/origin/*:refs/remotes/origin/*" 2>&1 | tail -5
git merge --ff-only pad/<branch>                            # only where a ff is intended
rm -f /tmp/sync-all.bundle
```

- Fetch into **`refs/remotes/pad/*`**, never straight onto `refs/heads/*`: a bundle that turns out to
  be stale or wrong must not be able to move the host's checked-out branch. The `--ff-only` merge is
  a separate, visible step.
- `git bundle verify` is the only offline integrity check there is; `| tail -3` keeps its useful
  lines (the "The bundle contains these … refs" block ends with the `ok` line).

### 5. Verify what landed — from the host, in the same command

A transfer is not done when the last command exits 0. Print the evidence in the **same** heredoc:
the ref map, the version string, the command count, and a sentinel line, so the pad's single output
block either contains the proof or shows exactly how far it got.

```bash
cd /root/workspace/bilibili-asr-archive && REPO=$PWD          # the product package is the repo/subdir
echo "--- refs AFTER ---"
git for-each-ref --format="%(refname:short) %(objectname:short)" refs/remotes/pad
git status -sb | head -2
git --no-pager log --oneline -1
bilibili-asr-archive/.venv/bin/bili-asr --version
# subcommand count: argparse lists them at 4-space indent, names may end in more spaces or EOL
bilibili-asr-archive/.venv/bin/bili-asr --help 2>&1 \
  | sed -n '/^positional arguments:/,/^options:/p' | grep -cE '^    [a-z][a-z-]+( |$)'
echo VERIFY_DONE
```

- Put a **unique sentinel** (`echo VERIFY_DONE`) as the *last* line. Truncated output is normal on
  this channel; the sentinel is what distinguishes "finished" from "cut off mid-transfer".
- Count subcommands by parsing `--help`, not by trusting a number written in a doc — the doc-side
  number is exactly the thing that drifts. Two traps measured on 2026-09-25: the indent is **four
  spaces** (a `^  [a-z]` pattern counts zero), and the longest name (`publish-transcripts`,
  `evaluate-concurrency`) is followed by a **newline**, so the pattern needs `( |$)`. A correct
  count on this commit is **20**.
- `--help` writes to stdout, but the parser exits non-zero on some subcommand typos — keep `2>&1`
  so the count never silently becomes 0.

### 6. Where bulk data goes on the host

| Location | Use |
|---|---|
| `/srv/bili-asr-archive` (pad, local ext4) | **the archive root since 2026-09-28.** Local disk, so `rm -rf` is a normal delete rather than a data-loss primitive. Small: ~32 GB free on `/`, enough for a verification corpus, not for the full archive. |
| `/mnt/e` (1.9 TB USB, on the target host) | **batch/archival data only.** Measured ~94 MB/s write, ~332 MB/s read; not suitable for a code repo or small-file-heavy operations |
| C: (the WSL root) | the git checkout and anything that must be fast per-file |
| ~~`/mnt/123pan`~~ (WebDAV via rclone, `rclone-123pan.service`) | **RETIRED 2026-09-28.** The mount degraded to `Input/output error` and then `401 Unauthorized` as its credential expired; it was unmounted and the unit disabled (the unit file is kept at `/etc/systemd/system/rclone-123pan.service` in case the credential is ever renewed). Do not treat it as usable storage. |

Rule of thumb: keep the working tree on a local disk; put the verification/small archive corpus on
`/srv/bili-asr-archive`; put bulk archival data on `/mnt/e`. Prefer local disk over a network mount for
anything a pipeline will write and delete — the 123pan retirement is the worked example of why: a
WebDAV mount that degrades turns routine cleanup into a data-loss primitive, and its failure mode
(`EIO`, then `401`) looks like a code problem rather than a credential problem.

### 7. Cleanup

```bash
git worktree prune            # stale worktrees from a previous transfer round
git for-each-ref refs/remotes/pad        # list, then delete the ones you no longer need
```

`refs/remotes/pad/*` accumulates one ref per transfer. Prune them once the merge has landed;
leaving them makes later `for-each-ref` output ambiguous about which side is authoritative.

## Why This Matters

Three failure modes cost real time before this was written down:

1. **Shell syntax in the wrong shell.** `;` and quoted arguments in the `ssh` command line are
   parsed by cmd.exe, so the command fails or, worse, half-runs. The heredoc form is the fix.
2. **A transfer read as done because the command exited 0.** On this channel the output can be
   truncated; a bundle that was only half-written still lets the first commands succeed. The
   sentinel + ref map + version probe is what makes the result citable.
3. **Bulk artifacts landing on C:.** They belong on `/mnt/e`; the throughput numbers above are the
   reason, and mixing them up slows every later per-file operation on the host.

## When to Apply

- Any change that has to be exercised on the GPU host and was authored on the pad.
- Any one-off remote diagnostic that needs more than one command.
- Reviewing a "I pushed it to the host" claim: ask for the ref map and the sentinel, not the exit
  code.
