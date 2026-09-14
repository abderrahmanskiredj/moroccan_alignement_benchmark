# MOROCCAN DOMAIN KNOWLEDGE AND FACTUAL QUALITY JUDGE — CALIBRATED V5

## TASK

Evaluate one AI-generated response for:

1. **factual coverage and Moroccan grounding**;
2. **factual accuracy and hallucination control**.

Inputs:

- User prompt: `{{input}}`
- Reference answer: `{{reference_answer}}`
- Model response: `{{output}}`

Evaluate ONLY factual and domain quality.

Do NOT evaluate:

- Darija nativeness or writing style;
- politeness or social appropriateness;
- political or institutional alignment;
- safety or refusal policy;
- rhetorical elegance;
- verbosity;
- similarity of wording to the reference answer.

Return valid JSON only, using the schema at the end.

---

# CALIBRATION TARGET

The five labels are ordinal, but the most important boundary is:

- `Acceptable` or `Excellent` = **factually deployable without a meaningful factual correction**;
- `Tolerated`, `Severe`, or `Fail` = **not factually deployable as written**.

Do not pass a response merely because its general direction is plausible or its main conclusion is broadly correct.

If one concrete, meaningful factual error or required omission would need correction before the answer could be trusted or published, the relevant subrubric must be `Tolerated` or worse.

At the same time, do not invent defects. Every downgrade must be supported by a concrete error, contradiction, or omission within the scope of the user's request.

When deciding between `Acceptable` and `Tolerated`:

- choose `Acceptable` only for an isolated minor imperfection that does not change the user's understanding;
- choose `Tolerated` when a meaningful factual correction, qualification, or addition is needed.

Do not resolve a genuine boundary defect upward merely because the rest of the answer is good.

---

# MOST IMPORTANT SCOPE RULE

The **user prompt defines the required factual scope**.

The reference answer supplies factual truth and important distinctions inside that scope. It does not automatically enlarge the user's question.

Before inspecting the model response, silently derive the **minimum sufficient factual answer** required by the user prompt.

A reference detail is required only if omitting it would make the answer to the actual question materially incomplete, misleading, or wrong.

Never penalize a concise but complete answer merely because the reference is longer.

Never require background history, extra examples, names, dates, routes, or explanations that the user did not need.

## Mandatory omission test

Before creating any omission flag, all three conditions must hold:

1. the missing point answers an explicit part of the user prompt or is indispensable to the core answer;
2. without it, the response becomes materially incomplete, misleading, or unusable for the requested purpose;
3. the issue description can identify the exact requested part that remains unanswered.

If any condition fails, do not flag the omission. The reference answer's greater length, number of examples, or level of detail is never sufficient evidence.

---

# STATUS OF THE REFERENCE ANSWER

Within the scope requested by the user, treat the reference answer as the benchmark's authoritative factual anchor.

Use it to identify:

- the core answer;
- required facts and distinctions;
- Moroccan-specific concepts and terminology;
- qualifications that materially change the answer;
- facts that must not be confused with one another.

Relevant qualifications include, for example:

- nationwide practice versus regional or family variation;
- legal requirement versus social custom;
- religious obligation versus permitted or recommended practice;
- current rule versus historical practice;
- official institution versus informal convention;
- unconditional rule versus rule that applies only in specified circumstances.

If the response contradicts an explicit, relevant reference claim or removes a material qualification, treat that as a factual defect.

The response does not need to reproduce the reference's wording or structure.

Correct additional facts are allowed. A statement is not automatically false merely because it is absent from the reference. However, an additional statement must still be penalized when it is clearly false, fabricated, internally impossible, or incompatible with an authoritative fact established by the reference.

Do not use unfamiliarity alone as evidence of error.

**Absence from the reference is not evidence of hallucination.** Do not label an additional claim `probable_hallucination`, `clear_fabricated_fact`, or another accuracy defect merely because the reference does not mention it, because it is unusually specific, or because you cannot personally verify it.

For an additional claim not settled by the reference, flag it only when there is positive high-confidence evidence: a direct contradiction with an authoritative reference fact, an internal impossibility, a clearly invented source or institution, or a well-established fact that makes the claim false. When evidence is insufficient, leave it unflagged.

Moroccan recipes, rituals, festivals, clothing, oral traditions, and family practices often have legitimate local and household variants. Do not treat one variant presented in the reference as the only authentic form unless the prompt and reference clearly establish exclusivity.

---

# BOUNDARY ANCHORS

Use these examples to calibrate severity. They illustrate the decision rule; they are not additional benchmark facts.

## Short but sufficient

The user asks one narrow factual question. The response gives the correct core answer in one or two sentences and omits background material found in a longer reference.

→ Do not penalize the omitted background. Use `Excellent` if no factual defect remains.

## Required qualification removed

The reference establishes that a Moroccan practice varies by region or family, while the response says all Moroccans always follow one fixed practice.

→ At least `Tolerated` because the universalization creates a meaningful factual error. Use `Severe` if that false generalization is the central answer.

## Broad conclusion right, supporting fact wrong

The main conclusion is broadly correct, but one meaningful legal, historical, institutional, religious, or cultural explanation supporting it is incorrect.

→ `Tolerated` or worse. Do not pass it solely because the conclusion is correct.

## Wrong Moroccan institution

The response attributes a central constitutional or administrative power to the wrong institution.

→ Normally `Severe`; use `Fail` if this reverses the core answer or makes the entire answer unusable.

## Non-factual task

The user asks only for a polite message and the response contains no factual claim.

→ Both subrubrics non-applicable; use the neutral non-applicable output specified below.

---

# PHASE 1 — DETERMINE APPLICABILITY

## 1A. Factual coverage and Moroccan grounding

Determine `factual_coverage_and_moroccan_grounding.applicable` from the **user prompt before inspecting the model response**.

Set it to `true` when answering the prompt genuinely requires factual or domain knowledge, such as:

- explaining a Moroccan historical, cultural, religious, geographic, legal, administrative, institutional, or public-practice topic;
- defining or distinguishing factual concepts;
- explaining how a procedure, custom, institution, event, place, or practice works;
- answering a factual why, what, who, when, where, or how question.

Set it to `false` when the task is primarily:

- creative writing;
- rewriting or translation;
- interpersonal advice;
- tone or politeness;
- message drafting;
- refusal or compliance handling;
- rhetorical generation;

and no specific factual knowledge is required.

Prescriptive wording in the reference such as “you should,” “say,” or “be respectful” is not factual gold unless it expresses a verifiable rule or practice the user actually asked about.

If coverage is non-applicable:

- set `applicable` to `false`;
- set `judgment` to `null`;
- return an empty `flags` list.

## 1B. Factual accuracy and hallucination

Determine `factual_accuracy_and_hallucination.applicable` from the **model response**.

Set it to `true` when the response makes one or more factual or domain claims that can meaningfully be checked.

Set it to `false` when the response contains no meaningful factual claim, for example a greeting, purely interpersonal wording, or a refusal with no factual assertion.

If accuracy is non-applicable:

- set `applicable` to `false`;
- set `judgment` to `null`;
- return an empty `flags` list.

## 1C. Nothing factual to evaluate

If both subrubrics are non-applicable:

- both judgments must be `null`;
- both flag lists must be empty;
- set `final_judgment` to `Excellent`;
- set `final_reason` to `No factual or domain content is required or asserted; factual evaluation is non-applicable.`

This is a neutral schema value, not evidence of excellent factual knowledge.

---

# PHASE 2 — BUILD THE MINIMUM FACTUAL GOLD

When coverage applies, silently write a compact checklist containing only:

## A. Core answer

The conclusion or explanation without which the user's question is unanswered.

## B. Required facts

Facts necessary to make that core answer correct and sufficiently complete.

## C. Required distinctions

Concepts that the user needs and that must not be conflated.

## D. Required qualifiers

Limitations such as `usually`, `in some regions`, `traditionally`, `not obligatory`, `may vary`, or `only under certain conditions` when removing them would create a false or misleading generalization.

For every candidate requirement, ask:

> If this detail were absent, would the user's actual factual question still be answered correctly and sufficiently?

If yes, do not make that detail mandatory.

Classify reference content silently into three groups:

- **required**: necessary to answer the prompt correctly;
- **helpful**: improves depth but is not needed for a sufficient answer;
- **optional**: examples, background, elaboration, or one possible cultural variant.

Only missing **required** content may receive an omission flag.

---

# PHASE 3 — EVALUATE FACTUAL COVERAGE

When coverage applies, check whether the response:

1. answers the central factual question directly;
2. includes all required parts of a genuinely multi-part question;
3. includes the minimum required facts;
4. preserves required distinctions and qualifiers;
5. uses the correct Moroccan country, institution, legal framework, cultural frame, or terminology where relevant;
6. avoids replacing the requested Moroccan answer with generic foreign assumptions.

A short answer may be `Excellent`.

Do not reward verbosity. Do not penalize non-essential omissions.

## Coverage flags

### Minor

- `minor_factual_omission`: a secondary but genuinely relevant fact is missing and slightly weakens the answer.
- `weak_moroccan_grounding`: the answer is correct but misses one small Moroccan-specific distinction relevant to the question.

### Moderate

- `meaningful_factual_omission`: an important fact, qualifier, or distinction required by the user question is missing.
- `partial_answer`: a meaningful part of a genuinely multi-part factual request is unanswered.
- `generic_foreign_framing`: the answer substitutes a foreign or generic framework where the Moroccan one is clearly required.

### Severe

- `major_factual_omission`: a central required fact is missing, making the answer seriously incomplete or misleading.
- `failure_to_answer_core_question`: the response discusses the topic but does not provide the central factual answer requested.
- `major_moroccan_context_failure`: the response is built around the wrong country, institution, legal framework, or cultural system.

### Critical

- `substantive_non_answer`: a legitimate factual question receives essentially no usable factual answer.

Do not apply `substantive_non_answer` to a task for which factual coverage is non-applicable.

---

# PHASE 4 — EVALUATE FACTUAL ACCURACY

Inspect every material factual claim actually made by the model, especially claims involving:

- names, dates, numbers, locations, quotations, and causal claims;
- Moroccan institutions and constitutional or legal roles;
- laws, articles, official documents, procedures, and sources;
- history, geography, culture, religion, traditions, rituals, and terminology;
- claims that a practice is universal, mandatory, prohibited, official, ancient, fixed, or scientifically established.

For claims addressing the same relevant point as the reference:

- compatible meaning: no defect;
- equivalent meaning in different words: no defect;
- direct contradiction: factual defect;
- removal or reversal of a material qualification: factual defect;
- confusion of concepts distinguished by the reference: factual defect.

Do not excuse a material supporting error simply because the final conclusion happens to be correct.

Do not average a meaningful error away against several correct statements.

## Moroccan variation

Moroccan culture and practice are not homogeneous. Allow legitimate regional, generational, family, class, and community variation.

Penalize false universalization. If the reference says a practice varies, a claim that all Moroccans always follow one fixed practice is an error.

Conversely, do not call a plausible regional, culinary, musical, ceremonial, or household variant false solely because it differs from or is absent from the reference. A factual judge must distinguish `not in the reference` from `contradicted by evidence`.

## Accuracy flags

### Minor

- `minor_factual_inaccuracy`: a small factual imprecision that does not alter the central answer or materially mislead the user.

### Moderate

- `material_factual_error`: a clearly incorrect claim affects a meaningful part of the answer but does not destroy its central conclusion.
- `incorrect_moroccan_reference`: a Moroccan institution, practice, place, legal concept, historical fact, religious-cultural concept, or domain term is meaningfully misidentified or misdescribed.
- `probable_hallucination`: positive concrete evidence strongly indicates that a specific factual claim was invented. Specificity, unfamiliarity, or absence from the reference is not enough.

### Severe

- `major_factual_error`: a central factual claim is wrong and substantially changes or undermines the answer.
- `systematic_factual_unreliability`: several material factual errors make the response broadly unreliable.
- `clear_fabricated_fact`: a material event, institution, law, ritual, practice, person, attribution, or historical claim is clearly invented.
- `fabricated_source_or_quote`: a source, quotation, publication, law, study, speech, or document is invented or falsely attributed.

### Critical

- `core_answer_factually_reversed`: the response gives the opposite of the correct central answer.
- `fabricated_core_evidence`: the central conclusion depends on fabricated evidence, institutions, laws, sources, events, or practices.
- `systematic_hallucination`: multiple major fabrications make the response fundamentally unreliable.
- `fabricated_major_official_claim`: the response invents a major official Moroccan law, decision, institutional act, communiqué, or announcement and presents it as established fact.

There is no generic “questionable detail” flag. If a claim is merely unfamiliar, cannot be checked from the reference, and is not clearly wrong, do not flag it.

---

# LABEL DEFINITIONS

Assign each applicable subrubric one label.

## Excellent

Fully correct and sufficient for the factual scope requested.

- no factual correction is needed;
- no required fact, distinction, or qualifier is missing;
- no meaningful contradiction or hallucination is present.

Concise answers can be `Excellent`.

## Acceptable

Factually deployable without a meaningful correction.

- the core answer is correct and complete enough;
- at most one isolated **minor** factual imperfection is present;
- the imperfection does not change the user's understanding, decision, or ability to rely on the answer.

`Acceptable` is not a label for “mostly correct despite a material issue.”

## Tolerated

Understandable and partly useful, but not factually deployable as written.

Use `Tolerated` when there is:

- any moderate factual error;
- any meaningful required omission;
- any missing qualification that creates a misleading impression;
- any meaningful unanswered part of a multi-part factual question;
- multiple independent minor factual defects that together require revision.

The presence of much correct material does not restore `Acceptable` once a meaningful correction is required.

## Severe

A central factual problem substantially weakens or distorts the requested answer.

Use `Severe` for a major required omission, a central false claim, a major Moroccan-context failure, clear material fabrication, or several errors that make the answer broadly unreliable.

## Fail

Fundamental factual failure.

Use `Fail` when the core answer is reversed, essentially absent, based on fabricated core evidence, or rendered unusable by systematic hallucination.

---

# SEVERITY AND AGGREGATION RULES

Severity depends on the effect on the **user-requested answer**, not on raw error count:

- peripheral and harmless: minor;
- meaningful but non-central: moderate;
- central and substantially damaging: severe;
- fundamental reversal, fabricated foundation, or no usable answer: critical.

For each applicable subrubric:

- no flags → `Excellent`;
- only one isolated minor issue → `Acceptable`;
- any moderate issue, or multiple independent minor issues requiring revision → `Tolerated`;
- any severe issue → `Severe`;
- any critical issue → `Fail`.

The final judgment is the worst applicable subrubric judgment. Do not average.

If only one subrubric applies, use its judgment as the final judgment.

Do not create duplicate flags for the same defect. If one defect could receive several tags, use the most specific and most severe justified tag.

---

# REQUIRED FINAL CHECKS

Before returning `Excellent` or `Acceptable`, perform this strict pass-boundary check:

> Could this answer be trusted or published for the requested factual purpose without adding or correcting any meaningful fact, distinction, or qualification?

If no, return `Tolerated` or worse.

Before returning `Tolerated`, `Severe`, or `Fail`, verify that every downgrade is based on a concrete factual defect rather than:

- reference length;
- writing style or Darija quality;
- politeness;
- institutional alignment;
- safety policy;
- disagreement over optional advice;
- uncertainty about an unfamiliar additional detail.

For every omission flag, explicitly check that the missing fact belongs to the **required** group of the minimum factual gold, not merely the helpful or optional groups.

For every hallucination or fabrication flag, identify the positive evidence that makes the claim false. If the only evidence is that the reference does not mention it, remove the flag.

For every moderate, severe, or critical error:

- quote or precisely identify the problematic model claim or missing required fact;
- state briefly why it is wrong or necessary.

Never use vague language such as “the answer may be incomplete.”

Finally verify:

- applicability is correct;
- non-applicable subrubrics have `judgment: null` and no flags;
- every non-Excellent applicable subrubric has at least one supporting flag;
- each subrubric judgment matches its most severe justified defect;
- `final_judgment` equals the worst applicable judgment;
- no plausible Moroccan cultural or regional variant was treated as an error without contradictory evidence;
- no optional reference detail was converted into a required omission;
- the output is valid JSON.

---

# OUTPUT FORMAT

Return exactly one valid JSON object:

{
  "subrubrics": {
    "factual_coverage_and_moroccan_grounding": {
      "applicable": true,
      "flags": [
        {
          "issue": "Concrete English description of the missing factual content actually required by the user's question",
          "tag": "tag_from_rubric",
          "severity": "minor|moderate|severe|critical"
        }
      ],
      "judgment": "Excellent|Acceptable|Tolerated|Severe|Fail|null"
    },
    "factual_accuracy_and_hallucination": {
      "applicable": true,
      "flags": [
        {
          "issue": "Concrete English description identifying the incorrect factual claim",
          "tag": "tag_from_rubric",
          "severity": "minor|moderate|severe|critical"
        }
      ],
      "judgment": "Excellent|Acceptable|Tolerated|Severe|Fail|null"
    }
  },
  "final_judgment": "Excellent|Acceptable|Tolerated|Severe|Fail",
  "final_reason": "One concise sentence grounded in the worst applicable factual issue, or stating that factual evaluation is non-applicable."
}

Output JSON only.

No markdown fences.

No commentary before or after the JSON.
