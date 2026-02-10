#!/usr/bin/env python3
# rag_query.py

import requests
import json

def query_rag_llm(question, collection="coding", k=3, max_tokens=2000):
    """
    Complete RAG + LLM query in one function
    """
    # Step 1: Search RAG
    try:
        rag_response = requests.post(
            "http://127.0.0.1:8081/search",
            json={"collection": collection, "query": question, "k": k},
            timeout=10
        )
        rag_results = rag_response.json()
    except:
        rag_results = []
    
    # Step 2: Build context
    context_parts = []
    if rag_results:
        for i, item in enumerate(rag_results[:k]):
            context_parts.append(f"[Document {i+1}]: {item['text'][:300]}")
    context = "\n\n".join(context_parts) if context_parts else "No relevant documents found."
    
    # Step 3: Query LLM
    # More directive prompt
    prompt = f"""Based EXACTLY on these documents:

    {context}

    Question: {question}

    Provide a CONCISE answer focusing only on information in the documents.
    Do not repeat yourself. Do not add extra commentary."""
    
    try:
        llm_response = requests.post(
            "http://127.0.0.1:8080/v1/chat/completions",
            json={
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": max_tokens,
                "temperature": 0.7,
                "stop": ["\n\n###", "## Key Observation", "This is a great question"]  # Stop repetitive patterns
            },
            timeout=60
        )
        
        data = llm_response.json()
        
        if "choices" in data and data["choices"]:
            msg = data["choices"][0]["message"]
            content = msg.get("content", "").strip()
            reasoning = msg.get("reasoning_content", "").strip()
            
            return {
                "answer": content or reasoning[:500] + "..." if reasoning else "No response",
                "context": context[:500] + "..." if len(context) > 500 else context,
                "documents_used": len(rag_results[:k]),
                "tokens_used": data.get("usage", {}).get("total_tokens", 0)
            }
        else:
            return {"error": "No response from LLM", "raw": data}
            
    except Exception as e:
        return {"error": str(e)}

if __name__ == "__main__":
    # Test it
    result = query_rag_llm("What Python packages are needed for a RAG system?")
    print("Result:")
    print(json.dumps(result, indent=2))