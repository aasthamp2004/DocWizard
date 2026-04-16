"""
eval_service.py
----------------
RAGAS-based evaluation runner configured to use Azure OpenAI
instead of the default OpenAI API.

Evaluates RAG pipeline quality across:
  - faithfulness      (is the answer grounded in context?)
  - answer_relevancy  (does the answer address the question?)
  - context_precision (are retrieved chunks relevant?)
"""

import os
import logging
from dotenv import load_dotenv

load_dotenv()
log = logging.getLogger(__name__)


def _get_ragas_llm():
    """Return a LangChain AzureChatOpenAI instance for RAGAS to use."""
    from langchain_openai import AzureChatOpenAI
    return AzureChatOpenAI(
        api_key         = os.getenv("AZURE_OPENAI_LLM_KEY"),
        azure_endpoint  = os.getenv("AZURE_OPENAI_LLM_ENDPOINT"),
        api_version     = os.getenv("AZURE_OPENAI_LLM_API_VERSION"),
        azure_deployment= os.getenv("AZURE_OPENAI_LLM_DEPLOYMENT"),
        temperature     = 0,
    )


def _get_ragas_embeddings():
    """Return a LangChain AzureOpenAIEmbeddings instance for RAGAS to use."""
    from langchain_openai import AzureOpenAIEmbeddings
    api_key  = (os.getenv("AZURE_OPENAI_EMB_KEY")   or "").strip() \
            or (os.getenv("AZURE_OPENAI_LLM_KEY")    or "").strip()
    endpoint = (os.getenv("AZURE_OPENAI_EMB_ENDPOINT") or "").strip() \
            or (os.getenv("AZURE_OPENAI_LLM_ENDPOINT")  or "").strip()
    version  = (os.getenv("AZURE_OPENAI_EMB_API_VERSION") or "").strip() \
            or (os.getenv("AZURE_OPENAI_LLM_API_VERSION")  or "").strip() \
            or "2024-02-01"
    deployment = (os.getenv("AZURE_OPENAI_EMB_DEPLOYMENT") or "").strip() \
              or "text-embedding-3-large"
    return AzureOpenAIEmbeddings(
        api_key         = api_key,
        azure_endpoint  = endpoint,
        api_version     = version,
        azure_deployment= deployment,
    )


def run_evaluation(questions: list[str], config: dict) -> dict:
    """
    Run RAGAS evaluation on a list of questions using Azure OpenAI.

    config: {
        top_k:      int   — chunks to retrieve per question (default 5)
        filters:    dict  — metadata filters to apply
        run_name:   str   — label for this run
    }

    Returns:
    {
        run_id:   int,
        summary:  { faithfulness, answer_relevancy, context_precision },
        results:  [ per-question data ],
    }
    """
    try:
        from ragas import evaluate
        from ragas.metrics import (
            faithfulness,
            answer_relevancy,
        )
        from datasets import Dataset
    except ImportError:
        raise ImportError(
            "RAGAS is not installed. Run: pip install ragas datasets"
        )

    from backend.services.p2.for_qa import ask
    from backend.chroma_db import save_eval_run

    top_k   = config.get("top_k", 5)
    filters = config.get("filters")

    # Configure RAGAS to use Azure OpenAI
    azure_llm   = _get_ragas_llm()
    azure_emb   = _get_ragas_embeddings()

    for metric in [faithfulness, answer_relevancy]:
        metric.llm        = azure_llm
        metric.embeddings = azure_emb

    # Build dataset rows
    data_rows = {
        "question": [],
        "answer":   [],
        "contexts": [],
    }
    per_question = []

    for q in questions:
        result   = ask(q, top_k=top_k, filters=filters)
        answer   = result["answer"]
        sources  = result["sources"]
        contexts = [s["chunk_text"] for s in sources]

        data_rows["question"].append(q)
        data_rows["answer"].append(answer)
        data_rows["contexts"].append(contexts)

        per_question.append({
            "question": q,
            "answer":   answer,
            "sources":  [
                {
                    "doc_title":    s["doc_title"],
                    "section_name": s["section_name"],
                    "score":        s["score"],
                    "notion_url":   s.get("notion_url", ""),
                }
                for s in sources
            ],
        })

    dataset = Dataset.from_dict(data_rows)

    # Run RAGAS evaluation
    score = evaluate(
        dataset,
        metrics=[faithfulness, answer_relevancy],
        llm=azure_llm,
        embeddings=azure_emb,
    )

    def _to_float(val) -> float:
        """RAGAS may return a float or a list of floats — handle both."""
        if isinstance(val, (int, float)):
            return float(val)
        if isinstance(val, list):
            nums = [float(v) for v in val if v is not None]
            return sum(nums) / len(nums) if nums else 0.0
        try:
            return float(val)
        except Exception:
            return 0.0

    summary = {
        "faithfulness":     round(_to_float(score["faithfulness"]),     4),
        "answer_relevancy": round(_to_float(score["answer_relevancy"]), 4),
    }

    # Persist to SQLite
    run_id = save_eval_run(
        run_name = config.get("run_name", "Unnamed Run"),
        config   = config,
        results  = per_question,
        summary  = summary,
    )

    return {
        "run_id":  run_id,
        "summary": summary,
        "results": per_question,
    }