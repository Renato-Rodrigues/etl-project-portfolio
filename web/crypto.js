// Browser side of etl_dash/crypto.py (WebCrypto). Also loaded by tests/decrypt_check.mjs under Node.
const ROLES = ["viewer", "admin", "test"];
const aad = (kind, role) => `etl-dash:v2:${kind}${role ? ":" + role : ""}`;
const enc = new TextEncoder();
const unb64 = (s) => Uint8Array.from(atob(s), (c) => c.charCodeAt(0));

async function aesOpen(rawKey, box, ad) {
  const key = await crypto.subtle.importKey("raw", rawKey, "AES-GCM", false, ["decrypt"]);
  return new Uint8Array(await crypto.subtle.decrypt(
    { name: "AES-GCM", iv: unb64(box.iv), additionalData: enc.encode(ad) }, key, unb64(box.ct)));
}

// -> {role, data, admin} or throws Error("wrong password"). Wraps are unlabeled: the role is the AAD that verifies.
async function unlock(payload, password) {
  const base = await crypto.subtle.importKey("raw", enc.encode(password.normalize("NFC")), "PBKDF2", false, ["deriveBits"]);
  const kek = new Uint8Array(await crypto.subtle.deriveBits(
    { name: "PBKDF2", hash: payload.kdf.hash, salt: unb64(payload.kdf.salt), iterations: payload.kdf.iterations },
    base, 256));
  for (const wrap of payload.keys) {
    for (const role of ROLES) {
      let keys;
      try { keys = await aesOpen(kek, wrap, aad("key", role)); } catch { continue; }
      const [box, tag] = role === "test" ? [payload.extra, "test"] : [payload, ""];
      const json = (bytes) => JSON.parse(new TextDecoder().decode(bytes));
      const data = json(await aesOpen(keys.slice(0, 32), box.data, aad("data", tag)));
      const admin = keys.length === 64 ? json(await aesOpen(keys.slice(32), box.admin, aad("admin", tag))) : null;
      return { role, data, admin };
    }
  }
  throw new Error("wrong password");
}
