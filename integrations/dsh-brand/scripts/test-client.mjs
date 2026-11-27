// Load client.js outside DSH with a minimal module-loader and slot stub, then assert
// the bundle registers exactly the three brand slots and renders the expected copy.
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import vm from "node:vm";

const root = dirname(dirname(fileURLToPath(import.meta.url)));
const failures = [];
const check = (condition, message) => {
  if (!condition) failures.push(message);
};

let captured = null;
const created = [];
const headline = { childElementCount: 0, textContent: "探索未至之境" };
let rerender;
let disconnected = false;

const context = {
  console,
  window: {
    __ModuleLoader__: {
      load(spec) {
        captured = spec;
      },
    },
  },
  document: {
    body: {},
    querySelectorAll: () => [headline],
  },
  MutationObserver: class {
    constructor(callback) { rerender = callback; }
    observe() {}
    disconnect() { disconnected = true; }
  },
  requestAnimationFrame: (callback) => callback(),
  require: (name) => {
    if (name !== "react") throw new Error(`unexpected require: ${name}`);
    return {
      createElement: (type, props, ...children) => {
        const element = { type, props: props ?? {}, children };
        created.push(element);
        return element;
      },
    };
  },
};

vm.createContext(context);
vm.runInContext(readFileSync(join(root, "client.js"), "utf8"), context, { filename: "client.js" });

check(captured !== null, "client.js did not call window.__ModuleLoader__.load");
check(captured?.id === "@aim-lab/dsh-brand", `unexpected module id: ${captured?.id}`);

const registrations = [];
const slots = {
  inject(_name, register) {
    register();
  },
  register(definition, component) {
    registrations.push({ definition, component });
  },
};
const effects = [];

const module = captured.factory(context.require);
check(Array.isArray(module.inject) && module.inject.includes("slots"), "factory must inject 'slots'");
module.apply({ slots, effect: (callback, label) => effects.push({ callback, label }) });

const names = registrations.map((entry) => entry.definition.name).sort();
check(
  JSON.stringify(names) ===
    JSON.stringify(["conversation.hero.brand.mark", "sidebar.brand.mark", "sidebar.brand.name"]),
  `unexpected slot registrations: ${names.join(", ")}`,
);

const brandName = registrations.find((entry) => entry.definition.name === "sidebar.brand.name");
const brandElement = brandName.component();
check(
  brandElement.children[0] === "火箭总体结构辅助设计智能体",
  `unexpected brand name: ${brandElement.children[0]}`,
);

const emblem = registrations.find((entry) => entry.definition.name === "sidebar.brand.mark");
check(Boolean(emblem), "sidebar.brand.mark must be registered");
const image = emblem.component({ size: 24 });
check(String(image.props.src).startsWith("data:image/png;base64,"), "emblem must be an inline PNG data URI");
check(
  Buffer.from(image.props.src.split(",")[1], "base64").equals(readFileSync(join(root, "icon.png"))),
  "sidebar mark must match the packaged icon",
);
check(image.props.width === 24, `sidebar emblem should render at slot size, got ${image.props.width}`);

const hero = registrations.find((entry) => entry.definition.name === "conversation.hero.brand.mark");
check(hero.component() === null, "home mark must render nothing");

check(effects.length === 1, "the headline swap must be registered as one effect");
const dispose = effects[0].callback();
check(headline.textContent === "开始本次结构设计任务", "initial headline was not replaced");
headline.textContent = "Into the Unknown";
rerender();
check(headline.textContent === "开始本次结构设计任务", "headline was not replaced after rerender");
dispose();
check(disconnected, "disabling the plugin must disconnect the observer");

if (failures.length > 0) {
  console.error("dsh-brand client test failed:");
  for (const failure of failures) console.error(`  - ${failure}`);
  process.exit(1);
}

console.log(`dsh-brand client test passed: ${registrations.length} slots, brand name and slogan verified`);
