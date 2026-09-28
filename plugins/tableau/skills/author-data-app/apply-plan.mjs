#!/usr/bin/env node
/**
 * Finalize a scaffolded data-app workspace by applying the `postUnzip` plan from
 * the `scaffold-data-app` MCP tool. Plan shape:
 *   { edits: [{ file, replacements: [{ find, replace, occurrence }] }],
 *     renames: [{ from, to }], wiresDatasource }
 * Every path is relative to the unzip dir, incl. the template root prefix
 * (e.g. "Data App Name/...").
 *
 * Order is why this is a script, not freehand edits: apply ALL edits first, THEN
 * renames in the given order (deepest first, root last). Renaming before editing
 * invalidates edit paths; reordering renames orphans a child under its parent.
 *
 * `occurrence: 'first'` replaces only the first remaining match — used to resolve
 * two identical anchors to different values in sequence; 'all'/omitted replaces
 * every match. `wiresDatasource` adds `<datasources />` to the residual-token check.
 *
 * Usage: node apply-plan.mjs <unzipDir> <planJsonPath>
 */

import { readFileSync, renameSync, writeFileSync } from 'node:fs';
import { join, resolve } from 'node:path';

const PLACEHOLDER_TOKENS = ['TODO-MANIFEST-ID', 'TODO App Name', 'TODO Username via Tableau MCP'];
const WIRING_ANCHOR_TOKEN = '<datasources />';

function die(message) {
  console.error(`✗ ${message}`);
  process.exit(1);
}

const [, , unzipDirArg, planPathArg] = process.argv;
if (!unzipDirArg || !planPathArg) {
  die('Usage: node apply-plan.mjs <unzipDir> <planJsonPath>');
}

const unzipDir = resolve(unzipDirArg);

let plan;
try {
  plan = JSON.parse(readFileSync(planPathArg, 'utf8'));
} catch (error) {
  die(`Could not read/parse plan JSON at ${planPathArg}: ${error.message}`);
}

const edits = Array.isArray(plan.edits) ? plan.edits : [];
const renames = Array.isArray(plan.renames) ? plan.renames : [];
if (edits.length === 0 && renames.length === 0) {
  die('Plan has no edits or renames — did you pass the full postUnzip object?');
}

// Guard against a plan path escaping the unzip dir.
function safeJoin(rel) {
  const abs = resolve(unzipDir, rel);
  if (abs !== unzipDir && !abs.startsWith(unzipDir + '/')) {
    die(`Plan path escapes the unzip directory: ${rel}`);
  }
  return abs;
}

// 1) Apply edits: literal (non-regex) find/replace on each file's contents.
for (const { file, replacements } of edits) {
  const abs = safeJoin(file);
  let content;
  try {
    content = readFileSync(abs, 'utf8');
  } catch (error) {
    die(`Edit target missing: ${file} (${error.message})`);
  }
  for (const { find, replace, occurrence } of replacements ?? []) {
    if (!content.includes(find)) {
      die(`Placeholder "${find}" not found in ${file} — template/plan out of sync.`);
    }
    if (occurrence === 'first') {
      const idx = content.indexOf(find);
      content = content.slice(0, idx) + replace + content.slice(idx + find.length);
    } else {
      content = content.split(find).join(replace);
    }
  }
  writeFileSync(abs, content, 'utf8');
  console.error(`  edited  ${file}`);
}

// 2) Apply renames in the given order (deepest-first, root last).
for (const { from, to } of renames) {
  try {
    renameSync(safeJoin(from), safeJoin(to));
  } catch (error) {
    die(`Rename failed: ${from} -> ${to} (${error.message})`);
  }
  console.error(`  renamed ${from} -> ${to}`);
}

// 3) The finalized workspace root is the target of the last rename.
const finalRootRel = renames.at(-1)?.to;
const finalRoot = finalRootRel ? safeJoin(finalRootRel) : unzipDir;

// 4) Verify no placeholder tokens survived. Recompute each edited file's final
//    path through every rename — a file can move via more than one (e.g. the
//    root-dir rename AND a nested package-dir rename).
function remapThroughRenames(relPath) {
  let current = relPath;
  for (const { from, to } of renames) {
    if (current === from) {
      current = to;
    } else if (current.startsWith(from + '/')) {
      current = to + current.slice(from.length);
    }
  }
  return current;
}

const residual = [];
for (const { file } of edits) {
  const finalRel = remapThroughRenames(file);
  let content;
  try {
    content = readFileSync(safeJoin(finalRel), 'utf8');
  } catch (error) {
    die(`Finalized file missing for placeholder check: ${finalRel} (${error.message})`);
  }
  const tokens = plan.wiresDatasource
    ? [...PLACEHOLDER_TOKENS, WIRING_ANCHOR_TOKEN]
    : PLACEHOLDER_TOKENS;
  for (const token of tokens) {
    if (content.includes(token)) {
      residual.push(`${finalRel}: "${token}"`);
    }
  }
}
if (residual.length > 0) {
  die(`Residual placeholders after finalize:\n  ${residual.join('\n  ')}`);
}

console.error(`✓ Finalized workspace at ${join(finalRoot)}`);
console.log(finalRoot);
