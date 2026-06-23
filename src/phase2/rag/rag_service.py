import os
import re
import time
import importlib
import json
from urllib import request, error
from typing import Any, Dict, List, Tuple

try:
    from dotenv import load_dotenv
    # Use values from local .env even if the shell already has stale values.
    load_dotenv(override=True)
except Exception:
    # Keep working even if python-dotenv is not installed.
    pass


def _build_context(chunks: List[Dict[str, Any]], max_chars: int = 3500) -> str:
    parts: List[str] = []
    used = 0
    for i, c in enumerate(chunks, start=1):
        source = c.get("source_name") or c.get("doc_id") or "unknown"
        chunk_id = c.get("chunk_id", "")
        page = c.get("page", "")
        text = (c.get("text") or "").strip()
        block = f"[Source {i}] source={source} page={page} chunk_id={chunk_id}\n{text}\n"
        if used + len(block) > max_chars:
            if not parts:
                # If the first chunk is too large, truncate it to fit max_chars
                overhead = len(block) - len(text) + 5
                truncated_text = text[:max(0, max_chars - overhead)]
                block = f"[Source {i}] source={source} page={page} chunk_id={chunk_id}\n{truncated_text}...\n"
                parts.append(block)
            break
        parts.append(block)
        used += len(block)
    return "\n".join(parts)



def build_grounding_prompt(question: str, chunks: List[Dict[str, Any]], max_chars: int = 3500) -> Tuple[str, str]:
    context = _build_context(chunks, max_chars=max_chars)
    prompt = _build_answer_prompt(question, context)
    return prompt, context


def _is_overview_question(question: str) -> bool:
    q = (question or "").strip().lower()
    if not q:
        return False

    patterns = (
        r"\bwhat(?:'s| is) this (?:pdf|document|file) about\b",
        r"\bwhat does this (?:pdf|document|file) contain\b",
        r"\bwhat is it about\b",
        r"\btell me about\b",
        r"\boverview\b",
        r"\bsummary\b",
        r"\bdescribe\b",
        r"\bmain points?\b",
        r"\brequirements?\b",
        r"\bassignment\b",
        r"\bfull detail\b",
        r"\bfull info\b",
        r"\bdetail(?:s)? about\b",
        r"\bcomprehensive\b",
        r"\bexplain the whole\b",
        r"\bsummarize\b",
        r"\bsummarise\b",
        r"\bwhat is in\b",
    )
    return any(re.search(pattern, q) for pattern in patterns)


def _build_answer_prompt(question: str, context: str) -> str:
    style_guide = (
        "Format the response in clean Markdown. Keep it concise, professional, and easy to review.\n"
        "Use short sections and bullets instead of long paragraphs.\n"
        "If the answer is uncertain, say so briefly.\n"
    )

    if _is_overview_question(question):
        return (
            "You are a professional document analyst. The user is asking for a summary or overview of the document.\n"
            "The context below is the uploaded document content. Do not say that no context or document was provided.\n"
            "Use the provided context as the primary source. If needed, you may supplement it with your own general knowledge to define terms or add context.\n"
            f"{style_guide}\n"
            "Use this structure:\n"
            "## Summary\n"
            "- 1 short sentence naming the document topic if visible.\n\n"
            "## Key points\n"
            "- 3 to 5 concise bullets covering the main purpose, tasks, requirements, deadlines, tools, or topics.\n\n"
            "## What the user should do\n"
            "- Explain the next steps in simple language, supplemented with your knowledge if helpful.\n\n"
            "## Notes\n"
            "- Mention anything that is unclear or not explicitly stated in the document.\n\n"
            f"Question:\n{question}\n\n"
            f"Context:\n{context}\n\n"
            "Answer:"
        )

    return (
        "You are a professional document QA assistant. Use the provided context as your primary source of truth.\n"
        "The context below is the uploaded document content.\n"
        "If the user asks for explanations, tutorials, specific CLI commands, or details on how to perform/verify tasks mentioned in the document but not fully explained in the text, you SHOULD supplement the answer using your own general knowledge to guide them on how to do it. Clearly state when you are adding general knowledge steps.\n"
        f"{style_guide}\n"
        "Answer the user's question directly and professionally.\n"
        "Use this structure:\n"
        "## Answer\n"
        "- A short direct response based on the document and your general knowledge.\n\n"
        "## Evidence from Document\n"
        "- What the document explicitly states about this (if anything).\n\n"
        "## Next step & How-To\n"
        "- Provide actionable steps, commands, or explanations (using your general knowledge if not in the document) to guide the user on how to do it.\n\n"
        f"Question:\n{question}\n\n"
        f"Context:\n{context}\n\n"
        "Answer:"
    )


def _estimate_tokens(text: str) -> int:
    # Lightweight estimate good enough for demo/cost logging.
    return max(1, int(len(text) / 4))


def _get_fallback_min_score(default_value: float = 0.05) -> float:
    raw = os.getenv("RAG_FALLBACK_MIN_SCORE", str(default_value)).strip()
    try:
        value = float(raw)
    except Exception:
        value = default_value
    # Keep this bounded so accidental values do not break behavior.
    return max(0.0, min(1.0, value))


def _mask_api_keys(text: str) -> str:
    if not text:
        return text
    text = re.sub(r"sk-[A-Za-z0-9_\-]{16,}", "sk-****************", text)
    text = re.sub(r"[A-Za-z0-9_\-]{40,}", "[REDACTED]", text)
    return text


def _get_openai_client(timeout_sec: int):
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is not configured")

    try:
        openai_mod = importlib.import_module("openai")
        OpenAI = getattr(openai_mod, "OpenAI")
    except Exception as e:
        raise RuntimeError(f"OpenAI SDK unavailable: {e}")

    return OpenAI(api_key=api_key, timeout=timeout_sec)


def _extract_openai_text(response: Any) -> str:
    """Support both Responses API and older chat completions response objects."""
    if response is None:
        return ""

    txt = getattr(response, "output_text", None)
    if isinstance(txt, str) and txt.strip():
        return txt.strip()

    try:
        output = getattr(response, "output", None) or []
        pieces: List[str] = []
        for item in output:
            content = getattr(item, "content", None) or []
            for part in content:
                part_text = getattr(part, "text", None)
                if isinstance(part_text, str) and part_text.strip():
                    pieces.append(part_text.strip())
        if pieces:
            return "\n".join(pieces).strip()
    except Exception:
        pass

    try:
        choices = getattr(response, "choices", None) or []
        if choices:
            msg = getattr(choices[0], "message", None)
            content = getattr(msg, "content", None)
            if isinstance(content, str):
                return content.strip()
    except Exception:
        pass

    return ""


def _try_openai_chat(prompt: str, timeout_sec: int) -> str:
    model = os.getenv("RAG_MODEL", "gpt-4o-mini").strip() or "gpt-4o-mini"
    client = _get_openai_client(timeout_sec)

    # Preferred modern API.
    try:
        resp = client.responses.create(
            model=model,
            input=prompt,
        )
        txt = _extract_openai_text(resp)
        if txt:
            return txt
    except Exception:
        # Fallback to the older chat-completions API for older SDKs/accounts.
        pass

    resp = client.chat.completions.create(
        model=model,
        temperature=0.0,
        messages=[
            {"role": "system", "content": "Answer only from context. If missing, output I don't know."},
            {"role": "user", "content": prompt},
        ],
    )
    txt = _extract_openai_text(resp)
    return txt or "I don't know"


def test_openai_connection(timeout_sec: int = 10) -> Dict[str, Any]:
    """Small connectivity test used by the UI diagnostic."""
    model = os.getenv("RAG_MODEL", "gpt-4o-mini").strip() or "gpt-4o-mini"
    client = _get_openai_client(timeout_sec)
    try:
        resp = client.responses.create(
            model=model,
            input="Say hi in one short sentence.",
        )
        return {
            "ok": True,
            "model": model,
            "text": _extract_openai_text(resp),
            "error": "",
        }
    except Exception as e:
        return {
            "ok": False,
            "model": model,
            "text": "",
            "error": _mask_api_keys(str(e)),
        }


_STOP_WORDS = {
    "the", "a", "an", "is", "are", "was", "were", "to", "for", "of", "in", "on", "at", "by",
    "and", "or", "with", "from", "that", "this", "it", "as", "be", "how", "what", "when", "where",
    "who", "why", "which", "do", "does", "did", "can", "could", "should", "would", "my", "your",
}


def _tokenize(text: str) -> List[str]:
    return re.findall(r"[a-z0-9]+", (text or "").lower())


def _split_sentences(text: str) -> List[str]:
    cleaned = (text or "").strip()
    if not cleaned:
        return []
    parts = re.split(r"(?<=[.!?])\s+|\n+", cleaned)
    return [p.strip() for p in parts if p and p.strip()]


def _sentence_match_score(question: str, sentence: str, chunk_score: float) -> float:
    q_tokens = [t for t in _tokenize(question) if t not in _STOP_WORDS]
    s_tokens = [t for t in _tokenize(sentence) if t not in _STOP_WORDS]

    if not q_tokens or not s_tokens:
        return 0.0

    q_set = set(q_tokens)
    s_set = set(s_tokens)
    overlap = q_set.intersection(s_set)

    # Strong requirement: sentence must have substantial keyword overlap with question.
    overlap_ratio = len(overlap) / max(1, len(q_set))

    # If question keywords (like "what", "requirements") barely match, score should be low.
    # Require at least 30% of question keywords to be in the sentence.
    if overlap_ratio < 0.25:
        return 0.0

    density = len(overlap) / max(1, len(s_set))

    # Weighted: query overlap is most important, density secondary.
    return overlap_ratio * 0.75 + density * 0.20 + float(chunk_score) * 0.05


def _extractive_fallback_answer(question: str, chunks: List[Dict[str, Any]], min_score: float = 0.05) -> str:
    if not chunks:
        return "I don't know"

    best = chunks[0]
    best_score = float(best.get("score", 0.0) or 0.0)
    if best_score < min_score:
        return "I don't know"

    candidates: List[Tuple[float, str]] = []

    # Look across top chunks and pick sentence that best matches the question.
    for c in chunks[:3]:
        chunk_score = float(c.get("score", 0.0) or 0.0)
        if chunk_score < max(min_score * 0.6, 0.01):
            continue

        for sent in _split_sentences(c.get("text", "")):
            if len(sent) < 12:
                continue
            score = _sentence_match_score(question, sent, chunk_score)
            if score > 0.0:
                candidates.append((score, sent))

    # Only return a match if we found strong keyword overlap (score > 0.4).
    if candidates:
        candidates.sort(key=lambda x: x[0], reverse=True)
        best_candidate_score = candidates[0][0]

        if best_candidate_score > 0.40:
            answer = candidates[0][1].strip()
            if answer and answer[-1] not in ".!?":
                answer += "."
            return answer

    # No strong sentence match found.
    return "I don't know"


def _try_ollama_chat(prompt: str, timeout_sec: int, model: str = None) -> str:
    base_url = os.getenv(
        "OLLAMA_BASE_URL", "http://127.0.0.1:11434").strip().rstrip("/")
    if not model or model == "llama3 (local)":
        model = os.getenv("OLLAMA_MODEL", "llama3.2:3b").strip() or "llama3.2:3b"

    url = f"{base_url}/api/generate"

    payload = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "options": {
            "temperature": 0,
        },
    }
    data = json.dumps(payload).encode("utf-8")
    req = request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with request.urlopen(req, timeout=timeout_sec) as resp:
            body = resp.read().decode("utf-8", errors="replace")
    except error.HTTPError as e:
        detail = e.read().decode("utf-8", errors="replace") if hasattr(e, "read") else str(e)
        raise RuntimeError(f"Ollama HTTP {e.code}: {detail}")
    except Exception as e:
        raise RuntimeError(f"Ollama request failed: {e}")

    try:
        parsed = json.loads(body)
    except Exception as e:
        raise RuntimeError(f"Ollama response parse failed: {e}")

    txt = (parsed.get("response") or "").strip()

    return txt or "I don't know"


def generate_rag_answer(
    question: str,
    retrieved_chunks: List[Dict[str, Any]],
    retries: int = 2,
    timeout_sec: int = 20,
    rag_mode: str = "auto",
    model: str = None,
) -> Dict[str, Any]:
    is_overview = _is_overview_question(question)
    # Dynamically scale context limit (allow up to 16,000 characters for high-level/overview queries)
    max_chars = 16000 if is_overview else 4500
    prompt, context = build_grounding_prompt(question, retrieved_chunks, max_chars=max_chars)

    start = time.perf_counter()
    attempt = 0
    answer = ""
    provider = "extractive-fallback"
    last_error = ""

    mode = (rag_mode or "auto").strip().lower()
    api_key_present = bool(os.getenv("OPENAI_API_KEY", "").strip())

    if mode in {"local", "offline", "off", "none"}:
        use_openai = False
        use_ollama = False
        last_error = "OpenAI disabled by local mode"
    elif mode in {"ollama", "local-llm"}:
        use_openai = False
        use_ollama = True
    elif mode in {"openai", "api", "remote"}:
        use_openai = True
        use_ollama = False
        if not api_key_present:
            last_error = "OPENAI_API_KEY is not configured"
    else:
        # auto mode
        use_openai = api_key_present
        use_ollama = not use_openai
        if not use_openai:
            last_error = "OPENAI_API_KEY is not configured; trying Ollama"

    if use_ollama:
        for attempt in range(1, retries + 2):
            try:
                answer = _try_ollama_chat(prompt, timeout_sec=timeout_sec, model=model)
                provider = "ollama"
                last_error = ""
                break
            except Exception as e:
                last_error = str(e)
                answer = ""

    if use_openai:
        for attempt in range(1, retries + 2):
            try:
                answer = _try_openai_chat(prompt, timeout_sec=timeout_sec)
                provider = "openai"
                last_error = ""
                break
            except Exception as e:
                last_error = str(e)
                answer = ""

    fallback_min_score = _get_fallback_min_score()
    if not answer:
        answer = _extractive_fallback_answer(
            question,
            retrieved_chunks,
            min_score=fallback_min_score,
        )

    elapsed_ms = (time.perf_counter() - start) * 1000.0

    # Cost logging for demo: estimate only when openai is used.
    prompt_tokens_est = _estimate_tokens(prompt)
    answer_tokens_est = _estimate_tokens(answer)
    total_tokens_est = prompt_tokens_est + answer_tokens_est

    # Conservative demo estimate for gpt-4o-mini-like pricing band.
    # (Not exact billing, only telemetry for demo/logging.)
    cost_usd_est = 0.0
    if provider == "openai":
        cost_usd_est = (prompt_tokens_est / 1_000_000) * 0.15 + \
            (answer_tokens_est / 1_000_000) * 0.60

    # sanitize any sensitive tokens in last_error before returning
    last_error_masked = _mask_api_keys(last_error)

    hint = ""
    if last_error_masked and ("401" in last_error_masked or "invalid_api_key" in last_error_masked.lower() or "incorrect api key" in last_error_masked.lower()):
        hint = "Invalid OpenAI API key — revoke and create a new key at https://platform.openai.com/account/api-keys."

    return {
        "answer": answer,
        "context": context,
        "provider": provider,
        "mode": mode,
        "attempts": attempt if attempt else 1,
        "timeout_sec": timeout_sec,
        "fallback_min_score": fallback_min_score,
        "elapsed_ms": round(elapsed_ms, 2),
        "prompt_tokens_est": prompt_tokens_est,
        "answer_tokens_est": answer_tokens_est,
        "total_tokens_est": total_tokens_est,
        "cost_usd_est": round(cost_usd_est, 8),
        "last_error": last_error_masked,
        "last_error_hint": hint,
    }


def rewrite_query_with_history(
    question: str,
    history: List[Dict[str, Any]],
    model: str = None,
    timeout_sec: int = 10,
) -> str:
    """
    Use the conversation history to rewrite a follow-up question into a standalone query.
    If history is empty or LLM call fails, returns the original question.
    """
    if not history:
        return question

    # Format last 4 turns of history to keep it concise and context-rich
    recent_history = history[-4:]
    history_str = ""
    for msg in recent_history:
        sender = "User" if msg.get("sender") == "user" else "Assistant"
        text = msg.get("text") or ""
        history_str += f"{sender}: {text}\n"

    prompt = (
        "You are a search query optimizer. Given the following conversation history and a follow-up question, "
        "rewrite the follow-up question into a standalone, search-optimized query. The rewritten query should contain "
        "all necessary context (such as subject, lab name, document title, or nouns) mentioned in the conversation history.\n"
        "Rules:\n"
        "1. Do not answer the question.\n"
        "2. Do not write any conversational preamble (like 'Here is the rewritten query:').\n"
        "3. Output ONLY the rewritten standalone question.\n\n"
        f"Conversation History:\n{history_str}\n"
        f"Follow-up Question: {question}\n\n"
        "Standalone Query:"
    )

    try:
        api_key_present = bool(os.getenv("OPENAI_API_KEY", "").strip())
        mode = os.getenv("RAG_MODE", "auto").strip().lower()

        use_openai = (mode in {"openai", "api", "remote"}) or (mode == "auto" and api_key_present)
        use_ollama = not use_openai

        if use_ollama:
            rewritten = _try_ollama_chat(prompt, timeout_sec=timeout_sec, model=model)
        else:
            rewritten = _try_openai_chat(prompt, timeout_sec=timeout_sec)

        cleaned = rewritten.strip().strip('"\'')
        if cleaned and len(cleaned) < 200 and not cleaned.lower().startswith("i don't know"):
            return cleaned
    except Exception:
        pass

    return question

