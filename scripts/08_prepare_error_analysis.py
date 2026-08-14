#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
08_prepare_error_analysis.py
============================
Reproducible item-level error analysis for the Moroccan Alignment Benchmark.

Implements the analyses requested in the paper notes:
  1) Which items defeat even the strongest models? (top-5 within each format)
  2) Hardness vs discrimination (top-5 minus bottom-5 item accuracy)
  3) MCQ documented-vs-tacit "attestation hypothesis", including a logistic
     regression with model and axis fixed effects and item-clustered SEs.

It also exports supporting diagnostics that are useful when writing the section:
  - enrichment ratios + Fisher exact tests + BH/FDR correction
  - human difficulty vs empirical hardness
  - negative-discrimination / suspicious-item queue
  - long response-level table for reproducibility
  - deterministic manual-review candidate workbook
  - figures and a concise Markdown fact sheet

Run from the repository root:
    python scripts/08_prepare_error_analysis.py

Dependencies:
    pandas numpy scipy statsmodels matplotlib openpyxl
"""

from __future__ import annotations

import json
import math
import re
import sys
import unicodedata
import warnings
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd
from scipy.stats import fisher_exact, kruskal, mannwhitneyu, spearmanr

try:
    import statsmodels.api as sm
    import statsmodels.formula.api as smf
    from statsmodels.stats.multitest import multipletests
except ImportError as e:
    raise SystemExit(
        "Missing statsmodels. Install dependencies with:\n"
        "  pip install pandas numpy scipy statsmodels matplotlib openpyxl\n"
    ) from e

import matplotlib.pyplot as plt


# -----------------------------------------------------------------------------
# CONFIGURATION
# -----------------------------------------------------------------------------

TOP_K = 5
BOTTOM_K = 5
CONSENSUS_HARD_THRESHOLD = 0.60   # >= 3/5 top systems fail
CONSENSUS_EASY_THRESHOLD = 0.20   # <= 1/5 top systems fail
NEGATIVE_DISCRIM_THRESHOLD = 0.0
MANUAL_REVIEW_TARGET = 420
RANDOM_SEED = 20260814
PARSER_VALIDATION_TOLERANCE = 0.005


@dataclass(frozen=True)
class FormatConfig:
    name: str
    short_name: str
    metadata_path: str
    score_path: str
    raw_response_path: Optional[str]
    gold_col: str
    expected_n: Optional[int] = None


FORMAT_CONFIGS = [
    FormatConfig(
        name="MCQ",
        short_name="mcq",
        metadata_path="data/02_final_benchmark/qcm_final_no_responses.xlsx",
        score_path="outputs/qcm_final_scores.xlsx",
        raw_response_path="outputs/model_responses/qcm_final_with_responses.xlsx",
        gold_col="final_answer",
        expected_n=577,
    ),
    FormatConfig(
        name="Binary",
        short_name="binary",
        metadata_path="data/02_final_benchmark/final_binary_no_responses.xlsx",
        score_path="outputs/final_binary_scores.xlsx",
        raw_response_path="outputs/model_responses/final_binary_with_responses.xlsx",
        gold_col="final_answer",
        expected_n=231,
    ),
    FormatConfig(
        name="ShortAnswer",
        short_name="sa",
        metadata_path="data/02_final_benchmark/final_shorts_no_responses.xlsx",
        score_path="outputs/final_short_answers_scores_llm_judge.xlsx",
        raw_response_path="outputs/model_responses/short_answers_final_with_responses.xlsx",
        gold_col="answer",
        expected_n=284,
    ),
]


# Optional model-family labels. These are descriptive only; they do not affect
# the core top-5 / bottom-5 definitions, which are always format-specific.
MODEL_FAMILY = {
    "gemini3_6_flash": "proprietary_api",
    "gpt5": "proprietary_api",
    "claude_sonnet5": "proprietary_api",
    "grok4_20": "proprietary_api",
    "gemma4_31b": "general_multilingual",
    "gemma4_26b": "general_multilingual",
    "aya_expanse_32b": "general_multilingual",
    "commandr": "general_multilingual",
    "qwen3_6_27b": "general_multilingual",
    "qwen3_5_9b": "general_multilingual",
    "gptoss_20b": "general_multilingual",
    "mistral_24b": "general_multilingual",
    "allam_7b": "arabic_centric",
    "jais2_8b_bf16": "arabic_centric",
    "mistral_saba": "arabic_centric",
    "atlaschat_27b": "moroccan_adapted",
    "gemmaroc_27b": "moroccan_adapted",
}


# -----------------------------------------------------------------------------
# PATH / NAME HELPERS
# -----------------------------------------------------------------------------


def find_repo_root() -> Path:
    """Find repository root whether called from root, scripts/, or elsewhere."""
    candidates: List[Path] = []
    try:
        candidates.append(Path(__file__).resolve().parent)
    except NameError:
        pass
    candidates.append(Path.cwd().resolve())

    seen = set()
    for start in candidates:
        for p in [start, *start.parents]:
            if p in seen:
                continue
            seen.add(p)
            if (p / "data").exists() and (p / "outputs").exists():
                return p
    raise FileNotFoundError(
        "Could not locate repository root. Run this script from the repo or place "
        "it under repo/scripts/."
    )


def slug(x: object) -> str:
    if x is None or (isinstance(x, float) and np.isnan(x)):
        return ""
    s = unicodedata.normalize("NFKD", str(x))
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = s.lower().strip()
    s = re.sub(r"[^a-z0-9]+", "_", s)
    return s.strip("_")


def model_key(x: object) -> str:
    return slug(x).replace("response_", "")


def canonical_axis(x: object) -> str:
    s = slug(x)
    mapping = {
        "history": "History",
        "culture": "Culture",
        "nativeness": "Nativeness",
        "respect_et_normes_sociales": "Social Norms",
        "respect_normes_sociales": "Social Norms",
        "social_norms": "Social Norms",
        "identite_marocaine": "National Identity",
        "national_identity": "National Identity",
        "geography": "Geography",
        "monarchy": "Monarchy",
        "religion": "Religion",
        "religion_and_spiritual_values": "Religion",
        "religion_spiritual_values": "Religion",
    }
    return mapping.get(s, str(x).strip() if pd.notna(x) else "Unknown")


def canonical_difficulty(x: object) -> str:
    s = slug(x)
    if s in {"easy", "medium", "hard"}:
        return s
    return s or "unknown"


def canonical_item_type(x: object) -> str:
    s = slug(x)
    if s in {"documented", "tacit"}:
        return s
    return s or "unknown"


def ensure_exists(path: Path, required: bool = True) -> bool:
    ok = path.exists()
    if required and not ok:
        raise FileNotFoundError(f"Required file not found: {path}")
    return ok


# -----------------------------------------------------------------------------
# EXCEL LOADING / COLUMN DETECTION
# -----------------------------------------------------------------------------


def read_sheet_with_column(path: Path, required_col: str = "item_id") -> Tuple[str, pd.DataFrame]:
    """Read the first sheet containing required_col."""
    xls = pd.ExcelFile(path)
    for sheet in xls.sheet_names:
        df = pd.read_excel(path, sheet_name=sheet)
        if required_col in df.columns:
            return sheet, df
    raise ValueError(f"No sheet containing '{required_col}' in {path}")


def read_metadata(path: Path) -> pd.DataFrame:
    _, df = read_sheet_with_column(path, "item_id")
    df = df.copy()
    df["item_id"] = df["item_id"].astype(str).str.strip()

    ren = {}
    if "Axe" in df.columns:
        ren["Axe"] = "axis"
    if "Difficulty" in df.columns:
        ren["Difficulty"] = "difficulty"
    df = df.rename(columns=ren)

    if "axis" in df.columns:
        df["axis_raw"] = df["axis"]
        df["axis"] = df["axis"].map(canonical_axis)
    else:
        df["axis"] = "Unknown"

    if "difficulty" in df.columns:
        df["difficulty_raw"] = df["difficulty"]
        df["difficulty"] = df["difficulty"].map(canonical_difficulty)
    else:
        df["difficulty"] = "unknown"

    if "item_type" in df.columns:
        df["item_type"] = df["item_type"].map(canonical_item_type)

    for c in ["intent_group", "intent_category", "status"]:
        if c not in df.columns:
            df[c] = np.nan
    return df


def read_overview(score_path: Path) -> pd.DataFrame:
    xls = pd.ExcelFile(score_path)
    target = None
    for sh in xls.sheet_names:
        if slug(sh) == "overview":
            target = sh
            break
    if target is None:
        raise ValueError(f"No Overview sheet in {score_path}")
    df = pd.read_excel(score_path, sheet_name=target).copy()
    if "modele" not in df.columns or "exactitude" not in df.columns:
        raise ValueError(f"Overview in {score_path} lacks modele/exactitude")
    df = df[pd.notna(df["modele"])].copy()
    df["model"] = df["modele"].astype(str).str.strip().map(model_key)

    # `exactitude` in the closed-format scorer is coverage-conditional
    # (correct / parsed).  The paper's primary metric, however, is strict
    # accuracy (correct / all items), so derive that directly from the counts
    # whenever they are available.  This matters for MCQ models with coverage
    # below 100% (notably ALLaM and Mistral-Small in the current results).
    df["accuracy_conditional"] = pd.to_numeric(df["exactitude"], errors="coerce")
    if "n_correct" in df.columns and "n_total" in df.columns:
        n_correct = pd.to_numeric(df["n_correct"], errors="coerce")
        n_total = pd.to_numeric(df["n_total"], errors="coerce")
        strict = n_correct.div(n_total.where(n_total.ne(0)))
        df["accuracy"] = strict.fillna(df["accuracy_conditional"])
    else:
        df["accuracy"] = df["accuracy_conditional"]

    if "couverture" in df.columns:
        df["coverage"] = pd.to_numeric(df["couverture"], errors="coerce")

    df = df[pd.notna(df["accuracy"])].sort_values("accuracy", ascending=False).reset_index(drop=True)
    df["rank_recomputed"] = np.arange(1, len(df) + 1)
    df["family"] = df["model"].map(MODEL_FAMILY).fillna("other")
    return df


def coerce_bool_series(s: pd.Series) -> pd.Series:
    def conv(v):
        if pd.isna(v):
            return np.nan
        if isinstance(v, (bool, np.bool_)):
            return bool(v)
        if isinstance(v, (int, np.integer)):
            if v in (0, 1):
                return bool(v)
        if isinstance(v, float) and not np.isnan(v) and v in (0.0, 1.0):
            return bool(int(v))
        t = str(v).strip().lower()
        if t in {"true", "t", "1", "yes", "y", "correct", "ok"}:
            return True
        if t in {"false", "f", "0", "no", "n", "incorrect", "wrong"}:
            return False
        return np.nan
    # Use pandas' nullable BooleanDtype so fillna(False) does not trigger the
    # object-downcasting FutureWarning in recent pandas versions.
    return s.map(conv).astype("boolean")


def detect_scored_detail(score_path: Path) -> Optional[Tuple[str, pd.DataFrame, Dict[str, str]]]:
    """
    Find an item-level sheet with model correctness columns.

    Returns (sheet_name, dataframe, model->correct_column) or None.
    Supports columns like:
      allam_7b_correct
      correct_allam_7b
    """
    xls = pd.ExcelFile(score_path)
    best = None
    best_score = -1
    for sh in xls.sheet_names:
        try:
            df = pd.read_excel(score_path, sheet_name=sh)
        except Exception:
            continue
        if "item_id" not in df.columns:
            continue

        corr_cols: Dict[str, str] = {}
        for c in df.columns:
            cs = slug(c)
            model = None
            if cs.endswith("_correct"):
                model = cs[:-8]
            elif cs.startswith("correct_"):
                model = cs[8:]
            if model:
                corr_cols[model_key(model)] = c

        score = 100 * len(corr_cols) + len(df)
        if corr_cols and score > best_score:
            best = (sh, df, corr_cols)
            best_score = score
    return best


def response_column_map(df: pd.DataFrame) -> Dict[str, str]:
    out = {}
    for c in df.columns:
        cs = slug(c)
        if cs.startswith("response_"):
            out[model_key(cs[len("response_"):])] = c
    return out


def reason_column_map(df: pd.DataFrame) -> Dict[str, str]:
    out = {}
    for c in df.columns:
        cs = slug(c)
        if cs.endswith("_raison_juge"):
            out[model_key(cs[:-12])] = c
        elif cs.endswith("_judge_reason"):
            out[model_key(cs[:-13])] = c
    return out


# -----------------------------------------------------------------------------
# CLOSED-FORMAT FALLBACK PARSER
# -----------------------------------------------------------------------------


def normalize_text(x: object) -> str:
    if x is None or pd.isna(x):
        return ""
    s = unicodedata.normalize("NFKC", str(x)).strip()
    s = re.sub(r"\s+", " ", s)
    return s


def normalize_match_text(x: object) -> str:
    s = normalize_text(x).lower()
    s = re.sub(r"[\s\u200e\u200f\u202a-\u202e]+", " ", s)
    s = re.sub(r"[\.,;:!?؟،؛\-–—_\(\)\[\]\{\}\"'`*#]+", "", s)
    return s.strip()


def valid_option_letters(row: pd.Series) -> List[str]:
    letters = []
    for L in "ABCD":
        c = f"response_{L}"
        if c in row.index and pd.notna(row[c]) and str(row[c]).strip() != "":
            letters.append(L)
    return letters


def parse_closed_response(raw: object, row: pd.Series) -> Optional[str]:
    """Best-effort fallback matching the paper's letter -> option-text -> normalized logic."""
    if raw is None or pd.isna(raw):
        return None
    txt = normalize_text(raw)
    if not txt:
        return None

    letters = valid_option_letters(row)
    if not letters:
        letters = ["A", "B"]

    # 1) exact / nearly exact letter answer
    compact = re.sub(r"[`*_#\s\.:;!?؟،؛\-–—\(\)\[\]\{\}]", "", txt).upper()
    if compact in letters:
        return compact

    # Common explicit final-answer phrasing.
    m = re.search(r"(?i)(?:final\s*answer|answer|choice|option|الجواب|الاختيار)\s*[:=\-]?\s*([A-D])\b", txt)
    if m and m.group(1).upper() in letters:
        return m.group(1).upper()

    # Unique standalone option letter anywhere in output.
    found = [L for L in letters if re.search(rf"(?<![A-Za-z]){L}(?![A-Za-z])", txt, flags=re.I)]
    found = sorted(set(x.upper() for x in found))
    if len(found) == 1:
        return found[0]

    # 2) verbatim option match
    stripped = txt.strip(" \t\n\r\"'`*#.:;!?؟،؛-–—()[]{}")
    verbatim = []
    for L in letters:
        c = f"response_{L}"
        if c in row.index and pd.notna(row[c]):
            opt = normalize_text(row[c])
            if stripped == opt:
                verbatim.append(L)
    if len(verbatim) == 1:
        return verbatim[0]

    # 3) normalized option match
    norm = normalize_match_text(txt)
    normalized = []
    for L in letters:
        c = f"response_{L}"
        if c in row.index and pd.notna(row[c]):
            opt = normalize_match_text(row[c])
            if norm == opt and opt:
                normalized.append(L)
    if len(normalized) == 1:
        return normalized[0]

    return None


# -----------------------------------------------------------------------------
# FORMAT -> LONG ITEM x MODEL TABLE
# -----------------------------------------------------------------------------


def build_format_long(root: Path, cfg: FormatConfig) -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, str]:
    meta_path = root / cfg.metadata_path
    score_path = root / cfg.score_path
    ensure_exists(meta_path)
    ensure_exists(score_path)

    meta = read_metadata(meta_path)
    if cfg.expected_n is not None and len(meta) != cfg.expected_n:
        warnings.warn(f"{cfg.name}: expected {cfg.expected_n} items, found {len(meta)} in {meta_path}")

    overview = read_overview(score_path)
    overview["format"] = cfg.name

    # Prefer existing item-level scorer output. This is important for short answer
    # because correctness is judge-based, and also avoids reimplementing closed
    # scoring when the scorer already exported item-level booleans.
    detail_info = detect_scored_detail(score_path)
    source = "scored_workbook"

    if detail_info is not None:
        sheet, detail, corr_map = detail_info
        detail = detail.copy()
        detail["item_id"] = detail["item_id"].astype(str).str.strip()
        resp_map = response_column_map(detail)
        reason_map = reason_column_map(detail)

        # Merge metadata from the released benchmark as source of truth.
        keep_meta = [c for c in meta.columns if c not in detail.columns or c == "item_id"]
        merged = detail.merge(meta[keep_meta], on="item_id", how="left", validate="one_to_one")

        rows = []
        available_models = set(corr_map)
        for model in overview["model"]:
            mk = model_key(model)
            if mk not in available_models:
                continue
            correct = coerce_bool_series(merged[corr_map[mk]]).fillna(False)
            response_col = resp_map.get(mk)
            reason_col = reason_map.get(mk)
            tmp = pd.DataFrame({
                "item_id": merged["item_id"],
                "model": mk,
                "correct": correct.astype(int),
                "response": merged[response_col] if response_col else np.nan,
                "judge_reason": merged[reason_col] if reason_col else np.nan,
            })
            rows.append(tmp)
        if not rows:
            detail_info = None
        else:
            long = pd.concat(rows, ignore_index=True)
            source += f":{sheet}"

    if detail_info is None:
        # Fallback is expected mainly for MCQ/Binary if their scored workbook does
        # not expose item-level correctness. Use released raw responses and the
        # deterministic option parser.
        if not cfg.raw_response_path:
            raise RuntimeError(f"{cfg.name}: no item-level correctness and no raw response file configured")
        raw_path = root / cfg.raw_response_path
        ensure_exists(raw_path)
        _, raw = read_sheet_with_column(raw_path, "item_id")
        raw = raw.copy()
        raw["item_id"] = raw["item_id"].astype(str).str.strip()
        resp_map = response_column_map(raw)
        merged = meta.merge(
            raw[["item_id", *[c for c in raw.columns if c.startswith("response_") and c not in meta.columns]]],
            on="item_id", how="left", validate="one_to_one"
        )
        rows = []
        for model in overview["model"]:
            mk = model_key(model)
            c = resp_map.get(mk)
            if c is None:
                continue
            preds = merged.apply(lambda r: parse_closed_response(r[c], r), axis=1)
            gold = merged[cfg.gold_col].astype(str).str.strip().str.upper()
            correct = preds.fillna("").str.upper().eq(gold)
            rows.append(pd.DataFrame({
                "item_id": merged["item_id"],
                "model": mk,
                "correct": correct.astype(int),
                "response": merged[c],
                "parsed_answer": preds,
                "judge_reason": np.nan,
            }))
        if not rows:
            raise RuntimeError(f"{cfg.name}: could not derive model response columns from {raw_path}")
        long = pd.concat(rows, ignore_index=True)
        source = f"fallback_parser:{raw_path.name}"

    # Attach metadata to long table.
    meta_cols = [
        "item_id", "axis", "difficulty", "intent_group", "intent_category",
        "item_type", "status", "input", cfg.gold_col,
        "response_A", "response_B", "response_C", "response_D",
        "primary_accepted_variants", "second_accepted_variants",
        "annotator_1_sources", "all_supporting_sources",
    ]
    meta_cols = [c for c in meta_cols if c in meta.columns]
    long = long.merge(meta[meta_cols], on="item_id", how="left", validate="many_to_one")
    long["format"] = cfg.name
    long["model"] = long["model"].map(model_key)
    long["family"] = long["model"].map(MODEL_FAMILY).fillna("other")
    long["correct"] = pd.to_numeric(long["correct"], errors="coerce").fillna(0).astype(int)

    # Validate item-level recomputed strict accuracy against the strict
    # Overview accuracy derived above (n_correct / n_total).
    recomputed = long.groupby("model", as_index=False)["correct"].mean().rename(columns={"correct": "accuracy_recomputed"})
    check = overview[["model", "accuracy"]].merge(recomputed, on="model", how="left")
    check["abs_diff"] = (check["accuracy"] - check["accuracy_recomputed"]).abs()
    bad = check[check["abs_diff"] > PARSER_VALIDATION_TOLERANCE]
    if len(bad):
        warnings.warn(
            f"{cfg.name}: {len(bad)} model(s) differ from Overview by > "
            f"{PARSER_VALIDATION_TOLERANCE:.3f}. See validation sheet. Source={source}."
        )

    return meta, overview, long, source


# -----------------------------------------------------------------------------
# TOP/BOTTOM MODELS, HARDNESS, DISCRIMINATION
# -----------------------------------------------------------------------------


def compute_item_metrics(meta: pd.DataFrame, overview: pd.DataFrame, long: pd.DataFrame, cfg: FormatConfig) -> Tuple[pd.DataFrame, List[str], List[str]]:
    available = set(long["model"].unique())
    ranking = [m for m in overview.sort_values("accuracy", ascending=False)["model"].tolist() if m in available]
    if len(ranking) < TOP_K + BOTTOM_K:
        warnings.warn(f"{cfg.name}: only {len(ranking)} scored models available")
    top = ranking[:min(TOP_K, len(ranking))]
    bottom = ranking[-min(BOTTOM_K, len(ranking)):]

    piv = long.pivot_table(index="item_id", columns="model", values="correct", aggfunc="first")
    top_acc = piv[top].mean(axis=1)
    bottom_acc = piv[bottom].mean(axis=1)
    all_acc = piv.mean(axis=1)

    # `piv.index` is already named item_id.  Build the frame with that index
    # and reset it exactly once; otherwise pandas tries to insert a second
    # item_id column and raises: ValueError: cannot insert item_id, already exists.
    metrics = pd.DataFrame({
        "top5_accuracy": top_acc,
        "bottom5_accuracy": bottom_acc,
        "all_model_accuracy": all_acc,
        "hardness": 1.0 - top_acc,
        "discrimination": top_acc - bottom_acc,
    }, index=piv.index).reset_index()
    metrics["consensus_hard"] = metrics["hardness"] >= CONSENSUS_HARD_THRESHOLD - 1e-12
    metrics["universally_hard"] = metrics["hardness"] >= 1.0 - 1e-12
    metrics["consensus_easy"] = metrics["hardness"] <= CONSENSUS_EASY_THRESHOLD + 1e-12
    metrics["negative_discrimination"] = metrics["discrimination"] < NEGATIVE_DISCRIM_THRESHOLD - 1e-12
    metrics["format"] = cfg.name

    # Join the released item metadata.
    metrics = meta.merge(metrics, on="item_id", how="left", validate="one_to_one")

    # Add compact diagnostic signatures.
    def failed_models(item_id: str, models: Sequence[str]) -> str:
        x = long[(long["item_id"] == item_id) & (long["model"].isin(models)) & (long["correct"] == 0)]
        return " | ".join(x["model"].tolist())

    def correct_models(item_id: str, models: Sequence[str]) -> str:
        x = long[(long["item_id"] == item_id) & (long["model"].isin(models)) & (long["correct"] == 1)]
        return " | ".join(x["model"].tolist())

    metrics["top5_failed_models"] = metrics["item_id"].map(lambda x: failed_models(x, top))
    metrics["bottom5_correct_models"] = metrics["item_id"].map(lambda x: correct_models(x, bottom))

    return metrics, top, bottom


# -----------------------------------------------------------------------------
# ENRICHMENT ANALYSIS
# -----------------------------------------------------------------------------


def enrichment_table(metrics: pd.DataFrame, features: Sequence[str]) -> pd.DataFrame:
    rows = []
    for feature in features:
        if feature not in metrics.columns:
            continue
        sub = metrics[pd.notna(metrics[feature])].copy()
        sub = sub[sub[feature].astype(str).str.strip() != ""]
        if sub.empty:
            continue
        hard = sub["consensus_hard"].astype(bool)
        n_all = len(sub)
        n_hard = int(hard.sum())
        if n_hard == 0:
            continue

        for value, g in sub.groupby(feature, dropna=True):
            val_mask = sub[feature].eq(value)
            a = int((hard & val_mask).sum())             # hard & value
            b = int((hard & ~val_mask).sum())            # hard & not value
            c = int((~hard & val_mask).sum())            # not hard & value
            d = int((~hard & ~val_mask).sum())           # not hard & not value
            base_share = (a + c) / n_all if n_all else np.nan
            hard_share = a / n_hard if n_hard else np.nan
            er = hard_share / base_share if base_share > 0 else np.nan
            try:
                odds, p_two = fisher_exact([[a, b], [c, d]], alternative="two-sided")
                _, p_over = fisher_exact([[a, b], [c, d]], alternative="greater")
            except Exception:
                odds, p_two, p_over = np.nan, np.nan, np.nan
            rows.append({
                "format": sub["format"].iloc[0] if "format" in sub.columns else "",
                "feature": feature,
                "value": value,
                "n_total": n_all,
                "n_hard": n_hard,
                "n_value": a + c,
                "n_hard_value": a,
                "base_share": base_share,
                "hard_share": hard_share,
                "enrichment_ratio": er,
                "odds_ratio": odds,
                "fisher_p_two_sided": p_two,
                "fisher_p_over": p_over,
            })

    out = pd.DataFrame(rows)
    if out.empty:
        return out

    out["fdr_q_global"] = multipletests(out["fisher_p_two_sided"].fillna(1.0), method="fdr_bh")[1]
    out["fdr_q_within_feature"] = np.nan
    for (_, feat), idx in out.groupby(["format", "feature"]).groups.items():
        p = out.loc[idx, "fisher_p_two_sided"].fillna(1.0).values
        out.loc[idx, "fdr_q_within_feature"] = multipletests(p, method="fdr_bh")[1]
    return out.sort_values(["format", "feature", "enrichment_ratio"], ascending=[True, True, False])


# -----------------------------------------------------------------------------
# HUMAN DIFFICULTY VS EMPIRICAL HARDNESS
# -----------------------------------------------------------------------------


def bootstrap_mean_ci(x: Sequence[float], n_boot: int = 5000, seed: int = RANDOM_SEED) -> Tuple[float, float]:
    arr = np.asarray(pd.Series(x).dropna(), dtype=float)
    if len(arr) == 0:
        return np.nan, np.nan
    if len(arr) == 1:
        return float(arr[0]), float(arr[0])
    rng = np.random.default_rng(seed)
    means = np.empty(n_boot)
    for i in range(n_boot):
        means[i] = rng.choice(arr, size=len(arr), replace=True).mean()
    return tuple(np.quantile(means, [0.025, 0.975]))


def difficulty_analysis(metrics: pd.DataFrame) -> Tuple[pd.DataFrame, pd.DataFrame]:
    rows = []
    tests = []
    for fmt, df in metrics.groupby("format"):
        d = df[df["difficulty"].isin(["easy", "medium", "hard"])].copy()
        for level in ["easy", "medium", "hard"]:
            g = d[d["difficulty"] == level]
            if g.empty:
                continue
            lo, hi = bootstrap_mean_ci(g["hardness"], seed=RANDOM_SEED + len(rows))
            rows.append({
                "format": fmt,
                "difficulty": level,
                "n_items": len(g),
                "mean_hardness": g["hardness"].mean(),
                "mean_hardness_ci_low": lo,
                "mean_hardness_ci_high": hi,
                "consensus_hard_n": int(g["consensus_hard"].sum()),
                "consensus_hard_rate": g["consensus_hard"].mean(),
                "universal_hard_n": int(g["universally_hard"].sum()),
                "negative_discrimination_n": int(g["negative_discrimination"].sum()),
                "all_model_accuracy": g["all_model_accuracy"].mean(),
            })

        enc = d["difficulty"].map({"easy": 1, "medium": 2, "hard": 3})
        rho, p = spearmanr(enc, d["hardness"], nan_policy="omit") if len(d) >= 3 else (np.nan, np.nan)
        groups = [d.loc[d["difficulty"] == lev, "hardness"].dropna().values for lev in ["easy", "medium", "hard"]]
        groups = [x for x in groups if len(x)]
        if len(groups) >= 2:
            kw_h, kw_p = kruskal(*groups)
        else:
            kw_h, kw_p = np.nan, np.nan
        tests.append({
            "format": fmt,
            "n_items": len(d),
            "spearman_rho_difficulty_vs_hardness": rho,
            "spearman_p": p,
            "kruskal_H": kw_h,
            "kruskal_p": kw_p,
        })
    return pd.DataFrame(rows), pd.DataFrame(tests)


# -----------------------------------------------------------------------------
# LOGISTIC REGRESSION HELPERS
# -----------------------------------------------------------------------------


def fit_clustered_logit(formula: str, df: pd.DataFrame, cluster_col: str) -> Tuple[pd.DataFrame, object]:
    """Binomial GLM with cluster-robust SEs; returns tidy coefficients + result."""
    model = smf.glm(formula=formula, data=df, family=sm.families.Binomial())
    res = model.fit(cov_type="cluster", cov_kwds={"groups": df[cluster_col]})
    ci = res.conf_int()
    tidy = pd.DataFrame({
        "term": res.params.index,
        "coef_log_odds": res.params.values,
        "std_error_clustered": res.bse.values,
        "z": res.tvalues.values,
        "p_value": res.pvalues.values,
        "ci_low_log_odds": ci[0].values,
        "ci_high_log_odds": ci[1].values,
    })
    tidy["odds_ratio"] = np.exp(tidy["coef_log_odds"])
    tidy["or_ci_low"] = np.exp(tidy["ci_low_log_odds"])
    tidy["or_ci_high"] = np.exp(tidy["ci_high_log_odds"])
    return tidy, res


def combined_difficulty_regression(long_all: pd.DataFrame) -> pd.DataFrame:
    d = long_all.copy()
    d = d[d["difficulty"].isin(["easy", "medium", "hard"])].copy()
    d["item_cluster"] = d["format"].astype(str) + ":" + d["item_id"].astype(str)
    d["correct_int"] = d["correct"].astype(int)
    if d.empty:
        return pd.DataFrame()
    formula = (
        "correct_int ~ C(model) + C(format) + C(axis) + "
        "C(difficulty, Treatment(reference='easy'))"
    )
    try:
        tidy, _ = fit_clustered_logit(formula, d, "item_cluster")
        return tidy
    except Exception as e:
        warnings.warn(f"Combined difficulty regression failed: {e}")
        return pd.DataFrame([{"term": "MODEL_FAILED", "error": str(e)}])


# -----------------------------------------------------------------------------
# ATTESTATION HYPOTHESIS: DOCUMENTED VS TACIT MCQ
# -----------------------------------------------------------------------------


def attestation_analysis(mcq_long: pd.DataFrame, mcq_metrics: pd.DataFrame, top_models: Sequence[str]) -> Dict[str, pd.DataFrame]:
    if "item_type" not in mcq_long.columns:
        warnings.warn("MCQ has no item_type column; attestation analysis skipped")
        return {}

    d = mcq_long[mcq_long["item_type"].isin(["documented", "tacit"])].copy()
    if d.empty or d["item_type"].nunique() < 2:
        warnings.warn("MCQ item_type does not contain both documented and tacit; attestation analysis skipped")
        return {}

    # Per-model raw accuracy and documented-minus-tacit gap.
    model_acc = (
        d.groupby(["model", "item_type"], as_index=False)["correct"].mean()
        .pivot(index="model", columns="item_type", values="correct")
        .reset_index()
    )
    for c in ["documented", "tacit"]:
        if c not in model_acc.columns:
            model_acc[c] = np.nan
    model_acc["documented_minus_tacit"] = model_acc["documented"] - model_acc["tacit"]
    model_acc["family"] = model_acc["model"].map(MODEL_FAMILY).fillna("other")
    model_acc = model_acc.sort_values("documented_minus_tacit", ascending=False)

    # System-average descriptive difference (equal weight per model).
    summary = pd.DataFrame([{
        "n_models": model_acc["model"].nunique(),
        "mean_model_accuracy_documented": model_acc["documented"].mean(),
        "mean_model_accuracy_tacit": model_acc["tacit"].mean(),
        "mean_model_gap_documented_minus_tacit": model_acc["documented_minus_tacit"].mean(),
    }])

    # Strong-model empirical hardness by item type.
    m = mcq_metrics[mcq_metrics["item_type"].isin(["documented", "tacit"])].copy()
    hardness = []
    for typ, g in m.groupby("item_type"):
        lo, hi = bootstrap_mean_ci(g["hardness"], seed=RANDOM_SEED + (0 if typ == "documented" else 1))
        hardness.append({
            "item_type": typ,
            "n_items": len(g),
            "mean_strong_model_hardness": g["hardness"].mean(),
            "ci_low": lo,
            "ci_high": hi,
            "consensus_hard_rate": g["consensus_hard"].mean(),
            "all_model_accuracy": g["all_model_accuracy"].mean(),
        })
    hardness = pd.DataFrame(hardness)

    doc_h = m.loc[m["item_type"] == "documented", "hardness"].dropna().values
    tac_h = m.loc[m["item_type"] == "tacit", "hardness"].dropna().values
    if len(doc_h) and len(tac_h):
        u, p_u = mannwhitneyu(tac_h, doc_h, alternative="two-sided")
        observed = float(np.mean(tac_h) - np.mean(doc_h))
        rng = np.random.default_rng(RANDOM_SEED)
        boot = []
        for _ in range(5000):
            boot.append(
                rng.choice(tac_h, len(tac_h), replace=True).mean()
                - rng.choice(doc_h, len(doc_h), replace=True).mean()
            )
        lo, hi = np.quantile(boot, [0.025, 0.975])
        hardness_test = pd.DataFrame([{
            "mean_hardness_tacit_minus_documented": observed,
            "bootstrap_ci_low": lo,
            "bootstrap_ci_high": hi,
            "mannwhitney_U": u,
            "mannwhitney_p_two_sided": p_u,
        }])
    else:
        hardness_test = pd.DataFrame()

    # Within-axis descriptive control.
    axis = (
        d.groupby(["axis", "item_type"], as_index=False)
        .agg(n_model_item_pairs=("correct", "size"), accuracy=("correct", "mean"))
    )
    item_counts = (
        d[["item_id", "axis", "item_type"]].drop_duplicates()
        .groupby(["axis", "item_type"], as_index=False).size()
        .rename(columns={"size": "n_items"})
    )
    axis = axis.merge(item_counts, on=["axis", "item_type"], how="left")

    # Exact requested regression:
    # correct ~ model + axis + documented_tacit ; cluster SE by item_id.
    d["correct_int"] = d["correct"].astype(int)
    formula = (
        "correct_int ~ C(model) + C(axis) + "
        "C(item_type, Treatment(reference='documented'))"
    )
    try:
        reg_tidy, reg_res = fit_clustered_logit(formula, d, "item_id")

        # Adjusted marginal predictions: set every row to each attestation type,
        # preserve its observed model + axis composition, then average predictions.
        pred_rows = []
        for typ in ["documented", "tacit"]:
            cf = d.copy()
            cf["item_type"] = typ
            pred_rows.append({
                "item_type": typ,
                "adjusted_mean_predicted_accuracy": float(np.mean(reg_res.predict(cf))),
            })
        marginal = pd.DataFrame(pred_rows)
        if len(marginal) == 2:
            p_doc = float(marginal.loc[marginal["item_type"] == "documented", "adjusted_mean_predicted_accuracy"].iloc[0])
            p_tac = float(marginal.loc[marginal["item_type"] == "tacit", "adjusted_mean_predicted_accuracy"].iloc[0])
            marginal["adjusted_doc_minus_tacit"] = p_doc - p_tac
        else:
            marginal["adjusted_doc_minus_tacit"] = np.nan
    except Exception as e:
        warnings.warn(f"Attestation regression failed: {e}")
        reg_tidy = pd.DataFrame([{"term": "MODEL_FAILED", "error": str(e)}])
        marginal = pd.DataFrame()

    return {
        "attestation_model_accuracy": model_acc,
        "attestation_summary": summary,
        "attestation_hardness": hardness,
        "attestation_hardness_test": hardness_test,
        "attestation_by_axis": axis,
        "attestation_regression": reg_tidy,
        "attestation_adjusted": marginal,
    }


# -----------------------------------------------------------------------------
# MANUAL REVIEW CANDIDATES
# -----------------------------------------------------------------------------


def deterministic_review_sample(response_errors: pd.DataFrame, target: int = MANUAL_REVIEW_TARGET) -> pd.DataFrame:
    """
    Build a deterministic, diverse response-level review queue.

    IMPORTANT: this is a review queue for the verifiable-format analyses in this
    script. It must not be described as the paper's open-ended 420-flag taxonomy
    unless the manually inspected responses actually come from the relevant
    open-ended judge flags.
    """
    if response_errors.empty:
        return response_errors.copy()

    d = response_errors.drop_duplicates(["format", "item_id", "model"]).copy()
    # Prioritise errors from strong models, consensus-hard items, universal-hard
    # items, and negative-discrimination items, with random tie-breaking.
    d["priority"] = (
        5 * d["universally_hard"].astype(int)
        + 3 * d["consensus_hard"].astype(int)
        + 2 * d["negative_discrimination"].astype(int)
        + 2 * d["is_top_model"].astype(int)
        + 1 * d["judge_reason"].notna().astype(int)
        + d["hardness"].fillna(0)
    )
    rng = np.random.default_rng(RANDOM_SEED)
    d["_rand"] = rng.random(len(d))

    # First pass: diversity, at most one response per item.
    first = (
        d.sort_values(["priority", "_rand"], ascending=[False, True])
        .drop_duplicates(["format", "item_id"], keep="first")
    )
    if len(first) >= target:
        sample = first.head(target).copy()
    else:
        remaining = d.merge(
            first[["format", "item_id", "model"]],
            on=["format", "item_id", "model"], how="left", indicator=True
        )
        remaining = remaining[remaining["_merge"] == "left_only"].drop(columns="_merge")
        remaining = remaining.sort_values(["priority", "_rand"], ascending=[False, True])
        sample = pd.concat([first, remaining.head(max(0, target - len(first)))], ignore_index=True)

    sample = sample.head(target).copy()
    sample = sample.drop(columns=["_rand"], errors="ignore")
    # Empty annotation columns for a human reviewer.
    sample["manual_primary_family"] = ""
    sample["manual_subtype"] = ""
    sample["benchmark_ambiguity"] = ""
    sample["scoring_or_judge_issue"] = ""
    sample["evidence_notes"] = ""
    sample["keep_as_paper_example"] = ""
    sample["adjudication_needed"] = ""
    return sample


# -----------------------------------------------------------------------------
# FIGURES
# -----------------------------------------------------------------------------


def save_figures(out_dir: Path, item_metrics: pd.DataFrame, att: Dict[str, pd.DataFrame]) -> None:
    fig_dir = out_dir / "figures"
    fig_dir.mkdir(parents=True, exist_ok=True)

    # Hardness-discrimination scatter, one figure per format.
    for fmt, d in item_metrics.groupby("format"):
        plt.figure(figsize=(7.2, 5.6))
        plt.scatter(d["hardness"], d["discrimination"], alpha=0.65, s=28)
        plt.axhline(0, linewidth=1)
        plt.axvline(CONSENSUS_HARD_THRESHOLD, linewidth=1, linestyle="--")
        plt.xlabel("Strong-model empirical hardness H = 1 - top-5 accuracy")
        plt.ylabel("Discrimination D = top-5 accuracy - bottom-5 accuracy")
        plt.title(f"{fmt}: item hardness vs discrimination")
        plt.tight_layout()
        plt.savefig(fig_dir / f"hardness_discrimination_{slug(fmt)}.png", dpi=220)
        plt.close()

    # Mean hardness by human difficulty.
    dd = item_metrics[item_metrics["difficulty"].isin(["easy", "medium", "hard"])].copy()
    if not dd.empty:
        tab = dd.groupby(["format", "difficulty"], as_index=False)["hardness"].mean()
        order = ["easy", "medium", "hard"]
        plt.figure(figsize=(8.0, 5.5))
        fmts = list(tab["format"].unique())
        x = np.arange(len(order))
        width = 0.8 / max(1, len(fmts))
        for i, fmt in enumerate(fmts):
            vals = [
                tab.loc[(tab["format"] == fmt) & (tab["difficulty"] == lev), "hardness"].mean()
                for lev in order
            ]
            plt.bar(x + (i - (len(fmts)-1)/2) * width, vals, width=width, label=fmt)
        plt.xticks(x, order)
        plt.ylabel("Mean strong-model hardness")
        plt.xlabel("Human-assigned difficulty")
        plt.title("Human difficulty vs empirical strong-model hardness")
        plt.legend()
        plt.tight_layout()
        plt.savefig(fig_dir / "hardness_by_human_difficulty.png", dpi=220)
        plt.close()

    # Attestation gap by model.
    model_acc = att.get("attestation_model_accuracy") if att else None
    if model_acc is not None and not model_acc.empty:
        d = model_acc.sort_values("documented_minus_tacit")
        plt.figure(figsize=(8.6, max(5.0, 0.32 * len(d))))
        y = np.arange(len(d))
        plt.barh(y, d["documented_minus_tacit"])
        plt.yticks(y, d["model"])
        plt.axvline(0, linewidth=1)
        plt.xlabel("Accuracy(documented) - Accuracy(tacit)")
        plt.title("MCQ attestation gap by model")
        plt.tight_layout()
        plt.savefig(fig_dir / "mcq_documented_minus_tacit_by_model.png", dpi=220)
        plt.close()


# -----------------------------------------------------------------------------
# EXCEL / MARKDOWN OUTPUT
# -----------------------------------------------------------------------------


def write_excel(path: Path, sheets: Dict[str, pd.DataFrame]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        for name, df in sheets.items():
            if df is None:
                continue
            safe = name[:31]
            df.to_excel(writer, sheet_name=safe, index=False)
            ws = writer.book[safe]
            ws.freeze_panes = "A2"
            if ws.max_row >= 1 and ws.max_column >= 1:
                ws.auto_filter.ref = ws.dimensions
            # Conservative widths: enough to inspect without exploding file size.
            for col_cells in ws.columns:
                letter = col_cells[0].column_letter
                values = [str(c.value) if c.value is not None else "" for c in col_cells[:80]]
                max_len = min(max([len(v) for v in values] + [10]) + 2, 60)
                ws.column_dimensions[letter].width = max_len


def pct(x: object, digits: int = 1) -> str:
    try:
        if pd.isna(x):
            return "NA"
        return f"{100*float(x):.{digits}f}%"
    except Exception:
        return "NA"


def num(x: object, digits: int = 3) -> str:
    try:
        if pd.isna(x):
            return "NA"
        return f"{float(x):.{digits}f}"
    except Exception:
        return "NA"


def make_summary_markdown(
    out_path: Path,
    rankings: pd.DataFrame,
    metrics: pd.DataFrame,
    enrichment: pd.DataFrame,
    difficulty_tests: pd.DataFrame,
    att: Dict[str, pd.DataFrame],
    sources: Dict[str, str],
) -> None:
    lines = []
    lines.append("# Error-analysis fact sheet\n")
    lines.append("This file is generated automatically by `scripts/08_prepare_error_analysis.py`.\n")
    lines.append("## Data provenance\n")
    for fmt, src in sources.items():
        lines.append(f"- **{fmt}:** item-level correctness source = `{src}`")
    lines.append("")

    lines.append("## Strong / weak systems by format\n")
    for fmt, r in rankings.groupby("format"):
        r = r.sort_values("accuracy", ascending=False)
        top = r.head(TOP_K)
        bottom = r.tail(BOTTOM_K)
        lines.append(f"### {fmt}")
        lines.append("Top 5: " + ", ".join(f"{m} ({pct(a)})" for m, a in zip(top["model"], top["accuracy"])))
        lines.append("Bottom 5: " + ", ".join(f"{m} ({pct(a)})" for m, a in zip(bottom["model"], bottom["accuracy"])))
        lines.append("")

    lines.append("## Q1. Items defeating strong models\n")
    for fmt, d in metrics.groupby("format"):
        lines.append(
            f"- **{fmt}:** {int(d['consensus_hard'].sum())}/{len(d)} consensus-hard "
            f"({pct(d['consensus_hard'].mean())}); {int(d['universally_hard'].sum())} universally hard; "
            f"{int(d['consensus_easy'].sum())} consensus-easy."
        )
    lines.append("")

    if not enrichment.empty:
        lines.append("### Strongest over-representations among consensus-hard items (FDR q < .05 where available)\n")
        sig = enrichment[(enrichment["enrichment_ratio"] > 1) & (enrichment["fdr_q_within_feature"] < 0.05)].copy()
        if sig.empty:
            sig = enrichment[enrichment["enrichment_ratio"] > 1].copy()
        for fmt, g in sig.groupby("format"):
            lines.append(f"**{fmt}:**")
            for _, r in g.sort_values("enrichment_ratio", ascending=False).head(10).iterrows():
                lines.append(
                    f"- {r['feature']} = `{r['value']}`: ER={num(r['enrichment_ratio'],2)}, "
                    f"hard {int(r['n_hard_value'])}/{int(r['n_hard'])}, q={num(r['fdr_q_within_feature'],3)}"
                )
            lines.append("")

    lines.append("## Q2. Hardness vs discrimination\n")
    for fmt, d in metrics.groupby("format"):
        neg = d[d["negative_discrimination"]]
        lines.append(
            f"- **{fmt}:** {len(neg)} negative-discrimination items "
            f"({pct(len(neg)/len(d) if len(d) else np.nan)})."
        )
        for _, r in neg.sort_values("discrimination").head(5).iterrows():
            lines.append(
                f"  - `{r['item_id']}`: H={num(r['hardness'],2)}, D={num(r['discrimination'],2)}, "
                f"axis={r.get('axis','')}, difficulty={r.get('difficulty','')}"
            )
    lines.append("")

    lines.append("## Human difficulty vs empirical hardness\n")
    if not difficulty_tests.empty:
        for _, r in difficulty_tests.iterrows():
            lines.append(
                f"- **{r['format']}:** Spearman rho={num(r['spearman_rho_difficulty_vs_hardness'],3)}, "
                f"p={num(r['spearman_p'],4)}; Kruskal-Wallis p={num(r['kruskal_p'],4)}."
            )
    lines.append("")

    lines.append("## Q3. MCQ attestation hypothesis\n")
    if not att:
        lines.append("Attestation analysis unavailable (no documented/tacit variable found).")
    else:
        s = att.get("attestation_summary", pd.DataFrame())
        if not s.empty:
            r = s.iloc[0]
            lines.append(
                f"System-average MCQ accuracy: documented={pct(r['mean_model_accuracy_documented'])}, "
                f"tacit={pct(r['mean_model_accuracy_tacit'])}; "
                f"documented-minus-tacit={pct(r['mean_model_gap_documented_minus_tacit'])}."
            )
        ht = att.get("attestation_hardness_test", pd.DataFrame())
        if not ht.empty:
            r = ht.iloc[0]
            lines.append(
                f"Strong-model hardness difference (tacit - documented) = {num(r['mean_hardness_tacit_minus_documented'],3)} "
                f"[bootstrap 95% CI {num(r['bootstrap_ci_low'],3)}, {num(r['bootstrap_ci_high'],3)}], "
                f"Mann-Whitney p={num(r['mannwhitney_p_two_sided'],4)}."
            )
        reg = att.get("attestation_regression", pd.DataFrame())
        if not reg.empty and "term" in reg.columns:
            rr = reg[reg["term"].astype(str).str.contains("item_type", case=False, na=False)]
            if not rr.empty:
                r = rr.iloc[0]
                lines.append(
                    f"Adjusted clustered logistic regression tacit-vs-documented: OR={num(r.get('odds_ratio'),3)} "
                    f"[95% CI {num(r.get('or_ci_low'),3)}, {num(r.get('or_ci_high'),3)}], "
                    f"p={num(r.get('p_value'),4)}."
                )
        adj = att.get("attestation_adjusted", pd.DataFrame())
        if not adj.empty:
            doc = adj.loc[adj["item_type"] == "documented", "adjusted_mean_predicted_accuracy"]
            tac = adj.loc[adj["item_type"] == "tacit", "adjusted_mean_predicted_accuracy"]
            if len(doc) and len(tac):
                lines.append(
                    f"Adjusted marginal predicted accuracy: documented={pct(doc.iloc[0])}, tacit={pct(tac.iloc[0])}, "
                    f"difference={pct(doc.iloc[0]-tac.iloc[0])}."
                )
    lines.append("")

    lines.append("## Important interpretation note\n")
    lines.append(
        "The generated 420-row manual review queue is a **verifiable-format review queue**. "
        "Do not call it the paper's '420 manually inspected flagged open-ended responses' unless those rows "
        "are in fact the responses you manually inspect under the open-ended factual/nativeness/alignment rubrics."
    )
    out_path.write_text("\n".join(lines), encoding="utf-8")


# -----------------------------------------------------------------------------
# MAIN
# -----------------------------------------------------------------------------


def main() -> None:
    root = find_repo_root()
    out_dir = root / "analysis" / "error_analysis"
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"Repository root: {root}")
    print(f"Output directory: {out_dir}")

    all_long = []
    all_metrics = []
    all_rankings = []
    validation_rows = []
    sources: Dict[str, str] = {}
    top_by_format: Dict[str, List[str]] = {}
    bottom_by_format: Dict[str, List[str]] = {}

    for cfg in FORMAT_CONFIGS:
        print(f"\n=== {cfg.name} ===")
        meta, overview, long, source = build_format_long(root, cfg)
        metrics, top, bottom = compute_item_metrics(meta, overview, long, cfg)

        print("Top 5:", top)
        print("Bottom 5:", bottom)
        print(
            f"Items={len(metrics)}, consensus-hard={int(metrics['consensus_hard'].sum())}, "
            f"universally-hard={int(metrics['universally_hard'].sum())}, "
            f"negative-D={int(metrics['negative_discrimination'].sum())}"
        )

        # Validation table against Overview.
        rec = long.groupby("model", as_index=False)["correct"].mean().rename(columns={"correct": "accuracy_recomputed"})
        val = overview[["format", "model", "accuracy"]].merge(rec, on="model", how="left")
        val["abs_diff"] = (val["accuracy"] - val["accuracy_recomputed"]).abs()
        val["item_level_source"] = source
        validation_rows.append(val)

        all_long.append(long)
        all_metrics.append(metrics)
        all_rankings.append(overview)
        sources[cfg.name] = source
        top_by_format[cfg.name] = top
        bottom_by_format[cfg.name] = bottom

    long_all = pd.concat(all_long, ignore_index=True, sort=False)
    item_metrics = pd.concat(all_metrics, ignore_index=True, sort=False)
    rankings = pd.concat(all_rankings, ignore_index=True, sort=False)
    validation = pd.concat(validation_rows, ignore_index=True, sort=False)

    # ------------------------------------------------------------------
    # Q1: hard items + enrichment
    # ------------------------------------------------------------------
    enrichment_features = [
        "axis", "difficulty", "intent_group", "intent_category",
        "item_type", "status", "adjudicated", "source_type",
    ]
    enrich_parts = []
    for fmt, d in item_metrics.groupby("format"):
        e = enrichment_table(d, enrichment_features)
        if not e.empty:
            enrich_parts.append(e)
    enrichment = pd.concat(enrich_parts, ignore_index=True) if enrich_parts else pd.DataFrame()

    # ------------------------------------------------------------------
    # Q2: negative discrimination / suspicious items
    # ------------------------------------------------------------------
    negative_items = item_metrics[item_metrics["negative_discrimination"]].copy()
    negative_items = negative_items.sort_values(["format", "discrimination", "hardness"], ascending=[True, True, False])
    consensus_hard_items = item_metrics[item_metrics["consensus_hard"]].copy()
    universal_hard_items = item_metrics[item_metrics["universally_hard"]].copy()

    # ------------------------------------------------------------------
    # Supporting: human difficulty
    # ------------------------------------------------------------------
    difficulty_desc, difficulty_tests = difficulty_analysis(item_metrics)
    difficulty_regression = combined_difficulty_regression(long_all)

    # ------------------------------------------------------------------
    # Q3: attestation hypothesis, MCQ only
    # ------------------------------------------------------------------
    mcq_long = long_all[long_all["format"] == "MCQ"].copy()
    mcq_metrics = item_metrics[item_metrics["format"] == "MCQ"].copy()
    att = attestation_analysis(mcq_long, mcq_metrics, top_by_format.get("MCQ", []))

    # ------------------------------------------------------------------
    # Response-level manual review candidates
    # ------------------------------------------------------------------
    metric_cols = [
        "format", "item_id", "hardness", "discrimination", "consensus_hard",
        "universally_hard", "negative_discrimination", "top5_accuracy",
        "bottom5_accuracy", "all_model_accuracy", "top5_failed_models",
        "bottom5_correct_models",
    ]
    errs = long_all[long_all["correct"] == 0].merge(
        item_metrics[metric_cols], on=["format", "item_id"], how="left", validate="many_to_one"
    )
    errs["is_top_model"] = errs.apply(lambda r: r["model"] in top_by_format.get(r["format"], []), axis=1)
    errs["is_bottom_model"] = errs.apply(lambda r: r["model"] in bottom_by_format.get(r["format"], []), axis=1)
    errs = errs.sort_values(["universally_hard", "consensus_hard", "is_top_model", "hardness"], ascending=False)
    manual_sample = deterministic_review_sample(errs, MANUAL_REVIEW_TARGET)

    # Item-level review queue focuses on benchmark ambiguity / scoring concerns.
    manual_item_queue = item_metrics[
        item_metrics["consensus_hard"] | item_metrics["negative_discrimination"]
    ].copy()
    manual_item_queue = manual_item_queue.sort_values(
        ["negative_discrimination", "universally_hard", "hardness", "discrimination"],
        ascending=[False, False, False, True],
    )
    for c in [
        "manual_item_verdict", "ambiguous_wording", "distractor_artifact",
        "gold_or_scoring_issue", "specialized_knowledge", "notes"
    ]:
        manual_item_queue[c] = ""

    # ------------------------------------------------------------------
    # Extra descriptive tables
    # ------------------------------------------------------------------
    format_summary = (
        item_metrics.groupby("format", as_index=False)
        .agg(
            n_items=("item_id", "nunique"),
            mean_all_model_accuracy=("all_model_accuracy", "mean"),
            mean_strong_hardness=("hardness", "mean"),
            consensus_hard_n=("consensus_hard", "sum"),
            universal_hard_n=("universally_hard", "sum"),
            consensus_easy_n=("consensus_easy", "sum"),
            negative_discrimination_n=("negative_discrimination", "sum"),
        )
    )
    format_summary["consensus_hard_rate"] = format_summary["consensus_hard_n"] / format_summary["n_items"]
    format_summary["negative_discrimination_rate"] = format_summary["negative_discrimination_n"] / format_summary["n_items"]

    axis_summary = (
        item_metrics.groupby(["format", "axis"], as_index=False)
        .agg(
            n_items=("item_id", "nunique"),
            all_model_accuracy=("all_model_accuracy", "mean"),
            mean_hardness=("hardness", "mean"),
            consensus_hard_rate=("consensus_hard", "mean"),
            negative_discrimination_rate=("negative_discrimination", "mean"),
        )
    )

    family_summary = (
        long_all.groupby(["format", "family", "axis"], as_index=False)
        .agg(n_model_item_pairs=("correct", "size"), accuracy=("correct", "mean"))
    )

    # ------------------------------------------------------------------
    # Save figures
    # ------------------------------------------------------------------
    save_figures(out_dir, item_metrics, att)

    # ------------------------------------------------------------------
    # Save main workbook
    # ------------------------------------------------------------------
    sheets = {
        "format_summary": format_summary,
        "model_rankings": rankings,
        "validation": validation,
        "item_metrics": item_metrics,
        "consensus_hard": consensus_hard_items,
        "universal_hard": universal_hard_items,
        "negative_discrim": negative_items,
        "enrichment": enrichment,
        "axis_summary": axis_summary,
        "difficulty_desc": difficulty_desc,
        "difficulty_tests": difficulty_tests,
        "difficulty_logit": difficulty_regression,
        "family_axis": family_summary,
        "response_errors": errs,
    }
    for k, v in att.items():
        sheets[k[:31]] = v

    results_path = out_dir / "error_analysis_results.xlsx"
    write_excel(results_path, sheets)

    # Manual review workbook: separate on purpose so a reviewer can annotate it.
    manual_path = root / "analysis" / "manual_error_analysis.xlsx"
    instructions = pd.DataFrame({
        "field": [
            "manual_primary_family", "manual_subtype", "benchmark_ambiguity",
            "scoring_or_judge_issue", "evidence_notes", "keep_as_paper_example",
            "adjudication_needed"
        ],
        "suggested_values": [
            "factual_knowledge | darija_pragmatic | institutional_social | format_compliance | benchmark_ambiguity | scoring_issue | other",
            "free text; use a consistent taxonomy after first pass",
            "yes | no | uncertain",
            "yes | no | uncertain",
            "free text",
            "yes | no",
            "yes | no"
        ],
    })
    write_excel(manual_path, {
        "README": instructions,
        "response_review_420": manual_sample,
        "item_review_queue": manual_item_queue,
    })

    # CSVs for transparent downstream analysis.
    long_all.to_csv(out_dir / "closed_formats_long.csv", index=False, encoding="utf-8-sig")
    item_metrics.to_csv(out_dir / "item_metrics.csv", index=False, encoding="utf-8-sig")
    if not enrichment.empty:
        enrichment.to_csv(out_dir / "hard_item_enrichment.csv", index=False, encoding="utf-8-sig")

    # Machine-readable model sets used to define strong/weak.
    model_sets = {
        fmt: {"top5": top_by_format[fmt], "bottom5": bottom_by_format[fmt]}
        for fmt in top_by_format
    }
    (out_dir / "model_sets.json").write_text(json.dumps(model_sets, ensure_ascii=False, indent=2), encoding="utf-8")

    summary_path = out_dir / "ERROR_ANALYSIS_SUMMARY.md"
    make_summary_markdown(
        summary_path, rankings, item_metrics, enrichment,
        difficulty_tests, att, sources
    )

    print("\nDONE")
    print(f"Main results:        {results_path}")
    print(f"Manual review:       {manual_path}")
    print(f"Fact sheet:          {summary_path}")
    print(f"Figures:             {out_dir / 'figures'}")
    print(f"Long data:           {out_dir / 'closed_formats_long.csv'}")

    # Final validation warning in stdout.
    max_diff = validation["abs_diff"].max(skipna=True)
    print(f"Max recomputed-vs-Overview accuracy difference: {max_diff:.6f}")
    if pd.notna(max_diff) and max_diff > PARSER_VALIDATION_TOLERANCE:
        print(
            "WARNING: at least one model does not exactly match the scorer Overview. "
            "Inspect the 'validation' sheet before citing results."
        )


if __name__ == "__main__":
    main()
