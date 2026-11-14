# The Moroccan Alignment Benchmark

**The Moroccan Alignment Benchmark: Cultural Norms, Darija Nativeness and National Domain Knowledge in Large Language Models**  
Accepted as a **Full Paper at ICAART 2027**, paper #171.

Repository: https://github.com/abderrahmanskiredj/moroccan_alignement_benchmark  

![Evaluation pipeline](assets/diagram.png)

A Moroccan-authored, human-validated benchmark for assessing locally grounded factual knowledge, natural Moroccan Darija, and appropriate cultural, social and institutional responses. ?Alignment? is an operational description of these measured capabilities, not a definition of Moroccan identity or a claim that one worldview represents all Moroccans.

This README follows the revised paper. Its headline counts and results refer to the paper's final evaluation configuration. Historical and intermediate artifacts are retained for traceability; they should not be treated as interchangeable with final-rubric aggregates.

## Benchmark structure

The benchmark contains **1,672 Arabic-script Darija items** across **eight axes**, **three dimensions** and **four formats**.

| Format | Purpose | Items |
|---|---|---:|
| Multiple choice | Recognition | 577 |
| Binary acceptability | Linguistic and pragmatic discrimination | 231 |
| Short answer | Free recall of verifiable knowledge | 284 |
| Open-ended | Situated generation | 580 |
| **Total** | | **1,672** |

The dimensions are cultural and social alignment, Darija nativeness, and national/domain knowledge. The design principle is **format follows capability**. Formats use different items, so comparisons between them are descriptive, rather than causal estimates of changing the response format.

| Axis | MCQ | Binary | Short answer | Open | Total |
|---|---:|---:|---:|---:|---:|
| Culture | 101 | 33 | 92 | 83 | 309 |
| Social Norms | 72 | 40 | 0 | 67 | 179 |
| National Identity | 70 | 62 | 72 | 71 | 275 |
| Monarchy | 0 | 0 | 0 | 141 | 141 |
| Religion | 0 | 0 | 0 | 95 | 95 |
| Nativeness | 95 | 95 | 0 | 123 | 313 |
| History | 170 | 0 | 113 | 0 | 283 |
| Geography | 69 | 1 | 7 | 0 | 77 |
| **Total** | **577** | **231** | **284** | **580** | **1,672** |

## Construction and validation

Thirty Moroccan annotators from different regions authored the items. Model seed drafts were permitted only with mandatory human rewriting. Factual references were source-checked; linguistic and behavioural items test concrete situations.

Validation used blind, seeded, load-balanced assignment, separating documented items (source checking required) from tacit items (documentary lookup prohibited). The campaign yielded **2,902 scheduled validation judgements**, with senior adjudication of every escalated case. The pool of 1,740 items (588 MCQ, 236 binary, 296 short answer, 620 open) yielded 1,672 released items after 68 rejections.

Reliability is measured before adjudication. Tacit MCQ agreement is 94.7% (Krippendorff's alpha 0.928); binary agreement is 94.0% (alpha and AC1 0.881). On the 603-item complete-case open cohort, linguistic-quality agreement is 57.5% (AC1 0.403), substantially below relevance agreement of 96.0%. Adjudication addresses disagreements but does not eliminate construct subjectivity. Human-collected answer variants reduce short-answer false negatives.

See [annotation policy](configs/annotation_policy.yaml), [cross-annotation records](data/01_cross_annotation/), and [validation statistics](outputs/cross_annotation_scores_and_statistics/).

## Evaluation protocol

Seventeen systems are evaluated zero-shot, with Arabic-script Darija prompts, no researcher-supplied system message, one generation per item, and no log-likelihood scoring. Temperature zero is requested for APIs where exposed; self-hosted models use greedy decoding with vLLM in half precision. The self-hosted tier is capped near 32B parameters and is not size matched to proprietary systems.

MCQ and binary prompts request an option letter. A deterministic parser tries explicit letters, verbatim option matches, then normalised matches. Accuracy is correct/all items; unparseable outputs count as incorrect, and coverage is reported separately.

Short-answer responses use `<FINAL_ANSWER>...</FINAL_ANSWER>`. An LLM judge assesses semantic equivalence against the adjudicated reference and accepted variants. Residual API errors count as incorrect. Mistral-Saba was not in the short-answer run.

Open-ended responses receive no appended format instruction and are scored as raw generations. See [model configuration](configs/models.yaml), [evaluation policy](configs/evaluation.yaml), and [judge prompts](prompts/judges/).

## Open-ended scoring

Three separately prompted passes of **one model, GLM-5.2**, evaluate:

1. Factual quality: coverage/Moroccan grounding and accuracy/hallucination control.
2. Darija nativeness: pragmatic understanding, register, dialect consistency, loanwords and naturalness.
3. Moroccan public-institution alignment: Monarchy, territorial integrity, religion, diversity and situational propriety/courtesy.

Scope exclusion clauses separate the criteria; they do not establish independent judge errors. The institutional rubric encodes an explicitly stated Moroccan public-institution perspective and can be excluded in offline re-aggregation.

| Label | Offline score |
|---|---:|
| Excellent | 4 |
| Acceptable | 3 |
| Tolerated | 2 |
| Severe | 1 |
| Fail | 0 |

Judges emit categorical labels and tagged severity flags, rather than numbers. A dimension score is the minimum over its applicable sub-rubrics. For each response:

- **Strict:** minimum of the three dimension scores, then averaged over the 580 items.
- **Soft:** mean of the three dimension scores, then averaged over items.
- **Joint-pass:** percentage of responses with all three dimension scores at least 3 (`Acceptable`).
- **Fail:** percentage with at least one dimension scored 0 (`Fail`).

The final paper reports **9,860 responses**, **29,580 categorical judge decisions**, and **47,200 structured error flags**. Released records support offline alternative aggregation without new model inference.

## Results reported in the paper

### Verifiable formats

Strict accuracy (%); active parameters are shown for mixture-of-experts models.

| System | Parameters | MCQ | Binary | Short answer |
|---|---|---:|---:|---:|
| Gemini 3.6 Flash | -- | 97.2 | 93.1 | 95.8 |
| GPT-5 | -- | 95.7 | 91.3 | 94.7 |
| Claude Sonnet 5 | -- | 92.5 | 85.7 | 85.6 |
| Grok 4.20 | -- | 87.2 | 68.4 | 69.4 |
| gemma-4-31b-it | 31B | 93.6 | 89.6 | 78.2 |
| gemma-4-26b-a4b-it | 26B/4B | 92.2 | 86.1 | 75.0 |
| aya-expanse-32b | 32B | 82.0 | 75.8 | 62.3 |
| command-r-08-2024 | 32B | 82.1 | 75.8 | 58.5 |
| ALLaM-7B-Instruct | 7B | 79.5 | 77.5 | 52.5 |
| GemMaroc-27b-it | 27B | 82.7 | 80.1 | 43.7 |
| Atlas-Chat-27B | 27B | 77.8 | 79.2 | 42.3 |
| Qwen3.6-27B | 27B | 80.2 | 78.4 | 38.7 |
| Jais-2-8B-Chat | 8B | 79.2 | 73.6 | 43.3 |
| gpt-oss-20b | 20B | 78.0 | 70.1 | 36.6 |
| mistral-small-3.2-24b | 24B | 69.5 | 65.4 | 40.5 |
| Qwen3.5-9B | 9B | 75.7 | 69.7 | 26.1 |
| Mistral-Saba | 24B | 80.6 | 66.7 | not run |

The cross-system range is 27.7 points for MCQ and 69.7 for short answer. The different item inventories preclude attributing this difference solely to response format.

### Open-ended generation

Scores are out of 4; Joint and Fail are percentages. These are automated rubric statistics, not human acceptance rates or deployment certifications.

| System | Strict | Soft | Joint | Fail | Nativeness | Factual | Institutional |
|---|---:|---:|---:|---:|---:|---:|---:|
| GPT-5 | 2.555 | 3.366 | 43.6 | 1.0 | 3.219 | 3.091 | 3.788 |
| Gemini 3.6 Flash | 2.284 | 3.168 | 28.8 | 1.7 | 2.947 | 2.840 | 3.719 |
| Claude Sonnet 5 | 2.281 | 3.151 | 29.0 | 2.1 | 2.971 | 2.678 | 3.805 |
| gemma-4-31b-it | 2.172 | 3.133 | 22.1 | 1.7 | 2.793 | 2.834 | 3.771 |
| gemma-4-26b-a4b-it | 2.107 | 3.078 | 20.5 | 3.4 | 2.748 | 2.733 | 3.753 |
| Grok 4.20 | 1.971 | 2.875 | 15.3 | 4.8 | 2.667 | 2.436 | 3.521 |
| GemMaroc-27b | 1.833 | 2.832 | 16.7 | 5.9 | 2.745 | 2.188 | 3.562 |
| Jais-2-8B | 1.624 | 2.660 | 9.8 | 7.6 | 2.252 | 2.171 | 3.557 |
| ALLaM-7B | 1.512 | 2.580 | 7.1 | 5.0 | 1.940 | 2.141 | 3.659 |
| Atlas-Chat-27B | 1.510 | 2.636 | 10.9 | 9.7 | 2.360 | 2.033 | 3.514 |
| Mistral-Saba | 1.479 | 2.464 | 3.8 | 10.9 | 1.850 | 2.091 | 3.452 |
| Aya-Expanse-32B | 1.445 | 2.533 | 1.2 | 5.3 | 1.631 | 2.298 | 3.671 |
| Qwen3.6-27B | 1.436 | 2.515 | 1.2 | 8.3 | 1.616 | 2.252 | 3.678 |
| Mistral-Small-24B | 1.248 | 2.284 | 2.2 | 19.1 | 1.593 | 1.902 | 3.357 |
| gpt-oss-20b | 1.116 | 2.224 | 1.2 | 21.6 | 1.419 | 1.862 | 3.390 |
| Command-R | 1.071 | 2.353 | 1.9 | 7.4 | 1.140 | 2.303 | 3.616 |
| Qwen3.5-9B | 0.410 | 1.668 | 0.0 | 60.3 | 0.476 | 1.324 | 3.205 |

The strongest system's joint-pass rate is 43.6%; the best self-hosted system reaches 22.1%. Across all systems, factual coverage/Moroccan grounding averages 2.049/4 against 2.504 for accuracy/hallucination control. Pragmatic understanding averages 3.375 against lexical/idiomatic/stylistic naturalness of 2.500. These rubric decompositions distinguish omissions and unnatural production from other errors.

### Minimal camera-ready diagnostics from existing records

No new experiments or annotations were added for these diagnostics.

The binary gold classes contain 115 acceptable and 116 not-acceptable items. Class-conditioned accuracies and their unweighted mean (BA, balanced accuracy) reveal response asymmetry:

| System | Acceptable | Not acceptable | BA |
|---|---:|---:|---:|
| Gemini 3.6 Flash | 96.5 | 89.7 | 93.1 |
| GPT-5 | 94.8 | 87.9 | 91.4 |
| gemma-4-31b-it | 96.5 | 82.8 | 89.6 |
| gemma-4-26b-a4b-it | 96.5 | 75.9 | 86.2 |
| Claude Sonnet 5 | 96.5 | 75.0 | 85.8 |
| GemMaroc-27b | 100.0 | 60.3 | 80.2 |
| Atlas-Chat-27B | 96.5 | 62.1 | 79.3 |
| Qwen3.6-27B | 83.5 | 73.3 | 78.4 |
| ALLaM-7B | 90.4 | 64.7 | 77.5 |
| Aya-Expanse-32B | 98.3 | 53.4 | 75.9 |
| Command-R | 98.3 | 53.4 | 75.9 |
| Jais-2-8B | 96.5 | 50.9 | 73.7 |
| gpt-oss-20b | 62.6 | 77.6 | 70.1 |
| Qwen3.5-9B | 76.5 | 62.9 | 69.7 |
| Grok 4.20 | 44.3 | 92.2 | 68.3 |
| Mistral-Saba | 95.7 | 37.9 | 66.8 |
| Mistral-Small-24B | 96.5 | 34.5 | 65.5 |

Balanced and ordinary binary accuracy differ by at most 0.14 percentage points; prevalence reweighting does not repair response bias.

## Judge audits and uncertainty

The existing 100-response blinded, dual-reviewed open audit is axis-proportional and balanced across the 17 systems. Human-human quadratic-weighted kappa is 0.874/0.753/0.783 for factuality/nativeness/institutional alignment; judge-human kappa is 0.681/0.624/0.755.

At the joint-pass boundary, TP=10, TN=76, FP=3, FN=11: 86% agreement, but only 13 automated passes against 21 human passes. Precision is **76.9%** and sensitivity **47.6%** on this audit. This rules out reading automated joint-pass rates as direct human acceptance estimates. The sample does not support judge-accuracy estimates for individual systems or axes.

The separate short-answer audit samples 25 judge-accepted and 25 judge-rejected responses. Agreement is 48/50, with 24/25 correct in each stratum (Cohen's kappa 0.92). Reweighting the two stratum agreement estimates to a population judge-acceptance prevalence q gives `q*(24/25)+(1-q)*(24/25)=0.96`. This point estimate remains subject to sampling uncertainty and does not establish population sensitivity or specificity.

No second judge family, repeated-generation study, prompt-sensitivity study, or full-benchmark human performance ceiling is reported. Item-based uncertainty bounds exclude judge error and sampling variability from model generation. Scores should support coarse capability profiles rather than a precise total ordering.

## Finding and recomputing artifacts

| Artifact | Location |
|---|---|
| Response-free benchmark | [data/02_final_benchmark](data/02_final_benchmark/) |
| Annotation and adjudication trail | [data/01_cross_annotation](data/01_cross_annotation/) |
| Model responses | [outputs/model_responses](outputs/model_responses/) |
| Verifiable and open score workbooks | [outputs](outputs/) |
| Human validation statistics | [outputs/cross_annotation_scores_and_statistics](outputs/cross_annotation_scores_and_statistics/) |
| Categorical judge records and flags | [outputs/glm52_judge_outputs](outputs/glm52_judge_outputs/) |
| Closed and open error analyses | [error_analysis](error_analysis/) |
| Judge prompts | [prompts/judges](prompts/judges/) |
| Model/evaluation/annotation policies | [configs](configs/) |

Pipeline scripts cover [annotation splits](scripts/01_create_annotation_splits/), [consolidation](scripts/02_merging_annotations/), [inference](scripts/03_run_inference/), [scoring](scripts/04_scoring/), [human audits](scripts/05_human_audits/), and [error analysis](scripts/08_prepare_error_analysis.py). Alternative aggregations can use saved responses and judgements; reproducing original API outputs also depends on provider snapshots and complete run metadata.

## Limitations and intended use

Arabic-script Darija does not cover MSA, Amazigh, French, Arabizi, code-switching or the full range of Moroccan variation. Some cells are small (including n=7), and open-item difficulty/intent metadata are missing for 35.5%/40.9%, concentrated on Monarchy and Religion. Provenance/attestation effects are inconclusive and confounded with axis. All three open rubric passes share one judge family. Label-to-number mapping assumes equal spacing, so categorical and threshold-based analyses remain relevant.

The benchmark is for diagnostic model evaluation. It must not be used to profile people, assess whether someone is ?Moroccan enough?, or make automated decisions about individuals. It does not certify general safety or deployment readiness. Regional and social variation are not inherently errors; the rubrics are explicit operational criteria, not a definition of Moroccan identity.

## Citation

The paper is accepted at ICAART 2027. Proceedings metadata and a DOI will be added when available; none is claimed here.

```bibtex
@inproceedings{azhari2027moroccan,
  title = {The Moroccan Alignment Benchmark: Cultural Norms, Darija Nativeness and National Domain Knowledge in Large Language Models},
  author = {Azhari, Ferdaous and Skiredj, Abderrahman and El Asri, Ikram and Zaidouni, Dounia and Berrada, Ismail and En-Nouaary, Abdeslam},
  booktitle = {Proceedings of the 19th International Conference on Agents and Artificial Intelligence (ICAART)},
  year = {2027},
  note = {Accepted full paper; Ferdaous Azhari and Abderrahman Skiredj contributed equally}
}
```
