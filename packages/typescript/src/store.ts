import {
  type Fact, type KeystoneRule, type MemoryStore, MemoryScope, StoreError, type WriteResult,
} from "./models.js";
import { VERSION } from "./version.js";

export { VERSION };

function object(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new StoreError("Invalid backend response: expected an object");
  }
  return value as Record<string, unknown>;
}

function string(value: unknown): string {
  if (typeof value !== "string" || !value.trim()) {
    throw new StoreError("Invalid backend response: expected a nonempty string");
  }
  return value;
}

/** Largest topK the Caura search endpoint accepts. */
export const MAX_TOP_K = 20;
/** Longest query the Caura search endpoint accepts; longer queries are truncated. */
export const MAX_QUERY_CHARS = 5000;

function runtimeTag(): string {
  const node = (globalThis as { process?: { versions?: { node?: string } } }).process?.versions?.node;
  return node ? ` (node/${node.split(".")[0]})` : "";
}

/**
 * Sent on every request so a server can tell SDK families apart. Names the
 * package, its version and, under Node, the Node major; nothing else. Browsers
 * drop a caller-supplied User-Agent, which is fine.
 */
export const USER_AGENT = `caura-rail-node/${VERSION}${runtimeTag()}`;

export interface StoreOptions {
  baseUrl?: string;
  apiKey?: string;
  tenantId?: string;
  timeoutMs?: number;
  fetch?: typeof globalThis.fetch;
}

export class RestMemoryStore implements MemoryStore {
  private readonly baseUrl: string;
  private readonly apiKey: string;
  private tenantId?: string;
  private readonly timeoutMs: number;
  private readonly fetchImpl: typeof globalThis.fetch;

  constructor(options: StoreOptions = {}) {
    const parsed = new URL(options.baseUrl ?? "http://localhost:8000");
    if (!["http:", "https:"].includes(parsed.protocol) ||
        parsed.username || parsed.password || parsed.search || parsed.hash) {
      throw new TypeError("baseUrl must be HTTP(S), without credentials, query, or fragment");
    }
    this.baseUrl = parsed.toString().replace(/\/$/, "");
    this.apiKey = options.apiKey ?? "standalone";
    this.tenantId = options.tenantId;
    this.timeoutMs = options.timeoutMs ?? 15000;
    if (!this.apiKey.trim()) throw new TypeError("apiKey must be nonempty");
    if (this.tenantId !== undefined && !this.tenantId.trim()) {
      throw new TypeError("tenantId must be nonempty");
    }
    if (!Number.isFinite(this.timeoutMs) || this.timeoutMs <= 0) {
      throw new TypeError("timeoutMs must be positive and finite");
    }
    this.fetchImpl = options.fetch ?? globalThis.fetch;
  }

  static fromEnv(env: Record<string, string | undefined>, overrides: StoreOptions = {}): RestMemoryStore {
    return new RestMemoryStore({
      baseUrl: env.CAURA_URL,
      apiKey: env.CAURA_API_KEY,
      tenantId: env.CAURA_TENANT || undefined,
      ...overrides,
    });
  }

  private async request(
    method: string, path: string, tenant?: string,
    body?: Record<string, unknown>, writing = false,
  ): Promise<unknown> {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), this.timeoutMs);
    try {
      const headers: Record<string, string> = { "X-API-Key": this.apiKey, "User-Agent": USER_AGENT };
      if (tenant) headers["X-Tenant-ID"] = tenant;
      if (body) headers["Content-Type"] = "application/json";
      const response = await this.fetchImpl(this.baseUrl + path, {
        method, headers, body: body ? JSON.stringify(body) : undefined,
        signal: controller.signal, redirect: "error",
      });
      if (!response.ok) {
        if (writing && response.status === 409) {
          let data: unknown;
          try { data = await response.json(); } catch { data = {}; }
          const raw = object(data);
          if (raw.error && typeof raw.error === "object") {
            const error = object(raw.error);
            if (error.code === "DUPLICATE_MEMORY") {
              const details = object(error.details);
              if (details.reason === "winner_no_longer_live") {
                throw new StoreError("Duplicate winner no longer live", 409, true);
              }
              if (["exact_content_hash", "semantic_similarity"].includes(String(details.reason))) {
                return { status: "deduplicated", id: string(details.existing_id) };
              }
            }
          }
        }
        const status = response.status;
        throw new StoreError("Caura request failed (HTTP " + status + ")", status,
          [408, 429].includes(status) || (status >= 500 && status < 600));
      }
      if (response.headers.get("X-Truncated")?.toLowerCase() === "true") {
        throw new StoreError("Backend returned truncated governance rules");
      }
      try { return await response.json(); }
      catch (error) {
        if (controller.signal.aborted) throw error;
        if (!(error instanceof SyntaxError)) throw error;
        throw new StoreError("Invalid backend response: expected JSON");
      }
    } catch (error) {
      if (error instanceof StoreError) throw error;
      throw new StoreError("Caura transport failure", undefined, true);
    } finally {
      clearTimeout(timer);
    }
  }

  private async resolve(scope: MemoryScope): Promise<string> {
    if (scope.tenantId && this.tenantId && scope.tenantId !== this.tenantId) {
      throw new StoreError("Scope tenant does not match the store tenant");
    }
    if (scope.tenantId) return scope.tenantId;
    if (!this.tenantId) {
      this.tenantId = string(object(await this.request("GET", "/api/v1/whoami")).tenant_id);
    }
    return this.tenantId;
  }

  async recall(query: string, scope: MemoryScope, topK = 8): Promise<Fact[]> {
    if (typeof query !== "string" || !query.trim()) throw new TypeError("query must be nonempty");
    if (!Number.isInteger(topK) || topK < 1 || topK > MAX_TOP_K) {
      throw new TypeError("topK must be an integer from 1 to " + MAX_TOP_K);
    }
    const tenant = await this.resolve(scope);
    const body: Record<string, unknown> = {
      tenant_id: tenant, query: [...query].slice(0, MAX_QUERY_CHARS).join(""),
      caller_agent_id: scope.agentId, top_k: topK,
    };
    if (scope.fleetId) body.fleet_ids = [scope.fleetId];
    const data = object(await this.request("POST", "/api/v1/search", tenant, body));
    if (!Array.isArray(data.items)) throw new StoreError("Invalid search response: missing items array");
    return data.items.map(raw => {
      const item = object(raw);
      return {
        id: string(item.id), content: string(item.content),
        agentId: item.agent_id == null ? undefined : string(item.agent_id),
      };
    });
  }

  async keystones(scope: MemoryScope): Promise<KeystoneRule[]> {
    const tenant = await this.resolve(scope);
    const params = new URLSearchParams({ tenant_id: tenant, agent_id: scope.agentId });
    if (scope.fleetId) params.set("fleet_id", scope.fleetId);
    const data = await this.request("GET", "/api/v1/keystones?" + params, tenant);
    const items = Array.isArray(data) ? data : object(data).items;
    if (!Array.isArray(items)) throw new StoreError("Invalid keystone response: expected an array");
    return items.map(raw => {
      const row = object(raw), rule = object(row.data);
      if (typeof rule.weight !== "number" || !Number.isInteger(rule.weight)) {
        throw new StoreError("Invalid keystone response: weight must be an integer");
      }
      return {
        docId: string(row.doc_id), title: string(rule.title),
        content: string(rule.content), weight: rule.weight,
      };
    }).sort((a, b) => b.weight - a.weight);
  }

  async write(fact: string, scope: MemoryScope): Promise<WriteResult> {
    if (typeof fact !== "string" || !fact.trim()) throw new TypeError("fact must be nonempty");
    const tenant = await this.resolve(scope);
    const body: Record<string, unknown> = {
      tenant_id: tenant, agent_id: scope.agentId, content: fact,
      visibility: scope.visibility, write_mode: "strong",
    };
    if (scope.fleetId) body.fleet_id = scope.fleetId;
    const data = object(await this.request("POST", "/api/v1/memories", tenant, body, true));
    if (data.status === "deduplicated") return { status: "deduplicated", id: string(data.id) };
    return { status: "written", id: string(data.id) };
  }
}
