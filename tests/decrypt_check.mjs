// Cross-check: decrypt a built index.html with the *browser* code (web/crypto.js) under Node's WebCrypto.
// usage: node tests/decrypt_check.mjs <index.html> <password>   -> prints {"role":..,"projects":N,"admin":bool}
import { readFileSync } from "node:fs";
import vm from "node:vm";

const [html, password] = [readFileSync(process.argv[2], "utf8"), process.argv[3]];
const payload = JSON.parse(html.match(/<script type="application\/json" id="payload">([\s\S]*?)<\/script>/)[1]);
const context = vm.createContext({ crypto: globalThis.crypto, atob, TextEncoder, TextDecoder, Uint8Array, JSON });
vm.runInContext(readFileSync(new URL("../web/crypto.js", import.meta.url), "utf8") + "\nthis.unlock = unlock;", context);
try {
  const s = await context.unlock(payload, password);
  console.log(JSON.stringify({ role: s.role, projects: s.data.projects.length, admin: s.admin !== null }));
} catch (e) {
  console.log(JSON.stringify({ error: e.message }));
}
