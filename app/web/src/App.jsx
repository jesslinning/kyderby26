import { useCallback, useEffect, useMemo, useState } from "react";
import { DefinitionsTab } from "./Definitions.jsx";
import { GlossaryTerm } from "./GlossaryTerm.jsx";
import { HorseLink } from "./HorseLink.jsx";

const TABS = [
  { id: "overview", label: "Overview" },
  { id: "rankings", label: "Rankings" },
  { id: "exacta", label: "Exacta" },
  { id: "trifecta", label: "Trifecta" },
  { id: "superfecta", label: "Superfecta" },
  { id: "models", label: "Models" },
  { id: "definitions", label: "Definitions" },
];

function pct(x) {
  if (x == null || Number.isNaN(x)) return "—";
  return `${(x * 100).toFixed(2)}%`;
}

function fmtScore(x) {
  if (x == null || Number.isNaN(x)) return "—";
  return Number(x).toFixed(4);
}

/** Sortable prediction table header: label + sort control + glossary icon (icon-only). */
function PredictionSortHeader({ sortKey, label, predictionSort, onSort, glossary }) {
  const active = predictionSort.key === sortKey;
  const ariaSort = active
    ? predictionSort.dir === "asc"
      ? "ascending"
      : "descending"
    : undefined;

  const sortAriaLabel = active
    ? `Sorted by ${label}, ${predictionSort.dir === "asc" ? "ascending" : "descending"}. Press to reverse order.`
    : `Sort table by ${label}`;

  return (
    <th scope="col" aria-sort={ariaSort}>
      <div className="th-ranking">
        <button
          type="button"
          className="th-ranking__sort"
          aria-label={sortAriaLabel}
          onClick={() => onSort(sortKey)}
        >
          <span>{label}</span>
          <span
            className={
              active ? "th-ranking__chev th-ranking__chev--active" : "th-ranking__chev"
            }
            aria-hidden
          >
            {active ? (predictionSort.dir === "asc" ? "↑" : "↓") : "↕"}
          </span>
        </button>
        {glossary}
      </div>
    </th>
  );
}

export default function App() {
  const [combined, setCombined] = useState(null);
  const [scenarios, setScenarios] = useState(null);
  const [error, setError] = useState(null);
  const [tab, setTab] = useState("overview");
  const [definitionScrollTarget, setDefinitionScrollTarget] = useState(null);
  const [predictionSort, setPredictionSort] = useState({
    key: "composite_score",
    dir: "desc",
  });

  const goToDefinition = useCallback((defId) => {
    setTab("definitions");
    setDefinitionScrollTarget(defId);
  }, []);

  useEffect(() => {
    if (tab !== "definitions" || !definitionScrollTarget) return;
    const id = definitionScrollTarget;
    const t = window.setTimeout(() => {
      document.getElementById(`def-${id}`)?.scrollIntoView({
        behavior: "smooth",
        block: "start",
      });
      setDefinitionScrollTarget(null);
    }, 80);
    return () => window.clearTimeout(t);
  }, [tab, definitionScrollTarget]);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const [c, s] = await Promise.all([
          fetch(`${import.meta.env.BASE_URL}combined_predictions.json`).then((r) => {
            if (!r.ok) throw new Error(`combined_predictions.json: ${r.status}`);
            return r.json();
          }),
          fetch(`${import.meta.env.BASE_URL}scenarios.json`).then((r) => {
            if (!r.ok) throw new Error(`scenarios.json: ${r.status}`);
            return r.json();
          }),
        ]);
        if (!cancelled) {
          setCombined(c);
          setScenarios(s);
        }
      } catch (e) {
        if (!cancelled) setError(e.message || String(e));
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const horsesSorted = useMemo(() => {
    if (!combined?.horses) return [];
    return [...combined.horses].sort(
      (a, b) => (b.composite_score ?? 0) - (a.composite_score ?? 0)
    );
  }, [combined]);

  const togglePredictionSort = useCallback((key) => {
    setPredictionSort((prev) => {
      if (prev.key === key) {
        return { key, dir: prev.dir === "asc" ? "desc" : "asc" };
      }
      return {
        key,
        dir: key === "horse_name" ? "asc" : "desc",
      };
    });
  }, []);

  const predictionRows = useMemo(() => {
    const rows = [...(combined?.horses ?? [])];
    const { key, dir } = predictionSort;
    const mul = dir === "asc" ? 1 : -1;

    const num = (v) => {
      if (v == null || v === "") return null;
      const n = Number(v);
      return Number.isFinite(n) ? n : null;
    };

    rows.sort((a, b) => {
      if (key === "horse_name") {
        const cmp = String(a.horse_name ?? "").localeCompare(
          String(b.horse_name ?? ""),
          undefined,
          { sensitivity: "base" }
        );
        return mul * cmp;
      }
      const na = num(a[key]);
      const nb = num(b[key]);
      if (na === null && nb === null) return 0;
      if (na === null) return 1;
      if (nb === null) return -1;
      return mul * (na - nb);
    });
    return rows;
  }, [combined?.horses, predictionSort]);

  const maxComposite = useMemo(() => {
    if (!horsesSorted.length) return 1;
    return Math.max(...horsesSorted.map((h) => h.composite_score ?? 0), 1e-9);
  }, [horsesSorted]);

  if (error) {
    return (
      <div className="shell">
        <header className="hero">
          <h1>Kentucky Derby prediction explorer</h1>
        </header>
        <div className="card error">
          <strong>Could not load JSON.</strong> Run{" "}
          <code className="mono">npm run data</code> from <code className="mono">app/web</code>{" "}
          (or copy <code className="mono">app/output/*.json</code> into{" "}
          <code className="mono">app/web/public/</code>), then refresh.
          <pre className="mono detail">{error}</pre>
        </div>
      </div>
    );
  }

  if (!combined || !scenarios) {
    return (
      <div className="shell">
        <p className="loading">Loading predictions…</p>
      </div>
    );
  }

  const w = scenarios.blend_weights ?? combined.blend_weights ?? {};

  return (
    <div className="shell">
      <header className="hero">
        <p className="eyebrow">Derby 2026 · ensemble view</p>
        <h1>Kentucky Derby prediction explorer</h1>
        <p className="lede">
          Heuristic blend of top-3 / top-5 classifiers and finish-position models. Exotic
          “naive” joints are illustrative softmax chains—not track prices.
        </p>
        <div className="weights">
          <span className="pill">
            top3 weight <strong>{w.ensemble_top3 ?? "—"}</strong>
          </span>
          <span className="pill">
            top5 weight <strong>{w.ensemble_top5 ?? "—"}</strong>
          </span>
          <span className="pill">
            FP strength weight <strong>{w.fp_strength ?? "—"}</strong>
          </span>
        </div>
        <p className="glossary-mobile-hint" role="note">
          <strong>Definitions:</strong> tap the circular{" "}
          <span className="glossary-mobile-hint__badge" aria-hidden>
            <svg viewBox="0 0 24 24" focusable="false">
              <path
                fill="currentColor"
                d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm1 15h-2v-6h2v6zm0-8h-2V7h2v2z"
              />
            </svg>
          </span>{" "}
          button beside a term for a one-line summary and <em>Open in Definitions</em>.
        </p>
      </header>

      <div className="tabs-nav">
        <div className="tabs-nav__mobile">
          <label className="tabs-nav__label" htmlFor="section-nav">
            Jump to section
          </label>
          <select
            id="section-nav"
            className="tabs-nav__select"
            value={tab}
            onChange={(e) => setTab(e.target.value)}
          >
            {TABS.map((t) => (
              <option key={t.id} value={t.id}>
                {t.label}
              </option>
            ))}
          </select>
        </div>
        <div className="tabs-scroll">
          <nav className="tabs" aria-label="Sections">
            {TABS.map((t) => (
              <button
                key={t.id}
                type="button"
                className={tab === t.id ? "tab active" : "tab"}
                onClick={() => setTab(t.id)}
              >
                {t.label}
              </button>
            ))}
          </nav>
        </div>
      </div>

      {tab === "overview" && (
        <section className="card">
          <h2 className="h2-with-glossary">
            <GlossaryTerm
              name="Composite score"
              defId="composite-score"
              summary="Weighted mix of average Top 3 likelihood, average Top 5 likelihood, and FP strength—a single ranking score, not a calibrated win probability."
              onNavigate={goToDefinition}
            >
              Composite score
            </GlossaryTerm>{" "}
            <span className="h2-suffix">(top field)</span>
          </h2>
          <p className="muted">
            Bar length is proportional to composite score (max in field = 100%).
          </p>
          <ul className="barlist">
            {horsesSorted.slice(0, 16).map((h) => (
              <li key={h.horse_name}>
                <HorseLink name={h.horse_name} className="bar-name" />
                <div className="bar-track">
                  <div
                    className="bar-fill"
                    style={{
                      width: `${((h.composite_score ?? 0) / maxComposite) * 100}%`,
                    }}
                  />
                </div>
                <span className="bar-val mono">{fmtScore(h.composite_score)}</span>
              </li>
            ))}
          </ul>
        </section>
      )}

      {tab === "rankings" && (
        <section className="card">
          <h2>Prediction ranking</h2>
          <p className="muted table-sort-hint">
            Tap a column heading to sort. The info icon opens the definition.
          </p>
          <p className="table-scroll-hint">Swipe sideways on small screens to see every column.</p>
          <div className="table-wrap">
            <table className="data dense data--sortable">
              <thead>
                <tr>
                  <PredictionSortHeader
                    sortKey="horse_name"
                    label="Horse"
                    predictionSort={predictionSort}
                    onSort={togglePredictionSort}
                    glossary={
                      <GlossaryTerm
                        variant="icon-only"
                        name="Horse"
                        defId="horse"
                        summary="The runner name used to merge every model’s predictions onto one row per horse."
                        onNavigate={goToDefinition}
                      >
                        Horse
                      </GlossaryTerm>
                    }
                  />
                  <PredictionSortHeader
                    sortKey="composite_score"
                    label="Composite"
                    predictionSort={predictionSort}
                    onSort={togglePredictionSort}
                    glossary={
                      <GlossaryTerm
                        variant="icon-only"
                        name="Composite"
                        defId="composite-score"
                        summary="Weighted combination of average Top 3 likelihood, average Top 5 likelihood, and FP strength into one ranking score."
                        onNavigate={goToDefinition}
                      >
                        Composite
                      </GlossaryTerm>
                    }
                  />
                  <PredictionSortHeader
                    sortKey="ensemble_top3"
                    label="Ensemble top3"
                    predictionSort={predictionSort}
                    onSort={togglePredictionSort}
                    glossary={
                      <GlossaryTerm
                        variant="icon-only"
                        name="Ensemble top3"
                        defId="ensemble-top3"
                        summary="The average likelihood across models predicting if a horse will finish in the Top 3."
                        onNavigate={goToDefinition}
                      >
                        Ensemble top3
                      </GlossaryTerm>
                    }
                  />
                  <PredictionSortHeader
                    sortKey="ensemble_top5"
                    label="Ensemble top5"
                    predictionSort={predictionSort}
                    onSort={togglePredictionSort}
                    glossary={
                      <GlossaryTerm
                        variant="icon-only"
                        name="Ensemble top5"
                        defId="ensemble-top5"
                        summary="The average likelihood across models predicting if a horse will finish in the Top 5."
                        onNavigate={goToDefinition}
                      >
                        Ensemble top5
                      </GlossaryTerm>
                    }
                  />
                  <PredictionSortHeader
                    sortKey="fp_strength"
                    label="FP strength"
                    predictionSort={predictionSort}
                    onSort={togglePredictionSort}
                    glossary={
                      <GlossaryTerm
                        variant="icon-only"
                        name="FP strength"
                        defId="fp-strength"
                        summary="How strongly finish-position models favor this horse vs the field, scaled 0–1 from mean predicted place—it is down-weighted in the composite."
                        onNavigate={goToDefinition}
                      >
                        FP strength
                      </GlossaryTerm>
                    }
                  />
                  <PredictionSortHeader
                    sortKey="ensemble_fp_mean"
                    label="Mean FP pred."
                    predictionSort={predictionSort}
                    onSort={togglePredictionSort}
                    glossary={
                      <GlossaryTerm
                        variant="icon-only"
                        name="Mean FP pred."
                        defId="mean-fp-pred"
                        summary="The average predicted finishing position across FP models (each outputs expected place; lower means a better expected finish)."
                        onNavigate={goToDefinition}
                      >
                        Mean FP pred.
                      </GlossaryTerm>
                    }
                  />
                </tr>
              </thead>
              <tbody>
                {predictionRows.map((h) => (
                  <tr key={h.horse_name}>
                    <td>
                      <HorseLink name={h.horse_name} />
                    </td>
                    <td className="mono">{fmtScore(h.composite_score)}</td>
                    <td className="mono">{fmtScore(h.ensemble_top3)}</td>
                    <td className="mono">{fmtScore(h.ensemble_top5)}</td>
                    <td className="mono">{fmtScore(h.fp_strength)}</td>
                    <td className="mono">{fmtScore(h.ensemble_fp_mean)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}

      {tab === "exacta" && <ExoticSection data={scenarios.exacta} />}
      {tab === "trifecta" && <ExoticSection data={scenarios.trifecta} />}
      {tab === "superfecta" && <ExoticSection data={scenarios.superfecta} />}

      {tab === "definitions" && <DefinitionsTab />}

      {tab === "models" && (
        <section className="card">
          <h2>Source models ({combined.meta?.length ?? 0})</h2>
          <div className="table-wrap">
            <table className="data dense">
              <thead>
                <tr>
                  <th>Target</th>
                  <th>Model</th>
                  <th>ID</th>
                </tr>
              </thead>
              <tbody>
                {(combined.meta ?? []).map((m) => (
                  <tr key={m.column_name}>
                    <td>
                      <span className={`tag tag-${m.target.replace("target_", "")}`}>
                        {m.target}
                      </span>
                    </td>
                    <td className="break">{m.model_label}</td>
                    <td className="mono muted">{m.model_id}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}
    </div>
  );
}

function ExoticSection({ data }) {
  if (!data?.tickets?.length) {
    return (
      <section className="card">
        <p className="muted">No scenario data.</p>
      </section>
    );
  }
  const cols = data.bet_type === "exacta" ? ["first", "second"] : data.bet_type === "trifecta" ? ["first", "second", "third"] : ["first", "second", "third", "fourth"];
  return (
    <section className="card">
      <h2 style={{ textTransform: "capitalize" }}>{data.bet_type}</h2>
      <p className="muted">
        Preset: <code className="mono">{data.preset}</code> · Top{" "}
        <strong>{data.top_n}</strong> horses considered · Showing{" "}
        <strong>{data.ticket_count}</strong> tickets · Cost per ticket: $
        {Number(data.cost_per_ticket).toFixed(2)} · Total{" "}
        <strong>${data.total_cost?.toFixed?.(2) ?? data.total_cost}</strong>
      </p>
      <p className="fine-print">{data.tickets[0]?.note}</p>
      <div className="table-wrap">
        <table className="data dense">
          <thead>
            <tr>
              {cols.map((c) => (
                <th key={c}>{c}</th>
              ))}
              <th>Naive P</th>
            </tr>
          </thead>
          <tbody>
            {data.tickets.map((t, i) => (
              <tr key={i}>
                {cols.map((c) => (
                  <td key={c}>
                    <HorseLink name={t[c]} />
                  </td>
                ))}
                <td className="mono">{pct(t.naive_probability)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
