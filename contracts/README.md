# Client contract tests

caura.json contains synthetic request/response examples shared by both packages.
They exercise the Caura REST contract: SearchRequest uses caller_agent_id and
fleet_ids; KeystoneDoc stores rule fields inside data; duplicate errors expose
error.code=DUPLICATE_MEMORY and structured error.details.

The schema references are the Caura server's SearchRequest, KeystoneDoc,
KeystonesEnvelope, and duplicate_memory definitions in
[caura-ai/caura](https://github.com/caura-ai/caura).

Python tests and Node tests consume the same fixture. smoke.py starts an ephemeral
loopback HTTP server, writes through Python, recalls and writes through TypeScript,
then recalls the TypeScript fact through Python. The fixture checks request
field shapes and responses. It does not implement production authentication,
authorization, semantic retrieval, or persistent storage.

From the repository root after installing both packages:

    python contracts/smoke.py

Real backend compatibility must also be checked using the live examples against
the managed service and a chosen OSS release. The fixture is intentionally named
a contract test to distinguish its coverage from those live checks.
