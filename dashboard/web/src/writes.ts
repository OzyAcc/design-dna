// A page's server writes, sent one after another. Each write starts only when the previous one has been answered, so an
// older, slower response can never overwrite a newer value. Typing is debounced per field (schedule); an explicit
// choice for the same field (run) replaces a pending edit. flush() sends everything pending and resolves only when the
// server has acknowledged all of it; it rejects while any write is still failing, so nothing is generated from content
// the server never received.
//
// Only a write whose value is still on screen is sent again automatically (typed copy, text fields): it is kept after a
// failure and retried by flush(). A write marked `once` (a choice the screen shows as not applied after a failure, or an
// action such as adding a variant) is reported and never replayed unseen; neither is a write that throws NotReplayable.
// Writes to the same server field share a key, so the newest one wins.
import { errText } from "./lib";

export type Ack = (ok: boolean) => void;
type Write = () => Promise<unknown>;
export type WriteOpts = { read?: boolean; once?: boolean };

/** Thrown by a write whose failure must not be retried later (e.g. the batch changed elsewhere and was reloaded). */
export class NotReplayable extends Error {}

export class WriteQueue {
  private timers = new Map<string, { id: number; fn: Write; ack?: Ack }>();
  private gen = new Map<string, number>();
  private replayGen = new Map<string, number>();
  private failed = new Map<string, { gen: number; fn: Write; ack?: Ack; message: string }>();
  private tail: Promise<unknown> = Promise.resolve();
  private active = 0;
  private listeners = new Set<() => void>();

  constructor(private onError?: (key: string, e: unknown, opts: WriteOpts) => void) {}

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
  run<T>(key: string, fn: () => Promise<T>, ack?: Ack, opts: WriteOpts = {}): Promise<T | undefined> {
    this.drop(key);
    const g = (this.gen.get(key) || 0) + 1;
    this.gen.set(key, g);
    if (!opts.read && !opts.once) this.replayGen.set(key, g);
    this.active++;
    this.notify();
    const p = this.tail.then(async () => {
      try {
        const r = await fn();
        if ((this.failed.get(key)?.gen ?? 0) <= g) this.failed.delete(key); // the server now has this or a newer value
        ack?.(true);
        return r;
      } catch (e) {
        const replay = !opts.read && !opts.once && !(e instanceof NotReplayable) && this.replayGen.get(key) === g;
        if (replay) this.failed.set(key, { gen: g, fn, ack, message: errText(e) });
        else if (e instanceof NotReplayable && (this.failed.get(key)?.gen ?? g) < g) this.failed.delete(key); // refused as stale: redo it
        ack?.(false);
        this.onError?.(key, e, replay ? opts : { ...opts, once: true });
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

  /** The user abandoned what this field was saving (e.g. chose an AI draft instead): never send it again. */
  forget(key: string): void {
    this.drop(key);
    if (this.failed.delete(key)) this.notify();
  }

  /** Everything the user did, acknowledged by the server; rejects if a write still fails after one more attempt. */
  async flush(): Promise<void> {
    await this.idle(); // what was typed or queued goes first: a newer write clears an older failure of its field
    for (const [key, f] of [...this.failed]) void this.run(key, f.fn, f.ack); // each is the latest value of its field
    await this.idle();
    if (this.failed.size) throw new Error(this.failures.join("; "));
  }

  private async idle() {
    while (this.active > 0 || this.timers.size > 0) {
      this.fireAll();
      await this.tail;
    }
  }

  private drop(key: string) {
    const t = this.timers.get(key);
    if (t) { clearTimeout(t.id); this.timers.delete(key); this.notify(); }
  }
}
