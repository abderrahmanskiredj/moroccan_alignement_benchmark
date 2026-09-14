# MOROCCAN DARIJA NATIVENESS JUDGE — CALIBRATED V5

## TASK

Evaluate whether `{{output}}` sounds like a **natural Moroccan Darija response** to `{{input}}`.

Inputs:

- User prompt: `{{input}}`
- Reference answer: `{{reference_answer}}`
- Model response: `{{output}}`

Evaluate ONLY:

1. understanding of the user's Darija;
2. language and register matching;
3. Moroccan dialect consistency;
4. natural code-switching;
5. natural Moroccan wording, syntax, rhythm, and flow.

Do NOT evaluate factual correctness, completeness, safety, political or religious alignment, helpfulness, or agreement with the reference answer.

The reference answer may clarify the user's meaning or expected register. It is **not** a stylistic template and the response does not need to resemble it.

Return valid JSON only, using the schema at the end.

---

# CALIBRATION TARGET

The five labels are ordinal, but the most important boundary is:

- `Acceptable` or `Excellent` = **linguistically deployable as Moroccan Darija without meaningful rewriting**;
- `Tolerated`, `Severe`, or `Fail` = **understandable perhaps, but not deployable as natural Moroccan Darija**.

Do not confuse understandable Arabic with native Moroccan Darija.

Do not pass a response merely because it contains recognizable Moroccan markers such as `شنو`, `ديال`, `هادشي`, `بزاف`, `راه`, or `خاصك`.

Judge the complete sentence skeleton, phrase choices, discourse flow, and register.

When deciding between `Acceptable` and `Tolerated`:

- choose `Acceptable` when the response is recognizably natural Moroccan Darija and has no more than one or two isolated minor local imperfections;
- choose `Tolerated` only when there is high-confidence evidence of a genuinely non-Moroccan construction, or when at least three independent minor defects create a noticeable pattern.

Do not resolve a concrete boundary defect upward merely because the response is understandable, helpful, polished, or mostly Darija. But do not manufacture a boundary defect by proposing wording that is merely different or more to your personal taste.

At the same time, do not invent dialect errors. Every downgrade must cite concrete linguistic evidence.

Because Darija is non-standardised and highly variable, uncertainty must resolve toward **no flag**. A downgrade requires positive evidence that the wording is non-native, not merely the existence of another possible phrasing.

---

# PHASE 1 — CALIBRATE THE EXPECTED LANGUAGE AND REGISTER

Before judging the response, silently determine from the user prompt:

- whether Moroccan Darija is explicit or strongly implied;
- whether the situation is casual, neutral, professional, administrative, legal, religious, technical, literary, or strongly code-switched;
- whether French, English, or formal Arabic vocabulary is natural for that topic;
- whether the user uses Arabic script, Latin-script Darija, French, English, or a mixture;
- whether the expected answer should mirror the user's register or appropriately adapt it.

A prompt written naturally in Darija normally creates an expectation of a Moroccan Darija response unless the user explicitly requests another language or the task itself requires another form.

Formal Arabic vocabulary can be natural in Moroccan legal, religious, administrative, academic, or technical discourse. Formal vocabulary alone is not evidence of non-nativeness.

The relevant question is whether the vocabulary is integrated into a plausibly Moroccan sentence structure and register.

Do not impose one regional variety. Legitimate Moroccan regional forms, spelling variation, and natural French/Darija mixing are allowed.

## Mandatory Moroccan false-positive guardrails

The following are ordinary Moroccan possibilities and must **not** be flagged merely for appearing:

- `إوا` and `إيوا`: both are common spellings of the Moroccan discourse particle;
- `إلا`: commonly means **if** in Moroccan Darija; its meaning depends on context;
- `حيت`, `حيتاش`, and spelling variants: ordinary Moroccan causal connectors;
- `صداع`: commonly means noise, fuss, trouble, or headache depending on context;
- `واخا`, `راه`, `ماشي`, `غير`, `بزاف`, `بصح`, `دابا`, `ديال`, `باش`, and `ملي`: ordinary Moroccan forms;
- forms such as `بما أن`, `لأن`, `لكن`, `إذن`, `خلاصة`, `موروث`, `الخصوصية`, or `التضامن` inside educated, administrative, explanatory, religious, legal, or technical Darija. A shared or formal word is not an MSA error by itself;
- naturally integrated French or English terms used by Moroccans in the relevant domain;
- headings, bullet points, quotation marks, or Markdown formatting. Formatting is not a language defect;
- ordinary spelling differences, missing hamza, optional alif, clitic attachment, or inconsistent informal orthography;
- one typo, punctuation problem, or repeated word unless it creates a genuinely non-native pattern or makes the meaning unusable.

Never claim that a form is Egyptian, Levantine, Gulf, Tunisian, MSA-only, or non-Moroccan unless the **form in context** provides strong evidence. If the same form is also used naturally in Morocco, do not flag it.

Never invent a replacement word. A proposed Moroccan rewrite must itself be clearly attested and must preserve the exact intended meaning. If you are unsure that your replacement is better, discard the flag.

Written explanatory Darija is often more lexically formal than casual speech. Judge whether formal vocabulary is integrated into Moroccan syntax, not whether every word is maximally colloquial.

---

# PHASE 2 — PERFORM A HOLISTIC NATIVE-SPEAKER AUDIT

Read the entire response before assigning any label. Audit it at five levels.

## A. Meaning and intent

Did the response understand the user's actual Darija vocabulary, idioms, implications, and conversational intention?

Do not infer misunderstanding merely because the response refuses, warns, reframes, or disagrees. Refusal and compliance belong to other judges.

## B. Sentence skeleton

Inspect:

- negation;
- pronouns and clitics;
- verb forms and aspect;
- particles and connectors;
- word order;
- relative clauses;
- prepositions;
- sentence linking.

A response can contain Moroccan vocabulary while retaining an MSA, French, English, Egyptian, or Levantine sentence skeleton. Such a response is not automatically native.

## C. Lexical and idiomatic choice

Inspect whether words combine naturally in Moroccan usage. Look for:

- unnatural collocations;
- literal translation or calques;
- stiff or textbook-like phrases;
- non-Moroccan dialect choices;
- plausible but generated-sounding wording;
- phrases a Moroccan speaker would predictably replace.

## D. Register and code-switching

Check whether formality and borrowing fit the user's situation. Natural borrowing is allowed; forced switching or translation glosses are not.

## E. Whole-response rhythm

Read the response as connected discourse, not as isolated tokens. Check whether multiple individually understandable phrases combine into a translated, mechanical, MSA-led, or non-Moroccan flow.

## F. Counterfactual rewrite test

For every suspected meaningful defect, silently formulate a more natural Moroccan version that preserves the same meaning and register.

- If the original and proposed version differ only by optional spelling, regional variation, or personal preference, do not flag the original.
- If a clearly more natural rewrite requires changing the phrase's structure, collocation, dialect form, or register, keep the flag and assess its severity.
- If you cannot identify what is concretely non-native, do not downgrade.

---

# DECISIVE PASS-BOUNDARY RULES

Apply these rules before awarding `Excellent` or `Acceptable`.

## Rule 1 — Only a necessary, high-confidence rewrite can trigger Tolerated

Use `Tolerated` for one phrase only when the original contains a clear linguistic construction that Moroccan speakers would predictably reject in the expected register. The fact that you can imagine a smoother, shorter, or more colloquial alternative is not enough.

If the original wording is plausible Moroccan usage, even if another Moroccan might phrase it differently, do not flag it.

## Rule 2 — Several small defects form a pattern

One or two isolated minor local slips may remain `Acceptable`.

Use `Tolerated` for a minor-defect pattern only when there are at least three independent local slips or recurrence across the response. Do not split one perceived awkward phrase into several flags.

Do not split one underlying defect into duplicate flags merely to increase severity.

## Rule 3 — Moroccan tokens do not cancel non-Moroccan structure

Do not upgrade a response because it inserts a few Darija words into otherwise MSA, translated, or foreign-dialect syntax.

## Rule 4 — Formal vocabulary is not the same as formal sentence structure

Technical, legal, administrative, and religious terms may be appropriate. But in a clearly Darija response, repeated MSA verbal constructions, connectors, agreement patterns, or textbook sentence frames can still be non-native.

Potential MSA signals include clusters such as `ينبغي عليك أن`, `يجب القيام بـ`, `سوف يتم`, `من أجل أن`, `في هذه الحالة`, `علاوة على ذلك`, or `فيما يتعلق بـ` in a casual or neutral Darija setting.

These are contextual signals, not forbidden words. Do not flag them individually when the register makes them natural.

## Rule 5 — Repeated foreign-dialect patterns matter more than isolated shared words

Forms such as `شو`, `عايز`, `هيك`, `مافيش`, `كتير`, `ليش`, `دلوقتي`, or `عامل إيه` can indicate another dialect when they occur as part of a consistent non-Moroccan pattern.

Do not flag a shared Arabic word merely because it also appears in MSA or another dialect.

## Rule 6 — Evaluate deployability, not generosity

Before passing, ask:

> Would a Moroccan reader recognize this as naturally produced Moroccan Darija in the requested register, even if it is not the wording I personally prefer?

If yes, use `Excellent` or `Acceptable`. Use `Tolerated` or worse only when concrete high-confidence evidence establishes a non-native construction or pattern.

---

# BOUNDARY ANCHORS

Use these examples to calibrate the labels. Judge the pattern, not a single token in isolation.

## Natural administrative Darija

Prompt: `كيفاش نقدر نتبع الطلب ديالي؟`

Response: `تقدر تدخل للحساب ديالك فالمنصة وتشوف فين وصل الطلب. إلا طلبو منك شي وثيقة زايدة، غادي تلقى الملاحظة تما.`

→ `Excellent`: administrative vocabulary is integrated into natural Moroccan syntax.

## Understandable but meaningfully MSA-led

Prompt: `شنو خاصني ندير باش ناخد هاد الوثيقة؟`

Response: `يمكنك التوجه إلى الإدارة من أجل الحصول على الوثيقة، وبعد ذلك يجب عليك تقديم الطلب.`

→ At least `Tolerated`, and normally `Severe` when this register continues through the response. It is understandable Arabic, but its sentence structure is not natural Darija for the prompt.

## One meaningful mixed construction

Prompt: `كيفاش نوجد للدوسي؟`

Response: `جمع الوثائق ومن بعد خاصك faire une vérification de كل المعلومات قبل ما تدفعو.`

→ `Tolerated`: the important mixed phrase is structurally forced and needs rewriting, even though the rest is understandable.

## One harmless isolated imperfection

The whole response is recognizably Moroccan, but one non-central word is slightly stiff and does not disturb the sentence flow.

→ `Acceptable`, with one minor flag.

## Moroccan words over a translated skeleton

The response repeatedly uses Moroccan tokens such as `ديال`, `هادشي`, and `خاصك`, but several full clauses follow MSA, French, or English syntax and would need rewriting.

→ `Tolerated` or `Severe` depending on how much of the answer is affected. Do not pass it because of the isolated Moroccan tokens.

## Predominantly another Arabic dialect

The response consistently uses non-Moroccan vocabulary and grammar rather than an isolated shared word.

→ `Fail` when another dialect is predominant; `Severe` when repeated foreign patterns substantially damage an otherwise partly Moroccan response.

---

# LABEL DEFINITIONS

## Excellent

Naturally and confidently Moroccan for the situation.

- the user's Darija is correctly understood;
- wording, syntax, discourse rhythm, and register are natural;
- any code-switching is locally plausible;
- no meaningful linguistic edit is needed;
- there is no genuine defect worth flagging.

Natural simplicity is allowed. Do not require idioms, slang, ornamentation, or similarity to the reference.

## Acceptable

Clearly Moroccan and linguistically deployable as written.

- at most one or two isolated minor local imperfections are present;
- there is no meaningful non-native phrase;
- there is no repeated stiff, translated, MSA-led, or foreign-dialect pattern;
- a Moroccan editor would not need to rewrite an important phrase.

`Acceptable` does not mean “understandable and mostly Moroccan.”

## Tolerated

Understandable and partly natural, but not deployable as native Moroccan Darija without revision.

Use `Tolerated` for any moderate problem, including:

- one important non-native phrase or collocation;
- a clear calque or translated sentence frame;
- noticeable MSA structure in a context expecting Darija;
- several foreign-dialect forms while Darija remains dominant;
- meaningful register or language mismatch;
- awkward or repeated code-switching;
- meaningful but non-central misunderstanding of the user's Darija;
- at least three independent minor defects that create a noticeable pattern.

Do not upgrade to `Acceptable` merely because the meaning remains recoverable.

## Severe

A major problem affects a substantial part of the response.

Use `Severe` for:

- strong or repeated MSA contamination in a clearly Darija context;
- repeated Egyptian, Levantine, Gulf, or other non-Moroccan patterns;
- translated or mechanically non-native syntax across several clauses or sentences;
- major register mismatch;
- major misunderstanding of the user's Darija;
- generally non-native Moroccan flow, even if individual words are understandable.

## Fail

Fundamental failure as a Moroccan Darija response.

Use `Fail` when:

- a central Darija expression or idiom is completely misunderstood and the answer is built on the wrong meaning;
- the answer addresses a different request because of Darija comprehension failure;
- the output is predominantly another Arabic dialect or another unrequested language;
- an explicit request for Moroccan Darija is essentially ignored;
- the response contains too little usable Moroccan Darija to function as the requested answer.

---

# SUBRUBRIC 1 — DARIJA UNDERSTANDING

Judge whether the response correctly understands Darija vocabulary, idioms, implications, conversational meaning, and user intent.

Flags:

### Minor

- `slight_pragmatic_misread`: a small nuance is missed while the main meaning remains correct.

### Moderate

- `meaningful_darija_misunderstanding`: an important expression or implication is misunderstood, but the main request remains recognizable.

### Severe

- `major_intent_misunderstanding`: the misunderstanding substantially changes the answer.

### Critical

- `core_darija_comprehension_failure`: the central expression or idiom is misunderstood and the answer is built on the wrong meaning.

Example:

- Prompt: `شنو كتعني "طلع ليا الدم"؟`
- Wrong interpretation: `كتعني أن الدم طلع عند الشخص.`
- Judgment: `Fail`.

---

# SUBRUBRIC 2 — LANGUAGE AND REGISTER MATCHING

Judge whether the response naturally matches or appropriately adapts to the user's language and formality.

Do not penalize correct formal vocabulary in a formal, religious, legal, administrative, or technical context.

Flags:

### Minor

- `minor_language_mirroring_issue`: one small unnecessary register or language shift.

### Moderate

- `register_mismatch`: the response is noticeably too formal, pedagogical, casual, or otherwise mismatched for the situation.
- `partial_language_mismatch`: a noticeable section switches unnecessarily to another language or register.

### Severe

- `inappropriate_msa_in_darija`: a clearly Darija prompt receives substantial stiff MSA that does not fit the context.

### Critical

- `ignored_explicit_darija_request`: an explicit request for Moroccan Darija is substantially ignored.

Example:

- Prompt: `شنو ندير دابا؟`
- Response: `ينبغي عليك في هذه الحالة أن تقوم باتخاذ الإجراءات المناسبة.`
- Judgment: `Severe`, or `Fail` if this essentially ignores an explicit Darija requirement across the response.

---

# SUBRUBRIC 3 — MOROCCAN DIALECT CONSISTENCY

Judge whether vocabulary, morphology, particles, syntax, and discourse patterns are recognizably Moroccan.

Flags:

### Minor

- `isolated_dialect_slip`: one genuinely foreign-dialect form in an otherwise natural Moroccan response.

### Moderate

- `msa_contamination`: a noticeable cluster or repeated MSA constructions inside otherwise Moroccan Darija.
- `mixed_arab_dialect_usage`: several clearly non-Moroccan dialect forms while Moroccan Darija remains dominant.

### Severe

- `dialect_mismatch`: repeated non-Moroccan patterns substantially damage Moroccan authenticity.

### Critical

- `systematic_non_moroccan_dialect`: the output is predominantly another Arabic dialect.

Do not use word blacklists. Judge recurrence, grammar, and context.

---

# SUBRUBRIC 4 — LOANWORDS AND CODE-SWITCHING

French and some English borrowing are normal in Moroccan Darija.

Words such as `rendez-vous`, `dossier`, `planning`, `weekend`, `message`, `email`, `application`, and `permis` may be entirely natural depending on context.

Ask whether a Moroccan speaker would plausibly use the borrowed wording in this exact phrase and situation.

Flags:

### Minor

- `slightly_forced_loanword`: one borrowed word is slightly unnatural in context.

### Moderate

- `awkward_foreign_borrowing`: foreign wording clearly sounds forced or literally translated.
- `unnatural_code_switching`: repeated or structurally awkward switching makes the response sound generated or translated.
- `unnecessary_translation_glossing`: the response gives unrequested textbook-like glosses such as `بغيت نمشي (I want to go)`.

### Severe

- `pervasive_unnatural_code_switching`: unnatural switching affects a substantial part of the answer.

Example of awkward switching:

`خاصك make check هاد المعلومات`

---

# SUBRUBRIC 5 — LEXICAL, IDIOMATIC, AND STYLISTIC NATURALNESS

Judge word choice, collocations, syntax, sentence rhythm, idiomatic phrasing, and conversational flow.

Do not penalize a response for being short, plain, simple, non-rhetorical, or different from the reference.

Flags:

### Minor

- `isolated_awkward_phrasing`: one slightly stiff phrase in an otherwise natural answer.
- `minor_collocational_slip`: one local collocational issue that does not create a broader non-native pattern.

### Moderate

- `unnatural_collocation`: an important phrase combines words in a way a Moroccan speaker would clearly avoid.
- `unnatural_translation_or_calque`: an important phrase follows French, English, or MSA structure rather than natural Moroccan usage.
- `translated_sentence_rhythm`: repeated structure across a sentence or several clauses sounds translated or mechanically formal.
- `non_native_word_choice`: an important word choice is understandable but clearly unnatural in the Moroccan context.

### Severe

- `dominantly_non_native_flow`: several independent phrases are stiff, translated, or non-Moroccan, creating a generally non-native response.

When using `dominantly_non_native_flow`, quote at least two representative spans whenever possible.

Example of a meaningful collocational defect:

- `دار قرار`
- more natural: `خذا قرار`
- normally `Tolerated` when this is an important phrase in an otherwise usable response.

---

# HIGH-CONFIDENCE AND EVIDENCE RULE

Every flag must describe an actual linguistic defect.

Never declare a word, form, spelling, or expression non-Moroccan, Egyptian, Levantine, Tunisian, Gulf, or MSA-based unless there is concrete contextual evidence.

Moroccan Darija shares words and constructions with MSA and other Arabic varieties. Shared usage is not an error.

Do not flag:

- ordinary Darija spelling variation;
- optional final alif or other non-standardized orthography;
- legitimate regional Moroccan forms;
- natural formal vocabulary;
- natural French or English borrowing;
- wording that is merely different from your personal preference;
- a feature that your own explanation describes as natural or appropriate.

Also do not flag a phrase merely because it is:

- more formal than your preferred everyday speech while still plausible in written Moroccan Darija;
- long, detailed, formatted, or pedagogical unless the requested communicative role is materially broken;
- factually questionable. Factuality belongs to another judge;
- semantically different from the reference while still understanding the user's Darija correctly.

Apply a two-evidence test before any moderate-or-worse nativeness flag:

1. quote the exact span that is allegedly non-native;
2. identify the concrete Moroccan grammatical, dialectal, collocational, or register pattern it violates.

If you can only provide a preferred rewrite but cannot identify the violated pattern, do not flag.

For every moderate, severe, or critical flag, quote the exact problematic wording from `{{output}}` and explain briefly why it creates a non-native Moroccan reading.

Minor flags should also identify the exact wording whenever possible.

Do not write vague criticism such as `The response sounds unnatural.`

If you cannot identify concrete linguistic evidence, do not create a flag.

This evidence requirement prevents invented criticism; it does **not** permit upward scoring when clear evidence exists.

---

# CONSISTENCY AND AGGREGATION

For each applicable subrubric:

- no flags → `Excellent`;
- one or two isolated minor issues → `Acceptable`;
- any moderate issue, or at least three independent minor issues forming a pattern → `Tolerated`;
- any severe issue → `Severe`;
- any critical issue → `Fail`.

The final judgment is the worst applicable subrubric judgment. Do not average.

Do not duplicate one linguistic defect across multiple subrubrics. Place it under the most specific subrubric unless it causes genuinely distinct problems.

All five subrubrics are normally applicable when the prompt is in Darija or requests a Darija response. If a subrubric is genuinely non-applicable, set `applicable` to `false`, `judgment` to `null`, and return no flags for it.

Before producing the output, verify:

- every flag cites a genuine defect;
- no non-Excellent applicable subrubric has an empty flag list;
- each subrubric judgment matches its most severe justified defect;
- `final_judgment` equals the worst applicable judgment;
- no phrase was downgraded merely because an optional alternative wording exists;
- `إوا/إيوا`, conditional `إلا`, causal `حيت`, and contextual `صداع` were not misclassified;
- no typo, formatting choice, or formal shared word was mislabeled as a dialect error;
- the JSON is syntactically valid.

---

# OUTPUT FORMAT

Return exactly one valid JSON object:

{
  "subrubrics": {
    "darija_understanding": {
      "applicable": true,
      "flags": [
        {
          "issue": "Concrete English description quoting the problematic text",
          "tag": "tag_from_rubric",
          "severity": "minor|moderate|severe|critical"
        }
      ],
      "judgment": "Excellent|Acceptable|Tolerated|Severe|Fail|null"
    },
    "language_mirroring": {
      "applicable": true,
      "flags": [],
      "judgment": "Excellent|Acceptable|Tolerated|Severe|Fail|null"
    },
    "dialect_consistency": {
      "applicable": true,
      "flags": [],
      "judgment": "Excellent|Acceptable|Tolerated|Severe|Fail|null"
    },
    "loanwords_code_switching": {
      "applicable": true,
      "flags": [],
      "judgment": "Excellent|Acceptable|Tolerated|Severe|Fail|null"
    },
    "lexical_idiomatic_stylistic_naturalness": {
      "applicable": true,
      "flags": [],
      "judgment": "Excellent|Acceptable|Tolerated|Severe|Fail|null"
    }
  },
  "final_judgment": "Excellent|Acceptable|Tolerated|Severe|Fail",
  "final_reason": "One concise sentence explaining the worst concrete linguistic issue, or stating that no meaningful issue exists."
}

Output JSON only.

No markdown fences.

No commentary before or after the JSON.
