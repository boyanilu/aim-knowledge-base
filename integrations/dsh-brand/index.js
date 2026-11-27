/**
 * Host half of the aim-lab-brand bundle.
 *
 * The package contributes browser presentation only, so the node side is an
 * empty Cordis plugin: it exists so the Loader has a host row to mount, while
 * the browser half ships through `exports["./client"]`.
 */
export function apply() {}
