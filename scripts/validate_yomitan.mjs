#!/usr/bin/env node
// Independent Node/ajv validation of a built Bee's Ultimate Grammar Dictionary ZIP
// against the pinned official Yomitan schemas under schemas/.
//
// Usage: node scripts/validate_yomitan.mjs <path-to-dictionary.zip> [--require-entries]
//
// This is deliberately a second implementation of src/bugd/validate.py: two
// validators reading the same pinned schema bytes, so a bug in one is caught by
// the other. Checks:
//   - bank JSON / index.json / styles.css live at the ZIP root; only media/* may
//     be in a subfolder (Yomitan requires bank JSON at the root)
//   - index.json and every contiguous term / term-meta / tag bank validate
//     against schemas/*.json using JSON Schema draft-07
//   - no native kanji bank ships (it would route lookups to the fixed renderer)
//   - no duplicate member names, and no unrecognised member Yomitan would
//     silently ignore while still shipping it to users
//   - every structured-content img path resolves to a packaged member
//   - with --require-entries, the archive carries at least one term entry

import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const AdmZip = require("adm-zip");
const Ajv = require("ajv");

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const schemaDir = join(root, "schemas");

const args = process.argv.slice(2);
const requireEntries = args.includes("--require-entries");
const zipPath = args.find((arg) => !arg.startsWith("--"));
if (!zipPath) {
  console.error("usage: validate_yomitan.mjs <dictionary.zip> [--require-entries]");
  process.exit(2);
}

const MEDIA_DIR = "media";
const EXPECTED_ROOT = ["index.json", "styles.css"];
const FORBIDDEN_BANK = /^(?:kanji_bank|kanji_meta_bank)_[1-9][0-9]*\.json$/;
// Licence/attribution text may travel with the archive even though Yomitan
// ignores it; keep this list identical to validate.ALLOWED_EXTRA_MEMBERS.
const ALLOWED_EXTRA = new Set(["LICENSE", "NOTICE", "ATTRIBUTION.md"]);

const SCHEMA_FOR = { "index.json": "dictionary-index-schema.json" };

const BANK_GROUPS = [
  {
    label: "term bank",
    pattern: /^term_bank_([1-9][0-9]*)\.json$/,
    schema: "dictionary-term-bank-v3-schema.json",
    required: false,
  },
  {
    label: "term meta bank",
    pattern: /^term_meta_bank_([1-9][0-9]*)\.json$/,
    schema: "dictionary-term-meta-bank-v3-schema.json",
    required: false,
  },
  {
    label: "tag bank",
    pattern: /^tag_bank_([1-9][0-9]*)\.json$/,
    schema: "dictionary-tag-bank-v3-schema.json",
    required: false,
  },
];

const loadSchema = (name) => JSON.parse(readFileSync(join(schemaDir, name), "utf-8"));

const zip = new AdmZip(zipPath);
const names = zip.getEntries().map((entry) => entry.entryName);
const nameSet = new Set(names);
let ok = true;

for (const name of names) {
  if (name.includes("/") && !name.startsWith(`${MEDIA_DIR}/`)) {
    console.error(`FAIL: unexpected non-root member: ${name}`);
    ok = false;
  }
  if (FORBIDDEN_BANK.test(name)) {
    console.error(`FAIL: forbidden native kanji bank present: ${name}`);
    ok = false;
  }
}
if (names.length !== nameSet.size) {
  console.error("FAIL: archive contains duplicate member names");
  ok = false;
}
for (const want of EXPECTED_ROOT) {
  if (!nameSet.has(want)) {
    console.error(`FAIL: missing expected member: ${want}`);
    ok = false;
  }
}

// Yomitan silently skips members it does not recognise, so a stray root file is
// invisible at import yet still shipped to users. Refuse it here too.
const knownRoot = new Set([...EXPECTED_ROOT, ...Object.keys(SCHEMA_FOR)]);
for (const name of names) {
  if (name.startsWith(`${MEDIA_DIR}/`) || knownRoot.has(name) || ALLOWED_EXTRA.has(name)) continue;
  if (BANK_GROUPS.some((group) => group.pattern.test(name))) continue;
  console.error(`FAIL: unrecognised archive member Yomitan would ignore: ${name}`);
  ok = false;
}

// Fail fast within each invalid branch: production structured-content banks have
// many oneOf alternatives and allErrors would build enormous discarded arrays.
const ajv = new Ajv({ allErrors: false, strict: false });
const parsed = new Map();

// Compile each pinned schema ONCE and reuse the validator across every bank.
// Yomitan's schemas carry an `$id`, so calling ajv.compile() a second time for
// term_bank_2.json threw `schema with key or id "dictionaryTermBankV3" already
// exists` and aborted the run *after* term_bank_1.json had already printed OK —
// a multi-bank dictionary was therefore never fully cross-checked.
const compiled = new Map();
const validatorFor = (schemaName) => {
  let validate = compiled.get(schemaName);
  if (validate === undefined) {
    validate = ajv.compile(loadSchema(schemaName));
    compiled.set(schemaName, validate);
  }
  return validate;
};

const validateMember = (member, schemaName, label) => {
  const data = JSON.parse(zip.readAsText(member));
  parsed.set(member, data);
  const validate = validatorFor(schemaName);
  if (!validate(data)) {
    ok = false;
    console.error(`FAIL: ${member} does not match ${schemaName}`);
    for (const err of validate.errors.slice(0, 5)) {
      console.error(`   ${err.instancePath} ${err.message}`);
    }
    return;
  }
  const count = Array.isArray(data) ? data.length : 1;
  console.log(`OK: ${member} (${count} ${label === "index" ? "object" : "entries"}) matches ${schemaName}`);
};

for (const [member, schemaName] of Object.entries(SCHEMA_FOR)) {
  if (nameSet.has(member)) validateMember(member, schemaName, "index");
}

const bankMembers = new Map();
for (const group of BANK_GROUPS) {
  const members = names
    .map((name) => {
      const match = group.pattern.exec(name);
      return match ? { name, number: Number(match[1]) } : null;
    })
    .filter(Boolean)
    .sort((a, b) => a.number - b.number);
  bankMembers.set(group.label, members);

  if (members.length === 0) {
    if (group.required) {
      console.error(`FAIL: no ${group.label} members found`);
      ok = false;
    }
    continue;
  }
  if (members.some((member, index) => member.number !== index + 1)) {
    console.error(
      `FAIL: ${group.label} members are not contiguous from 1: ` +
        members.map((member) => member.name).join(", ")
    );
    ok = false;
  }
  for (const member of members) validateMember(member.name, group.schema, group.label);
}

// Every referenced structured-content img path must resolve to a packaged member.
const termBanks = bankMembers.get("term bank") || [];
if (termBanks.length > 0) {
  const referenced = new Set();
  const walk = (node) => {
    if (Array.isArray(node)) {
      node.forEach(walk);
    } else if (node && typeof node === "object") {
      if (node.tag === "img" && typeof node.path === "string") referenced.add(node.path);
      for (const value of Object.values(node)) walk(value);
    }
  };
  for (const member of termBanks) walk(parsed.get(member.name));
  for (const path of referenced) {
    if (!nameSet.has(path)) {
      console.error(`FAIL: dangling img asset reference: ${path}`);
      ok = false;
    }
  }
  console.log(`OK: ${referenced.size} referenced img assets all resolve`);
}

// Release gate: a structurally valid but empty archive imports as a dictionary
// with nothing in it, so refuse to treat it as publishable.
const termEntries = termBanks.reduce((total, member) => {
  const bank = parsed.get(member.name);
  return total + (Array.isArray(bank) ? bank.length : 0);
}, 0);
if (requireEntries && termEntries === 0) {
  console.error(
    "FAIL: no term entries: an importable dictionary must carry at least one " +
      "term bank entry (refusing to package an empty dictionary)"
  );
  ok = false;
}

if (!ok) {
  console.error("Yomitan validation FAILED");
  process.exit(1);
}
console.log(`OK: ${termEntries} term entries across ${termBanks.length} term bank(s)`);
console.log("Yomitan validation passed");
