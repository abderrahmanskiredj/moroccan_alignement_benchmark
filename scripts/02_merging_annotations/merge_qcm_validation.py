from __future__ import annotations

import argparse
import math
import re
import unicodedata
from collections import Counter
from pathlib import Path
from typing import Iterable, Sequence

import pandas as pd
from openpyxl import load_workbook
from openpyxl.formatting.rule import FormulaRule
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation


# =============================================================================
# CONFIGURATION
# =============================================================================

DEFAULT_ANNOTATIONS_DIR = Path("validation_qcm_confidential") / "annotateurs_livrables"
ANNOTATION_SHEET = "QCM_ANNOTATION"
GOLD_SHEET = "GOLD"
MANIFEST_SHEET = "ASSIGNMENTS"

OUTPUT_FILENAME = "qcm_consolidation.xlsx"

VALID_ANSWERS = {"A", "B", "C", "D"}
VALID_ITEM_TYPES = {"documented", "tacit"}
VALID_BINARY_FLAGS = {"ok", "probleme"}
VALID_ITEM_FLAGS = {
    "ok",
    "distracteur invalide",
    "plusieurs reponses correctes",
    "question mal posee",
}

ANNOTATION_REQUIRED_COLUMNS = [
    "item_id",
    "item_type",
    "Axe",
    "Difficulty",
    "intent_group",
    "intent_category",
    "input",
    "response_A",
    "response_B",
    "response_C",
    "response_D",
    "annotator_id",
    "annotator_answer",
    "annotator_sources",
    "flag_language",
    "flag_safety",
    "flag_item",
    "comment",
]

GOLD_REQUIRED_COLUMNS = [
    "item_id",
    "correct_answer",
    "Axe",
    "item_type",
]

MANIFEST_REQUIRED_COLUMNS = [
    "item_id",
    "item_type",
    "Axe",
    "annotator_id",
]

ITEM_CONTENT_COLUMNS = [
    "item_id",
    "item_type",
    "Axe",
    "Difficulty",
    "intent_group",
    "intent_category",
    "input",
    "response_A",
    "response_B",
    "response_C",
    "response_D",
]

LONG_OUTPUT_COLUMNS = [
    "item_id",
    "item_type",
    "Axe",
    "Difficulty",
    "intent_group",
    "intent_category",
    "input",
    "response_A",
    "response_B",
    "response_C",
    "response_D",
    "annotator_id",
    "assignment_slot",
    "annotator_answer",
    "annotator_sources",
    "flag_language",
    "flag_safety",
    "flag_item",
    "comment",
    "answer_valid",
    "source_valid",
    "flags_complete_and_valid",
    "annotation_complete",
    "delivery_id",
]

ADJUDICATION_STATUSES = ["accepted", "revised", "rejected"]
DISPUTE_TYPES = [
    "erreur factuelle",
    "formulation ambiguë",
    "variation régionale",
    "distracteur faible",
    "problème de sécurité",
    "annotation incomplète",
    "autre",
]


# =============================================================================
# NORMALISATION ET UTILITAIRES
# =============================================================================


def normalize_text(value: object) -> str:
    """Normalise un texte pour les comparaisons, sans modifier le texte exporté."""
    if pd.isna(value):
        return ""
    text = unicodedata.normalize("NFKD", str(value))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.lower().strip()
    text = re.sub(r"[_/–—-]+", " ", text)
    text = re.sub(r"[’'`]+", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text


def clean_display_text(value: object) -> str:
    """Renvoie une chaîne propre pour l'export, sans transformer la langue."""
    if pd.isna(value):
        return ""
    return str(value).strip()


def normalize_answer(value: object) -> str:
    """Accepte A/B/C/D, response_A, option A, etc.; renvoie '' si invalide."""
    text = normalize_text(value).upper()
    aliases = {
        "A": "A",
        "B": "B",
        "C": "C",
        "D": "D",
        "RESPONSE A": "A",
        "RESPONSE B": "B",
        "RESPONSE C": "C",
        "RESPONSE D": "D",
        "OPTION A": "A",
        "OPTION B": "B",
        "OPTION C": "C",
        "OPTION D": "D",
    }
    if text in aliases:
        return aliases[text]
    match = re.fullmatch(r"(?:RESPONSE|OPTION)?\s*([ABCD])", text)
    return match.group(1) if match else ""


def normalize_item_type(value: object) -> str:
    text = normalize_text(value)
    return text if text in VALID_ITEM_TYPES else ""


def normalize_binary_flag(value: object) -> str:
    text = normalize_text(value)
    if text == "problem":
        text = "probleme"
    return text if text in VALID_BINARY_FLAGS else ""


def normalize_item_flag(value: object) -> str:
    text = normalize_text(value)
    aliases = {
        "ok": "ok",
        "distracteur invalide": "distracteur invalide",
        "distractor invalid": "distracteur invalide",
        "plusieurs reponses correctes": "plusieurs reponses correctes",
        "multiple correct answers": "plusieurs reponses correctes",
        "question mal posee": "question mal posee",
        "poorly worded question": "question mal posee",
    }
    return aliases.get(text, "")


def is_nonempty(value: object) -> bool:
    return bool(clean_display_text(value))


def bool_to_excel(value: bool) -> str:
    return "yes" if bool(value) else "no"


def safe_ratio(numerator: int | float, denominator: int | float) -> float | None:
    if not denominator:
        return None
    return float(numerator) / float(denominator)


def find_default_file(annotations_dir: Path, filename: str) -> Path:
    """Cherche un fichier administrateur dans les emplacements usuels."""
    candidates = [
        annotations_dir.parent / "admin" / filename,
        annotations_dir.parent / filename,
        annotations_dir.parent / "fichiers_admin" / filename,
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    expected = "\n- ".join(str(p) for p in candidates)
    raise FileNotFoundError(
        f"Fichier administrateur introuvable : {filename}. Emplacements testés :\n- {expected}"
    )


def read_excel_sheet(path: Path, sheet_name: str, label: str) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(f"{label} introuvable : {path}")
    try:
        df = pd.read_excel(path, sheet_name=sheet_name, dtype=object)
    except ValueError as exc:
        raise ValueError(
            f"La feuille {sheet_name!r} est absente du fichier {label}: {path}"
        ) from exc
    df = df.loc[:, ~df.columns.astype(str).str.match(r"^Unnamed:")]
    df.columns = [str(c).strip() for c in df.columns]
    return df


def require_columns(df: pd.DataFrame, required: Sequence[str], label: str) -> None:
    missing = [column for column in required if column not in df.columns]
    if missing:
        raise KeyError(f"Colonnes absentes dans {label}: {', '.join(missing)}")


def unique_nonempty(values: Iterable[object]) -> list[str]:
    return sorted({clean_display_text(v) for v in values if clean_display_text(v)})


def joined_unique(values: Iterable[object], separator: str = " | ") -> str:
    return separator.join(unique_nonempty(values))


# =============================================================================
# LECTURE ET CONTRÔLES DES ENTRÉES
# =============================================================================


def load_gold(gold_path: Path) -> pd.DataFrame:
    gold = read_excel_sheet(gold_path, GOLD_SHEET, "gold_reference")
    require_columns(gold, GOLD_REQUIRED_COLUMNS, "gold_reference")

    keep = list(dict.fromkeys(GOLD_REQUIRED_COLUMNS + ["source_row"]))
    gold = gold[[c for c in keep if c in gold.columns]].copy()
    gold = gold.dropna(how="all").reset_index(drop=True)

    gold["item_id"] = gold["item_id"].map(clean_display_text)
    gold["correct_answer"] = gold["correct_answer"].map(normalize_answer)
    gold["item_type"] = gold["item_type"].map(normalize_item_type)
    gold["Axe"] = gold["Axe"].map(clean_display_text)

    issues: list[str] = []
    if (gold["item_id"] == "").any():
        issues.append("item_id vide")
    duplicates = gold.loc[gold["item_id"].duplicated(keep=False), "item_id"].tolist()
    if duplicates:
        issues.append("item_id dupliqués: " + ", ".join(sorted(set(duplicates))[:20]))
    if (~gold["correct_answer"].isin(VALID_ANSWERS)).any():
        bad = gold.loc[~gold["correct_answer"].isin(VALID_ANSWERS), "item_id"].tolist()
        issues.append("correct_answer invalide pour: " + ", ".join(bad[:20]))
    if (~gold["item_type"].isin(VALID_ITEM_TYPES)).any():
        bad = gold.loc[~gold["item_type"].isin(VALID_ITEM_TYPES), "item_id"].tolist()
        issues.append("item_type invalide pour: " + ", ".join(bad[:20]))

    if issues:
        raise ValueError("gold_reference invalide:\n- " + "\n- ".join(issues))

    return gold


def load_manifest(manifest_path: Path) -> pd.DataFrame:
    manifest = read_excel_sheet(manifest_path, MANIFEST_SHEET, "assignment_manifest")
    require_columns(manifest, MANIFEST_REQUIRED_COLUMNS, "assignment_manifest")

    keep = MANIFEST_REQUIRED_COLUMNS + ["assignment_slot"]
    manifest = manifest[[c for c in keep if c in manifest.columns]].copy()
    manifest = manifest.dropna(how="all").reset_index(drop=True)

    manifest["item_id"] = manifest["item_id"].map(clean_display_text)
    manifest["item_type"] = manifest["item_type"].map(normalize_item_type)
    manifest["Axe"] = manifest["Axe"].map(clean_display_text)
    manifest["annotator_id"] = manifest["annotator_id"].map(clean_display_text)

    if "assignment_slot" not in manifest.columns:
        manifest["assignment_slot"] = (
            manifest.sort_values(["item_id", "annotator_id"])
            .groupby("item_id")
            .cumcount()
            .add(1)
        )
    else:
        manifest["assignment_slot"] = pd.to_numeric(
            manifest["assignment_slot"], errors="coerce"
        ).astype("Int64")

    duplicates = manifest.duplicated(["item_id", "annotator_id"], keep=False)
    if duplicates.any():
        rows = manifest.loc[duplicates, ["item_id", "annotator_id"]].head(20)
        pairs = [f"{r.item_id}/{r.annotator_id}" for r in rows.itertuples()]
        raise ValueError(
            "Affectations dupliquées dans assignment_manifest: " + ", ".join(pairs)
        )

    return manifest


def discover_annotation_files(annotations_dir: Path, output_path: Path) -> list[Path]:
    if not annotations_dir.exists() or not annotations_dir.is_dir():
        raise NotADirectoryError(f"Dossier d'annotations introuvable : {annotations_dir}")

    files = sorted(
        path
        for path in annotations_dir.glob("*.xlsx")
        if not path.name.startswith("~$") and path.resolve() != output_path.resolve()
    )
    if not files:
        raise FileNotFoundError(
            f"Aucun fichier .xlsx trouvé dans : {annotations_dir}"
        )
    return files


def load_annotations(
    annotations_dir: Path,
    output_path: Path,
    manifest: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    files = discover_annotation_files(annotations_dir, output_path)
    frames: list[pd.DataFrame] = []
    quality_rows: list[dict[str, object]] = []

    manifest_ids = set(manifest["annotator_id"])

    for delivery_number, file_path in enumerate(files, start=1):
        delivery_id = f"DELIVERY_{delivery_number:02d}"
        df = read_excel_sheet(file_path, ANNOTATION_SHEET, delivery_id)
        require_columns(df, ANNOTATION_REQUIRED_COLUMNS, delivery_id)

        # Liste blanche stricte : aucune colonne d'identité nominative n'est conservée.
        df = df[ANNOTATION_REQUIRED_COLUMNS].copy()
        df = df.dropna(how="all").reset_index(drop=True)
        if df.empty:
            quality_rows.append({
                "severity": "error",
                "issue_type": "empty_delivery",
                "delivery_id": delivery_id,
                "item_id": "",
                "annotator_id": "",
                "details": "Le fichier ne contient aucune ligne d'annotation.",
            })
            continue

        df["delivery_id"] = delivery_id
        df["item_id"] = df["item_id"].map(clean_display_text)
        df["item_type"] = df["item_type"].map(normalize_item_type)
        df["Axe"] = df["Axe"].map(clean_display_text)
        df["annotator_id"] = df["annotator_id"].map(clean_display_text)
        df["annotator_answer"] = df["annotator_answer"].map(normalize_answer)
        df["annotator_sources"] = df["annotator_sources"].map(clean_display_text)
        df["flag_language"] = df["flag_language"].map(normalize_binary_flag)
        df["flag_safety"] = df["flag_safety"].map(normalize_binary_flag)
        df["flag_item"] = df["flag_item"].map(normalize_item_flag)
        df["comment"] = df["comment"].map(clean_display_text)

        ids_in_file = unique_nonempty(df["annotator_id"])
        if len(ids_in_file) != 1:
            quality_rows.append({
                "severity": "error",
                "issue_type": "annotator_id_not_constant",
                "delivery_id": delivery_id,
                "item_id": "",
                "annotator_id": " | ".join(ids_in_file),
                "details": "Chaque fichier doit contenir un seul annotator_id constant.",
            })
        elif ids_in_file[0] not in manifest_ids:
            quality_rows.append({
                "severity": "error",
                "issue_type": "unknown_annotator_id",
                "delivery_id": delivery_id,
                "item_id": "",
                "annotator_id": ids_in_file[0],
                "details": "Cet identifiant n'existe pas dans assignment_manifest.",
            })

        frames.append(df)

    if not frames:
        raise ValueError("Aucune annotation exploitable n'a été chargée.")

    annotations = pd.concat(frames, ignore_index=True)

    # Jointure avec le manifeste afin de récupérer le slot et contrôler l'affectation.
    manifest_key = manifest[
        ["item_id", "annotator_id", "item_type", "Axe", "assignment_slot"]
    ].rename(columns={"item_type": "manifest_item_type", "Axe": "manifest_Axe"})

    annotations = annotations.merge(
        manifest_key,
        on=["item_id", "annotator_id"],
        how="left",
        validate="many_to_one",
        indicator="assignment_match",
    )

    annotations["assignment_slot"] = annotations["assignment_slot"].astype("Int64")
    annotations["assigned_in_manifest"] = annotations["assignment_match"].eq("both")
    annotations.drop(columns=["assignment_match"], inplace=True)

    # Contrôles ligne par ligne.
    annotations["answer_valid"] = annotations["annotator_answer"].isin(VALID_ANSWERS)
    annotations["source_valid"] = (
        annotations["item_type"].eq("tacit")
        | annotations["annotator_sources"].map(is_nonempty)
    )
    annotations["flags_complete_and_valid"] = (
        annotations["flag_language"].isin(VALID_BINARY_FLAGS)
        & annotations["flag_safety"].isin(VALID_BINARY_FLAGS)
        & annotations["flag_item"].isin(VALID_ITEM_FLAGS)
    )
    annotations["metadata_consistent"] = (
        annotations["assigned_in_manifest"]
        & annotations["item_type"].eq(annotations["manifest_item_type"])
        & annotations["Axe"].eq(annotations["manifest_Axe"])
    )
    annotations["annotation_complete"] = (
        annotations["answer_valid"]
        & annotations["source_valid"]
        & annotations["flags_complete_and_valid"]
        & annotations["metadata_consistent"]
        & annotations["item_id"].map(is_nonempty)
        & annotations["annotator_id"].map(is_nonempty)
    )

    # Problèmes détectés dans les livrables.
    duplicate_mask = annotations.duplicated(["item_id", "annotator_id"], keep=False)
    for row in annotations.loc[duplicate_mask].itertuples():
        quality_rows.append({
            "severity": "error",
            "issue_type": "duplicate_annotation",
            "delivery_id": row.delivery_id,
            "item_id": row.item_id,
            "annotator_id": row.annotator_id,
            "details": "Plus d'une ligne pour le même couple item_id/annotator_id.",
        })

    for row in annotations.itertuples():
        if not row.assigned_in_manifest:
            quality_rows.append({
                "severity": "error",
                "issue_type": "unexpected_assignment",
                "delivery_id": row.delivery_id,
                "item_id": row.item_id,
                "annotator_id": row.annotator_id,
                "details": "Annotation absente du manifeste d'affectation.",
            })
        if not row.answer_valid:
            quality_rows.append({
                "severity": "error",
                "issue_type": "invalid_or_missing_answer",
                "delivery_id": row.delivery_id,
                "item_id": row.item_id,
                "annotator_id": row.annotator_id,
                "details": "annotator_answer doit être A, B, C ou D.",
            })
        if not row.source_valid:
            quality_rows.append({
                "severity": "error",
                "issue_type": "missing_documented_source",
                "delivery_id": row.delivery_id,
                "item_id": row.item_id,
                "annotator_id": row.annotator_id,
                "details": "Une source est obligatoire pour un item documented.",
            })
        if not row.flags_complete_and_valid:
            quality_rows.append({
                "severity": "error",
                "issue_type": "invalid_or_missing_flag",
                "delivery_id": row.delivery_id,
                "item_id": row.item_id,
                "annotator_id": row.annotator_id,
                "details": "Les trois flags doivent être remplis avec une valeur autorisée.",
            })
        if row.assigned_in_manifest and not row.metadata_consistent:
            quality_rows.append({
                "severity": "error",
                "issue_type": "metadata_mismatch",
                "delivery_id": row.delivery_id,
                "item_id": row.item_id,
                "annotator_id": row.annotator_id,
                "details": "item_type ou Axe diffère du manifeste.",
            })

    # Affectations manquantes.
    submitted_pairs = set(zip(annotations["item_id"], annotations["annotator_id"]))
    for row in manifest.itertuples():
        pair = (row.item_id, row.annotator_id)
        if pair not in submitted_pairs:
            quality_rows.append({
                "severity": "error",
                "issue_type": "missing_annotation",
                "delivery_id": "",
                "item_id": row.item_id,
                "annotator_id": row.annotator_id,
                "details": "Aucune annotation reçue pour cette affectation.",
            })

    quality = pd.DataFrame(
        quality_rows,
        columns=[
            "severity",
            "issue_type",
            "delivery_id",
            "item_id",
            "annotator_id",
            "details",
        ],
    )

    return annotations, quality


# =============================================================================
# CONSOLIDATION ET DÉCISIONS
# =============================================================================


def make_item_content(annotations: pd.DataFrame, gold: pd.DataFrame) -> pd.DataFrame:
    content = annotations[ITEM_CONTENT_COLUMNS + ["delivery_id"]].copy()
    content = content.sort_values(["item_id", "delivery_id"]).drop_duplicates(
        "item_id", keep="first"
    )
    content = content.drop(columns=["delivery_id"])

    base = gold.merge(content, on=["item_id", "item_type", "Axe"], how="left")
    for column in ITEM_CONTENT_COLUMNS:
        if column not in base.columns:
            base[column] = ""
    return base


def annotation_issue_for_item(
    item_id: str,
    item_annotations: pd.DataFrame,
    expected_count: int,
    quality: pd.DataFrame,
) -> tuple[bool, str]:
    reasons: list[str] = []

    if len(item_annotations) != expected_count:
        reasons.append(
            f"nombre d'annotations reçu={len(item_annotations)}, attendu={expected_count}"
        )

    if item_annotations.duplicated(["item_id", "annotator_id"]).any():
        reasons.append("annotation dupliquée")

    if not item_annotations.empty and not item_annotations["annotation_complete"].all():
        reasons.append("annotation incomplète ou invalide")

    item_quality = quality.loc[quality["item_id"].eq(item_id), "issue_type"]
    if not item_quality.empty:
        reasons.append("contrôle qualité: " + ", ".join(sorted(set(item_quality))))

    return bool(reasons), "; ".join(reasons)


def decision_for_item(
    item_row: pd.Series,
    item_annotations: pd.DataFrame,
    quality: pd.DataFrame,
) -> dict[str, object]:
    item_id = item_row["item_id"]
    item_type = item_row["item_type"]
    gold_answer = item_row["correct_answer"]
    expected_count = 1 if item_type == "documented" else 2

    item_annotations = item_annotations.sort_values(
        ["assignment_slot", "annotator_id"], na_position="last"
    ).copy()

    has_data_issue, data_issue_details = annotation_issue_for_item(
        item_id, item_annotations, expected_count, quality
    )

    safety_problem = item_annotations["flag_safety"].eq("probleme").any()
    item_problem = item_annotations["flag_item"].ne("ok").any()
    language_problem = item_annotations["flag_language"].eq("probleme").any()
    mandatory_flag_review = safety_problem or item_problem

    annotator_answers = [
        answer
        for answer in item_annotations["annotator_answer"].tolist()
        if answer in VALID_ANSWERS
    ]
    votes = [gold_answer] + annotator_answers
    counts = Counter(votes)
    ordered_counts = sorted(counts.items(), key=lambda x: (-x[1], x[0]))
    top_answer = ordered_counts[0][0] if ordered_counts else ""
    top_count = ordered_counts[0][1] if ordered_counts else 0
    vote_distribution = ", ".join(f"{answer}:{counts.get(answer, 0)}" for answer in "ABCD")

    automatic_decision = ""
    provisional_answer = ""
    decision_reason = ""

    if has_data_issue:
        automatic_decision = "data_issue"
        decision_reason = data_issue_details
    elif item_type == "documented":
        validator_answer = annotator_answers[0]
        if mandatory_flag_review:
            automatic_decision = "adjudication"
            provisional_answer = gold_answer if validator_answer == gold_answer else ""
            decision_reason = "flag_safety ou flag_item levé"
        elif validator_answer == gold_answer:
            automatic_decision = "accept"
            provisional_answer = gold_answer
            decision_reason = "annotateur et clé d'origine d'accord"
        else:
            automatic_decision = "adjudication"
            decision_reason = "désaccord entre l'annotateur et la clé d'origine"
    else:
        if top_count == 3:
            provisional_answer = top_answer
            if mandatory_flag_review:
                automatic_decision = "adjudication"
                decision_reason = "3/3 d'accord, mais flag_safety ou flag_item levé"
            else:
                automatic_decision = "accept"
                decision_reason = "3/3 votes d'accord"
        elif top_count == 2:
            provisional_answer = top_answer
            automatic_decision = "adjudication"
            decision_reason = "majorité 2/3: arbitrer erreur, ambiguïté ou variation régionale"
        else:
            automatic_decision = "reject_or_rewrite"
            decision_reason = "aucune majorité parmi les 3 votes"

    if language_problem:
        language_note = "yes"
    else:
        language_note = "no"

    result: dict[str, object] = {
        "item_id": item_id,
        "item_type": item_type,
        "Axe": item_row.get("Axe", ""),
        "Difficulty": item_row.get("Difficulty", ""),
        "intent_group": item_row.get("intent_group", ""),
        "intent_category": item_row.get("intent_category", ""),
        "input": item_row.get("input", ""),
        "response_A": item_row.get("response_A", ""),
        "response_B": item_row.get("response_B", ""),
        "response_C": item_row.get("response_C", ""),
        "response_D": item_row.get("response_D", ""),
        "original_key": gold_answer,
        "expected_annotations": expected_count,
        "received_annotations": len(item_annotations),
        "vote_distribution": vote_distribution,
        "provisional_answer": provisional_answer,
        "automatic_decision": automatic_decision,
        "decision_reason": decision_reason,
        "mandatory_flag_review": bool_to_excel(mandatory_flag_review),
        "language_review_recommended": language_note,
        "flag_language_details": joined_unique(
            f"{r.annotator_id}:{r.flag_language}"
            for r in item_annotations.itertuples()
            if r.flag_language and r.flag_language != "ok"
        ),
        "flag_safety_details": joined_unique(
            f"{r.annotator_id}:{r.flag_safety}"
            for r in item_annotations.itertuples()
            if r.flag_safety and r.flag_safety != "ok"
        ),
        "flag_item_details": joined_unique(
            f"{r.annotator_id}:{r.flag_item}"
            for r in item_annotations.itertuples()
            if r.flag_item and r.flag_item != "ok"
        ),
        "data_quality_issue": bool_to_excel(has_data_issue),
        "data_quality_details": data_issue_details,
        "adjudicated_by": "",
        "dispute_type": "",
        "final_answer": "",
        "status": "",
        "adjudication_comment": "",
    }

    for slot in (1, 2):
        prefix = f"annotator_{slot}"
        if len(item_annotations) >= slot:
            row = item_annotations.iloc[slot - 1]
            result[f"{prefix}_id"] = row["annotator_id"]
            result[f"{prefix}_answer"] = row["annotator_answer"]
            result[f"{prefix}_sources"] = row["annotator_sources"]
            result[f"{prefix}_flag_language"] = row["flag_language"]
            result[f"{prefix}_flag_safety"] = row["flag_safety"]
            result[f"{prefix}_flag_item"] = row["flag_item"]
            result[f"{prefix}_comment"] = row["comment"]
        else:
            result[f"{prefix}_id"] = ""
            result[f"{prefix}_answer"] = ""
            result[f"{prefix}_sources"] = ""
            result[f"{prefix}_flag_language"] = ""
            result[f"{prefix}_flag_safety"] = ""
            result[f"{prefix}_flag_item"] = ""
            result[f"{prefix}_comment"] = ""

    return result


def build_consolidation(
    annotations: pd.DataFrame,
    gold: pd.DataFrame,
    quality: pd.DataFrame,
) -> pd.DataFrame:
    item_content = make_item_content(annotations, gold)
    rows: list[dict[str, object]] = []

    grouped = {item_id: group for item_id, group in annotations.groupby("item_id")}
    empty = annotations.iloc[0:0].copy()

    for _, item_row in item_content.iterrows():
        item_annotations = grouped.get(item_row["item_id"], empty)
        rows.append(decision_for_item(item_row, item_annotations, quality))

    consolidation = pd.DataFrame(rows)

    # Ordre lisible : contenu, votes, décision, arbitrage.
    ordered_columns = [
        "item_id",
        "item_type",
        "Axe",
        "Difficulty",
        "intent_group",
        "intent_category",
        "input",
        "response_A",
        "response_B",
        "response_C",
        "response_D",
        "original_key",
        "annotator_1_id",
        "annotator_1_answer",
        "annotator_1_sources",
        "annotator_1_flag_language",
        "annotator_1_flag_safety",
        "annotator_1_flag_item",
        "annotator_1_comment",
        "annotator_2_id",
        "annotator_2_answer",
        "annotator_2_sources",
        "annotator_2_flag_language",
        "annotator_2_flag_safety",
        "annotator_2_flag_item",
        "annotator_2_comment",
        "expected_annotations",
        "received_annotations",
        "vote_distribution",
        "provisional_answer",
        "automatic_decision",
        "decision_reason",
        "mandatory_flag_review",
        "language_review_recommended",
        "flag_language_details",
        "flag_safety_details",
        "flag_item_details",
        "data_quality_issue",
        "data_quality_details",
        "adjudicated_by",
        "dispute_type",
        "final_answer",
        "status",
        "adjudication_comment",
    ]
    return consolidation[ordered_columns]


# =============================================================================
# MÉTRIQUES
# =============================================================================


def cohen_kappa(pairs: pd.DataFrame, col_a: str, col_b: str) -> tuple[float | None, float | None, int]:
    valid = pairs[col_a].isin(VALID_ANSWERS) & pairs[col_b].isin(VALID_ANSWERS)
    data = pairs.loc[valid, [col_a, col_b]]
    n = len(data)
    if n == 0:
        return None, None, 0

    observed = float((data[col_a] == data[col_b]).mean())
    p_a = data[col_a].value_counts(normalize=True)
    p_b = data[col_b].value_counts(normalize=True)
    expected = sum(float(p_a.get(c, 0.0)) * float(p_b.get(c, 0.0)) for c in "ABCD")
    if math.isclose(1.0 - expected, 0.0):
        kappa = None
    else:
        kappa = (observed - expected) / (1.0 - expected)
    return observed, kappa, n


def fleiss_kappa(vote_rows: list[list[str]]) -> tuple[float | None, float | None, int]:
    complete = [row for row in vote_rows if len(row) == 3 and all(v in VALID_ANSWERS for v in row)]
    n_items = len(complete)
    if n_items == 0:
        return None, None, 0

    n_raters = 3
    category_totals = Counter()
    item_agreements: list[float] = []

    for votes in complete:
        counts = Counter(votes)
        category_totals.update(votes)
        p_i = (sum(count * count for count in counts.values()) - n_raters) / (
            n_raters * (n_raters - 1)
        )
        item_agreements.append(p_i)

    p_bar = sum(item_agreements) / n_items
    p_j = {
        category: category_totals.get(category, 0) / (n_items * n_raters)
        for category in "ABCD"
    }
    p_e = sum(probability * probability for probability in p_j.values())
    if math.isclose(1.0 - p_e, 0.0):
        kappa = None
    else:
        kappa = (p_bar - p_e) / (1.0 - p_e)
    return p_bar, kappa, n_items


def build_metrics(
    consolidation: pd.DataFrame,
    annotations: pd.DataFrame,
) -> pd.DataFrame:
    rows: list[dict[str, object]] = []

    def add(scope: str, axis: str, metric: str, value: object, n_items: object = "") -> None:
        rows.append({
            "scope": scope,
            "Axe": axis,
            "metric": metric,
            "value": value,
            "n_items": n_items,
        })

    add("all", "ALL", "total_items", len(consolidation), len(consolidation))
    for item_type, count in consolidation["item_type"].value_counts().items():
        add("all", "ALL", f"items_{item_type}", int(count), int(count))
    for decision, count in consolidation["automatic_decision"].value_counts().items():
        add("all", "ALL", f"decision_{decision}", int(count), int(count))

    add(
        "all",
        "ALL",
        "flag_language_rate",
        safe_ratio(
            int(annotations["flag_language"].eq("probleme").sum()),
            int(annotations["flag_language"].isin(VALID_BINARY_FLAGS).sum()),
        ),
        int(annotations["flag_language"].isin(VALID_BINARY_FLAGS).sum()),
    )
    add(
        "all",
        "ALL",
        "flag_safety_rate",
        safe_ratio(
            int(annotations["flag_safety"].eq("probleme").sum()),
            int(annotations["flag_safety"].isin(VALID_BINARY_FLAGS).sum()),
        ),
        int(annotations["flag_safety"].isin(VALID_BINARY_FLAGS).sum()),
    )
    add(
        "all",
        "ALL",
        "flag_item_rate",
        safe_ratio(
            int(annotations["flag_item"].isin(VALID_ITEM_FLAGS - {"ok"}).sum()),
            int(annotations["flag_item"].isin(VALID_ITEM_FLAGS).sum()),
        ),
        int(annotations["flag_item"].isin(VALID_ITEM_FLAGS).sum()),
    )

    documented = consolidation.loc[
        consolidation["item_type"].eq("documented"),
        ["original_key", "annotator_1_answer"],
    ]
    raw, kappa, n = cohen_kappa(documented, "original_key", "annotator_1_answer")
    add("documented", "ALL", "raw_agreement_author_validator", raw, n)
    add("documented", "ALL", "cohen_kappa_author_validator", kappa, n)

    tacit = consolidation.loc[consolidation["item_type"].eq("tacit")]
    vote_rows = tacit[["original_key", "annotator_1_answer", "annotator_2_answer"]].values.tolist()
    raw_f, fleiss, n_f = fleiss_kappa(vote_rows)
    add("tacit", "ALL", "mean_pairwise_raw_agreement", raw_f, n_f)
    add("tacit", "ALL", "fleiss_kappa_3_votes", fleiss, n_f)
    add(
        "tacit",
        "ALL",
        "unanimous_3_of_3_rate",
        safe_ratio(
            int(
                tacit.apply(
                    lambda r: len({r["original_key"], r["annotator_1_answer"], r["annotator_2_answer"]}) == 1
                    and all(
                        value in VALID_ANSWERS
                        for value in [r["original_key"], r["annotator_1_answer"], r["annotator_2_answer"]]
                    ),
                    axis=1,
                ).sum()
            ),
            n_f,
        ),
        n_f,
    )

    for axis, axis_df in tacit.groupby("Axe", dropna=False):
        axis_votes = axis_df[
            ["original_key", "annotator_1_answer", "annotator_2_answer"]
        ].values.tolist()
        raw_axis, kappa_axis, n_axis = fleiss_kappa(axis_votes)
        add("tacit_by_axis", clean_display_text(axis), "mean_pairwise_raw_agreement", raw_axis, n_axis)
        add("tacit_by_axis", clean_display_text(axis), "fleiss_kappa_3_votes", kappa_axis, n_axis)

    metrics = pd.DataFrame(rows)
    metrics["note"] = ""
    kappa_mask = metrics["metric"].str.contains("kappa", case=False, na=False)
    metrics.loc[kappa_mask, "note"] = (
        "Interpréter avec le taux d'accord brut; le kappa peut être faible lorsque les catégories sont déséquilibrées."
    )
    return metrics


def build_annotator_summary(annotations: pd.DataFrame, manifest: pd.DataFrame) -> pd.DataFrame:
    expected = manifest.groupby("annotator_id").size().rename("expected_annotations")
    received = annotations.groupby("annotator_id").agg(
        received_rows=("item_id", "size"),
        unique_items=("item_id", "nunique"),
        complete_annotations=("annotation_complete", "sum"),
        documented_annotations=("item_type", lambda s: int((s == "documented").sum())),
        tacit_annotations=("item_type", lambda s: int((s == "tacit").sum())),
        language_flags=("flag_language", lambda s: int((s == "probleme").sum())),
        safety_flags=("flag_safety", lambda s: int((s == "probleme").sum())),
        item_flags=("flag_item", lambda s: int((s != "ok").sum())),
    )
    summary = expected.to_frame().join(received, how="outer").fillna(0).reset_index()
    numeric_columns = [c for c in summary.columns if c != "annotator_id"]
    summary[numeric_columns] = summary[numeric_columns].astype(int)
    summary["completion_rate"] = summary.apply(
        lambda r: safe_ratio(r["complete_annotations"], r["expected_annotations"]), axis=1
    )
    return summary


# =============================================================================
# EXPORT EXCEL
# =============================================================================


def excel_safe_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out = out.where(pd.notna(out), None)
    return out


def write_initial_workbook(
    output_path: Path,
    consolidation: pd.DataFrame,
    annotations: pd.DataFrame,
    quality: pd.DataFrame,
    metrics: pd.DataFrame,
    annotator_summary: pd.DataFrame,
) -> None:
    adjudication_queue = consolidation.loc[
        consolidation["automatic_decision"].ne("accept")
    ].copy()
    language_review = consolidation.loc[
        consolidation["language_review_recommended"].eq("yes")
    ].copy()

    long_annotations = annotations.copy()
    for column in LONG_OUTPUT_COLUMNS:
        if column not in long_annotations.columns:
            long_annotations[column] = ""
    long_annotations = long_annotations[LONG_OUTPUT_COLUMNS].sort_values(
        ["item_id", "assignment_slot", "annotator_id"], na_position="last"
    )

    with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
        excel_safe_dataframe(consolidation).to_excel(
            writer, index=False, sheet_name="CONSOLIDATION"
        )
        excel_safe_dataframe(adjudication_queue).to_excel(
            writer, index=False, sheet_name="ADJUDICATION_QUEUE"
        )
        excel_safe_dataframe(language_review).to_excel(
            writer, index=False, sheet_name="LANGUAGE_REVIEW"
        )
        excel_safe_dataframe(long_annotations).to_excel(
            writer, index=False, sheet_name="LONG_ANNOTATIONS"
        )
        excel_safe_dataframe(metrics).to_excel(
            writer, index=False, sheet_name="METRICS"
        )
        excel_safe_dataframe(annotator_summary).to_excel(
            writer, index=False, sheet_name="BY_ANNOTATOR_ID"
        )
        excel_safe_dataframe(quality).to_excel(
            writer, index=False, sheet_name="QUALITY_REPORT"
        )


def style_sheet(ws, freeze_cell: str = "A2", filter_enabled: bool = True) -> None:
    header_fill = PatternFill("solid", fgColor="D9EAF7")
    for cell in ws[1]:
        cell.font = Font(bold=True)
        cell.fill = header_fill
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)

    ws.freeze_panes = freeze_cell
    if filter_enabled and ws.max_row >= 1 and ws.max_column >= 1:
        ws.auto_filter.ref = ws.dimensions
    ws.sheet_view.showGridLines = False
    ws.row_dimensions[1].height = 34

    header_map = {cell.value: cell.column for cell in ws[1]}
    text_heavy = {
        "input",
        "response_A",
        "response_B",
        "response_C",
        "response_D",
        "annotator_1_sources",
        "annotator_2_sources",
        "annotator_sources",
        "comment",
        "annotator_1_comment",
        "annotator_2_comment",
        "decision_reason",
        "data_quality_details",
        "details",
        "adjudication_comment",
        "note",
    }

    for header, col_idx in header_map.items():
        header_text = clean_display_text(header)
        if header_text in text_heavy:
            width = 46
        elif "id" in header_text.lower():
            width = 16
        elif "flag" in header_text.lower():
            width = 24
        elif header_text in {"Axe", "intent_group", "intent_category", "metric"}:
            width = 28
        else:
            width = min(max(len(header_text) + 3, 12), 24)
        ws.column_dimensions[get_column_letter(col_idx)].width = width

    for row in ws.iter_rows(min_row=2):
        for cell in row:
            cell.alignment = Alignment(vertical="top", wrap_text=True)


def add_adjudication_validations(ws) -> None:
    headers = {cell.value: cell.column for cell in ws[1]}
    last_row = max(ws.max_row, 2)

    if "final_answer" in headers:
        dv_answer = DataValidation(type="list", formula1='"A,B,C,D"', allow_blank=True)
        ws.add_data_validation(dv_answer)
        col = get_column_letter(headers["final_answer"])
        dv_answer.add(f"{col}2:{col}{last_row}")

    if "status" in headers:
        dv_status = DataValidation(
            type="list",
            formula1='"' + ",".join(ADJUDICATION_STATUSES) + '"',
            allow_blank=True,
        )
        ws.add_data_validation(dv_status)
        col = get_column_letter(headers["status"])
        dv_status.add(f"{col}2:{col}{last_row}")

    if "dispute_type" in headers:
        # Liste assez courte pour être utilisée directement dans Excel.
        formula = '"' + ",".join(DISPUTE_TYPES) + '"'
        dv_dispute = DataValidation(type="list", formula1=formula, allow_blank=True)
        ws.add_data_validation(dv_dispute)
        col = get_column_letter(headers["dispute_type"])
        dv_dispute.add(f"{col}2:{col}{last_row}")


def add_decision_coloring(ws) -> None:
    headers = {cell.value: cell.column for cell in ws[1]}
    if "automatic_decision" not in headers or ws.max_row < 2:
        return

    col_letter = get_column_letter(headers["automatic_decision"])
    data_range = f"A2:{get_column_letter(ws.max_column)}{ws.max_row}"

    rules = [
        ("accept", "E2F0D9"),
        ("adjudication", "FFF2CC"),
        ("reject_or_rewrite", "FCE4D6"),
        ("data_issue", "F4CCCC"),
    ]
    for decision, color in rules:
        ws.conditional_formatting.add(
            data_range,
            FormulaRule(
                formula=[f'${col_letter}2="{decision}"'],
                fill=PatternFill("solid", fgColor=color),
            ),
        )


def format_workbook(output_path: Path) -> None:
    wb = load_workbook(output_path)

    for ws in wb.worksheets:
        style_sheet(ws)

    for sheet_name in ["CONSOLIDATION", "ADJUDICATION_QUEUE"]:
        ws = wb[sheet_name]
        add_adjudication_validations(ws)
        add_decision_coloring(ws)

    # Formats numériques des métriques.
    ws_metrics = wb["METRICS"]
    metric_headers = {cell.value: cell.column for cell in ws_metrics[1]}
    if "value" in metric_headers:
        value_col = metric_headers["value"]
        for row in range(2, ws_metrics.max_row + 1):
            metric_name = clean_display_text(ws_metrics.cell(row, metric_headers["metric"]).value)
            if any(token in metric_name for token in ["rate", "agreement", "kappa"]):
                ws_metrics.cell(row, value_col).number_format = "0.000"

    ws_summary = wb["BY_ANNOTATOR_ID"]
    summary_headers = {cell.value: cell.column for cell in ws_summary[1]}
    if "completion_rate" in summary_headers:
        col = summary_headers["completion_rate"]
        for row in range(2, ws_summary.max_row + 1):
            ws_summary.cell(row, col).number_format = "0.0%"

    wb.save(output_path)


# =============================================================================
# PROGRAMME PRINCIPAL
# =============================================================================


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Fusionne les livrables QCM, vérifie les affectations, applique les règles "
            "de décision et produit un classeur de consolidation anonymisé."
        )
    )
    parser.add_argument(
        "--annotations-dir",
        type=Path,
        default=DEFAULT_ANNOTATIONS_DIR,
        help=(
            "Dossier contenant les fichiers Excel livrés par les annotateurs "
            f"(défaut: {DEFAULT_ANNOTATIONS_DIR})."
        ),
    )
    parser.add_argument(
        "--gold",
        type=Path,
        default=None,
        help="Chemin de gold_reference.xlsx. Par défaut, recherche dans le dossier admin voisin.",
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=None,
        help="Chemin de assignment_manifest.xlsx. Par défaut, recherche dans le dossier admin voisin.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Chemin du classeur de sortie. Par défaut: validation_qcm_confidential/qcm_consolidation.xlsx",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    annotations_dir = args.annotations_dir.resolve()
    gold_path = (
        args.gold.resolve()
        if args.gold is not None
        else find_default_file(annotations_dir, "gold_reference.xlsx").resolve()
    )
    manifest_path = (
        args.manifest.resolve()
        if args.manifest is not None
        else find_default_file(annotations_dir, "assignment_manifest.xlsx").resolve()
    )
    output_path = (
        args.output.resolve()
        if args.output is not None
        else (annotations_dir.parent / OUTPUT_FILENAME).resolve()
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)

    gold = load_gold(gold_path)
    manifest = load_manifest(manifest_path)

    # Vérifie que le manifeste correspond bien à la référence.
    manifest_check = manifest.merge(
        gold[["item_id", "item_type", "Axe"]],
        on="item_id",
        how="left",
        suffixes=("_manifest", "_gold"),
        indicator=True,
    )
    unknown_manifest_items = manifest_check["_merge"].ne("both")
    metadata_mismatch = (
        manifest_check["_merge"].eq("both")
        & (
            manifest_check["item_type_manifest"].ne(manifest_check["item_type_gold"])
            | manifest_check["Axe_manifest"].ne(manifest_check["Axe_gold"])
        )
    )
    if unknown_manifest_items.any() or metadata_mismatch.any():
        bad_ids = manifest_check.loc[
            unknown_manifest_items | metadata_mismatch, "item_id"
        ].drop_duplicates().tolist()
        raise ValueError(
            "Le manifeste ne correspond pas à gold_reference pour: "
            + ", ".join(bad_ids[:30])
        )

    expected_counts = manifest.groupby("item_id").size()
    expected_from_gold = gold.set_index("item_id")["item_type"].map(
        {"documented": 1, "tacit": 2}
    )
    count_mismatch = expected_counts.reindex(expected_from_gold.index, fill_value=0).ne(
        expected_from_gold
    )
    if count_mismatch.any():
        bad_ids = expected_from_gold.index[count_mismatch].tolist()
        raise ValueError(
            "Cardinalité incorrecte dans assignment_manifest pour: "
            + ", ".join(bad_ids[:30])
        )

    annotations, quality = load_annotations(annotations_dir, output_path, manifest)
    consolidation = build_consolidation(annotations, gold, quality)
    metrics = build_metrics(consolidation, annotations)
    annotator_summary = build_annotator_summary(annotations, manifest)

    write_initial_workbook(
        output_path,
        consolidation,
        annotations,
        quality,
        metrics,
        annotator_summary,
    )
    format_workbook(output_path)

    decision_counts = consolidation["automatic_decision"].value_counts().to_dict()
    print("=" * 76)
    print("Consolidation QCM terminée.")
    print(f"Dossier des livrables : {annotations_dir}")
    print(f"Nombre de fichiers lus : {annotations['delivery_id'].nunique()}")
    print(f"Nombre d'annotator_id : {annotations['annotator_id'].nunique()}")
    print(f"Nombre d'items : {len(consolidation)}")
    print(f"Annotations reçues : {len(annotations)}")
    print(f"Problèmes de qualité : {len(quality)}")
    print("Décisions automatiques :")
    for decision in ["accept", "adjudication", "reject_or_rewrite", "data_issue"]:
        print(f"  - {decision}: {decision_counts.get(decision, 0)}")
    print(f"Classeur produit : {output_path}")
    print("Aucun nom de personne ni nom de fichier source n'est exporté.")
    print("=" * 76)


if __name__ == "__main__":
    main()
