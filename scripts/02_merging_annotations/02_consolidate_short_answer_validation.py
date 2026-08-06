from __future__ import annotations

import argparse
import math
import re
import unicodedata
from collections import Counter
from pathlib import Path
from typing import Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

import numpy as np
import pandas as pd
from openpyxl import load_workbook
from openpyxl.formatting.rule import FormulaRule
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation


# =============================================================================
# CONFIGURATION
# =============================================================================

DEFAULT_INPUT_DIR = Path("validation_short_answer") / "annotateurs_livrables"
DEFAULT_OUTPUT_FILE = (
    Path("validation_short_answer")
    / "short_answer_cross_validation_consolidation.xlsx"
)

ANNOTATION_SHEET_NAME = "SHORT_ANSWER_REVIEW"
EXPECTED_ANNOTATOR_IDS = [f"ANN_{number:02d}" for number in range(1, 10)]

ANSWER_CORRECTNESS_VALUES = ["correct", "minor_fix", "incorrect"]
QUESTION_QUALITY_VALUES = ["ok", "review"]
REVIEW_ROUND_VALUES = ["primary", "second_check"]

PREFERRED_SOURCE_COLUMNS = [
    "Axe",
    "Difficulty",
    "intent_group",
    "intent_category",
    "input",
    "answer",
    "item_id",
]

REQUIRED_COLUMNS = [
    "item_id",
    "annotator_id",
    "review_round",
    "answer_correctness",
    "question_quality",
    "accepted_variants",
    "supporting_source",
    "review_comment",
]

ANNOTATION_COLUMNS = [
    "annotator_id",
    "review_round",
    "answer_correctness",
    "question_quality",
    "accepted_variants",
    "supporting_source",
    "review_comment",
]

# Conservative indicators that an annotator explicitly could not verify a fact.
VERIFICATION_PROBLEM_PATTERN = re.compile(
    r"\b(?:"
    r"cannot\s+verify|could\s+not\s+verify|not\s+verified|unverifiable|"
    r"source\s+not\s+found|source\s+insufficient|"
    r"impossible\s+[àa]\s+v[ée]rifier|non\s+v[ée]rifi[ée]|"
    r"source\s+introuvable|source\s+insuffisante|"
    r"pas\s+pu\s+v[ée]rifier|n['’]ai\s+pas\s+pu\s+v[ée]rifier"
    r")\b",
    flags=re.IGNORECASE,
)

# Columns carrying personal identity are always removed and never written.
PRIVATE_IDENTITY_COLUMNS_NORMALIZED = {
    "annotatorname",
    "reviewername",
    "evaluatorname",
    "validatorname",
    "fullname",
    "nomannotateur",
    "nomreviewer",
    "nomvalidateur",
}

INTERNAL_COLUMNS = {
    "_workbook_number",
    "_source_row_number",
    "_item_key",
    "_judgment_issue",
    "_judgment_complete",
    "_verification_problem",
}


# =============================================================================
# TEXT AND VALUE UTILITIES
# =============================================================================


def has_value(value: object) -> bool:
    return not pd.isna(value) and bool(str(value).strip())


def clean_text(value: object) -> str:
    if not has_value(value):
        return ""
    return str(value).strip()


def normalize_text(value: object) -> str:
    """Normalize text for comparisons without changing the displayed source text."""
    text = clean_text(value)
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.lower().strip()
    text = re.sub(r"[’'`]+", "'", text)
    text = re.sub(r"\s+", " ", text)
    return text


def normalize_column_name(value: object) -> str:
    text = unicodedata.normalize("NFKD", str(value))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return re.sub(r"[^a-z0-9]+", "", text.lower())


def is_private_identity_column(column: object) -> bool:
    return normalize_column_name(column) in PRIVATE_IDENTITY_COLUMNS_NORMALIZED


def normalize_item_id(value: object) -> str:
    if not has_value(value):
        return ""
    if isinstance(value, (int, np.integer)):
        return str(int(value))
    if isinstance(value, (float, np.floating)) and float(value).is_integer():
        return str(int(value))
    return str(value).strip()


def normalize_annotator_id(value: object) -> str:
    text = clean_text(value).upper()
    text = re.sub(r"\s+", "", text)
    match = re.fullmatch(r"ANN[_-]?(\d{1,2})", text)
    if match:
        return f"ANN_{int(match.group(1)):02d}"
    return text


def normalize_category(value: object, field: str) -> str:
    text = clean_text(value).lower()
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = re.sub(r"[\s\-/]+", "_", text)
    text = re.sub(r"_+", "_", text).strip("_")

    aliases: Dict[str, Dict[str, str]] = {
        "answer_correctness": {
            "correct": "correct",
            "minor_fix": "minor_fix",
            "minorfix": "minor_fix",
            "incorrect": "incorrect",
        },
        "question_quality": {
            "ok": "ok",
            "review": "review",
            "a_revoir": "review",
            "arevoir": "review",
        },
        "review_round": {
            "primary": "primary",
            "second_check": "second_check",
            "secondcheck": "second_check",
            "secondary": "second_check",
        },
    }
    return aliases.get(field, {}).get(text, text)


def ordered_unique(values: Iterable[object]) -> List[str]:
    result: List[str] = []
    seen = set()
    for value in values:
        text = clean_text(value)
        if not text:
            continue
        key = normalize_text(text)
        if key not in seen:
            seen.add(key)
            result.append(text)
    return result


def split_variants(value: object) -> List[str]:
    text = clean_text(value)
    if not text:
        return []
    return ordered_unique(part.strip() for part in text.split("|") if part.strip())


def combine_annotated_text(rows: pd.DataFrame, column: str) -> str:
    """Combine text while retaining only annotator IDs as provenance."""
    parts: List[str] = []
    for _, row in rows.iterrows():
        value = clean_text(row.get(column, ""))
        if value:
            parts.append(f"{row['annotator_id']}: {value}")
    return " || ".join(parts)


def join_issues(issues: Iterable[str]) -> str:
    return " | ".join(ordered_unique(issues))


def yes_no(value: bool) -> str:
    return "yes" if value else "no"


# =============================================================================
# INPUT DISCOVERY AND READING
# =============================================================================


def discover_workbooks(input_dir: Path, output_file: Path) -> List[Path]:
    if not input_dir.exists():
        raise FileNotFoundError(f"Input folder not found: {input_dir}")
    if not input_dir.is_dir():
        raise NotADirectoryError(f"Input path is not a folder: {input_dir}")

    candidates: List[Path] = []
    for pattern in ("*.xlsx", "*.xlsm"):
        candidates.extend(input_dir.glob(pattern))

    output_resolved = output_file.resolve()
    workbooks = sorted(
        path
        for path in candidates
        if not path.name.startswith("~$") and path.resolve() != output_resolved
    )
    if not workbooks:
        raise FileNotFoundError(
            f"No .xlsx or .xlsm workbook found in: {input_dir}"
        )
    return workbooks


def read_one_workbook(
    workbook_path: Path,
    workbook_number: int,
    sheet_name: str,
) -> pd.DataFrame:
    try:
        df = pd.read_excel(
            workbook_path,
            sheet_name=sheet_name,
            dtype=object,
            engine="openpyxl",
        )
    except ValueError as exc:
        available = pd.ExcelFile(workbook_path, engine="openpyxl").sheet_names
        raise ValueError(
            f"Workbook #{workbook_number} does not contain sheet '{sheet_name}'. "
            f"Available sheets: {', '.join(available)}"
        ) from exc

    df.columns = [str(column).strip() for column in df.columns]
    if len(set(df.columns)) != len(df.columns):
        raise ValueError(f"Workbook #{workbook_number} has duplicate column names.")

    # Remove empty Excel-generated columns and every personal identity column.
    removable_columns = [
        column
        for column in df.columns
        if (
            re.match(r"^Unnamed:", column, flags=re.IGNORECASE)
            and df[column].isna().all()
        )
        or is_private_identity_column(column)
    ]
    if removable_columns:
        df = df.drop(columns=removable_columns)

    missing = [column for column in REQUIRED_COLUMNS if column not in df.columns]
    if missing:
        raise KeyError(
            f"Workbook #{workbook_number} is missing required columns: "
            + ", ".join(missing)
        )

    # Ignore rows that contain neither an item nor an annotation.
    meaningful_columns = [
        "item_id",
        "annotator_id",
        "review_round",
        "answer_correctness",
        "question_quality",
        "accepted_variants",
        "supporting_source",
        "review_comment",
    ]
    meaningful_mask = df[meaningful_columns].apply(
        lambda column: column.map(has_value)
    ).any(axis=1)
    df = df.loc[meaningful_mask].copy()

    if df.empty:
        raise ValueError(f"Workbook #{workbook_number} contains no completed rows.")

    df["_workbook_number"] = workbook_number
    df["_source_row_number"] = df.index + 2

    df["item_id"] = df["item_id"].map(normalize_item_id)
    df["_item_key"] = df["item_id"]
    df["annotator_id"] = df["annotator_id"].map(normalize_annotator_id)
    df["review_round"] = df["review_round"].map(
        lambda value: normalize_category(value, "review_round")
    )
    df["answer_correctness"] = df["answer_correctness"].map(
        lambda value: normalize_category(value, "answer_correctness")
    )
    df["question_quality"] = df["question_quality"].map(
        lambda value: normalize_category(value, "question_quality")
    )

    for column in ["accepted_variants", "supporting_source", "review_comment"]:
        df[column] = df[column].map(clean_text)

    nonempty_ids = ordered_unique(df["annotator_id"])
    if len(nonempty_ids) != 1:
        raise ValueError(
            f"Workbook #{workbook_number} must contain exactly one annotator_id; "
            f"found: {', '.join(nonempty_ids) if nonempty_ids else 'none'}"
        )

    workbook_annotator_id = nonempty_ids[0]
    if workbook_annotator_id not in EXPECTED_ANNOTATOR_IDS:
        raise ValueError(
            f"Workbook #{workbook_number} contains an unexpected annotator_id: "
            f"{workbook_annotator_id}"
        )

    return df.reset_index(drop=True)


def load_all_judgments(
    workbook_paths: Sequence[Path],
    sheet_name: str,
) -> Tuple[pd.DataFrame, List[str]]:
    frames: List[pd.DataFrame] = []
    source_columns_order: List[str] = []

    for workbook_number, workbook_path in enumerate(workbook_paths, start=1):
        df = read_one_workbook(workbook_path, workbook_number, sheet_name)
        frames.append(df)

        for column in df.columns:
            if (
                column not in ANNOTATION_COLUMNS
                and column not in INTERNAL_COLUMNS
                and not is_private_identity_column(column)
                and column not in source_columns_order
            ):
                source_columns_order.append(column)

    all_judgments = pd.concat(frames, ignore_index=True, sort=False)

    # Put the standard source schema first, then preserve any additional source fields.
    preferred_present = [
        column for column in PREFERRED_SOURCE_COLUMNS if column in source_columns_order
    ]
    other_source_columns = [
        column
        for column in source_columns_order
        if column not in preferred_present and column != "item_id"
    ]
    source_columns = preferred_present + other_source_columns

    return all_judgments, source_columns


# =============================================================================
# JUDGMENT VALIDATION
# =============================================================================


def validate_judgment_row(row: pd.Series) -> Tuple[str, bool, bool]:
    issues: List[str] = []

    if not clean_text(row.get("item_id")):
        issues.append("missing item_id")

    annotator_id = clean_text(row.get("annotator_id"))
    if not annotator_id:
        issues.append("missing annotator_id")
    elif annotator_id not in EXPECTED_ANNOTATOR_IDS:
        issues.append("unexpected annotator_id")

    review_round = clean_text(row.get("review_round"))
    if not review_round:
        issues.append("missing review_round")
    elif review_round not in REVIEW_ROUND_VALUES:
        issues.append("invalid review_round")

    answer_correctness = clean_text(row.get("answer_correctness"))
    if not answer_correctness:
        issues.append("missing answer_correctness")
    elif answer_correctness not in ANSWER_CORRECTNESS_VALUES:
        issues.append("invalid answer_correctness")

    question_quality = clean_text(row.get("question_quality"))
    if not question_quality:
        issues.append("missing question_quality")
    elif question_quality not in QUESTION_QUALITY_VALUES:
        issues.append("invalid question_quality")

    supporting_source = clean_text(row.get("supporting_source"))
    if not supporting_source:
        issues.append("missing supporting_source")

    review_comment = clean_text(row.get("review_comment"))
    comment_required = (
        answer_correctness in {"minor_fix", "incorrect"}
        or question_quality == "review"
    )
    if comment_required and not review_comment:
        issues.append("missing required review_comment")

    verification_text = f"{supporting_source} {review_comment}".strip()
    verification_problem = bool(
        verification_text and VERIFICATION_PROBLEM_PATTERN.search(verification_text)
    )
    if verification_problem:
        issues.append("verification problem explicitly reported")

    return join_issues(issues), not issues, verification_problem


def add_judgment_quality_columns(all_judgments: pd.DataFrame) -> pd.DataFrame:
    df = all_judgments.copy()
    validation = df.apply(validate_judgment_row, axis=1, result_type="expand")
    validation.columns = [
        "_judgment_issue",
        "_judgment_complete",
        "_verification_problem",
    ]
    df = pd.concat([df, validation], axis=1)
    df["judgment_complete"] = df["_judgment_complete"].map(yes_no)
    df["judgment_issue"] = df["_judgment_issue"]
    df["verification_problem"] = df["_verification_problem"].map(yes_no)
    return df


# =============================================================================
# CONSOLIDATION AND DECISION RULES
# =============================================================================


def canonical_source_values(
    rows: pd.DataFrame,
    source_columns: Sequence[str],
) -> Tuple[Dict[str, object], List[str]]:
    canonical: Dict[str, object] = {}
    conflicts: List[str] = []

    for column in source_columns:
        if column == "item_id":
            canonical[column] = clean_text(rows.iloc[0].get("item_id", ""))
            continue

        values = [value for value in rows[column].tolist() if has_value(value)] if column in rows else []
        canonical[column] = values[0] if values else ""
        normalized = ordered_unique(normalize_text(value) for value in values)
        if len(normalized) > 1:
            conflicts.append(column)

    return canonical, conflicts


def extract_round_row(rows: pd.DataFrame, review_round: str) -> Optional[pd.Series]:
    selected = rows[rows["review_round"] == review_round]
    if len(selected) == 1:
        return selected.iloc[0]
    return None


def prefixed_judgment_fields(
    row: Optional[pd.Series],
    prefix: str,
) -> Dict[str, object]:
    fields = {
        f"{prefix}_annotator_id": "",
        f"{prefix}_answer_correctness": "",
        f"{prefix}_question_quality": "",
        f"{prefix}_accepted_variants": "",
        f"{prefix}_supporting_source": "",
        f"{prefix}_review_comment": "",
        f"{prefix}_judgment_complete": "",
        f"{prefix}_judgment_issue": "",
        f"{prefix}_verification_problem": "",
    }
    if row is None:
        return fields

    fields.update(
        {
            f"{prefix}_annotator_id": clean_text(row.get("annotator_id")),
            f"{prefix}_answer_correctness": clean_text(
                row.get("answer_correctness")
            ),
            f"{prefix}_question_quality": clean_text(row.get("question_quality")),
            f"{prefix}_accepted_variants": clean_text(
                row.get("accepted_variants")
            ),
            f"{prefix}_supporting_source": clean_text(
                row.get("supporting_source")
            ),
            f"{prefix}_review_comment": clean_text(row.get("review_comment")),
            f"{prefix}_judgment_complete": yes_no(
                bool(row.get("_judgment_complete", False))
            ),
            f"{prefix}_judgment_issue": clean_text(row.get("_judgment_issue")),
            f"{prefix}_verification_problem": yes_no(
                bool(row.get("_verification_problem", False))
            ),
        }
    )
    return fields


def determine_provisional_decision(
    primary: Optional[pd.Series],
    second: Optional[pd.Series],
    item_issues: Sequence[str],
    merged_variants: Sequence[str],
) -> Tuple[str, str, str, str]:
    """
    Return:
      provisional_decision, requires_adjudication, decision_reason, recommended_action
    """
    if item_issues:
        return (
            "incomplete_or_invalid_item",
            "yes",
            join_issues(item_issues),
            "Resolve assignment, missing fields, source conflicts, or invalid values before final adjudication.",
        )

    rows = [row for row in (primary, second) if row is not None]
    if not rows:
        return (
            "incomplete_or_invalid_item",
            "yes",
            "no usable judgment",
            "Recover the missing review and then adjudicate.",
        )

    if any(row["question_quality"] == "review" for row in rows):
        return (
            "review_question",
            "yes",
            "at least one reviewer selected question_quality=review",
            "A third reviewer must decide whether to rewrite, clarify, replace, or reject the question.",
        )

    if any(bool(row["_verification_problem"]) for row in rows):
        return (
            "adjudicate_source_verification",
            "yes",
            "at least one reviewer explicitly reported that the answer could not be verified",
            "Verify the fact with an authoritative source before keeping or correcting the item.",
        )

    labels = [row["answer_correctness"] for row in rows]
    if second is not None and len(set(labels)) > 1:
        return (
            "adjudicate_answer_disagreement",
            "yes",
            "primary and second reviewers disagree on answer_correctness",
            "A third reviewer must determine the correct answer status and required correction.",
        )

    agreed_label = labels[0]
    if agreed_label == "correct":
        if merged_variants:
            return (
                "accept_with_variants",
                "no",
                "answer accepted; additional equivalent variants were recorded",
                "Keep the current answer and add the merged accepted variants.",
            )
        return (
            "accept",
            "no",
            "answer_correctness=correct and question_quality=ok",
            "Keep the item unchanged.",
        )

    if agreed_label == "minor_fix":
        return (
            "apply_minor_correction",
            "yes",
            "answer core is correct but at least one minor correction was requested",
            "The adjudicator confirms the corrected reference answer and any accepted variants.",
        )

    if agreed_label == "incorrect":
        return (
            "correct_or_reject",
            "yes",
            "reference answer was judged incorrect",
            "The adjudicator replaces the answer when a verified correction exists; otherwise reject the item.",
        )

    return (
        "incomplete_or_invalid_item",
        "yes",
        "unrecognized answer_correctness value",
        "Correct the invalid annotation and adjudicate.",
    )


def consolidate_items(
    all_judgments: pd.DataFrame,
    source_columns: Sequence[str],
) -> Tuple[pd.DataFrame, pd.DataFrame]:
    item_rows: List[Dict[str, object]] = []
    issue_rows: List[Dict[str, object]] = []

    # Rows without an item_id cannot be grouped into an item decision.
    missing_id_rows = all_judgments[all_judgments["_item_key"] == ""]
    for _, row in missing_id_rows.iterrows():
        issue_rows.append(
            {
                "issue_scope": "judgment",
                "item_id": "",
                "annotator_id": clean_text(row.get("annotator_id")),
                "review_round": clean_text(row.get("review_round")),
                "issue": clean_text(row.get("_judgment_issue")) or "missing item_id",
            }
        )

    usable = all_judgments[all_judgments["_item_key"] != ""].copy()

    for item_id, rows in usable.groupby("_item_key", sort=True, dropna=False):
        rows = rows.copy().reset_index(drop=True)
        source_values, source_conflicts = canonical_source_values(rows, source_columns)

        primary_rows = rows[rows["review_round"] == "primary"]
        second_rows = rows[rows["review_round"] == "second_check"]
        unexpected_round_rows = rows[
            ~rows["review_round"].isin(REVIEW_ROUND_VALUES)
        ]

        primary = extract_round_row(rows, "primary")
        second = extract_round_row(rows, "second_check")

        item_issues: List[str] = []
        if len(primary_rows) != 1:
            item_issues.append(
                f"expected exactly 1 primary judgment; found {len(primary_rows)}"
            )
        if len(second_rows) > 1:
            item_issues.append(
                f"expected at most 1 second_check judgment; found {len(second_rows)}"
            )
        if not unexpected_round_rows.empty:
            item_issues.append(
                f"found {len(unexpected_round_rows)} judgment(s) with invalid review_round"
            )

        if primary is not None and second is not None:
            if primary["annotator_id"] == second["annotator_id"]:
                item_issues.append(
                    "primary and second_check were completed by the same annotator_id"
                )

        if source_conflicts:
            item_issues.append(
                "source-column conflicts: " + ", ".join(source_conflicts)
            )

        incomplete_rows = rows[~rows["_judgment_complete"]]
        if not incomplete_rows.empty:
            details = ordered_unique(incomplete_rows["_judgment_issue"])
            item_issues.append("incomplete/invalid judgment: " + "; ".join(details))

        duplicate_keys = (
            rows.groupby(["annotator_id", "review_round"], dropna=False)
            .size()
            .loc[lambda series: series > 1]
        )
        if not duplicate_keys.empty:
            item_issues.append("duplicate judgment for the same annotator_id and round")

        merged_variants: List[str] = []
        for value in rows["accepted_variants"]:
            merged_variants.extend(split_variants(value))
        merged_variants = ordered_unique(merged_variants)

        provisional_decision, requires_adjudication, reason, action = (
            determine_provisional_decision(
                primary=primary,
                second=second,
                item_issues=item_issues,
                merged_variants=merged_variants,
            )
        )

        answer_agreement = "not_applicable"
        question_agreement = "not_applicable"
        if primary is not None and second is not None:
            answer_agreement = yes_no(
                primary["answer_correctness"] == second["answer_correctness"]
            )
            question_agreement = yes_no(
                primary["question_quality"] == second["question_quality"]
            )

        result: Dict[str, object] = dict(source_values)
        result.update(
            {
                "judgment_count": len(rows),
                "primary_judgment_count": len(primary_rows),
                "second_check_judgment_count": len(second_rows),
                "unique_annotator_count": rows["annotator_id"].nunique(),
                "double_reviewed": yes_no(second is not None),
                "answer_correctness_agreement": answer_agreement,
                "question_quality_agreement": question_agreement,
                "source_conflict_columns": ", ".join(source_conflicts),
                "merged_accepted_variants": " | ".join(merged_variants),
                "all_supporting_sources": combine_annotated_text(
                    rows, "supporting_source"
                ),
                "all_review_comments": combine_annotated_text(
                    rows, "review_comment"
                ),
                "provisional_decision": provisional_decision,
                "requires_adjudication": requires_adjudication,
                "decision_reason": reason,
                "recommended_action": action,
            }
        )
        result.update(prefixed_judgment_fields(primary, "primary"))
        result.update(prefixed_judgment_fields(second, "second"))
        item_rows.append(result)

        if item_issues:
            for issue in item_issues:
                issue_rows.append(
                    {
                        "issue_scope": "item",
                        "item_id": item_id,
                        "annotator_id": "",
                        "review_round": "",
                        "issue": issue,
                    }
                )

        for _, judgment in rows[rows["_judgment_issue"] != ""].iterrows():
            issue_rows.append(
                {
                    "issue_scope": "judgment",
                    "item_id": item_id,
                    "annotator_id": judgment["annotator_id"],
                    "review_round": judgment["review_round"],
                    "issue": judgment["_judgment_issue"],
                }
            )

    consolidated = pd.DataFrame(item_rows)
    if not consolidated.empty:
        source_first = [
            column for column in source_columns if column in consolidated.columns
        ]
        decision_columns = [
            "judgment_count",
            "primary_judgment_count",
            "second_check_judgment_count",
            "unique_annotator_count",
            "double_reviewed",
            "answer_correctness_agreement",
            "question_quality_agreement",
            "primary_annotator_id",
            "primary_answer_correctness",
            "primary_question_quality",
            "primary_accepted_variants",
            "primary_supporting_source",
            "primary_review_comment",
            "primary_judgment_complete",
            "primary_judgment_issue",
            "primary_verification_problem",
            "second_annotator_id",
            "second_answer_correctness",
            "second_question_quality",
            "second_accepted_variants",
            "second_supporting_source",
            "second_review_comment",
            "second_judgment_complete",
            "second_judgment_issue",
            "second_verification_problem",
            "source_conflict_columns",
            "merged_accepted_variants",
            "all_supporting_sources",
            "all_review_comments",
            "provisional_decision",
            "requires_adjudication",
            "decision_reason",
            "recommended_action",
        ]
        consolidated = consolidated[source_first + decision_columns]
        consolidated = consolidated.sort_values("item_id").reset_index(drop=True)

    data_quality_issues = pd.DataFrame(
        issue_rows,
        columns=[
            "issue_scope",
            "item_id",
            "annotator_id",
            "review_round",
            "issue",
        ],
    ).drop_duplicates()

    return consolidated, data_quality_issues


def build_adjudication_queue(consolidated: pd.DataFrame) -> pd.DataFrame:
    if consolidated.empty:
        return pd.DataFrame()

    queue = consolidated[consolidated["requires_adjudication"] == "yes"].copy()
    queue["adjudicator_id"] = ""
    queue["adjudication_answer_correctness"] = ""
    queue["adjudication_question_quality"] = ""
    queue["adjudicated_answer"] = ""
    queue["adjudicated_accepted_variants"] = ""
    queue["adjudication_comment"] = ""
    queue["final_decision"] = ""
    queue["adjudication_status"] = "pending"
    return queue.reset_index(drop=True)


# =============================================================================
# AGREEMENT AND SUMMARY METRICS
# =============================================================================


def confusion_matrix_dataframe(
    pairs: pd.DataFrame,
    primary_column: str,
    second_column: str,
    categories: Sequence[str],
) -> pd.DataFrame:
    matrix = pd.crosstab(
        pairs[primary_column],
        pairs[second_column],
        dropna=False,
    ).reindex(index=categories, columns=categories, fill_value=0)
    matrix.index.name = "primary"
    matrix.columns.name = "second_check"
    return matrix.reset_index()


def cohen_kappa_from_labels(
    first: Sequence[str],
    second: Sequence[str],
    categories: Sequence[str],
    weight_type: str = "unweighted",
) -> float:
    if len(first) != len(second):
        raise ValueError("Kappa inputs must have the same length.")
    n = len(first)
    if n == 0:
        return math.nan

    category_to_index = {category: index for index, category in enumerate(categories)}
    k = len(categories)
    observed_counts = np.zeros((k, k), dtype=float)

    for left, right in zip(first, second):
        if left not in category_to_index or right not in category_to_index:
            continue
        observed_counts[category_to_index[left], category_to_index[right]] += 1

    valid_n = observed_counts.sum()
    if valid_n == 0:
        return math.nan

    observed = observed_counts / valid_n
    row_marginals = observed.sum(axis=1)
    column_marginals = observed.sum(axis=0)
    expected = np.outer(row_marginals, column_marginals)

    if weight_type == "unweighted":
        disagreement_weights = np.ones((k, k), dtype=float) - np.eye(k)
    elif weight_type == "linear":
        denominator = max(k - 1, 1)
        disagreement_weights = np.fromfunction(
            lambda i, j: np.abs(i - j) / denominator,
            (k, k),
            dtype=float,
        )
    elif weight_type == "quadratic":
        denominator = max(k - 1, 1)
        disagreement_weights = np.fromfunction(
            lambda i, j: ((i - j) / denominator) ** 2,
            (k, k),
            dtype=float,
        )
    else:
        raise ValueError(f"Unknown weight_type: {weight_type}")

    observed_disagreement = float((disagreement_weights * observed).sum())
    expected_disagreement = float((disagreement_weights * expected).sum())

    if expected_disagreement == 0:
        return 1.0 if observed_disagreement == 0 else math.nan
    return 1.0 - observed_disagreement / expected_disagreement


def safe_percentage(numerator: float, denominator: float) -> float:
    return round(numerator / denominator * 100, 2) if denominator else math.nan


def complete_double_review_pairs(consolidated: pd.DataFrame) -> pd.DataFrame:
    if consolidated.empty:
        return consolidated.copy()
    mask = (
        (consolidated["primary_judgment_count"] == 1)
        & (consolidated["second_check_judgment_count"] == 1)
        & (consolidated["primary_judgment_complete"] == "yes")
        & (consolidated["second_judgment_complete"] == "yes")
        & consolidated["primary_answer_correctness"].isin(
            ANSWER_CORRECTNESS_VALUES
        )
        & consolidated["second_answer_correctness"].isin(
            ANSWER_CORRECTNESS_VALUES
        )
        & consolidated["primary_question_quality"].isin(
            QUESTION_QUALITY_VALUES
        )
        & consolidated["second_question_quality"].isin(
            QUESTION_QUALITY_VALUES
        )
        & (
            consolidated["primary_annotator_id"]
            != consolidated["second_annotator_id"]
        )
    )
    return consolidated.loc[mask].copy()


def build_metrics(
    all_judgments: pd.DataFrame,
    consolidated: pd.DataFrame,
    workbook_count: int,
) -> Dict[str, pd.DataFrame]:
    observed_ids = sorted(ordered_unique(all_judgments["annotator_id"]))
    missing_ids = sorted(set(EXPECTED_ANNOTATOR_IDS) - set(observed_ids))
    unexpected_ids = sorted(set(observed_ids) - set(EXPECTED_ANNOTATOR_IDS))

    pair_df = complete_double_review_pairs(consolidated)
    n_pairs = len(pair_df)

    answer_raw = (
        float(
            (
                pair_df["primary_answer_correctness"]
                == pair_df["second_answer_correctness"]
            ).mean()
        )
        if n_pairs
        else math.nan
    )
    question_raw = (
        float(
            (
                pair_df["primary_question_quality"]
                == pair_df["second_question_quality"]
            ).mean()
        )
        if n_pairs
        else math.nan
    )

    answer_linear_kappa = cohen_kappa_from_labels(
        pair_df["primary_answer_correctness"].tolist(),
        pair_df["second_answer_correctness"].tolist(),
        ANSWER_CORRECTNESS_VALUES,
        "linear",
    )
    answer_quadratic_kappa = cohen_kappa_from_labels(
        pair_df["primary_answer_correctness"].tolist(),
        pair_df["second_answer_correctness"].tolist(),
        ANSWER_CORRECTNESS_VALUES,
        "quadratic",
    )
    question_kappa = cohen_kappa_from_labels(
        pair_df["primary_question_quality"].tolist(),
        pair_df["second_question_quality"].tolist(),
        QUESTION_QUALITY_VALUES,
        "unweighted",
    )

    total_items = len(consolidated)
    adjudication_items = int(
        (consolidated["requires_adjudication"] == "yes").sum()
    ) if total_items else 0
    variants_items = int(
        consolidated["merged_accepted_variants"].map(has_value).sum()
    ) if total_items else 0
    correction_items = int(
        consolidated["provisional_decision"].isin(
            ["apply_minor_correction", "correct_or_reject"]
        ).sum()
    ) if total_items else 0

    source_complete_judgments = int(
        all_judgments["supporting_source"].map(has_value).sum()
    )
    complete_judgments = int(all_judgments["_judgment_complete"].sum())

    overview = pd.DataFrame(
        [
            ("input_workbooks", workbook_count),
            ("expected_annotators", len(EXPECTED_ANNOTATOR_IDS)),
            ("observed_annotator_ids", ", ".join(observed_ids)),
            ("missing_annotator_ids", ", ".join(missing_ids)),
            ("unexpected_annotator_ids", ", ".join(unexpected_ids)),
            (
                "batch_complete",
                "yes" if not missing_ids and not unexpected_ids else "no",
            ),
            ("unique_items", total_items),
            ("total_judgments", len(all_judgments)),
            (
                "primary_judgments",
                int((all_judgments["review_round"] == "primary").sum()),
            ),
            (
                "second_check_judgments",
                int((all_judgments["review_round"] == "second_check").sum()),
            ),
            (
                "items_with_second_check",
                int((consolidated["second_check_judgment_count"] >= 1).sum())
                if total_items
                else 0,
            ),
            ("complete_double_review_pairs_for_agreement", n_pairs),
            ("complete_judgments", complete_judgments),
            (
                "judgment_completion_rate_percent",
                safe_percentage(complete_judgments, len(all_judgments)),
            ),
            (
                "source_completion_rate_percent",
                safe_percentage(source_complete_judgments, len(all_judgments)),
            ),
            ("items_requiring_adjudication", adjudication_items),
            (
                "adjudication_rate_percent",
                safe_percentage(adjudication_items, total_items),
            ),
            ("items_requiring_answer_correction", correction_items),
            (
                "answer_correction_rate_percent",
                safe_percentage(correction_items, total_items),
            ),
            ("items_enriched_with_variants", variants_items),
            (
                "accepted_variants_enrichment_rate_percent",
                safe_percentage(variants_items, total_items),
            ),
        ],
        columns=["metric", "value"],
    )

    agreement = pd.DataFrame(
        [
            (
                "answer_correctness",
                "raw_agreement",
                n_pairs,
                round(answer_raw, 6) if not math.isnan(answer_raw) else math.nan,
                round(answer_raw * 100, 2) if not math.isnan(answer_raw) else math.nan,
            ),
            (
                "answer_correctness",
                "linear_weighted_cohen_kappa",
                n_pairs,
                round(answer_linear_kappa, 6)
                if not math.isnan(answer_linear_kappa)
                else math.nan,
                math.nan,
            ),
            (
                "answer_correctness",
                "quadratic_weighted_cohen_kappa",
                n_pairs,
                round(answer_quadratic_kappa, 6)
                if not math.isnan(answer_quadratic_kappa)
                else math.nan,
                math.nan,
            ),
            (
                "question_quality",
                "raw_agreement",
                n_pairs,
                round(question_raw, 6)
                if not math.isnan(question_raw)
                else math.nan,
                round(question_raw * 100, 2)
                if not math.isnan(question_raw)
                else math.nan,
            ),
            (
                "question_quality",
                "cohen_kappa",
                n_pairs,
                round(question_kappa, 6)
                if not math.isnan(question_kappa)
                else math.nan,
                math.nan,
            ),
        ],
        columns=["field", "metric", "n_pairs", "value", "percent"],
    )

    by_annotator = (
        all_judgments.assign(
            is_primary=(all_judgments["review_round"] == "primary").astype(int),
            is_second=(all_judgments["review_round"] == "second_check").astype(int),
            is_complete=all_judgments["_judgment_complete"].astype(int),
            has_source=all_judgments["supporting_source"].map(has_value).astype(int),
            flagged=(
                (all_judgments["answer_correctness"] != "correct")
                | (all_judgments["question_quality"] == "review")
            ).astype(int),
        )
        .groupby("annotator_id", as_index=False)
        .agg(
            total_judgments=("item_id", "size"),
            primary_judgments=("is_primary", "sum"),
            second_check_judgments=("is_second", "sum"),
            complete_judgments=("is_complete", "sum"),
            judgments_with_source=("has_source", "sum"),
            flagged_judgments=("flagged", "sum"),
        )
    )
    if not by_annotator.empty:
        by_annotator["completion_rate_percent"] = (
            by_annotator["complete_judgments"]
            / by_annotator["total_judgments"]
            * 100
        ).round(2)
        by_annotator["source_completion_rate_percent"] = (
            by_annotator["judgments_with_source"]
            / by_annotator["total_judgments"]
            * 100
        ).round(2)
        by_annotator["flag_rate_percent"] = (
            by_annotator["flagged_judgments"]
            / by_annotator["total_judgments"]
            * 100
        ).round(2)

    def group_summary(column: str) -> pd.DataFrame:
        if consolidated.empty or column not in consolidated.columns:
            return pd.DataFrame()
        result = (
            consolidated.assign(
                is_double=(consolidated["second_check_judgment_count"] == 1).astype(int),
                needs_adjudication=(
                    consolidated["requires_adjudication"] == "yes"
                ).astype(int),
                has_variants=consolidated["merged_accepted_variants"]
                .map(has_value)
                .astype(int),
                answer_agreement=(
                    consolidated["answer_correctness_agreement"] == "yes"
                ).astype(int),
                question_agreement=(
                    consolidated["question_quality_agreement"] == "yes"
                ).astype(int),
            )
            .groupby(column, dropna=False, as_index=False)
            .agg(
                total_items=("item_id", "size"),
                double_reviewed_items=("is_double", "sum"),
                items_requiring_adjudication=("needs_adjudication", "sum"),
                items_with_variants=("has_variants", "sum"),
                answer_agreements=("answer_agreement", "sum"),
                question_agreements=("question_agreement", "sum"),
            )
        )
        result["adjudication_rate_percent"] = (
            result["items_requiring_adjudication"] / result["total_items"] * 100
        ).round(2)
        result["answer_raw_agreement_percent"] = np.where(
            result["double_reviewed_items"] > 0,
            (
                result["answer_agreements"]
                / result["double_reviewed_items"]
                * 100
            ).round(2),
            np.nan,
        )
        result["question_raw_agreement_percent"] = np.where(
            result["double_reviewed_items"] > 0,
            (
                result["question_agreements"]
                / result["double_reviewed_items"]
                * 100
            ).round(2),
            np.nan,
        )
        return result

    decision_counts = (
        consolidated["provisional_decision"]
        .value_counts(dropna=False)
        .rename_axis("provisional_decision")
        .reset_index(name="item_count")
    ) if not consolidated.empty else pd.DataFrame(
        columns=["provisional_decision", "item_count"]
    )
    if not decision_counts.empty:
        decision_counts["percentage"] = (
            decision_counts["item_count"] / total_items * 100
        ).round(2)

    answer_confusion = confusion_matrix_dataframe(
        pair_df,
        "primary_answer_correctness",
        "second_answer_correctness",
        ANSWER_CORRECTNESS_VALUES,
    )
    question_confusion = confusion_matrix_dataframe(
        pair_df,
        "primary_question_quality",
        "second_question_quality",
        QUESTION_QUALITY_VALUES,
    )

    return {
        "METRICS_OVERVIEW": overview,
        "AGREEMENT": agreement,
        "BY_ANNOTATOR": by_annotator,
        "BY_AXIS": group_summary("Axe"),
        "BY_DIFFICULTY": group_summary("Difficulty"),
        "DECISION_COUNTS": decision_counts,
        "ANSWER_CONFUSION": answer_confusion,
        "QUESTION_CONFUSION": question_confusion,
    }


# =============================================================================
# OUTPUT PREPARATION AND EXCEL FORMATTING
# =============================================================================


HEADER_FILL = PatternFill("solid", fgColor="1F4E78")
HEADER_FONT = Font(color="FFFFFF", bold=True)
GOOD_FILL = PatternFill("solid", fgColor="E2F0D9")
WARNING_FILL = PatternFill("solid", fgColor="FFF2CC")
BAD_FILL = PatternFill("solid", fgColor="F4CCCC")
INFO_FILL = PatternFill("solid", fgColor="D9EAF7")
GRAY_FILL = PatternFill("solid", fgColor="F2F2F2")
THIN_GRAY = Side(style="thin", color="B7B7B7")
TABLE_BORDER = Border(
    left=THIN_GRAY,
    right=THIN_GRAY,
    top=THIN_GRAY,
    bottom=THIN_GRAY,
)


def clean_all_judgments_for_output(
    all_judgments: pd.DataFrame,
    source_columns: Sequence[str],
) -> pd.DataFrame:
    output_columns = [
        column
        for column in source_columns
        if column in all_judgments.columns and not is_private_identity_column(column)
    ] + [
        "annotator_id",
        "review_round",
        "answer_correctness",
        "question_quality",
        "accepted_variants",
        "supporting_source",
        "review_comment",
        "judgment_complete",
        "judgment_issue",
        "verification_problem",
    ]
    result = all_judgments[output_columns].copy()
    sort_columns = [
        column
        for column in ["item_id", "review_round", "annotator_id"]
        if column in result.columns
    ]
    if sort_columns:
        result = result.sort_values(sort_columns).reset_index(drop=True)
    return result


def build_readme_dataframe() -> pd.DataFrame:
    rows = [
        ("Purpose", "Merge the nine short-answer validation workbooks, remove all personal names, compute provisional decisions, prepare adjudication, and calculate reliability metrics."),
        ("Privacy", "Only annotator_id is retained. Personal-name columns and input filenames are never written to the consolidation workbook."),
        ("Input sheet", ANNOTATION_SHEET_NAME),
        ("Expected IDs", ", ".join(EXPECTED_ANNOTATOR_IDS)),
        ("accept", "The available judgment(s) mark the answer correct, the question ok, sources are present, and no issue is detected."),
        ("accept_with_variants", "Same as accept, with additional equivalent answers merged using |."),
        ("apply_minor_correction", "The answer is fundamentally correct but requires a minor correction. It is placed in adjudication so the final corrected answer is confirmed."),
        ("correct_or_reject", "The reference answer was judged incorrect. The adjudicator must replace it using a verified source or reject the item."),
        ("review_question", "At least one reviewer marked question_quality=review. The question must be clarified, rewritten, replaced, or rejected."),
        ("adjudicate_answer_disagreement", "The primary and second reviewers disagree on answer_correctness."),
        ("adjudicate_source_verification", "A reviewer explicitly reported that the answer could not be verified."),
        ("incomplete_or_invalid_item", "The item has missing/invalid annotations, assignment problems, duplicate judgments, source-data conflicts, or other integrity issues."),
        ("Agreement subset", "Agreement and kappa are calculated only on items with exactly one complete primary review and one complete second_check review by different annotator IDs."),
        ("Answer reliability", "Raw agreement plus linear- and quadratic-weighted Cohen's kappa for correct / minor_fix / incorrect."),
        ("Question reliability", "Raw agreement plus unweighted Cohen's kappa for ok / review."),
        ("Adjudication queue", "Complete the blank adjudication columns; no annotator names are required."),
    ]
    return pd.DataFrame(rows, columns=["section", "description"])


def write_output_workbook(
    output_file: Path,
    consolidated: pd.DataFrame,
    adjudication_queue: pd.DataFrame,
    all_judgments_output: pd.DataFrame,
    metrics: Mapping[str, pd.DataFrame],
    data_quality_issues: pd.DataFrame,
) -> None:
    output_file.parent.mkdir(parents=True, exist_ok=True)

    with pd.ExcelWriter(output_file, engine="openpyxl") as writer:
        build_readme_dataframe().to_excel(
            writer, index=False, sheet_name="README"
        )
        consolidated.to_excel(
            writer, index=False, sheet_name="CONSOLIDATED_ITEMS"
        )
        adjudication_queue.to_excel(
            writer, index=False, sheet_name="ADJUDICATION_QUEUE"
        )
        all_judgments_output.to_excel(
            writer, index=False, sheet_name="ALL_JUDGMENTS"
        )
        for sheet_name, dataframe in metrics.items():
            dataframe.to_excel(writer, index=False, sheet_name=sheet_name)
        data_quality_issues.to_excel(
            writer, index=False, sheet_name="DATA_QUALITY_ISSUES"
        )

    format_output_workbook(output_file)


def style_worksheet(ws) -> None:
    ws.sheet_view.showGridLines = False
    ws.freeze_panes = "A2"
    if ws.max_row >= 1 and ws.max_column >= 1:
        ws.auto_filter.ref = ws.dimensions

    ws.row_dimensions[1].height = 40
    for cell in ws[1]:
        cell.fill = HEADER_FILL
        cell.font = HEADER_FONT
        cell.alignment = Alignment(
            horizontal="center", vertical="center", wrap_text=True
        )
        cell.border = TABLE_BORDER

    text_heavy_markers = (
        "input",
        "answer",
        "comment",
        "source",
        "variant",
        "reason",
        "action",
        "description",
        "issue",
    )

    for row in ws.iter_rows(min_row=2):
        for cell in row:
            cell.alignment = Alignment(vertical="top", wrap_text=True)
            cell.border = TABLE_BORDER

    for column_index, cells in enumerate(ws.columns, start=1):
        header = clean_text(ws.cell(1, column_index).value).lower()
        if any(marker in header for marker in text_heavy_markers):
            width = 52
        elif header in {
            "provisional_decision",
            "requires_adjudication",
            "answer_correctness_agreement",
            "question_quality_agreement",
        }:
            width = 27
        else:
            max_length = max(
                (len(str(cell.value)) for cell in cells if cell.value is not None),
                default=10,
            )
            width = min(max(max_length + 2, 12), 28)
        ws.column_dimensions[get_column_letter(column_index)].width = width


def add_consolidated_conditional_formatting(ws) -> None:
    header_to_col = {cell.value: cell.column for cell in ws[1]}
    last_row = max(ws.max_row, 2)

    if "requires_adjudication" in header_to_col:
        letter = get_column_letter(header_to_col["requires_adjudication"])
        ws.conditional_formatting.add(
            f"{letter}2:{letter}{last_row}",
            FormulaRule(formula=[f'{letter}2="yes"'], fill=BAD_FILL),
        )
        ws.conditional_formatting.add(
            f"{letter}2:{letter}{last_row}",
            FormulaRule(formula=[f'{letter}2="no"'], fill=GOOD_FILL),
        )

    if "provisional_decision" in header_to_col:
        letter = get_column_letter(header_to_col["provisional_decision"])
        for value in ["accept", "accept_with_variants"]:
            ws.conditional_formatting.add(
                f"{letter}2:{letter}{last_row}",
                FormulaRule(formula=[f'{letter}2="{value}"'], fill=GOOD_FILL),
            )
        for value in ["apply_minor_correction", "review_question"]:
            ws.conditional_formatting.add(
                f"{letter}2:{letter}{last_row}",
                FormulaRule(formula=[f'{letter}2="{value}"'], fill=WARNING_FILL),
            )
        for value in [
            "correct_or_reject",
            "adjudicate_answer_disagreement",
            "adjudicate_source_verification",
            "incomplete_or_invalid_item",
        ]:
            ws.conditional_formatting.add(
                f"{letter}2:{letter}{last_row}",
                FormulaRule(formula=[f'{letter}2="{value}"'], fill=BAD_FILL),
            )


def add_adjudication_validations(ws) -> None:
    if ws.max_row < 2:
        return
    header_to_col = {cell.value: cell.column for cell in ws[1]}
    last_row = ws.max_row

    validation_specs = {
        "adjudication_answer_correctness": ANSWER_CORRECTNESS_VALUES,
        "adjudication_question_quality": QUESTION_QUALITY_VALUES,
        "final_decision": [
            "accept",
            "accept_with_variants",
            "corrected_and_accept",
            "rewrite_question",
            "reject_item",
        ],
        "adjudication_status": ["pending", "in_progress", "completed"],
    }

    for column, values in validation_specs.items():
        if column not in header_to_col:
            continue
        column_letter = get_column_letter(header_to_col[column])
        validation = DataValidation(
            type="list",
            formula1='"' + ",".join(values) + '"',
            allow_blank=True,
        )
        validation.error = "Choose a value from the list."
        validation.errorTitle = "Invalid value"
        validation.showErrorMessage = True
        ws.add_data_validation(validation)
        validation.add(f"{column_letter}2:{column_letter}{last_row}")

    if "adjudication_status" in header_to_col:
        letter = get_column_letter(header_to_col["adjudication_status"])
        ws.conditional_formatting.add(
            f"{letter}2:{letter}{last_row}",
            FormulaRule(formula=[f'{letter}2="completed"'], fill=GOOD_FILL),
        )
        ws.conditional_formatting.add(
            f"{letter}2:{letter}{last_row}",
            FormulaRule(formula=[f'{letter}2="pending"'], fill=WARNING_FILL),
        )


def format_output_workbook(output_file: Path) -> None:
    wb = load_workbook(output_file)

    for ws in wb.worksheets:
        style_worksheet(ws)

    if "README" in wb.sheetnames:
        ws = wb["README"]
        ws.freeze_panes = "A2"
        ws.column_dimensions["A"].width = 34
        ws.column_dimensions["B"].width = 115
        for row in ws.iter_rows(min_row=2):
            row[0].fill = INFO_FILL
            row[0].font = Font(bold=True)

    if "CONSOLIDATED_ITEMS" in wb.sheetnames:
        add_consolidated_conditional_formatting(wb["CONSOLIDATED_ITEMS"])

    if "ADJUDICATION_QUEUE" in wb.sheetnames:
        add_consolidated_conditional_formatting(wb["ADJUDICATION_QUEUE"])
        add_adjudication_validations(wb["ADJUDICATION_QUEUE"])

    if "ALL_JUDGMENTS" in wb.sheetnames:
        ws = wb["ALL_JUDGMENTS"]
        header_to_col = {cell.value: cell.column for cell in ws[1]}
        if "judgment_issue" in header_to_col:
            letter = get_column_letter(header_to_col["judgment_issue"])
            last_row = max(ws.max_row, 2)
            ws.conditional_formatting.add(
                f"{letter}2:{letter}{last_row}",
                FormulaRule(formula=[f'{letter}2<>""'], fill=BAD_FILL),
            )

    if "METRICS_OVERVIEW" in wb.sheetnames:
        ws = wb["METRICS_OVERVIEW"]
        ws.column_dimensions["A"].width = 44
        ws.column_dimensions["B"].width = 48

    if "DATA_QUALITY_ISSUES" in wb.sheetnames:
        ws = wb["DATA_QUALITY_ISSUES"]
        if ws.max_row > 1:
            for row in ws.iter_rows(min_row=2):
                for cell in row:
                    cell.fill = BAD_FILL

    # Explicit workbook-level privacy check: no personal identity column survives.
    for ws in wb.worksheets:
        headers = [cell.value for cell in ws[1]] if ws.max_row >= 1 else []
        forbidden = [header for header in headers if is_private_identity_column(header)]
        if forbidden:
            raise RuntimeError(
                f"Privacy check failed in sheet '{ws.title}': "
                + ", ".join(str(value) for value in forbidden)
            )

    wb.save(output_file)


# =============================================================================
# MAIN
# =============================================================================


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Merge and consolidate short-answer cross-validation workbooks. "
            "Only annotator IDs are retained; personal names and filenames are excluded."
        )
    )
    parser.add_argument(
        "--input-dir",
        type=Path,
        default=DEFAULT_INPUT_DIR,
        help=(
            "Folder containing the annotator deliverables "
            f"(default: {DEFAULT_INPUT_DIR})."
        ),
    )
    parser.add_argument(
        "--output-file",
        type=Path,
        default=DEFAULT_OUTPUT_FILE,
        help=(
            "Consolidated Excel output "
            f"(default: {DEFAULT_OUTPUT_FILE})."
        ),
    )
    parser.add_argument(
        "--sheet-name",
        default=ANNOTATION_SHEET_NAME,
        help=(
            "Annotation sheet name "
            f"(default: {ANNOTATION_SHEET_NAME})."
        ),
    )
    parser.add_argument(
        "--strict-batch",
        action="store_true",
        help=(
            "Fail when the observed annotator IDs are not exactly ANN_01 through ANN_09. "
            "Without this option, the workbook is still generated and the issue is reported."
        ),
    )
    return parser.parse_args()


def main() -> None:
    args = parse_arguments()
    input_dir = args.input_dir.expanduser().resolve()
    output_file = args.output_file.expanduser().resolve()

    workbook_paths = discover_workbooks(input_dir, output_file)
    all_judgments_raw, source_columns = load_all_judgments(
        workbook_paths,
        args.sheet_name,
    )
    all_judgments = add_judgment_quality_columns(all_judgments_raw)

    observed_ids = sorted(ordered_unique(all_judgments["annotator_id"]))
    missing_ids = sorted(set(EXPECTED_ANNOTATOR_IDS) - set(observed_ids))
    unexpected_ids = sorted(set(observed_ids) - set(EXPECTED_ANNOTATOR_IDS))

    if args.strict_batch and (missing_ids or unexpected_ids):
        details = []
        if missing_ids:
            details.append("missing IDs: " + ", ".join(missing_ids))
        if unexpected_ids:
            details.append("unexpected IDs: " + ", ".join(unexpected_ids))
        raise ValueError("Incomplete or invalid annotator batch: " + "; ".join(details))

    consolidated, data_quality_issues = consolidate_items(
        all_judgments,
        source_columns,
    )

    # Add batch-level issues to the audit sheet without exposing names or filenames.
    batch_issues: List[Dict[str, str]] = []
    if len(workbook_paths) != len(EXPECTED_ANNOTATOR_IDS):
        batch_issues.append(
            {
                "issue_scope": "batch",
                "item_id": "",
                "annotator_id": "",
                "review_round": "",
                "issue": (
                    f"expected {len(EXPECTED_ANNOTATOR_IDS)} workbooks; "
                    f"found {len(workbook_paths)}"
                ),
            }
        )
    if missing_ids:
        batch_issues.append(
            {
                "issue_scope": "batch",
                "item_id": "",
                "annotator_id": "",
                "review_round": "",
                "issue": "missing annotator IDs: " + ", ".join(missing_ids),
            }
        )
    if unexpected_ids:
        batch_issues.append(
            {
                "issue_scope": "batch",
                "item_id": "",
                "annotator_id": "",
                "review_round": "",
                "issue": "unexpected annotator IDs: " + ", ".join(unexpected_ids),
            }
        )
    if batch_issues:
        data_quality_issues = pd.concat(
            [data_quality_issues, pd.DataFrame(batch_issues)],
            ignore_index=True,
        ).drop_duplicates()

    adjudication_queue = build_adjudication_queue(consolidated)
    all_judgments_output = clean_all_judgments_for_output(
        all_judgments,
        source_columns,
    )
    metrics = build_metrics(
        all_judgments,
        consolidated,
        len(workbook_paths),
    )

    write_output_workbook(
        output_file=output_file,
        consolidated=consolidated,
        adjudication_queue=adjudication_queue,
        all_judgments_output=all_judgments_output,
        metrics=metrics,
        data_quality_issues=data_quality_issues,
    )

    print("=" * 88)
    print("Short-answer cross-validation consolidation completed.")
    print(f"Input folder                 : {input_dir}")
    print(f"Input workbooks              : {len(workbook_paths)}")
    print(f"Observed annotator IDs       : {', '.join(observed_ids)}")
    print(f"Unique items                 : {len(consolidated)}")
    print(f"Total judgments              : {len(all_judgments)}")
    print(
        "Items requiring adjudication: "
        f"{int((consolidated['requires_adjudication'] == 'yes').sum()) if not consolidated.empty else 0}"
    )
    print(f"Output workbook              : {output_file}")
    if missing_ids:
        print(f"WARNING - missing IDs        : {', '.join(missing_ids)}")
    if unexpected_ids:
        print(f"WARNING - unexpected IDs     : {', '.join(unexpected_ids)}")
    print("Privacy check                : only annotator IDs retained")
    print("=" * 88)


if __name__ == "__main__":
    main()
