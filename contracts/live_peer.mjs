import assert from "node:assert/strict";
import { MemoryScope, Rail, RestMemoryStore } from "@caura/rail";

const [marker, agentId, fleetId] = process.argv.slice(2);
const runId = marker.split(" ").at(-1);
const store = RestMemoryStore.fromEnv(process.env);
const scope = new MemoryScope({ agentId, fleetId, visibility: "scope_team" });
const rail = new Rail({ store, scope });
const turn = await rail.turn(`Remember: TypeScript live check ${runId} recorded.`, (_, ctx) => {
  assert.equal(ctx.degraded, false, ctx.errors.join("; "));
  assert.ok(ctx.facts.some(f => f.content.includes(marker)), "TypeScript could not recall Python's fact");
  assert.ok(ctx.keystones.some(r => r.title === `Rule high ${runId}`), "TypeScript missed the rule");
  return "Recorded";
});
assert.equal(turn.degraded, false, turn.errors.join("; "));
assert.equal(turn.writes[0]?.status, "written");
assert.equal((await store.write(`TypeScript live check ${runId} recorded.`, scope)).status, "deduplicated");
console.log("TypeScript peer verified against", process.env.CAURA_URL);
