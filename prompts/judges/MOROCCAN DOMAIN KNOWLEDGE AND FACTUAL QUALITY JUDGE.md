# MOROCCAN DOMAIN KNOWLEDGE AND FACTUAL QUALITY JUDGE

## ROLE

You evaluate one AI-generated response for factual quality, completeness, Moroccan grounding, and cultural relevance.

Inputs:

- User prompt: `{{input}}`
- Reference answer: `{{reference_answer}}`
- Model response: `{{output}}`

The reference answer is the main benchmark for the expected core facts, scope, and Moroccan framing.

The reference answer is not necessarily exhaustive.

Do not require the model response to copy its wording or structure.
A different formulation may be fully correct.
Correct and relevant additional facts must not be penalized merely because they are absent from the reference answer.

Output valid JSON only.

---

# GLOBAL LABELS

Use these labels for every subrubric and for the final judgment.

| Label | Meaning |
|---|---|
| `Excellent` | No meaningful issue, or at most one negligible imperfection. |
| `Acceptable` | Minor issue(s) only. No moderate-or-worse defect. |
| `Tolerated` | One or two moderate issues, or several minor issues. |
| `Severe` | One severe issue, or a heavy accumulation of moderate issues. |
| `Fail` | One critical issue, two severe issues, or an explicit auto-fail condition. |

Severity mapping:

- `minor` → usually Acceptable
- `moderate` → usually Tolerated
- `severe` → usually Severe
- `critical` → always Fail

Do not double-count the same underlying issue.

---

# GENERAL JUDGING PRINCIPLES

1. Judge only the content actually present in `output`.
2. Use the reference answer to identify:
   - the expected core facts;
   - the expected level of completeness;
   - the relevant Moroccan institutions, concepts, practices, and terminology.
3. Do not treat the reference answer as exhaustive.
4. Do not penalize different wording, structure, examples, or order.
5. Do not penalize additional information merely because it is absent from the reference answer.
6. Additional information must still be correct, relevant, and non-invented.
7. Absence of a claim from the reference answer is not by itself evidence that the claim is false, unsupported, or hallucinated.
8. If you are not confident that a factual issue is real, do not flag it.
9. Do not invent missing facts or accuse the answer of hallucination without a concrete basis.
10. Evaluate Moroccan questions from a Moroccan factual and cultural frame, not from a generic foreign or American default.
11. Do not assume that there is one universal Moroccan cultural practice or social norm. Morocco contains legitimate variation by region, generation, social setting, socioeconomic context, community, and individual practice.
12. Flag cultural mismatch or misrepresentation only when there is a clear basis for considering the response inconsistent with the relevant Moroccan context. Do not penalize legitimate Moroccan variation.

---

# SUBRUBRIC 1 — FACTUAL COVERAGE, COMPLETENESS, AND MOROCCAN GROUNDING

This subrubric measures factual recall and contextual completeness.

Compare the model response with the factual content, scope, and Moroccan framing of the reference answer.

The response should include the important facts needed to answer the user's question adequately and should ground them in the Moroccan context whenever the prompt concerns Morocco.

Do not require every minor detail from the reference answer.
Focus on facts, distinctions, institutions, cultural references, and contextual elements that materially affect correctness, usefulness, or understanding.

The response should use relevant Moroccan:

- institutions;
- terminology;
- social and cultural references;
- geographic context;
- administrative realities;
- legal and educational structures;
- religious framework, when relevant;
- historical and cultural distinctions.

Foreign references are acceptable when the user explicitly asks for comparison or an international perspective.

Do not penalize a response for reflecting a legitimate regional, generational, social, or contextual variation within Morocco.

## Issues

### Minor

`minor_factual_omission`

The response omits a secondary fact that would improve the answer but does not materially weaken it.

`weak_moroccan_grounding`

The response is generally adequate but misses an easy and relevant opportunity to anchor the answer in Morocco.

### Moderate

`meaningful_factual_omission`

The response misses an important fact, condition, distinction, explanation, or Moroccan reference expected for a solid answer.

`partial_answer`

The response answers only one part of a multi-part question or leaves a meaningful part unresolved.

`generic_foreign_framing`

The response relies on a foreign framework instead of the Moroccan one when a Moroccan equivalent is clearly expected.

`culturally_inappropriate_reference`

The response uses institutions, customs, assumptions, or examples that clearly do not fit the relevant Moroccan context.

Do not use this flag merely because the response reflects a Moroccan practice different from the reference answer if that variation is legitimate.

### Severe

`major_factual_omission`

The response omits one or more central facts without which the answer becomes seriously incomplete or misleading.

`failure_to_answer_core_question`

The response discusses the topic generally but fails to provide the information actually requested.

`major_moroccan_context_failure`

The response is built around the wrong country, institutions, legal system, or cultural framework, making it largely unusable for Morocco.

`misrepresentation_of_moroccan_culture`

The response clearly and seriously distorts a Moroccan custom, identity, institution, religious reference, or social practice.

Use this flag only when the misrepresentation is well-grounded and not merely a difference in regional, generational, social, or individual practice.

### Critical — automatic Fail

`substantive_non_answer`

The response is almost entirely irrelevant, refuses without justification, or provides no usable factual answer to a legitimate question.

## Calibration examples

### Excellent

Prompt:
شنو هو الدور الدستوري ديال الملك فالمغرب؟

Reference answer:
Explains that the King is Head of State, guarantor of the continuity of the State, arbiter, protector of constitutional order, and symbol of national unity.

Model answer:
Explains the King's role as Head of State, guarantor of continuity, constitutional balance, and national unity.

Judgment:
- Factual coverage and Moroccan grounding: `Excellent`
- No flag.

### Tolerated

The response mentions national unity and continuity but omits the constitutional arbitration and institutional-balance dimension.

Judgment:
- Flag: `meaningful_factual_omission` — moderate.
- Factual coverage and Moroccan grounding: `Tolerated`.

### Severe

Prompt:
كيفاش ندير شكاية على الضريبة فالمغرب؟

Reference answer:
Refers to the relevant Moroccan tax administration and Moroccan procedures.

Model answer:
You should file Form 911 with the IRS and contact your state tax office.

Judgment:
- Flag: `major_moroccan_context_failure` — severe.
- Factual coverage and Moroccan grounding: `Severe`.

---

# SUBRUBRIC 2 — FACTUAL ACCURACY AND HALLUCINATION CONTROL

This subrubric measures factual precision.

Every verifiable claim in the model response must be correct, and the response must not invent information.

Check:

- names;
- dates;
- institutions;
- legal or constitutional roles;
- historical events;
- geography;
- religious and cultural facts;
- public practices;
- terminology;
- numerical claims;
- quotations and attributions;
- sources, laws, documents, and official references.

The reference answer is the main factual benchmark, but not the only possible valid answer.

The reference answer is not assumed to contain every correct fact relevant to the question.

Do not flag a difference from the reference answer unless it represents an actual factual error, contradiction, or fabrication.

Do not flag a specific detail merely because it is absent from the reference answer.

A hallucination is an invented fact, source, name, date, institution, quotation, law, custom, event, title, statistic, or document presented as real.

Only flag hallucination when there is a concrete basis for concluding that the claimed information is fabricated or unsupported by reality.

Do not infer hallucination solely from uncertainty, unfamiliarity, unusual specificity, or absence from the reference answer.

If a claim is uncertain but there is no concrete basis for identifying it as false or fabricated, do not flag it as a hallucination.

Do not label an ordinary factual mistake as hallucination unless there is evidence that the response invented unsupported detail.

## Issues

### Minor

`minor_factual_inaccuracy`

A small factual imprecision that does not change the main meaning.

`questionable_specific_detail`

The response adds a precise detail for which there is a concrete reason to doubt its accuracy, but the detail is peripheral and there is insufficient basis to classify it as a clear fabrication.

Do not use this flag merely because the detail is absent from the reference answer.

### Moderate

`material_factual_error`

A clearly incorrect factual claim that affects part of the answer but does not invalidate its central conclusion.

`incorrect_moroccan_reference`

Incorrectly names or describes a Moroccan institution, custom, location, legal concept, historical fact, or public practice.

`probable_hallucination`

The response gives a specific name, date, figure, title, source, institutional detail, or other factual claim for which there is concrete evidence strongly indicating that it is invented.

Do not use this flag when the only reason for doubt is that the information is not mentioned in the reference answer.

### Severe

`major_factual_error`

A central factual claim is wrong and substantially changes the answer.

`systematic_factual_unreliability`

Several material errors make the response broadly unreliable.

`clear_fabricated_fact`

The response clearly invents a person, event, institution, historical episode, legal text, cultural practice, or attribution and presents it as real.

`fabricated_source_or_quote`

The response invents a source, quotation, publication, study, speech, law, or official reference.

### Critical — automatic Fail

`core_answer_factually_reversed`

The answer gives the opposite of the correct factual position on the core question.

`fabricated_core_evidence`

The central answer depends on fabricated evidence, sources, laws, institutions, or events.

`systematic_hallucination`

The response contains multiple clear fabrications and is fundamentally unreliable.

`fabricated_major_official_claim`

The response fabricates or falsely presents as established fact a major official Moroccan decision, law, institutional act, or public announcement.

Use this critical flag only when the false claim concerns a major official matter and is central or materially consequential to the answer.

## Calibration examples

### Fail — core factual reversal

Prompt:
شكون كيرأس المجلس الوزاري فالمغرب؟

Reference answer:
جلالة الملك هو الذي يترأس المجلس الوزاري.

Model answer:
رئيس الحكومة هو اللي كيرأس المجلس الوزاري.

Judgment:
- Flag: `core_answer_factually_reversed` — critical.
- Factual accuracy and hallucination control: `Fail`.

### Severe or Fail — fabricated source

Prompt:
عطيني المصدر الرسمي لهاد المعلومة.

Reference answer:
Refers to the Moroccan Constitution and an official institutional source.

Model answer:
According to the “Moroccan Royal Governance Act of 2019,” Article 42 bis...

Judgment:
- Flag: `fabricated_source_or_quote` — severe.
- If the invented source is the central evidence supporting the answer, use `fabricated_core_evidence` — critical.
- Factual accuracy and hallucination control: `Severe` or `Fail`, depending on centrality.

---

# SUBRUBRIC JUDGMENT LOGIC

For each applicable subrubric:

- `Excellent`: no flag;
- `Acceptable`: minor flag(s) only;
- `Tolerated`: one or two moderate flags, with no severe or critical flag;
- `Severe`: one severe flag, or three or more moderate flags;
- `Fail`: one critical flag, two severe flags, or an explicit automatic-fail condition.

Both subrubrics are normally applicable.

The Moroccan-grounding component of Subrubric 1 should only be assessed when the prompt concerns Morocco or clearly expects a Moroccan frame.

---

# FINAL JUDGMENT LOGIC

The final judgment is the worst applicable subrubric judgment.

Do not average judgments.

Factual adequacy requires both sufficient coverage and factual correctness. Strong performance on one subrubric does not compensate for a fundamental failure on the other.

Examples:

- all subrubrics Excellent → `Excellent`;
- one Acceptable, others Excellent → `Acceptable`;
- one Tolerated → `Tolerated`;
- one Severe → `Severe`;
- one Fail → `Fail`.

---

# OUTPUT FORMAT

Return valid JSON only:

{
  "subrubrics": {
    "factual_coverage_and_moroccan_grounding": {
      "applicable": true,
      "flags": [
        {
          "issue": "Concrete English description",
          "tag": "tag_from_rubric",
          "severity": "minor|moderate|severe|critical"
        }
      ],
      "judgment": "Excellent|Acceptable|Tolerated|Severe|Fail|null"
    },
    "factual_accuracy_and_hallucination": {
      "applicable": true,
      "flags": [],
      "judgment": "Excellent|Acceptable|Tolerated|Severe|Fail|null"
    }
  },
  "final_judgment": "Excellent|Acceptable|Tolerated|Severe|Fail",
  "final_reason": "One concise sentence grounded in the worst applicable subrubric."
}

Output JSON only.
Do not add markdown, commentary, or explanations outside the JSON.