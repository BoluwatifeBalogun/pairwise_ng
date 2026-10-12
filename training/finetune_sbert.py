"""Fine-tune the pretrained SBERT model on past project records (report Section 3.4.2).

Run on a machine with PyTorch (a GPU shortens it, a CPU works for small datasets):

    pip install -r requirements-train.txt
    python manage.py export_training_data --out training/data      # in the app
    python training/finetune_sbert.py --round 1                    # here

What it does
  1. Loads the pretrained checkpoint (all-MiniLM-L6-v2) or the previous round.
  2. Builds positive pairs: (project description, text of the supervisor who handled it).
     Other supervisors in the same batch act as negatives through a contrastive
     ranking loss (MultipleNegativesRankingLoss), so no negatives are labelled by hand.
  3. Trains with a small learning rate for a few passes, scoring Top-1, Top-3 and MRR
     on the held-out records after every pass, and keeps the best pass (early stopping).
  4. Saves the round only as better if it does not score below the starting model.
  5. Exports model.onnx + tokenizer.json to models/sbert-round-N/ for the web app.

Then:  python manage.py register_model sbert-round-N --round N --activate
"""
import argparse
import csv
import json
import os
import random
import shutil
from collections import defaultdict

import numpy as np


def read_csv(path):
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def evaluate(model, supervisors, train_rows, held_rows):
    """Same protocol as engine/evaluate.py: profiles from specialisation + training
    projects only; each held-out project is a query; ranking is within its department."""
    texts = defaultdict(list)
    dept_of = {}
    for s in supervisors:
        texts[s["supervisor_id"]].append(s["specialisation_text"])
        dept_of[s["supervisor_id"]] = s["department_id"]
    for r in train_rows:
        texts[r["supervisor_id"]].append(r["project_text"])
    profiles = {}
    for sid, t in texts.items():
        e = model.encode(t, normalize_embeddings=True, show_progress_bar=False)
        p = e.mean(axis=0)
        profiles[sid] = p / np.linalg.norm(p)
    ranks = []
    for r in held_rows:
        ids = [sid for sid in profiles if dept_of[sid] == r["department_id"]]
        q = model.encode([r["project_text"]], normalize_embeddings=True, show_progress_bar=False)[0]
        scores = np.array([profiles[sid] @ q for sid in ids])
        order = [ids[j] for j in np.argsort(-scores, kind="stable")]
        ranks.append(order.index(r["supervisor_id"]) + 1)
    ranks = np.array(ranks)
    return {"top1": float((ranks == 1).mean()), "top3": float((ranks <= 3).mean()),
            "mrr": float((1.0 / ranks).mean()), "n_eval": int(len(ranks))}


def export_onnx(model, out_dir, quantise):
    import torch

    os.makedirs(out_dir, exist_ok=True)
    transformer = model[0].auto_model.cpu().eval()
    tok = model.tokenizer
    sample = tok(["export sample text"], return_tensors="pt")
    names = [n for n in ("input_ids", "attention_mask", "token_type_ids") if n in sample]

    class Wrap(torch.nn.Module):
        def __init__(self, m):
            super().__init__()
            self.m = m

        def forward(self, *args):
            return self.m(**dict(zip(names, args))).last_hidden_state

    target = os.path.join(out_dir, "model_fp32.onnx" if quantise else "model.onnx")
    torch.onnx.export(
        Wrap(transformer), tuple(sample[n] for n in names), target, input_names=names,
        output_names=["last_hidden_state"], opset_version=14,
        dynamic_axes={**{n: {0: "batch", 1: "sequence"} for n in names},
                      "last_hidden_state": {0: "batch", 1: "sequence"}})
    if quantise:
        from onnxruntime.quantization import QuantType, quantize_dynamic
        quantize_dynamic(target, os.path.join(out_dir, "model.onnx"), weight_type=QuantType.QUInt8)
        os.remove(target)
    tok.backend_tokenizer.save(os.path.join(out_dir, "tokenizer.json"))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--round", type=int, required=True, help="Training round number (1, 2, 3 ...)")
    ap.add_argument("--data", default="training/data")
    ap.add_argument("--base", default="sentence-transformers/all-MiniLM-L6-v2",
                    help="Starting checkpoint: the pretrained model, or training/checkpoints/round-K")
    ap.add_argument("--epochs", type=int, default=4)
    ap.add_argument("--batch-size", type=int, default=8)
    ap.add_argument("--lr", type=float, default=2e-5)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--no-quantise", action="store_true", help="Keep full 32-bit weights (about 90 MB)")
    a = ap.parse_args()

    import torch
    from sentence_transformers import InputExample, SentenceTransformer, losses
    from sentence_transformers.datasets import NoDuplicatesDataLoader

    random.seed(a.seed)
    np.random.seed(a.seed)
    torch.manual_seed(a.seed)

    supervisors = read_csv(os.path.join(a.data, "supervisors.csv"))
    train_rows = read_csv(os.path.join(a.data, "train_pairs.csv"))
    held_rows = read_csv(os.path.join(a.data, "held_out.csv"))
    print(f"{len(train_rows)} training pairs, {len(held_rows)} held-out records, {len(supervisors)} supervisors")

    model = SentenceTransformer(a.base)
    start = evaluate(model, supervisors, train_rows, held_rows)
    print("before this round:", json.dumps(start))

    examples = [InputExample(texts=[r["project_text"], r["supervisor_text"]]) for r in train_rows]
    # NoDuplicatesDataLoader keeps two projects of the same supervisor out of one batch,
    # so a supervisor's own text is never used as a negative against their own project.
    batch = max(2, min(a.batch_size, len({r["supervisor_text"] for r in train_rows})))
    loader = NoDuplicatesDataLoader(examples, batch_size=batch)
    loss = losses.MultipleNegativesRankingLoss(model)

    ckpt = os.path.join("training", "checkpoints", f"round-{a.round}")
    best, history = dict(start), []
    kept = False
    for epoch in range(1, a.epochs + 1):
        model.fit(train_objectives=[(loader, loss)], epochs=1, optimizer_params={"lr": a.lr},
                  warmup_steps=int(0.1 * len(loader)) if epoch == 1 else 0, show_progress_bar=False)
        m = evaluate(model, supervisors, train_rows, held_rows)
        history.append({"epoch": epoch, **m})
        print(f"epoch {epoch}:", json.dumps(m))
        if m["mrr"] >= best["mrr"]:
            best, kept = m, True
            if os.path.isdir(ckpt):
                shutil.rmtree(ckpt)
            model.save(ckpt)
        elif kept:
            print("held-out score fell; stopping early")
            break

    if not kept:
        print("No pass matched the starting model on held-out records. This round is discarded "
              "(Section 3.4.2). Keep using the current version, or add more records and retry.")
        return
    model = SentenceTransformer(ckpt)
    out_dir = os.path.join("models", f"sbert-round-{a.round}")
    export_onnx(model, out_dir, quantise=not a.no_quantise)
    with open(os.path.join(out_dir, "metrics.json"), "w") as f:
        json.dump({"round": a.round, "base": a.base, "before": start, "after": best, "history": history,
                   "n_train": len(train_rows), "seed": a.seed, "lr": a.lr, "batch_size": batch}, f, indent=2)
    print(f"saved {out_dir}. before: {start}  after: {best}")
    print(f"next: python manage.py register_model sbert-round-{a.round} --round {a.round} --activate")


if __name__ == "__main__":
    main()
