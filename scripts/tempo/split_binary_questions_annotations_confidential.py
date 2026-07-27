from __future__ import annotations

import argparse
import itertools
import random
import re
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path
from typing import Dict, List, Tuple

import pandas as pd
from openpyxl import load_workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation


# ---------------------------------------------------------------------------
# CONFIGURATION
# ---------------------------------------------------------------------------

SHEET_NAME = "Binary questions"
ANNOTATION_SHEET_NAME = "BINARY_ANNOTATION"
RANDOM_SEED = 20260726

ANNOTATORS = [
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

# Facultatif : renseigner les régions pour favoriser deux annotateurs de
# régions différentes sur chaque item tacite.
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
    "response_A",
    "response_B",
    "correct_answer",
    "item_id",
]

ANNOTATION_COLUMNS = [
    "annotator_id",
    "annotator_answer",
    "flag_language",
    "flag_safety",
    "flag_item",
    "comment",
]


# ---------------------------------------------------------------------------
# OUTILS
# ---------------------------------------------------------------------------

def normalize_text(value: object) -> str:
    text = "" if pd.isna(value) else str(value)
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.lower().strip()
    text = re.sub(r"[_/–—-]+", " ", text)
    text = re.sub(r"[’'`]+", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text


def normalize_correct_answer(value: object) -> str:
    """Accepte A/B, response_A/response_B, option A/option B, etc."""
    if pd.isna(value):
        raise ValueError("correct_answer vide")

    text = normalize_text(value).upper()
    aliases = {
        "A": "A",
        "B": "B",
        "RESPONSE A": "A",
        "RESPONSE B": "B",
        "OPTION A": "A",
        "OPTION B": "B",
    }
    if text in aliases:
        return aliases[text]

    match = re.fullmatch(r"(?:RESPONSE|OPTION)?\s*([AB])", text)
    if match:
        return match.group(1)

    raise ValueError(f"correct_answer invalide : {value!r}; valeur attendue = A ou B")


def prepare_dataframe(input_file: Path) -> Tuple[pd.DataFrame, List[str]]:
    """
    Lit la feuille Binary questions.

    Toutes les colonnes présentes sont conservées, y compris les colonnes
    supplémentaires. Seules les colonnes Excel entièrement vides du type
    Unnamed sont supprimées.
    """
    df = pd.read_excel(input_file, sheet_name=SHEET_NAME, dtype=object)

    # Nettoyage des noms de colonnes sans supprimer les vraies colonnes métier.
    df.columns = [str(c).strip() for c in df.columns]
    unnamed = [
        c for c in df.columns
        if re.match(r"^Unnamed:", c) and df[c].isna().all()
    ]
    if unnamed:
        df = df.drop(columns=unnamed)

    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise KeyError(
            f"Colonnes obligatoires absentes de la feuille '{SHEET_NAME}' : "
            + ", ".join(missing)
        )

    # Ignore les lignes parasites créées par du formatage, des formules ou des
    # colonnes administratives remplies sous le vrai tableau. Une ligne est un
    # item seulement si au moins un champ central de la question est renseigné.
    original_excel_rows = pd.Series(df.index + 2, index=df.index)
    item_core_columns = [
        "Axe", "input", "response_A", "response_B", "item_id"
    ]
    meaningful_mask = df[item_core_columns].apply(
        lambda col: col.map(lambda value: bool(str(value).strip()) if not pd.isna(value) else False)
    ).any(axis=1)
    df = df.loc[meaningful_mask].copy()
    df["source_row"] = original_excel_rows.loc[df.index].astype(int)
    df = df.reset_index(drop=True)

    if df.empty:
        raise ValueError(f"La feuille '{SHEET_NAME}' ne contient aucun item exploitable.")

    # Conserve l'ordre exact des colonnes source pour les fichiers annotateurs.
    source_columns = [c for c in df.columns if c != "source_row"]

    # Complète les item_id manquants sans toucher aux IDs déjà présents.
    df["item_id"] = df["item_id"].apply(
        lambda x: "" if pd.isna(x) else str(x).strip()
    )
    existing_ids = {x for x in df["item_id"] if x}
    generated_ids: List[str] = []
    next_number = 1

    for current_id in df["item_id"]:
        if current_id:
            generated_ids.append(current_id)
            continue

        while f"BIN_{next_number:04d}" in existing_ids:
            next_number += 1
        new_id = f"BIN_{next_number:04d}"
        existing_ids.add(new_id)
        generated_ids.append(new_id)
        next_number += 1

    df["item_id"] = generated_ids

    duplicates = df.loc[df["item_id"].duplicated(keep=False), "item_id"].tolist()
    if duplicates:
        raise ValueError(
            "item_id dupliqués détectés : "
            + ", ".join(sorted(set(duplicates))[:20])
        )

    # Valide et normalise la clé binaire.
    errors: List[str] = []
    normalized_answers: List[str | None] = []
    for idx, value in df["correct_answer"].items():
        excel_row = int(df.at[idx, "source_row"])

        # Certains fichiers contiennent aussi `correct_response`. Si la cellule
        # `correct_answer` est réellement vide, on peut récupérer la clé depuis
        # cette colonne : soit A/B, soit le texte exact de response_A/response_B.
        candidate = value
        if pd.isna(candidate) or not str(candidate).strip():
            if "correct_response" in df.columns:
                fallback = df.at[idx, "correct_response"]
                if not pd.isna(fallback) and str(fallback).strip():
                    fallback_text = str(fallback).strip()
                    response_a = "" if pd.isna(df.at[idx, "response_A"]) else str(df.at[idx, "response_A"]).strip()
                    response_b = "" if pd.isna(df.at[idx, "response_B"]) else str(df.at[idx, "response_B"]).strip()
                    if normalize_text(fallback_text) == normalize_text(response_a) and response_a:
                        candidate = "A"
                    elif normalize_text(fallback_text) == normalize_text(response_b) and response_b:
                        candidate = "B"
                    else:
                        candidate = fallback_text

        try:
            normalized_answers.append(normalize_correct_answer(candidate))
        except ValueError as exc:
            errors.append(f"ligne Excel {excel_row}: {exc}")
            normalized_answers.append(None)

    if errors:
        raise ValueError(
            "Clés correct_answer invalides :\n- " + "\n- ".join(errors[:30])
        )

    df["correct_answer"] = normalized_answers
    return df, source_columns


def different_regions(ann1: str, ann2: str) -> bool:
    r1 = ANNOTATOR_REGIONS.get(ann1, "").strip()
    r2 = ANNOTATOR_REGIONS.get(ann2, "").strip()
    if not r1 or not r2:
        return True
    return normalize_text(r1) != normalize_text(r2)


def assign_items(df: pd.DataFrame) -> Tuple[Dict[str, List[int]], pd.DataFrame]:
    """
    Tous les items sont tacites et reçoivent exactement deux annotations.
    La répartition est équilibrée globalement et par Axe.
    """
    rng = random.Random(RANDOM_SEED)
    annotator_ids = ANNOTATORS.copy()

    assignments: Dict[str, List[int]] = {ann: [] for ann in annotator_ids}
    total_load = Counter({ann: 0 for ann in annotator_ids})
    axis_load = defaultdict(Counter)
    pair_count = Counter()
    manifest_rows = []

    all_pairs = [
        pair
        for pair in itertools.combinations(annotator_ids, 2)
        if different_regions(pair[0], pair[1])
    ]
    if not all_pairs:
        raise ValueError(
            "Aucune paire d'annotateurs ne satisfait la contrainte régionale."
        )

    axes = list(df["Axe"].drop_duplicates())
    rng.shuffle(axes)

    for axis in axes:
        indices = df.index[df["Axe"] == axis].tolist()
        rng.shuffle(indices)

        for idx in indices:
            candidate_pairs = all_pairs[:]
            rng.shuffle(candidate_pairs)

            def pair_score(pair: Tuple[str, str]) -> Tuple[float, ...]:
                a, b = pair
                return (
                    max(axis_load[str(axis)][a], axis_load[str(axis)][b]),
                    axis_load[str(axis)][a] + axis_load[str(axis)][b],
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

                manifest_rows.append({
                    "item_id": df.at[idx, "item_id"],
                    "item_type": "tacit",
                    "Axe": axis,
                    "annotator_id": annotator_id,
                    "assignment_slot": slot,
                })

    manifest = pd.DataFrame(manifest_rows)

    # Chaque item doit apparaître exactement deux fois.
    counts = manifest.groupby("item_id").size()
    bad = counts.reindex(df["item_id"], fill_value=0) != 2
    if bad.any():
        bad_ids = df.loc[bad.to_numpy(), "item_id"].tolist()
        raise RuntimeError(
            "Erreur interne d'attribution pour : " + ", ".join(bad_ids[:20])
        )

    return assignments, manifest


def add_instruction_sheet(
    workbook_path: Path,
    annotator_id: str,
) -> None:
    wb = load_workbook(workbook_path)
    ws = wb.create_sheet("INSTRUCTIONS", 0)

    instructions = [
        ("Fichier d'annotation — Questions binaires", ""),
        ("Identifiant", annotator_id),
        ("", ""),
        ("Règles générales", ""),
        ("1", "Répondre à chaque item dans annotator_answer : A ou B."),
        ("2", "Tous les items sont tacites : recherche internet interdite."),
        ("3", "Répondre selon l'intuition native, de manière immédiate et indépendante."),
        ("4", "Ne pas modifier item_id, les questions, les réponses proposées ni les métadonnées."),
        ("5", "Remplir les trois colonnes de signalement, même lorsque tout est correct."),
        ("", ""),
        ("Valeurs attendues", ""),
        ("flag_language", "ok / problème"),
        ("flag_safety", "ok / problème"),
        (
            "flag_item",
            "ok / réponse A invalide / réponse B invalide / plusieurs réponses correctes / aucune réponse correcte / question mal posée",
        ),
        ("comment", "Facultatif, une ligne concise."),
    ]

    for row_idx, (left, right) in enumerate(instructions, start=1):
        ws.cell(row=row_idx, column=1, value=left)
        ws.cell(row=row_idx, column=2, value=right)

    ws["A1"].font = Font(bold=True, size=14)
    ws["A1"].fill = PatternFill("solid", fgColor="D9EAF7")
    ws["A5"].font = Font(bold=True)
    ws["A12"].font = Font(bold=True)
    ws.column_dimensions["A"].width = 24
    ws.column_dimensions["B"].width = 110

    for row in ws.iter_rows():
        for cell in row:
            cell.alignment = Alignment(vertical="top", wrap_text=True)

    wb.save(workbook_path)


def format_annotation_workbook(workbook_path: Path) -> None:
    wb = load_workbook(workbook_path)
    ws = wb[ANNOTATION_SHEET_NAME]

    header_fill = PatternFill("solid", fgColor="D9EAF7")
    for cell in ws[1]:
        cell.font = Font(bold=True)
        cell.fill = header_fill
        cell.alignment = Alignment(
            horizontal="center", vertical="center", wrap_text=True
        )

    ws.freeze_panes = "A2"
    ws.auto_filter.ref = ws.dimensions
    ws.sheet_view.showGridLines = False
    ws.row_dimensions[1].height = 36

    header_to_col = {cell.value: cell.column for cell in ws[1]}
    preferred_widths = {
        "item_id": 15,
        "Axe": 28,
        "Difficulty": 13,
        "intent_group": 25,
        "intent_category": 28,
        "input": 58,
        "response_A": 42,
        "response_B": 42,
        "annotator_id": 14,
        "annotator_answer": 18,
        "flag_language": 18,
        "flag_safety": 18,
        "flag_item": 30,
        "comment": 45,
    }

    # Largeur raisonnable pour les colonnes supplémentaires.
    for header, col_idx in header_to_col.items():
        width = preferred_widths.get(str(header), 20)
        ws.column_dimensions[get_column_letter(col_idx)].width = width

    for row in ws.iter_rows(min_row=2):
        for cell in row:
            cell.alignment = Alignment(vertical="top", wrap_text=True)

    last_row = max(ws.max_row, 2)

    dv_answer = DataValidation(type="list", formula1='"A,B"', allow_blank=False)
    dv_binary = DataValidation(type="list", formula1='"ok,problème"', allow_blank=False)
    dv_item = DataValidation(
        type="list",
        formula1=(
            '"ok,réponse A invalide,réponse B invalide,plusieurs réponses correctes,'
            'aucune réponse correcte,question mal posée"'
        ),
        allow_blank=False,
    )

    ws.add_data_validation(dv_answer)
    ws.add_data_validation(dv_binary)
    ws.add_data_validation(dv_item)

    answer_col = get_column_letter(header_to_col["annotator_answer"])
    language_col = get_column_letter(header_to_col["flag_language"])
    safety_col = get_column_letter(header_to_col["flag_safety"])
    item_col = get_column_letter(header_to_col["flag_item"])

    dv_answer.add(f"{answer_col}2:{answer_col}{last_row}")
    dv_binary.add(f"{language_col}2:{language_col}{last_row}")
    dv_binary.add(f"{safety_col}2:{safety_col}{last_row}")
    dv_item.add(f"{item_col}2:{item_col}{last_row}")

    wb.save(workbook_path)


def create_annotator_files(
    df: pd.DataFrame,
    source_columns: List[str],
    assignments: Dict[str, List[int]],
    annotators_dir: Path,
) -> None:
    annotators_dir.mkdir(parents=True, exist_ok=True)
    rng = random.Random(RANDOM_SEED + 1)

    # Toutes les colonnes source sont conservées, sauf correct_answer.
    visible_source_columns = [
        column for column in source_columns if column != "correct_answer"
    ]

    for annotator_id in ANNOTATORS:
        row_indices = assignments[annotator_id][:]
        rng.shuffle(row_indices)

        out = df.loc[row_indices, visible_source_columns].copy()
        out["annotator_id"] = annotator_id
        out["annotator_answer"] = ""
        out["flag_language"] = ""
        out["flag_safety"] = ""
        out["flag_item"] = ""
        out["comment"] = ""

        out = out[visible_source_columns + ANNOTATION_COLUMNS]

        filename = f"{annotator_id}.xlsx"
        output_path = annotators_dir / filename
        out.to_excel(output_path, index=False, sheet_name=ANNOTATION_SHEET_NAME)
        format_annotation_workbook(output_path)
        add_instruction_sheet(output_path, annotator_id)


def write_admin_files(
    df: pd.DataFrame,
    source_columns: List[str],
    manifest: pd.DataFrame,
    admin_dir: Path,
) -> None:
    admin_dir.mkdir(parents=True, exist_ok=True)

    # La clé contient toutes les colonnes source, plus la ligne d'origine.
    gold_columns = source_columns + ["source_row"]
    gold = df[gold_columns].copy()
    gold.to_excel(admin_dir / "gold_reference.xlsx", index=False, sheet_name="GOLD")

    manifest = manifest.sort_values(
        ["annotator_id", "Axe", "item_id", "assignment_slot"]
    )
    manifest.to_excel(
        admin_dir / "assignment_manifest.xlsx",
        index=False,
        sheet_name="ASSIGNMENTS",
    )

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

    with pd.ExcelWriter(
        admin_dir / "allocation_summary.xlsx",
        engine="openpyxl",
    ) as writer:
        total_summary.to_excel(writer, index=False, sheet_name="BY_ANNOTATOR")
        axis_summary.to_excel(writer, index=False, sheet_name="BY_AXIS")
        item_summary.to_excel(writer, index=False, sheet_name="BY_AXIS_TOTAL")


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Divise la feuille 'Binary questions' entre 9 annotateurs. "
            "Tous les items sont tacites et sont assignés à deux annotateurs."
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
        default=Path("binary_questions_annotation_output"),
        help=(
            "Dossier de sortie "
            "(défaut : binary_questions_annotation_output)."
        ),
    )
    args = parser.parse_args()

    input_file = args.input_file.resolve()
    output_dir = args.output_dir.resolve()
    annotators_dir = output_dir / "annotateurs"
    admin_dir = output_dir / "admin"

    if not input_file.exists():
        raise FileNotFoundError(f"Fichier introuvable : {input_file}")

    df, source_columns = prepare_dataframe(input_file)
    assignments, manifest = assign_items(df)
    create_annotator_files(df, source_columns, assignments, annotators_dir)
    write_admin_files(df, source_columns, manifest, admin_dir)

    print("=" * 72)
    print("Répartition des questions binaires terminée.")
    print(f"Source : {input_file}")
    print(f"Feuille : {SHEET_NAME}")
    print(f"Sortie : {output_dir}")
    print(f"Nombre d'items : {len(df)}")
    print(f"Nombre total de jugements : {len(manifest)}")
    print("Tous les items sont tacites et reçoivent 2 annotations.")
    print("-" * 72)

    load = (
        manifest.groupby(["annotator_id"])
        .size()
        .rename("judgments")
        .reset_index()
    )
    for _, row in load.iterrows():
        print(
            f"{row['annotator_id']}: {row['judgments']} jugements"
        )

    print("-" * 72)
    print("Fichiers annotateurs :", annotators_dir)
    print("Fichiers administrateur :", admin_dir)
    print("Ne partage pas admin/gold_reference.xlsx avec les annotateurs.")
    print("=" * 72)


if __name__ == "__main__":
    main()
