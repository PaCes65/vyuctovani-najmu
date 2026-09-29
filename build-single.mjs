import { readFile, writeFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import path from "node:path";

const here = path.dirname(fileURLToPath(import.meta.url));
const index = await readFile(path.join(here, "index.html"), "utf8");
const css = await readFile(path.join(here, "style.css"), "utf8");
const core = (await readFile(path.join(here, "core.mjs"), "utf8")).replace(/^export /gm, "");
const app = (await readFile(path.join(here, "app.mjs"), "utf8")).replace(/^import \{[^\n]+\} from "\.\/core\.mjs";\n/, "");
const combined = index
  .replace('<link rel="stylesheet" href="./style.css">', `<style>\n${css}\n</style>`)
  .replace('<script type="module" src="./app.mjs"></script>', "")
  .replace("</body>", `<script>\n"use strict";\n${core}\n${app}\n</script>\n</body>`);
const output = path.resolve(here, "../PrekladTextuCZ-Web.html");
await writeFile(output, combined);
console.log(output);
