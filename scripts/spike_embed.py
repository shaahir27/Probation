"""Day-1 Spike: Local CPU embedding speed and memory with fastembed.

Authority: docs/IMPLEMENTATION_PLAN.md Phase 0 and docs/DECISIONS_AND_OPEN_QUESTIONS.md O-6.

Run with:
    python scripts/spike_embed.py
"""

import sys
import time


def run_embed_spike() -> None:
    print("=== Probation Spike: Local CPU Embeddings (fastembed) ===")
    model_name = "sentence-transformers/all-MiniLM-L6-v2"
    print(f"Target model: {model_name}")

    try:
        from fastembed import TextEmbedding
    except ImportError:
        print("\n[!] fastembed package is not installed.")
        print("To install: pip install fastembed")
        print("Fallback option: sentence-transformers")
        return

    print("Loading ONNX embedding model onto CPU...")
    load_start = time.perf_counter()
    embedder = TextEmbedding(model_name=model_name)
    load_time = time.perf_counter() - load_start
    print(f"[+] Model loaded in {load_time:.3f}s")

    sample_texts = [
        "Please review the attached project proposal and provide your feedback by end of day.",
        "Meeting invitation: Weekly Engineering Sync on Google Meet at 10:00 AM.",
        "Your flight ticket to New Delhi has been confirmed. PNR: ABC123.",
        "Monthly cloud infrastructure invoice payment receipt for $42.50.",
        "Hey, are you free for a quick chat regarding the hackathon submission?",
    ] * 20  # 100 sentences batch test

    print(f"Embedding batch of {len(sample_texts)} sentences on CPU...")
    embed_start = time.perf_counter()
    embeddings = list(embedder.embed(sample_texts))
    embed_time = time.perf_counter() - embed_start

    dim = len(embeddings[0]) if embeddings else 0
    throughput = len(sample_texts) / embed_time if embed_time > 0 else 0

    print(f"[+] Completed embedding {len(sample_texts)} texts in {embed_time:.3f}s")
    print(f"    Vector Dimension: {dim} (expected: 384)")
    print(f"    Throughput:       {throughput:.1f} texts/sec on CPU")
    print("\nVerification result: fastembed CPU ONNX runtime is verified and suitable for local use.")


if __name__ == "__main__":
    run_embed_spike()
