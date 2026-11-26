#!/usr/bin/env python3
"""Hugging Face token lookup, for repos published behind the HF "auto" gate.

Some official repos are gated: `README.md`, `config.json` and the safetensors
shards return 401 ("Access to model ... is restricted") unless the request
carries a token, even when the gate auto-approves the account. Anything in this
repo that fetches from huggingface.co must send `Authorization: Bearer <token>`
or it silently sees an empty card / no config.

Token order: HF_TOKEN, HUGGING_FACE_HUB_TOKEN, then the `hf` CLI's stored token.
With no token the header is omitted, so public repos behave exactly as before.
"""
import os

TOKEN_PATHS = ("~/.cache/huggingface/token", "~/.huggingface/token")


def token():
    for key in ("HF_TOKEN", "HUGGING_FACE_HUB_TOKEN"):
        val = (os.environ.get(key) or "").strip()
        if val:
            return val
    for path in TOKEN_PATHS:
        try:
            with open(os.path.expanduser(path), encoding="utf-8") as f:
                val = f.read().strip()
        except OSError:
            continue
        if val:
            return val
    return None


def headers(extra=None, user_agent="aibench/0.1"):
    hdrs = {"User-Agent": user_agent}
    tok = token()
    if tok:
        hdrs["Authorization"] = "Bearer " + tok
    if extra:
        hdrs.update(extra)
    return hdrs
