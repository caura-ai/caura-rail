# Caura Rail for TypeScript and JavaScript

[![npm](https://img.shields.io/npm/v/%40caura%2Frail?label=npm&color=0E6B5A)](https://www.npmjs.com/package/@caura/rail) [![Node.js](https://img.shields.io/node/v/%40caura%2Frail?label=Node.js)](https://www.npmjs.com/package/@caura/rail) [![CI](https://img.shields.io/github/actions/workflow/status/caura-ai/caura-rail/ci.yml?label=CI)](https://github.com/caura-ai/caura-rail/actions/workflows/ci.yml) [![License](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](https://github.com/caura-ai/caura-rail/blob/main/LICENSE)

Memory operations around agent turns: fetch governance rules and relevant facts
from [Caura](https://caura.ai) before your agent runs, then extract and store
facts from the completed turn. ES modules for Node.js 22+, no runtime
dependencies, type declarations included.

```bash
npm install @caura/rail
```

```ts
import { MemoryScope, Rail, RestMemoryStore } from "@caura/rail";

const rail = new Rail({
  store: RestMemoryStore.fromEnv(process.env), // CAURA_URL, CAURA_API_KEY
  scope: new MemoryScope({ agentId: "support-1" }),
});
const turn = await rail.turn("Remember: We deploy in eu-west-1.", async (message, context) => {
  return "Noted. " + context.text; // pass context to your model
});
console.log(turn.reply, turn.writes.map(w => w.status));
```

Full documentation, including the guide, API reference, and reliability
semantics, lives in the
[repository](https://github.com/caura-ai/caura-rail#readme).
A Python package with the same semantics is published as `caura-rail`.

Licensed under Apache-2.0.
