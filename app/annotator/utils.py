import os
import numpy as np
from openai import OpenAI
from typing import List
from django.conf import settings

# Initialize client
# Assuming OPENAI_API_KEY is in settings or env
api_key = os.getenv("OPENAI_API_KEY")

if api_key:
    client = OpenAI(
        api_key=api_key,
        base_url="https://api.openai.com/v1",
    )
else:
    client = None

EMBEDDING_MODEL = "text-embedding-3-small"


def get_embedding(
    text: str,
    dimensions: int = 1536,
    model: str = EMBEDDING_MODEL,
) -> List[float]:
    """Wraps the OpenAI API to get embeddings."""
    if not client:
        # Fallback or error if client not initialized
        print("OpenAI client not initialized (missing API key?)")
        return []

    text = text.replace("\n", " ")
    try:
        response = client.embeddings.create(
            input=[text], model=model, dimensions=dimensions
        )
        embedding_32 = np.array(response.data[0].embedding, dtype=np.float32)
        return embedding_32
    except Exception as e:
        print(f"Error getting embedding: {e}")
        return []


def cosine_similarity(a: List[float], b: List[float]) -> float:
    """Calculates cosine similarity between two vectors."""
    if a is None or b is None:
        return 0.0

    a_arr = np.array(a)
    b_arr = np.array(b)

    norm_a = np.linalg.norm(a_arr)
    norm_b = np.linalg.norm(b_arr)

    if norm_a == 0 or norm_b == 0:
        return 0.0

    return float(np.dot(a_arr, b_arr) / (norm_a * norm_b))
