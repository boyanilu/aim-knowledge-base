// Pack the bundle into artifacts/ (ignored by git). Creates the directory when missing.
import { spawnSync } from "node:child_process";
import { mkdirSync } from "node:fs";

mkdirSync("artifacts", { recursive: true });

const npm = process.platform === "win32" ? "npm.cmd" : "npm";
const result = spawnSync(npm, ["pack", "--pack-destination", "artifacts"], {
  stdio: "inherit",
  shell: process.platform === "win32",
});

if (result.error) {
  console.error(result.error.message);
  process.exit(1);
}
process.exit(result.status ?? 1);
