import os
from dotenv import load_dotenv
from langchain_openai import AzureChatOpenAI

load_dotenv()

# Azure LLM Setup
llm = AzureChatOpenAI(
    api_key=os.getenv("AZURE_OPENAI_LLM_KEY"),
    azure_endpoint=os.getenv("AZURE_OPENAI_LLM_ENDPOINT"),
    api_version=os.getenv("AZURE_OPENAI_LLM_API_VERSION"),
    azure_deployment=os.getenv("AZURE_OPENAI_LLM_DEPLOYMENT"),
    temperature=0.7
)

# from langchain_core.prompts import ChatPromptTemplate
# from langchain_core.output_parsers import StrOutputParser

# # Prompt Template
# prompt = ChatPromptTemplate.from_messages([
#     ("system", "You are a professional enterprise document generator."),
#     ("human", """
#     Industry: {category}
#     Document Type: {document_type}

#     Structured Input:
#     {content}

#     Generate a well-formatted, professional, structured document.
#     Use headings and proper formatting.
#     """)
# ])

# # Output Parser
# parser = StrOutputParser()

# # LCEL Chain (LangChain Expression Language)
# chain = prompt | llm | parser


# def generate_document(category: str, document_type: str, content: dict):
#     return chain.invoke({
#         "category": category,
#         "document_type": document_type,
#         "content": content
#     })