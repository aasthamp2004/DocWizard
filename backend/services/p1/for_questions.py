import json
from backend.services.p1.for_planning import llm


def generate_questions(title, sections):

    prompt = f"""
You are an intelligent business analyst.

Document Title:
{title}

Sections:
{sections}

Instructions:
1. For each section, generate important and relevant input questions required to write that section. Club 2 or more questions together if they are closely related to minimize the number of questions.
2. Number of questions may be anything but the questions must be relevant and important to write that section.
3. Generate only relevant questions for sections like signature or date and do not generate questions just for the sake of asking questions.
4. Number of questions depends on the complexity of the section and try to minimize the number of questions..

Return strict JSON format:

{{
  "Section Name": ["Question 1", "Question 2"]
}}

No explanation.
No markdown.
"""

    response = llm.invoke(prompt).content.strip()
    return json.loads(response)