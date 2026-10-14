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

## Second evaluation (`live_20261014_191748.json`): repetition

The raw-output check failed for four cases (`rich_contextual` 10 duplicates + 1 tendency, `sparse` 1 duplicate +
3 trimmed, `stated_sensitive` 5, `long` 2). Grounding, sensitive-attribute, exact-phrase, injection and contradiction
checks passed; the saved profiles were safe. The failures were repetition, not invention.

**Diagnosis.** That file kept only the *final* profiles, so the removed entries were not saved. What can be said:
the validator then only removed text that was identical after normalisation, so every one of the 10 / 1 / 5 / 2
removed entries was an **exact repetition** (the same string in two sections). The cleaned profiles still held many
**reworded repetitions** the old validator could not see: "Teases her closest friends constantly" in
`warmth_and_expressiveness`, `relationships_and_social` *and* a context tendency; "Loves long walks, filter coffee,
and old Hindi film songs" as one trait and again as three interests; every situational behaviour (grandfather,
work, weddings, strangers) restated as a trait. A smaller group is **legitimate related observations** (for example
"Shows care by turning up with food" and the same with "instead of saying 'I love you'") and stays. The missing
space in `shortnessin those situations` is not in the data: the saved summary has a normal space, and no invisible or
odd character exists anywhere in the file. It is a terminal soft-wrap/copy artefact. The console now prints the summary
pre-wrapped, and tests pin that parsing and grounding never touch internal whitespace.

**Changes.**
- Prompt: one fact, one place; every entry must add something new; no restated examples; one sentence of the source is
  one entry; situational behaviour lives in `context_tendencies` only; empty lists are normal; guidance may not just
  restate a trait; each uncertainty is a different question. Rich descriptions are still asked to keep every distinct detail.
- Validator: after exact duplicates, an entry is removed only when another entry already says *all* of it (its content
  words, lightly stemmed, are contained in the other's) and the other adds no negation, number or opposite attitude.
  Items are compared across sections and against evidence-backed tendencies (a tendency without real evidence is
  dropped first and never justifies removing anything). Guidance and uncertainties are compared only with their own
  kind. Entries that share wording but differ ("Loves loud parties" / "Hates loud parties", other person, other
  setting, other number) both stay. Nothing is rewritten and no replacement text is ever invented.
- Evaluator: checks are tiered (critical / raw / quality / format). Raw-output cleanup is still a FAIL, now with
  `exact_duplicates` and `near_duplicates` shown separately; nothing is excluded or re-scored. The results file now
  also stores the model's raw output and every removed entry (with reason and the entry that covers it) so a failure is
  diagnosable offline. These live only in the local git-ignored file; the API and database never see them.

**Offline result on the saved run** (`--rescore`; cleaned profiles, so *not* the original raw counts): no critical
failure; the new rules would additionally remove 5 / 14 / 7 reworded repeats (smoke / rich_contextual / long); every
removal was read and is the same observation reworded or contained in a longer entry. Reworded repeats that share
only part of the wording (food example) are not detected and are listed under QUALITY for a human.

**Not proven.** Whether the new prompt makes the model repeat less is untested until a live run. The validator removes
repetition; it cannot judge that a quote supports a tendency, that wording is not embellished, or that guidance is
sensible (for example the tautological "Respond in a quiet manner, reflecting Dev's quiet nature").

## Third evaluation (`live_20261014_220756.json`): final offline tuning

Critical checks all passed again; the raw-output check still failed in four cases (rich_contextual 10 exact + 12 near,
sparse 1 sparse-limit trim, stated_sensitive 1 near, long 4 exact + 4 near). The file now holds the raw output and every
removal, so this was read directly. (It records no dropped context tendency in any case; the one noted for the first
run is not in this file.)

**What the removal records show.** All 31 removals were correct: every "exact" one was identical text copied into a second
section (money in two sections, "teases her closest friends constantly" in three); every "near" one was an entry fully
contained in a context tendency or in a longer entry (each situational behaviour restated as a trait; one sentence of
three interests split into three; "listens first" in two places). None removed a distinct fact, negation, number or
opposite attitude, and none was justified by an ungrounded tendency. The sparse trim removed a guidance line that
invented a topic ("consider referencing cricket"); the guidance that survived ("not pressuring him to speak more than he
is comfortable with") still adds a comfort need the description never states.

**Prompt.** Replaced the general "one fact, one place" with explicit field ownership: situational behaviour only in
`context_tendencies`; interests only in `interests_and_habits` (one entry per sentence, never as a core trait); dislikes
in boundaries or communication preferences, not both; reactions in one of response/empathy; a final "delete any entry
another already says" pass. Rich descriptions must keep every distinct detail and every contradiction or exception.
Guidance may not restate a trait or a context entry or invent topics, comfort levels, pressures or needs, and is `[]`
for sparse input unless the description says how to treat the person. The summary may not add moods or adjectives
("stays near the snack table" is not "withdrawn"). No new size cap was added.

**Validator.** Removals were appropriate, so the rules were not loosened. Two corrections found while re-running the
saved raw output: (1) the like/dislike detection compared whole words, so "loves/hates/dislikes" were not recognised
as attitudes; they now compare stems, which makes the opposite-attitude guard actually work ("Loves noise" is not
covered by "Hates noise but loves music"). (2) The guard against *extra numbers* in the covering entry was dropped
(an extra number only adds detail; a different number already prevents a match), and an extra attitude blocks removal
only when the shorter entry itself states an attitude. "instead of" and "rather than" count as the same contrast.
Re-running the saved raw outputs: rich_contextual 10 exact / 16 near, long 4 / 5, stated_sensitive 0 / 1; the
additional removals (a restated grandfather behaviour, "dislikes being rushed/interrupted" next to "hates being rushed
and gets short with people who interrupt her", the food line reworded) were all read and are the same observation.
Entries are still never rewritten, and a failing result still leaves the last good profile in place.

**Evaluator.** Sparse input with any guidance now adds a REVIEW item. Raw-output cleanup is still a FAIL.

**Not proven.** Whether the prompt reduces what the model produces is only known from a new live run. The validator
cannot see reworded repeats that share only part of their wording ("after listening" vs "then"), unsupported guidance,
or embellished wording; those stay human-review items.
