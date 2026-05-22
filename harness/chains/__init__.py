"""
LangChain/LangGraph chain layer for iterative RAG experimentation.

This module wraps the existing LlamaIndex retrieval infrastructure with
LangChain-idiomatic components so new RAG strategies can be composed
quickly and evaluated via LangSmith experiments.

Structure:
    retriever.py    — EMARetriever(BaseRetriever): LangChain adapter for LlamaIndex
    llms.py         — get_langchain_llm(tier_id): ChatModel factory from models.yaml
    simple_rag.py   — build_rag_chain(): LCEL chains (zero_shot / few_shot / cot_self)
    evaluators.py   — LangSmith evaluators wrapping harness/judge.py
    registry.py     — CHAIN_REGISTRY and get_chain() strategy factory
    agents/
        react.py    — LangGraph ReAct agent with EMA retrieval tools
        crag.py     — Corrective RAG: retrieve → grade → rewrite → retrieve → answer

Tracing:
    Set LANGCHAIN_TRACING_V2=true and LANGCHAIN_PROJECT=ema-nlp in
    ~/.myenvs/ema_nlp.env to automatically send all chain and agent
    traces to LangSmith. Without these vars the chains run normally
    but traces are not recorded.

Usage:
    from harness.chains.retriever import EMARetriever
    from harness.chains.llms import get_langchain_llm
    from harness.chains.simple_rag import build_rag_chain
    from harness.embed import build_index

    index = build_index(corpus_path, index_dir)
    retriever = EMARetriever(index=index, mode="hybrid", k=10)
    llm = get_langchain_llm("frontier")
    chain = build_rag_chain("zero_shot", retriever=retriever, llm=llm)
    result = chain.invoke({"question": "What is the AI limit for NDMA?"})
"""
