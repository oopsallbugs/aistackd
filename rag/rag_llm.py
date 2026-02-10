#!/usr/bin/env python3
import requests
import json
import sys

def rag_llm_query(collection, question, k=3, max_tokens=4096):
    # Thinking / reasoning models often need 2000+ tokens for good reasoning + answer to be formatted correctly.
    # As they do step-by-step reasoning before final answer, responses could be cut off if max_tokens is too low.
    """
    Query RAG and get response from GLM model.
    
    Args:
        collection: RAG collection name
        question: User question
        k: Number of RAG results to include
        max_tokens: Maximum tokens for LLM response
    """
    # Step 1: Search RAG
    rag_url = "http://127.0.0.1:8081/search"
    rag_data = {
        "collection": collection,
        "query": question,
        "k": k
    }
    
    print(f"🔍 Searching '{collection}' for: {question}")
    rag_response = requests.post(rag_url, json=rag_data)
    
    if rag_response.status_code != 200:
        print(f"❌ RAG search failed: {rag_response.text}")
        return None
    
    results = rag_response.json()
    
    if not results:
        print("❌ No results found in RAG collection")
        return None
    
    print(f"📄 Found {len(results)} relevant chunks")
    print("-" * 60)
    
    # Build context
    context_parts = []
    sources = []
    
    for i, result in enumerate(results[:k]):
        print(f"Result {i+1} (similarity: {result['similarity']:.4f}):")
        print(f"📁 File: {result['filename']}")
        preview = result['text'][:200].replace('\n', ' ')
        print(f"📝 Content: {preview}...")
        print()
        
        context_parts.append(f"[Document {i+1} from {result['filename']}]:\n{result['text']}")
        sources.append(result['filename'])
    
    context = "\n\n".join(context_parts)
    
    # Step 2: Query LLM with enough tokens for reasoning
    llm_url = "http://127.0.0.1:8080/v1/chat/completions"
    
    # System prompt
    system_prompt = """You are a helpful assistant. Based on the provided documentation, 
answer the question directly and concisely. Focus on the information in the documents."""
    
    user_prompt = f"""Based on the following documentation:

{context}

Question: {question}

Provide a comprehensive answer based solely on the documentation above:"""
    
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt}
    ]
    
    # Thinking / reasoning models often need more tokens for good reasoning + answer to be formatted correctly.
    # Total tokens = prompt tokens + max_tokens
    # Set max_tokens high enough (2000+) for reasoning + answer
    llm_data = {
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": 0.7
    }
    
    print(f"🤖 Generating answer (max_tokens: {max_tokens})...")
    print("-" * 60)
    
    try:
        llm_response = requests.post(llm_url, json=llm_data, timeout=60)
    except requests.exceptions.Timeout:
        print("❌ LLM request timed out")
        return None
    
    if llm_response.status_code != 200:
        print(f"❌ LLM query failed: {llm_response.text}")
        return None
    
    result = llm_response.json()
    
    choice = result.get("choices", [{}])[0]
    message = choice.get("message", {})
    
    # GLM puts answer in 'content', reasoning in 'reasoning_content'
    answer = message.get("content", "").strip()
    reasoning = message.get("reasoning_content", "")
    
    if not answer and reasoning:
        print("⚠️  No direct answer in 'content', extracting from reasoning...")
        # Try to get the last substantive paragraph from reasoning
        lines = reasoning.split('\n')
        # Filter out analysis markers
        answer_lines = []
        for line in reversed(lines):
            line = line.strip()
            if line and not any(marker in line.lower() for marker in 
                              ['analysis:', 'step', '1.', '2.', '3.', '4.', '5.', 
                               'drafting', 'refine', 'self-correction', '**']):
                if len(line) > 20:  # Substantive line
                    answer_lines.insert(0, line)
                if len(' '.join(answer_lines)) > 100:  # Got enough
                    break
        
        answer = ' '.join(answer_lines)
    
    print("💡 ANSWER:")
    print("-" * 60)
    print(answer)
    print("-" * 60)
    
    # Show stats
    usage = result.get("usage", {})
    print(f"📊 Stats:")
    print(f"  - Prompt tokens: {usage.get('prompt_tokens', 'N/A')}")
    print(f"  - Completion tokens: {usage.get('completion_tokens', 'N/A')}")
    print(f"  - Total tokens: {usage.get('total_tokens', 'N/A')}")
    print(f"  - Finish reason: {choice.get('finish_reason', 'N/A')}")
    
    # Show sources
    print(f"\n📚 Sources used:")
    for i, source in enumerate(set(sources), 1):
        print(f"  {i}. {source}")
    
    return {
        "answer": answer,
        "reasoning": reasoning[:500] + "..." if len(reasoning) > 500 else reasoning,
        "sources": list(set(sources)),
        "stats": {
            "prompt_tokens": usage.get("prompt_tokens"),
            "completion_tokens": usage.get("completion_tokens"),
            "total_tokens": usage.get("total_tokens"),
            "rag_results": len(results)
        }
    }

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python3 rag_llm.py <collection> <question>")
        print("Example: python3 rag_llm.py coding 'What is this project about?'")
        print("\nOptional environment variables:")
        print("  MAX_TOKENS=2000  # Set max tokens for GLM (default: 2000)")
        print("  K_RESULTS=3      # Number of RAG results (default: 3)")
        sys.exit(1)
    
    collection = sys.argv[1]
    question = " ".join(sys.argv[2:])
    
    # Get settings from environment or defaults
    import os
    max_tokens = int(os.getenv("MAX_TOKENS", "2000"))
    k_results = int(os.getenv("K_RESULTS", "3"))
    
    print(f"⚙️  Settings: max_tokens={max_tokens}, k_results={k_results}")
    print()
    
    result = rag_llm_query(collection, question, k=k_results, max_tokens=max_tokens)