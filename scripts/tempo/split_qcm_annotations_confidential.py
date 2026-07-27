
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

SHEET_NAME = "QCM"
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

# Facultatif : renseigner les régions pour imposer, sur les items tacites,
# deux annotateurs de régions différentes. Laisser vide si l'information
# n'est pas disponible.
ANNOTATOR_REGIONS: Dict[str, str] = {
    # "ANN_01": "Rabat-Salé-Kénitra",
    # "ANN_02": "Souss-Massa",
}

REQUIRED_COLUMNS = [
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
    "correct_answer",
    "item_id",
]

ANNOTATION_COLUMNS = [
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


# ---------------------------------------------------------------------------
# OUTILS
# ---------------------------------------------------------------------------

def normalize_text(value: object) -> str:
    """Normalise un libellé pour effectuer des correspondances robustes."""
    text = "" if pd.isna(value) else str(value)
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.lower().strip()
    text = re.sub(r"[_/–—-]+", " ", text)
    text = re.sub(r"[’'`]+", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text


def safe_filename(text: str) -> str:
    """Crée un nom de fichier compatible Windows/macOS/Linux."""
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = re.sub(r'[<>:"/\\|?*]+', "_", text)
    text = re.sub(r"\s+", "_", text.strip())
    return text


def normalize_correct_answer(value: object) -> str:
    """
    Accepte A/B/C/D, response_A, option A, etc., et renvoie A/B/C/D.
    Lève une erreur pour une clé invalide.
    """
    if pd.isna(value):
        raise ValueError("correct_answer vide")
    text = normalize_text(value).upper()
    aliases = {
        "A": "A", "B": "B", "C": "C", "D": "D",
        "RESPONSE A": "A", "RESPONSE B": "B",
        "RESPONSE C": "C", "RESPONSE D": "D",
        "OPTION A": "A", "OPTION B": "B",
        "OPTION C": "C", "OPTION D": "D",
    }
    if text in aliases:
        return aliases[text]
    match = re.fullmatch(r"(?:RESPONSE|OPTION)?\s*([ABCD])", text)
    if match:
        return match.group(1)
    raise ValueError(f"correct_answer invalide : {value!r}")


def prepare_dataframe(input_file: Path) -> pd.DataFrame:
    """Lit QCM, nettoie les colonnes et valide les données, y compris item_type."""
    df = pd.read_excel(input_file, sheet_name=SHEET_NAME, dtype=object)

    # Supprime les colonnes Excel vides du type "Unnamed: 12".
    df = df.loc[:, ~df.columns.astype(str).str.match(r"^Unnamed:")]
    df.columns = [str(c).strip() for c in df.columns]

    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise KeyError(
            "Colonnes obligatoires absentes de la feuille QCM : "
            + ", ".join(missing)
        )

    # Ne conserve que les colonnes utiles, dans l'ordre attendu.
    df = df[REQUIRED_COLUMNS].copy()

    # Retire les lignes totalement vides.
    df = df.dropna(how="all").reset_index(drop=True)
    if df.empty:
        raise ValueError("La feuille QCM ne contient aucun item.")

    # Garde une trace de la ligne d'origine dans Excel (en-tête = ligne 1).
    df["source_row"] = df.index + 2

    # Nettoyage des item_id.
    df["item_id"] = df["item_id"].apply(
        lambda x: "" if pd.isna(x) else str(x).strip()
    )

    existing_ids = {x for x in df["item_id"] if x}
    next_number = 1
    generated_ids = []

    for current_id in df["item_id"]:
        if current_id:
            generated_ids.append(current_id)
            continue

        while f"MCQ_{next_number:04d}" in existing_ids:
            next_number += 1
        new_id = f"MCQ_{next_number:04d}"
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

    # Valide et normalise la clé.
    errors = []
    normalized_answers = []
    for idx, value in df["correct_answer"].items():
        try:
            normalized_answers.append(normalize_correct_answer(value))
        except ValueError as exc:
            errors.append(f"ligne Excel {idx + 2}: {exc}")
            normalized_answers.append(None)

    if errors:
        raise ValueError(
            "Clés correct_answer invalides :\n- " + "\n- ".join(errors[:30])
        )

    df["correct_answer"] = normalized_answers

    # Lit directement item_type depuis le fichier source.
    # Les seules valeurs autorisées sont documented et tacit.
    item_type_errors = []
    normalized_item_types = []
    for idx, value in df["item_type"].items():
        item_type = normalize_text(value)
        if item_type in {"documented", "tacit"}:
            normalized_item_types.append(item_type)
        else:
            displayed = "vide" if pd.isna(value) or not str(value).strip() else repr(value)
            item_type_errors.append(
                f"ligne Excel {idx + 2}: item_type {displayed}; "
                "valeur attendue = documented ou tacit"
            )
            normalized_item_types.append(None)

    if item_type_errors:
        raise ValueError(
            "Valeurs item_type invalides :\n- " + "\n- ".join(item_type_errors[:30])
        )

    df["item_type"] = normalized_item_types
    return df


def different_regions(ann1: str, ann2: str) -> bool:
    """
    Renvoie True si la contrainte régionale est satisfaite.
    Si une région manque, la paire reste autorisée.
    """
    r1 = ANNOTATOR_REGIONS.get(ann1, "").strip()
    r2 = ANNOTATOR_REGIONS.get(ann2, "").strip()
    if not r1 or not r2:
        return True
    return normalize_text(r1) != normalize_text(r2)


def assign_items(
    df: pd.DataFrame,
) -> Tuple[Dict[str, List[int]], pd.DataFrame]:
    """
    Attribution stratifiée par Axe :
    - documented : 1 annotateur par item ;
    - tacit : 2 annotateurs distincts par item ;
    - équilibre la charge globale et la charge par axe ;
    - limite la répétition des mêmes paires ;
    - respecte les régions différentes si ANNOTATOR_REGIONS est renseigné.
    """
    rng = random.Random(RANDOM_SEED)
    annotator_ids = ANNOTATORS[:]

    assignments: Dict[str, List[int]] = {a_id: [] for a_id in annotator_ids}
    total_load = Counter({a_id: 0 for a_id in annotator_ids})
    axis_load = defaultdict(Counter)
    pair_count = Counter()
    manifest_rows = []

    # Mélange l'ordre des axes pour ne pas favoriser toujours les mêmes personnes.
    axes = list(df["Axe"].drop_duplicates())
    rng.shuffle(axes)

    for axis in axes:
        axis_indices = df.index[df["Axe"] == axis].tolist()
        rng.shuffle(axis_indices)

        documented_indices = [
            idx for idx in axis_indices if df.at[idx, "item_type"] == "documented"
        ]
        tacit_indices = [
            idx for idx in axis_indices if df.at[idx, "item_type"] == "tacit"
        ]

        # 1 vote de validation pour les documented.
        for idx in documented_indices:
            candidates = annotator_ids[:]
            rng.shuffle(candidates)
            chosen = min(
                candidates,
                key=lambda ann: (
                    axis_load[str(axis)][ann],
                    total_load[ann],
                    rng.random(),
                ),
            )
            assignments[chosen].append(idx)
            axis_load[str(axis)][chosen] += 1
            total_load[chosen] += 1

            manifest_rows.append({
                "item_id": df.at[idx, "item_id"],
                "item_type": "documented",
                "Axe": axis,
                "annotator_id": chosen,
                "assignment_slot": 1,
            })

        # 2 votes indépendants pour les tacit.
        all_pairs = [
            pair
            for pair in itertools.combinations(annotator_ids, 2)
            if different_regions(pair[0], pair[1])
        ]
        if not all_pairs:
            raise ValueError(
                "Aucune paire d'annotateurs ne satisfait la contrainte régionale."
            )

        for idx in tacit_indices:
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
            pair_key = tuple(sorted(chosen_pair))
            pair_count[pair_key] += 1

            for slot, chosen in enumerate(chosen_pair, start=1):
                assignments[chosen].append(idx)
                axis_load[str(axis)][chosen] += 1
                total_load[chosen] += 1

                manifest_rows.append({
                    "item_id": df.at[idx, "item_id"],
                    "item_type": "tacit",
                    "Axe": axis,
                    "annotator_id": chosen,
                        "assignment_slot": slot,
                })

    manifest = pd.DataFrame(manifest_rows)

    # Contrôles de cardinalité.
    counts = manifest.groupby("item_id").size()
    expected = df.set_index("item_id")["item_type"].map(
        {"documented": 1, "tacit": 2}
    )
    mismatches = counts.reindex(expected.index, fill_value=0) != expected
    if mismatches.any():
        bad_ids = expected.index[mismatches].tolist()
        raise RuntimeError(
            "Erreur interne d'attribution pour : " + ", ".join(bad_ids[:20])
        )

    return assignments, manifest


def add_instruction_sheet(workbook_path: Path, annotator_id: str) -> None:
    wb = load_workbook(workbook_path)
    ws = wb.create_sheet("INSTRUCTIONS", 0)

    instructions = [
        ("Fichier d'annotation QCM", ""),
        ("Identifiant", annotator_id),
        ("", ""),
        ("Règles générales", ""),
        ("1", "Répondre à chaque item dans annotator_answer : A, B, C ou D."),
        ("2", "Pour un item documented : recherche autorisée et encouragée ; annotator_sources obligatoire."),
        ("3", "Pour un item tacit : recherche interdite ; répondre à l'intuition native et immédiate."),
        ("4", "Ne pas modifier item_id, les questions, les options ni les colonnes d'identification."),
        ("5", "Utiliser les trois colonnes de signalement, même lorsque tout est correct."),
        ("", ""),
        ("Valeurs attendues", ""),
        ("flag_language", "ok / problème"),
        ("flag_safety", "ok / problème"),
        (
            "flag_item",
            "ok / distracteur invalide / plusieurs réponses correctes / question mal posée",
        ),
        ("comment", "Facultatif, une ligne concise."),
    ]

    for row_idx, (left, right) in enumerate(instructions, start=1):
        ws.cell(row=row_idx, column=1, value=left)
        ws.cell(row=row_idx, column=2, value=right)

    ws["A1"].font = Font(bold=True, size=14)
    ws["A1"].fill = PatternFill("solid", fgColor="D9EAF7")
    ws["A5"].font = Font(bold=True)
    ws["A13"].font = Font(bold=True)

    ws.column_dimensions["A"].width = 24
    ws.column_dimensions["B"].width = 105
    for row in ws.iter_rows():
        for cell in row:
            cell.alignment = Alignment(vertical="top", wrap_text=True)

    wb.save(workbook_path)


def format_annotation_workbook(workbook_path: Path) -> None:
    wb = load_workbook(workbook_path)
    ws = wb["QCM_ANNOTATION"]

    # Style d'en-tête.
    header_fill = PatternFill("solid", fgColor="D9EAF7")
    for cell in ws[1]:
        cell.font = Font(bold=True)
        cell.fill = header_fill
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)

    ws.freeze_panes = "A2"
    ws.auto_filter.ref = ws.dimensions
    ws.sheet_view.showGridLines = False

    # Largeurs de colonnes adaptées.
    widths = {
        "item_id": 15,
        "item_type": 14,
        "Axe": 28,
        "Difficulty": 13,
        "intent_group": 25,
        "intent_category": 28,
        "input": 55,
        "response_A": 38,
        "response_B": 38,
        "response_C": 38,
        "response_D": 38,
        "annotator_id": 14,
        "annotator_answer": 18,
        "annotator_sources": 45,
        "flag_language": 18,
        "flag_safety": 18,
        "flag_item": 28,
        "comment": 45,
    }

    header_to_col = {cell.value: cell.column for cell in ws[1]}
    for header, width in widths.items():
        col_idx = header_to_col[header]
        ws.column_dimensions[get_column_letter(col_idx)].width = width

    for row in ws.iter_rows(min_row=2):
        for cell in row:
            cell.alignment = Alignment(vertical="top", wrap_text=True)

    last_row = max(ws.max_row, 2)

    # Listes déroulantes.
    dv_answer = DataValidation(type="list", formula1='"A,B,C,D"', allow_blank=False)
    dv_binary = DataValidation(type="list", formula1='"ok,problème"', allow_blank=False)
    dv_item = DataValidation(
        type="list",
        formula1='"ok,distracteur invalide,plusieurs réponses correctes,question mal posée"',
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

    # Fige aussi la première colonne visuellement.
    ws.row_dimensions[1].height = 36

    wb.save(workbook_path)


def write_admin_files(
    df: pd.DataFrame,
    manifest: pd.DataFrame,
    admin_dir: Path,
) -> None:
    admin_dir.mkdir(parents=True, exist_ok=True)

    # Clé d'origine : ne jamais envoyer aux annotateurs.
    gold_columns = [
        "item_id",
        "correct_answer",
        "Axe",
        "item_type",
        "source_row",
    ]
    gold = df[gold_columns].copy()
    gold.to_excel(admin_dir / "gold_reference.xlsx", index=False, sheet_name="GOLD")

    # Manifest d'attribution utile pour la consolidation.
    manifest = manifest.sort_values(
        ["annotator_id", "Axe", "item_id", "assignment_slot"]
    )
    manifest.to_excel(
        admin_dir / "assignment_manifest.xlsx",
        index=False,
        sheet_name="ASSIGNMENTS",
    )

    # Rapport de charge global et par axe.
    total_summary = (
        manifest.groupby(["annotator_id"], as_index=False)
        .agg(
            total_judgments=("item_id", "count"),
            documented_judgments=("item_type", lambda s: int((s == "documented").sum())),
            tacit_judgments=("item_type", lambda s: int((s == "tacit").sum())),
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
        df.groupby(["Axe", "item_type"], as_index=False)
        .agg(number_of_items=("item_id", "count"))
    )
    item_summary["expected_judgments"] = item_summary.apply(
        lambda r: r["number_of_items"] * (1 if r["item_type"] == "documented" else 2),
        axis=1,
    )

    with pd.ExcelWriter(
        admin_dir / "allocation_summary.xlsx",
        engine="openpyxl",
    ) as writer:
        total_summary.to_excel(writer, index=False, sheet_name="BY_ANNOTATOR")
        axis_summary.to_excel(writer, index=False, sheet_name="BY_AXIS")
        item_summary.to_excel(writer, index=False, sheet_name="BY_ITEM_TYPE")


def create_annotator_files(
    df: pd.DataFrame,
    assignments: Dict[str, List[int]],
    annotators_dir: Path,
) -> None:
    annotators_dir.mkdir(parents=True, exist_ok=True)
    rng = random.Random(RANDOM_SEED + 1)

    for annotator_id in ANNOTATORS:
        row_indices = assignments[annotator_id][:]
        rng.shuffle(row_indices)

        out = df.loc[row_indices, [
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
        ]].copy()

        out["annotator_id"] = annotator_id
        out["annotator_answer"] = ""
        out["annotator_sources"] = ""
        out["flag_language"] = ""
        out["flag_safety"] = ""
        out["flag_item"] = ""
        out["comment"] = ""
        out = out[ANNOTATION_COLUMNS]

        filename = f"{annotator_id}.xlsx"
        output_path = annotators_dir / filename

        out.to_excel(
            output_path,
            index=False,
            sheet_name="QCM_ANNOTATION",
        )
        format_annotation_workbook(output_path)
        add_instruction_sheet(output_path, annotator_id)


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Divise la feuille QCM entre 9 annotateurs en utilisant la colonne "
            "item_type déjà présente (documented/tacit)."
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
        default=Path("qcm_annotation_output"),
        help="Dossier de sortie (défaut : qcm_annotation_output).",
    )
    args = parser.parse_args()

    input_file = args.input_file.resolve()
    output_dir = args.output_dir.resolve()
    annotators_dir = output_dir / "annotateurs"
    admin_dir = output_dir / "admin"

    if not input_file.exists():
        raise FileNotFoundError(f"Fichier introuvable : {input_file}")

    df = prepare_dataframe(input_file)
    assignments, manifest = assign_items(df)

    create_annotator_files(df, assignments, annotators_dir)
    write_admin_files(df, manifest, admin_dir)

    print("=" * 72)
    print("Répartition terminée.")
    print(f"Source : {input_file}")
    print(f"Sortie : {output_dir}")
    print(f"Nombre d'items : {len(df)}")
    print(f"Items documented : {(df['item_type'] == 'documented').sum()}")
    print(f"Items tacit : {(df['item_type'] == 'tacit').sum()}")
    print(f"Nombre total de jugements : {len(manifest)}")
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
