"""
excel_generator_agent.py
-------------------------
Generates structured tabular data for Excel-type documents:
balance sheets, P&L statements, cash flow statements, schedules, etc.

Returns a structured dict that the frontend can render as tables
and export to .xlsx with proper formatting.
"""

import json
from backend.services.langchain import llm


# Document types that should always be treated as tabular
TABULAR_DOCUMENT_TYPES = {
    "balance sheet", "profit and loss", "p&l", "income statement",
    "cash flow statement", "cash flow", "trial balance",
    "depreciation schedule", "amortization schedule", "loan schedule",
    "budget", "financial forecast", "projection", "revenue forecast",
    "expense report", "cost breakdown", "payroll schedule",
    "inventory schedule", "fixed asset schedule", "tax schedule",
    "accounts receivable", "accounts payable", "aging report",
    "kpi dashboard", "sales report", "financial summary",
}


def is_tabular_document(title: str) -> bool:
    """Check if a document title suggests tabular/Excel format."""
    title_lower = title.lower()
    return any(keyword in title_lower for keyword in TABULAR_DOCUMENT_TYPES)


def generate_excel_sections(title: str, sections: list, user_answers: dict) -> dict:
    """
    Generate structured tabular data for each section.

    Returns:
    {
      "doc_type": "excel",
      "title": "...",
      "sheets": [
        {
          "sheet_name": "Balance Sheet",
          "headers": ["Particulars", "2023 (₹)", "2024 (₹)"],
          "rows": [
            ["ASSETS", "", ""],
            ["Current Assets", "", ""],
            ["Cash and Bank", "150000", "200000"],
            ...
          ],
          "totals_rows": [2, 7],       // row indices that should be styled as totals
          "header_rows": [0, 1],       // row indices that are section headers (bold, colored)
          "notes": "..."               // optional notes for this sheet
        }
      ]
    }
    """

    prompt = f"""
You are a professional financial analyst and document generator.

Document Title: {title}
Sections / Sheets required: {sections}

User Provided Information:
{json.dumps(user_answers, indent=2)}

Generate structured tabular data for a professional Excel document.

Rules:
1. Each section becomes one sheet/table
2. Every table must have clear column headers
3. Include subtotals and totals rows where appropriate
4. Use proper financial formatting conventions
5. If user didn't provide specific numbers, use realistic placeholder values
6. Group rows logically (Assets → Current Assets → items, then Non-Current Assets → items)
7. Mark which rows are headers/category rows vs data rows vs total rows
8. Always write dates in dd/mm/yyyy format (e.g. 22/12/2025, not 22/12/25 or 12/22/2025)

Return STRICTLY valid JSON in this exact format:
{{
  "sheets": [
    {{
      "sheet_name": "Section Name",
      "description": "Brief description of this sheet",
      "headers": ["Column 1", "Column 2", "Column 3"],
      "rows": [
        ["Row Label", "Value 1", "Value 2"],
        ["Another Row", "Value 1", "Value 2"]
      ],
      "header_rows": [0],
      "totals_rows": [5],
      "notes": "Any important notes about this sheet"
    }}
  ]
}}

No explanation. No markdown. Only valid JSON.
"""

    response = llm.invoke(prompt)
    raw = response.content.strip()

    # Clean markdown fences if present
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    raw = raw.strip()

    parsed = json.loads(raw)

    # Return clean structure — no doc_type key needed downstream
    return {
        "title": title,
        **parsed
    }


def _auto_detect_row_types(rows: list) -> tuple:
    """
    Auto-detect which rows are section headers vs totals
    based on content patterns — used as fallback when LLM omits them.
    """
    header_rows = []
    totals_rows = []
    total_keywords = {"total", "subtotal", "sub-total", "grand total", "net", "sum"}
    header_keywords = {"assets", "liabilities", "equity", "income", "expenses",
                       "revenue", "current", "non-current", "operating", "financing"}

    for i, row in enumerate(rows):
        if not row:
            continue
        first_cell = str(row[0]).lower().strip()
        # Rows where all value columns are empty = section header
        value_cells = [str(c).strip() for c in row[1:]]
        all_empty = all(c in ("", "-", "–", "0") for c in value_cells)

        if all_empty and any(kw in first_cell for kw in header_keywords):
            header_rows.append(i)
        elif any(kw in first_cell for kw in total_keywords):
            totals_rows.append(i)

    return header_rows, totals_rows


def refine_excel_section(sheet_name: str, current_data: dict, feedback: str) -> dict:
    """
    Refine a specific sheet's tabular data based on user feedback.
    Passes full current structure to LLM so row indices stay correct.
    """
    current_rows      = current_data.get("rows", [])
    current_headers   = current_data.get("headers", [])
    current_h_rows    = current_data.get("header_rows", [])
    current_t_rows    = current_data.get("totals_rows", [])

    # Build a column map string so LLM knows exactly which column index = which header
    col_map = " | ".join([f"col[{i}] = '{h}'" for i, h in enumerate(current_headers)])

    # Build annotated rows so LLM can reference by row label + column name
    annotated_rows = {}
    for i, row in enumerate(current_rows):
        row_dict = {}
        for j, cell in enumerate(row):
            header = current_headers[j] if j < len(current_headers) else f"col_{j}"
            row_dict[header] = cell
        annotated_rows[i] = row_dict

    prompt = f"""
You are a professional financial analyst editing a spreadsheet table.

Sheet Name: {sheet_name}

Column mapping: {col_map}

CURRENT TABLE — each row shown as {{column_name: value}}:
{json.dumps(annotated_rows, indent=2)}

Current header_rows (section label rows with no values): {current_h_rows}
Current totals_rows (subtotal/total rows): {current_t_rows}

User Feedback: "{feedback}"

CRITICAL RULES:
1. "update X to 500000" means: find the ROW where col[0] contains "X" and set its VALUE column to 500000
2. "update description of X as Y" means: find the ROW where col[0]="X" and set its description/text column to Y
3. If user says "update non-current assets to 500000" — find rows UNDER the "Non-Current Assets" section header and update the SUBTOTAL row for that section to 500000 (NOT the section label row itself which has no value)
4. Apply ONLY what was asked — all other rows stay identical
5. If numeric values changed, recalculate any subtotal/total rows that sum those values
6. Return rows as arrays in original column order: {json.dumps(current_headers)}
7. header_rows = indices of pure section label rows (all value columns empty)
8. totals_rows = indices of rows whose col[0] contains "total", "subtotal", "net", "sum"
9. NEVER leave fewer rows than the input — output must have exactly {len(current_rows)} rows
10. Always write dates in dd/mm/yyyy format (e.g. 22/12/2025, not 22/12/25 or 12/22/2025)

Return STRICTLY valid JSON — rows must be arrays not objects:
{{
  "sheet_name": "{sheet_name}",
  "description": "One sentence: what was changed",
  "headers": {json.dumps(current_headers)},
  "rows": [["cell1", "cell2", "cell3"]],
  "header_rows": [],
  "totals_rows": [],
  "notes": ""
}}

No explanation. No markdown. Only JSON.
"""

    response = llm.invoke(prompt)
    raw = response.content.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    raw = raw.strip()

    result = json.loads(raw)

    # Safety net: if LLM returned empty header/totals indices, auto-detect them
    if not result.get("header_rows") and not result.get("totals_rows"):
        auto_h, auto_t = _auto_detect_row_types(result.get("rows", []))
        result["header_rows"] = auto_h
        result["totals_rows"] = auto_t

    return result