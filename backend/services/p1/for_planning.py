import os
import json
from dotenv import load_dotenv
from langchain_openai import AzureChatOpenAI

from datetime import datetime, timezone, timedelta

def current_ist() -> str:
    IST = timezone(timedelta(hours=5, minutes=30))
    return datetime.now(IST).strftime("Current date and time (IST): %d %b %Y, %I:%M %p")


load_dotenv()

llm = AzureChatOpenAI(
    api_key=os.getenv("AZURE_OPENAI_LLM_KEY"),
    azure_endpoint=os.getenv("AZURE_OPENAI_LLM_ENDPOINT"),
    api_version=os.getenv("AZURE_OPENAI_LLM_API_VERSION"),
    deployment_name=os.getenv("AZURE_OPENAI_LLM_DEPLOYMENT"),
    temperature=0.3
)

# Document types that should be generated as Excel/tabular format
TABULAR_KEYWORDS = [
    "balance sheet", "profit and loss", "p&l", "income statement",
    "cash flow", "trial balance", "depreciation schedule",
    "amortization schedule", "loan schedule", "budget", "forecast",
    "projection", "expense report", "cost breakdown", "payroll",
    "inventory", "fixed asset", "tax schedule", "accounts receivable",
    "accounts payable", "aging report", "kpi", "sales report",
    "financial summary", "schedule", "statement", "ledger",
]

# Document types that should NOT show section headings —
# these are continuous-flow prose docs where headings break the reading experience.
NO_HEADING_KEYWORDS = [
    "letter", "cover letter", "resignation letter", "offer letter",
    "appointment letter", "termination letter", "recommendation letter",
    "reference letter", "apology letter", "complaint letter",
    "thank you letter", "acknowledgement letter", "invitation letter",
    "follow up letter", "follow-up letter", "demand letter",
    "email", "memo", "memorandum", "note", "notice",
    "personal statement", "statement of purpose",
]


def detect_doc_format(title: str, sections: list) -> str:
    """
    Returns 'excel' if the document is tabular/financial,
    'word' otherwise.
    """
    combined = (title + " " + " ".join(sections)).lower()
    if any(kw in combined for kw in TABULAR_KEYWORDS):
        return "excel"
    return "word"


def detect_show_headings(title: str, doc_type: str) -> bool:
    """
    Returns False for letter/memo/email type docs where section
    headings should be hidden. True for all other doc types.
    """
    combined = (title + " " + (doc_type or "")).lower()
    return not any(kw in combined for kw in NO_HEADING_KEYWORDS)


DEPARTMENT_LIST = [
    "Business Development", "Finance", "Human Resources", "Legal",
    "Operations", "Marketing", "Sales", "IT", "Procurement",
    "Compliance", "Administration", "Strategy", "General"
]

# Recognised document types — LLM picks the closest match
DOC_TYPE_LIST = [
    "Policy", "Procedure", "SOP", "Proposal", "Business Plan",
    "Report", "Agreement", "Contract", "Letter", "Memo",
    "Notice", "Email", "Invoice", "Quotation", "Purchase Order",
    "Job Description", "Offer Letter", "Resignation Letter",
    "Appraisal", "Minutes", "Agenda", "Presentation", "Scope of Work",
    "NDA", "MOU", "Terms and Conditions", "Compliance Document",
    "Project Plan", "Risk Assessment", "Budget", "Financial Statement",
    "General"
]


def plan_document(user_prompt: str) -> dict:
    dept_options = ", ".join(f'"{d}"' for d in DEPARTMENT_LIST)
    type_options = ", ".join(f'"{t}"' for t in DOC_TYPE_LIST)
    prompt = f"""
You are a professional document architect.
{current_ist}

User Request:
{user_prompt}

Determine:
1. Proper document title
2. Professional sections commonly used for this document type
3. Whether this document is best represented as:
   - "excel" (tabular data: financial statements, schedules, budgets, reports with rows/columns)
   - "word" (prose document: SOPs, business plans, policies, proposals, letters, emails)
4. The department this document belongs to. Choose exactly one from:
   [{dept_options}]
5. The document type. Choose the single closest match from:
   [{type_options}]
   Examples:
     "Write a refund policy" → "Policy"
     "Draft a business proposal" → "Proposal"
     "Resignation letter" → "Resignation Letter"
     "Vendor NDA" → "NDA"
     "Q3 sales report" → "Report"
     "Employee onboarding SOP" → "SOP"
     "Balance sheet FY2024" → "Financial Statement"
     If nothing fits exactly, use "General"
6. Whether section headings should be shown in the final document.
   Set "show_headings" to false for:
   - Any letter (cover letter, offer letter, resignation letter, recommendation letter, etc.)
   - Emails, memos, notices, personal statements
   These documents flow as continuous prose — section titles would look unprofessional.
   Set "show_headings" to true for:
   - SOPs, business plans, reports, policies, proposals, contracts, agreements, etc.

Return strictly valid JSON:

{{
  "title": "Document Title",
  "sections": ["Section 1", "Section 2"],
  "doc_format": "word",
  "department": "Finance",
  "doc_type": "Policy",
  "show_headings": true
}}

For financial documents (balance sheet, P&L, cash flow, schedules, budgets):
  → always use "excel"
For narrative documents (SOP, business plan, policy, proposal):
  → always use "word", show_headings: true
For letters, emails, memos:
  → always use "word", show_headings: false
  → sections should be logical parts of the letter, e.g.:
     ["Salutation", "Opening", "Body", "Closing", "Signature"]
     but these will NOT be printed as visible headings

Department mapping examples:
  Business Plan, Proposal, Market Analysis → Business Development
  Balance Sheet, Budget, Cash Flow → Finance
  Onboarding, Policy, Payroll → Human Resources
  Contract, SOP, Compliance → Legal or Operations
  Campaign, Brand Guide → Marketing
  Letter, Memo, Notice → Administration or relevant dept

No explanation. No markdown. Only JSON.
"""

    prompt = prompt.replace("{current_ist}", current_ist())
    response = llm.invoke(prompt).content.strip()

    # Clean markdown fences
    if response.startswith("```"):
        response = response.split("```")[1]
        if response.startswith("json"):
            response = response[4:]
    response = response.strip()

    result = json.loads(response)

    # Safety net: if LLM didn't return doc_format, detect it ourselves
    if "doc_format" not in result:
        result["doc_format"] = detect_doc_format(
            result.get("title", ""),
            result.get("sections", [])
        )

    # Safety net: default department if missing
    if "department" not in result or not result["department"]:
        result["department"] = "General"

    # Safety net: default doc_type if missing or not in our list
    if "doc_type" not in result or not result["doc_type"]:
        result["doc_type"] = "General"
    elif result["doc_type"] not in DOC_TYPE_LIST:
        # LLM returned something close but not exact — keep it (it's still useful)
        pass

    # Safety net: if show_headings missing, infer from title + doc_type
    if "show_headings" not in result:
        result["show_headings"] = detect_show_headings(
            result.get("title", ""),
            result.get("doc_type", "")
        )

    return result