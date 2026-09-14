# Human audit protocol for the Moroccan Alignment Benchmark

This package prepares three independent checks. The sampling seed is fixed at
`20260816`, source hashes are recorded, and reviewer workbooks hide model names
and automated decisions.

## 1. Open-ended judge validation

- 100 unique model responses sampled from the 9,860-response matrix.
- Stratified to reproduce the open-item axis distribution while balancing the
  17 evaluated systems (5–6 responses per system).
- No LLM-judge label is used during sampling. This avoids constructing the
  validation set around the judge's own predictions.
- Every response is independently rated by two of four Moroccan reviewers.
- Pair rotation is balanced: 200 assignments, exactly 50 per reviewer, with all
  six reviewer pairs used almost equally.
- The response receives one five-level human label for factual quality, Darija
  nativeness and Moroccan public-institution alignment.
- Reviewers use the full released rubrics and remain blind to model identity,
  judge labels and the other review.

The paper must call these **100 model responses**, not 100 open items. Rubrics
must be frozen before this fresh sample is annotated.

## 2. Short-answer judge audit

- 50 unique model responses.
- Exactly 25 LLM-accepted and 25 LLM-rejected cases.
- All 16 short-answer systems contribute 3 or 4 responses.
- Axis and normalized difficulty distributions are balanced as closely as the
  class/model constraints permit.
- A single blinded reviewer assigns `Correct` or `Incorrect`, with confidence,
  reason category and comment.

Because the design fixes the LLM prediction prevalence at 50/50, report the
confusion matrix, class-specific agreement, sensitivity, specificity, balanced
accuracy and Cohen's kappa. Do not present raw agreement as population-wide
judge accuracy without applying sampling weights.


## Repository placement

Copy the script to:

`scripts/05_human_audits/prepare_and_score_human_audits.py`

The default inputs match the repository tree:

- `outputs/model_responses/open_question_final_with_responses.xlsx`
- `outputs/glm52_judge_outputs/judgments.jsonl`
- `outputs/open_questions_final_scores.xlsx`
- `outputs/final_short_answers_scores_llm_judge.xlsx`

## Commands

From the repository root:

```bash
python scripts/05_human_audits/prepare_and_score_human_audits.py inspect
python scripts/05_human_audits/prepare_and_score_human_audits.py prepare
python scripts/05_human_audits/prepare_and_score_human_audits.py score
```

The generated directory is:

`data/03_human_judge_audits/`

It contains:

- `ADMIN_sampling_manifest.xlsx` — keep private;
- `sampling_manifest.json` — seed, counts and source hashes;
- four blinded open-validation workbooks, 50 responses each;
- one blinded short-answer workbook, 50 responses;


Run
the same command with the complete repository file to create all three.

After the reviewer files are returned, keep their filenames unchanged and run
`score`. If the two open reviewers disagree, the first scoring pass creates
`open_validation/OPEN_ADJUDICATION.xlsx`. The senior adjudicator fills only its
yellow cells without seeing the automated judge labels, saves it, and reruns
`score`. The final run creates:

- `ADMIN_validation_results.xlsx`;
- `publication_metrics.json`;
- human–human and judge–human confusion matrices;
- quadratic-weighted kappa and within-one-level agreement for open answers;
- the short-answer confusion matrix, sensitivity, specificity, balanced
  accuracy, Cohen's kappa and Wilson intervals;


## Immediate paper corrections

Until the new annotation is finished, remove or replace the existing exact
judge–human values (`0.71`, `0.66`, `0.74`, and their within-one-level rates).
New raters and a new independent sample will not reproduce those values exactly.

After completion, describe the protocol as:

> On a fresh held-out sample of 100 model responses, stratified across systems
> and open-ended benchmark axes, each response was independently evaluated by
> two of four Moroccan reviewers using the same five-level scales as the three
> rubric judges. Model identity, automated labels and the other review were
> hidden during annotation.

Do not claim human–human or judge–human statistics until the returned reviewer
workbooks have been consolidated and checked.
