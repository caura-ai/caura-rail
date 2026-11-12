/**
 * Package version as a source constant. Nothing stamps it at build time, so it
 * must agree with package.json; `npm test` asserts that and the release
 * workflow checks package.json against the tag. release-please bumps it with
 * the other version files, finding it by the marker at the end of the line.
 */
export const VERSION = "1.0.2"; // x-release-please-version
