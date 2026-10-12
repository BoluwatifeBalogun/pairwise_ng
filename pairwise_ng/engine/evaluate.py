"""Ranking evaluation on held-out project records (report Sections 3.9 and 4.7.2).

Each held-out project description is treated as a new student's interest statement;
the supervisor who actually handled the project is the correct answer.
"""
import numpy as np

from .vectors import build_profile, fit_matrix


def ranking_metrics(fit, correct):
    """fit: (n_queries, n_supervisors); correct[i]: index of the right supervisor."""
    fit = np.asarray(fit)
    ranks = []
    for i, c in enumerate(correct):
        order = np.argsort(-fit[i], kind="stable")
        ranks.append(int(np.where(order == c)[0][0]) + 1)
    ranks = np.array(ranks)
    return {
        "top1": float(np.mean(ranks == 1)),
        "top3": float(np.mean(ranks <= 3)),
        "mrr": float(np.mean(1.0 / ranks)),
        "n_eval": int(len(ranks)),
    }


def evaluate_encoder(encoder, supervisors, held_out):
    """supervisors: list of {"texts": [specialisation + training project texts]}
    held_out: list of (query_text, supervisor_index)."""
    profiles = [build_profile(encoder.encode(s["texts"])) for s in supervisors]
    queries = encoder.encode([q for q, _ in held_out])
    fit = fit_matrix(queries, profiles)
    return ranking_metrics(fit, [c for _, c in held_out])
