"""
Load DataRobot batch CSVs (target_FP / target_top3 / target_top5), merge on horse_name,
and build ensemble columns plus a heuristic composite score.

FP models predict expected finish position (lower is better). Classifiers expose
``target_topX_1_PREDICTION`` as P(top X). The composite blends ensemble probabilities
with a rank-based FP strength; FP is intentionally low-weight.

This is a descriptive blend, not a calibrated joint probability model.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

KNOWN_TARGETS = ("target_FP", "target_top3", "target_top5")

DEFAULT_BLEND_WEIGHTS = {
    "ensemble_top3": 0.5,
    "ensemble_top5": 0.4,
    "fp_strength": 0.1,
}


@dataclass
class FileMeta:
    target: str
    model_label: str
    model_id: str
    path: str
    column_name: str


@dataclass
class CombinedPredictionBundle:
    """Wide frame (one row per horse) plus file metadata and blend weights."""

    wide: pd.DataFrame
    meta: list[FileMeta] = field(default_factory=list)
    blend_weights: dict[str, float] = field(
        default_factory=lambda: dict(DEFAULT_BLEND_WEIGHTS)
    )

    def to_json_payload(self) -> dict[str, Any]:
        """Records safe for JSON (NaN -> null). Frontend-friendly."""
        df = self.wide.replace({np.nan: None})
        return {
            "blend_weights": self.blend_weights,
            "meta": [asdict(m) for m in self.meta],
            "horses": df.to_dict(orient="records"),
            "columns": list(df.columns),
        }


def _repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def default_predictions_dir() -> Path:
    return _repo_root() / "data prep" / "data" / "predictions"


def default_output_dir() -> Path:
    return _repo_root() / "app" / "output"


def parse_prediction_filename(path: Path) -> tuple[str, str, str] | None:
    """
    Parse ``predictions_{target}_{model_label}_{model_id}.csv``.

    ``model_id`` is the final underscore-separated segment (DataRobot model id).
    """
    name = path.name
    if not name.startswith("predictions_") or not name.endswith(".csv"):
        return None
    stem = name[: -len(".csv")]
    body = stem[len("predictions_") :]
    for tgt in KNOWN_TARGETS:
        prefix = tgt + "_"
        if body.startswith(prefix):
            remainder = body[len(prefix) :]
            idx = remainder.rfind("_")
            if idx <= 0:
                return None
            model_id = remainder[idx + 1 :]
            model_label = remainder[:idx]
            if not model_id or not model_label:
                return None
            return tgt, model_label, model_id
    return None


_SLUG_SAFE = re.compile(r"[^a-zA-Z0-9]+")


def _column_slug(model_label: str, max_len: int = 48) -> str:
    s = _SLUG_SAFE.sub("_", model_label.strip()).strip("_")
    if len(s) > max_len:
        s = s[:max_len].rstrip("_")
    return s or "model"


def _value_column_for_target(target: str) -> str:
    if target == "target_FP":
        return "target_FP_PREDICTION"
    if target == "target_top3":
        return "target_top3_1_PREDICTION"
    if target == "target_top5":
        return "target_top5_1_PREDICTION"
    raise ValueError(f"unknown target {target!r}")


def _prefix_for_target(target: str) -> str:
    return {"target_FP": "fp", "target_top3": "top3", "target_top5": "top5"}[target]


def load_prediction_csv(path: Path, meta: FileMeta) -> pd.DataFrame:
    try:
        df = pd.read_csv(path)
    except pd.errors.EmptyDataError as e:
        raise ValueError(f"{path}: empty CSV") from e
    if len(df) == 0:
        raise ValueError(f"{path}: no data rows")
    vc = _value_column_for_target(meta.target)
    if vc not in df.columns:
        raise ValueError(f"{path}: missing column {vc!r}")
    if "horse_name" not in df.columns:
        raise ValueError(f"{path}: missing horse_name")
    dup = df["horse_name"].duplicated()
    if dup.any():
        raise ValueError(f"{path}: duplicate horse_name rows: {df.loc[dup, 'horse_name'].tolist()}")
    out = df[["horse_name", vc]].rename(columns={vc: meta.column_name})
    return out


def _spearman_warning(wide: pd.DataFrame) -> None:
    if "ensemble_top3" not in wide.columns or "ensemble_fp_mean" not in wide.columns:
        return
    try:
        rho = wide["ensemble_top3"].corr(wide["ensemble_fp_mean"], method="spearman")
    except Exception:
        return
    if rho is None or np.isnan(rho):
        return
    # Better finishes -> lower FP mean; higher top3 prob -> better. Expect negative
    # correlation between ensemble_top3 and ensemble_fp_mean (good horses: high top3, low FP).
    if rho > 0.2:
        logger.warning(
            "Spearman(ensemble_top3, ensemble_fp_mean) = %.3f — expected strongly negative "
            "(good horses: high top-3 probability, lower predicted finish position). "
            "Check data alignment.",
            rho,
        )


def build_bundle(
    predictions_dir: Path | None = None,
    *,
    blend_weights: dict[str, float] | None = None,
) -> CombinedPredictionBundle:
    """
    Glob ``predictions_*.csv``, merge on horse_name, add ensemble_* and composite_score.

    Raises if horse sets differ across files (strict alignment).
    """
    root = predictions_dir or default_predictions_dir()
    if not root.is_dir():
        raise FileNotFoundError(f"predictions directory not found: {root}")

    paths = sorted(root.glob("predictions_*.csv"))
    if not paths:
        raise FileNotFoundError(f"no predictions_*.csv under {root}")

    meta_list: list[FileMeta] = []
    frames: list[pd.DataFrame] = []

    for p in paths:
        parsed = parse_prediction_filename(p)
        if not parsed:
            logger.debug("skip non-matching file: %s", p.name)
            continue
        target, model_label, model_id = parsed
        slug = _column_slug(model_label)
        col = f"{_prefix_for_target(target)}__{slug}__{model_id}"
        m = FileMeta(
            target=target,
            model_label=model_label,
            model_id=model_id,
            path=str(p.resolve()),
            column_name=col,
        )
        try:
            frames.append(load_prediction_csv(p, m))
        except ValueError as e:
            logger.warning("skip %s: %s", p.name, e)
            continue
        meta_list.append(m)

    if not frames:
        raise ValueError(f"no valid prediction files under {root}")

    wide = frames[0]
    for nxt in frames[1:]:
        wide = wide.merge(nxt, on="horse_name", how="inner")

    n0 = len(frames[0])
    if len(wide) != n0:
        raise ValueError(
            f"horse_name sets differ across files: merged {len(wide)} rows, "
            f"expected {n0} from first file — check scoring intake alignment."
        )

    fp_cols = [m.column_name for m in meta_list if m.target == "target_FP"]
    t3_cols = [m.column_name for m in meta_list if m.target == "target_top3"]
    t5_cols = [m.column_name for m in meta_list if m.target == "target_top5"]

    if fp_cols:
        wide["ensemble_fp_mean"] = wide[fp_cols].mean(axis=1)
        # Lower expected finish -> better. Rank ascending then percentile [0,1], higher = better.
        ranks = wide["ensemble_fp_mean"].rank(method="average", ascending=True)
        wide["fp_strength"] = (ranks - 1) / max(len(wide) - 1, 1)
    else:
        wide["ensemble_fp_mean"] = np.nan
        wide["fp_strength"] = 0.5

    wide["ensemble_top3"] = wide[t3_cols].mean(axis=1) if t3_cols else np.nan
    wide["ensemble_top5"] = wide[t5_cols].mean(axis=1) if t5_cols else np.nan

    w = dict(DEFAULT_BLEND_WEIGHTS)
    if blend_weights:
        w.update(blend_weights)

    wide["composite_score"] = (
        w.get("ensemble_top3", 0.5) * wide["ensemble_top3"].fillna(0)
        + w.get("ensemble_top5", 0.4) * wide["ensemble_top5"].fillna(0)
        + w.get("fp_strength", 0.1) * wide["fp_strength"].fillna(0)
    )

    _spearman_warning(wide)

    return CombinedPredictionBundle(
        wide=wide.sort_values("composite_score", ascending=False).reset_index(drop=True),
        meta=meta_list,
        blend_weights=w,
    )


def bundle_to_json(bundle: CombinedPredictionBundle, indent: int | None = 2) -> str:
    payload = bundle.to_json_payload()
    return json.dumps(payload, indent=indent, allow_nan=False)
