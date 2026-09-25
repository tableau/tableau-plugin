#!/usr/bin/env node
/**
 * Deterministically wire an embedded (local file) datasource into a scaffolded
 * data-app `.twb`, as an alternative to wire-datasource.mjs's published-datasource
 * path. Same job, same two empty `<datasources />` anchors (workbook root + worksheet
 * `<view>`), same "fill both or fail" contract — but the connection is a `textscan`
 * (CSV) file bundled inside the `.twbx` instead of a `sqlproxy` (Data Server) proxy
 * to a published datasource on a server.
 *
 * CSV only, for now: Tableau also supports embedding Excel (`excel-direct`), other
 * local file types, and true embedded Hyper extracts (`hyper`, via the Hyper API),
 * but only the CSV/`textscan` path has been validated end-to-end (published and
 * queried live from a data-app extension). Extending this script to other file
 * types would need its own validation pass first.
 *
 * Unlike a published datasource, the file itself must ship inside the `.twbx`.
 * This script copies the source file to `<workspace root>/Data/<filename>` —
 * a directory that sits at the ARCHIVE ROOT alongside `Packages/`, never inside
 * it. Phase 3 packaging (SKILL.md) must zip `Data/` in addition to `Packages/`.
 *
 * Column metadata is inferred directly from the CSV (header row + a sample of
 * data rows, integer/real/string) rather than requiring a hand-written descriptor
 * — there is no MCP introspection tool for a local file the way there is for a
 * published datasource. An optional descriptor can override inferred datatype/role
 * per field by name.
 *
 * Usage:
 *   node wire-embedded-datasource.mjs <path-to.twb> <path-to.csv> [descriptor.json]
 *
 * descriptor.json (optional; overrides inferred datatype/role for named fields):
 *   {
 *     "caption": "Tennis Players",              // optional, defaults from filename
 *     "connectionName": "federated.<hash>",     // optional, generated if omitted
 *     "fields": [
 *       { "name": "career_singles_titles", "datatype": "integer", "role": "measure" }
 *     ]
 *   }
 *
 * Exits non-zero with a diagnostic on any failure (missing/already-filled anchor,
 * empty CSV, drifted template) rather than emitting a broken workbook. Prints the
 * wired `.twb` path on stdout.
 */

import { readFileSync, writeFileSync, copyFileSync, mkdirSync, existsSync } from 'node:fs';
import { resolve, dirname, basename, extname } from 'node:path';

// The exact empty anchors emitted by the scaffold template. Matched literally.
const EMPTY_ANCHOR = '<datasources />';

function die(message) {
  console.error(`✗ ${message}`);
  process.exit(1);
}

// XML attribute-value escaping (single-quoted attrs + element text).
function esc(value) {
  return String(value)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/'/g, '&apos;')
    .replace(/"/g, '&quot;');
}

// Minimal CSV line splitter: no embedded-comma/quote support. Good enough for the
// flat, simple CSVs this path is meant for; a quoted-field CSV needs a real parser.
function splitCsvLine(line) {
  return line.split(',').map((cell) => cell.trim());
}

function inferDatatype(values) {
  const nonEmpty = values.filter((v) => v !== '');
  if (nonEmpty.length === 0) return 'string';
  if (nonEmpty.every((v) => /^-?\d+$/.test(v))) return 'integer';
  if (nonEmpty.every((v) => /^-?\d+(\.\d+)?$/.test(v))) return 'real';
  return 'string';
}

// datatype -> Tableau column `type`.
function typeOf(datatype) {
  return datatype === 'real' || datatype === 'integer' ? 'quantitative' : 'nominal';
}

// A field's derived attributes, computed once and reused across all blocks so the
// root metadata-record, the root column, the view column, and the column-instance
// all agree — mirrors wire-datasource.mjs's deriveField.
function deriveField(name, datatype, role, ordinal) {
  const isMeasure = role === 'measure';
  const type = typeOf(datatype);
  return {
    name,
    datatype,
    role,
    type,
    ordinal,
    aggregation: isMeasure ? 'Sum' : 'Count',
    localName: `[${name}]`,
    derivation: isMeasure ? 'Sum' : 'None',
    instanceName: isMeasure ? `[sum:${name}:qk]` : `[none:${name}:nk]`,
  };
}

// --- args ---------------------------------------------------------------

const [, , twbPathArg, csvPathArg, descriptorPathArg] = process.argv;
if (!twbPathArg || !csvPathArg) {
  die('Usage: node wire-embedded-datasource.mjs <path-to.twb> <path-to.csv> [descriptor.json]');
}
const twbPath = resolve(twbPathArg);
const csvPath = resolve(csvPathArg);
if (extname(csvPath).toLowerCase() !== '.csv') {
  die(`Only .csv files are supported by this script (got "${basename(csvPath)}"). See file header for other embedded-file types (unvalidated).`);
}
if (!existsSync(csvPath)) {
  die(`CSV not found at ${csvPath}`);
}

let descriptor = {};
if (descriptorPathArg) {
  try {
    descriptor = JSON.parse(readFileSync(descriptorPathArg, 'utf8'));
  } catch (error) {
    die(`Could not read/parse descriptor JSON at ${descriptorPathArg}: ${error.message}`);
  }
}

// --- read + infer from the CSV ------------------------------------------

let csvLines;
try {
  csvLines = readFileSync(csvPath, 'utf8').split(/\r\n|\r|\n/).filter((l) => l.length > 0);
} catch (error) {
  die(`Could not read CSV at ${csvPath}: ${error.message}`);
}
if (csvLines.length < 2) {
  die('CSV must have a header row plus at least one data row.');
}

const header = splitCsvLine(csvLines[0]);
const sampleRows = csvLines.slice(1, 201).map(splitCsvLine); // sample up to 200 rows for type inference

const overridesByName = new Map((Array.isArray(descriptor.fields) ? descriptor.fields : []).map((f) => [f.name, f]));

const fields = header.map((name, i) => {
  if (!name) die(`CSV header has an empty column name at position ${i}.`);
  const override = overridesByName.get(name);
  const columnValues = sampleRows.map((row) => row[i] ?? '');
  const datatype = override?.datatype || inferDatatype(columnValues);
  const role = override?.role === 'measure' || override?.role === 'dimension'
    ? override.role
    : (datatype === 'integer' || datatype === 'real' ? 'measure' : 'dimension');
  return deriveField(name, datatype, role, i);
});

const filename = basename(csvPath);
const tableBaseName = basename(filename, extname(filename));
const caption = descriptor.caption || tableBaseName.replace(/[_-]+/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase());

// Single source of truth for the join key. Must start with "federated." — the
// wiring is a federated connection wrapping a named textscan connection, not a
// bare sqlproxy the way a published datasource is.
const connectionName =
  descriptor.connectionName ||
  `federated.${Math.random().toString(36).slice(2)}${Math.random().toString(36).slice(2)}`.slice(0, 37);
if (!connectionName.startsWith('federated.')) {
  die(`connectionName must start with "federated." (got "${connectionName}").`);
}
const namedConnectionName = connectionName.replace(/^federated\./, 'textscan.');

// --- copy the CSV into Data/<filename> at the workspace root -------------

const workspaceRoot = dirname(twbPath);
const dataDir = resolve(workspaceRoot, 'Data');
mkdirSync(dataDir, { recursive: true });
const destCsvPath = resolve(dataDir, filename);
copyFileSync(csvPath, destCsvPath);

// --- build the XML blocks ------------------------------------------------

const metadataRecords = fields
  .map(
    (f) => `          <metadata-record class='column'>
            <remote-name>${esc(f.name)}</remote-name>
            <remote-type>${f.type === 'quantitative' ? 5 : 129}</remote-type>
            <local-name>${esc(f.localName)}</local-name>
            <parent-name>[${esc(tableBaseName)}]</parent-name>
            <remote-alias>${esc(f.name)}</remote-alias>
            <ordinal>${f.ordinal}</ordinal>
            <local-type>${esc(f.datatype)}</local-type>
            <aggregation>${f.aggregation}</aggregation>
            <contains-null>true</contains-null>
          </metadata-record>`,
  )
  .join('\n');

const rootColumns = fields
  .map((f) => `      <column datatype='${esc(f.datatype)}' name='${esc(f.localName)}' role='${f.role}' type='${f.type}' />`)
  .join('\n');

const rootDatasource = `<datasources>
    <datasource caption='${esc(caption)}' inline='true' name='${esc(connectionName)}' version='18.1'>
      <connection class='federated'>
        <named-connections>
          <named-connection caption='${esc(filename)}' name='${esc(namedConnectionName)}'>
            <connection class='textscan' directory='Data' filename='${esc(filename)}' password='' server='' />
          </named-connection>
        </named-connections>
        <relation connection='${esc(namedConnectionName)}' name='${esc(filename)}' table='[${esc(tableBaseName)}#csv]' type='table' />
        <metadata-records>
${metadataRecords}
        </metadata-records>
      </connection>
      <aliases enabled='yes' />
${rootColumns}
    </datasource>
  </datasources>`;

const viewColumns = fields
  .map(
    (f) =>
      `            <column aggregation='${f.aggregation}' datatype='${esc(f.datatype)}' name='${esc(f.localName)}' role='${f.role}' type='${f.type}' />`,
  )
  .join('\n');

const viewColumnInstances = fields
  .map(
    (f) =>
      `            <column-instance column='${esc(f.localName)}' derivation='${f.derivation}' name='${esc(f.instanceName)}' pivot='key' type='${f.type}' />`,
  )
  .join('\n');

const viewDatasources = `<datasources>
            <datasource caption='${esc(caption)}' name='${esc(connectionName)}' />
          </datasources>
          <datasource-dependencies datasource='${esc(connectionName)}'>
${viewColumns}
${viewColumnInstances}
          </datasource-dependencies>`;

// --- apply, splitting on <worksheets> so each anchor is unambiguous ------

let content;
try {
  content = readFileSync(twbPath, 'utf8');
} catch (error) {
  die(`Could not read .twb at ${twbPath}: ${error.message}`);
}

const splitIdx = content.indexOf('<worksheets>');
if (splitIdx === -1) {
  die('No <worksheets> element found — is this a scaffolded data-app .twb?');
}
let head = content.slice(0, splitIdx);
let tail = content.slice(splitIdx);

// Root anchor lives in the head (before <worksheets>).
if (!head.includes(EMPTY_ANCHOR)) {
  die(`Root "${EMPTY_ANCHOR}" anchor not found before <worksheets> — already wired or template drifted.`);
}
head = head.replace(EMPTY_ANCHOR, rootDatasource);

// View anchor is the first empty <datasources /> inside the worksheets section.
if (!tail.includes(EMPTY_ANCHOR)) {
  die(`View "${EMPTY_ANCHOR}" anchor not found inside <worksheets> — already wired or template drifted.`);
}
tail = tail.replace(EMPTY_ANCHOR, viewDatasources);

const wired = head + tail;

// --- verify before writing ----------------------------------------------

if (wired.includes(EMPTY_ANCHOR)) {
  die('An empty <datasources /> anchor survived wiring — refusing to write a half-wired workbook.');
}
// Unlike wire-datasource.mjs's bare sqlproxy, the relation here joins through the
// named connection's own key, not the outer federated one — so the two join keys
// must be verified separately rather than expecting one string 4 times.
//
// connectionName (federated.<hash>) appears: root datasource name, view datasource
// name, datasource-dependencies datasource = at least 3 references.
const refCount = wired.split(`'${connectionName}'`).length - 1;
if (refCount < 3) {
  die(`Expected the connection name to appear >=3 times, saw ${refCount} — wiring incomplete.`);
}
// namedConnectionName (textscan.<hash>) appears: named-connection name, relation
// connection = at least 2 references.
const namedRefCount = wired.split(`'${namedConnectionName}'`).length - 1;
if (namedRefCount < 2) {
  die(`Expected the named connection to appear >=2 times, saw ${namedRefCount} — wiring incomplete.`);
}

writeFileSync(twbPath, wired, 'utf8');
console.error(
  `✓ Wired embedded CSV datasource '${caption}' (${connectionName}) with ${fields.length} field(s) into ${twbPath}`,
);
console.error(`✓ Copied ${filename} to ${destCsvPath}`);
console.log(twbPath);
