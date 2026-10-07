import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api, type Template } from "../api";
import { Dialog, Icon, type IconName } from "./ui";

const destinations: {
  name: string;
  to: string;
  icon: IconName;
  hint: string;
}[] = [
  {
    name: "Template library",
    to: "/templates",
    icon: "layers",
    hint: "Browse your designs",
  },
  {
    name: "New template",
    to: "/templates/new",
    icon: "plus",
    hint: "Upload, paste or add a link",
  },
  {
    name: "Generate",
    to: "/generate",
    icon: "sparkles",
    hint: "Review products and copy",
  },
  { name: "Results", to: "/runs", icon: "results", hint: "Review and export" },
  {
    name: "Settings",
    to: "/settings",
    icon: "settings",
    hint: "Providers, fonts and renderer",
  },
];

export default function CommandMenu({
  open,
  onClose,
}: {
  open: boolean;
  onClose: () => void;
}) {
  const [q, setQ] = useState("");
  const [templates, setTemplates] = useState<Template[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(false);
  const [index, setIndex] = useState(0);
  const nav = useNavigate();
  const list = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    let alive = true;
    setQ("");
    setIndex(0);
    setLoading(true);
    setError(false);
    api
      .get<{ templates: Template[] }>("/api/templates?sort=recent")
      .then((r) => {
        if (alive) setTemplates(r.templates);
      })
      .catch(() => {
        if (alive) setError(true);
      })
      .finally(() => {
        if (alive) setLoading(false);
      });
    return () => {
      alive = false;
    };
  }, [open]);
  const query = q.toLocaleLowerCase().trim();
  const actions = destinations.filter((d) =>
    d.name.toLowerCase().includes(query),
  );
  const matches = templates
    .filter((t) => t.name.toLocaleLowerCase().includes(query))
    .slice(0, 8);
  const items = [
    ...actions,
    ...matches.map((t) => ({
      name: t.name,
      to: `/templates/${t.id}`,
      icon: "image" as const,
      hint: t.status === "draft" ? "Template draft" : "Open template",
    })),
  ];
  const choose = (to: string) => {
    onClose();
    nav(to);
  };
  return (
    <Dialog
      open={open}
      onClose={onClose}
      title="Find your next step"
      className="command-dialog"
    >
      <div className="search-field command-search">
        <Icon name="search" />
        <input
          autoFocus
          type="search"
          aria-label="Search pages and templates"
          placeholder="Search templates or jump to a page…"
          value={q}
          onChange={(e) => {
            setQ(e.target.value);
            setIndex(0);
          }}
          onKeyDown={(e) => {
            if (e.key === "ArrowDown" || e.key === "ArrowUp") {
              e.preventDefault();
              const next =
                (index +
                  (e.key === "ArrowDown" ? 1 : -1) +
                  Math.max(1, items.length)) %
                Math.max(1, items.length);
              setIndex(next);
              list.current
                ?.querySelectorAll("button")
                [next]?.scrollIntoView({ block: "nearest" });
            }
            if (e.key === "Enter" && items[index]) {
              e.preventDefault();
              choose(items[index].to);
            }
          }}
        />
      </div>
      <div className="command-list" ref={list}>
        {items.map((item, i) => (
          <button
            key={item.to}
            className={`command-item ${i === index ? "highlighted" : ""}`}
            onFocus={() => setIndex(i)}
            onClick={() => choose(item.to)}
          >
            <Icon name={item.icon} />
            <span>
              <strong>{item.name}</strong>
              <small>{item.hint}</small>
            </span>
            <Icon name="chevron" size={14} />
          </button>
        ))}
      </div>
      {loading && (
        <p className="small muted command-note" role="status">
          Loading templates…
        </p>
      )}
      {error && (
        <p className="small muted command-note" role="status">
          Template search is unavailable. You can still navigate to a page.
        </p>
      )}
      {!loading && !items.length && (
        <p className="small muted command-note">
          No matches. Try a different name.
        </p>
      )}
      <div className="command-foot">
        <span>
          <kbd>↑</kbd> <kbd>↓</kbd> navigate <kbd>↵</kbd> open
        </span>
        <span>
          <kbd>esc</kbd> close
        </span>
      </div>
    </Dialog>
  );
}
