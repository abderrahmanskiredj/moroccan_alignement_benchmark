from __future__ import annotations

import argparse
import itertools
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

SHEET_NAME = "Open Question"
ANNOTATION_SHEET_NAME = "OPEN_ANNOTATION"
LEGEND_SHEET_NAME = "LEGEND"
RANDOM_SEED = 20260726

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
    "ANN_10",
]

# Facultatif : si le fichier source contient une colonne indiquant la personne
# qui a créé chaque item, écrire ici son nom exact afin d'empêcher l'auto-revue.
# Exemples : "author_name", "creator", "created_by".
# Laisser None si cette information n'existe pas dans le fichier.
CREATOR_COLUMN: Optional[str] = None

# Facultatif : renseigner les régions afin de favoriser deux évaluateurs de
# régions différentes. Si rien n'est renseigné, cette contrainte est ignorée.
ANNOTATOR_REGIONS: Dict[str, str] = {
    # "ANN_01": "Rabat-Salé-Kénitra",
    # "ANN_02": "Souss-Massa",
}

REQUIRED_COLUMNS = [
    "Axe",
    "Difficulty",
    "intent_group",
    "intent_category",
    "input",
    "Answer_chatgpt_corrected",
    "item_id",
]

ANNOTATION_COLUMNS = [
    "annotator_id",
    "linguistic_quality",
    "answer_relevance",
    "answer_completeness",
    "factual_precision",
    "safety_alignment",
    "review_comment",
    "supporting_source",
]

RESERVED_COLUMNS = set(ANNOTATION_COLUMNS + ["source_row"])

THREE_LEVEL_VALUES = ["no_issue", "minor_issue", "major_issue"]
SAFETY_VALUES = ["safe", "needs_review", "unsafe"]


# =============================================================================
# TEXT AND FILE UTILITIES
# =============================================================================


def normalize_text(value: object) -> str:
    """Normalize text for robust comparisons without changing source data."""
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
    """Resolve a creator value to one of the configured annotator IDs."""
    if not has_value(value):
        return None

    normalized = normalize_text(value)
    for annotator_id in ANNOTATORS:
        if normalized == normalize_text(annotator_id):
            return annotator_id
    return None


def different_regions(ann1: str, ann2: str) -> bool:
    r1 = ANNOTATOR_REGIONS.get(ann1, "").strip()
    r2 = ANNOTATOR_REGIONS.get(ann2, "").strip()
    if not r1 or not r2:
        return True
    return normalize_text(r1) != normalize_text(r2)


# =============================================================================
# INPUT PREPARATION AND VALIDATION
# =============================================================================


def prepare_dataframe(input_file: Path) -> Tuple[pd.DataFrame, List[str]]:
    """
    Read and validate the 'Open Question' sheet.

    All meaningful source columns are preserved. Fully empty Excel columns such
    as trailing 'Unnamed:' columns are removed. Rows that contain no actual item
    content are ignored even when formatting exists below the table.
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

    # Remove only fully empty technical columns created by Excel formatting.
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

    # An item is considered meaningful when at least one central field is filled.
    item_core_columns = ["Axe", "input", "Answer_chatgpt_corrected", "item_id"]
    meaningful_mask = df[item_core_columns].apply(
        lambda column: column.map(has_value)
    ).any(axis=1)

    df = df.loc[meaningful_mask].copy()
    df["source_row"] = original_excel_rows.loc[df.index].astype(int)
    df = df.reset_index(drop=True)

    if df.empty:
        raise ValueError(f"La feuille '{SHEET_NAME}' ne contient aucun item exploitable.")

    source_columns = [column for column in df.columns if column != "source_row"]

    # Validate central fields so incomplete items are not silently distributed.
    field_errors: List[str] = []
    for idx, row in df.iterrows():
        excel_row = int(row["source_row"])
        for column in ["Axe", "input", "Answer_chatgpt_corrected"]:
            if not has_value(row[column]):
                field_errors.append(f"ligne Excel {excel_row}: '{column}' vide")

    if field_errors:
        raise ValueError(
            "Items incomplets détectés :\n- " + "\n- ".join(field_errors[:50])
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

        while f"OPEN_{next_number:04d}" in existing_ids:
            next_number += 1
        new_id = f"OPEN_{next_number:04d}"
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
# BALANCED DOUBLE ASSIGNMENT
# =============================================================================


def assign_items(df: pd.DataFrame) -> Tuple[Dict[str, List[int]], pd.DataFrame]:
    """
    Assign every item to exactly two distinct reviewers.

    The heuristic balances total workload, workload per Axe, and pair repetition.
    When CREATOR_COLUMN is configured and resolvable, the original creator is
    excluded from the candidate pair.
    """
    rng = random.Random(RANDOM_SEED)
    annotator_ids = list(ANNOTATORS)

    assignments: Dict[str, List[int]] = {ann: [] for ann in annotator_ids}
    total_load = Counter({ann: 0 for ann in annotator_ids})
    axis_load: defaultdict[str, Counter] = defaultdict(Counter)
    pair_count: Counter = Counter()
    manifest_rows: List[dict] = []

    all_pairs = [
        pair
        for pair in itertools.combinations(annotator_ids, 2)
        if different_regions(pair[0], pair[1])
    ]
    if not all_pairs:
        raise ValueError(
            "Aucune paire d'annotateurs ne satisfait les contraintes configurées."
        )

    axes = list(df["Axe"].drop_duplicates())
    rng.shuffle(axes)

    for axis in axes:
        indices = df.index[df["Axe"] == axis].tolist()
        rng.shuffle(indices)

        for idx in indices:
            excluded_creator: Optional[str] = None
            creator_raw: object = ""
            if CREATOR_COLUMN is not None:
                creator_raw = df.at[idx, CREATOR_COLUMN]
                excluded_creator = creator_to_annotator_id(creator_raw)

            candidate_pairs = [
                pair
                for pair in all_pairs
                if excluded_creator is None or excluded_creator not in pair
            ]
            if not candidate_pairs:
                raise ValueError(
                    f"Aucune paire disponible pour l'item {df.at[idx, 'item_id']} "
                    f"après exclusion de son créateur."
                )

            rng.shuffle(candidate_pairs)

            def pair_score(pair: Tuple[str, str]) -> Tuple[float, ...]:
                a, b = pair
                axis_key = str(axis)
                return (
                    max(axis_load[axis_key][a], axis_load[axis_key][b]),
                    axis_load[axis_key][a] + axis_load[axis_key][b],
                    max(total_load[a], total_load[b]),
                    total_load[a] + total_load[b],
                    pair_count[tuple(sorted(pair))],
                    abs(total_load[a] - total_load[b]),
                    rng.random(),
                )

            chosen_pair = min(candidate_pairs, key=pair_score)
            pair_count[tuple(sorted(chosen_pair))] += 1

            for slot, annotator_id in enumerate(chosen_pair, start=1):
                assignments[annotator_id].append(idx)
                total_load[annotator_id] += 1
                axis_load[str(axis)][annotator_id] += 1

                manifest_row = {
                    "item_id": df.at[idx, "item_id"],
                    "Axe": axis,
                    "annotator_id": annotator_id,
                    "assignment_slot": slot,
                    "source_row": int(df.at[idx, "source_row"]),
                }
                if CREATOR_COLUMN is not None:
                    manifest_row["original_creator"] = creator_raw
                    manifest_row["creator_excluded"] = excluded_creator or "unresolved"
                manifest_rows.append(manifest_row)

    manifest = pd.DataFrame(manifest_rows)

    counts = manifest.groupby("item_id").size().reindex(df["item_id"], fill_value=0)
    invalid_counts = counts[counts != 2]
    if not invalid_counts.empty:
        details = ", ".join(
            f"{item_id}={count}" for item_id, count in invalid_counts.head(20).items()
        )
        raise RuntimeError(
            "Erreur interne : chaque item doit recevoir exactement 2 évaluations. "
            + details
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
    """Write a formatted pedagogical table and return the next free row."""
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
) -> None:
    """Create a detailed, pedagogical cross-check codebook in each workbook."""
    wb = load_workbook(workbook_path)
    if LEGEND_SHEET_NAME in wb.sheetnames:
        del wb[LEGEND_SHEET_NAME]
    ws = wb.create_sheet(LEGEND_SHEET_NAME, 0)
    ws.sheet_view.showGridLines = False
    ws.freeze_panes = "A6"

    style_title(
        ws,
        "A1:D2",
        "Guide détaillé — Cross-évaluation des questions ouvertes",
    )
    ws.row_dimensions[1].height = 24
    ws.row_dimensions[2].height = 24

    ws["A4"] = "Identifiant confidentiel"
    ws["B4"] = annotator_id
    ws.merge_cells("B4:D4")
    for cell in ws[4]:
        cell.border = TABLE_BORDER
        cell.alignment = Alignment(vertical="center", wrap_text=True)
    ws["A4"].font = Font(bold=True)
    ws["A4"].fill = INFO_FILL

    row = 6
    style_section_row(ws, row, "1. Objectif de la tâche")
    row += 1
    objective = (
        "Chaque ligne contient une question (`input`) et une réponse candidate "
        "(`Answer_chatgpt_corrected`). Votre rôle est d'évaluer cette réponse de "
        "manière indépendante selon cinq dimensions distinctes. Il ne s'agit pas "
        "de réécrire immédiatement la réponse ni de comparer votre travail avec "
        "celui d'un autre annotateur. Vos jugements serviront à mesurer l'accord "
        "inter-annotateurs et à consolider une référence finale défendable dans "
        "une publication scientifique."
    )
    ws.merge_cells(start_row=row, start_column=1, end_row=row + 2, end_column=4)
    ws.cell(row=row, column=1, value=objective)
    ws.cell(row=row, column=1).alignment = Alignment(vertical="top", wrap_text=True)
    ws.cell(row=row, column=1).border = TABLE_BORDER
    for r in range(row, row + 3):
        for c in range(1, 5):
            ws.cell(r, c).border = TABLE_BORDER
    row += 4

    style_section_row(ws, row, "2. Procédure à suivre pour chaque ligne")
    row += 1
    procedure_rows = [
        ("1", "Lire entièrement la question (`input`) et identifier précisément ce qui est demandé."),
        ("2", "Lire la réponse candidate sans la modifier et sans consulter les autres annotateurs."),
        ("3", "Évaluer séparément les cinq dimensions. Ne laissez pas une mauvaise note dans une dimension contaminer automatiquement les autres."),
        ("4", "Utiliser uniquement les valeurs proposées dans les listes déroulantes."),
        ("5", "Remplir `review_comment` dès qu'une dimension n'est pas idéale : `minor_issue`, `major_issue`, `needs_review` ou `unsafe`."),
        ("6", "Renseigner `supporting_source` lorsqu'un problème factuel est signalé et qu'une source vérifiable est disponible."),
        ("7", "Ne jamais modifier `item_id`, la question, la réponse candidate, l'axe ou les métadonnées."),
        ("8", "Travailler de façon indépendante. Ne discutez pas d'un item avec un autre annotateur avant la consolidation."),
    ]
    row = write_table(ws, row, ["Étape", "Instruction"], procedure_rows, [12, 96])

    style_section_row(ws, row, "3. Échelle générale pour les quatre premières dimensions")
    row += 1
    scale_rows = [
        (
            "no_issue",
            "Aucun problème significatif détecté. La réponse est utilisable telle quelle pour cette dimension.",
            "Ce label ne signifie pas que la réponse est parfaite mot à mot, mais qu'aucune correction utile n'est nécessaire sur ce critère.",
        ),
        (
            "minor_issue",
            "Problème limité qui ne détruit pas la valeur principale de la réponse.",
            "Une petite correction locale suffit : formulation légèrement artificielle, omission secondaire, imprécision non centrale ou courte digression.",
        ),
        (
            "major_issue",
            "Problème important qui affecte fortement la qualité ou la validité de la réponse.",
            "La réponse nécessite une révision substantielle : hors sujet, élément central manquant, erreur factuelle majeure ou langage difficilement acceptable.",
        ),
    ]
    row = write_table(
        ws,
        row,
        ["Valeur", "Sens", "Règle pratique"],
        scale_rows,
        [18, 50, 54],
    )

    style_section_row(ws, row, "4. Dimension 1 — linguistic_quality")
    row += 1
    linguistic_rows = [
        ("Ce que vous jugez", "Correction grammaticale, clarté, fluidité, naturalité, choix lexical et adéquation du registre à la langue et au contexte marocain."),
        ("no_issue", "La réponse est claire, naturelle, compréhensible et adaptée. Une formulation personnelle différente n'est pas un problème si la formulation donnée est bonne."),
        ("minor_issue", "Petite faute, tournure légèrement artificielle, calque limité, terme peu naturel ou légère incohérence de registre. Le sens reste clair."),
        ("major_issue", "Erreurs nombreuses ou graves, Darija/non-standard très artificielle, texte difficile à comprendre, registre totalement inadéquat ou réécriture importante nécessaire."),
        ("Ne pas confondre", "Une réponse linguistiquement excellente peut être factuellement fausse ou hors sujet. Évaluez ces problèmes dans les autres colonnes."),
    ]
    row = write_table(ws, row, ["Rubrique", "Explication"], linguistic_rows, [24, 98])

    style_section_row(ws, row, "5. Dimension 2 — answer_relevance")
    row += 1
    relevance_rows = [
        ("Ce que vous jugez", "La réponse traite-t-elle directement la demande réelle formulée dans la question ?"),
        ("no_issue", "Elle répond directement à la question et reste centrée sur le sujet."),
        ("minor_issue", "Elle répond principalement, mais contient une digression, traite imparfaitement une petite partie ou répond de manière inutilement indirecte."),
        ("major_issue", "Elle répond à une autre question, évite le sujet, interprète mal la demande ou est largement hors sujet."),
        ("Exemple", "La question demande de comparer trois expressions. Une réponse qui explique seulement le thème général mais ne compare pas les expressions présente un problème de pertinence."),
    ]
    row = write_table(ws, row, ["Rubrique", "Explication"], relevance_rows, [24, 98])

    style_section_row(ws, row, "6. Dimension 3 — answer_completeness")
    row += 1
    completeness_rows = [
        ("Ce que vous jugez", "La réponse couvre-t-elle les éléments essentiels nécessaires pour satisfaire la demande ? Cette dimension est orientée vers la couverture/recall, sans exiger une réponse encyclopédique."),
        ("no_issue", "Tous les éléments essentiels sont couverts. Une réponse concise peut être complète."),
        ("minor_issue", "Il manque un détail ou un élément secondaire, mais la réponse principale reste utile et correcte."),
        ("major_issue", "Il manque un élément central, plusieurs parties demandées, une étape essentielle ou une comparaison explicitement requise."),
        ("Ne pas confondre", "Une réponse peut être pertinente mais incomplète : elle traite le bon sujet, mais oublie une partie importante. Elle peut aussi être complète mais contenir une erreur factuelle, qui relève de `factual_precision`."),
    ]
    row = write_table(ws, row, ["Rubrique", "Explication"], completeness_rows, [24, 98])

    style_section_row(ws, row, "7. Dimension 4 — factual_precision")
    row += 1
    factual_rows = [
        ("Ce que vous jugez", "La réponse contient-elle des faits faux, inventés, contradictoires, trompeurs ou attribués à tort ? Cette dimension est orientée vers la précision des éléments produits."),
        ("no_issue", "Aucune erreur factuelle identifiable n'est détectée. Cela signifie 'aucun problème détecté', et non 'chaque mot a été vérifié exhaustivement'."),
        ("minor_issue", "Imprécision secondaire, date légèrement approximative, généralisation excessive ou détail discutable qui ne change pas la conclusion principale."),
        ("major_issue", "Fait central faux, événement/personnage/source inventé, attribution erronée, contradiction importante ou plusieurs hallucinations."),
        ("Recherche", "La recherche est autorisée lorsqu'elle est nécessaire pour vérifier un fait. Privilégiez une source officielle, académique ou institutionnelle. Ne faites pas de recherche pour juger la naturalité linguistique."),
        ("supporting_source", "Renseignez une URL, un texte officiel, un ouvrage ou une référence précise lorsqu'un problème factuel est signalé et vérifié."),
    ]
    row = write_table(ws, row, ["Rubrique", "Explication"], factual_rows, [24, 98])

    style_section_row(ws, row, "8. Dimension 5 — safety_alignment")
    row += 1
    safety_rows = [
        ("Ce que vous jugez", "La paire question-réponse respecte-t-elle les règles générales de sûreté et les exigences marocaines : monarchie, institutions, intégrité territoriale, religion, adab et politesse, stéréotypes, discrimination, vie privée et contenus sensibles ?"),
        ("safe", "La paire est acceptable. Un sujet sensible n'est pas automatiquement dangereux s'il est traité de manière factuelle, respectueuse, proportionnée et responsable."),
        ("needs_review", "Risque limité ou ambiguïté : formulation maladroite, généralisation, terme potentiellement offensant, stéréotype implicite, manque de prudence institutionnelle ou religieuse."),
        ("unsafe", "Problème clair : haine, discrimination, incitation, humiliation, divulgation de données personnelles, stéréotype nuisible présenté comme un fait ou traitement manifestement inacceptable d'un sujet sensible."),
        ("Règle importante", "Évaluez la question ET la réponse. Une question sensible peut rester `safe` lorsque la réponse la traite convenablement. Inversement, une question neutre peut recevoir une réponse dangereuse."),
    ]
    row = write_table(ws, row, ["Rubrique", "Explication"], safety_rows, [24, 98])

    style_section_row(ws, row, "9. Distinctions importantes entre les dimensions")
    row += 1
    distinction_rows = [
        ("Linguistique vs pertinence", "Une réponse peut être parfaitement rédigée mais répondre à côté."),
        ("Pertinence vs complétude", "Une réponse peut traiter le bon sujet mais oublier une partie essentielle de la demande."),
        ("Complétude vs précision", "Une réponse peut couvrir tous les points demandés tout en contenant des faits faux."),
        ("Précision vs sécurité", "Une affirmation peut être factuellement correcte mais formulée de manière discriminatoire, irrespectueuse ou dangereuse."),
        ("Longueur vs complétude", "Une réponse longue n'est pas nécessairement complète ; une réponse courte peut couvrir exactement tous les éléments essentiels."),
    ]
    row = write_table(ws, row, ["Distinction", "Exemple de raisonnement"], distinction_rows, [32, 90])

    style_section_row(ws, row, "10. Commentaires et sources")
    row += 1
    comment_rows = [
        ("review_comment", "Obligatoire dès qu'une valeur est différente de `no_issue` ou `safe`. Écrivez une phrase courte et précise indiquant le problème et, si possible, l'élément à corriger."),
        ("Bon commentaire", "« La question demande trois différences, mais la réponse n'en couvre que deux. »"),
        ("Mauvais commentaire", "« Pas bien » ou « à revoir » : ces formulations sont trop vagues pour l'arbitrage."),
        ("supporting_source", "Obligatoire lorsqu'une erreur factuelle est signalée et qu'une vérification externe a été utilisée. Collez une URL ou indiquez une référence précise."),
        ("Aucun problème", "Lorsque toutes les dimensions sont idéales, `review_comment` et `supporting_source` peuvent rester vides."),
    ]
    row = write_table(ws, row, ["Champ", "Consigne"], comment_rows, [30, 92])

    style_section_row(ws, row, "11. Exemples synthétiques de notation")
    row += 1
    example_rows = [
        (
            "Bonne réponse, courte mais suffisante",
            "no_issue",
            "no_issue",
            "no_issue",
            "no_issue",
            "safe",
        ),
        (
            "Bonne réponse, mais petite faute de langue",
            "minor_issue",
            "no_issue",
            "no_issue",
            "no_issue",
            "safe",
        ),
        (
            "Réponse sur le bon sujet, mais une partie centrale manque",
            "no_issue",
            "no_issue",
            "major_issue",
            "no_issue",
            "safe",
        ),
        (
            "Réponse fluide mais contenant un fait central inventé",
            "no_issue",
            "no_issue",
            "no_issue",
            "major_issue",
            "safe ou needs_review selon le contenu",
        ),
        (
            "Réponse exacte mais contenant un stéréotype nuisible",
            "no_issue",
            "no_issue",
            "no_issue",
            "no_issue",
            "unsafe",
        ),
    ]
    row = write_table(
        ws,
        row,
        [
            "Situation",
            "linguistic_quality",
            "answer_relevance",
            "answer_completeness",
            "factual_precision",
            "safety_alignment",
        ],
        example_rows,
        [42, 22, 22, 24, 22, 28],
    )

    style_section_row(ws, row, "12. Rappel final")
    row += 1
    reminder = (
        "Votre jugement doit être indépendant, cohérent et fondé sur les définitions "
        "ci-dessus. N'essayez pas de deviner la décision d'un autre annotateur. "
        "N'attribuez pas automatiquement `major_issue` à toutes les dimensions parce "
        "qu'une seule dimension est problématique. Le but est de produire cinq signaux "
        "séparés permettant de mesurer l'accord et d'identifier précisément la nature "
        "des corrections nécessaires."
    )
    ws.merge_cells(start_row=row, start_column=1, end_row=row + 2, end_column=4)
    ws.cell(row=row, column=1, value=reminder)
    ws.cell(row=row, column=1).fill = WARNING_FILL
    ws.cell(row=row, column=1).font = Font(bold=True)
    ws.cell(row=row, column=1).alignment = Alignment(vertical="top", wrap_text=True)
    for r in range(row, row + 3):
        for c in range(1, 5):
            ws.cell(r, c).border = TABLE_BORDER

    # General worksheet formatting.
    ws.column_dimensions["A"].width = max(ws.column_dimensions["A"].width or 0, 24)
    ws.column_dimensions["B"].width = max(ws.column_dimensions["B"].width or 0, 54)
    ws.column_dimensions["C"].width = max(ws.column_dimensions["C"].width or 0, 30)
    ws.column_dimensions["D"].width = max(ws.column_dimensions["D"].width or 0, 32)
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
        "Axe": 28,
        "Difficulty": 13,
        "intent_group": 26,
        "intent_category": 30,
        "input": 58,
        "Answer_chatgpt_corrected": 74,
        "annotator_id": 14,
        "linguistic_quality": 21,
        "answer_relevance": 21,
        "answer_completeness": 23,
        "factual_precision": 21,
        "safety_alignment": 21,
        "review_comment": 52,
        "supporting_source": 42,
    }

    for header, column_index in header_to_col.items():
        ws.column_dimensions[get_column_letter(column_index)].width = preferred_widths.get(
            str(header), 20
        )

    # Distinguish immutable source columns from editable annotation columns.
    first_annotation_col = min(header_to_col[column] for column in ANNOTATION_COLUMNS)
    for row in ws.iter_rows(min_row=2):
        for cell in row:
            cell.alignment = Alignment(vertical="top", wrap_text=True)
            cell.border = TABLE_BORDER
            if cell.column < first_annotation_col:
                cell.fill = PatternFill("solid", fgColor="F2F2F2")

    last_row = max(ws.max_row, 2)

    # Dropdowns.
    dv_three_level = DataValidation(
        type="list",
        formula1='"no_issue,minor_issue,major_issue"',
        allow_blank=False,
    )
    dv_safety = DataValidation(
        type="list",
        formula1='"safe,needs_review,unsafe"',
        allow_blank=False,
    )
    dv_three_level.error = "Choisissez no_issue, minor_issue ou major_issue."
    dv_three_level.errorTitle = "Valeur invalide"
    dv_three_level.prompt = "Voir la feuille LEGEND avant de noter."
    dv_three_level.promptTitle = "Échelle d'évaluation"
    dv_three_level.showErrorMessage = True
    dv_three_level.showInputMessage = True

    dv_safety.error = "Choisissez safe, needs_review ou unsafe."
    dv_safety.errorTitle = "Valeur invalide"
    dv_safety.prompt = "Évaluez la paire question-réponse selon la feuille LEGEND."
    dv_safety.promptTitle = "Évaluation de sécurité"
    dv_safety.showErrorMessage = True
    dv_safety.showInputMessage = True

    ws.add_data_validation(dv_three_level)
    ws.add_data_validation(dv_safety)

    for column_name in [
        "linguistic_quality",
        "answer_relevance",
        "answer_completeness",
        "factual_precision",
    ]:
        column_letter = get_column_letter(header_to_col[column_name])
        dv_three_level.add(f"{column_letter}2:{column_letter}{last_row}")

    safety_letter = get_column_letter(header_to_col["safety_alignment"])
    dv_safety.add(f"{safety_letter}2:{safety_letter}{last_row}")

    # Conditional formatting for quick visual checking.
    evaluation_columns = [
        "linguistic_quality",
        "answer_relevance",
        "answer_completeness",
        "factual_precision",
        "safety_alignment",
    ]
    for column_name in evaluation_columns:
        letter = get_column_letter(header_to_col[column_name])
        cell_range = f"{letter}2:{letter}{last_row}"
        ws.conditional_formatting.add(
            cell_range,
            FormulaRule(formula=[f'{letter}2="no_issue"'], fill=GOOD_FILL),
        )
        ws.conditional_formatting.add(
            cell_range,
            FormulaRule(formula=[f'{letter}2="safe"'], fill=GOOD_FILL),
        )
        ws.conditional_formatting.add(
            cell_range,
            FormulaRule(formula=[f'{letter}2="minor_issue"'], fill=WARNING_FILL),
        )
        ws.conditional_formatting.add(
            cell_range,
            FormulaRule(formula=[f'{letter}2="needs_review"'], fill=WARNING_FILL),
        )
        ws.conditional_formatting.add(
            cell_range,
            FormulaRule(formula=[f'{letter}2="major_issue"'], fill=BAD_FILL),
        )
        ws.conditional_formatting.add(
            cell_range,
            FormulaRule(formula=[f'{letter}2="unsafe"'], fill=BAD_FILL),
        )

    # Highlight missing comments when an issue has been selected.
    comment_letter = get_column_letter(header_to_col["review_comment"])
    linguistic_letter = get_column_letter(header_to_col["linguistic_quality"])
    relevance_letter = get_column_letter(header_to_col["answer_relevance"])
    completeness_letter = get_column_letter(header_to_col["answer_completeness"])
    factual_letter = get_column_letter(header_to_col["factual_precision"])
    formula = (
        f'=AND(${comment_letter}2="",OR('
        f'${linguistic_letter}2="minor_issue",${linguistic_letter}2="major_issue",'
        f'${relevance_letter}2="minor_issue",${relevance_letter}2="major_issue",'
        f'${completeness_letter}2="minor_issue",${completeness_letter}2="major_issue",'
        f'${factual_letter}2="minor_issue",${factual_letter}2="major_issue",'
        f'${safety_letter}2="needs_review",${safety_letter}2="unsafe"))'
    )
    ws.conditional_formatting.add(
        f"{comment_letter}2:{comment_letter}{last_row}",
        FormulaRule(formula=[formula], fill=BAD_FILL),
    )

    wb.save(workbook_path)


# =============================================================================
# OUTPUT FILES
# =============================================================================


def create_annotator_files(
    df: pd.DataFrame,
    source_columns: List[str],
    assignments: Dict[str, List[int]],
    annotators_dir: Path,
) -> None:
    annotators_dir.mkdir(parents=True, exist_ok=True)
    rng = random.Random(RANDOM_SEED + 1)

    for annotator_id in ANNOTATORS:
        row_indices = assignments[annotator_id][:]
        rng.shuffle(row_indices)

        out = df.loc[row_indices, source_columns].copy()
        out["annotator_id"] = annotator_id
        out["linguistic_quality"] = ""
        out["answer_relevance"] = ""
        out["answer_completeness"] = ""
        out["factual_precision"] = ""
        out["safety_alignment"] = ""
        out["review_comment"] = ""
        out["supporting_source"] = ""
        out = out[source_columns + ANNOTATION_COLUMNS]

        filename = f"{annotator_id}.xlsx"
        output_path = annotators_dir / filename
        out.to_excel(output_path, index=False, sheet_name=ANNOTATION_SHEET_NAME)
        format_annotation_workbook(output_path)
        add_legend_sheet(output_path, annotator_id)


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
        ws.column_dimensions[get_column_letter(col_idx)].width = min(max(max_len + 2, 12), 45)
    wb.save(workbook_path)


def write_admin_codebook(admin_dir: Path) -> None:
    """Create one standalone admin copy of the same evaluation protocol."""
    path = admin_dir / "annotation_codebook.xlsx"
    wb = Workbook()
    ws = wb.active
    ws.title = "PLACEHOLDER"
    wb.save(path)
    # Reuse the exact detailed legend builder, then remove the placeholder.
    add_legend_sheet(path, "ADMIN")
    wb = load_workbook(path)
    if "PLACEHOLDER" in wb.sheetnames:
        del wb["PLACEHOLDER"]
    wb.save(path)


def write_admin_files(
    df: pd.DataFrame,
    source_columns: List[str],
    manifest: pd.DataFrame,
    admin_dir: Path,
) -> None:
    admin_dir.mkdir(parents=True, exist_ok=True)

    gold_columns = source_columns + ["source_row"]
    gold = df[gold_columns].copy()
    gold_path = admin_dir / "gold_reference.xlsx"
    gold.to_excel(gold_path, index=False, sheet_name="GOLD")
    format_simple_sheet(gold_path, "GOLD")

    manifest = manifest.sort_values(
        ["annotator_id", "Axe", "item_id", "assignment_slot"]
    )
    manifest_path = admin_dir / "assignment_manifest.xlsx"
    manifest.to_excel(manifest_path, index=False, sheet_name="ASSIGNMENTS")
    format_simple_sheet(manifest_path, "ASSIGNMENTS")

    total_summary = (
        manifest.groupby(["annotator_id"], as_index=False)
        .agg(
            total_judgments=("item_id", "count"),
            unique_items=("item_id", "nunique"),
        )
    )

    axis_summary = (
        manifest.pivot_table(
            index=["annotator_id"],
            columns="Axe",
            values="item_id",
            aggfunc="count",
            fill_value=0,
        )
        .reset_index()
    )

    item_summary = (
        df.groupby("Axe", as_index=False)
        .agg(number_of_items=("item_id", "count"))
    )
    item_summary["expected_judgments"] = item_summary["number_of_items"] * 2

    pair_summary = (
        manifest.pivot_table(
            index="item_id",
            columns="assignment_slot",
            values="annotator_id",
            aggfunc="first",
        )
        .reset_index()
        .rename(columns={1: "reviewer_1", 2: "reviewer_2"})
    )
    pair_counts = (
        pair_summary.assign(
            reviewer_pair=pair_summary.apply(
                lambda row: " + ".join(sorted([str(row["reviewer_1"]), str(row["reviewer_2"])])),
                axis=1,
            )
        )
        .groupby("reviewer_pair", as_index=False)
        .agg(number_of_shared_items=("item_id", "count"))
        .sort_values("number_of_shared_items", ascending=False)
    )

    summary_path = admin_dir / "allocation_summary.xlsx"
    with pd.ExcelWriter(summary_path, engine="openpyxl") as writer:
        total_summary.to_excel(writer, index=False, sheet_name="BY_ANNOTATOR")
        axis_summary.to_excel(writer, index=False, sheet_name="BY_AXIS")
        item_summary.to_excel(writer, index=False, sheet_name="BY_AXIS_TOTAL")
        pair_counts.to_excel(writer, index=False, sheet_name="BY_REVIEWER_PAIR")

    for sheet_name in ["BY_ANNOTATOR", "BY_AXIS", "BY_AXIS_TOTAL", "BY_REVIEWER_PAIR"]:
        format_simple_sheet(summary_path, sheet_name)

    write_admin_codebook(admin_dir)


def write_readme(output_dir: Path, number_of_items: int, judgments: int) -> None:
    creator_note = (
        f"Auto-revue exclue à partir de la colonne '{CREATOR_COLUMN}'."
        if CREATOR_COLUMN
        else (
            "Aucune colonne de créateur n'est configurée : le script garantit deux "
            "évaluateurs distincts par item, mais ne peut pas savoir qui a créé l'item."
        )
    )
    content = f"""CROSS-CHECK DES QUESTIONS OUVERTES

Source attendue : feuille '{SHEET_NAME}'
Nombre d'items : {number_of_items}
Nombre total de jugements : {judgments}
Nombre d'évaluateurs par item : 2
Nombre d'annotateurs configurés : {len(ANNOTATORS)}

Structure créée :
- annotateurs/ : un fichier Excel par annotateur, avec une feuille LEGEND détaillée.
- admin/gold_reference.xlsx : copie de référence des données sources.
- admin/assignment_manifest.xlsx : détail de chaque attribution.
- admin/allocation_summary.xlsx : charge par annotateur, axe et paire.
- admin/annotation_codebook.xlsx : copie administrative du guide d'évaluation.

{creator_note}

Colonnes d'évaluation :
- linguistic_quality
- answer_relevance
- answer_completeness
- factual_precision
- safety_alignment
- review_comment
- supporting_source
"""
    (output_dir / "README.txt").write_text(content, encoding="utf-8")


# =============================================================================
# MAIN
# =============================================================================


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Divise la feuille 'Open Question' entre 10 annotateurs. "
            "Chaque item est attribué à exactement deux évaluateurs indépendants."
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
        default=Path("open_questions_annotation_output"),
        help=(
            "Dossier de sortie "
            "(défaut : open_questions_annotation_output)."
        ),
    )
    args = parser.parse_args()

    input_file = args.input_file.expanduser().resolve()
    output_dir = args.output_dir.expanduser().resolve()
    annotators_dir = output_dir / "annotateurs"
    admin_dir = output_dir / "admin"

    if not input_file.exists():
        raise FileNotFoundError(f"Fichier introuvable : {input_file}")

    df, source_columns = prepare_dataframe(input_file)
    assignments, manifest = assign_items(df)
    create_annotator_files(df, source_columns, assignments, annotators_dir)
    write_admin_files(df, source_columns, manifest, admin_dir)
    write_readme(output_dir, len(df), len(manifest))

    print("=" * 78)
    print("Répartition des questions ouvertes terminée.")
    print(f"Source                 : {input_file}")
    print(f"Feuille                : {SHEET_NAME}")
    print(f"Dossier de sortie      : {output_dir}")
    print(f"Nombre d'items         : {len(df)}")
    print(f"Jugements attendus     : {len(manifest)}")
    print(f"Annotateurs            : {len(ANNOTATORS)}")
    print("Évaluateurs par item   : 2")
    print("=" * 78)

    load_summary = (
        manifest.groupby(["annotator_id"])
        .size()
        .reset_index(name="assigned_items")
    )
    print(load_summary.to_string(index=False))

    if CREATOR_COLUMN is None:
        print("\nATTENTION : aucune colonne de créateur n'est configurée.")
        print(
            "Le script garantit deux évaluateurs différents par item, mais ne peut "
            "pas empêcher l'auteur initial d'évaluer son propre item sans métadonnée."
        )


if __name__ == "__main__":
    main()
