// Static checks for the dsh-brand bundle: manifest, patch row, assets and syntax.
import { spawnSync } from "node:child_process";
import { readFileSync, statSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const root = dirname(dirname(fileURLToPath(import.meta.url)));
const failures = [];

function check(condition, message) {
  if (!condition) failures.push(message);
}

function read(path) {
  return readFileSync(join(root, path), "utf8");
}

function size(path) {
  return statSync(join(root, path)).size;
}

const manifest = JSON.parse(read("package.json"));
check(manifest.name === "@aim-lab/dsh-brand", "package name must be @aim-lab/dsh-brand");
check(/^\d+\.\d+\.\d+$/.test(manifest.version), "version must be semver");
check(manifest.type === "module", "package must be an ES module");
check(Boolean(manifest.dsh?.bundle?.patch), "dsh.bundle.patch is required");
check(manifest.dsh?.client?.platform === "web", "dsh.client.platform must be web");
check(manifest.dsh?.client?.immediately === true, "dsh.client.immediately must be true");
check(
  Array.isArray(manifest.dsh?.client?.inject) && manifest.dsh.client.inject.length > 0,
  "dsh.client.inject must list the client packages whose slots are used",
);
check(manifest.exports?.["./icon"] === "./icon.png", "exports['./icon'] must point at icon.png");
check(
  (manifest.files ?? []).includes("cordis.patch.yml"),
  "files must ship cordis.patch.yml",
);

const patch = read("cordis.patch.yml");
check(
  patch.includes(`name: '${manifest.name}'`),
  "cordis.patch.yml row name must equal the package name",
);
check(
  /id:\s*ui-brand-official[\s\S]*disabled:\s*true/.test(patch),
  "cordis.patch.yml must disable ui-brand-official",
);

for (const path of ["index.js", "client.js", "icon.png"]) {
  try {
    check(size(path) > 0, `${path} must not be empty`);
  } catch {
    failures.push(`${path} is missing`);
  }
}

const iconBytes = size("icon.png");
check(iconBytes <= 256 * 1024, `icon.png is ${iconBytes} bytes; the limit is 256 KiB`);
check(readFileSync(join(root, "icon.png")).subarray(1, 4).toString() === "PNG", "icon.png must be a PNG");


for (const locale of ["zh", "en"]) {
  const dict = JSON.parse(read(`locale/${locale}.json`));
  check(Boolean(dict.meta?.title), `locale/${locale}.json needs meta.title`);
  check(Boolean(dict.meta?.description), `locale/${locale}.json needs meta.description`);
}

for (const file of ["index.js", "client.js"]) {
  const result = spawnSync(process.execPath, ["--check", join(root, file)], { encoding: "utf8" });
  check(result.status === 0, `${file} failed node --check: ${result.stderr.trim()}`);
}

if (failures.length > 0) {
  console.error("dsh-brand check failed:");
  for (const failure of failures) console.error(`  - ${failure}`);
  process.exit(1);
}

console.log(
  `dsh-brand check passed: ${manifest.name}@${manifest.version}, icon ${Math.round(iconBytes / 1024)} KiB`,
);
