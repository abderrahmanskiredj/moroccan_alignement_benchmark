#!/usr/bin/env python3
"""
run_vllm_eval5.py
=================

Évaluation locale avec vLLM de tous les modèles configurés sur les 4 datasets Darija.

Version prévue pour un GPU NVIDIA H100 avec suffisamment de VRAM :
  1) Tous les modèles sont chargés en FP16 (aucun FP8 / aucune quantification).
  2) Les modèles sont regroupés dans une seule liste MODELS exhaustive.
  3) Les réglages Gemma 3 multimodaux/text-only sont appliqués uniquement à GemMaroc.
  4) Un sous-processus distinct est conservé pour chaque modèle afin de libérer la VRAM.
  5) max_num_seqs reste volontairement à 8 pour garder un démarrage robuste.
  6) Le script reprend automatiquement les lignes déjà remplies dans les fichiers Excel.

Lancement normal :
    python run_vllm_eval5_fp16_h100.py

Un seul modèle :
    python run_vllm_eval5_fp16_h100.py --model gemmaroc_27b

Plusieurs modèles :
    python run_vllm_eval5_fp16_h100.py --models atlaschat_27b,gemmaroc_27b
"""

# IMPORTANT : ces variables doivent être définies AVANT tout import de vLLM.
import os

os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
os.environ.setdefault("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True")
os.environ.setdefault("VLLM_USE_FLASHINFER_SAMPLER", "0")

# Correctif de robustesse principal pour le blocage vu avec GemMaroc.
# On force le Model Runner V1 à la place du V2.
os.environ["VLLM_USE_V2_MODEL_RUNNER"] = "0"

# Facultatif mais utile pour voir davantage d'informations après chargement.
os.environ.setdefault("VLLM_LOG_MODEL_INSPECTION", "0")

import re
import sys
import argparse
import subprocess
from pathlib import Path

import pandas as pd


# ============================== CONFIG ==============================

FILES = [
    {"path": "final_binary_no_responses.xlsx",        "task": "binary"},
    {"path": "qcm_final_no_responses.xlsx",          "task": "qcm"},
    {"path": "final_shorts_no_responses.xlsx",       "task": "shorts"},
    {"path": "open_question_final_no_responses.xlsx", "task": "open"},
]

MODELS = [
    {
        "short": "atlaschat_27b",
        "path": "./Atlas-Chat-27B",
        "cpu_offload_gb": 0,
        "max_model_len": 4096,
        "max_num_seqs": 8,
        "gpu_mem_util": 0.93,
    },
    {
        "short": "gemmaroc_27b",
        "path": "./GemMaroc-27b-it",
        "cpu_offload_gb": 0,
        "max_model_len": 4096,
        "max_num_seqs": 8,
        "gpu_mem_util": 0.93,
        "gemma3_text_only": True,
    },
    {
        "short": "allam_7b",
        "path": "./ALLaM-7B-Instruct-preview",
        "cpu_offload_gb": 0,
        "max_model_len": 4096,
        "max_num_seqs": 8,
        "gpu_mem_util": 0.93,
    },
    {
        "short": "jais2_8b",
        "path": "./Jais-2-8B-Chat",
        "cpu_offload_gb": 0,
        "max_model_len": 4096,
        "max_num_seqs": 8,
        "gpu_mem_util": 0.93,
    },
    {
        "short": "aya_expanse_32b",
        "path": "./aya-expanse-32b",
        "cpu_offload_gb": 0,
        "max_model_len": 4096,
        "max_num_seqs": 8,
        "gpu_mem_util": 0.93,
    },
]

MODELS_BY_SHORT = {m["short"]: m for m in MODELS}

MCQ_OPTION_COLS = ["response_A", "response_B", "response_C", "response_D"]

# Génération / sauvegarde.
MAX_TOKENS_SHORT = 512
MAX_TOKENS_OPEN = 2048
CHUNK = 128

ERROR_PREFIXES = ("[ERROR]", "[UNEXPECTED_ERROR]", "[PROMPT_ERROR]")


# ============================== I/O EXCEL ==============================

def load_all_sheets(path: str) -> dict:
    return pd.read_excel(path, sheet_name=None)


def save_all_sheets(sheets: dict, path: str):
    """Sauvegarde atomique : écrit dans un .tmp puis remplace l'original."""
    p = Path(path)
    tmp = p.with_name(p.stem + ".tmp" + p.suffix)
    with pd.ExcelWriter(tmp, engine="openpyxl") as writer:
        for name, sdf in sheets.items():
            sdf.to_excel(writer, sheet_name=name, index=False)
    tmp.replace(path)


def detect_sheet(sheets: dict) -> str:
    """Feuille cible = première feuille qui contient une colonne 'input'."""
    for name, sdf in sheets.items():
        if "input" in sdf.columns:
            return name
    return next(iter(sheets))


# ============================== PROMPTS ==============================

def get_option_cols(df) -> list:
    return [c for c in MCQ_OPTION_COLS if c in df.columns]


def build_mcq_prompt(row, option_cols):
    """QCM/binaire : demande une seule lettre en sortie."""
    lines, letters = [], []
    for col in option_cols:
        value = row[col]
        if pd.isna(value) or str(value).strip() == "":
            continue
        letter = col.split("_")[-1].upper()
        letters.append(letter)
        lines.append(f"{letter}: {value}")

    allowed = " ولا ".join(letters)
    prompt = (
        f"{row['input']}\n\n"
        + "\n".join(lines)
        + f"\n\nجاوب بحرف واحد فقط: {allowed}. بلا شرح، بلا علامات، بلا كلام زايد."
    )
    return prompt, letters


ANSWER_OPEN_TAG = "<FINAL_ANSWER>"
ANSWER_CLOSE_TAG = "</FINAL_ANSWER>"


def build_shorts_prompt(row) -> str:
    return (
        f"{row['input']}\n\n"
        "جاوب على السؤال بالدارجة المغربية ولا بالعربية الفصحى.\n"
        "خاصك تكتب الجواب النهائي ديالك (كلمة ولا جملة قصيرة، بلا شرح) بين هاد "
        "العلامتين بالضبط، مرة وحدة فقط، بلا ما تبدل شكلهم:\n"
        f"{ANSWER_OPEN_TAG}جوابك هنا{ANSWER_CLOSE_TAG}\n\n"
        "يمكن ليك تفكر ولا تشرح شوية قبل هاد العلامتين إلا كان ضروري بالنسبة "
        "ليك، ولكن الجواب النهائي والمختصر خاصو يكون بين العلامتين، وماكاينش "
        f"تكتب حتى حرف بعد {ANSWER_CLOSE_TAG}."
    )


def build_open_prompt(row) -> str:
    return (
        f"{row['input']}\n\n"
        "جاوب بالدارجة المغربية ولا بالعربية الفصحى. "
        "كون مختصر ومباشر فجوابك، بلا حشو."
    )


# ============================== PARSING ==============================

def parse_mcq(raw_text, letters):
    """Retourne la lettre de réponse ou None. Prend le dernier match."""
    if not raw_text:
        return None

    text = str(raw_text).strip()
    if text in letters:
        return text

    charset = "".join(letters)
    if not charset:
        return None

    matches = re.findall(rf"(?<![A-Za-z])([{charset}])(?![A-Za-z])", text)
    if matches:
        return matches[-1]
    return None


def clean_answer(raw_text) -> str:
    if raw_text is None:
        return ""
    text = str(raw_text).strip()
    text = text.strip(" \n\t\"'“”«»")
    return text


ANSWER_TAG_PAT = re.compile(
    re.escape(ANSWER_OPEN_TAG) + r"(.*?)" + re.escape(ANSWER_CLOSE_TAG),
    re.DOTALL | re.IGNORECASE,
)


def extract_final_answer(raw_text):
    """Retourne (réponse, méthode), méthode in {tag, fallback, empty}."""
    if not raw_text:
        return "", "empty"

    text = str(raw_text)
    matches = ANSWER_TAG_PAT.findall(text)
    if matches:
        candidate = clean_answer(matches[-1])
        if candidate:
            return candidate, "tag"

    cleaned = clean_answer(text)
    if cleaned:
        return cleaned, "fallback"

    return "", "empty"


# ============================== REPRISE ==============================

def is_done(task: str, value) -> bool:
    if task == "open":
        if pd.isna(value):
            return False
        s = str(value).strip()
        if s == "" or s == "EMPTY":
            return False
        if s.startswith(ERROR_PREFIXES):
            return False
        return True

    return not pd.isna(value)


# ============================== ÉCRITURE RÉSULTATS ==============================

def write_result(df, idx, task, resp_col, raw_col, parse_col, raw_text, letters):
    if task in ("binary", "qcm"):
        parsed = parse_mcq(raw_text, letters)
        df.at[idx, resp_col] = parsed if parsed is not None else "UNPARSED"
        df.at[idx, raw_col] = raw_text

    elif task == "shorts":
        answer, method = extract_final_answer(raw_text)
        df.at[idx, resp_col] = answer if answer else "EMPTY"
        df.at[idx, raw_col] = raw_text
        df.at[idx, parse_col] = method

    else:  # open
        df.at[idx, resp_col] = (
            raw_text if (raw_text and str(raw_text).strip()) else "EMPTY"
        )


# ============================== TRAITEMENT D'UN FICHIER ==============================

def process_file(llm, sampling, file_cfg: dict, short: str):
    path = file_cfg["path"]
    task = file_cfg["task"]

    if not Path(path).exists():
        print(f"  [SKIP] fichier introuvable : {path}", flush=True)
        return

    sheets = load_all_sheets(path)
    sheet_name = file_cfg.get("sheet") or detect_sheet(sheets)
    df = sheets[sheet_name]

    if "input" not in df.columns:
        print(f"  [SKIP] pas de colonne 'input' dans {path}::{sheet_name}", flush=True)
        return

    resp_col = f"response_{short}"

    if task == "binary":
        # Pas de préfixe response_ pour éviter que le scorer le prenne pour un modèle.
        raw_col = f"{short}_raw"
    elif task in ("qcm", "shorts"):
        raw_col = f"response_{short}_raw"
    else:
        raw_col = None

    parse_col = f"response_{short}_parse" if task == "shorts" else None

    for c in (resp_col, raw_col, parse_col):
        if c and c not in df.columns:
            df[c] = pd.NA

    option_cols = get_option_cols(df) if task in ("binary", "qcm") else None
    if task in ("binary", "qcm") and not option_cols:
        print(f"  [SKIP] aucune colonne d'option {MCQ_OPTION_COLS} dans {path}", flush=True)
        return

    todo = [i for i in df.index if not is_done(task, df.at[i, resp_col])]
    print(
        f"  {path} :: {sheet_name} — {len(todo)} ligne(s) à faire pour {short}",
        flush=True,
    )

    if not todo:
        return

    items = []  # (idx, conversation, letters)

    for idx in todo:
        try:
            if task in ("binary", "qcm"):
                prompt, letters = build_mcq_prompt(df.loc[idx], option_cols)
            elif task == "shorts":
                prompt, letters = build_shorts_prompt(df.loc[idx]), None
            else:
                prompt, letters = build_open_prompt(df.loc[idx]), None
        except Exception as e:
            print(f"    [PROMPT_ERROR idx={idx}] {e}", flush=True)
            continue

        items.append((idx, [{"role": "user", "content": prompt}], letters))

    total = len(items)

    for start in range(0, total, CHUNK):
        chunk = items[start : start + CHUNK]
        conversations = [c for (_, c, _) in chunk]

        print(
            f"    -> génération lignes {start + 1} à {min(start + CHUNK, total)} / {total}",
            flush=True,
        )

        outputs = llm.chat(
            conversations,
            sampling_params=sampling,
            use_tqdm=True,
        )

        for (idx, _, letters), out in zip(chunk, outputs):
            raw_text = out.outputs[0].text if out.outputs else ""
            write_result(
                df,
                idx,
                task,
                resp_col,
                raw_col,
                parse_col,
                raw_text,
                letters,
            )

        sheets[sheet_name] = df

        try:
            save_all_sheets(sheets, path)
        except Exception as e:
            print(f"    (sauvegarde échouée, on continue : {e})", flush=True)

        print(f"    -> sauvegardé {min(start + CHUNK, total)}/{total}", flush=True)


# ============================== GPU / DIAGNOSTIC ==============================

def print_gpu_status():
    """Affiche la VRAM disponible juste avant de construire le moteur."""
    try:
        import torch

        if not torch.cuda.is_available():
            print("[ERREUR] CUDA n'est pas disponible dans cet environnement.", flush=True)
            return

        device = torch.cuda.current_device()
        name = torch.cuda.get_device_name(device)
        free_b, total_b = torch.cuda.mem_get_info(device)
        free_gb = free_b / (1024 ** 3)
        total_gb = total_b / (1024 ** 3)

        print(
            f"GPU -> {name} | VRAM libre {free_gb:.2f} / {total_gb:.2f} GiB",
            flush=True,
        )

        if free_gb < 30:
            print(
                "[WARNING] Moins de 30 GiB de VRAM libre avant chargement. "
                "Vérifie qu'aucun autre process n'occupe le GPU (nvidia-smi).",
                flush=True,
            )

    except Exception as e:
        print(f"[WARNING] Impossible de lire l'état GPU : {e}", flush=True)


# ============================== CONSTRUCTION DU MOTEUR vLLM ==============================

def build_llm(short: str):
    """Construit vLLM en FP16 avec seulement les réglages spécifiques nécessaires."""
    import torch
    import vllm
    from vllm import LLM

    m = MODELS_BY_SHORT[short]

    # Un seul GPU H100 par modèle. L'orchestrateur charge les modèles l'un après l'autre.
    tp = 1
    gpu_util = float(m.get("gpu_mem_util", 0.93))
    max_model_len = int(m.get("max_model_len", 4096))
    max_num_seqs = int(m.get("max_num_seqs", 8))
    cpu_offload_gb = float(m.get("cpu_offload_gb", 0))

    if torch.cuda.device_count() < tp:
        raise RuntimeError(
            f"TP={tp} demandé mais seulement {torch.cuda.device_count()} GPU CUDA visible(s)."
        )

    print(f"vLLM version -> {vllm.__version__}", flush=True)
    print(f"Model -> {short}", flush=True)
    print(
        f"config -> dtype=float16 | quant=NONE | TP={tp} | "
        f"gpu_mem_util={gpu_util} | max_model_len={max_model_len} | "
        f"max_num_seqs={max_num_seqs} | cpu_offload_gb={cpu_offload_gb} | "
        "enforce_eager=True",
        flush=True,
    )

    kwargs = dict(
        model=m["path"],
        tensor_parallel_size=tp,
        dtype="float16",
        gpu_memory_utilization=gpu_util,
        max_model_len=max_model_len,
        max_num_seqs=max_num_seqs,
        trust_remote_code=True,

        # Plus robuste au démarrage : pas de torch.compile / CUDA graphs.
        enforce_eager=True,

        # On explicite le runner de génération.
        runner="generate",
    )

    if cpu_offload_gb > 0:
        kwargs["cpu_offload_gb"] = cpu_offload_gb

    # GemMaroc est un Gemma 3 multimodal, mais cette évaluation est 100 % texte.
    # Ces options ne sont PAS envoyées aux autres architectures.
    if m.get("gemma3_text_only", False):
        kwargs.update(
            language_model_only=True,
            skip_mm_profiling=True,
            mm_processor_cache_gb=0,
        )

    print("-> Initialisation du moteur vLLM...", flush=True)
    llm = LLM(**kwargs)
    print("-> Moteur vLLM chargé avec succès.", flush=True)
    return llm


# ============================== EXÉCUTION D'UN MODÈLE ==============================

def run_model(short: str) -> int:
    if short not in MODELS_BY_SHORT:
        print(
            f"[ERREUR] modèle inconnu : {short} (connus : {list(MODELS_BY_SHORT)})",
            flush=True,
        )
        return 2

    model_path = MODELS_BY_SHORT[short]["path"]
    if not Path(model_path).exists():
        print(
            f"[ERREUR] dossier modèle absent : {model_path}",
            flush=True,
        )
        return 3

    from vllm import SamplingParams

    print(f"\n########## Chargement de {short} ({model_path}) ##########", flush=True)
    print_gpu_status()

    llm = build_llm(short)

    sampling_short = SamplingParams(
        temperature=0.0,
        max_tokens=MAX_TOKENS_SHORT,
    )
    sampling_open = SamplingParams(
        temperature=0.0,
        max_tokens=MAX_TOKENS_OPEN,
    )

    for file_cfg in FILES:
        sampling = sampling_open if file_cfg["task"] == "open" else sampling_short

        print(
            f"\n--- {short} :: {file_cfg['task']} ({file_cfg['path']}) ---",
            flush=True,
        )

        try:
            process_file(llm, sampling, file_cfg, short)
        except KeyboardInterrupt:
            raise
        except Exception as e:
            print(
                f"  [ERREUR fichier {file_cfg['path']}] {type(e).__name__}: {e}",
                flush=True,
            )

    print(f"\n########## {short} terminé ##########", flush=True)
    return 0


# ============================== ORCHESTRATION ==============================

def orchestrate(shorts: list):
    """Un sous-processus par modèle pour garantir la libération de VRAM."""
    script = os.path.abspath(__file__)

    for short in shorts:
        m = MODELS_BY_SHORT.get(short)
        if m is None:
            print(f"[SKIP] modèle inconnu : {short}", flush=True)
            continue

        if not Path(m["path"]).exists():
            print(
                f"[SKIP] {short} : dossier absent ({m['path']}).",
                flush=True,
            )
            continue

        print(f"\n==================== MODÈLE : {short} ====================", flush=True)

        try:
            ret = subprocess.run(
                [sys.executable, "-u", script, "--model", short],
                env=os.environ.copy(),
            ).returncode
        except KeyboardInterrupt:
            print(
                "\nInterrompu manuellement. Relance la même commande pour reprendre.",
                flush=True,
            )
            return

        if ret != 0:
            print(
                f"[AVERTISSEMENT] {short} s'est terminé avec le code {ret}.",
                flush=True,
            )

    print("\nTous les modèles présents ont été traités.", flush=True)


# ============================== MAIN ==============================



def main():
    ap = argparse.ArgumentParser(
        description="Inférence vLLM sur les 4 datasets d'évaluation Darija."
    )

    ap.add_argument(
        "--model",
        help="Nom court d'un seul modèle à exécuter.",
    )

    ap.add_argument(
        "--models",
        help="Liste de modèles séparés par des virgules.",
    )

    args = ap.parse_args()

    # Exemple :
    # python run_vllm_eval5.py --model aya_expanse_32b
    if args.model:
        sys.exit(run_model(args.model))

    # Exemple :
    # python run_vllm_eval5.py --models aya_expanse_32b,atlaschat_27b
    if args.models:
        shorts = [
            x.strip()
            for x in args.models.split(",")
            if x.strip()
        ]
        orchestrate(shorts)
        return

    # Par défaut :
    # python run_vllm_eval5.py
    #
    # Exécute automatiquement tous les modèles définis dans MODELS.
    shorts = [m["short"] for m in MODELS]
    orchestrate(shorts)


if __name__ == "__main__":
    main()
