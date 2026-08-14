# Error-analysis fact sheet

This file is generated automatically by `scripts/08_prepare_error_analysis.py`.

## Data provenance

- **MCQ:** item-level correctness source = `scored_workbook:Details`
- **Binary:** item-level correctness source = `scored_workbook:Details`
- **ShortAnswer:** item-level correctness source = `scored_workbook:Details`

## Strong / weak systems by format

### Binary
Top 5: gemini3_6_flash (93.1%), gpt5 (91.3%), gemma4_31b (89.6%), gemma4_26b (86.1%), claude_sonnet5 (85.7%)
Bottom 5: gptoss_20b (70.1%), qwen3_5_9b (69.7%), grok4_20 (68.4%), mistral_saba (66.7%), mistral_24b (65.4%)

### MCQ
Top 5: gemini3_6_flash (97.2%), gpt5 (95.7%), gemma4_31b (93.6%), claude_sonnet5 (92.5%), gemma4_26b (92.2%)
Bottom 5: jais2_8b_bf16 (79.2%), gptoss_20b (78.0%), atlaschat_27b (77.8%), qwen3_5_9b (75.7%), mistral_24b (69.5%)

### ShortAnswer
Top 5: gemini3_6_flash (95.8%), gpt5 (94.7%), claude_sonnet5 (85.6%), gemma4_31b (78.2%), gemma4_26b (75.0%)
Bottom 5: atlaschat_27b (42.3%), mistral_24b (40.5%), qwen3_6_27b (38.7%), gptoss_20b (36.6%), qwen3_5_9b (26.1%)

## Q1. Items defeating strong models

- **Binary:** 20/231 consensus-hard (8.7%); 8 universally hard; 203 consensus-easy.
- **MCQ:** 25/577 consensus-hard (4.3%); 3 universally hard; 540 consensus-easy.
- **ShortAnswer:** 26/284 consensus-hard (9.2%); 6 universally hard; 231 consensus-easy.

### Strongest over-representations among consensus-hard items (FDR q < .05 where available)

**Binary:**
- intent_group = `idiom_comprehension`: ER=5.25, hard 5/20, q=0.018
- intent_group = `linguistic_naturalness`: ER=2.99, hard 7/20, q=0.035
- axis = `Nativeness`: ER=2.19, hard 18/20, q=0.000

**MCQ:**
- axis = `History`: ER=2.31, hard 17/25, q=0.000
- item_type = `documented`: ER=1.38, hard 20/25, q=0.023

**ShortAnswer:**
- axis = `Culture`: ER=2.02, hard 17/26, q=0.001
- difficulty = `medium`: ER=1.61, hard 18/26, q=0.019

## Q2. Hardness vs discrimination

- **Binary:** 15 negative-discrimination items (6.5%).
  - `BQ_113`: H=1.00, D=-0.40, axis=Nativeness, difficulty=hard
  - `BQ_158`: H=0.60, D=-0.40, axis=Nativeness, difficulty=hard
  - `BQ_144`: H=1.00, D=-0.40, axis=Nativeness, difficulty=hard
  - `BQ_159`: H=1.00, D=-0.40, axis=Nativeness, difficulty=medium
  - `BQ_160`: H=0.60, D=-0.40, axis=Nativeness, difficulty=medium
- **MCQ:** 15 negative-discrimination items (2.6%).
  - `QCM_266`: H=0.80, D=-0.60, axis=Culture, difficulty=easy
  - `QCM_087`: H=0.80, D=-0.60, axis=History, difficulty=easy
  - `QCM_267`: H=0.60, D=-0.40, axis=Culture, difficulty=hard
  - `QCM_164`: H=0.40, D=-0.20, axis=History, difficulty=medium
  - `QCM_088`: H=0.40, D=-0.20, axis=History, difficulty=easy
- **ShortAnswer:** 1 negative-discrimination items (0.4%).
  - `SA_123`: H=0.40, D=-0.20, axis=History, difficulty=hard

## Human difficulty vs empirical hardness

- **Binary:** Spearman rho=0.171, p=0.0093; Kruskal-Wallis p=0.0349.
- **MCQ:** Spearman rho=-0.037, p=0.3767; Kruskal-Wallis p=0.2390.
- **ShortAnswer:** Spearman rho=0.063, p=0.2871; Kruskal-Wallis p=0.5551.

## Q3. MCQ attestation hypothesis

System-average MCQ accuracy: documented=81.0%, tacit=87.8%; documented-minus-tacit=-6.8%.
Strong-model hardness difference (tacit - documented) = -0.045 [bootstrap 95% CI -0.070, -0.020], Mann-Whitney p=0.0010.
Adjusted clustered logistic regression tacit-vs-documented: OR=1.427 [95% CI 0.701, 2.906], p=0.3265.
Adjusted marginal predicted accuracy: documented=82.3%, tacit=86.5%, difference=-4.2%.

## Important interpretation note

The generated 420-row manual review queue is a **verifiable-format review queue**. Do not call it the paper's '420 manually inspected flagged open-ended responses' unless those rows are in fact the responses you manually inspect under the open-ended factual/nativeness/alignment rubrics.