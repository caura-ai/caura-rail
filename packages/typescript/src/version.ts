/**
 * Package version as a source constant. Nothing stamps it at build time, so it
 * must agree with package.json; `npm test` asserts that and the release
 * workflow checks package.json against the tag.
 */
export const VERSION = "1.0.2";
