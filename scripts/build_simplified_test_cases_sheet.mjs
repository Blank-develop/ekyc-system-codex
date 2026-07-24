import fs from "node:fs/promises";
import path from "node:path";
import vm from "node:vm";
import { SpreadsheetFile, Workbook } from "@oai/artifact-tool";

const root = "/Users/chilanhouthnitvongkhay/Downloads/ekyc-system-codex";
const sourcePath = path.join(root, "scripts", "build_nist_ial2_test_cases_sheet.mjs");
const outputDir = path.join(root, "outputs", "simplified_test_cases");
const csvPath = path.join(outputDir, "phayaid_simplified_test_cases.csv");
const xlsxPath = path.join(outputDir, "phayaid_simplified_test_cases.xlsx");

const headers = [
  "Test Case ID",
  "Area",
  "Priority",
  "Test Type",
  "Test Scenario",
  "Test Data / Condition",
  "Expected Result",
  "Status",
  "Actual Result",
  "Tester",
  "Run Date",
  "Notes"
];

function extractRowsLiteral(source) {
  const start = source.indexOf("const rows = [");
  if (start < 0) throw new Error("Could not find rows literal in source test matrix.");

  const arrayStart = source.indexOf("[", start);
  let depth = 0;
  let inString = false;
  let quote = "";
  let escaped = false;

  for (let index = arrayStart; index < source.length; index += 1) {
    const char = source[index];
    if (inString) {
      if (escaped) {
        escaped = false;
      } else if (char === "\\") {
        escaped = true;
      } else if (char === quote) {
        inString = false;
        quote = "";
      }
      continue;
    }
    if (char === '"' || char === "'" || char === "`") {
      inString = true;
      quote = char;
      continue;
    }
    if (char === "[") depth += 1;
    if (char === "]") {
      depth -= 1;
      if (depth === 0) return source.slice(arrayStart, index + 1);
    }
  }
  throw new Error("Rows literal did not close.");
}

async function loadDetailedRows() {
  const source = await fs.readFile(sourcePath, "utf8");
  const literal = extractRowsLiteral(source);
  return vm.runInNewContext(literal);
}

function simplifyRow(row) {
  return [
    row[0],
    row[1],
    row[9],
    row[10],
    row[2],
    row[3] || row[4] || "",
    row[6],
    "Not Run",
    "",
    "",
    "",
    ""
  ];
}

function csvEscape(value) {
  const text = String(value ?? "");
  if (/[",\n]/.test(text)) return `"${text.replaceAll('"', '""')}"`;
  return text;
}

function toCsv(matrix) {
  return matrix.map((row) => row.map(csvEscape).join(",")).join("\n") + "\n";
}

function countBy(rows, index) {
  const counts = new Map();
  for (const row of rows) counts.set(row[index], (counts.get(row[index]) ?? 0) + 1);
  return [...counts.entries()];
}

function buildSummaryRows(rows) {
  return [
    ["PhayaID / LALIGENCE Simplified eKYC Test Cases"],
    ["Purpose", "Simple QA tracker focused on test scenario and expected result."],
    ["How to use", "Run each scenario, choose a Status, and fill Actual Result, Tester, Run Date, and Notes."],
    ["Total test cases", rows.length],
    [],
    ["By Area", "Count"],
    ...countBy(rows, 1),
    [],
    ["By Priority", "Count"],
    ...countBy(rows, 2)
  ];
}

async function main() {
  const detailedRows = await loadDetailedRows();
  const rows = detailedRows.map(simplifyRow);

  await fs.mkdir(outputDir, { recursive: true });
  await fs.writeFile(csvPath, toCsv([headers, ...rows]), "utf8");

  const workbook = Workbook.create();
  const summary = workbook.worksheets.add("Summary");
  const cases = workbook.worksheets.add("Test Cases");

  const summaryRows = buildSummaryRows(rows);
  summary.getRange(`A1:B${summaryRows.length}`).values = summaryRows.map((row) => [row[0] ?? null, row[1] ?? null]);
  cases.getRange(`A1:L${rows.length + 1}`).values = [headers, ...rows];

  summary.showGridLines = false;
  cases.showGridLines = false;
  summary.freezePanes.freezeRows(1);
  cases.freezePanes.freezeRows(1);
  cases.freezePanes.freezeColumns(1);

  summary.getRange("A1:B1").format = {
    fill: "#081632",
    font: { name: "Aptos", size: 16, color: "#FFFFFF", bold: true },
    verticalAlignment: "center"
  };
  summary.getRange("A1:B1").format.rowHeightPx = 36;
  summary.getRange(`A2:B${summaryRows.length}`).format = {
    font: { name: "Aptos", size: 10, color: "#081632" },
    wrapText: true,
    verticalAlignment: "top",
    borders: { preset: "inside", style: "thin", color: "#E5EAF3" }
  };
  summary.getRange("A6:B6").format = {
    fill: "#E7BF35",
    font: { name: "Aptos", size: 11, color: "#081632", bold: true },
    horizontalAlignment: "center"
  };
  summary.getRange("A17:B17").format = {
    fill: "#E7BF35",
    font: { name: "Aptos", size: 11, color: "#081632", bold: true },
    horizontalAlignment: "center"
  };
  summary.getRange("A:A").format.columnWidthPx = 220;
  summary.getRange("B:B").format.columnWidthPx = 560;

  cases.getRange("A1:L1").format = {
    fill: "#081632",
    font: { name: "Aptos", size: 10, color: "#FFFFFF", bold: true },
    horizontalAlignment: "center",
    verticalAlignment: "center",
    wrapText: true,
    borders: { preset: "outside", style: "thin", color: "#081632" }
  };
  cases.getRange("A1:L1").format.rowHeightPx = 40;
  cases.getRange(`A2:L${rows.length + 1}`).format = {
    font: { name: "Aptos", size: 10, color: "#081632" },
    verticalAlignment: "top",
    wrapText: true,
    borders: { preset: "inside", style: "thin", color: "#E5EAF3" }
  };
  cases.getRange(`A2:A${rows.length + 1}`).format = {
    fill: "#F8FAFF",
    font: { name: "Aptos", size: 10, color: "#081632", bold: true }
  };
  cases.getRange(`H2:H${rows.length + 1}`).dataValidation = {
    allowBlank: false,
    list: { inCellDropDown: true, source: ["Not Run", "Pass", "Fail", "Blocked", "Retest"] }
  };
  cases.getRange(`C2:C${rows.length + 1}`).conditionalFormats.add("containsText", {
    text: "Critical",
    format: { fill: "#FEE2E2", font: { color: "#991B1B", bold: true } }
  });
  cases.getRange(`C2:C${rows.length + 1}`).conditionalFormats.add("containsText", {
    text: "High",
    format: { fill: "#FEF3C7", font: { color: "#92400E", bold: true } }
  });
  cases.getRange(`C2:C${rows.length + 1}`).conditionalFormats.add("containsText", {
    text: "Medium",
    format: { fill: "#E0F2FE", font: { color: "#075985", bold: true } }
  });

  const widths = [94, 160, 96, 120, 300, 260, 360, 110, 250, 130, 120, 250];
  for (let index = 0; index < widths.length; index += 1) {
    const column = String.fromCharCode("A".charCodeAt(0) + index);
    cases.getRange(`${column}:${column}`).format.columnWidthPx = widths[index];
  }
  cases.getRange(`A2:L${rows.length + 1}`).format.rowHeightPx = 58;

  const output = await SpreadsheetFile.exportXlsx(workbook);
  await output.save(xlsxPath);

  console.log(JSON.stringify({ csvPath, xlsxPath, rows: rows.length }, null, 2));
}

await main();
