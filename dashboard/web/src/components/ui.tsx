// Project-owned primitives inspired by composable component systems. No third-party component source is vendored.
import {
  useEffect,
  useId,
  useRef,
  type CSSProperties,
  type ReactNode,
} from "react";

const paths = {
  layers: "M3 7l9-5 9 5-9 5-9-5zm0 5l9 5 9-5M3 17l9 5 9-5",
  grid: "M3 3h7v7H3zM14 3h7v7h-7zM3 14h7v7H3zM14 14h7v7h-7z",
  list: "M9 5h12M9 12h12M9 19h12M3 5h1M3 12h1M3 19h1",
  plus: "M12 5v14M5 12h14",
  search: "M21 21l-5-5M18 10a8 8 0 11-16 0 8 8 0 0116 0z",
  arrow: "M4 12h16M14 6l6 6-6 6",
  chevron: "M9 5l7 7-7 7",
  close: "M6 6l12 12M6 18L18 6",
  menu: "M4 6h16M4 12h16M4 18h16",
  panel: "M3 3h18v18H3zM9 3v18",
  folder: "M3 7V4h6l2 3h10v13H3V7z",
  image: "M3 3h18v18H3zM3 17l6-6 4 4 3-3 5 5M16 7h.01",
  upload: "M12 16V3M7 8l5-5 5 5M3 15v6h18v-6",
  link: "M10 13a5 5 0 007 0l3-3a5 5 0 00-7-7l-2 2M14 11a5 5 0 00-7 0l-3 3a5 5 0 007 7l2-2",
  copy: "M8 8h13v13H8zM16 8V3H3v13h5",
  check: "M5 12l4 4L19 6",
  sparkles:
    "M12 3l2.5 6.5L21 12l-6.5 2.5L12 21l-2.5-6.5L3 12l6.5-2.5L12 3zM20 2v4M18 4h4",
  settings:
    "M12 8a4 4 0 100 8 4 4 0 000-8zM12 2v3M12 19v3M2 12h3M19 12h3M5 5l2 2M17 17l2 2M5 19l2-2M17 7l2-2",
  results: "M3 3h18v18H3zM3 8h18M8 8v13M12 12h5M12 16h5",
  sun: "M12 8a4 4 0 100 8 4 4 0 000-8zM12 1v3M12 20v3M1 12h3M20 12h3M4 4l2 2M18 18l2 2M4 20l2-2M18 6l2-2",
  moon: "M21 13A9 9 0 1111 3a7 7 0 0010 10z",
  shield: "M12 2l9 4v6c0 5-9 10-9 10S3 17 3 12V6l9-4zM8 12l3 3 5-6",
  clock: "M12 3a9 9 0 100 18 9 9 0 000-18zM12 7v5l3 2",
  filter: "M4 5h16M7 12h10M10 19h4",
  download: "M12 3v13M7 11l5 5 5-5M3 17v4h18v-4",
  book: "M3 3h7l2 2 2-2h7v17h-7l-2 2-2-2H3V3zM12 5v17",
} as const;
export type IconName = keyof typeof paths;
export function Icon({
  name,
  size = 18,
  className = "",
}: {
  name: IconName;
  size?: number;
  className?: string;
}) {
  return (
    <svg
      className={`icon ${className}`}
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.6"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <path d={paths[name]} />
    </svg>
  );
}

export function PageHeader({
  eyebrow,
  title,
  description,
  actions,
}: {
  eyebrow: string;
  title: ReactNode;
  description?: ReactNode;
  actions?: ReactNode;
}) {
  return (
    <div className="page-head">
      <div>
        <span className="label eyebrow">{eyebrow}</span>
        <h1>{title}</h1>
        {description && <p className="lede">{description}</p>}
      </div>
      {actions && <div className="row page-actions">{actions}</div>}
    </div>
  );
}

export function EmptyState({
  icon = "layers",
  title,
  children,
  actions,
}: {
  icon?: IconName;
  title: string;
  children: ReactNode;
  actions?: ReactNode;
}) {
  return (
    <section className="empty">
      <div className="empty-icon">
        <Icon name={icon} size={28} />
      </div>
      <h2>{title}</h2>
      <div className="empty-copy">{children}</div>
      {actions && <div className="row">{actions}</div>}
    </section>
  );
}

export function SkeletonCards() {
  return (
    <div className="cards" aria-busy="true" aria-label="Loading templates">
      {[0, 1, 2, 3].map((i) => (
        <div key={i} className="tcard skeleton-card" aria-hidden="true">
          <div className="skeleton skeleton-art" />
          <div className="tcard-body">
            <div className="skeleton skeleton-line" />
            <div className="skeleton skeleton-line short" />
          </div>
        </div>
      ))}
    </div>
  );
}

// Native modal semantics provide inert background, Escape handling and focus restoration.
export function Dialog({
  open,
  onClose,
  title,
  children,
  className = "",
  id,
}: {
  open: boolean;
  onClose: () => void;
  title: string;
  children: ReactNode;
  className?: string;
  id?: string;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  const titleId = useId();
  const close = useRef(onClose);
  close.current = onClose;
  useEffect(() => {
    const d = ref.current;
    if (!d) return;
    if (open && !d.open) d.showModal();
    if (!open && d.open) d.close();
    return () => {
      if (d.open) d.close();
    };
  }, [open]);
  return (
    <dialog
      ref={ref}
      id={id}
      className={`ui-dialog ${className}`}
      aria-labelledby={titleId}
      tabIndex={-1}
      onClose={() => close.current()}
      onKeyDown={(e) => {
        if (e.key !== "Tab") return;
        const nodes = Array.from(
          e.currentTarget.querySelectorAll<HTMLElement>(
            "a[href],button:not([disabled]),input:not([disabled]):not([type=hidden]),textarea:not([disabled]),select:not([disabled]),[tabindex]:not([tabindex='-1'])",
          ),
        ).filter(
          (el) =>
            el.getClientRects().length &&
            getComputedStyle(el).visibility !== "hidden",
        );
        const first = nodes[0],
          last = nodes[nodes.length - 1];
        if (!first) {
          e.preventDefault();
          e.currentTarget.focus();
          return;
        }
        const active = document.activeElement;
        if (
          !nodes.includes(active as HTMLElement) ||
          (e.shiftKey && active === first) ||
          (!e.shiftKey && active === last)
        ) {
          e.preventDefault();
          (e.shiftKey ? last : first).focus();
        }
      }}
      onClick={(e) => {
        if (e.target === e.currentTarget) {
          const r = e.currentTarget.getBoundingClientRect();
          if (
            e.clientX < r.left ||
            e.clientX > r.right ||
            e.clientY < r.top ||
            e.clientY > r.bottom
          )
            close.current();
        }
      }}
    >
      <div className="dialog-head">
        <h2 id={titleId}>{title}</h2>
        <button
          className="btn ghost icon-btn"
          aria-label={`Close ${title}`}
          onClick={onClose}
        >
          <Icon name="close" />
        </button>
      </div>
      {open && children}
    </dialog>
  );
}

export function Spotlight({
  children,
  className = "",
  style,
}: {
  children: ReactNode;
  className?: string;
  style?: CSSProperties;
}) {
  return (
    <div
      className={`spotlight ${className}`}
      style={style}
      onPointerMove={(e) => {
        if (
          e.pointerType !== "mouse" ||
          window.matchMedia("(prefers-reduced-motion: reduce)").matches
        )
          return;
        const r = e.currentTarget.getBoundingClientRect();
        e.currentTarget.style.setProperty(
          "--spot-x",
          `${e.clientX - r.left}px`,
        );
        e.currentTarget.style.setProperty("--spot-y", `${e.clientY - r.top}px`);
      }}
    >
      {children}
    </div>
  );
}
