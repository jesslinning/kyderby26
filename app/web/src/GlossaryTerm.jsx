import {
  useEffect,
  useId,
  useLayoutEffect,
  useRef,
  useState,
} from "react";
import { createPortal } from "react-dom";

const MQ_MOBILE = "(max-width: 639px)";

function InfoIcon() {
  return (
    <svg
      className="glossary-term__icon"
      viewBox="0 0 24 24"
      aria-hidden
      focusable="false"
    >
      <path
        fill="currentColor"
        d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm1 15h-2v-6h2v6zm0-8h-2V7h2v2z"
      />
    </svg>
  );
}

/**
 * Tap/click the info icon for a definition sheet (mobile) or anchored panel (desktop).
 * Hover alone is not required—better for touch devices.
 *
 * `variant="icon-only"` hides the visible label (children remain for screen readers).
 */
export function GlossaryTerm({
  children,
  summary,
  defId,
  onNavigate,
  name,
  variant,
}) {
  const [open, setOpen] = useState(false);
  const [anchoredPos, setAnchoredPos] = useState(null);
  const rootRef = useRef(null);
  const anchorRef = useRef(null);
  const panelRef = useRef(null);
  const panelId = useId();
  const titleId = `${panelId}-title`;
  const label = name ?? (typeof children === "string" ? children : "Term");

  const handleJump = (e) => {
    e.preventDefault();
    e.stopPropagation();
    onNavigate(defId);
    setOpen(false);
  };

  useLayoutEffect(() => {
    if (!open) {
      setAnchoredPos(null);
      return;
    }
    const mq = window.matchMedia(MQ_MOBILE);
    const place = () => {
      if (mq.matches) {
        setAnchoredPos(null);
        return;
      }
      const el = anchorRef.current;
      if (!el) return;
      const r = el.getBoundingClientRect();
      const width = Math.min(300, window.innerWidth - 24);
      let left = r.left + r.width / 2 - width / 2;
      left = Math.max(12, Math.min(left, window.innerWidth - width - 12));
      setAnchoredPos({
        top: r.bottom + 8,
        left,
        width,
      });
    };
    place();
    mq.addEventListener("change", place);
    window.addEventListener("resize", place);
    return () => {
      mq.removeEventListener("change", place);
      window.removeEventListener("resize", place);
    };
  }, [open]);

  useEffect(() => {
    if (!open) return;

    const onKey = (e) => {
      if (e.key === "Escape") setOpen(false);
    };

    const onPointer = (e) => {
      const t = e.target;
      if (rootRef.current?.contains(t)) return;
      if (panelRef.current?.contains(t)) return;
      setOpen(false);
    };

    let prevOverflow = "";
    if (window.matchMedia(MQ_MOBILE).matches) {
      prevOverflow = document.body.style.overflow;
      document.body.style.overflow = "hidden";
    }

    document.addEventListener("keydown", onKey);
    document.addEventListener("mousedown", onPointer);
    document.addEventListener("touchstart", onPointer, { passive: true });

    return () => {
      document.removeEventListener("keydown", onKey);
      document.removeEventListener("mousedown", onPointer);
      document.removeEventListener("touchstart", onPointer);
      document.body.style.overflow = prevOverflow;
    };
  }, [open]);

  const panel =
    open &&
    typeof document !== "undefined" &&
    createPortal(
      <>
        <div
          className="glossary-term__backdrop"
          aria-hidden
          onClick={() => setOpen(false)}
        />
        <div
          ref={panelRef}
          id={panelId}
          role="dialog"
          aria-modal="true"
          aria-labelledby={titleId}
          className={`glossary-term__panel ${anchoredPos ? "glossary-term__panel--anchored" : "glossary-term__panel--sheet"}`}
          style={
            anchoredPos
              ? {
                  position: "fixed",
                  top: anchoredPos.top,
                  left: anchoredPos.left,
                  width: anchoredPos.width,
                  maxHeight: "min(320px, calc(100vh - 24px))",
                }
              : undefined
          }
        >
          <p id={titleId} className="glossary-term__panel-title">
            {label}
          </p>
          <p className="glossary-term__summary">{summary}</p>
          <div className="glossary-term__actions">
            <button type="button" className="glossary-term__primary" onClick={handleJump}>
              Open in Definitions
            </button>
            <button
              type="button"
              className="glossary-term__ghost"
              onClick={() => setOpen(false)}
            >
              Close
            </button>
          </div>
        </div>
      </>,
      document.body
    );

  return (
    <>
      <span
        className={
          variant === "icon-only" ? "glossary-term glossary-term--icon-only" : "glossary-term"
        }
        ref={rootRef}
      >
        <span className="glossary-term__row">
          <span
            className={
              variant === "icon-only"
                ? "glossary-term__text glossary-term__text--sr-only"
                : "glossary-term__text"
            }
          >
            {children}
          </span>
          <button
            ref={anchorRef}
            type="button"
            className="glossary-term__info"
            aria-expanded={open}
            aria-controls={panelId}
            aria-haspopup="dialog"
            aria-label={`${label}: open short definition`}
            onClick={() => setOpen((v) => !v)}
          >
            <InfoIcon />
          </button>
        </span>
      </span>
      {panel}
    </>
  );
}
