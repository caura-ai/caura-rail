import assert from "node:assert/strict";
import { MemoryScope, Rail, RestMemoryStore } from "@caura/rail";

const store = new RestMemoryStore({ baseUrl: process.argv[2], apiKey: "contract-key" });
const scope = new MemoryScope({
  agentId: "typescript-agent", fleetId: "support", visibility: "scope_team",
});
const rail = new Rail({ store, scope });
const turn = await rail.turn("Remember: TypeScript learned the renewal date.", (_, ctx) => {
  assert.equal(ctx.degraded, false);
  assert.ok(ctx.facts.some(f => f.content === "Python learned the deployment region."));
  assert.equal(ctx.keystones.length, 2);
  return "Recorded";
});
assert.equal(turn.writes[0].status, "written");
