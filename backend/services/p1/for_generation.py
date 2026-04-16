import json
from backend.services.langchain import llm

from datetime import datetime, timezone, timedelta

def current_ist() -> str:
    IST = timezone(timedelta(hours=5, minutes=30))
    return datetime.now(IST).strftime("Current date and time (IST): %d %b %Y, %I:%M %p")



def generate_document_sections(title, sections, user_answers, show_headings=True):

    # Separate filled answers from empty ones so LLM knows what was provided
    filled = {q: a for q, a in user_answers.items() if str(a).strip()}

    # Prose-flow instruction for letter/memo/email type docs
    if show_headings:
        structure_instruction = (
            "Return strictly valid JSON where each key is a section name and "
            "the value is the full professional content for that section.\n"
            "Each section should be 2-5 sentences minimum with substance and detail."
        )
        format_note = ""
    else:
        structure_instruction = (
            "This is a LETTER / MEMO / EMAIL — it must read as flowing, continuous prose.\n"
            "Do NOT write section headings, titles, or labels inside the content values.\n"
            "Each JSON key represents a logical part of the document (e.g. Salutation, Body).\n"
            "The key names will NOT be shown to the reader — only the content values will.\n"
            "Write the content as it would appear in a real letter:\n"
            "  - Salutation: just the greeting line, e.g. 'Dear Mr. Smith,'\n"
            "  - Opening: first paragraph — context/purpose\n"
            "  - Body: main content paragraphs, naturally flowing\n"
            "  - Closing: sign-off paragraph\n"
            "  - Signature: closing line, e.g. 'Yours sincerely,\\n[Name]\\n[Designation]'\n"
            "Do not prefix any section value with the section name or a colon."
        )
        format_note = (
            "\nCRITICAL: This document will be rendered WITHOUT section headings. "
            "Each content value must stand alone as natural prose — no labels, no titles inside values."
        )

    prompt = f"""
You are a professional document writer with deep expertise across business, legal, technical, and operational domains.
{current_ist}

Document Title: {title}
Sections to write: {sections}

User-provided context:
{json.dumps(filled, indent=2) if filled else "No specific inputs provided."}

Instructions:
1. Write detailed, professional content for EVERY section listed above.
2. For sections where the user provided context, incorporate their input naturally.
3. For sections where NO input was provided, generate realistic, high-quality professional content
   appropriate for a "{title}" document — do NOT write "No content provided" or leave sections empty.
4. Use industry-standard language and structure.
5. For documents like employee handbook, make the content detailed in paragraphs or points or any relevant format and the entire document should be of 15-20 pages.
6. Always write dates in dd/mm/yyyy format (e.g. 22/12/2025, not 22/12/25 or 12/22/2025).
7. {structure_instruction}{format_note}

Return strictly valid JSON with this exact structure:
{{
  "Section Name": "Full generated content here as a string",
  "Another Section": "Full generated content here"
}}

No explanation. No markdown. Only JSON.
"""

    prompt = prompt.replace("{current_ist}", current_ist())
    response = llm.invoke(prompt)
    raw = response.content.strip()

    # Strip markdown fences if present
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    raw = raw.strip()

    result = json.loads(raw)

    # Safety net: replace any empty/placeholder values with a retry
    empty_keys = [k for k, v in result.items() if not str(v).strip()
                  or str(v).lower() in ("no content provided.", "no content provided", "n/a", "")]

    if empty_keys:
        retry_prompt = f"""
You are a professional document writer.
Document: {title}

Write content for these specific sections: {empty_keys}
Generate realistic, professional content for each — do not leave anything empty.
{"Do NOT include section headings inside the content values." if not show_headings else ""}

Return strictly valid JSON:
{{
  "Section Name": "Content here"
}}
No explanation. No markdown. Only JSON.
"""
        retry_response = llm.invoke(retry_prompt)
        retry_raw = retry_response.content.strip()
        if retry_raw.startswith("```"):
            retry_raw = retry_raw.split("```")[1]
            if retry_raw.startswith("json"):
                retry_raw = retry_raw[4:]
        try:
            retry_result = json.loads(retry_raw.strip())
            result.update(retry_result)
        except Exception:
            pass

    return result