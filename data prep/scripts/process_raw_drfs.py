"""Combine all Brisnet .DRF files under data/raw into processed outputs.

Writes (training / history):
  data/processed/combined.csv             — Kentucky Derby entries only (see ``--full-card``)
  data/processed/combined_pp_long.csv    — past_performances_long on that frame

The latest prediction card (default ``CDX0502-2026.DRF``) is **excluded** from the
training combine and processed separately **without** official results merge:

  data/processed/predictions.csv         — Derby field for scoring / inference
  data/processed/predictions_pp_long.csv — PP-long for that card

By default, rows are restricted to the Kentucky Derby race on each card (``KyDerby``
classification at Churchill Downs). Use ``--full-card`` to keep every race in every raw DRF.

Official Kentucky Derby finish / odds (when ``data/reference/kentucky_derby_results_*.csv``
is present) are merged onto training rows only; prediction exports omit targets.

Run from ``data prep``:  python scripts/process_raw_drfs.py
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

from derby_reference import (
    attach_derby_labels_to_pp_long,
    finalize_derby_training_columns,
    merge_official_derby_results,
)
from load_drf import load_drf, past_performances_long, select_kentucky_derby


def _repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


DEFAULT_PREDICTION_DRF_NAME = "CDX0502-2026.DRF"


def _list_drf_files(raw_dir: Path, *, exclude_names: frozenset[str] | None = None) -> list[Path]:
    if not raw_dir.is_dir():
        return []
    paths = [p for p in raw_dir.iterdir() if p.is_file() and p.suffix.upper() == ".DRF"]
    if exclude_names:
        paths = [p for p in paths if p.name not in exclude_names]
    return sorted(paths, key=lambda p: p.name.lower())


def _save_table(df: pd.DataFrame, dest_base: Path) -> Path:
    """Write UTF-8 CSV (no index column)."""
    dest_base.parent.mkdir(parents=True, exist_ok=True)
    out_path = dest_base.with_suffix(".csv")
    df.to_csv(out_path, index=False, encoding="utf-8")
    return out_path


def combine_raw_drfs(
    raw_dir: Path,
    processed_dir: Path,
    *,
    source_column: str = "_source_drf",
    reference_csv: Path | None = None,
    derby_only: bool = True,
    exclude_drf_names: frozenset[str] | None = None,
) -> tuple[Path, Path]:
    paths = _list_drf_files(raw_dir, exclude_names=exclude_drf_names)
    if not paths:
        raise FileNotFoundError(
            f"No .DRF files found in {raw_dir}"
            + (f" after excluding {sorted(exclude_drf_names)!r}" if exclude_drf_names else "")
        )

    chunks: list[pd.DataFrame] = []
    for p in paths:
        chunks.append(load_drf(p).assign(**{source_column: p.name}))

    combined = pd.concat(chunks, ignore_index=True)

    if derby_only:
        # Multi-year concat can include different Derby race numbers (e.g. 12 vs 14).
        combined = select_kentucky_derby(combined, require_unique_race=False)

    root = _repo_root()
    ref_path = reference_csv if reference_csv is not None else (
        root / "data" / "reference" / "kentucky_derby_results_2017_2025.csv"
    )
    ref_path = ref_path.resolve()
    if ref_path.is_file():
        combined = merge_official_derby_results(combined, ref_path)
    else:
        print(
            f"Warning: reference results not found at {ref_path}; "
            "skipping merge and training targets (year, target_FP, target_top3, target_top5).",
            file=sys.stderr,
        )

    if "official_finish_position" in combined.columns:
        combined = finalize_derby_training_columns(combined)

    wide_path = _save_table(combined, processed_dir / "combined")

    pp_long = past_performances_long(combined)
    if "target_FP" in combined.columns:
        pp_long = attach_derby_labels_to_pp_long(pp_long, combined)
    long_path = _save_table(pp_long, processed_dir / "combined_pp_long")

    return wide_path, long_path


def export_predictions_drf(
    raw_dir: Path,
    processed_dir: Path,
    prediction_drf_name: str,
    *,
    source_column: str = "_source_drf",
    derby_only: bool = True,
) -> tuple[Path | None, Path | None]:
    """Derby-only extract from the holdout DRF: no results merge, adds ``year`` from ``date``."""
    pred_path = raw_dir / prediction_drf_name
    if not pred_path.is_file():
        return None, None

    df = load_drf(pred_path).assign(**{source_column: pred_path.name})
    if derby_only:
        df = select_kentucky_derby(df, require_unique_race=False)
    df["year"] = pd.to_datetime(df["date"], errors="coerce").dt.year

    wide_path = _save_table(df, processed_dir / "predictions")
    pp_long = past_performances_long(df)
    long_path = _save_table(pp_long, processed_dir / "predictions_pp_long")
    return wide_path, long_path


def main(argv: list[str] | None = None) -> int:
    root = _repo_root()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--raw-dir",
        type=Path,
        default=root / "data" / "raw",
        help="Directory containing .DRF files (default: data/raw)",
    )
    parser.add_argument(
        "--processed-dir",
        type=Path,
        default=root / "data" / "processed",
        help="Output directory (default: data/processed)",
    )
    parser.add_argument(
        "--reference-csv",
        type=Path,
        default=None,
        help="Kentucky Derby results CSV (default: data/reference/kentucky_derby_results_2017_2025.csv)",
    )
    parser.add_argument(
        "--full-card",
        action="store_true",
        help="Include all races from each DRF (default: Kentucky Derby runners only)",
    )
    parser.add_argument(
        "--prediction-drf",
        type=str,
        default=DEFAULT_PREDICTION_DRF_NAME,
        help=(
            "Basename under raw/ excluded from training combine and exported as predictions "
            f"(default: {DEFAULT_PREDICTION_DRF_NAME}). Use empty string to disable."
        ),
    )
    parser.add_argument(
        "--skip-predictions-export",
        action="store_true",
        help="Do not write predictions.csv / predictions_pp_long.csv",
    )
    args = parser.parse_args(argv)

    raw_dir = args.raw_dir.resolve()
    processed_dir = args.processed_dir.resolve()

    prediction_name = (args.prediction_drf or "").strip()
    exclude_names: frozenset[str] | None = None
    if prediction_name:
        exclude_names = frozenset({prediction_name})

    try:
        wide_path, long_path = combine_raw_drfs(
            raw_dir,
            processed_dir,
            reference_csv=args.reference_csv,
            derby_only=not args.full_card,
            exclude_drf_names=exclude_names,
        )
    except FileNotFoundError as e:
        print(e, file=sys.stderr)
        return 1

    n_train = len(_list_drf_files(raw_dir, exclude_names=exclude_names))
    print(f"Training combine: {n_train} DRF file(s) from {raw_dir}")
    if exclude_names:
        print(f"Excluded from training combine: {sorted(exclude_names)}")
    print(f"Wide combined -> {wide_path}")
    print(f"Long PP combined -> {long_path}")

    if prediction_name and not args.skip_predictions_export:
        pw, pl = export_predictions_drf(
            raw_dir,
            processed_dir,
            prediction_name,
            derby_only=not args.full_card,
        )
        if pw is None:
            print(
                f"Note: prediction DRF {prediction_name!r} not found under {raw_dir}; "
                "skipped predictions export.",
                file=sys.stderr,
            )
        else:
            print(f"Predictions wide -> {pw}")
            print(f"Predictions PP long -> {pl}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
