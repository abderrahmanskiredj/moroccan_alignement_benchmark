# The Moroccan Alignment Benchmark

![Evaluation pipeline](assets/diagram.png)

A Moroccan-authored, human-validated benchmark for evaluating whether large language models can **retrieve Moroccan knowledge, produce natural Moroccan Darija, and respond appropriately in Moroccan cultural, social, and institutional contexts**.

The benchmark contains **1,672 Arabic-script Darija items** across **8 axes**, **3 evaluation dimensions**, and **4 complementary formats**. It evaluates **17 systems** under a common generation-only protocol and releases the validation trail, model responses, scores, LLM-judge records, structured error flags, and error-analysis artifacts needed to audit or recompute the reported results.

---

## Benchmark at a glance

| Format | Purpose | Released items |
|---|---|---:|
| Multiple choice | Recognition of Moroccan knowledge and linguistic/cultural distinctions | 577 |
| Binary acceptability | Discrimination between acceptable and unacceptable formulations/behaviours | 231 |
| Short answer | Free recall of verifiable Moroccan knowledge | 284 |
| Open-ended | Situated generation: factual grounding, Darija nativeness, and institutional/social alignment | 580 |
| **Total** |  | **1,672** |

The pre-validation pool contained **1,740 items**: 588 MCQ, 236 binary, 296 short-answer, and 620 open-ended items. After cross-validation and adjudication, **68 items were rejected**, leaving the 1,672-item released benchmark.

### Three evaluation dimensions

1. **Cultural and social alignment**
2. **Darija nativeness**
3. **Moroccan national/domain knowledge**

### Eight axes

- Culture
- Respect and Social Norms
- National Identity
- Monarchy
- Religion
- Nativeness
- History
- Geography

### Released distribution

| Axis | MCQ | Binary | Short answer | Open-ended | Total |
|---|---:|---:|---:|---:|---:|
| Culture | 101 | 33 | 92 | 82 | 308 |
| Respect and Social Norms | 72 | 40 | 0 | 67 | 179 |
| National Identity | 70 | 62 | 72 | 71 | 275 |
| Monarchy | 0 | 0 | 0 | 141 | 141 |
| Religion | 0 | 0 | 0 | 96 | 96 |
| Nativeness | 95 | 95 | 0 | 123 | 313 |
| History | 170 | 0 | 113 | 0 | 283 |
| Geography | 69 | 1 | 7 | 0 | 77 |
| **Total** | **577** | **231** | **284** | **580** | **1,672** |

---

## Design principle: format follows capability

The benchmark deliberately does not reduce Moroccan competence to a single multiple-choice score.

- **MCQ** measures recognition.
- **Short answer** removes answer candidates and measures retrieval.
- **Binary acceptability** probes linguistic and pragmatic discrimination.
- **Open-ended generation** requires a response that is simultaneously useful, factually grounded, linguistically natural, and appropriate to the Moroccan context.

All evaluated systems are run under a **generation-only** setup. No log-likelihood or perplexity scoring is used.

---

## Human construction and validation

### Item construction

The items were authored by **30 Moroccan annotators from different regions**, all fluent speakers of Moroccan Darija.

Factual items were anchored in written sources whenever available. Nativeness and behavioural items were designed to capture phenomena that are poorly represented by translated benchmarks, including:

- Moroccan idioms and collocations,
- MSA overproduction,
- French calques,
- non-Moroccan Arabic dialect forms,
- register mismatch,
- literal interpretation of idiomatic expressions,
- socially inappropriate or overly flat formulations.

### Blind cross-validation

Validation used pseudonymous identifiers.

- **MCQ, binary, and short answer:** `ANN_01` through `ANN_09`
- **Open-ended:** `ANN_01` through `ANN_10`

Assignments were blind, seeded, load-balanced, and shuffled. Validators did not receive the administrator-only answer key as a target to confirm.

The validation policy distinguishes:

- **documented items**, which can be checked against written evidence, and
- **tacit items**, which depend on native linguistic or cultural judgement.

For documented items, source checking was mandatory. For tacit items, documentary lookup was forbidden so that the validation measured independent native judgement rather than source retrieval.

The campaign produced **2,930 human validation judgements**:

| Format | Human judgements |
|---|---:|
| MCQ | 835 |
| Binary | 472 |
| Short answer | 355 |
| Open-ended | 1,268 |
| **Total** | **2,930** |

Every escalated case was resolved by senior adjudication.

The complete policy used by the released repository is in [`configs/annotation_policy.yaml`](configs/annotation_policy.yaml).

---

## Evaluated systems

The benchmark evaluates **17 systems** spanning:

- general-purpose multilingual models,
- Arabic-centric models,
- Moroccan-Darija-adapted models,
- proprietary API-served systems,
- self-hosted open-weight systems.

The canonical model identifiers used by the repository are defined in:

```text
configs/models.yaml
```

All 17 systems were evaluated on MCQ, binary, and open-ended generation. The short-answer run contains 16 systems because Mistral-Saba was not included in that run.

---

## Inference protocol

The common evaluation protocol is defined in [`configs/evaluation.yaml`](configs/evaluation.yaml).

Core rules:

- zero-shot evaluation,
- Arabic-script Darija prompts,
- no system prompt,
- one generation per item,
- greedy decoding,
- temperature `0`,
- generation-only evaluation for every format,
- locally served open-weight models via vLLM in half precision,
- no parsing or appended output instruction for open-ended items.

### Output contracts

**MCQ and binary**

Models are asked to return a single option letter. Evaluation nevertheless uses a deterministic cascading parser so that recoverable formatting variation does not become an arbitrary scoring error.

**Short answer**

The final answer is extracted from:

```text
<FINAL_ANSWER>...</FINAL_ANSWER>
```

The extracted span is graded for **semantic correctness**, not exact string identity, against the final adjudicated reference and the accepted answer variants collected during validation.

**Open-ended**

The raw generation is scored directly. No answer-format instruction is appended and no parser is applied.

---

## Scoring

### MCQ and binary

The primary metric is **strict accuracy**:

```text
correct / all items
```

Unparseable answers count as incorrect. Coverage is reported separately.

The parser applies, in order:

1. explicit option-letter extraction,
2. verbatim option-string matching,
3. normalized option matching.

### Short answer

A dedicated LLM-as-judge scoring pipeline determines whether the extracted answer is semantically equivalent to the adjudicated reference or one of its accepted variants.

Transport/API failures are conservatively counted as incorrect.

### Open-ended generation

Open-ended responses are independently evaluated by three **disjoint** judges:

1. **Moroccan domain knowledge and factual quality**
   - factual coverage and Moroccan grounding
   - factual accuracy and hallucination control

2. **Moroccan Darija nativeness**
   - Darija/pragmatic understanding
   - language and register mirroring
   - dialect consistency
   - loanwords and code-switching
   - lexical, idiomatic, and stylistic naturalness

3. **Moroccan public-institution alignment**
   - Monarchy / Royal Institution
   - territorial integrity
   - religion and the official religious framework
   - Moroccan diversity and stereotypes
   - `sswab`, `adab`, dignity, and socially appropriate conflict handling

The prompts are released in:

```text
prompts/judges/
├── MOROCCAN DARIJA NATIVENESS JUDGE.md
├── MOROCCAN DOMAIN KNOWLEDGE AND FACTUAL QUALITY JUDGE.md
└── moroccan_public_institution_alignment_judge_v3.md
```

All three open-ended judges use **GLM-5.2** at temperature `0`.

### Open-ended label scale

| Label | Numeric value |
|---|---:|
| Excellent | 4 |
| Acceptable | 3 |
| Tolerated | 2 |
| Severe | 1 |
| Fail | 0 |

Each judge returns categorical sub-rubric decisions and structured error flags. The judge-level final label is the **worst applicable sub-rubric label**.

For item \(i\) and model \(m\):

- **Strict score:** minimum of nativeness, factual, and alignment scores
- **Soft score:** mean of the three dimension scores
- **Deployable rate:** proportion of responses with all three dimensions at least `Acceptable`
- **Fail rate:** proportion receiving `Fail` from at least one judge

“Deployable” is only the benchmark name for simultaneous passage of these three measured gates; it is **not** a certification of production safety or deployment readiness.

For the 580 open-ended items and 17 systems, the release contains:

- **9,860 model responses**
- **29,580 judge decisions**
- **48,857 structured error flags**

Because categorical judgements and individual flags are released, alternative aggregations can be recomputed without re-running model inference.

---

## Repository structure

The repository preserves both the final benchmark and the intermediate validation/evaluation artifacts.

```text
.
├── README.md
├── requirements.txt
├── .gitattributes
├── .gitignore
│
├── assets/
│   └── diagram.png
│
├── configs/
│   ├── annotation_policy.yaml
│   ├── evaluation.yaml
│   └── models.yaml
│
├── data/
│   ├── 00_prevalidation/
│   │   └── items_prevalidation.xlsx
│   │
│   ├── 01_cross_annotation/
│   │   ├── Binary questions/
│   │   │   ├── admin/
│   │   │   ├── annotateurs/
│   │   │   ├── annotator_deliverables/
│   │   │   └── binary_consolidation/
│   │   ├── MCQ/
│   │   │   ├── admin/
│   │   │   ├── annotateurs/
│   │   │   ├── annotator_deliverables/
│   │   │   └── mcq_consolidation/
│   │   ├── Open questions/
│   │   │   ├── admin/
│   │   │   ├── annotateurs/
│   │   │   └── annotator_deliverables/
│   │   └── Short answers/
│   │       ├── admin/
│   │       ├── annotateurs/
│   │       ├── annotator_deliverables/
│   │       └── short_answers_consolidation/
│   │
│   └── 02_final_benchmark/
│       ├── final_binary_no_responses.xlsx
│       ├── final_shorts_no_responses.xlsx
│       ├── open_question_final_no_responses.xlsx
│       └── qcm_final_no_responses.xlsx
│
├── outputs/
│   ├── final_binary_scores.xlsx
│   ├── final_short_answers_scores_llm_judge.xlsx
│   ├── open_questions_final_scores.xlsx
│   ├── qcm_final_scores.xlsx
│   ├── cross_annotation_scores_and_statistics/
│   ├── glm52_judge_outputs/
│   │   ├── eval_report.xlsx
│   │   ├── flags.jsonl
│   │   └── judgments.jsonl
│   └── model_responses/
│       ├── final_binary_with_responses.xlsx
│       ├── open_question_final_with_responses.xlsx
│       ├── qcm_final_with_responses.xlsx
│       └── short_answers_final_with_responses.xlsx
│
├── prompts/
│   └── judges/
│
├── scripts/
│   ├── 01_create_annotation_splits/
│   ├── 02_merging_annotations/
│   ├── 03_run_inference/
│   ├── 04_scoring/
│   └── 08_prepare_error_analysis.py
│
└── error_analysis/
    ├── open_questions_error_analysis/
    │   ├── figures/
    │   ├── 00_README.csv
    │   ├── 01_reconciliation.csv
    │   ├── 02_leaderboard.csv
    │   ├── 03_top5.csv
    │   ├── 04_item_hardness.csv
    │   ├── 05_hard_summary.csv
    │   ├── 06_enrichment.csv
    │   ├── 07_FN_by_model.csv
    │   ├── 08_FN_global.csv
    │   ├── 09_sub_global.csv
    │   ├── 10_sub_by_model.csv
    │   ├── 11_tags_global.csv
    │   ├── 12_tags_by_model.csv
    │   ├── 13_diff_summary.csv
    │   ├── 14_spearman.csv
    │   └── open_error_analysis.xlsx
    └── qcm_binary_shorts_error_analysis/
        ├── figures/
        ├── closed_formats_long.csv
        ├── error_analysis_results.xlsx
        ├── ERROR_ANALYSIS_SUMMARY.md
        ├── hard_item_enrichment.csv
        ├── item_metrics.csv
        └── model_sets.json
```

---

## Where to find the main release artifacts

### Response-free benchmark

```text
data/02_final_benchmark/
```

These files contain the released benchmark items without evaluated-model responses.

### Model generations

```text
outputs/model_responses/
```

These workbooks pair the benchmark items with the responses generated by the evaluated systems.

### Final scores

```text
outputs/
```

- `qcm_final_scores.xlsx`
- `final_binary_scores.xlsx`
- `final_short_answers_scores_llm_judge.xlsx`
- `open_questions_final_scores.xlsx`

### Human validation statistics

```text
outputs/cross_annotation_scores_and_statistics/
```

This directory contains the released validation/reliability workbooks for all four formats.

### Open-ended judge records

```text
outputs/glm52_judge_outputs/
```

- `judgments.jsonl` — structured categorical judge records
- `flags.jsonl` — structured error flags
- `eval_report.xlsx` — aggregated judge/evaluation report

### Error analysis

```text
error_analysis/
```

The repository includes both:

- closed-format hardness/discrimination analysis, and
- open-ended factual/nativeness/alignment decomposition with per-model and global error-tag summaries.

---

## Reproducing the pipeline

The repository exposes the implemented stages rather than a single opaque evaluation command.

### 1. Create annotation splits

```text
scripts/01_create_annotation_splits/
```

Contains separate splitters for MCQ, binary, short-answer, and open-ended validation.

### 2. Merge, consolidate, and adjudicate annotations

```text
scripts/02_merging_annotations/
```

Contains consolidation scripts and the notebooks used to compute cross-validation statistics.

### 3. Run model inference

```text
scripts/03_run_inference/
```

Contains the four format-specific inference notebooks and the vLLM serving/evaluation script.

### 4. Score the benchmark

```text
scripts/04_scoring/
```

Contains:

- deterministic MCQ scoring,
- deterministic binary scoring,
- LLM-as-judge short-answer scoring,
- GLM-5.2 open-ended rubric judging.

### 5. Reproduce the error analysis

```text
scripts/08_prepare_error_analysis.py
error_analysis/
```

---

## Interpretation and intended use

This benchmark is intended for:

- language-model evaluation,
- analysis of Moroccan factual and cultural grounding,
- Darija nativeness evaluation,
- diagnosis of failure modes in Moroccan-facing assistants,
- comparison of recognition, retrieval, discrimination, and situated generation.

It is **not** intended to:

- profile individuals,
- decide whether a person is “Moroccan enough,”
- assess an individual's cultural authenticity,
- make automated decisions about people,
- certify a model as generally safe or production-ready,
- replace domain-specific evaluation for medical, cybersecurity, privacy, self-harm, illegal-activity, or other deployment risks.

Morocco is regionally, socially, generationally, linguistically, and culturally diverse. The benchmark operationalizes explicit evaluation criteria; it does not claim that one response, dialectal realization, or social behaviour is the only valid Moroccan one.

---

## Reproducibility note

The release includes the response-free benchmark, cross-annotation artifacts, adjudicated/final consolidations, validation statistics, model configurations, evaluation policy, annotation policy, judge prompts, inference notebooks, scoring scripts, model responses, judge records, error flags, and error-analysis outputs.

This allows the reported aggregate metrics—and alternative open-ended aggregations—to be audited from released artifacts without re-running the evaluated models.
