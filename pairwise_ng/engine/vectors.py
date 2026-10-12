"""Vector arithmetic for the SBERT matching module (report Section 4.4, Code Listing 4.1)."""
import numpy as np


def normalise(v):
    """Rescale a vector to unit length."""
    v = np.asarray(v, dtype=float)
    n = np.linalg.norm(v)
    if n == 0:
        raise ValueError("cannot normalise a zero vector")
    return v / n


def build_profile(embeddings):
    """Supervisor profile: average of the supervisor's text embeddings, rescaled to unit length."""
    return normalise(np.mean(np.asarray(embeddings, dtype=float), axis=0))


def fit_matrix(student_embs, supervisor_profiles):
    """Cosine similarity of every student-supervisor pair as one matrix product."""
    S = np.vstack([normalise(e) for e in student_embs])
    V = np.vstack(supervisor_profiles)
    return S @ V.T
