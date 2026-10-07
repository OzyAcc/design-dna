// A page's server writes, sent one after another. Each write starts only when the previous one has been answered, so an
// older, slower response can never overwrite a newer value. Typing is debounced per field (schedule); an explicit
// choice for the same field (run) replaces a pending edit. flush() sends everything pending and resolves only when the
// server has acknowledged all of it; it rejects while any write is still failing, so nothing is generated from content
// the server never received.
import { errText } from "./lib";

export type Ack = (ok: boolean) => void;
type Write = () => Promise<unknown>;

export class WriteQueue {
  private timers = new Map<string, { id: number; fn: Write; ack?: Ack }>();
  private gen = new Map<string, number>();
  private failed = new Map<string, { gen: number; fn: Write; ack?: Ack; message: string }>();
  private tail: Promise<unknown> = Promise.resolve();
  private active = 0;
  private listeners = new Set<() => void>();

  constructor(private onError?: (key: string, e: unknown) => void) {}

  /** Writes not yet acknowledged: debounced, queued or in flight. */
  get busy(): boolean { return this.active > 0 || this.timers.size > 0; }
  get failures(): string[] { return [...this.failed.values()].map((f) => f.message); }

  subscribe(fn: () => void): () => void { this.listeners.add(fn); return () => { this.listeners.delete(fn); }; }
  private notify() { this.listeners.forEach((fn) => fn()); }

  /** Debounced write for one field: a newer call for the same key replaces it. */
  schedule(key: string, fn: Write, delay: number, ack?: Ack): void {
    this.drop(key);
    const id = window.setTimeout(() => { this.timers.delete(key); void this.run(key, fn, ack); }, delay);
    this.timers.set(key, { id, fn, ack });
    this.notify();
  }

  /** Send now (after the writes already queued). Replaces a pending debounced write for the same key. */
  run<T>(key: string, fn: () => Promise<T>, ack?: Ack, opts: { read?: boolean } = {}): Promise<T | undefined> {
    this.drop(key);
    const g = (this.gen.get(key) || 0) + 1;
    this.gen.set(key, g);
    this.active++;
    this.notify();
    const p = this.tail.then(async () => {
      try {
        const r = await fn();
        if ((this.failed.get(key)?.gen ?? 0) <= g) this.failed.delete(key);
        ack?.(true);
        return r;
      } catch (e) {
        if (!opts.read && (this.gen.get(key) || 0) === g) this.failed.set(key, { gen: g, fn, ack, message: errText(e) });
        ack?.(false);
        this.onError?.(key, e);
        return undefined;
      } finally {
        this.active--;
        this.notify();
      }
    });
    this.tail = p;
    return p;
  }

  /** Send a pending debounced write for this key now (e.g. when its editor goes away). */
  fire(key: string): void {
    const t = this.timers.get(key);
    if (t) { this.drop(key); void this.run(key, t.fn, t.ack); }
  }

  fireAll(): void { [...this.timers.keys()].forEach((k) => this.fire(k)); }

  /** Everything the user did, acknowledged by the server; rejects if a write still fails after one more attempt. */
  async flush(): Promise<void> {
    this.fireAll();
    for (const [key, f] of [...this.failed]) {
      if ((this.gen.get(key) || 0) === f.gen) void this.run(key, f.fn, f.ack); // retry only if nothing newer replaced it
    }
    while (this.active > 0 || this.timers.size > 0) {
      this.fireAll();
      await this.tail;
    }
    if (this.failed.size) throw new Error(this.failures.join("; "));
  }

  private drop(key: string) {
    const t = this.timers.get(key);
    if (t) { clearTimeout(t.id); this.timers.delete(key); this.notify(); }
  }
}
