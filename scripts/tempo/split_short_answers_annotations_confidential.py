from __future__ import annotations

import argparse
import math
import random
import re
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

import pandas as pd
from openpyxl import Workbook, load_workbook
from openpyxl.formatting.rule import FormulaRule
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation


# =============================================================================
# CONFIGURATION
# =============================================================================

SHEET_NAME = "Short answer"
ANNOTATION_SHEET_NAME = "SHORT_ANSWER_REVIEW"
LEGEND_SHEET_NAME = "LEGEND"
DEFAULT_RANDOM_SEED = 20260726
DEFAULT_DOUBLE_CHECK_PERCENT = 20.0

ANNOTATORS: List[str] = [
    "ANN_01",
    "ANN_02",
    "ANN_03",
    "ANN_04",
    "ANN_05",
    "ANN_06",
    "ANN_07",
    "ANN_08",
    "ANN_09",
]

# Facultatif : si le fichier contient une colonne indiquant l'auteur initial,
# écrire ici son nom exact pour empêcher l'auto-évaluation.
# Exemples : "author_name", "creator", "created_by".
# Laisser None si cette information n'existe pas.
CREATOR_COLUMN: Optional[str] = None

REQUIRED_COLUMNS = [
    "Axe",
    "Difficulty",
    "intent_group",
    "intent_category",
    "input",
    "answer",
    "item_id",
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

RESERVED_COLUMNS = set(ANNOTATION_COLUMNS + ["source_row"])
ANSWER_CORRECTNESS_VALUES = ["correct", "minor_fix", "incorrect"]
QUESTION_QUALITY_VALUES = ["ok", "review"]
REVIEW_ROUNDS = ["primary", "second_check"]


# =============================================================================
# TEXT AND FILE UTILITIES
# =============================================================================


def normalize_text(value: object) -> str:
    """Normalize text for comparisons without changing the source value."""
    text = "" if pd.isna(value) else str(value)
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.lower().strip()
    text = re.sub(r"[_/–—-]+", " ", text)
    text = re.sub(r"[’'`]+", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text


def has_value(value: object) -> bool:
    return not pd.isna(value) and bool(str(value).strip())


def safe_filename(text: str) -> str:
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = re.sub(r'[<>:"/\\|?*]+', "_", text)
    text = re.sub(r"\s+", "_", text.strip())
    return text


def creator_to_annotator_id(value: object) -> Optional[str]:
    """Resolve an author name/ID to a configured annotator ID."""
    if not has_value(value):
        return None

    normalized = normalize_text(value)
    for annotator_id in ANNOTATORS:
        if normalized == normalize_text(annotator_id):
            return annotator_id
    return None


# =============================================================================
# INPUT PREPARATION AND VALIDATION
# =============================================================================


def prepare_dataframe(input_file: Path) -> Tuple[pd.DataFrame, List[str]]:
    """
    Read and validate the 'Short answer' sheet.

    All meaningful source columns are preserved, including any extra columns.
    Only completely empty technical 'Unnamed:' columns are removed. Rows that
    contain no actual item content are ignored even if Excel formatting extends
    below the table.
    """
    try:
        df = pd.read_excel(input_file, sheet_name=SHEET_NAME, dtype=object)
    except ValueError as exc:
        available = pd.ExcelFile(input_file).sheet_names
        raise ValueError(
            f"Feuille '{SHEET_NAME}' introuvable. Feuilles disponibles : "
            + ", ".join(available)
        ) from exc

    df.columns = [str(column).strip() for column in df.columns]

    unnamed_columns = [
        column
        for column in df.columns
        if re.match(r"^Unnamed:", column, flags=re.IGNORECASE)
        and df[column].isna().all()
    ]
    if unnamed_columns:
        df = df.drop(columns=unnamed_columns)

    missing = [column for column in REQUIRED_COLUMNS if column not in df.columns]
    if missing:
        raise KeyError(
            f"Colonnes obligatoires absentes de la feuille '{SHEET_NAME}' : "
            + ", ".join(missing)
        )

    collisions = sorted(RESERVED_COLUMNS.intersection(df.columns))
    if collisions:
        raise ValueError(
            "Le fichier source contient déjà des colonnes réservées au cross-check : "
            + ", ".join(collisions)
            + ". Renomme-les ou supprime-les avant d'exécuter le script."
        )

    if CREATOR_COLUMN is not None and CREATOR_COLUMN not in df.columns:
        raise KeyError(
            f"CREATOR_COLUMN='{CREATOR_COLUMN}' mais cette colonne n'existe pas "
            f"dans la feuille '{SHEET_NAME}'."
        )

    original_excel_rows = pd.Series(df.index + 2, index=df.index)

    core_columns = ["Axe", "Difficulty", "input", "answer", "item_id"]
    meaningful_mask = df[core_columns].apply(
        lambda column: column.map(has_value)
    ).any(axis=1)

    df = df.loc[meaningful_mask].copy()
    df["source_row"] = original_excel_rows.loc[df.index].astype(int)
    df = df.reset_index(drop=True)

    if df.empty:
        raise ValueError(f"La feuille '{SHEET_NAME}' ne contient aucun item exploitable.")

    source_columns = [column for column in df.columns if column != "source_row"]

    field_errors: List[str] = []
    for _, row in df.iterrows():
        excel_row = int(row["source_row"])
        for column in [
            "Axe",
            "Difficulty",
            "intent_group",
            "intent_category",
            "input",
            "answer",
        ]:
            if not has_value(row[column]):
                field_errors.append(f"ligne Excel {excel_row}: '{column}' vide")

    if field_errors:
        displayed = field_errors[:50]
        suffix = "" if len(field_errors) <= 50 else f"\n... et {len(field_errors) - 50} autre(s)."
        raise ValueError(
            "Items incomplets détectés :\n- " + "\n- ".join(displayed) + suffix
        )

    # Preserve existing IDs and generate only missing ones.
    df["item_id"] = df["item_id"].apply(
        lambda value: "" if pd.isna(value) else str(value).strip()
    )
    existing_ids = {item_id for item_id in df["item_id"] if item_id}
    generated_ids: List[str] = []
    next_number = 1

    for current_id in df["item_id"]:
        if current_id:
            generated_ids.append(current_id)
            continue

        while f"SA_{next_number:04d}" in existing_ids:
            next_number += 1
        new_id = f"SA_{next_number:04d}"
        existing_ids.add(new_id)
        generated_ids.append(new_id)
        next_number += 1

    df["item_id"] = generated_ids

    duplicate_ids = df.loc[
        df["item_id"].duplicated(keep=False), "item_id"
    ].tolist()
    if duplicate_ids:
        raise ValueError(
            "item_id dupliqués détectés : "
            + ", ".join(sorted(set(duplicate_ids))[:30])
        )

    return df, source_columns


# =============================================================================
# STRATIFIED SECOND-CHECK SAMPLING
# =============================================================================


def proportional_allocation(
    group_sizes: Dict[Tuple[str, str], int],
    target: int,
    rng: random.Random,
) -> Dict[Tuple[str, str], int]:
    """Allocate an exact target proportionally using the largest-remainder rule."""
    total = sum(group_sizes.values())
    if total <= 0 or target <= 0:
        return {key: 0 for key in group_sizes}

    quotas = {key: size * target / total for key, size in group_sizes.items()}
    allocations = {
        key: min(size, int(math.floor(quotas[key])))
        for key, size in group_sizes.items()
    }

    remaining = target - sum(allocations.values())
    candidates = list(group_sizes.keys())
    rng.shuffle(candidates)
    candidates.sort(
        key=lambda key: (quotas[key] - math.floor(quotas[key]), group_sizes[key]),
        reverse=True,
    )

    while remaining > 0:
        progressed = False
        for key in candidates:
            if allocations[key] < group_sizes[key]:
                allocations[key] += 1
                remaining -= 1
                progressed = True
                if remaining == 0:
                    break
        if not progressed:
            break

    return allocations


def select_second_check_sample(
    df: pd.DataFrame,
    double_check_percent: float,
    seed: int,
) -> List[int]:
    """
    Select a reproducible proportional sample stratified by Axe × Difficulty.

    The total sample size is exactly round(N × percentage), with at least one
    item when the requested percentage is above zero.
    """
    if not 0 <= double_check_percent <= 100:
        raise ValueError("--double-check-percent doit être compris entre 0 et 100.")

    n_items = len(df)
    if n_items == 0 or double_check_percent == 0:
        return []

    target = int(round(n_items * double_check_percent / 100.0))
    target = max(1, min(n_items, target))

    rng = random.Random(seed + 101)
    strata: Dict[Tuple[str, str], List[int]] = {}

    grouped = df.groupby(["Axe", "Difficulty"], dropna=False, sort=False)
    for (axis, difficulty), group in grouped:
        key = (str(axis), str(difficulty))
        indices = group.index.tolist()
        rng.shuffle(indices)
        strata[key] = indices

    allocations = proportional_allocation(
        {key: len(indices) for key, indices in strata.items()},
        target,
        rng,
    )

    sampled: List[int] = []
    for key, indices in strata.items():
        sampled.extend(indices[: allocations[key]])

    rng.shuffle(sampled)
    if len(sampled) != target:
        raise RuntimeError(
            f"Erreur interne d'échantillonnage : {len(sampled)} items sélectionnés "
            f"au lieu de {target}."
        )

    return sampled


# =============================================================================
# BALANCED REVIEWER ASSIGNMENT
# =============================================================================


def assign_items(
    df: pd.DataFrame,
    second_check_indices: Sequence[int],
    seed: int,
) -> Tuple[Dict[str, List[Tuple[int, str]]], pd.DataFrame]:
    """
    Assign one primary reviewer to every item and a distinct second reviewer to
    the stratified sample. Workload is balanced globally and by stratum.
    """
    rng = random.Random(seed)
    annotator_ids = list(ANNOTATORS)

    assignments: Dict[str, List[Tuple[int, str]]] = {
        annotator_id: [] for annotator_id in annotator_ids
    }
    total_load = Counter({ann: 0 for ann in annotator_ids})
    primary_load = Counter({ann: 0 for ann in annotator_ids})
    second_load = Counter({ann: 0 for ann in annotator_ids})
    axis_load: defaultdict[str, Counter] = defaultdict(Counter)
    stratum_load: defaultdict[Tuple[str, str], Counter] = defaultdict(Counter)
    primary_for_item: Dict[int, str] = {}
    manifest_rows: List[dict] = []

    # Primary assignment: grouped to spread each axis/difficulty across reviewers.
    strata = list(df.groupby(["Axe", "Difficulty"], dropna=False, sort=False).groups.items())
    rng.shuffle(strata)

    for (axis, difficulty), index_collection in strata:
        indices = list(index_collection)
        rng.shuffle(indices)
        stratum_key = (str(axis), str(difficulty))
        axis_key = str(axis)

        for idx in indices:
            excluded_creator: Optional[str] = None
            creator_raw: object = ""
            if CREATOR_COLUMN is not None:
                creator_raw = df.at[idx, CREATOR_COLUMN]
                excluded_creator = creator_to_annotator_id(creator_raw)

            candidates = [
                ann for ann in annotator_ids if ann != excluded_creator
            ]
            if not candidates:
                raise ValueError(
                    f"Aucun annotateur disponible pour l'item {df.at[idx, 'item_id']}."
                )

            rng.shuffle(candidates)

            def primary_score(ann: str) -> Tuple[float, ...]:
                return (
                    stratum_load[stratum_key][ann],
                    axis_load[axis_key][ann],
                    primary_load[ann],
                    total_load[ann],
                    rng.random(),
                )

            chosen = min(candidates, key=primary_score)
            primary_for_item[idx] = chosen
            assignments[chosen].append((idx, "primary"))
            total_load[chosen] += 1
            primary_load[chosen] += 1
            axis_load[axis_key][chosen] += 1
            stratum_load[stratum_key][chosen] += 1

            manifest_row = {
                "item_id": df.at[idx, "item_id"],
                "Axe": axis,
                "Difficulty": difficulty,
                "annotator_id": chosen,
                "review_round": "primary",
                "source_row": int(df.at[idx, "source_row"]),
                "primary_annotator_id": chosen,
            }
            if CREATOR_COLUMN is not None:
                manifest_row["original_creator"] = creator_raw
                manifest_row["creator_excluded"] = excluded_creator or "unresolved"
            manifest_rows.append(manifest_row)

    # Second-check assignment: distinct from primary and balanced.
    pair_count: Counter[Tuple[str, str]] = Counter()
    second_stratum_load: defaultdict[Tuple[str, str], Counter] = defaultdict(Counter)
    sampled_indices = list(second_check_indices)
    rng.shuffle(sampled_indices)

    for idx in sampled_indices:
        axis = df.at[idx, "Axe"]
        difficulty = df.at[idx, "Difficulty"]
        stratum_key = (str(axis), str(difficulty))
        primary = primary_for_item[idx]

        excluded_creator: Optional[str] = None
        creator_raw: object = ""
        if CREATOR_COLUMN is not None:
            creator_raw = df.at[idx, CREATOR_COLUMN]
            excluded_creator = creator_to_annotator_id(creator_raw)

        candidates = [
            ann
            for ann in annotator_ids
            if ann != primary and ann != excluded_creator
        ]
        if not candidates:
            raise ValueError(
                f"Aucun second évaluateur disponible pour l'item "
                f"{df.at[idx, 'item_id']}."
            )

        rng.shuffle(candidates)

        def second_score(ann: str) -> Tuple[float, ...]:
            pair = tuple(sorted((primary, ann)))
            return (
                second_stratum_load[stratum_key][ann],
                second_load[ann],
                total_load[ann],
                pair_count[pair],
                rng.random(),
            )

        chosen = min(candidates, key=second_score)
        pair = tuple(sorted((primary, chosen)))
        pair_count[pair] += 1

        assignments[chosen].append((idx, "second_check"))
        total_load[chosen] += 1
        second_load[chosen] += 1
        second_stratum_load[stratum_key][chosen] += 1

        manifest_row = {
            "item_id": df.at[idx, "item_id"],
            "Axe": axis,
            "Difficulty": difficulty,
            "annotator_id": chosen,
            "review_round": "second_check",
            "source_row": int(df.at[idx, "source_row"]),
            "primary_annotator_id": primary,
        }
        if CREATOR_COLUMN is not None:
            manifest_row["original_creator"] = creator_raw
            manifest_row["creator_excluded"] = excluded_creator or "unresolved"
        manifest_rows.append(manifest_row)

    manifest = pd.DataFrame(manifest_rows)

    expected_counts = pd.Series(1, index=df["item_id"])
    sampled_ids = set(df.loc[list(second_check_indices), "item_id"])
    expected_counts.loc[list(sampled_ids)] = 2
    actual_counts = manifest.groupby("item_id").size().reindex(df["item_id"], fill_value=0)
    invalid = actual_counts[actual_counts != expected_counts]
    if not invalid.empty:
        details = ", ".join(
            f"{item_id}: attendu={int(expected_counts[item_id])}, obtenu={int(count)}"
            for item_id, count in invalid.head(20).items()
        )
        raise RuntimeError("Erreur interne d'attribution : " + details)

    duplicate_reviewers = (
        manifest.groupby("item_id")["annotator_id"].nunique()
        < manifest.groupby("item_id").size()
    )
    if duplicate_reviewers.any():
        bad_ids = duplicate_reviewers[duplicate_reviewers].index.tolist()
        raise RuntimeError(
            "Un même annotateur a été attribué deux fois au même item : "
            + ", ".join(bad_ids[:20])
        )

    return assignments, manifest


# =============================================================================
# EXCEL STYLING HELPERS
# =============================================================================


HEADER_FILL = PatternFill("solid", fgColor="1F4E78")
HEADER_FONT = Font(color="FFFFFF", bold=True)
SECTION_FILL = PatternFill("solid", fgColor="D9EAF7")
SUBSECTION_FILL = PatternFill("solid", fgColor="EAF2F8")
GOOD_FILL = PatternFill("solid", fgColor="E2F0D9")
WARNING_FILL = PatternFill("solid", fgColor="FFF2CC")
BAD_FILL = PatternFill("solid", fgColor="F4CCCC")
INFO_FILL = PatternFill("solid", fgColor="EDEDED")
PRIMARY_FILL = PatternFill("solid", fgColor="DDEBF7")
SECOND_FILL = PatternFill("solid", fgColor="E4DFEC")
THIN_GRAY = Side(style="thin", color="B7B7B7")
TABLE_BORDER = Border(left=THIN_GRAY, right=THIN_GRAY, top=THIN_GRAY, bottom=THIN_GRAY)


def style_title(ws, cell_range: str, text: str) -> None:
    ws.merge_cells(cell_range)
    cell = ws[cell_range.split(":")[0]]
    cell.value = text
    cell.fill = HEADER_FILL
    cell.font = Font(color="FFFFFF", bold=True, size=15)
    cell.alignment = Alignment(horizontal="center", vertical="center")


def style_section_row(ws, row: int, text: str, end_column: int = 4) -> None:
    ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=end_column)
    cell = ws.cell(row=row, column=1, value=text)
    cell.fill = SECTION_FILL
    cell.font = Font(bold=True, size=12, color="1F1F1F")
    cell.alignment = Alignment(vertical="center")
    for column in range(1, end_column + 1):
        ws.cell(row=row, column=column).border = TABLE_BORDER


def write_table(
    ws,
    start_row: int,
    headers: Sequence[str],
    rows: Sequence[Sequence[object]],
    widths: Optional[Sequence[float]] = None,
) -> int:
    for col_idx, header in enumerate(headers, start=1):
        cell = ws.cell(row=start_row, column=col_idx, value=header)
        cell.fill = SUBSECTION_FILL
        cell.font = Font(bold=True)
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        cell.border = TABLE_BORDER

    for row_offset, values in enumerate(rows, start=1):
        row_idx = start_row + row_offset
        for col_idx, value in enumerate(values, start=1):
            cell = ws.cell(row=row_idx, column=col_idx, value=value)
            cell.alignment = Alignment(vertical="top", wrap_text=True)
            cell.border = TABLE_BORDER

    if widths:
        for col_idx, width in enumerate(widths, start=1):
            ws.column_dimensions[get_column_letter(col_idx)].width = width

    return start_row + len(rows) + 2


def add_legend_sheet(
    workbook_path: Path,
    annotator_id: str,
    double_check_percent: float,
) -> None:
    """Add a detailed and pedagogical guide to each annotator workbook."""
    wb = load_workbook(workbook_path)
    if LEGEND_SHEET_NAME in wb.sheetnames:
        del wb[LEGEND_SHEET_NAME]
    ws = wb.create_sheet(LEGEND_SHEET_NAME, 0)
    ws.sheet_view.showGridLines = False
    ws.freeze_panes = "A6"

    style_title(
        ws,
        "A1:D2",
        "Guide détaillé — Validation des réponses courtes",
    )
    ws.row_dimensions[1].height = 24
    ws.row_dimensions[2].height = 24

    ws["A4"] = "Identifiant de l'annotateur"
    ws["B4"] = annotator_id
    ws.merge_cells("B4:D4")
    for cell in ws[4]:
        cell.border = TABLE_BORDER
        cell.alignment = Alignment(vertical="center", wrap_text=True)
    ws["A4"].font = Font(bold=True)
    ws["A4"].fill = INFO_FILL

    row = 6
    style_section_row(ws, row, "1. Objectif de la validation")
    row += 1
    objective = (
        "Chaque ligne contient une question factuelle courte (`input`) et une réponse "
        "de référence candidate (`answer`). Votre rôle est de vérifier que la question "
        "est utilisable, que la réponse est correcte et que les principales variantes "
        "acceptables sont enregistrées. Tous les items reçoivent une revue primaire. "
        f"Un échantillon stratifié d'environ {double_check_percent:g} % reçoit en plus "
        "une seconde revue indépendante afin de mesurer l'accord inter-annotateurs."
    )
    ws.merge_cells(start_row=row, start_column=1, end_row=row + 2, end_column=4)
    ws.cell(row=row, column=1, value=objective)
    ws.cell(row=row, column=1).alignment = Alignment(vertical="top", wrap_text=True)
    for r in range(row, row + 3):
        for c in range(1, 5):
            ws.cell(r, c).border = TABLE_BORDER
    row += 4

    style_section_row(ws, row, "2. Comprendre `review_round`")
    row += 1
    round_rows = [
        (
            "primary",
            "Vous êtes l'évaluateur principal de cet item. Vérifiez la réponse et fournissez une source fiable.",
        ),
        (
            "second_check",
            "L'item appartient à l'échantillon de fiabilité. Évaluez-le de manière totalement indépendante, sans chercher ni demander le jugement du premier annotateur.",
        ),
        (
            "Règle identique",
            "Les mêmes critères et la même exigence de rigueur s'appliquent aux deux rounds. `second_check` ne signifie pas une revue plus rapide ou superficielle.",
        ),
    ]
    row = write_table(ws, row, ["Valeur", "Signification"], round_rows, [24, 98])

    style_section_row(ws, row, "3. Procédure à suivre pour chaque ligne")
    row += 1
    procedure_rows = [
        ("1", "Lire la question (`input`) et identifier exactement l'information demandée."),
        ("2", "Lire la réponse candidate (`answer`) sans modifier les colonnes sources."),
        ("3", "Vérifier le fait dans une source fiable : source officielle, institutionnelle, académique, ouvrage reconnu ou référence historique solide."),
        ("4", "Choisir une valeur pour `answer_correctness`."),
        ("5", "Choisir `ok` ou `review` dans `question_quality`."),
        ("6", "Ajouter dans `accepted_variants` les autres formes réellement correctes qui devraient être acceptées lors de l'évaluation automatique ou humaine."),
        ("7", "Renseigner `supporting_source` pour documenter votre vérification."),
        ("8", "Écrire un commentaire précis lorsqu'une correction ou une revue est nécessaire."),
        ("9", "Ne jamais modifier `item_id`, `input`, `answer`, `Axe`, `Difficulty`, `intent_group` ou `intent_category`."),
        ("10", "Ne pas consulter les autres annotateurs avant la consolidation. L'indépendance des jugements est nécessaire pour calculer l'accord."),
    ]
    row = write_table(ws, row, ["Étape", "Instruction"], procedure_rows, [12, 110])

    style_section_row(ws, row, "4. Colonne `answer_correctness`")
    row += 1
    correctness_rows = [
        (
            "correct",
            "La réponse répond correctement à la question et peut rester telle quelle.",
            "Une autre formulation possible ne rend pas la réponse actuelle incorrecte : ajoutez simplement cette formulation dans `accepted_variants`.",
        ),
        (
            "minor_fix",
            "Le noyau de la réponse est correct, mais une petite correction est nécessaire.",
            "Exemples : orthographe d'un nom, précision de date, qualificatif essentiel manquant, réponse légèrement trop vague ou translittération à normaliser.",
        ),
        (
            "incorrect",
            "La réponse est factuellement fausse, répond à autre chose ou nécessite un remplacement substantiel.",
            "Indiquez la bonne réponse ou la correction attendue dans `review_comment` et fournissez la source.",
        ),
    ]
    row = write_table(
        ws,
        row,
        ["Valeur", "Quand l'utiliser", "Règle pratique"],
        correctness_rows,
        [20, 50, 58],
    )

    style_section_row(ws, row, "5. Colonne `question_quality`")
    row += 1
    quality_rows = [
        (
            "ok",
            "La question est claire, répondable, suffisamment précise et repose sur une prémisse factuelle valide.",
        ),
        (
            "review",
            "La question est ambiguë, contient une prémisse erronée, accepte plusieurs réponses substantiellement différentes sans le préciser, est trop large pour une réponse courte ou comporte un problème linguistique sérieux.",
        ),
        (
            "Important",
            "Ne choisissez pas `review` uniquement parce que vous auriez formulé la question différemment. Il faut un problème réel qui affecte sa compréhension, sa validité ou son évaluation.",
        ),
    ]
    row = write_table(ws, row, ["Valeur", "Quand l'utiliser"], quality_rows, [24, 104])

    style_section_row(ws, row, "6. Colonne `accepted_variants`")
    row += 1
    variants_rows = [
        (
            "Objectif",
            "Réduire les faux négatifs : un modèle peut donner une réponse correcte avec une autre graphie, langue, translittération, forme longue ou format de date.",
        ),
        (
            "Séparateur",
            "Séparez les variantes par le symbole `|`.",
        ),
        (
            "Exemple — lieu",
            "وليلي | Volubilis | وَلِيلِي",
        ),
        (
            "Exemple — événement",
            "حرب يوغرطة | الحرب اليوغرطية | Jugurthine War",
        ),
        (
            "Exemple — date",
            "682 م | سنة 682 ميلادية | 682 CE, uniquement si ces formes expriment exactement la même réponse attendue.",
        ),
        (
            "À inclure",
            "Graphies reconnues, noms arabes/français usuels, forme complète et abrégée standard, translittérations correctes, synonymes strictement équivalents et formats de date équivalents.",
        ),
        (
            "À ne pas inclure",
            "Réponses approximatives, termes seulement associés au sujet, variantes factuellement discutables, réponses plus larges qui pourraient masquer une erreur ou formulations qui changent la granularité demandée.",
        ),
        (
            "Aucune variante",
            "Laissez la cellule vide lorsqu'aucune variante supplémentaire utile n'est nécessaire.",
        ),
    ]
    row = write_table(ws, row, ["Rubrique", "Consigne / exemple"], variants_rows, [28, 100])

    style_section_row(ws, row, "7. Colonne `supporting_source`")
    row += 1
    source_rows = [
        (
            "Règle générale",
            "Une source doit être renseignée pour chaque item, car ce dataset est traité comme documentaire.",
        ),
        (
            "Sources recommandées",
            "Site officiel, texte juridique, institution publique, publication académique, ouvrage reconnu, archive, musée, université ou encyclopédie de référence.",
        ),
        (
            "Format conseillé",
            "Titre de la source — institution/auteur — URL ou référence bibliographique.",
        ),
        (
            "Second contrôle",
            "Vérifiez vous-même l'information. Vous pouvez citer la même source si elle est solide et que vous l'avez réellement consultée, ou fournir une autre source indépendante.",
        ),
        (
            "À éviter",
            "Écrire seulement `Google`, `Internet`, `ChatGPT` ou une référence impossible à retrouver. Un moteur de recherche n'est pas une source.",
        ),
        (
            "Sources contradictoires",
            "Choisissez `question_quality = review` ou `answer_correctness = minor_fix/incorrect` selon le cas, puis expliquez brièvement le désaccord dans `review_comment`.",
        ),
    ]
    row = write_table(ws, row, ["Rubrique", "Consigne"], source_rows, [28, 100])

    style_section_row(ws, row, "8. Colonne `review_comment`")
    row += 1
    comment_rows = [
        (
            "Quand est-il obligatoire ?",
            "Lorsque `answer_correctness` vaut `minor_fix` ou `incorrect`, ou lorsque `question_quality` vaut `review`.",
        ),
        (
            "Bon commentaire",
            "« La réponse est globalement correcte, mais la date doit être formulée comme une période approximative selon la source. »",
        ),
        (
            "Bon commentaire",
            "« La question attend une seule conséquence alors que plusieurs réponses historiques sont défendables ; préciser la conséquence visée. »",
        ),
        (
            "Bon commentaire",
            "« La réponse proposée est incorrecte. La réponse vérifiée est : … »",
        ),
        (
            "Mauvais commentaire",
            "`À revoir`, `pas bon` ou `faux` sans explication : ces commentaires ne permettent pas l'arbitrage.",
        ),
        (
            "Quand peut-il rester vide ?",
            "Lorsque la réponse est `correct`, la question est `ok` et aucune explication supplémentaire n'est utile.",
        ),
    ]
    row = write_table(ws, row, ["Rubrique", "Consigne / exemple"], comment_rows, [28, 100])

    style_section_row(ws, row, "9. Exemples proches de vos données")
    row += 1
    example_rows = [
        (
            "Question claire, réponse exacte",
            "correct",
            "ok",
            "Ajouter seulement les variantes de graphie utiles.",
        ),
        (
            "La réponse donne le bon personnage mais avec une orthographe mineure à corriger",
            "minor_fix",
            "ok",
            "Indiquer la graphie correcte dans le commentaire.",
        ),
        (
            "La question contient une date erronée dans sa prémisse, même si l'answer semble plausible",
            "à juger selon la réponse",
            "review",
            "Expliquer la prémisse incorrecte et citer la source.",
        ),
        (
            "Plusieurs noms strictement équivalents sont acceptables",
            "correct",
            "ok",
            "Les enregistrer dans `accepted_variants`, sans pénaliser la réponse actuelle.",
        ),
        (
            "Plusieurs réponses historiques différentes peuvent être défendues parce que la question est trop large",
            "selon le cas",
            "review",
            "La question doit être précisée ou déplacée vers les questions ouvertes.",
        ),
        (
            "La réponse contredit une source fiable sur un élément central",
            "incorrect",
            "ok ou review selon la question",
            "Écrire la correction et la source dans le commentaire.",
        ),
    ]
    row = write_table(
        ws,
        row,
        ["Situation", "answer_correctness", "question_quality", "Action"],
        example_rows,
        [48, 24, 22, 54],
    )

    style_section_row(ws, row, "10. Distinctions importantes")
    row += 1
    distinction_rows = [
        (
            "Réponse incorrecte vs question à revoir",
            "Une réponse peut être fausse alors que la question est très bonne. Inversement, la réponse peut correspondre à l'intention de l'auteur mais la question être ambiguë ou fondée sur une prémisse problématique.",
        ),
        (
            "Variante acceptable vs correction",
            "Une variante est une autre réponse également correcte. Une correction remplace ou modifie une réponse actuelle qui est insuffisante ou fausse.",
        ),
        (
            "Formulation différente vs problème réel",
            "Ne signalez pas un item uniquement parce que vous préférez une autre tournure. Signalez-le lorsque la formulation affecte réellement la compréhension ou la validité.",
        ),
        (
            "Réponse courte vs réponse incomplète",
            "Une réponse d'un seul mot peut être parfaitement suffisante si la question demande un nom. La longueur seule ne détermine pas la qualité.",
        ),
    ]
    row = write_table(ws, row, ["Distinction", "Explication"], distinction_rows, [34, 94])

    style_section_row(ws, row, "11. Liste de contrôle avant de terminer")
    row += 1
    checklist_rows = [
        ("✓", "Toutes les cellules `answer_correctness` sont remplies avec une valeur de la liste."),
        ("✓", "Toutes les cellules `question_quality` sont remplies."),
        ("✓", "Chaque item possède une source vérifiable."),
        ("✓", "Les variantes sont séparées par `|` et sont réellement équivalentes."),
        ("✓", "Tout `minor_fix`, `incorrect` ou `review` est expliqué dans `review_comment`."),
        ("✓", "Aucune colonne source n'a été modifiée."),
        ("✓", "Les items `second_check` ont été évalués indépendamment."),
    ]
    row = write_table(ws, row, ["", "Vérification"], checklist_rows, [8, 120])

    style_section_row(ws, row, "12. Rappel final")
    row += 1
    reminder = (
        "Le but n'est pas de rendre chaque item plus long ou plus sophistiqué. Le but est "
        "de garantir qu'une question courte possède une réponse fiable, vérifiable et "
        "évaluable, avec suffisamment de variantes acceptées pour ne pas pénaliser une "
        "réponse correcte uniquement à cause de sa graphie ou de sa langue."
    )
    ws.merge_cells(start_row=row, start_column=1, end_row=row + 2, end_column=4)
    ws.cell(row=row, column=1, value=reminder)
    ws.cell(row=row, column=1).fill = WARNING_FILL
    ws.cell(row=row, column=1).font = Font(bold=True)
    ws.cell(row=row, column=1).alignment = Alignment(vertical="top", wrap_text=True)
    for r in range(row, row + 3):
        for c in range(1, 5):
            ws.cell(r, c).border = TABLE_BORDER

    ws.column_dimensions["A"].width = max(ws.column_dimensions["A"].width or 0, 26)
    ws.column_dimensions["B"].width = max(ws.column_dimensions["B"].width or 0, 60)
    ws.column_dimensions["C"].width = max(ws.column_dimensions["C"].width or 0, 34)
    ws.column_dimensions["D"].width = max(ws.column_dimensions["D"].width or 0, 42)
    for row_cells in ws.iter_rows():
        for cell in row_cells:
            cell.alignment = Alignment(
                horizontal=cell.alignment.horizontal,
                vertical="top",
                wrap_text=True,
            )

    wb.save(workbook_path)


def format_annotation_workbook(workbook_path: Path) -> None:
    wb = load_workbook(workbook_path)
    ws = wb[ANNOTATION_SHEET_NAME]
    ws.sheet_view.showGridLines = False
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = ws.dimensions
    ws.row_dimensions[1].height = 42

    header_to_col = {cell.value: cell.column for cell in ws[1]}
    for cell in ws[1]:
        cell.fill = HEADER_FILL
        cell.font = HEADER_FONT
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        cell.border = TABLE_BORDER

    preferred_widths = {
        "item_id": 15,
        "Axe": 27,
        "Difficulty": 13,
        "intent_group": 30,
        "intent_category": 32,
        "input": 66,
        "answer": 36,
        "annotator_id": 14,
        "review_round": 17,
        "answer_correctness": 22,
        "question_quality": 19,
        "accepted_variants": 50,
        "supporting_source": 56,
        "review_comment": 58,
    }

    for header, column_index in header_to_col.items():
        ws.column_dimensions[get_column_letter(column_index)].width = preferred_widths.get(
            str(header), 20
        )

    first_annotation_col = min(header_to_col[column] for column in ANNOTATION_COLUMNS)
    round_col = header_to_col["review_round"]

    for row in ws.iter_rows(min_row=2):
        for cell in row:
            cell.alignment = Alignment(vertical="top", wrap_text=True)
            cell.border = TABLE_BORDER
            if cell.column < first_annotation_col:
                cell.fill = PatternFill("solid", fgColor="F2F2F2")

        round_value = str(ws.cell(row=row[0].row, column=round_col).value or "")
        ws.cell(row=row[0].row, column=round_col).fill = (
            PRIMARY_FILL if round_value == "primary" else SECOND_FILL
        )
        ws.cell(row=row[0].row, column=round_col).font = Font(bold=True)

    last_row = max(ws.max_row, 2)

    dv_correctness = DataValidation(
        type="list",
        formula1='"correct,minor_fix,incorrect"',
        allow_blank=False,
    )
    dv_quality = DataValidation(
        type="list",
        formula1='"ok,review"',
        allow_blank=False,
    )
    dv_correctness.error = "Choisissez correct, minor_fix ou incorrect."
    dv_correctness.errorTitle = "Valeur invalide"
    dv_correctness.prompt = "Consultez la feuille LEGEND avant de noter."
    dv_correctness.promptTitle = "Validation de la réponse"
    dv_correctness.showErrorMessage = True
    dv_correctness.showInputMessage = True

    dv_quality.error = "Choisissez ok ou review."
    dv_quality.errorTitle = "Valeur invalide"
    dv_quality.prompt = "Signalez uniquement un problème réel de question."
    dv_quality.promptTitle = "Qualité de la question"
    dv_quality.showErrorMessage = True
    dv_quality.showInputMessage = True

    ws.add_data_validation(dv_correctness)
    ws.add_data_validation(dv_quality)

    correctness_letter = get_column_letter(header_to_col["answer_correctness"])
    quality_letter = get_column_letter(header_to_col["question_quality"])
    source_letter = get_column_letter(header_to_col["supporting_source"])
    comment_letter = get_column_letter(header_to_col["review_comment"])

    dv_correctness.add(f"{correctness_letter}2:{correctness_letter}{last_row}")
    dv_quality.add(f"{quality_letter}2:{quality_letter}{last_row}")

    ws.conditional_formatting.add(
        f"{correctness_letter}2:{correctness_letter}{last_row}",
        FormulaRule(formula=[f'{correctness_letter}2="correct"'], fill=GOOD_FILL),
    )
    ws.conditional_formatting.add(
        f"{correctness_letter}2:{correctness_letter}{last_row}",
        FormulaRule(formula=[f'{correctness_letter}2="minor_fix"'], fill=WARNING_FILL),
    )
    ws.conditional_formatting.add(
        f"{correctness_letter}2:{correctness_letter}{last_row}",
        FormulaRule(formula=[f'{correctness_letter}2="incorrect"'], fill=BAD_FILL),
    )
    ws.conditional_formatting.add(
        f"{quality_letter}2:{quality_letter}{last_row}",
        FormulaRule(formula=[f'{quality_letter}2="ok"'], fill=GOOD_FILL),
    )
    ws.conditional_formatting.add(
        f"{quality_letter}2:{quality_letter}{last_row}",
        FormulaRule(formula=[f'{quality_letter}2="review"'], fill=WARNING_FILL),
    )

    # Source is mandatory for every documented item.
    ws.conditional_formatting.add(
        f"{source_letter}2:{source_letter}{last_row}",
        FormulaRule(formula=[f'={source_letter}2=""'], fill=BAD_FILL),
    )

    # Comment is required when the answer/question has been flagged.
    missing_comment_formula = (
        f'=AND(${comment_letter}2="",OR('
        f'${correctness_letter}2="minor_fix",'
        f'${correctness_letter}2="incorrect",'
        f'${quality_letter}2="review"))'
    )
    ws.conditional_formatting.add(
        f"{comment_letter}2:{comment_letter}{last_row}",
        FormulaRule(formula=[missing_comment_formula], fill=BAD_FILL),
    )

    wb.save(workbook_path)


# =============================================================================
# OUTPUT FILES
# =============================================================================


def create_annotator_files(
    df: pd.DataFrame,
    source_columns: List[str],
    assignments: Dict[str, List[Tuple[int, str]]],
    annotators_dir: Path,
    double_check_percent: float,
    seed: int,
) -> None:
    annotators_dir.mkdir(parents=True, exist_ok=True)
    rng = random.Random(seed + 1)

    for annotator_id in ANNOTATORS:
        assigned = assignments[annotator_id][:]
        rng.shuffle(assigned)

        rows: List[pd.Series] = []
        rounds: List[str] = []
        for idx, review_round in assigned:
            rows.append(df.loc[idx, source_columns])
            rounds.append(review_round)

        if rows:
            out = pd.DataFrame(rows).reset_index(drop=True)
        else:
            out = pd.DataFrame(columns=source_columns)

        out["annotator_id"] = annotator_id
        out["review_round"] = rounds
        out["answer_correctness"] = ""
        out["question_quality"] = ""
        out["accepted_variants"] = ""
        out["supporting_source"] = ""
        out["review_comment"] = ""
        out = out[source_columns + ANNOTATION_COLUMNS]

        filename = f"{annotator_id}.xlsx"
        output_path = annotators_dir / filename
        out.to_excel(output_path, index=False, sheet_name=ANNOTATION_SHEET_NAME)
        format_annotation_workbook(output_path)
        add_legend_sheet(
            output_path,
            annotator_id,
            double_check_percent,
        )


def format_simple_sheet(workbook_path: Path, sheet_name: str) -> None:
    wb = load_workbook(workbook_path)
    ws = wb[sheet_name]
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = ws.dimensions
    ws.sheet_view.showGridLines = False

    for cell in ws[1]:
        cell.fill = HEADER_FILL
        cell.font = HEADER_FONT
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        cell.border = TABLE_BORDER

    for row in ws.iter_rows(min_row=2):
        for cell in row:
            cell.alignment = Alignment(vertical="top", wrap_text=True)
            cell.border = TABLE_BORDER

    for col_idx, column_cells in enumerate(ws.columns, start=1):
        max_len = max(
            (len(str(cell.value)) for cell in column_cells if cell.value is not None),
            default=10,
        )
        ws.column_dimensions[get_column_letter(col_idx)].width = min(max(max_len + 2, 12), 52)

    wb.save(workbook_path)


def write_admin_codebook(admin_dir: Path, double_check_percent: float) -> None:
    path = admin_dir / "annotation_codebook.xlsx"
    wb = Workbook()
    ws = wb.active
    ws.title = "PLACEHOLDER"
    wb.save(path)

    add_legend_sheet(
        path,
        "ADMIN",
        double_check_percent,
    )
    wb = load_workbook(path)
    if "PLACEHOLDER" in wb.sheetnames:
        del wb["PLACEHOLDER"]
    wb.save(path)


def write_admin_files(
    df: pd.DataFrame,
    source_columns: List[str],
    manifest: pd.DataFrame,
    second_check_indices: Sequence[int],
    admin_dir: Path,
    double_check_percent: float,
) -> None:
    admin_dir.mkdir(parents=True, exist_ok=True)

    gold = df[source_columns + ["source_row"]].copy()
    gold_path = admin_dir / "gold_reference.xlsx"
    gold.to_excel(gold_path, index=False, sheet_name="GOLD")
    format_simple_sheet(gold_path, "GOLD")

    manifest = manifest.sort_values(
        ["annotator_id", "review_round", "Axe", "Difficulty", "item_id"]
    ).reset_index(drop=True)
    manifest_path = admin_dir / "assignment_manifest.xlsx"
    manifest.to_excel(manifest_path, index=False, sheet_name="ASSIGNMENTS")
    format_simple_sheet(manifest_path, "ASSIGNMENTS")

    sampled = df.loc[list(second_check_indices), [
        "item_id", "Axe", "Difficulty", "intent_group", "intent_category", "source_row"
    ]].copy()
    sampled["double_check_selected"] = "yes"
    sampled_path = admin_dir / "double_check_sample.xlsx"
    sampled.to_excel(sampled_path, index=False, sheet_name="SAMPLE")
    format_simple_sheet(sampled_path, "SAMPLE")

    by_annotator = (
        manifest.pivot_table(
            index=["annotator_id"],
            columns="review_round",
            values="item_id",
            aggfunc="count",
            fill_value=0,
        )
        .reset_index()
    )
    for column in REVIEW_ROUNDS:
        if column not in by_annotator.columns:
            by_annotator[column] = 0
    by_annotator["total_judgments"] = (
        by_annotator["primary"] + by_annotator["second_check"]
    )

    by_axis = (
        manifest.pivot_table(
            index=["annotator_id", "review_round"],
            columns="Axe",
            values="item_id",
            aggfunc="count",
            fill_value=0,
        )
        .reset_index()
    )

    by_difficulty = (
        manifest.pivot_table(
            index=["annotator_id", "review_round"],
            columns="Difficulty",
            values="item_id",
            aggfunc="count",
            fill_value=0,
        )
        .reset_index()
    )

    dataset_strata = (
        df.groupby(["Axe", "Difficulty"], dropna=False, as_index=False)
        .agg(total_items=("item_id", "count"))
    )
    sample_strata = (
        df.loc[list(second_check_indices)]
        .groupby(["Axe", "Difficulty"], dropna=False, as_index=False)
        .agg(double_checked_items=("item_id", "count"))
    )
    by_stratum = dataset_strata.merge(
        sample_strata,
        on=["Axe", "Difficulty"],
        how="left",
    )
    by_stratum["double_checked_items"] = (
        by_stratum["double_checked_items"].fillna(0).astype(int)
    )
    by_stratum["realized_percentage"] = (
        by_stratum["double_checked_items"] / by_stratum["total_items"] * 100
    ).round(2)

    second_manifest = manifest[manifest["review_round"] == "second_check"].copy()
    if not second_manifest.empty:
        second_manifest["reviewer_pair"] = second_manifest.apply(
            lambda row: " + ".join(
                sorted([str(row["primary_annotator_id"]), str(row["annotator_id"])])
            ),
            axis=1,
        )
        pair_summary = (
            second_manifest.groupby("reviewer_pair", as_index=False)
            .agg(number_of_shared_items=("item_id", "count"))
            .sort_values("number_of_shared_items", ascending=False)
        )
    else:
        pair_summary = pd.DataFrame(
            columns=["reviewer_pair", "number_of_shared_items"]
        )

    overview = pd.DataFrame(
        [
            ("sheet_name", SHEET_NAME),
            ("total_items", len(df)),
            ("requested_double_check_percent", double_check_percent),
            ("double_checked_items", len(second_check_indices)),
            (
                "realized_double_check_percent",
                round(len(second_check_indices) / len(df) * 100, 2) if len(df) else 0,
            ),
            ("total_judgments", len(manifest)),
            ("number_of_annotators", len(ANNOTATORS)),
        ],
        columns=["metric", "value"],
    )

    summary_path = admin_dir / "allocation_summary.xlsx"
    with pd.ExcelWriter(summary_path, engine="openpyxl") as writer:
        overview.to_excel(writer, index=False, sheet_name="OVERVIEW")
        by_annotator.to_excel(writer, index=False, sheet_name="BY_ANNOTATOR")
        by_axis.to_excel(writer, index=False, sheet_name="BY_AXIS")
        by_difficulty.to_excel(writer, index=False, sheet_name="BY_DIFFICULTY")
        by_stratum.to_excel(writer, index=False, sheet_name="BY_STRATUM")
        pair_summary.to_excel(writer, index=False, sheet_name="BY_REVIEWER_PAIR")

    for sheet_name in [
        "OVERVIEW",
        "BY_ANNOTATOR",
        "BY_AXIS",
        "BY_DIFFICULTY",
        "BY_STRATUM",
        "BY_REVIEWER_PAIR",
    ]:
        format_simple_sheet(summary_path, sheet_name)

    write_admin_codebook(admin_dir, double_check_percent)


def write_readme(
    output_dir: Path,
    number_of_items: int,
    number_of_double_checked_items: int,
    total_judgments: int,
    double_check_percent: float,
) -> None:
    creator_note = (
        f"Auto-évaluation exclue à partir de la colonne '{CREATOR_COLUMN}'."
        if CREATOR_COLUMN
        else (
            "Aucune colonne de créateur n'est configurée : le script équilibre les "
            "attributions mais ne peut pas identifier l'auteur initial d'un item."
        )
    )

    realized = (
        number_of_double_checked_items / number_of_items * 100
        if number_of_items
        else 0
    )

    content = f"""VALIDATION DES RÉPONSES COURTES

Source attendue : feuille '{SHEET_NAME}'
Nombre total d'items : {number_of_items}
Revue primaire : 100 % des items
Pourcentage demandé en second contrôle : {double_check_percent:g} %
Items effectivement double-contrôlés : {number_of_double_checked_items} ({realized:.2f} %)
Nombre total de jugements : {total_judgments}
Nombre d'annotateurs : {len(ANNOTATORS)}

Structure créée :
- annotateurs/ : un fichier Excel par annotateur, avec une feuille LEGEND détaillée.
- admin/gold_reference.xlsx : copie de référence de toutes les colonnes sources.
- admin/assignment_manifest.xlsx : détail de chaque attribution primaire et secondaire.
- admin/double_check_sample.xlsx : liste exacte des items sélectionnés pour la fiabilité.
- admin/allocation_summary.xlsx : charge par annotateur, axe, difficulté et strate.
- admin/annotation_codebook.xlsx : copie administrative du guide.

Méthode :
- Tous les items sont traités comme documentés.
- Chaque item reçoit un reviewer primaire.
- Un échantillon reproductible est sélectionné proportionnellement par Axe × Difficulty.
- Chaque item de l'échantillon reçoit un second reviewer différent du premier.
- Le tirage est reproductible grâce à la graine aléatoire configurée.

Colonnes d'évaluation :
- answer_correctness : correct / minor_fix / incorrect
- question_quality : ok / review
- accepted_variants : variantes correctes séparées par |
- supporting_source : source vérifiable
- review_comment : obligatoire en cas de problème

{creator_note}
"""
    (output_dir / "README.txt").write_text(content, encoding="utf-8")


# =============================================================================
# MAIN
# =============================================================================


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Répartit la feuille 'Short answer' entre 9 annotateurs : "
            "100 % en revue primaire et un échantillon stratifié en second contrôle."
        )
    )
    parser.add_argument(
        "input_file",
        type=Path,
        help="Chemin du fichier Excel source.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("short_answers_annotation_output"),
        help="Dossier de sortie (défaut : short_answers_annotation_output).",
    )
    parser.add_argument(
        "--double-check-percent",
        type=float,
        default=DEFAULT_DOUBLE_CHECK_PERCENT,
        help=(
            "Pourcentage d'items sélectionnés pour un second contrôle indépendant "
            f"(défaut : {DEFAULT_DOUBLE_CHECK_PERCENT:g})."
        ),
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=DEFAULT_RANDOM_SEED,
        help=(
            "Graine aléatoire pour rendre l'échantillon et la répartition "
            f"reproductibles (défaut : {DEFAULT_RANDOM_SEED})."
        ),
    )
    args = parser.parse_args()

    input_file = args.input_file.expanduser().resolve()
    output_dir = args.output_dir.expanduser().resolve()
    annotators_dir = output_dir / "annotateurs"
    admin_dir = output_dir / "admin"

    if not input_file.exists():
        raise FileNotFoundError(f"Fichier introuvable : {input_file}")

    if not 0 <= args.double_check_percent <= 100:
        raise ValueError("--double-check-percent doit être compris entre 0 et 100.")

    df, source_columns = prepare_dataframe(input_file)
    second_check_indices = select_second_check_sample(
        df,
        args.double_check_percent,
        args.seed,
    )
    assignments, manifest = assign_items(
        df,
        second_check_indices,
        args.seed,
    )

    create_annotator_files(
        df,
        source_columns,
        assignments,
        annotators_dir,
        args.double_check_percent,
        args.seed,
    )
    write_admin_files(
        df,
        source_columns,
        manifest,
        second_check_indices,
        admin_dir,
        args.double_check_percent,
    )
    write_readme(
        output_dir,
        len(df),
        len(second_check_indices),
        len(manifest),
        args.double_check_percent,
    )

    print("=" * 84)
    print("Répartition des réponses courtes terminée.")
    print(f"Source                         : {input_file}")
    print(f"Feuille                        : {SHEET_NAME}")
    print(f"Dossier de sortie              : {output_dir}")
    print(f"Nombre total d'items           : {len(df)}")
    print(f"Items en revue primaire        : {len(df)}")
    print(f"Items en second contrôle       : {len(second_check_indices)}")
    print(f"Pourcentage demandé            : {args.double_check_percent:g} %")
    realized = len(second_check_indices) / len(df) * 100 if len(df) else 0
    print(f"Pourcentage effectivement tiré : {realized:.2f} %")
    print(f"Jugements attendus             : {len(manifest)}")
    print(f"Annotateurs                    : {len(ANNOTATORS)}")
    print(f"Graine aléatoire               : {args.seed}")
    print("=" * 84)

    load_summary = (
        manifest.pivot_table(
            index=["annotator_id"],
            columns="review_round",
            values="item_id",
            aggfunc="count",
            fill_value=0,
        )
        .reset_index()
    )
    for column in REVIEW_ROUNDS:
        if column not in load_summary.columns:
            load_summary[column] = 0
    load_summary["total"] = (
        load_summary["primary"] + load_summary["second_check"]
    )
    print(load_summary.to_string(index=False))

    if CREATOR_COLUMN is None:
        print("\nNOTE : aucune colonne de créateur n'est configurée.")
        print(
            "Le script ne peut donc pas empêcher l'auteur initial d'évaluer son "
            "propre item. Pour l'activer, renseignez CREATOR_COLUMN en haut du script."
        )


if __name__ == "__main__":
    main()
