/** Build the formatted Excel snapshot of the Sector v0.93 decision register. */

import crypto from "node:crypto";
import fs from "node:fs/promises";
import { createRequire } from "node:module";
import path from "node:path";
import { fileURLToPath } from "node:url";


const scriptDir = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = path.dirname(scriptDir);
const runtimeRequire = createRequire(
  path.join(process.cwd(), "artifact-tool-runner.cjs"),
);
const { SpreadsheetFile, Workbook } = runtimeRequire("@oai/artifact-tool");

const decisionsPath = path.join(repoRoot, "docs", "v093_decision_register.md");
const programmePath = path.join(repoRoot, "docs", "v093_pr_programme.md");
const outputPath = path.join(
  repoRoot,
  "docs",
  "sector_v093_decision_register.xlsx",
);
const previewDir = path.join(repoRoot, "tmp", "v093-decision-workbook-preview");

const decisionsText = await fs.readFile(decisionsPath, "utf8");
const programmeText = await fs.readFile(programmePath, "utf8");
const decisionsSha256 = crypto
  .createHash("sha256")
  .update(decisionsText, "utf8")
  .digest("hex")
  .toUpperCase();

function cleanCell(value) {
  return value
    .trim()
    .replaceAll("`", "")
    .replaceAll("**", "")
    .replace(/\[([^\]]+)\]\([^\)]+\)/g, "$1")
    .replace(/\s+/g, " ");
}

function markdownRows(text, firstCellPattern, expectedColumns) {
  return text
    .split(/\r?\n/)
    .filter((line) => firstCellPattern.test(line))
    .map((line) => line.split("|").slice(1, -1).map(cleanCell))
    .filter((row) => row.length === expectedColumns);
}

function tableAfter(text, heading, headerFirstCell, expectedColumns) {
  const start = text.indexOf(heading);
  if (start < 0) {
    throw new Error(`Missing Markdown heading: ${heading}`);
  }
  const tail = text.slice(start).split(/\r?\n/);
  const headerIndex = tail.findIndex((line) =>
    line.startsWith(`| ${headerFirstCell} |`),
  );
  if (headerIndex < 0) {
    throw new Error(`Missing Markdown table after: ${heading}`);
  }
  const rows = [];
  for (const line of tail.slice(headerIndex + 2)) {
    if (!line.startsWith("|")) {
      break;
    }
    const row = line.split("|").slice(1, -1).map(cleanCell);
    if (row.length === expectedColumns) {
      rows.push(row);
    }
  }
  return rows;
}

const decisionRows = markdownRows(
  decisionsText,
  /^\| D093-\d{3} \|/,
  5,
).map((row) => [
  row[0],
  row[1],
  row[2],
  row[3],
  row[4],
  "Frozen",
  row[0] === "D093-013" ? "Deferred" : "Implement",
]);

const programmeRows = markdownRows(
  programmeText,
  /^\| \d+ \| PR-/,
  4,
).map((row) => [Number(row[0]), row[1], row[2], row[3]]);

const standardsRows = tableAfter(
  decisionsText,
  "## Standards status frozen for implementation",
  "Family",
  4,
);

const manualVisualRows = tableAfter(
  programmeText,
  "### 2.8 Manual review and target information architecture",
  "Current page",
  3,
).map((row) => ["Manual", ...row]);
const reportVisualRows = tableAfter(
  programmeText,
  "### 2.9 Report review and target profiles",
  "Current page",
  3,
).map((row) => ["Report", ...row]);
const publicationRows = [...manualVisualRows, ...reportVisualRows];

if (decisionRows.length !== 27) {
  throw new Error(`Expected 27 decisions, found ${decisionRows.length}`);
}
if (programmeRows.length !== 10) {
  throw new Error(`Expected 10 programme rows, found ${programmeRows.length}`);
}
if (standardsRows.length !== 4) {
  throw new Error(`Expected 4 standards rows, found ${standardsRows.length}`);
}

const workbook = Workbook.create();
const readMe = workbook.worksheets.add("Read Me");
const decisions = workbook.worksheets.add("Decisions");
const programme = workbook.worksheets.add("PR Programme");
const standards = workbook.worksheets.add("Standards");
const publication = workbook.worksheets.add("Publication QA");

const darkBlue = "#17365D";
const midBlue = "#1F4E78";
const lightBlue = "#D9EAF7";
const paleBlue = "#EEF5FA";
const green = "#E2F0D9";
const amber = "#FFF2CC";
const grey = "#E7E6E6";
const white = "#FFFFFF";
const text = "#1F1F1F";
const border = "#B4C6D7";

function setTitle(sheet, rangeAddress, title, subtitle) {
  const titleRange = sheet.getRange(rangeAddress);
  titleRange.merge();
  titleRange.values = [[title]];
  titleRange.format = {
    fill: darkBlue,
    font: { bold: true, color: white, size: 20 },
    verticalAlignment: "center",
    horizontalAlignment: "left",
  };
  titleRange.format.rowHeight = 34;

  const columns = rangeAddress.split(":")[1].replace(/\d+/g, "");
  const subtitleRange = sheet.getRange(`A2:${columns}2`);
  subtitleRange.merge();
  subtitleRange.values = [[subtitle]];
  subtitleRange.format = {
    fill: lightBlue,
    font: { italic: true, color: darkBlue, size: 10 },
    verticalAlignment: "center",
    wrapText: true,
  };
  subtitleRange.format.rowHeight = 28;
}

function styleTable(sheet, address, tableName, widths) {
  const table = sheet.tables.add(address, true, tableName);
  table.style = "TableStyleMedium2";
  table.showBandedColumns = false;
  table.showFilterButton = true;
  const header = table.getHeaderRowRange();
  header.format = {
    fill: midBlue,
    font: { bold: true, color: white, size: 10 },
    verticalAlignment: "center",
    wrapText: true,
    borders: { preset: "outside", style: "thin", color: darkBlue },
  };
  header.format.rowHeight = 32;
  widths.forEach(([column, width]) => {
    sheet.getRange(`${column}1:${column}200`).format.columnWidth = width;
  });
  return table;
}

function styleBody(sheet, address, rowHeight = 58) {
  const range = sheet.getRange(address);
  range.format = {
    font: { color: text, size: 9 },
    verticalAlignment: "top",
    horizontalAlignment: "left",
    wrapText: true,
    borders: {
      insideHorizontal: { style: "thin", color: border },
      bottom: { style: "thin", color: border },
    },
  };
  range.format.rowHeight = rowHeight;
}

for (const sheet of [readMe, decisions, programme, standards, publication]) {
  sheet.showGridLines = false;
}

setTitle(
  readMe,
  "A1:G1",
  "Sector v0.93 Decision Register",
  "Owner decisions and programme controls - frozen 2026-08-08",
);
readMe.getRange("A4:B12").values = [
  ["Record", "Value"],
  ["Target release", "Sector 0.93"],
  ["Programme baseline", "decd1232abb0a082639de90726c125dc988e1078"],
  ["Baseline tree", "f25a74a1a234b7b09ddc1be216fe31187333abbd"],
  ["Baseline release", "v0.92-source.1"],
  ["Decision freeze date", "2026-08-08"],
  ["Canonical record", "docs/v093_decision_register.md"],
  ["Canonical record SHA-256", decisionsSha256],
  ["Governing identity", "docs/product_identity.md"],
];
styleTable(readMe, "A4:B12", "RegisterMetadata", [
  ["A", 27],
  ["B", 76],
]);
styleBody(readMe, "A5:B12", 26);

readMe.getRange("D4:E9").values = [
  ["Live summary", "Count"],
  ["Frozen decisions", null],
  ["Implementation decisions", null],
  ["Deferred decisions", null],
  ["Planned PR slices", null],
  ["PR slices in progress", null],
];
readMe.getRange("E5").formulas = [["=COUNTA(Decisions!A5:A31)"]];
readMe.getRange("E6").formulas = [["=COUNTIF(Decisions!G5:G31,\"Implement\")"]];
readMe.getRange("E7").formulas = [["=COUNTIF(Decisions!G5:G31,\"Deferred\")"]];
readMe.getRange("E8").formulas = [["=COUNTIF('PR Programme'!D5:D14,\"Planned\")"]];
readMe.getRange("E9").formulas = [["=COUNTIF('PR Programme'!D5:D14,\"In progress\")"]];
styleTable(readMe, "D4:E9", "RegisterSummary", [
  ["D", 27],
  ["E", 14],
]);
styleBody(readMe, "D5:E9", 26);
readMe.getRange("E5:E9").format = {
  fill: paleBlue,
  font: { bold: true, color: darkBlue, size: 12 },
  horizontalAlignment: "center",
  verticalAlignment: "center",
};

readMe.getRange("A15:G18").merge();
readMe.getRange("A15:G18").values = [[
  "Authority and use: this workbook is a formatted snapshot of the accepted " +
    "Markdown decision register. The accepted Git revision is authoritative " +
    "if a discrepancy is found. Sector remains a transparent structural " +
    "calculation tool, not an engineering certification or global compliance " +
    "system. A qualified engineer remains responsible for applicability, " +
    "inputs, modelling, independent verification and acceptance.",
]];
readMe.getRange("A15:G18").format = {
  fill: amber,
  font: { color: text, size: 10 },
  wrapText: true,
  verticalAlignment: "center",
  borders: { preset: "outside", style: "medium", color: "#BF9000" },
};
readMe.freezePanes.freezeRows(2);

setTitle(
  decisions,
  "A1:G1",
  "Frozen owner decisions",
  "Filter by PR, status or disposition. Complete wording is retained from the canonical register.",
);
const decisionHeaders = [
  "Decision ID",
  "Frozen decision",
  "Reason and boundary",
  "Acceptance evidence",
  "Owning PR",
  "Status",
  "Disposition",
];
decisions.getRange(`A4:G${decisionRows.length + 4}`).values = [
  decisionHeaders,
  ...decisionRows,
];
styleTable(
  decisions,
  `A4:G${decisionRows.length + 4}`,
  "V093Decisions",
  [
    ["A", 15],
    ["B", 48],
    ["C", 66],
    ["D", 48],
    ["E", 18],
    ["F", 14],
    ["G", 14],
  ],
);
styleBody(decisions, `A5:G${decisionRows.length + 4}`, 72);
decisions.getRange(`A5:A${decisionRows.length + 4}`).format = {
  fill: paleBlue,
  font: { bold: true, color: darkBlue, size: 9 },
  horizontalAlignment: "center",
  verticalAlignment: "top",
};
decisions.getRange(`F5:F${decisionRows.length + 4}`).format = {
  fill: lightBlue,
  font: { bold: true, color: darkBlue, size: 9 },
  horizontalAlignment: "center",
  verticalAlignment: "top",
};
for (let index = 0; index < decisionRows.length; index += 1) {
  const row = index + 5;
  decisions.getRange(`G${row}`).format = {
    fill: decisionRows[index][6] === "Deferred" ? amber : green,
    font: { bold: true, color: text, size: 9 },
    horizontalAlignment: "center",
    verticalAlignment: "top",
  };
}
decisions.freezePanes.freezeRows(4);
decisions.freezePanes.freezeColumns(1);

setTitle(
  programme,
  "A1:D1",
  "Pull-request programme",
  "Statuses change only after objective evidence exists; dependencies are execution gates.",
);
programme.getRange(`A4:D${programmeRows.length + 4}`).values = [
  ["Order", "Slice", "Depends on", "Status"],
  ...programmeRows,
];
styleTable(
  programme,
  `A4:D${programmeRows.length + 4}`,
  "V093Programme",
  [
    ["A", 10],
    ["B", 62],
    ["C", 32],
    ["D", 18],
  ],
);
styleBody(programme, `A5:D${programmeRows.length + 4}`, 42);
programme.getRange(`A5:A${programmeRows.length + 4}`).format = {
  fill: paleBlue,
  font: { bold: true, color: darkBlue, size: 10 },
  horizontalAlignment: "center",
  verticalAlignment: "center",
};
for (let index = 0; index < programmeRows.length; index += 1) {
  const row = index + 5;
  programme.getRange(`D${row}`).format = {
    fill: programmeRows[index][3] === "In progress" ? amber : grey,
    font: { bold: true, color: text, size: 9 },
    horizontalAlignment: "center",
    verticalAlignment: "center",
  };
}
programme.freezePanes.freezeRows(4);

setTitle(
  standards,
  "A1:D1",
  "Standards status and implementation boundary",
  "Licensed standards remain the equation and clause authority; this sheet records routing and disclosure decisions.",
);
standards.getRange(`A4:D${standardsRows.length + 4}`).values = [
  ["Family", "Sector label and scope", "Status disclosure", "v0.93 boundary"],
  ...standardsRows,
];
styleTable(
  standards,
  `A4:D${standardsRows.length + 4}`,
  "V093Standards",
  [
    ["A", 34],
    ["B", 57],
    ["C", 56],
    ["D", 64],
  ],
);
styleBody(standards, `A5:D${standardsRows.length + 4}`, 86);
standards.freezePanes.freezeRows(4);

setTitle(
  publication,
  "A1:D1",
  "Manual and report visual evidence",
  "Concrete v0.92 findings are paired with measurable v0.93 treatments; crack spacing is one example, not the scope boundary.",
);
publication.getRange(`A4:D${publicationRows.length + 4}`).values = [
  ["Surface", "Current page", "Observed issue", "Required treatment"],
  ...publicationRows,
];
styleTable(
  publication,
  `A4:D${publicationRows.length + 4}`,
  "V093PublicationQA",
  [
    ["A", 14],
    ["B", 18],
    ["C", 65],
    ["D", 70],
  ],
);
styleBody(publication, `A5:D${publicationRows.length + 4}`, 68);
publication.getRange(`A5:A${publicationRows.length + 4}`).format = {
  fill: paleBlue,
  font: { bold: true, color: darkBlue, size: 9 },
  horizontalAlignment: "center",
  verticalAlignment: "top",
};
publication.freezePanes.freezeRows(4);

await fs.mkdir(previewDir, { recursive: true });
for (const sheetName of [
  "Read Me",
  "Decisions",
  "PR Programme",
  "Standards",
  "Publication QA",
]) {
  const preview = await workbook.render({
    sheetName,
    autoCrop: "all",
    scale: 1,
    format: "png",
  });
  const safeName = sheetName.toLowerCase().replaceAll(" ", "-");
  await fs.writeFile(
    path.join(previewDir, `${safeName}.png`),
    new Uint8Array(await preview.arrayBuffer()),
  );
}

const inspection = await workbook.inspect({
  kind: "workbook,sheet,table,formula",
  maxChars: 12000,
  tableMaxRows: 8,
  tableMaxCols: 8,
  tableMaxCellChars: 120,
});
const inspectionText = inspection.ndjson ?? JSON.stringify(inspection, null, 2);
await fs.writeFile(
  path.join(previewDir, "workbook-inspection.ndjson"),
  inspectionText,
  "utf8",
);

const output = await SpreadsheetFile.exportXlsx(workbook);
await output.save(outputPath);

console.log(`Workbook: ${outputPath}`);
console.log(`Canonical Markdown SHA-256: ${decisionsSha256}`);
console.log(`Previews: ${previewDir}`);
