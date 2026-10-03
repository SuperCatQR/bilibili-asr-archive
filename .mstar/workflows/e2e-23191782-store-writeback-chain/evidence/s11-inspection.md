# S11 — Human inspection of proofread blocks (≥5 required)

**Part**: `BV1acKfzEEWS:p0` — 【实事求是】为什么职业革命家一定要学习黑格尔哲学 (539 s)
**Routes**: caption = `subtitle-ai`/`ai-zh` (195 entries, harvested S3); ASR = forced local Qwen3-ASR run (S11 forced leg)
**Artifacts**: `artifacts/.tmp/proofread-work/inputs/BV1acKfzEEWS.p0.sidebyside.md`,
`artifacts/.tmp/proofread-work/align/BV1acKfzEEWS.p0.alignment.jsonl`
**Thresholds (frozen)**: agree ≥ 0.85 · minor 0.75–0.85 · review < 0.75; `SequenceMatcher(autojunk=False)`
**Machine summary**: 29 blocks · 24 agree / 3 minor / 2 review · 83 ASR segments / 2049 chars · 195 subtitle entries, **0 unassigned**

This is the on-hardware hand-inspection that `I-000102` recorded as never delivered. Judgements below are
human readings of the printed table, not threshold echoes.

| # | Block | sim | Machine | Human verdict | What the reading shows |
|---|---|---|---|---|---|
| 1 | 00:00:00,080–15,840 | 0.930 | agree | **agree** | ASR adds disfluency particles the caption dropped (啊，这个/呃) and one word order slip (`就是学马克思` vs `学马克思`). Content identical. Both usable. |
| 3 | 00:00:26,080–32,320 | 0.955 | agree | **agree** | Difference is punctuation and the causal `但是` placement only. Clean. |
| 5 | 00:00:39,440–57,120 | 0.956 | agree | **agree** | Long span, high fidelity: 职业革命家/庸众/必读 all correct on both sides. ASR keeps spoken 就不要废话的, caption the same. |
| 7 | 00:01:06,080–2:28,800 | 0.912 | agree | **minor** ⚠ | Machine says agree but this block contains the run's clearest **real** damage: caption has `建建邦治县雪` where ASR reads `建建邦学` (both garbled; target is likely 建邦学/制宪学), and caption `里路` vs ASR `理路`. **This is a caption-side garble that a high similarity score hides.** Reading both columns is what surfaces it. |
| 9 | 00:02:53,360–57,840 | 0.762 | minor | **minor** | `至高法要` (ASR) vs `制高法药` (caption): both wrong, different ways. Real disagreement — needs adjudication, cannot be auto-kept. |
| 11 | 00:03:14,934–28,854 | 0.875 | agree | **minor** ⚠ | **The hotword case, live**: ASR writes `自我阳气的`, caption writes `自我洋气的` — the intended word is **扬弃**. Caption also has `权利的逻辑` where ASR has `权力的逻辑` (ASR correct here). Two homophone families in one block. |
| 15 | 00:04:54,934–58,614 | 0.727 | review | **review** | ASR stops mid-clause (`然后从其中把自己`); caption continues (`…拯救出来也好`). The ASR route genuinely **lost the tail** — a real ASR-side truncation, correctly caught by the score. |
| 12 | 00:03:28,854–4:15,254 | 0.949 | agree | **agree** | Highest-stakes content (职业革命家 要求, 权力的异化) reads correctly on both sides. ASR's punctuation/particles differ only. |

## Tally and what it means

- **8 blocks inspected** (≥5 required): 5 judged agree · 2 judged minor **despite a passing machine score** · 1 judged review.
- **Machine verdict is not sufficient.** Blocks 7 and 11 both scored ≥0.875 (agree) but carry real defects when read. A pipeline that trusted the threshold would keep both silently.
- **Route asymmetries run both ways.** Block 7/9: the *caption* carries the garble. Block 11/15: the *ASR* carries it. Neither route is uniformly better — this is the empirical case for the side-by-side product.
- **Homophones are measured, not hypothesised.** `扬弃` surfaces as 阳气/洋气, `权力/权利` swaps, `制宪学/治县雪`. These are the families `MEASURED_HOTWORD_CANDIDATES` names; at HEAD `DEFAULT_HOTWORDS = ()`, so the shipped default does **not** correct them (S10 confirms the path is inert). This run is a fresh measured sample of that gap.
- **Coverage is total**: 195/195 subtitle entries assigned to a block, 0 unassigned — the block-alignment leg has no hole at this part.

**Verdict for `I-000102`**: the on-hardware hand-inspection is now **delivered** for one part, with the
artifacts above as evidence. The wider claim ("re-run the four artefacts and hand-inspect ≥5 blocks")
is met at *one* part; a corpus-wide claim would need more parts.
