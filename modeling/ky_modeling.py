#!/usr/bin/env python3
"""
Kentucky Derby 2026 — DataRobot pipeline (idempotent Use Case, dataset, three projects).

Phase A: MANUAL target → predictor FL from Informative Features minus targets and official_final_odds.
Phase B: Parallel Quick autopilot → barrier wait_for_autopilot on all three.
Phase C: Recommended → FrozenModel parent → feature impact (reuse cached FI when possible;
request only if missing) → poll → FI top-100 FL (reuse exact hash, else reuse any FI top100
that already has leaderboard models from Comprehensive, else create; KY_FORCE_NEW_FI_TOP100 to
skip that reuse) → Comprehensive only when no models yet on the chosen FI list → barrier wait.
Phase D: Top 5 models per project by CV score → batch score AI Catalog dataset → data prep/data/predictions
(with passthrough `horse_name` only, max_explanations=5; skip if output CSV already exists — delete old CSVs when changing batch options).
(DataRobot may still queue jobs server-side by account limits.)

Credentials: modeling/.env. Data: ../data prep/data/processed/combined.csv
"""

from __future__ import annotations

import logging
import math
import os
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

import datarobot as dr
import datarobot.errors as dre
from datarobot.enums import AUTOPILOT_MODE, PROJECT_STAGE
from datarobot.models import FrozenModel
from datarobot.models.batch_job import IntakeAdapters, OutputAdapters
from datarobot.models.recommended_model import ModelRecommendation
from datarobotx.idp.common.hashing import get_hash
from datarobotx.idp.datasets import get_or_create_dataset_from_file
from datarobotx.idp.projects import get_or_create_project_from_dataset
from datarobotx.idp.use_cases import get_or_create_use_case
from dotenv import load_dotenv

USE_CASE_NAME = "Kentucky Derby 2026"
USE_CASE_DESCRIPTION = "Kentucky Derby 2026 — ky_modeling.py idempotent pipeline"
DATASET_NAME = "Kentucky Derby combined"

TARGETS = ("target_FP", "target_top3", "target_top5")
EXCLUDED_TARGETS = ("target_FP", "target_top3", "target_top5")
# Also excluded from Informative-based predictor featurelist (not targets).
EXTRA_PREDICTOR_EXCLUSIONS = ("official_final_odds",)
PREDICTOR_EXCLUSIONS = EXCLUDED_TARGETS + EXTRA_PREDICTOR_EXCLUSIONS

INFORMATIVE_FEATURES = "Informative Features"
PREDICTOR_FL_PREFIX = "KD predictors Informative"
FI_TOP100_PREFIX = "FI top100"

FL_TOKEN = get_hash("Informative", *PREDICTOR_EXCLUSIONS)

# AI Catalog dataset used as batch scoring intake (override with KY_PREDICTIONS_DATASET_ID).
PREDICTIONS_INTAKE_DATASET_ID_DEFAULT = "69f56fb600691f79bbdabc9b"

TOP_MODELS_PER_PROJECT = 5

# Phase D batch output: intake columns passed through to scored CSV (comma-separated env override).
BATCH_PASSTHROUGH_COLUMNS_DEFAULT = ("horse_name",)
BATCH_MAX_EXPLANATIONS_DEFAULT = 5


def _batch_passthrough_columns() -> list[str]:
    raw = os.environ.get("KY_BATCH_PASSTHROUGH_COLUMNS", "").strip()
    if raw:
        return [c.strip() for c in raw.split(",") if c.strip()]
    return list(BATCH_PASSTHROUGH_COLUMNS_DEFAULT)


def _batch_max_explanations() -> int:
    return int(os.environ.get("KY_BATCH_MAX_EXPLANATIONS", str(BATCH_MAX_EXPLANATIONS_DEFAULT)))


def _ensure_prediction_explanations_initialized(project_id: str, model_id: str) -> bool:
    """Return True if batch jobs may use max_explanations; False if PE init is not possible (e.g. 422)."""
    try:
        dr.PredictionExplanationsInitialization.get(project_id, model_id)
        logger.info(
            "    Prediction explanations already initialized for model %s",
            model_id,
        )
        return True
    except dre.ClientError as e:
        if e.status_code == 422:
            logger.warning(
                "    Prediction explanations unavailable for model %s: %s",
                model_id,
                e,
            )
            return False
        if e.status_code != 404:
            raise

    try:
        logger.info("    Initializing prediction explanations for model %s ...", model_id)
        job = dr.PredictionExplanationsInitialization.create(project_id, model_id)
        job.wait_for_completion(max_wait=7200)
        return True
    except dre.ClientError as e:
        if e.status_code == 422:
            logger.warning(
                "    PE initialization failed for model %s: %s — batch will omit explanation columns",
                model_id,
                e,
            )
            return False
        raise


# Batch scoring: wait for download link / streaming (default SDK download_timeout is 120s; queue-heavy accounts may need more).
def _batch_predict_download_timeout() -> int:
    return int(os.environ.get("KY_BATCH_PREDICT_DOWNLOAD_TIMEOUT", "3600"))


def _batch_predict_download_read_timeout() -> int:
    return int(os.environ.get("KY_BATCH_PREDICT_DOWNLOAD_READ_TIMEOUT", "7200"))


logger = logging.getLogger("ky_modeling")


class _FlushStreamHandler(logging.StreamHandler):
    """Emit log lines to stdout and flush so terminal progress is visible immediately."""

    def emit(self, record: logging.LogRecord) -> None:
        super().emit(record)
        self.flush()


def _configure_logging() -> None:
    logger.setLevel(logging.INFO)
    logger.handlers.clear()
    h = _FlushStreamHandler(sys.stdout)
    h.setLevel(logging.INFO)
    h.setFormatter(
        logging.Formatter("%(asctime)s | %(levelname)s | %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
    )
    logger.addHandler(h)
    logger.propagate = False


def _repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _combined_csv_path() -> Path:
    return _repo_root() / "data prep" / "data" / "processed" / "combined.csv"


def _predictions_output_dir() -> Path:
    out = _repo_root() / "data prep" / "data" / "predictions"
    out.mkdir(parents=True, exist_ok=True)
    return out


def _predictions_intake_dataset_id() -> str:
    return os.environ.get("KY_PREDICTIONS_DATASET_ID", PREDICTIONS_INTAKE_DATASET_ID_DEFAULT)


def _sanitize_filename_part(name: str, max_len: int = 90) -> str:
    s = re.sub(r"[^\w\-.]+", "_", name.strip())
    s = re.sub(r"_+", "_", s).strip("_")
    return (s[:max_len] if s else "model")


def _unwrap_project_metrics_meta(meta: Any) -> list[dict[str, Any]]:
    if isinstance(meta, dict):
        return meta["metric_details"]
    return meta.metric_details


def _metric_is_ascending(project: dr.Project, metric_name: str) -> bool:
    """True if lower metric values are better (RMSE, LogLoss, …)."""
    project.refresh()
    tgt = project.target
    if not tgt:
        raise RuntimeError(f"Project {project.id} has no target")
    details = _unwrap_project_metrics_meta(project.get_metrics(tgt))
    for m in details:
        if m["metric_name"] == metric_name:
            return bool(m["ascending"])
    raise ValueError(f"Metric {metric_name!r} not found in project {project.id} metric_details")


def _cv_primary_score(model: dr.Model, metric: str) -> float | None:
    """Leaderboard score for ranking: prefer crossValidation, then backtesting, then validation."""
    row = (model.metrics or {}).get(metric)
    if not row:
        return None
    for key in ("crossValidation", "backtesting", "validation"):
        v = row.get(key)
        if v is None:
            continue
        try:
            f = float(v)
        except (TypeError, ValueError):
            continue
        if math.isnan(f):
            continue
        return f
    return None


def _top_models_by_cv(project_id: str, limit: int) -> list[dr.Model]:
    project = dr.Project.get(project_id)
    project.refresh()
    metric = project.metric
    if not metric:
        raise RuntimeError(f"Project {project_id} has no optimization metric")

    is_ascending = _metric_is_ascending(project, metric)

    scored: list[tuple[float, str, dr.Model]] = []
    for m in dr.Model.list(project_id):
        score = _cv_primary_score(m, metric)
        if score is None:
            continue
        scored.append((score, m.id, m))

    scored.sort(
        key=lambda x: (-x[0], x[1]) if not is_ascending else (x[0], x[1])
    )
    out_models = [t[2] for t in scored[:limit]]
    if len(out_models) < limit:
        logger.warning(
            "  Only %s model(s) with CV/backtest/validation scores for metric %r (wanted %s)",
            len(out_models),
            metric,
            limit,
        )
    return out_models


def _run_batch_predictions_for_project(
    project_id: str,
    target: str,
    intake_dataset_id: str,
    models: list[dr.Model],
) -> None:
    catalog = dr.Dataset.get(intake_dataset_id)
    out_dir = _predictions_output_dir()
    passthrough = _batch_passthrough_columns()
    max_pe = _batch_max_explanations()

    for m in models:
        full = dr.Model.get(project_id, m.id)
        model_label = _sanitize_filename_part(getattr(full, "model_type", "model"))
        fname = f"predictions_{target}_{model_label}_{full.id}.csv"
        out_path = out_dir / fname

        # Same path as older runs; if batch columns/explanations changed, remove stale CSVs or we skip forever.
        if out_path.is_file():
            logger.info(
                "  Skip batch scoring (already exists) target=%r model=%s → %s",
                target,
                full.id,
                out_path,
            )
            continue

        logger.info(
            "  Batch scoring target=%r model=%s (%s) → %s",
            target,
            full.id,
            model_label,
            out_path,
        )

        pe_for_batch = max_pe
        if max_pe > 0 and not _ensure_prediction_explanations_initialized(project_id, full.id):
            pe_for_batch = 0

        batch_kw: dict[str, Any] = {
            "intake_settings": {
                "type": IntakeAdapters.DATASET,
                "dataset": catalog,
            },
            "output_settings": {
                "type": OutputAdapters.LOCAL_FILE,
                "path": str(out_path),
            },
            "passthrough_columns": passthrough,
            "download_timeout": _batch_predict_download_timeout(),
            "download_read_timeout": _batch_predict_download_read_timeout(),
        }
        if pe_for_batch > 0:
            batch_kw["max_explanations"] = pe_for_batch

        dr.BatchPredictionJob.score_with_leaderboard_model(full, **batch_kw)


def _load_env() -> tuple[str, str]:
    load_dotenv(Path(__file__).resolve().parent / ".env")
    try:
        token = os.environ["DATAROBOT_API_TOKEN"]
        endpoint = os.environ["DATAROBOT_ENDPOINT"]
    except KeyError as e:
        raise SystemExit(
            f"Missing env var {e!s}. Set DATAROBOT_API_TOKEN and DATAROBOT_ENDPOINT in modeling/.env"
        ) from e
    return token, endpoint


def _log_dataset_featurelists(dataset_id: str) -> None:
    try:
        ds = dr.Dataset.get(dataset_id)
        flists = ds.get_featurelists()
        logger.info(f"  Dataset {dataset_id!r}: {len(flists)} featurelist(s) at catalog scope")
        for fl in flists[:20]:
            logger.info(f"    - {fl.name!r}")
        if len(flists) > 20:
            logger.info(f"    ... ({len(flists) - 20} more)")
    except Exception as exc:
        logger.warning("  Could not list dataset featurelists: %s", exc)


def _register_manual_target(project: dr.Project, target: str) -> None:
    project.refresh()
    st = project.get_status()
    if st.get("stage") == PROJECT_STAGE.MODELING:
        logger.info(f"    Target stage already MODELING for {project.id}; skipping MANUAL registration.")
        return
    logger.info(f"    analyze_and_model MANUAL target={target!r} ...")
    project.analyze_and_model(target=target, mode=AUTOPILOT_MODE.MANUAL, max_wait=3600)


def _wait_informative_on_project(project: dr.Project, timeout_secs: int = 3600) -> None:
    deadline = time.time() + timeout_secs
    while time.time() < deadline:
        project.refresh()
        if project.get_featurelist_by_name(INFORMATIVE_FEATURES) is not None:
            return
        time.sleep(10)
    raise TimeoutError(
        f"Timed out waiting for '{INFORMATIVE_FEATURES}' on project {project.id}"
    )


def _get_or_create_predictor_featurelist(project: dr.Project) -> dr.Featurelist:
    label = f"{PREDICTOR_FL_PREFIX} [{FL_TOKEN}]"
    for fl in project.get_featurelists():
        if FL_TOKEN in fl.name and fl.name.startswith(PREDICTOR_FL_PREFIX):
            logger.info("  Reusing existing predictor featurelist id=%s name=%r", fl.id, fl.name)
            return fl
    try:
        return project.create_featurelist(
            name=label,
            starting_featurelist_name=INFORMATIVE_FEATURES,
            features_to_exclude=list(PREDICTOR_EXCLUSIONS),
        )
    except Exception:
        _wait_informative_on_project(project)
        return project.create_featurelist(
            name=label,
            starting_featurelist_name=INFORMATIVE_FEATURES,
            features_to_exclude=list(PREDICTOR_EXCLUSIONS),
        )


def _kickoff_quick(project_id: str, predictor_fl_id: str) -> str:
    p = dr.Project.get(project_id)
    p.refresh()
    st = p.get_status()
    if st.get("autopilot_done"):
        return "quick_skipped_done"
    p.start_autopilot(predictor_fl_id, mode=AUTOPILOT_MODE.QUICK)
    return "quick_started"


def _wait_all_autopilot(project_ids: list[str]) -> None:
    """Wait on all projects concurrently (same wall time as slowest project)."""

    def _wait_one(pid: str) -> str:
        logger.info(f"  Waiting for autopilot (Quick): {pid} ...")
        dr.Project.get(pid).wait_for_autopilot(timeout=48 * 3600, verbosity=0)
        return pid

    if not project_ids:
        return
    with ThreadPoolExecutor(max_workers=len(project_ids)) as ex:
        list(ex.map(_wait_one, project_ids))


def _resolve_parent_for_feature_impact(project_id: str, model: dr.Model) -> dr.Model:
    if getattr(model, "is_frozen", False):
        fm = FrozenModel.get(project_id, model.id)
        pid = getattr(fm, "parent_model_id", None)
        if not pid:
            raise RuntimeError(f"Frozen model {model.id} has no parent_model_id")
        return dr.Model.get(project_id, pid)
    return model


def _request_feature_impact_subset(parents: list[tuple[dr.Project, dr.Model]]) -> None:
    """Issue FI requests only for the given parents (subset)."""

    def _request_one(item: tuple[dr.Project, dr.Model]) -> str:
        proj, parent = item
        logger.info(f"  request_feature_impact parent={parent.id} project={proj.id}")
        parent.request_feature_impact()
        return proj.id

    if not parents:
        return
    with ThreadPoolExecutor(max_workers=len(parents)) as ex:
        list(ex.map(_request_one, parents))


def _poll_feature_impact_until_ready(
    parents: list[tuple[dr.Project, dr.Model]],
    poll_secs: int = 60,
    timeout_secs: int = 48 * 3600,
    initial_results: dict[str, list[Any]] | None = None,
) -> dict[str, list[Any]]:
    deadline = time.time() + timeout_secs
    results: dict[str, list[Any]] = dict(initial_results or {})
    pending = {proj.id for proj, _ in parents if proj.id not in results}

    while time.time() < deadline and pending:
        for proj, parent in parents:
            if proj.id not in pending:
                continue
            try:
                fi = parent.get_feature_impact()
                results[proj.id] = fi
                pending.discard(proj.id)
                logger.info(f"    Feature impact ready for project {proj.id}")
            except dre.ClientError as e:
                if e.status_code not in (404, 422):
                    raise
            except Exception:
                pass
        if pending:
            logger.info(f"  FI pending for {len(pending)} project(s); sleeping {poll_secs}s ...")
            time.sleep(poll_secs)

    if pending:
        raise TimeoutError(f"Feature impact not ready for projects: {pending}")
    return results


def _top100_feature_names(fi_rows: list[Any]) -> list[str]:
    def norm(row: Any) -> float:
        if isinstance(row, dict):
            return float(row.get("impactNormalized") or row.get("impact_normalized") or 0)
        return float(getattr(row, "impact_normalized", None) or getattr(row, "impactNormalized", None) or 0)

    def fname(row: Any) -> str:
        if isinstance(row, dict):
            return str(row.get("featureName") or row.get("feature_name") or "")
        return str(getattr(row, "feature_name", None) or getattr(row, "featureName", None) or "")

    rows = list(fi_rows)
    rows.sort(key=lambda r: (-norm(r), fname(r)))
    out: list[str] = []
    seen: set[str] = set()
    for row in rows:
        n = fname(row)
        if n and n not in seen:
            seen.add(n)
            out.append(n)
        if len(out) >= 100:
            break
    return out


def _force_new_fi_top100_featurelist() -> bool:
    """If true, do not reuse another project's FI top100 list that already has models."""
    return os.environ.get("KY_FORCE_NEW_FI_TOP100", "").strip().lower() in (
        "1",
        "true",
        "yes",
    )


def _resolve_fi_top100_featurelist(
    project: dr.Project, parent_model_id: str, names: list[str]
) -> dr.Featurelist:
    """Pick FI top100 FL: exact hash match, else any FI top100 that already has Comprehensive models, else create."""
    project.refresh()
    fi_token = get_hash(parent_model_id, tuple(names))
    label = f"{FI_TOP100_PREFIX} [{fi_token}]"

    for fl in project.get_featurelists():
        if fi_token in fl.name and fl.name.startswith(FI_TOP100_PREFIX):
            logger.info(
                "  Reusing FI top100 matching current parent/FI hash id=%s name=%r",
                fl.id,
                fl.name,
            )
            return fl

    if not _force_new_fi_top100_featurelist():
        reuse_candidates = [
            fl
            for fl in project.get_featurelists()
            if fl.name.startswith(FI_TOP100_PREFIX)
            and _models_exist_for_featurelist(project.id, fl.id)
        ]
        if reuse_candidates:
            reuse_candidates.sort(key=lambda x: x.name)
            chosen = reuse_candidates[0]
            logger.info(
                "  Reusing FI top100 that already has leaderboard models (no new FL / Comprehensive): "
                "id=%s name=%r",
                chosen.id,
                chosen.name,
            )
            return chosen

    logger.info("  Creating FI top100 featurelist %r (%s features)", label, len(names))
    return project.create_featurelist(name=label, features=names)


def _models_exist_for_featurelist(project_id: str, featurelist_id: str) -> bool:
    for m in dr.Model.list(project_id):
        if getattr(m, "featurelist_id", None) == featurelist_id:
            return True
    return False


def _kickoff_comprehensive(
    project_id: str, fi_featurelist_id: str, target: str
) -> bool:
    """Start Comprehensive without waiting. Returns True if a run was started."""
    project = dr.Project.get(project_id)
    project.refresh()
    if _models_exist_for_featurelist(project_id, fi_featurelist_id):
        logger.info(
            f"  [{target}] Comprehensive skipped — leaderboard already has models "
            f"for FI list {fi_featurelist_id!r}"
        )
        return False
    logger.info(f"  [{target}] start_autopilot COMPREHENSIVE featurelist={fi_featurelist_id}")
    project.start_autopilot(fi_featurelist_id, mode=AUTOPILOT_MODE.COMPREHENSIVE)
    return True


def _wait_comprehensive_autopilot(project_ids: list[str]) -> None:
    """Wait for Comprehensive in parallel so one project does not block others."""

    def _wait_one(pid: str) -> str:
        logger.info(f"  Waiting for autopilot (Comprehensive): {pid} ...")
        dr.Project.get(pid).wait_for_autopilot(timeout=72 * 3600, verbosity=0)
        return pid

    if not project_ids:
        return
    with ThreadPoolExecutor(max_workers=len(project_ids)) as ex:
        list(ex.map(_wait_one, project_ids))


def _kickoff_comprehensive_job(job: tuple[str, str, str]) -> str | None:
    """Worker for parallel Comprehensive kickoff: (project_id, fi_fl_id, target)."""
    pid, fl_id, target = job
    return pid if _kickoff_comprehensive(pid, fl_id, target) else None


def main() -> None:
    _configure_logging()
    csv_path = _combined_csv_path()
    if not csv_path.is_file():
        raise SystemExit(f"Data file not found: {csv_path}")

    logger.info(
        "Predictor featurelist excludes Informative columns: %s",
        PREDICTOR_EXCLUSIONS,
    )

    token, endpoint = _load_env()
    dr.Client(token=token, endpoint=endpoint)

    logger.info("Use case...")
    use_case_id = get_or_create_use_case(
        endpoint, token, USE_CASE_NAME, USE_CASE_DESCRIPTION
    )
    logger.info(f"  id={use_case_id}")

    logger.info("Dataset (idempotent upload)...")
    dataset_id = get_or_create_dataset_from_file(
        endpoint,
        token,
        DATASET_NAME,
        str(csv_path),
        use_cases=use_case_id,
    )
    logger.info(f"  id={dataset_id}")
    _log_dataset_featurelists(dataset_id)

    works: list[dict[str, Any]] = []
    for target in TARGETS:
        logger.info(f"\n=== Setup project target={target!r} ===")
        prep_token = get_hash(dataset_id, use_case_id, "kd2026_modeling", target)
        project_label = f"Kentucky Derby modeling [{prep_token}]"
        project_id = get_or_create_project_from_dataset(
            endpoint,
            token,
            project_label,
            dataset_id,
            use_case=use_case_id,
        )
        logger.info(f"  project_id={project_id} name={project_label!r}")
        project = dr.Project.get(project_id)
        _register_manual_target(project, target)
        _wait_informative_on_project(project)
        pfl = _get_or_create_predictor_featurelist(project)
        logger.info(f"  predictor featurelist id={pfl.id} name={pfl.name!r}")
        works.append(
            {
                "target": target,
                "project_id": project_id,
                "predictor_fl_id": pfl.id,
            }
        )

    logger.info("\n=== Phase B: parallel Quick autopilot ===")
    with ThreadPoolExecutor(max_workers=3) as ex:
        futs = [
            ex.submit(_kickoff_quick, w["project_id"], w["predictor_fl_id"]) for w in works
        ]
        for f in as_completed(futs):
            logger.info(f"  {f.result()}")

    _wait_all_autopilot([w["project_id"] for w in works])

    logger.info("\n=== Phase C: recommended → parent → FI → top100 → Comprehensive ===")
    parents: list[tuple[dr.Project, dr.Model]] = []

    for w in works:
        proj = dr.Project.get(w["project_id"])
        rec = ModelRecommendation.get(proj.id)
        if rec is None:
            raise RuntimeError(f"No recommended model for project {proj.id}")
        m = rec.get_model()
        parent = _resolve_parent_for_feature_impact(proj.id, m)
        parents.append((proj, parent))
        logger.info(
            f"  target={w['target']!r} recommended={m.id} frozen={getattr(m,'is_frozen',False)} "
            f"fi_model={parent.id}"
        )

    fi_prefetch: dict[str, list[Any]] = {}
    fi_need_request: list[tuple[dr.Project, dr.Model]] = []
    for proj, parent in parents:
        try:
            fi_prefetch[proj.id] = parent.get_feature_impact()
            logger.info(
                "    Feature impact already available for project %s — skipping new FI job",
                proj.id,
            )
        except dre.ClientError as e:
            if e.status_code in (404, 422):
                fi_need_request.append((proj, parent))
            else:
                raise

    if fi_need_request:
        logger.info(
            "  Requesting feature impact for %s project(s) without cached FI ...",
            len(fi_need_request),
        )
        _request_feature_impact_subset(fi_need_request)

    fi_results = _poll_feature_impact_until_ready(parents, initial_results=fi_prefetch)

    comprehensive_jobs: list[tuple[str, str, str]] = []
    for w in works:
        proj = dr.Project.get(w["project_id"])
        fi_rows = fi_results[proj.id]
        names = _top100_feature_names(fi_rows)
        rec = ModelRecommendation.get(proj.id)
        parent = _resolve_parent_for_feature_impact(proj.id, rec.get_model())
        fi_fl = _resolve_fi_top100_featurelist(proj, parent.id, names)
        logger.info(
            f"  target={w['target']!r} FI top100 fl={fi_fl.id!r} ({len(names)} features)"
        )
        comprehensive_jobs.append((proj.id, fi_fl.id, w["target"]))

    logger.info("\n=== Phase C2: Comprehensive kickoff (parallel) ===")
    pending_comprehensive: list[str] = []
    if comprehensive_jobs:
        n_workers = len(comprehensive_jobs)
        with ThreadPoolExecutor(max_workers=n_workers) as ex:
            kick_results = list(ex.map(_kickoff_comprehensive_job, comprehensive_jobs))
        pending_comprehensive = [r for r in kick_results if r]

    if comprehensive_jobs and not pending_comprehensive:
        logger.info(
            "  All Comprehensive runs skipped — FI top100 lists already have leaderboard models."
        )

    if pending_comprehensive:
        logger.info("\n=== Phase C3: wait for Comprehensive autopilots (parallel) ===")
        _wait_comprehensive_autopilot(pending_comprehensive)

    intake_pred_id = _predictions_intake_dataset_id()
    logger.info("\n=== Phase D: batch predictions (top %s per project) ===", TOP_MODELS_PER_PROJECT)
    logger.info("  Intake AI Catalog dataset id=%s", intake_pred_id)
    logger.info(
        "  Passthrough columns=%s max_explanations=%s (env KY_BATCH_PASSTHROUGH_COLUMNS, KY_BATCH_MAX_EXPLANATIONS)",
        _batch_passthrough_columns(),
        _batch_max_explanations(),
    )

    for w in works:
        top = _top_models_by_cv(w["project_id"], TOP_MODELS_PER_PROJECT)
        if not top:
            logger.warning("  No scorable models for target=%r project=%s", w["target"], w["project_id"])
            continue
        logger.info(
            "  target=%r project=%s top_model_ids=%s",
            w["target"],
            w["project_id"],
            [m.id for m in top],
        )
        _run_batch_predictions_for_project(
            w["project_id"], w["target"], intake_pred_id, top
        )

    logger.info("\n=== Summary ===")
    logger.info(f"use_case_id={use_case_id}")
    logger.info(f"dataset_id={dataset_id}")
    for w in works:
        n = len(dr.Model.list(w["project_id"]))
        logger.info(f"target={w['target']!r} project_id={w['project_id']} models={n}")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        logging.getLogger("ky_modeling").warning("Interrupted")
        sys.exit(130)
