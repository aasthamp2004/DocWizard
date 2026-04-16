from backend.services.langchain import llm


def refine_section(section_name, original_text, user_feedback):

    prompt = f"""
You are a professional editor.

Section: {section_name}

Original Content:
{original_text}

User Feedback:
{user_feedback}

Rewrite this section incorporating the feedback.
Important: Always read and convert dates in dd/mm/yyyy format (e.g. 22/12/2025 should be converted to 22nd December 2025) and ensure the rewritten section is clear, concise, and well-structured.
Return only the improved section text.
"""

    response = llm.invoke(prompt)
    return response.content