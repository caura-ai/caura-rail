import { randomUUID } from "node:crypto";
import { MemoryScope, Rail, RestMemoryStore } from "@caura/rail";

const marker = "Rail example " + randomUUID();
const store = RestMemoryStore.fromEnv(process.env);
const scope = new MemoryScope({
  agentId: "rail-example-writer", fleetId: "rail-examples", visibility: "scope_team",
});
const writer = new Rail({ store, scope });
const turn = await writer.turn("Remember: " + marker, () => "Noted");
if (turn.degraded || turn.writes[0]?.status !== "written") {
  throw new Error("Write did not complete; inspect the turn errors and backend configuration");
}
const reader = new Rail({ store, scope: scope.forAgent("rail-example-reader") });
const ctx = await reader.recall(marker);
if (ctx.degraded || !ctx.facts.some(f => f.content.includes(marker))) {
  throw new Error("Second agent could not recall the fact; check fleet permissions");
}
console.log("Second agent recalled the saved fact:", marker);
