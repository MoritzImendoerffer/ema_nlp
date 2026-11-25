# The error census and the review sitting: do the checks catch what goes wrong?

**Status:** proposed 2026-11-25 · backlog row 20 · no work unit yet · needs row 18 (the
answer record) and the owner's time. The method rests on published studies that a
literature session read and checked against the papers
([`../eval/2026-11-25_direction_review.md`](../eval/2026-11-25_direction_review.md),
section 5.1). The lead did not read them.

Two terms. An **error census** is a person reading claims of stored answers and labelling
each as supported or not, with the kind of error. A **sitting** is one session in which a
person reviews prepared answers while the time and the missed errors are recorded.

## The problem

The owner wants a person to confirm an agent's answer quickly, with code doing part of the
checking (direction review, section 1). Row 18 adds four checks by plain code. Nothing yet
says what those checks are worth.

1. **No check has been scored on an error that occurred.** The only labels of stored
   claims are an assistant's: two model annotators sorted 60 claims on 2026-11-25. At
   least one of them found 17 of the 60 not fully backed by the passages the agent had
   received. No person has looked at one of them.
2. **Injected errors cannot stand in.** Detectors trained on synthetic factual errors
   scored 91.2 to 97.8 on synthetic errors and 50.9 to 54.2 on real ones of one dataset,
   where 50 is chance (Goyal and Durrett 2021).
3. **The fast way to review is the unsafe one.** Showing a person only the claims that a
   check flagged saves time. A planted prescribing error was missed by 77.8% of 120
   medical students when decision support was present and silent, and by 49.1% without
   decision support (Lyell et al. 2017). The same can happen with claims that pass a check
   and are wrong.
4. **The store holds almost no human verdicts.** A reviewer counted 2 citation verdicts in
   `mlflow.db` on 2026-11-25.

## The idea

First count, then decide whether to test people. A person labels the claims of whole
answers with a fixed codebook. The checks of row 18 are then scored on those labels. One
number from that census settles most of the question: **the number of wrong claims among
the claims that every check passed.** A reviewer who is shown only the flagged claims
misses exactly those, by construction. If the census finds none in a sample of useful size,
flagged-only review is safe on this material and no sitting is needed. If it finds some, a
sitting compares two ways of showing answers that could catch them.

## What it deliberately does not do

- **No injected error is reported as a result.** A test may corrupt a record to show that
  a check fires.
- **No general statement from one reviewer.** One person's sitting is a case study: counts,
  minutes and intervals over items, and no claim about reviewers.
- **No new review interface.** The census uses a sheet. The sitting uses static pages.
- **No mark of "passed" beside a claim** in the arm that shows the full answer. A checklist
  of met requirements raised confidence after wrong approvals (Grunde-McLaughlin et al.
  2026, preprint, 12 people).
- **The model's labels never remove a claim.** They may order the work.

## Implementation sketch

Size: M, most of it a person's time. Code: a sampler, a sheet generator, a validator of the
label file and a scorer, each small.

### Step 0 — a pilot that needs no code and no model call

The 60 claims sampled on 2026-11-25 are in
`$EMA_RESULTS_DIR/2026-11-25_direction_review/`, with two sets of assistant labels. A person
labels 30 of them with the codebook below, without seeing those labels. At 2.53 minutes
per claim (the reading time measured by Si et al. 2024) that is about 75 minutes. It shows
whether the codebook can be applied, and how far the assistant's labels agree with a
person's. Limit: these answers predate row 18, so no check of row 18 can be scored on them.

### Step 1 — the census

| Part | Design | Rests on |
|---|---|---|
| Unit | One claim of one stored answer, shown with the question, its citation and **all** passages the agent received, not only the cited one. An answer without claims is counted | Direction review, rule 5 |
| Kind of claim | restatement, merge, value (a number, date or name), count or comparison, inference, generalisation, abstention | The labels of 2026-11-25, mapped to the claim types of Schlichtkrull et al. 2023 so that shares compare |
| Support | fully, partly, not supported, contradicted, each judged against the received passages | |
| Kind of error | evident conflict, subtle conflict, evident unsupported addition, subtle unsupported addition; a flag "true in the world but absent from the passages" | Niu et al. 2024 |
| | A second attribute: entity, event, noun phrase, other | Goyal and Durrett 2021 |
| | Two retrieval labels: the citation points at the wrong passage; the source is superseded | Ouyang et al. 2025 |
| Sample | Whole answers drawn at random. About 100 claims, which is about 26 answers at the 3.8 claims per answer of the stored runs. Intervals are computed over answers, because claims of one answer are not independent | Miller 2024, preprint |
| Time | About 4 hours for 100 claims | Si et al. 2024 |
| Agreement | A second person labels at least 30 claims. Cohen's kappa per label set | Goyal and Durrett 2021 report 74% agreement on spans and 84% on categories over 50 summaries |
| Model pre-sort | The assistant's labels may order the claims. The person's first 30 labels are made without seeing them, because a visible aid steers the reader | Skitka 1998; Lyell et al. 2017 |

The answers come from one evaluation run made after row 18 has shipped, so that each claim
has a passage tag, a quote and check outcomes. That run pays for model calls and needs the
owner's yes, with the cost in a decision note.

### Step 2 — the checks, scored on the census

For each check of row 18: recall per kind of error, and false alarms on claims that the
person called fully supported, each with n and an interval over answers. Then the central
count: wrong claims among the claims that passed every check, by kind of error.

### Step 3 — the sitting, only if step 2 finds wrong claims among the passed ones

| Part | Design | Rests on |
|---|---|---|
| Layout | The same person sees every arm, on different answers, in balanced order | Lyell et al. 2017 |
| Arm A | The full answer with its sources. No mark on a claim that passed | Grunde-McLaughlin et al. 2026 |
| Arm B | The flagged claims only. Its misses among passed claims equal the census count, so it needs no sitting | By construction |
| Arm C | The flagged claims plus a random share of the passed claims | No precedent was found for this arm |
| Errors | Real ones, at the rate at which they occur, with error-free answers mixed in. If the share of wrong answers is raised, the page says by how much and treats detection as an upper bound | Evans et al. 2013; Zhou et al. 2026 |
| First number | Wrong claims missed among the claims that passed | Skitka 1998; Lyell et al. 2017 |
| Further numbers | Minutes per answer, misses among flagged claims, correct claims wrongly rejected | |
| Pace | About 6 full answers per hour, an estimate from the reading time above | |
| Not relied on | An instruction to verify, or a second reviewer. Neither reduced misses | Skitka 1998, second study, 144 people |

## Verification

- **The codebook is a file** in `benchmark/`, with one example per label taken from the
  pilot. A validator rejects a label file with an unknown label, a missing claim or a claim
  that is not in the sample.
- **The label file is authored data.** A tool writes a candidate sheet. A person fills in a
  copy, and no tool overwrites it.
- **The scorer has tests** on a small label file made by hand: recall and false alarms per
  kind of error, and the interval over answers.
- **The page in `docs/eval/`** names the run, the benchmark file and its commit, the
  generator, who labelled, n claims and n answers, the agreement, and every claim that the
  two readers labelled differently.
- **What would count against the idea of row 18:** recall of the quote check near zero on
  the kinds of error that occur most, or a false-alarm rate so high that most supported
  claims are flagged.

## Open questions

| | Question | Options | Recommendation |
|---|---|---|---|
| 1 | Who labels? | (a) the owner; (b) the owner and one second person for 30 claims; (c) an assistant, labelled as such | (b). (c) alone repeats what exists. **Needs the owner:** about 4 hours for 100 claims, after a pilot of about 75 minutes |
| 2 | Which answers feed the census? | (a) one run of the present 45 questions with `naive_rag`; (b) wait for benchmark v0 (row 15) | (a) first. It is the cheapest material with records. Repeat on benchmark v0, which holds the classes where derivations occur |
| 3 | Is the pilot of step 0 done before row 18? | yes; no | Yes. It costs no model call and tests the codebook before code is written around it. **Needs the owner** |
| 4 | Where are labels entered? | (a) a sheet (CSV) beside a static page per answer; (b) the chat app's review panel; (c) MLflow's assessment view | (a). It adds no service, and the panel is not in the repository (`public/elements/` is in `.gitignore`) |
| 5 | What does one reviewer's sitting count as? | Decide before the sitting | A case study: counts and minutes with intervals over items. The census count is the main result |
| 6 | How many errors among passed claims justify a sitting? | Decide before the census is read | Any, on a sample of 100 claims. With none, report the upper bound that a sample of that size allows, and repeat on benchmark v0 |

## For the implementing session

- Nothing here starts before row 18 has shipped, except step 0.
- The model's labels order the sheet. They are not shown for the first 30 claims and never
  remove a claim (direction review, section 6.1, rule 2).
- A label that an assistant gave is stored as the assistant's (planning workflow, rule 11).
- The run that feeds the census is a paid run. Write the decision note with the cost first.
- The references of every study named here are in the direction review, section 5.1,
  except these four, which the literature session also read: Schlichtkrull, M. et al.
  (2023), AVeriTeC, NeurIPS 2023 Datasets and Benchmarks, arXiv:2305.13117; Ouyang et al.
  (2025), ACL 2025, arXiv:2503.04800; Miller (2024), preprint, arXiv:2411.00640; Lee et al.
  (2026), ICML 2026, arXiv:2511.21140. The last one bears on the pre-sort: testing how many
  wrong claims the assistant's labels miss needs about 200 labels, and 30 only show whether
  the two agree at all.
