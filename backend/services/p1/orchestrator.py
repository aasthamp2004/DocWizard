from backend.services.p1.for_planning import generate_document_sections
from backend.services.p1.for_questions import generate_questions
from backend.services.p1.for_generation import generate_document


class DocumentOrchestrator:

    def plan(self, category, document_type):
        return generate_document_sections(category, document_type)

    def ask_questions(self, sections):
        return generate_questions(sections)

    def generate(self, document_type, answers):
        return generate_document(document_type, answers)