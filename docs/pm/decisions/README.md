# docs/pm/decisions — what waits on the owner

One note per question that a person has to settle before a task of the work unit in progress
can go on. `/next` writes a note when a task is blocked or reaches a checkpoint. `/plan` writes
one for a run that deletes, takes longer than one hour on the GPU, or pays for model calls.

## The shape of a note

```yaml
---
type: pm-decision
epic: <unit id>
status: open            # settled, once answered
opened: YYYY-MM-DD
waiting_on: the owner
blocks: TASK-00N
tags: [pm/decision]
---
```

The body says what was found, the options, what each option means for the owner, and a
recommendation. It explains the words it uses: the reader was not in the session. For a run
that costs, it gives the counts, the hours and the amount, with the arithmetic.

## What happens to a note

- **Answered:** the answer and who gave it are written into the note under "The answers", and
  `status` becomes `settled`. `/ship` adds one entry to [`DECISIONS.md`](../../../DECISIONS.md)
  that links the note.
- **Still open when the unit ships:** the question moves to
  [`OPEN_QUESTIONS.md`](../../../OPEN_QUESTIONS.md) with a row in the backlog's question table,
  and the note is deleted.
- **A settled note stays here** when its epic is archived. Other documents link it as the
  reason for what was built.

An answer that an assistant gave in the owner's place is labelled as the assistant's, in the
note and wherever the answer is used.

The board script skips this file: it is the folder's index, not a decision.
