from __future__ import annotations

import argparse
import math
import re
import unicodedata
from collections import Counter
from itertools import combinations
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

DEFAULT_INPUT_DIR = Path("cross_check_open_confidential") / "annotator_deliverables"
DEFAULT_OUTPUT_FILE = (
    Path("cross_check_open_confidential")
    / "open_question_cross_check_consolidation.xlsx"
)

# The deliverable workbooks are assumed to have a single relevant sheet.
# Pass --sheet-name if your files use a specific sheet name instead of the first sheet.
DEFAULT_SHEET_NAME: object = 0
DEFAULT_SHEET_NAME: str = "OPEN_ANNOTATION"

EXPECTED_ANNOTATOR_IDS = [f"ANN_{number:02d}" for number in range(1, 11)]

# Each quality dimension has one "clean" value. Anything else is treated as a
# reported issue. Edit this if your annotation guide uses different labels.
CLEAN_VALUES: Dict[str, str] = {
    "linguistic_quality": "no_issue",
    "answer_relevance": "no_issue",
    "answer_completeness": "no_issue",
    "factual_precision": "no_issue",
    "safety_alignment": "safe",
    "code_switching": "no_issue",
}
QUALITY_DIMENSIONS = list(CLEAN_VALUES.keys())

SOURCE_COLUMNS = [
    "Axe",
    "Difficulty",
    "intent_group",
    "intent_category",
    "input",
    "Answer_chatgpt_corrected",
    "item_id",
]

REQUIRED_COLUMNS = (
    SOURCE_COLUMNS
    + ["annotator_id"]
    + QUALITY_DIMENSIONS
    + ["review_comment", "supporting_source"]
)

ANNOTATION_COLUMNS = (
    ["annotator_id"] + QUALITY_DIMENSIONS + ["review_comment", "supporting_source"]
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

INTERNAL_COLUMN_PREFIX = "_"


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
    text = re.sub(r"[\u2019'`]+", "'", text)
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


def normalize_dimension_value(value: object) -> str:
    """Normalize a quality-dimension label for comparison (case/accents/spacing only)."""
    text = clean_text(value)
    if not text:
        return ""
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.lower().strip()
    text = re.sub(r"[\s\-/]+", "_", text)
    text = re.sub(r"_+", "_", text).strip("_")
    return text


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


def combine_annotated_text(rows: pd.DataFrame, column: str) -> str:
    """Combine text across raters while retaining only annotator IDs as provenance."""
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


def mode_label(labels: Sequence[str]) -> str:
    """Most frequent label; ties are reported explicitly rather than picked arbitrarily."""
    if not labels:
        return ""
    counts = Counter(labels)
    top_count = max(counts.values())
    winners = sorted(label for label, count in counts.items() if count == top_count)
    if len(winners) == 1:
        return winners[0]
    return "tied(" + "/".join(winners) + ")"


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
        raise FileNotFoundError(f"No .xlsx or .xlsm workbook found in: {input_dir}")
    return workbooks


def infer_annotator_id_from_filename(path: Path) -> str:
    match = re.search(r"ANN[_-]?(\d{1,2})", path.stem, flags=re.IGNORECASE)
    if match:
        return f"ANN_{int(match.group(1)):02d}"
    return ""


def read_one_workbook(
    workbook_path: Path,
    workbook_number: int,
    sheet_name: object,
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
            f"Workbook #{workbook_number} ({workbook_path.name}) does not contain "
            f"sheet '{sheet_name}'. Available sheets: {', '.join(available)}"
        ) from exc

    # Column headers may carry stray leading/trailing whitespace (observed on
    # 'code_switching' in real deliverables), so strip before anything else.
    df.columns = [str(column).strip() for column in df.columns]
    if len(set(df.columns)) != len(df.columns):
        raise ValueError(
            f"Workbook #{workbook_number} ({workbook_path.name}) has duplicate column names."
        )

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
            f"Workbook #{workbook_number} ({workbook_path.name}) is missing required "
            "columns: " + ", ".join(missing)
        )

    # Ignore fully blank rows.
    meaningful_columns = ["item_id", "annotator_id"] + QUALITY_DIMENSIONS
    meaningful_mask = df[meaningful_columns].apply(
        lambda column: column.map(has_value)
    ).any(axis=1)
    df = df.loc[meaningful_mask].copy()
    if df.empty:
        raise ValueError(
            f"Workbook #{workbook_number} ({workbook_path.name}) contains no completed rows."
        )

    df["_workbook_number"] = workbook_number
    df["_source_row_number"] = df.index + 2
    df["item_id"] = df["item_id"].map(normalize_item_id)
    df["_item_key"] = df["item_id"]
    df["annotator_id"] = df["annotator_id"].map(normalize_annotator_id)

    # Fall back to the filename when annotator_id is blank on some rows.
    filename_id = infer_annotator_id_from_filename(workbook_path)
    if filename_id:
        blank_mask = df["annotator_id"] == ""
        if blank_mask.any():
            df.loc[blank_mask, "annotator_id"] = filename_id

    for column in ["review_comment", "supporting_source"]:
        df[column] = df[column].map(clean_text)
    for dimension in QUALITY_DIMENSIONS:
        df[dimension] = df[dimension].map(clean_text)
        df[f"_{dimension}_norm"] = df[dimension].map(normalize_dimension_value)
        clean_norm = normalize_dimension_value(CLEAN_VALUES[dimension])
        df[f"_{dimension}_missing"] = df[f"_{dimension}_norm"] == ""
        df[f"_{dimension}_flag"] = (df[f"_{dimension}_norm"] != "") & (
            df[f"_{dimension}_norm"] != clean_norm
        )

    nonempty_ids = ordered_unique(df["annotator_id"])
    if len(nonempty_ids) != 1:
        raise ValueError(
            f"Workbook #{workbook_number} ({workbook_path.name}) must contain exactly "
            f"one annotator_id; found: {', '.join(nonempty_ids) if nonempty_ids else 'none'}"
            + (f" (filename suggests {filename_id})" if filename_id else "")
        )

    workbook_annotator_id = nonempty_ids[0]
    if workbook_annotator_id not in EXPECTED_ANNOTATOR_IDS:
        raise ValueError(
            f"Workbook #{workbook_number} ({workbook_path.name}) contains an unexpected "
            f"annotator_id: {workbook_annotator_id}"
        )
    if filename_id and workbook_annotator_id != filename_id:
        raise ValueError(
            f"Workbook #{workbook_number} ({workbook_path.name}): annotator_id column "
            f"says {workbook_annotator_id} but the filename suggests {filename_id}."
        )

    return df.reset_index(drop=True)


def load_all_judgments(
    workbook_paths: Sequence[Path],
    sheet_name: object,
) -> Tuple[pd.DataFrame, List[str]]:
    frames: List[pd.DataFrame] = []
    source_columns_order: List[str] = []

    for workbook_number, workbook_path in enumerate(workbook_paths, start=1):
        df = read_one_workbook(workbook_path, workbook_number, sheet_name)
        frames.append(df)

        for column in df.columns:
            if (
                column not in ANNOTATION_COLUMNS
                and not column.startswith(INTERNAL_COLUMN_PREFIX)
                and not is_private_identity_column(column)
                and column not in source_columns_order
            ):
                source_columns_order.append(column)

    all_judgments = pd.concat(frames, ignore_index=True, sort=False)

    preferred_present = [
        column for column in SOURCE_COLUMNS if column in source_columns_order
    ]
    other_source_columns = [
        column
        for column in source_columns_order
        if column not in preferred_present and column != "item_id"
    ]
    source_columns = preferred_present + other_source_columns

    return all_judgments, source_columns


# =============================================================================
# JUDGMENT (ROW-LEVEL) VALIDATION
# =============================================================================


def validate_judgment_row(row: pd.Series) -> Tuple[str, bool]:
    issues: List[str] = []

    if not clean_text(row.get("item_id")):
        issues.append("missing item_id")

    annotator_id = clean_text(row.get("annotator_id"))
    if not annotator_id:
        issues.append("missing annotator_id")
    elif annotator_id not in EXPECTED_ANNOTATOR_IDS:
        issues.append("unexpected annotator_id")

    flagged_dimensions: List[str] = []
    for dimension in QUALITY_DIMENSIONS:
        if bool(row.get(f"_{dimension}_missing")):
            issues.append(f"missing {dimension}")
        elif bool(row.get(f"_{dimension}_flag")):
            flagged_dimensions.append(dimension)

    review_comment = clean_text(row.get("review_comment"))
    if flagged_dimensions and not review_comment:
        issues.append(
            "missing review_comment for flagged dimension(s): "
            + ", ".join(flagged_dimensions)
        )

    return join_issues(issues), not issues


def add_judgment_quality_columns(all_judgments: pd.DataFrame) -> pd.DataFrame:
    df = all_judgments.copy()
    validation = df.apply(validate_judgment_row, axis=1, result_type="expand")
    validation.columns = ["_judgment_issue", "_judgment_complete"]
    df = pd.concat([df, validation], axis=1)
    df["judgment_complete"] = df["_judgment_complete"].map(yes_no)
    df["judgment_issue"] = df["_judgment_issue"]

    df["_any_flag"] = df[[f"_{d}_flag" for d in QUALITY_DIMENSIONS]].any(axis=1)
    df["any_dimension_flagged"] = df["_any_flag"].map(yes_no)

    factual_flag_no_source = df["_factual_precision_flag"] & ~df["supporting_source"].map(
        has_value
    )
    df["_supporting_source_recommended_missing"] = factual_flag_no_source
    return df


# =============================================================================
# CONSOLIDATION AND DECISION RULES (PER item_id, VARIABLE NUMBER OF RATERS)
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
        values = (
            [value for value in rows[column].tolist() if has_value(value)]
            if column in rows
            else []
        )
        canonical[column] = values[0] if values else ""
        normalized = ordered_unique(normalize_text(value) for value in values)
        if len(normalized) > 1:
            conflicts.append(column)

    return canonical, conflicts


def summarize_dimension(rows: pd.DataFrame, dimension: str) -> Dict[str, object]:
    clean_norm = normalize_dimension_value(CLEAN_VALUES[dimension])
    norms = [
        row[f"_{dimension}_norm"]
        for _, row in rows.iterrows()
        if row[f"_{dimension}_norm"] != ""
    ]
    display_pairs = [
        f"{row['annotator_id']}:{clean_text(row[dimension]) or '(missing)'}"
        for _, row in rows.iterrows()
    ]
    n_missing = int(rows[f"_{dimension}_missing"].sum())
    n_flagged = sum(1 for value in norms if value != clean_norm)

    if not norms:
        status = "missing"
    elif len(set(norms)) == 1:
        status = "unanimous_issue" if norms[0] != clean_norm else "unanimous_clean"
    else:
        status = "disagreement"

    return {
        "status": status,
        "n_missing": n_missing,
        "n_flagged": n_flagged,
        "majority_label": mode_label(norms),
        "labels_display": " | ".join(display_pairs),
    }


def determine_provisional_decision(
    rater_count: int,
    dimension_summaries: Mapping[str, Dict[str, object]],
    item_issues: Sequence[str],
) -> Tuple[str, str, str, str]:
    """
    Return: provisional_decision, requires_adjudication, decision_reason, recommended_action
    """
    if item_issues:
        return (
            "incomplete_or_invalid_item",
            "yes",
            join_issues(item_issues),
            "Resolve assignment, missing ratings, or source conflicts before adjudicating.",
        )

    disagreement_dims = [
        dim for dim, summary in dimension_summaries.items() if summary["status"] == "disagreement"
    ]
    if disagreement_dims:
        return (
            "adjudicate_dimension_disagreement",
            "yes",
            "raters disagree on: " + ", ".join(disagreement_dims),
            "A third reviewer decides the correct rating for the disputed dimension(s).",
        )

    missing_dims = [
        dim for dim, summary in dimension_summaries.items() if summary["status"] == "missing"
    ]
    if missing_dims:
        return (
            "incomplete_or_invalid_item",
            "yes",
            "no usable rating for: " + ", ".join(missing_dims),
            "Recover the missing rating(s) and then adjudicate.",
        )

    issue_dims = [
        dim
        for dim, summary in dimension_summaries.items()
        if summary["status"] == "unanimous_issue"
    ]

    if rater_count == 1:
        if issue_dims:
            return (
                "single_reviewer_flagged_issue",
                "yes",
                "the only reviewer reported an issue on: " + ", ".join(issue_dims),
                "Assign a second reviewer to confirm before applying any correction.",
            )
        return (
            "accept_single_review",
            "no",
            "the only reviewer reported no issue on any dimension",
            "Keep the item as-is; note that it was not cross-checked.",
        )

    if issue_dims:
        return (
            "confirmed_issue_apply_correction",
            "yes",
            "all raters agree there is an issue on: " + ", ".join(issue_dims),
            "Apply the correction described in the review comments for the flagged dimension(s).",
        )

    return (
        "accept",
        "no",
        "all raters agree every dimension is clean",
        "Keep the item unchanged.",
    )


def consolidate_items(
    all_judgments: pd.DataFrame,
    source_columns: Sequence[str],
) -> Tuple[pd.DataFrame, pd.DataFrame]:
    item_rows: List[Dict[str, object]] = []
    issue_rows: List[Dict[str, object]] = []

    missing_id_rows = all_judgments[all_judgments["_item_key"] == ""]
    for _, row in missing_id_rows.iterrows():
        issue_rows.append(
            {
                "issue_scope": "judgment",
                "item_id": "",
                "annotator_id": clean_text(row.get("annotator_id")),
                "issue": clean_text(row.get("_judgment_issue")) or "missing item_id",
            }
        )

    usable = all_judgments[all_judgments["_item_key"] != ""].copy()

    for item_id, rows in usable.groupby("_item_key", sort=True, dropna=False):
        rows = rows.copy().reset_index(drop=True)
        source_values, source_conflicts = canonical_source_values(rows, source_columns)

        rater_count = len(rows)
        unique_annotators = rows["annotator_id"].nunique()

        item_issues: List[str] = []
        if unique_annotators != rater_count:
            duplicated = (
                rows["annotator_id"]
                .value_counts()
                .loc[lambda s: s > 1]
                .index.tolist()
            )
            item_issues.append(
                "duplicate judgment(s) from the same annotator_id: " + ", ".join(duplicated)
            )
        if source_conflicts:
            item_issues.append("source-column conflicts: " + ", ".join(source_conflicts))

        incomplete_rows = rows[~rows["_judgment_complete"]]
        if not incomplete_rows.empty:
            details = ordered_unique(incomplete_rows["_judgment_issue"])
            item_issues.append("incomplete/invalid judgment: " + "; ".join(details))

        dimension_summaries = {
            dimension: summarize_dimension(rows, dimension) for dimension in QUALITY_DIMENSIONS
        }

        provisional_decision, requires_adjudication, reason, action = (
            determine_provisional_decision(rater_count, dimension_summaries, item_issues)
        )

        result: Dict[str, object] = dict(source_values)
        result.update(
            {
                "rater_count": rater_count,
                "unique_annotator_count": unique_annotators,
                "cross_checked": yes_no(unique_annotators >= 2),
                "annotator_ids": " | ".join(ordered_unique(rows["annotator_id"])),
                "all_review_comments": combine_annotated_text(rows, "review_comment"),
                "all_supporting_sources": combine_annotated_text(rows, "supporting_source"),
                "source_conflict_columns": ", ".join(source_conflicts),
                "provisional_decision": provisional_decision,
                "requires_adjudication": requires_adjudication,
                "decision_reason": reason,
                "recommended_action": action,
            }
        )
        for dimension in QUALITY_DIMENSIONS:
            summary = dimension_summaries[dimension]
            result[f"{dimension}_status"] = summary["status"]
            result[f"{dimension}_n_flagged"] = summary["n_flagged"]
            result[f"{dimension}_labels"] = summary["labels_display"]
        item_rows.append(result)

        for issue in item_issues:
            issue_rows.append(
                {
                    "issue_scope": "item",
                    "item_id": item_id,
                    "annotator_id": "",
                    "issue": issue,
                }
            )
        for _, judgment in rows[rows["_judgment_issue"] != ""].iterrows():
            issue_rows.append(
                {
                    "issue_scope": "judgment",
                    "item_id": item_id,
                    "annotator_id": judgment["annotator_id"],
                    "issue": judgment["_judgment_issue"],
                }
            )
        for _, judgment in rows[rows["_supporting_source_recommended_missing"]].iterrows():
            issue_rows.append(
                {
                    "issue_scope": "note",
                    "item_id": item_id,
                    "annotator_id": judgment["annotator_id"],
                    "issue": "factual_precision flagged without a supporting_source",
                }
            )

    consolidated = pd.DataFrame(item_rows)
    if not consolidated.empty:
        source_first = [column for column in source_columns if column in consolidated.columns]
        dimension_columns: List[str] = []
        for dimension in QUALITY_DIMENSIONS:
            dimension_columns += [
                f"{dimension}_status",
                f"{dimension}_n_flagged",
                f"{dimension}_labels",
            ]
        decision_columns = [
            "rater_count",
            "unique_annotator_count",
            "cross_checked",
            "annotator_ids",
        ] + dimension_columns + [
            "source_conflict_columns",
            "all_review_comments",
            "all_supporting_sources",
            "provisional_decision",
            "requires_adjudication",
            "decision_reason",
            "recommended_action",
        ]
        consolidated = consolidated[source_first + decision_columns]
        consolidated = consolidated.sort_values("item_id").reset_index(drop=True)

    data_quality_issues = pd.DataFrame(
        issue_rows,
        columns=["issue_scope", "item_id", "annotator_id", "issue"],
    ).drop_duplicates()

    return consolidated, data_quality_issues


def build_adjudication_queue(consolidated: pd.DataFrame) -> pd.DataFrame:
    if consolidated.empty:
        return pd.DataFrame()

    queue = consolidated[consolidated["requires_adjudication"] == "yes"].copy()
    queue["adjudicator_id"] = ""
    for dimension in QUALITY_DIMENSIONS:
        queue[f"adjudicated_{dimension}"] = ""
    queue["adjudicated_answer_chatgpt_corrected"] = ""
    queue["adjudication_comment"] = ""
    queue["final_decision"] = ""
    queue["adjudication_status"] = "pending"
    return queue.reset_index(drop=True)


def build_safety_flags(all_judgments: pd.DataFrame, source_columns: Sequence[str]) -> pd.DataFrame:
    flagged = all_judgments[all_judgments["_safety_alignment_flag"]].copy()
    if flagged.empty:
        return pd.DataFrame(
            columns=source_columns + ["annotator_id", "safety_alignment", "review_comment"]
        )
    keep = [c for c in source_columns if c in flagged.columns] + [
        "annotator_id",
        "safety_alignment",
        "review_comment",
        "supporting_source",
    ]
    result = flagged[keep].copy()
    return result.sort_values(["item_id", "annotator_id"]).reset_index(drop=True)


# =============================================================================
# AGREEMENT AND SUMMARY METRICS
# =============================================================================


def safe_percentage(numerator: float, denominator: float) -> float:
    return round(numerator / denominator * 100, 2) if denominator else math.nan


def pairwise_concordant_and_total(category_counts: Sequence[int]) -> Tuple[int, int]:
    n = sum(category_counts)
    total = n * (n - 1) // 2
    concordant = sum(count * (count - 1) // 2 for count in category_counts)
    return concordant, total


def fleiss_kappa_variable_n(item_category_counts: Sequence[Mapping[str, int]]) -> float:
    """
    Generalized Fleiss' kappa for a variable number of raters per subject.
    Reduces to the classic formula when every subject has the same rater count.
    Only subjects with 2+ raters should be passed in.
    """
    items = [dict(counts) for counts in item_category_counts if sum(counts.values()) >= 2]
    if not items:
        return math.nan

    categories = sorted({category for counts in items for category in counts})
    n_i = np.array([sum(counts.values()) for counts in items], dtype=float)
    count_matrix = np.array(
        [[counts.get(category, 0) for category in categories] for counts in items],
        dtype=float,
    )

    p_i = (
        (count_matrix**2).sum(axis=1) - n_i
    ) / (n_i * (n_i - 1))
    p_bar = float(p_i.mean())

    p_j = count_matrix.sum(axis=0) / n_i.sum()
    p_e = float((p_j**2).sum())

    if p_e == 1.0:
        return 1.0 if p_bar == 1.0 else math.nan
    return (p_bar - p_e) / (1 - p_e)


def build_agreement_table(consolidated: pd.DataFrame, all_judgments: pd.DataFrame) -> pd.DataFrame:
    rows: List[Dict[str, object]] = []
    if consolidated.empty:
        return pd.DataFrame(
            columns=[
                "dimension",
                "items_total",
                "items_cross_checked",
                "items_unanimous_clean",
                "items_unanimous_issue",
                "items_disagreement",
                "items_missing",
                "mean_pairwise_agreement_exact_percent",
                "mean_pairwise_agreement_clean_vs_issue_percent",
                "full_unanimity_percent",
                "fleiss_kappa_clean_vs_issue_variable_n",
            ]
        )

    for dimension in QUALITY_DIMENSIONS:
        clean_norm = normalize_dimension_value(CLEAN_VALUES[dimension])
        status_col = f"{dimension}_status"
        multi = consolidated[consolidated["unique_annotator_count"] >= 2]

        exact_pairwise_pcts: List[float] = []
        binary_pairwise_pcts: List[float] = []
        binary_item_counts: List[Dict[str, int]] = []

        for item_id, item_rows in all_judgments[all_judgments["_item_key"] != ""].groupby(
            "_item_key"
        ):
            # One judgment per annotator: a duplicate submission from the same
            # annotator is not an independent second opinion and would inflate
            # agreement artificially.
            item_rows = item_rows.drop_duplicates(subset="annotator_id")
            norms = [
                v for v in item_rows[f"_{dimension}_norm"].tolist() if v != ""
            ]
            if len(norms) < 2:
                continue
            exact_counts = list(Counter(norms).values())
            concordant, total = pairwise_concordant_and_total(exact_counts)
            if total:
                exact_pairwise_pcts.append(concordant / total * 100)

            n_flagged = sum(1 for v in norms if v != clean_norm)
            n_clean = len(norms) - n_flagged
            b_concordant, b_total = pairwise_concordant_and_total([n_clean, n_flagged])
            if b_total:
                binary_pairwise_pcts.append(b_concordant / b_total * 100)
            binary_item_counts.append({"clean": n_clean, "issue": n_flagged})

        kappa = fleiss_kappa_variable_n(binary_item_counts)

        # Status counts (unanimous/disagreement/missing) are only meaningful
        # for items that were actually cross-checked by 2+ raters.
        status_counts = multi[status_col].value_counts()
        rows.append(
            {
                "dimension": dimension,
                "items_total": int(len(consolidated)),
                "items_cross_checked": int(len(multi)),
                "items_unanimous_clean": int(status_counts.get("unanimous_clean", 0)),
                "items_unanimous_issue": int(status_counts.get("unanimous_issue", 0)),
                "items_disagreement": int(status_counts.get("disagreement", 0)),
                "items_missing": int(status_counts.get("missing", 0)),
                "mean_pairwise_agreement_exact_percent": round(
                    float(np.mean(exact_pairwise_pcts)), 2
                )
                if exact_pairwise_pcts
                else math.nan,
                "mean_pairwise_agreement_clean_vs_issue_percent": round(
                    float(np.mean(binary_pairwise_pcts)), 2
                )
                if binary_pairwise_pcts
                else math.nan,
                "full_unanimity_percent": safe_percentage(
                    status_counts.get("unanimous_clean", 0)
                    + status_counts.get("unanimous_issue", 0),
                    len(multi),
                ),
                "fleiss_kappa_clean_vs_issue_variable_n": round(kappa, 4)
                if not math.isnan(kappa)
                else math.nan,
            }
        )

    return pd.DataFrame(rows)


def build_by_annotator(all_judgments: pd.DataFrame) -> pd.DataFrame:
    df = all_judgments.assign(
        is_complete=all_judgments["_judgment_complete"].astype(int),
        has_source=all_judgments["supporting_source"].map(has_value).astype(int),
        flagged_dimension_count=all_judgments[[f"_{d}_flag" for d in QUALITY_DIMENSIONS]].sum(
            axis=1
        ),
    )
    by_annotator = df.groupby("annotator_id", as_index=False).agg(
        total_judgments=("item_id", "size"),
        complete_judgments=("is_complete", "sum"),
        judgments_with_source=("has_source", "sum"),
        flagged_dimension_instances=("flagged_dimension_count", "sum"),
    )
    if not by_annotator.empty:
        by_annotator["completion_rate_percent"] = (
            by_annotator["complete_judgments"] / by_annotator["total_judgments"] * 100
        ).round(2)
        by_annotator["source_completion_rate_percent"] = (
            by_annotator["judgments_with_source"] / by_annotator["total_judgments"] * 100
        ).round(2)
        by_annotator["flag_rate_percent"] = (
            by_annotator["flagged_dimension_instances"]
            / (by_annotator["total_judgments"] * len(QUALITY_DIMENSIONS))
            * 100
        ).round(2)
    return by_annotator


def build_group_summary(consolidated: pd.DataFrame, column: str) -> pd.DataFrame:
    if consolidated.empty or column not in consolidated.columns:
        return pd.DataFrame()
    unsafe_mask = consolidated["safety_alignment_n_flagged"] > 0
    result = (
        consolidated.assign(
            is_cross_checked=(consolidated["unique_annotator_count"] >= 2).astype(int),
            needs_adjudication=(consolidated["requires_adjudication"] == "yes").astype(int),
            has_unsafe_flag=unsafe_mask.astype(int),
        )
        .groupby(column, dropna=False, as_index=False)
        .agg(
            total_items=("item_id", "size"),
            cross_checked_items=("is_cross_checked", "sum"),
            items_requiring_adjudication=("needs_adjudication", "sum"),
            items_with_unsafe_flag=("has_unsafe_flag", "sum"),
        )
    )
    result["adjudication_rate_percent"] = (
        result["items_requiring_adjudication"] / result["total_items"] * 100
    ).round(2)
    return result


def build_metrics(
    all_judgments: pd.DataFrame,
    consolidated: pd.DataFrame,
    workbook_count: int,
) -> Dict[str, pd.DataFrame]:
    observed_ids = sorted(ordered_unique(all_judgments["annotator_id"]))
    missing_ids = sorted(set(EXPECTED_ANNOTATOR_IDS) - set(observed_ids))
    unexpected_ids = sorted(set(observed_ids) - set(EXPECTED_ANNOTATOR_IDS))

    total_items = len(consolidated)
    adjudication_items = (
        int((consolidated["requires_adjudication"] == "yes").sum()) if total_items else 0
    )
    cross_checked_items = (
        int((consolidated["unique_annotator_count"] >= 2).sum()) if total_items else 0
    )
    single_review_items = total_items - cross_checked_items
    unsafe_items = (
        int((consolidated["safety_alignment_n_flagged"] > 0).sum()) if total_items else 0
    )
    complete_judgments = int(all_judgments["_judgment_complete"].sum())

    overview = pd.DataFrame(
        [
            ("input_workbooks", workbook_count),
            ("expected_annotators", len(EXPECTED_ANNOTATOR_IDS)),
            ("observed_annotator_ids", ", ".join(observed_ids)),
            ("missing_annotator_ids", ", ".join(missing_ids)),
            ("unexpected_annotator_ids", ", ".join(unexpected_ids)),
            ("batch_complete", "yes" if not missing_ids and not unexpected_ids else "no"),
            ("unique_items", total_items),
            ("total_judgments", len(all_judgments)),
            ("items_cross_checked_2plus_raters", cross_checked_items),
            ("items_single_review_only", single_review_items),
            ("complete_judgments", complete_judgments),
            (
                "judgment_completion_rate_percent",
                safe_percentage(complete_judgments, len(all_judgments)),
            ),
            ("items_requiring_adjudication", adjudication_items),
            ("adjudication_rate_percent", safe_percentage(adjudication_items, total_items)),
            ("items_with_at_least_one_unsafe_flag", unsafe_items),
            ("unsafe_flag_rate_percent", safe_percentage(unsafe_items, total_items)),
        ],
        columns=["metric", "value"],
    )

    agreement = build_agreement_table(consolidated, all_judgments)
    by_annotator = build_by_annotator(all_judgments)

    decision_counts = (
        consolidated["provisional_decision"]
        .value_counts(dropna=False)
        .rename_axis("provisional_decision")
        .reset_index(name="item_count")
        if total_items
        else pd.DataFrame(columns=["provisional_decision", "item_count"])
    )
    if not decision_counts.empty:
        decision_counts["percentage"] = (
            decision_counts["item_count"] / total_items * 100
        ).round(2)

    return {
        "METRICS_OVERVIEW": overview,
        "AGREEMENT_BY_DIMENSION": agreement,
        "BY_ANNOTATOR": by_annotator,
        "BY_AXIS": build_group_summary(consolidated, "Axe"),
        "BY_DIFFICULTY": build_group_summary(consolidated, "Difficulty"),
        "DECISION_COUNTS": decision_counts,
    }


# =============================================================================
# OUTPUT PREPARATION AND EXCEL FORMATTING
# =============================================================================


HEADER_FILL = PatternFill("solid", fgColor="1F4E78")
HEADER_FONT = Font(color="FFFFFF", bold=True)
GOOD_FILL = PatternFill("solid", fgColor="E2F0D9")
WARNING_FILL = PatternFill("solid", fgColor="FFF2CC")
BAD_FILL = PatternFill("solid", fgColor="F4CCCC")
GRAY_FILL = PatternFill("solid", fgColor="F2F2F2")
THIN_GRAY = Side(style="thin", color="B7B7B7")
TABLE_BORDER = Border(left=THIN_GRAY, right=THIN_GRAY, top=THIN_GRAY, bottom=THIN_GRAY)


def clean_all_judgments_for_output(
    all_judgments: pd.DataFrame,
    source_columns: Sequence[str],
) -> pd.DataFrame:
    output_columns = [
        column
        for column in source_columns
        if column in all_judgments.columns and not is_private_identity_column(column)
    ] + ["annotator_id"] + QUALITY_DIMENSIONS + [
        "review_comment",
        "supporting_source",
        "any_dimension_flagged",
        "judgment_complete",
        "judgment_issue",
    ]
    result = all_judgments[output_columns].copy()
    sort_columns = [c for c in ["item_id", "annotator_id"] if c in result.columns]
    if sort_columns:
        result = result.sort_values(sort_columns).reset_index(drop=True)
    return result


def build_readme_dataframe() -> pd.DataFrame:
    rows = [
        ("Purpose", "Merge the ten open-question cross-check workbooks, remove personal names, compute per-item provisional decisions across six quality dimensions, prepare adjudication, and calculate inter-annotator reliability."),
        ("Privacy", "Only annotator_id is retained. Personal-name columns and input filenames are never written to the consolidation workbook."),
        ("Expected IDs", ", ".join(EXPECTED_ANNOTATOR_IDS)),
        ("Rater count per item", "Not assumed fixed. Each item_id is grouped across however many annotator deliverables actually reference it; items reviewed by only one annotator are accepted as-is unless that annotator flagged an issue."),
        ("Quality dimensions", ", ".join(QUALITY_DIMENSIONS)),
        ("Clean value per dimension", ", ".join(f"{k}={v}" for k, v in CLEAN_VALUES.items())),
        ("accept", "All raters (2+) agree every dimension is clean."),
        ("accept_single_review", "The item had only one reviewer, who reported no issue."),
        ("confirmed_issue_apply_correction", "All raters (2+) agree on the same flagged dimension(s); apply the correction described in the review comments."),
        ("single_reviewer_flagged_issue", "The item had only one reviewer, who flagged an issue. Needs a second opinion before correcting."),
        ("adjudicate_dimension_disagreement", "Raters disagree on at least one dimension's rating; a third reviewer must decide."),
        ("incomplete_or_invalid_item", "Missing ratings, duplicate judgments from the same annotator, or source-data conflicts across deliverables."),
        ("Agreement metrics", "Computed only on items reviewed by 2+ annotators. Includes mean pairwise agreement (exact label and clean-vs-issue), full-unanimity rate, and a Fleiss' kappa variant generalized for a variable number of raters per item."),
        ("SAFETY_FLAGS sheet", "Every individual judgment where safety_alignment was rated anything other than 'safe', regardless of adjudication status, for quick review."),
        ("Adjudication queue", "Fill in the blank adjudication columns; no annotator names are required."),
    ]
    return pd.DataFrame(rows, columns=["section", "description"])


def write_output_workbook(
    output_file: Path,
    consolidated: pd.DataFrame,
    adjudication_queue: pd.DataFrame,
    safety_flags: pd.DataFrame,
    all_judgments_output: pd.DataFrame,
    metrics: Mapping[str, pd.DataFrame],
    data_quality_issues: pd.DataFrame,
) -> None:
    output_file.parent.mkdir(parents=True, exist_ok=True)

    with pd.ExcelWriter(output_file, engine="openpyxl") as writer:
        build_readme_dataframe().to_excel(writer, index=False, sheet_name="README")
        consolidated.to_excel(writer, index=False, sheet_name="CONSOLIDATED_ITEMS")
        adjudication_queue.to_excel(writer, index=False, sheet_name="ADJUDICATION_QUEUE")
        safety_flags.to_excel(writer, index=False, sheet_name="SAFETY_FLAGS")
        all_judgments_output.to_excel(writer, index=False, sheet_name="ALL_JUDGMENTS")
        for sheet_name, dataframe in metrics.items():
            dataframe.to_excel(writer, index=False, sheet_name=sheet_name)
        data_quality_issues.to_excel(writer, index=False, sheet_name="DATA_QUALITY_ISSUES")

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
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        cell.border = TABLE_BORDER

    text_heavy_markers = (
        "input",
        "answer",
        "comment",
        "source",
        "reason",
        "action",
        "description",
        "issue",
        "labels",
    )

    for row in ws.iter_rows(min_row=2):
        for cell in row:
            cell.alignment = Alignment(vertical="top", wrap_text=True)
            cell.border = TABLE_BORDER

    for column_index, cells in enumerate(ws.columns, start=1):
        header = clean_text(ws.cell(1, column_index).value).lower()
        if any(marker in header for marker in text_heavy_markers):
            width = 52
        elif header in {"provisional_decision", "requires_adjudication"}:
            width = 27
        else:
            max_length = max(
                (len(str(cell.value)) for cell in cells if cell.value is not None),
                default=10,
            )
            width = min(max(max_length + 2, 12), 26)
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
        for value in ["accept", "accept_single_review"]:
            ws.conditional_formatting.add(
                f"{letter}2:{letter}{last_row}",
                FormulaRule(formula=[f'{letter}2="{value}"'], fill=GOOD_FILL),
            )
        for value in ["confirmed_issue_apply_correction", "single_reviewer_flagged_issue"]:
            ws.conditional_formatting.add(
                f"{letter}2:{letter}{last_row}",
                FormulaRule(formula=[f'{letter}2="{value}"'], fill=WARNING_FILL),
            )
        for value in ["adjudicate_dimension_disagreement", "incomplete_or_invalid_item"]:
            ws.conditional_formatting.add(
                f"{letter}2:{letter}{last_row}",
                FormulaRule(formula=[f'{letter}2="{value}"'], fill=BAD_FILL),
            )

    for dimension in QUALITY_DIMENSIONS:
        status_header = f"{dimension}_status"
        if status_header in header_to_col:
            letter = get_column_letter(header_to_col[status_header])
            ws.conditional_formatting.add(
                f"{letter}2:{letter}{last_row}",
                FormulaRule(formula=[f'{letter}2="unanimous_clean"'], fill=GOOD_FILL),
            )
            ws.conditional_formatting.add(
                f"{letter}2:{letter}{last_row}",
                FormulaRule(
                    formula=[f'{letter}2="unanimous_issue"'], fill=WARNING_FILL
                ),
            )
            ws.conditional_formatting.add(
                f"{letter}2:{letter}{last_row}",
                FormulaRule(formula=[f'{letter}2="disagreement"'], fill=BAD_FILL),
            )
            ws.conditional_formatting.add(
                f"{letter}2:{letter}{last_row}",
                FormulaRule(formula=[f'{letter}2="missing"'], fill=BAD_FILL),
            )


def add_adjudication_validations(ws) -> None:
    if ws.max_row < 2:
        return
    header_to_col = {cell.value: cell.column for cell in ws[1]}
    last_row = ws.max_row

    validation_specs: Dict[str, List[str]] = {
        "final_decision": [
            "accept",
            "accept_with_correction",
            "reject_item",
            "needs_more_review",
        ],
        "adjudication_status": ["pending", "in_progress", "completed"],
    }
    for dimension in QUALITY_DIMENSIONS:
        validation_specs[f"adjudicated_{dimension}"] = [
            CLEAN_VALUES[dimension],
            "confirmed_issue",
        ]

    for column, values in validation_specs.items():
        if column not in header_to_col:
            continue
        column_letter = get_column_letter(header_to_col[column])
        validation = DataValidation(
            type="list",
            formula1='"' + ",".join(values) + '"',
            allow_blank=True,
        )
        validation.error = "Choose a value from the list, or type a more specific label."
        validation.errorTitle = "Suggested values"
        validation.showErrorMessage = False
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
        ws.column_dimensions["A"].width = 32
        ws.column_dimensions["B"].width = 115

    if "CONSOLIDATED_ITEMS" in wb.sheetnames:
        add_consolidated_conditional_formatting(wb["CONSOLIDATED_ITEMS"])

    if "ADJUDICATION_QUEUE" in wb.sheetnames:
        add_consolidated_conditional_formatting(wb["ADJUDICATION_QUEUE"])
        add_adjudication_validations(wb["ADJUDICATION_QUEUE"])

    if "SAFETY_FLAGS" in wb.sheetnames and wb["SAFETY_FLAGS"].max_row > 1:
        ws = wb["SAFETY_FLAGS"]
        for row in ws.iter_rows(min_row=2):
            for cell in row:
                cell.fill = BAD_FILL

    if "DATA_QUALITY_ISSUES" in wb.sheetnames and wb["DATA_QUALITY_ISSUES"].max_row > 1:
        ws = wb["DATA_QUALITY_ISSUES"]
        for row in ws.iter_rows(min_row=2):
            for cell in row:
                cell.fill = GRAY_FILL

    # Explicit workbook-level privacy check: no personal identity column survives.
    for ws in wb.worksheets:
        headers = [cell.value for cell in ws[1]] if ws.max_row >= 1 else []
        forbidden = [header for header in headers if is_private_identity_column(header)]
        if forbidden:
            raise RuntimeError(
                f"Privacy check failed in sheet '{ws.title}': " + ", ".join(str(v) for v in forbidden)
            )

    wb.save(output_file)


# =============================================================================
# MAIN
# =============================================================================


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Merge and consolidate open-question cross-check workbooks. "
            "Only annotator IDs are retained; personal names and filenames are excluded."
        )
    )
    parser.add_argument(
        "--input-dir",
        type=Path,
        default=DEFAULT_INPUT_DIR,
        help=f"Folder containing ANN_01.xlsx .. ANN_10.xlsx (default: {DEFAULT_INPUT_DIR}).",
    )
    parser.add_argument(
        "--output-file",
        type=Path,
        default=DEFAULT_OUTPUT_FILE,
        help=f"Consolidated Excel output (default: {DEFAULT_OUTPUT_FILE}).",
    )
    parser.add_argument(
        "--sheet-name",
        default=DEFAULT_SHEET_NAME,
        help="Sheet name to read from each deliverable (default: first sheet).",
    )
    parser.add_argument(
        "--strict-batch",
        action="store_true",
        help=(
            "Fail when the observed annotator IDs are not exactly ANN_01 through ANN_10. "
            "Without this option, the workbook is still generated and the issue is reported."
        ),
    )
    return parser.parse_args()


def main() -> None:
    args = parse_arguments()
    input_dir = args.input_dir.expanduser().resolve()
    output_file = args.output_file.expanduser().resolve()
    sheet_name = args.sheet_name

    workbook_paths = discover_workbooks(input_dir, output_file)
    all_judgments_raw, source_columns = load_all_judgments(workbook_paths, sheet_name)
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

    consolidated, data_quality_issues = consolidate_items(all_judgments, source_columns)

    batch_issues: List[Dict[str, str]] = []
    if len(workbook_paths) != len(EXPECTED_ANNOTATOR_IDS):
        batch_issues.append(
            {
                "issue_scope": "batch",
                "item_id": "",
                "annotator_id": "",
                "issue": (
                    f"expected {len(EXPECTED_ANNOTATOR_IDS)} workbooks; found {len(workbook_paths)}"
                ),
            }
        )
    if missing_ids:
        batch_issues.append(
            {
                "issue_scope": "batch",
                "item_id": "",
                "annotator_id": "",
                "issue": "missing annotator IDs: " + ", ".join(missing_ids),
            }
        )
    if unexpected_ids:
        batch_issues.append(
            {
                "issue_scope": "batch",
                "item_id": "",
                "annotator_id": "",
                "issue": "unexpected annotator IDs: " + ", ".join(unexpected_ids),
            }
        )
    if batch_issues:
        data_quality_issues = pd.concat(
            [data_quality_issues, pd.DataFrame(batch_issues)], ignore_index=True
        ).drop_duplicates()

    adjudication_queue = build_adjudication_queue(consolidated)
    safety_flags = build_safety_flags(all_judgments, source_columns)
    all_judgments_output = clean_all_judgments_for_output(all_judgments, source_columns)
    metrics = build_metrics(all_judgments, consolidated, len(workbook_paths))

    write_output_workbook(
        output_file=output_file,
        consolidated=consolidated,
        adjudication_queue=adjudication_queue,
        safety_flags=safety_flags,
        all_judgments_output=all_judgments_output,
        metrics=metrics,
        data_quality_issues=data_quality_issues,
    )

    print("=" * 88)
    print("Open-question cross-check consolidation completed.")
    print(f"Input folder                 : {input_dir}")
    print(f"Input workbooks               : {len(workbook_paths)}")
    print(f"Observed annotator IDs        : {', '.join(observed_ids)}")
    print(f"Unique items                  : {len(consolidated)}")
    print(f"Total judgments               : {len(all_judgments)}")
    print(
        "Items cross-checked (2+ raters): "
        f"{int((consolidated['unique_annotator_count'] >= 2).sum()) if not consolidated.empty else 0}"
    )
    print(
        "Items requiring adjudication  : "
        f"{int((consolidated['requires_adjudication'] == 'yes').sum()) if not consolidated.empty else 0}"
    )
    print(f"Output workbook               : {output_file}")
    if missing_ids:
        print(f"WARNING - missing IDs         : {', '.join(missing_ids)}")
    if unexpected_ids:
        print(f"WARNING - unexpected IDs      : {', '.join(unexpected_ids)}")
    print("Privacy check                 : only annotator IDs retained")
    print("=" * 88)


if __name__ == "__main__":
    main()
