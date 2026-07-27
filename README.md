# The Moroccan Alignment Benchmark

![Evaluation pipeline](assets/diagram.png)

Repository accompanying the Moroccan Alignment Benchmark.

## Benchmark at a glance

- 1,726 evaluation items
- 8 evaluation axes
- 4 question formats
- 588 multiple-choice questions
- 236 binary questions
- 296 short-answer questions
- 606 open-ended questions
- 9 cross-validation annotators
- 3 disjoint LLM judges

Detailed reproduction instructions will be added here.


moroccan-alignment-benchmark/
│
├── README.md
├── requirements.txt
├── LICENSE-CODE
├── LICENSE-DATA
├── CITATION.cff
├── .gitignore
│
├── assets/
│   └── diagram.png
│
├── configs/
│   ├── annotation_policy.yaml
│   ├── models.yaml
│   └── evaluation.yaml
│
├── prompts/
│   ├── system_prompt.txt
│   └── judges/
│       ├── culture_factuality.txt
│       ├── nativeness.txt
│       └── safety.txt
│
├── data/
│   ├── 00_prevalidation/
│   │   ├── items_prevalidation.xlsx
│   │   └── original_keys.csv
│   │
│   ├── 01_cross_annotation/
│   │   ├── MCQ/
│   │   │   ├── admin/
│   │   │   │   ├── assignment_manifest.csv
│   │   │   │   ├── consolidation_report.xlsx
│   │   │   │   └── adjudication_decisions.xlsx
│   │   │   │
│   │   │   └── annotators/
│   │   │       ├── annotator_01.xlsx
│   │   │       ├── annotator_02.xlsx
│   │   │       ├── annotator_03.xlsx
│   │   │       ├── annotator_04.xlsx
│   │   │       ├── annotator_05.xlsx
│   │   │       ├── annotator_06.xlsx
│   │   │       ├── annotator_07.xlsx
│   │   │       ├── annotator_08.xlsx
│   │   │       └── annotator_09.xlsx
│   │   │
│   │   ├── Binary_questions/
│   │   │   ├── admin/
│   │   │   │   ├── assignment_manifest.csv
│   │   │   │   ├── consolidation_report.xlsx
│   │   │   │   └── adjudication_decisions.xlsx
│   │   │   │
│   │   │   └── annotators/
│   │   │       ├── annotator_01.xlsx
│   │   │       ├── annotator_02.xlsx
│   │   │       ├── annotator_03.xlsx
│   │   │       ├── annotator_04.xlsx
│   │   │       ├── annotator_05.xlsx
│   │   │       ├── annotator_06.xlsx
│   │   │       ├── annotator_07.xlsx
│   │   │       ├── annotator_08.xlsx
│   │   │       └── annotator_09.xlsx
│   │   │
│   │   ├── Short_answers/
│   │   │   ├── admin/
│   │   │   │   ├── assignment_manifest.csv
│   │   │   │   ├── consolidation_report.xlsx
│   │   │   │   └── adjudication_decisions.xlsx
│   │   │   │
│   │   │   └── annotators/
│   │   │       ├── annotator_01.xlsx
│   │   │       ├── annotator_02.xlsx
│   │   │       ├── annotator_03.xlsx
│   │   │       ├── annotator_04.xlsx
│   │   │       ├── annotator_05.xlsx
│   │   │       ├── annotator_06.xlsx
│   │   │       ├── annotator_07.xlsx
│   │   │       ├── annotator_08.xlsx
│   │   │       └── annotator_09.xlsx
│   │   │
│   │   └── Open_questions/
│   │       ├── admin/
│   │       │   ├── assignment_manifest.csv
│   │       │   ├── consolidation_report.xlsx
│   │       │   └── adjudication_decisions.xlsx
│   │       │
│   │       └── annotators/
│   │           ├── annotator_01.xlsx
│   │           ├── annotator_02.xlsx
│   │           ├── annotator_03.xlsx
│   │           ├── annotator_04.xlsx
│   │           ├── annotator_05.xlsx
│   │           ├── annotator_06.xlsx
│   │           ├── annotator_07.xlsx
│   │           ├── annotator_08.xlsx
│   │           └── annotator_09.xlsx
│   │
│   └── 02_final_benchmark/
│       ├── moroccan_alignment_benchmark.xlsx
│       ├── moroccan_alignment_benchmark.csv
│       └── data_dictionary.md
│
├── outputs/
│   ├── generations/
│   │   ├── model_01.jsonl
│   │   ├── model_02.jsonl
│   │   └── ...
│   │
│   ├── judgments/
│   │   ├── culture_factuality/
│   │   │   ├── model_01.jsonl
│   │   │   └── ...
│   │   ├── nativeness/
│   │   │   ├── model_01.jsonl
│   │   │   └── ...
│   │   └── safety/
│   │       ├── model_01.jsonl
│   │       └── ...
│   │
│   ├── model_answers.xlsx
│   ├── item_level_results.csv
│   ├── leaderboard.csv
│   ├── confidence_intervals.csv
│   └── final_results.xlsx
│
├── analysis/
│   └── manual_error_analysis.xlsx
│
├── scripts/
│   ├── 01_create_annotation_splits.py
│   ├── 02_consolidate_annotations.py
│   ├── 03_finalize_benchmark.py
│   ├── 04_run_inference.py
│   ├── 05_score_closed_formats.py
│   ├── 06_run_llm_judges.py
│   ├── 07_aggregate_results.py
│   ├── 08_prepare_error_analysis.py
│   └── utils.py
│
├── tests/
│   ├── test_closed_answer_parser.py
│   └── test_judge_output_schema.py
│
└── reproduce_results.sh