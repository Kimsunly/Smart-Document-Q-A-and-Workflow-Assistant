#!/usr/bin/env python3
"""Test Ollama 3B model for improved answer quality"""

from src.phase2.rag.rag_service import generate_rag_answer
import os
from dotenv import load_dotenv

# Force .env reload
load_dotenv(override=True)

# Check model config
print(f"Configured Ollama Model: {os.getenv('OLLAMA_MODEL')}")
print(f"Ollama API URL: {os.getenv('OLLAMA_BASE_URL')}")

# Import and test RAG service

# Test with sample chunks
test_chunks = [
    {
        'text': 'Training opportunities are available through our online learning platform. Employees can access courses on leadership, technical skills, and professional development.',
        'doc_id': 'policy.pdf',
        'page': 2,
        'chunk_id': 1
    },
]

test_question = 'What training opportunities are available?'

print(f"\nTesting Ollama with question: \"{test_question}\"")
print("(This may take 30-60 seconds on first run as 3B model generates response...)")
result = generate_rag_answer(
    question=test_question,
    retrieved_chunks=test_chunks,
    rag_mode='ollama',
    timeout_sec=60  # Increase timeout for larger 3B model
)

print(f"\nResult:")
print(f"  Provider: {result.get('provider')}")
print(f"  Answer: {result.get('answer')}")
print(f"  Retrieved chunks: {len(result.get('retrieved_chunks', []))}")
if result.get('last_error'):
    print(f"  Error: {result.get('last_error')}")
