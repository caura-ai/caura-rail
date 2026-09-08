export type Visibility = "scope_agent" | "scope_team" | "scope_org";

export interface ScopeOptions {
  agentId: string;
  tenantId?: string;
  fleetId?: string;
  visibility?: Visibility;
}

export class MemoryScope {
  readonly agentId: string;
  readonly tenantId?: string;
  readonly fleetId?: string;
  readonly visibility: Visibility;

  constructor(options: ScopeOptions) {
    for (const value of [options.agentId, options.tenantId, options.fleetId]) {
      if (value !== undefined && (typeof value !== "string" || !value.trim())) {
        throw new TypeError("Scope identifiers must be nonempty strings");
      }
    }
    if (typeof options.agentId !== "string") throw new TypeError("agentId is required");
    this.agentId = options.agentId;
    this.tenantId = options.tenantId;
    this.fleetId = options.fleetId;
    this.visibility = options.visibility ?? "scope_agent";
    if (!["scope_agent", "scope_team", "scope_org"].includes(this.visibility)) {
      throw new TypeError("Invalid visibility");
    }
    if (this.visibility === "scope_team" && !this.fleetId) {
      throw new TypeError("TEAM visibility requires fleetId");
    }
    Object.freeze(this);
  }

  forAgent(agentId: string): MemoryScope {
    return new MemoryScope({ ...this, agentId });
  }
}

export interface Fact { id: string; content: string; agentId?: string }
export interface KeystoneRule { docId: string; title: string; content: string; weight: number }
export interface WriteResult {
  status: "written" | "deduplicated" | "deferred" | "rejected" | "dropped";
  id?: string;
  error?: string;
}

export class RecallContext {
  facts: Fact[] = [];
  keystones: KeystoneRule[] = [];
  errors: string[] = [];

  get degraded(): boolean { return this.errors.length > 0; }
  get text(): string {
    const sections: string[] = [];
    if (this.keystones.length) {
      sections.push("### GOVERNANCE RULES\n" +
        this.keystones.map(r => "- " + r.title + ": " + r.content).join("\n"));
    }
    if (this.facts.length) {
      sections.push("### RECALLED MEMORY\n" + this.facts.map(f => "- " + f.content).join("\n"));
    }
    return sections.join("\n\n");
  }
}

export class StoreError extends Error {
  constructor(
    message: string,
    readonly status?: number,
    readonly retryable = false,
  ) {
    super(message);
    this.name = "StoreError";
  }
}

export interface MemoryStore {
  recall(query: string, scope: MemoryScope, topK?: number): Promise<Fact[]>;
  keystones(scope: MemoryScope): Promise<KeystoneRule[]>;
  write(fact: string, scope: MemoryScope): Promise<WriteResult>;
}
