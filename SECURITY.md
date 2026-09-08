# Security

## Reporting a vulnerability

Email security@caura.ai with a description, affected versions, and reproduction
steps. Do not open a public issue for security reports. You will receive an
acknowledgement within three business days and a fix or mitigation plan after
triage. Coordinated disclosure is appreciated.

## What Rail does with data

- Rail sends user messages as search queries and extracted facts as memory
  content to the configured Caura backend, over the URL you supply. Use `https`
  for anything other than a local server.
- The API key is sent in the `X-API-Key` header and is never written to errors,
  results, or logs.
- Rail does not log. Fact content and backend response bodies never appear in
  `StoreError` messages or `turn.errors`.
- Rail does not load `.env` files or read any environment variables other than
  `CAURA_URL`, `CAURA_API_KEY`, and `CAURA_TENANT`, and only when you call
  `from_env` / `fromEnv`.
- HTTP redirects are not followed, so a redirecting backend cannot move
  credentials to another host.

## What Rail does not do

- It does not verify the truth of extracted facts or defend against prompt
  injection in recalled content. Treat `context.text` as untrusted input to your
  model.
- It does not provide exactly-once delivery or a persistent queue. See
  [reliability](docs/reliability.md).

## Supported versions

Security fixes are released for the latest minor version of 1.x.
