import {
  MemoryScope, type MemoryStore, RecallContext, StoreError, type WriteResult,
} from "./models.js";

export type Extractor = (message: string, reply: string) => string[] | Promise<string[]>;
export type Agent = (message: string, context: RecallContext) => string | Promise<string>;

export function ruleExtract(message: string, _reply: string): string[] {
  return [...new Set(message.split(/\r?\n/).map(line => line.trim())
    .filter(line => /^(remember:\s*|we (use|deploy)\b|our (plan|contract)\b)/i.test(line))
    .map(line => line.replace(/^remember:\s*/i, "")))];
}

interface Pending { fact: string; scope: MemoryScope; attempts: number }

export class Outbox {
  private queue: Pending[] = [];
  totalDropped = 0;
  constructor(readonly capacity = 1000) {
    if (!Number.isInteger(capacity) || capacity < 1) throw new TypeError("capacity must be positive");
  }
  get size(): number { return this.queue.length; }
  /** Used by Rail. Evictions, including replay collisions, are counted. */
  push(item: Pending): void {
    if (this.queue.length === this.capacity) { this.queue.shift(); this.totalDropped++; }
    this.queue.push(item);
  }
  take(): Pending[] {
    const batch = this.queue;
    this.queue = [];
    return batch;
  }
}

export interface RailOptions {
  store: MemoryStore;
  scope: MemoryScope;
  extractor?: Extractor;
  outbox?: Outbox;
  topK?: number;
  requireKeystones?: boolean;
  maxContextChars?: number;
  maxFacts?: number;
  maxFactChars?: number;
}

export class TurnResult {
  context = new RecallContext();
  reply = "";
  writes: WriteResult[] = [];
  errors: string[] = [];
  get degraded(): boolean { return this.context.degraded || this.errors.length > 0; }
}

export class Rail {
  readonly outbox: Outbox;
  readonly telemetry = {
    turnsTotal: 0, degradedTurns: 0, writesDeferred: 0, writesRejected: 0, extractionFailures: 0,
  };
  private readonly store: MemoryStore;
  private readonly scope: MemoryScope;
  private readonly extractor: Extractor;
  private readonly topK: number;
  private readonly requireKeystones: boolean;
  private readonly maxContextChars: number;
  private readonly maxFacts: number;
  private readonly maxFactChars: number;

  constructor(options: RailOptions) {
    this.store = options.store;
    this.scope = options.scope;
    if (!(this.scope instanceof MemoryScope)) throw new TypeError("scope must be a MemoryScope");
    this.extractor = options.extractor ?? ruleExtract;
    this.outbox = options.outbox ?? new Outbox();
    this.topK = options.topK ?? 8;
    this.requireKeystones = options.requireKeystones ?? false;
    this.maxContextChars = options.maxContextChars ?? 16000;
    this.maxFacts = options.maxFacts ?? 16;
    this.maxFactChars = options.maxFactChars ?? 4000;
    for (const value of [this.topK, this.maxContextChars, this.maxFacts, this.maxFactChars]) {
      if (!Number.isInteger(value) || value < 1) throw new TypeError("Limits must be positive integers");
    }
  }

  async recall(query: string): Promise<RecallContext> {
    if (typeof query !== "string" || !query.trim()) throw new TypeError("query must be nonempty");
    const ctx = new RecallContext();
    try { ctx.keystones = await this.store.keystones(this.scope); }
    catch (error) {
      if (!(error instanceof StoreError) || this.requireKeystones) throw error;
      ctx.errors.push("keystones: " + error.message);
    }
    try { ctx.facts = await this.store.recall(query, this.scope, this.topK); }
    catch (error) {
      if (!(error instanceof StoreError)) throw error;
      ctx.errors.push("recall: " + error.message);
    }
    const facts = ctx.facts;
    ctx.facts = [];
    if ([...ctx.text].length > this.maxContextChars) {
      if (this.requireKeystones) throw new StoreError("Governance rules exceed the context budget");
      ctx.keystones = [];
      ctx.errors.push("governance_context_overflow");
    }
    for (const fact of facts) {
      ctx.facts.push(fact);
      if ([...ctx.text].length > this.maxContextChars) {
        ctx.facts.pop();
        ctx.errors.push("facts_context_truncated");
        break;
      }
    }
    return ctx;
  }

  async turn(message: string, agent: Agent): Promise<TurnResult> {
    if (typeof message !== "string" || !message.trim()) throw new TypeError("message must be nonempty");
    this.telemetry.turnsTotal++;
    const turn = new TurnResult();
    try {
      try { turn.context = await this.recall(message); }
      catch (error) {
        if (error instanceof StoreError) turn.errors.push("governance_unavailable");
        throw error;
      }
      turn.reply = await agent(message, turn.context);
      if (typeof turn.reply !== "string") throw new TypeError("Agent reply must be a string");
      let facts: string[];
      try {
        const raw: unknown = await this.extractor(message, turn.reply);
        if (!Array.isArray(raw) || raw.length > this.maxFacts ||
            raw.some(f => typeof f !== "string" || [...f].length > this.maxFactChars)) {
          throw new TypeError("Extractor must return a bounded list of strings");
        }
        facts = [...new Set((raw as string[]).map(f => f.trim()).filter(Boolean))];
      } catch {
        this.telemetry.extractionFailures++;
        turn.errors.push("extraction_failed");
        return turn;
      }
      for (const fact of facts) {
        try { turn.writes.push(await this.store.write(fact, this.scope)); }
        catch (error) {
          if (!(error instanceof StoreError)) throw error;
          if (error.retryable) {
            this.outbox.push({ fact, scope: this.scope, attempts: 0 });
            this.telemetry.writesDeferred++;
            turn.writes.push({ status: "deferred", error: error.message });
          } else {
            this.telemetry.writesRejected++;
            turn.writes.push({ status: "rejected", error: error.message });
          }
          turn.errors.push(error.retryable ? "deferred" : "rejected");
        }
      }
      return turn;
    } finally {
      if (turn.degraded) this.telemetry.degradedTurns++;
    }
  }

  async run(message: string, agent: Agent): Promise<string> {
    return (await this.turn(message, agent)).reply;
  }

  async flushOutbox(maxAttempts = 3): Promise<WriteResult[]> {
    if (!Number.isInteger(maxAttempts) || maxAttempts < 1) {
      throw new TypeError("maxAttempts must be positive");
    }
    const batch = this.outbox.take(), results: WriteResult[] = [];
    for (const [index, item] of batch.entries()) {
      item.attempts++;
      try { results.push(await this.store.write(item.fact, item.scope)); }
      catch (error) {
        if (!(error instanceof StoreError)) {
          for (const pending of batch.slice(index)) this.outbox.push(pending);
          throw error;
        }
        if (error.retryable && item.attempts < maxAttempts) {
          this.outbox.push(item);
          results.push({ status: "deferred", error: error.message });
        } else {
          this.outbox.totalDropped++;
          results.push({ status: "dropped", error: error.message });
        }
      }
    }
    return results;
  }
}
