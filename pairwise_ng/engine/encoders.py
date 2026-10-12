"""Sentence-BERT encoders. SBERT is the only learning model in the system.

Two interchangeable backends load the same kind of model directory:
  * ONNX Runtime (model.onnx + tokenizer.json): light enough for a small server.
  * sentence-transformers / PyTorch: used when a version was saved by the
    fine-tuning script and has not been exported to ONNX.
Both apply the SBERT recipe: transformer -> mean pooling over tokens -> unit length.
"""
import os
import threading

import numpy as np

MAX_TOKENS = 256
_lock = threading.Lock()
_cache = {}


class OnnxSbertEncoder:
    backend = "onnxruntime"

    def __init__(self, model_dir):
        import onnxruntime as ort
        from tokenizers import Tokenizer

        opts = ort.SessionOptions()
        opts.intra_op_num_threads = int(os.environ.get("SBERT_THREADS", "2"))
        self.session = ort.InferenceSession(
            os.path.join(model_dir, "model.onnx"), sess_options=opts,
            providers=["CPUExecutionProvider"])
        self.input_names = {i.name for i in self.session.get_inputs()}
        self.tokenizer = Tokenizer.from_file(os.path.join(model_dir, "tokenizer.json"))
        self.tokenizer.enable_truncation(MAX_TOKENS)
        self.tokenizer.enable_padding()
        self.dim = self.session.get_outputs()[0].shape[-1]

    def encode(self, texts, batch_size=32):
        texts = list(texts)
        out = []
        for start in range(0, len(texts), batch_size):
            enc = self.tokenizer.encode_batch(texts[start:start + batch_size])
            ids = np.array([e.ids for e in enc], dtype=np.int64)
            mask = np.array([e.attention_mask for e in enc], dtype=np.int64)
            feeds = {"input_ids": ids, "attention_mask": mask}
            if "token_type_ids" in self.input_names:
                feeds["token_type_ids"] = np.zeros_like(ids)
            hidden = self.session.run(None, feeds)[0]
            if hidden.ndim == 3:  # token embeddings: mean-pool over real tokens
                m = mask[..., None].astype(hidden.dtype)
                hidden = (hidden * m).sum(axis=1) / np.clip(m.sum(axis=1), 1e-9, None)
            hidden = hidden / np.linalg.norm(hidden, axis=1, keepdims=True)
            out.append(hidden.astype(np.float32))
        return np.vstack(out) if out else np.zeros((0, self.dim), dtype=np.float32)


class SentenceTransformerEncoder:
    backend = "sentence-transformers"

    def __init__(self, model_dir):
        from sentence_transformers import SentenceTransformer

        self.model = SentenceTransformer(model_dir, device="cpu")
        self.dim = self.model.get_sentence_embedding_dimension()

    def encode(self, texts, batch_size=32):
        return np.asarray(self.model.encode(
            list(texts), batch_size=batch_size, normalize_embeddings=True,
            show_progress_bar=False), dtype=np.float32)


def load_encoder(model_dir):
    """Load (once per process) the encoder stored in model_dir."""
    model_dir = os.path.abspath(model_dir)
    with _lock:
        if model_dir not in _cache:
            if os.path.exists(os.path.join(model_dir, "model.onnx")):
                _cache[model_dir] = OnnxSbertEncoder(model_dir)
            elif os.path.exists(os.path.join(model_dir, "modules.json")):
                _cache[model_dir] = SentenceTransformerEncoder(model_dir)
            else:
                raise FileNotFoundError(
                    f"No SBERT model found in {model_dir} (expected model.onnx or a "
                    "sentence-transformers folder).")
        return _cache[model_dir]
