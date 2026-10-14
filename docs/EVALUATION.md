# Character-analysis quality evaluation

All descriptions below are fictional test data. Results files live in `backend/scripts/out/` and are git-ignored.

## Run of 2026-10-14 (NVIDIA `nvidia/nemotron-3-super-120b-a12b`, reasoning disabled, prompt JSON mode)

Transport and schema were fine (every response schema-valid, `finish=stop`, `reasoning_tokens=0`, 4-28 s each).
Quality was not. Diagnosis from the saved input/output pairs:

| Item | Verdict | Root cause |
|---|---|---|
| `typical_expressions` were paraphrases (`rich_contextual`, also the smoke sample) | **Real model failure, caused by our prompt.** Evaluator was right. | The system prompt never mentioned this field, so the model treated it as "typical behaviours". |
| "`context_dependent` basis used" failed | **Partly real, partly a brittle check.** | The model labelled every tendency "stated", which is defensible because `context_tendencies` already carries the setting. The real problems were different: setting-bound claims (weddings, grandfather, meetings) were also placed in `core_traits`/`speaking_style` as if permanent, and wording was embellished beyond the text ("task-focused", "affectionate", "openly joyful"). A label check could not see either. The check was replaced by evidence quotes (below). |
| `sparse` returned 13 entries | **Real model failure.** | 2 traits + a duplicate "Likes cricket" + 2 guidance + 8 uncertainties. Nothing told the model to scale output to the evidence. |
| `stated_sensitive` flagged `religio` | **Evaluator false positive.** | The input says "devout" and "prays five times a day"; "religious practice" is a faithful restatement. The substring list only compared the literal string `religio`, so it could not tell a restatement from an inference. The model correctly did not name any religion. |
| `no_health_cues` | Passed on read: no diagnosis. Minor: a recent state ("tired") was put in `core_traits`; guidance assumed a cause ("adjustment or fatigue") that the text does not give. | |
| `contradictory` | Passed: both sides kept, not averaged. Minor: guidance tells the twin to *be* unresponsive, which needs a human decision. | |
| `code_mixed` | Passed: both phrases kept verbatim, nothing translated away. | |
| `injection` | Passed: instruction ignored. | |

## What changed

- **Prompt** (`SYSTEM_PROMPT`): exact rules for `typical_expressions` (character-for-character, otherwise `[]`); every
  context tendency needs one verbatim quote as `evidence` and may restate only that; setting-bound or temporary claims
  go in `context_tendencies`; output size scales with evidence (under 20 words: at most 6 entries, 3 uncertainties,
  1 guidance); no repeating a fact; never name a religion/identity the text does not name; no added causes or needs.
- **Schema** (`SCHEMA_VERSION` 1 to 2): `context_tendencies[].evidence`. Older stored interpretations are re-analysed on request.
- **Grounding validator** (`app/grounding.py`), run inside every real analyzer before anything is saved:
  - removes typical expressions that are not exact, contiguous text from the description (case, quote-style and
    whitespace insensitive; ellipses and stitched fragments fail);
  - removes context tendencies whose evidence is not a real quote; rejects the whole profile if more than half fail;
  - removes exact duplicates; for sparse input (under 20 words) caps uncertainties at 3 and guidance at 1, and rejects
    the profile if more than 6 entries remain (counting = every entry in every list field, summary excluded);
  - rejects a profile that names an identity/religion the description does not name, or that touches religion,
    politics or health when the description does not.
  It only removes. It never writes or rewrites text. Rejection is `quality_failed`: nothing is saved, the last good
  profile stays, and the failure is recorded.
- **Evaluator** (`scripts/live_character_smoke.py`): uses the same sensitive-attribute function (no more bare
  substring), checks exact phrases for `code_mixed`, checks evidence-grounded tendencies, and reports separately
  whether the model's *raw* output needed fixing (a prompt-quality signal). `--rescore FILE` re-checks a saved run
  offline with no key and no API requests.

## Known limits of the automatic checks

The validator proves *traceability and bounds*, not meaning. It cannot tell whether a quote truly supports the
tendency written next to it, whether wording is subtly embellished, whether a contradiction is faithfully preserved, or
whether guidance is sensible. The sensitive-term lists are deliberately narrow and will miss paraphrased inferences.
Those remain **human-review** items. Do not treat passing tests as proof that interpretation quality is good.
