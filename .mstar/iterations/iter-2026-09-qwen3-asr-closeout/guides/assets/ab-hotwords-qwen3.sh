#!/usr/bin/env bash
# T5 — the two-arm hotword measurement under the shipping Qwen3-ASR engine.
#
# SSOT for what this does and why: {ITERATION_DIR}/iter-2026-09-qwen3-asr-closeout/
# guides/t5-hotword-measurement-protocol.md .  This script only drives it.
#
# Question: does the shipped DEFAULT_HOTWORDS list (33 entries, `asr.py:100-164`)
# earn its place now that it reaches the model as a free-form `prompt`
# (`asr.py:791`) rather than as a FunASR decode-time bias?
#
# Three arms, three roots, same audio, same model, same device:
#   with     arm A — shipping configuration
#   without  arm B — DEFAULT_HOTWORDS temporarily reduced to the empty tuple
#   repeat   arm R — byte-for-byte arm A's configuration
#
# Two corpora share this one script, selected by CORPUS, because the arm
# discipline — especially the arm-B source edit and its double restore proof —
# must not exist in two diverging copies:
#   CORPUS=long  (default) the frozen six-item corpus: the P1–P9 verdict, ~7.3 h
#   CORPUS=short           a three-item ≤10 min set: a faster instrument whose
#                          reading is narrower (protocol Amendment 3)
# Arm R covers the whole corpus when it is short enough to afford, one item
# otherwise; the row list below states which for each corpus.
# ITEM_ORDER=shortest-first banks the cheapest items first on a long run.
#
# Arm B CANNOT be produced by an environment variable: `_extra_hotwords`
# (`asr.py:257-266`) *skips* every term already in DEFAULT_HOTWORDS and
# `default_config()` only ever appends (`asr.py:286`), so BILI_ASR_HOTWORDS can
# add and never subtract.  Arm B is therefore a temporary, uncommitted source
# edit, restored immediately and proven restored TWICE (protocol §4).
#
# The restore is inside `trap ... EXIT` so that a killed, failed or interrupted
# run still puts asr.py back.  A run that cannot prove the restore is void.
set -euo pipefail

HOST_REPO=/root/workspace/bilibili-asr-archive
PRODUCT=$HOST_REPO/bilibili-asr-archive
SRC=$PRODUCT/src
ASR_PY=$SRC/bili_asr/asr.py
PY=$PRODUCT/.venv/bin/python

# ------------------------------------------------------------- corpus choice
# CORPUS selects which rows and which audio root the three arms run over.  The
# two roots are separate trees so one corpus can never overwrite the other's
# artifacts, and each arm root is a complete archive either way.
CORPUS=${CORPUS:-long}
ITEM_ORDER=${ITEM_ORDER:-longest-first}
case "$CORPUS" in
  long)
    AB=/root/e2e-asr/ab-hotwords-qwen3
    # Was /mnt/123pan/bili-asr-e2e/asr-vs-subtitle/audio until 2026-09-26, when that
    # mount started answering 401 on every read and the staged arms were lost with it
    # (register row R3).  The six were re-downloaded from Bilibili to a local disk, and
    # the source now points there: a local path cannot fail the way a remote mount did.
    # Recorded so a reader comparing this run with the 2026-09-22 measurements knows the
    # audio is a fresh fetch whose durations match the frozen record within 2 s.
    AUDIO_SRC=/mnt/e/asr-archive-c6/audio
    NOISE_ITEM=BV1iddQYQE7D.p0    # protocol §7: longest corpus item, arm R's single row
    REPEAT_SCOPE=noise ;;         # 7682 s — one item is all the noise floor needs
  short)
    AB=/root/e2e-asr/ab-short-corpus
    AUDIO_SRC=/root/e2e-asr/ab-short/audio
    NOISE_ITEM=BV1wLTP6NE9h.p0    # 448 s; the whole set is affordable, so R covers it
    REPEAT_SCOPE=all ;;
  short2)
    # The second short set, chosen from a DEEPER sweep of the same uploader and
    # staged under a NEW root on a different device, because the first short set
    # and the frozen six both lived only on 123pan and were lost when that mount
    # failed auth.  `/mnt/e` is a local disk, so nothing here depends on WebDAV.
    AB=/root/e2e-asr/ab-short2/arms
    AUDIO_SRC=/mnt/e/asr-archive-short2/audio
    NOISE_ITEM=BV1aRTA6mEGF.p0
    REPEAT_SCOPE=all ;;
  *) echo "CORPUS must be 'long', 'short' or 'short2', not '$CORPUS'" >&2; exit 2 ;;
esac
REFERENCE=BV13hEB63En5.p0          # protocol §3/§8: smoke item; staged below if present

export HSA_ENABLE_DXG_DETECTION=1
export BILI_ASR_MODEL=$PRODUCT/models/Qwen3-ASR-1.7B-hf
export BILI_ASR_ALIGNER_MODEL=$PRODUCT/models/Qwen3-ForcedAligner-0.6B-hf
export BILI_ASR_MODEL_ID=Qwen/Qwen3-ASR-1.7B-hf
export HF_HUB_OFFLINE=1
unset BILI_ASR_HOTWORDS BILI_ASR_CHUNK_SECONDS

log() { printf '[%s] %s\n' "$(date -Is)" "$*"; }
die() { printf '[%s] FATAL: %s\n' "$(date -Is)" "$*" >&2; exit 1; }

# --------------------------------------------------------------- the rows
# Frozen per corpus.  The long set is compass C6's six parts and carries the
# P1–P9 verdict; the short set is three items ≤600 s whose selection rule,
# coverage and limits are stated in protocol Amendment 3.
#
# ITEM_ORDER picks the sequence the rows are seeded in.  The corpus is the same
# either way — only the order changes — but on a run that lasts hours the order
# decides how much is banked if it has to stop early:
#   longest-first   (default, protocol §3) the reference item leads
#   shortest-first  cheapest items land first, so a partial run still holds the
#                   most completed items
# Whichever is chosen is recorded in the seed output, because a reader comparing
# two runs must be able to see that only the order differed.
seed() {  # $1 = root, $2 = "all" | "noise"
  local root=$1 which=${2:-all}
  mkdir -p "$root/manifest" "$root/audio"
  "$PY" - "$root" "$which" "$AUDIO_SRC" "$CORPUS" "$ITEM_ORDER" <<'PY'
import json, os, sys, pathlib
root, which, audio_src, corpus, item_order = sys.argv[1:6]

if corpus == "long":
    # compass C6, longest first.  The reference item's audio is not staged on
    # this host, so protocol §3 says record it unavailable and run
    # longest-first rather than substitute a different item silently.
    ROWS = [
        ("BV1iddQYQE7D", 29363077962, 7682, "2025-04-11", "【随便聊聊】普通人如何扬弃性的压抑，革命者如何扬弃爱的压抑"),
        ("BV1BdtazGEBE", 31594841414, 6395, "2025-08-09", "【哲学与现实】爱情升级指南——当你说“我爱你”时，你到底在怎说什么"),
        ("BV1vNTqzFEve", 30412768784, 5112, "2025-06-09", "【爱欲经济学】爱情的阶次和解放"),
        ("BV1Y7M4zNEfF", 30506419561, 2598, "2025-06-15", "【行动指南】从爱情走向革命"),
        ("BV11p5qzAE6s", 29471278516, 2408, "2025-04-17", "【实事求是】被迫配种的本已是囚，革命者应该如何恋爱"),
        ("BV1zz5zzFENq", 29471998505, 2087, "2025-04-17", "【历史唯物主义】革命与爱情"),
    ]
    NOISE = "BV1iddQYQE7D.p0"
elif corpus == "short":
    # The first short set: every item in the local corpus with duration_s <= 600 s,
    # taken whole rather than by cherry-picking (protocol Amendment 3 §"How the
    # three were chosen").  Ordered longest first for the same reason.
    ROWS = [
        ("BV1aRTA6mEGF", 39462570344, 571, "2026-06-28", "【项目预告】150元在线装配电工培训和电工论坛"),
        ("BV132XgBjER4", 37034656553, 500, "2026-03-28", "【实事求是】对某特定行为的披露和定性"),
        ("BV1wLTP6NE9h", 39462830522, 449, "2026-06-28", "【对敌攻略】国际劳工仲裁庭，欢迎有识之士加入"),
    ]
    NOISE = "BV1wLTP6NE9h.p0"
elif corpus == "short2":
    # A deeper sweep (pages 1-10 of the uploader's 1691 videos, 210 scanned)
    # found 12 parts at <=600 s; these are the eight not already measured in the
    # first short set.  Two carry NO caption track and are recorded absent
    # rather than substituted.  Order and membership are fixed here so the set
    # is the sweep's output, not a pick.
    # The twelve <=600 s parts the sweep found, MINUS the three already measured
    # in `short` (BV1wLTP6NE9h 449, BV132XgBjER4 500, BV1aRTA6mEGF 571): an item
    # must not sit in two corpora, or the same audio is measured twice under two
    # names.  Nine rows remain, and they are the sweep's remainder rather than a
    # choice — no row was added or dropped for how it scored.
    ROWS = [
        ("BV11Z421N7AM", 1647513375, 565, "2023-06-30", "【行动建议】把这两类妄人从我们的团队里清除出去"),
        ("BV16D7azJEcm", 30308107017, 560, "2025-06-01", "【行动建议】与其害怕死亡，更应害怕衰老"),
        ("BV1kEVszWEbm", 29827661855, 560, "2025-04-24", "【实事求是】这不是巧合，这是历史的真实的普遍性"),
        ("BV1acKfzEEWS", 30713908862, 539, "2025-06-09", "【实事求是】为什么职业革命家一定要学习黑格尔哲学"),
        ("BV1DT3UzwEbj", 30856121058, 529, "2025-06-15", "【实事求是】心之三贼：但是、一直、其实——穿越三种“穿越性”的幻想"),
        ("BV1qR7az2EzY", 30307977934, 469, "2025-05-31", "【随便聊聊】如何看待陈腐者"),
        ("BV1WQpBewEyZ", 25633102207, 431, "2024-10-17", "【逃生通道】造神容易拜神危险，请君入瓮何必多言"),
        ("BV1aAhLzsENb", 31468421662, 374, "2025-07-20", "【实事求是】大勇者必有大怯"),
        ("BV1YFEUzpEsT", 30030759743, 74, "2025-05-28", "【实事求是】5000元真伪现场探访"),
    ]
    NOISE = "BV1aRTA6mEGF.p0"
else:
    # Fail loudly on an unknown corpus.  Without this the script would fall
    # through with ROWS unbound and raise NameError several lines later, which
    # reads like a script bug rather than a bad argument.
    raise SystemExit(f"unknown corpus {corpus!r}: expected long, short or short2")

if which == "noise":
    ROWS = [r for r in ROWS if r[0] + ".p0" == NOISE]

# The order is a knob, not an accident.  The reference item's audio is not
# staged on this host, so protocol §3 runs the corpus in a stated order rather
# than substituting a different item silently.
if item_order == "longest-first":
    ROWS = sorted(ROWS, key=lambda r: -r[2])
elif item_order == "shortest-first":
    ROWS = sorted(ROWS, key=lambda r: r[2])
else:
    raise SystemExit(f"ITEM_ORDER must be longest-first or shortest-first, not {item_order!r}")

rows = [
    {"work_id": f"{bvid}:p0", "bvid": bvid, "page_index": 0, "cid": cid,
     "title": title, "duration_s": dur, "pubdate_str": pub, "status": "audio_ok"}
    for bvid, cid, dur, pub, title in ROWS
]
p = pathlib.Path(root, "manifest", "manifest.jsonl")
p.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
staged = []
for r in rows:
    src = pathlib.Path(audio_src, f'{r["bvid"]}.p0.m4a')
    dst = pathlib.Path(root, "audio", f'{r["bvid"]}.p0.m4a')
    if not src.exists():
        continue
    if dst.exists():
        dst.unlink()
    # A hardlink is impossible for the long corpus: /mnt/123pan is an rclone
    # fuse mount on a different device, so os.link raises EXDEV.  The protocol
    # allows "hardlink or copy — NEVER a symlink"; copy is the working branch.
    # A symlink would be refused outright by path_policy's O_NOFOLLOW open.
    try:
        os.link(src, dst)
    except OSError:
        import shutil
        shutil.copyfile(src, dst)
    assert not dst.is_symlink()
    assert dst.stat().st_size == src.stat().st_size, f"short copy: {dst.name}"
    staged.append((r["bvid"], dst.stat().st_size))
print(f"seed {root} [{corpus}/{item_order}]: {len(rows)} rows, {len(staged)} audio staged, "
      f"{sum(s for _, s in staged)} bytes")
print("  order: " + ", ".join(f"{b}={d}s" for b, _, d, _, _ in ROWS))
PY
}

# ------------------------------------------------------------ environment
env_record() {
  log "=== environment record (protocol §8)"
  cd "$PRODUCT"
  echo "repo HEAD: $(git -C "$HOST_REPO" log --oneline -1)"
  echo "src tree:  $(git -C "$HOST_REPO" rev-parse HEAD:bilibili-asr-archive/src)"
  echo "venv:      $PY"
  "$PY" -c "import sys,transformers,torch;print('python',sys.version.split()[0],'transformers',transformers.__version__,'torch',torch.__version__)"
  echo "HSA_ENABLE_DXG_DETECTION=$HSA_ENABLE_DXG_DETECTION"
  echo "BILI_ASR_MODEL=$BILI_ASR_MODEL"
  echo "BILI_ASR_HOTWORDS=${BILI_ASR_HOTWORDS:-<unset>}"
  echo "--- check-asr-env"
  "$PY" -m bili_asr check-asr-env && echo "check-asr-env exit 0" || echo "check-asr-env exit $?"
}

# --------------------------------------------------------- arm B's edit
remove_terms() {
  local before
  before=$("$PY" - "$ASR_PY" <<'PY'
import re, sys, pathlib
t = pathlib.Path(sys.argv[1]).read_text(encoding="utf-8")
m = re.search(r'DEFAULT_HOTWORDS: tuple\[str, \.\.\.\] = \((.*?)\n\)', t, re.S)
if m is None:
    print(-1)
else:
    # Count only real tuple entries: a comment line inside the literal quotes
    # terms too (e.g. the ITEM/AITEM occurrences), and counting those would
    # make the guard pass on a list that is not the one being removed.
    body = [ln for ln in m.group(1).splitlines() if not ln.strip().startswith("#")]
    print(len(re.findall(r'"([^"]+)"', "\n".join(body))))
PY
)
  # The shipped list is 33 entries (protocol Amendment 1).  A mismatch means
  # the source is not what this arm believes it is, so refuse rather than edit
  # something else: this function rewrites the product's decoder prompt.
  [ "$before" = "33" ] || die "expected 33 shipped terms before the edit, found $before; refusing"
  "$PY" - "$ASR_PY" <<'PY'
import re, sys, pathlib
p = pathlib.Path(sys.argv[1])
t = p.read_text(encoding="utf-8")
t, n = re.subn(
    r'DEFAULT_HOTWORDS: tuple\[str, \.\.\.\] = \(.*?\n\)',
    'DEFAULT_HOTWORDS: tuple[str, ...] = ()',
    t, count=1, flags=re.S,
)
assert n == 1, f"literal not found exactly once: {n}"
p.write_text(t, encoding="utf-8")
PY
  local after
  after=$("$PY" - "$ASR_PY" <<'PY'
import re, sys, pathlib
t = pathlib.Path(sys.argv[1]).read_text(encoding="utf-8")
# Arm B's edit writes the one-line form `= ()`; the multi-line literal the
# guard reads beforehand cannot match this pattern at all, so a surviving
# literal reads as NO-LITERAL rather than as a count.
if re.search(r'DEFAULT_HOTWORDS: tuple\[str, \.\.\.\] = \(\)\s*$', t, re.M):
    print(0)
else:
    print("NO-LITERAL")
PY
)
  [ "$after" = "0" ] || die "post-edit term count is '$after', expected 0; refusing to run the without arm"
  log "arm B edit applied: 33 shipped terms -> empty tuple"
}

restore_asr() {
  # Restore from the byte snapshot taken before the edit, NOT from git.
  #
  # Why not `git checkout`: it restores HEAD, and this host's HEAD is not
  # necessarily the file the arms must run on.  On 2026-09-26 the target host's
  # working tree held the 33-entry restoration as an *uncommitted* change while
  # HEAD still carried the 26-entry list the restoration replaced — so a git
  # restore would have silently reverted the fix, and the git-shaped proof
  # (porcelain empty + blob == HEAD) would have *passed*, because reverting is
  # exactly what makes those two agree.  Arm R would then have measured the
  # wrong configuration while every check said the run was sound.
  #
  # A byte snapshot cannot fail that way: it restores what the run started from,
  # whatever that was, and the proof is that the bytes came back unchanged.
  [ -n "${ASR_SNAPSHOT:-}" ] && [ -f "$ASR_SNAPSHOT" ] || {
    log "  no snapshot to restore from — this arm is void"
    return 1
  }
  cp -f "$ASR_SNAPSHOT" "$ASR_PY"
  local now
  now=$(sha256sum "$ASR_PY" | cut -d' ' -f1)
  log "=== restore proof (byte-anchored)"
  log "  expected sha256: $ASR_SHA_BEFORE"
  log "  actual   sha256: $now"
  if [ "$now" != "$ASR_SHA_BEFORE" ]; then
    log "  RESTORE NOT PROVEN — this arm is void"
    return 1
  fi
  # The git-shaped reading is still reported, but as a *description* of the
  # tree, never as the proof: on a tree whose fix is uncommitted, "working
  # differs from HEAD" is the correct and expected state, not a failure.
  local blob head
  blob=$(git -C "$HOST_REPO" hash-object -- "$ASR_PY" 2>/dev/null || echo "?")
  head=$(git -C "$HOST_REPO" rev-parse HEAD:bilibili-asr-archive/src/bili_asr/asr.py 2>/dev/null || echo "?")
  log "  (context) working blob $blob / HEAD blob $head"
  if [ "$blob" != "$head" ]; then
    log "  (context) working tree differs from HEAD — expected when the fix is uncommitted"
  fi
  log "  RESTORE PROVEN: bytes identical to the pre-edit snapshot"
}

# Take the byte snapshot the restore depends on.  Called once, before any arm.
snapshot_asr() {
  ASR_SNAPSHOT=$(mktemp /tmp/asr-snapshot-XXXXXX.py)
  cp -f "$ASR_PY" "$ASR_SNAPSHOT"
  ASR_SHA_BEFORE=$(sha256sum "$ASR_PY" | cut -d' ' -f1)
  # Refuse to start on a list this run does not understand.  Without this, an
  # arm could measure a configuration nobody declared.
  local n
  n=$("$PY" - "$ASR_PY" <<'PY'
import re, sys, pathlib
t = pathlib.Path(sys.argv[1]).read_text(encoding="utf-8")
m = re.search(r'DEFAULT_HOTWORDS: tuple\[str, \.\.\.\] = \((.*?)\n\)', t, re.S)
if m is None:
    print(-1)
else:
    body = [ln for ln in m.group(1).splitlines() if not ln.strip().startswith("#")]
    print(len(re.findall(r'"([^"]+)"', "\n".join(body))))
PY
)
  log "=== pre-run snapshot: $ASR_SHA_BEFORE ($n shipped terms)"
  [ "$n" = "33" ] || log "  WARNING: expected the 33-entry list; arms will measure '$n' terms"
}

# --------------------------------------------------------------- one arm
run_arm() {  # $1 = arm
  local arm=$1
  log "=== arm $arm starting"
  cd "$PRODUCT"
  unset BILI_ASR_HOTWORDS || true
  local rc=0
  "$PY" -m bili_asr asr --pending --archive-root "$AB/$arm" || rc=$?
  log "=== arm $arm finished rc=$rc"
  return $rc
}

# ------------------------------------------------------------- read-back
readback() {
  local arm=$1 md
  md=$(ls "$AB/$arm"/transcripts/md/*.md 2>/dev/null | head -1)
  [ -n "$md" ] || { echo "  $arm: NO ARTIFACT"; return; }
  "$PY" - "$arm" "$md" <<'PY'
import json, sys, pathlib
arm, md = sys.argv[1], sys.argv[2]
text = pathlib.Path(md).read_text(encoding="utf-8")
front = text.split("---")[1]
fm = {}
for line in front.strip().splitlines():
    k, _, v = line.partition(": ")
    try:
        fm[k] = json.loads(v)
    except Exception:
        fm[k] = v
terms = [t for t in str(fm.get("asr_hotwords", "") or "").split(",") if t]
print(f"  {arm}: {len(terms)} entries | {pathlib.Path(md).name}")
for k in ("asr_model_name", "asr_model_id", "asr_device", "asr_chunk_seconds", "source"):
    if k in fm:
        print(f"      {k} = {fm[k]}")
pathlib.Path(f"/tmp/abhot-{arm}-hotwords.txt").write_text(",".join(terms), encoding="utf-8")
PY
}

case "${1:-}" in
  setup)
    # Source availability is checked BEFORE anything is removed.  This ordering
    # is the whole reason the check exists: an earlier version ran `rm -rf` and
    # then copied from AUDIO_SRC, so when AUDIO_SRC was unreadable (the 123pan
    # mount answering EIO/401 on reads) it destroyed the staged arms and could
    # not replace them.  Losing uploaded audio is not recoverable by re-running
    # the script, so the guard runs first and refuses.
    missing=0
    for bv in $("$PY" - "$CORPUS" <<'PY'
import sys
CORPUS_BVIDS = {
    "long":   ["BV1zz5zzFENq","BV11p5qzAE6s","BV1Y7M4zNEfF","BV1vNTqzFEve","BV1BdtazGEBE","BV1iddQYQE7D"],
    "short":  ["BV1aRTA6mEGF","BV132XgBjER4","BV1wLTP6NE9h"],
    "short2": ["BV11Z421N7AM","BV16D7azJEcm","BV1kEVszWEbm","BV1acKfzEEWS","BV1DT3UzwEbj",
               "BV1qR7az2EzY","BV1WQpBewEyZ","BV1aAhLzsENb","BV1YFEUzpEsT"],
}
# An unknown corpus is a bug in this map, not a reason to check the wrong list:
# checking the wrong list is how a guard passes while the data it guards is absent.
try:
    bvids = CORPUS_BVIDS[sys.argv[1]]
except KeyError:
    raise SystemExit(f"guard has no item list for corpus {sys.argv[1]!r}")
print(" ".join(bvids))
PY
); do
      head -c 1 "$AUDIO_SRC/$bv.p0.m4a" >/dev/null 2>&1 || missing=$((missing + 1))
    done
    [ "$missing" = "0" ] || die "AUDIO_SRC ($AUDIO_SRC) is unreadable for $missing item(s); refusing to delete the existing arms — stage the audio first"
    # Keep the existing arms when they are already complete: a re-run to change
    # ITEM_ORDER must not require re-copying audio at all.
    if [ -f "$AB/with/manifest/manifest.jsonl" ] && [ "$(ls "$AB"/with/audio/*.m4a 2>/dev/null | wc -l)" -gt 0 ]; then
      log "arms already staged under $AB; reusing (set FORCE_SETUP=1 to rebuild from AUDIO_SRC)"
    fi
    if [ "${FORCE_SETUP:-0}" = "1" ]; then
      rm -rf "$AB"
    fi
    mkdir -p "$AB"
    seed "$AB/with"    all
    seed "$AB/without" all
    seed "$AB/repeat"  "$REPEAT_SCOPE"
    log "three arm roots seeded under $AB (CORPUS=$CORPUS, arm R scope=$REPEAT_SCOPE, order=$ITEM_ORDER)"
    ls -la "$AB/with/audio/"; ;;
  env)      env_record; snapshot_asr ;;
  with)     snapshot_asr; run_arm with ;;
  repeat)   snapshot_asr; run_arm repeat ;;
  without)
    snapshot_asr
    trap 'restore_asr || true' EXIT
    remove_terms
    run_arm without
    restore_asr || die "the without arm is void: restore not proven"
    trap - EXIT ;;
  readback) for a in with without repeat; do readback "$a"; done ;;
  all)
    snapshot_asr
    trap 'restore_asr || true' EXIT
    env_record
    run_arm with
    remove_terms
    run_arm without
    restore_asr || die "the without arm is void: restore not proven"
    trap - EXIT
    run_arm repeat
    log "=== ALL ARMS DONE (CORPUS=$CORPUS)" ;;
  *) echo "usage: CORPUS={long|short} ITEM_ORDER={longest-first|shortest-first} $0 {setup|env|with|without|repeat|all|readback}" >&2; exit 2 ;;
esac
