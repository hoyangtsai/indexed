import base64
import io
import os
from typing import Any
from urllib.parse import unquote, urlparse

import numpy as np
import open_clip
import requests
import torch
from fastapi import FastAPI, HTTPException
from PIL import Image
from pydantic import BaseModel


MODEL_NAME = os.getenv("MODEL_NAME", "ViT-L-14")
PRETRAINED = os.getenv("PRETRAINED", "openai")
SERVED_MODEL_ID = os.getenv("SERVED_MODEL_ID", "openclip-vit-l-14")
HTTP_TIMEOUT_SECONDS = float(os.getenv("HTTP_TIMEOUT_SECONDS", "20"))
LOCAL_IMAGE_ROOTS = os.getenv("LOCAL_IMAGE_ROOTS", "/mnt/indexed-assets")
FUSION_MODE = os.getenv("FUSION_MODE", "adaptive").strip().lower()
FIXED_IMAGE_WEIGHT = float(os.getenv("FIXED_IMAGE_WEIGHT", "0.8"))
FIXED_TEXT_WEIGHT = float(os.getenv("FIXED_TEXT_WEIGHT", "0.2"))
ADAPTIVE_TEXT_WEIGHT_MIN = float(os.getenv("ADAPTIVE_TEXT_WEIGHT_MIN", "0.15"))
ADAPTIVE_TEXT_WEIGHT_MAX = float(os.getenv("ADAPTIVE_TEXT_WEIGHT_MAX", "0.45"))
ADAPTIVE_TEXT_WEIGHT_SLOPE = float(os.getenv("ADAPTIVE_TEXT_WEIGHT_SLOPE", "0.015"))

app = FastAPI(title="OpenCLIP Embedding Service", version="1.0.0")

device = "cpu"
model, _, preprocess = open_clip.create_model_and_transforms(
    MODEL_NAME,
    pretrained=PRETRAINED,
    device=device,
)
tokenizer = open_clip.get_tokenizer(MODEL_NAME)
model.eval()


class EmbeddingRequest(BaseModel):
    model: str
    messages: list[dict[str, Any]]


def _parse_allowed_roots(raw: str) -> list[str]:
    normalized = raw.replace(",", os.pathsep)
    roots: list[str] = []
    for entry in normalized.split(os.pathsep):
        path = os.path.realpath(os.path.expanduser(entry.strip()))
        if path and path not in roots:
            roots.append(path)
    return roots


def _is_allowed_local_path(file_path: str, allowed_roots: list[str]) -> bool:
    candidate = os.path.realpath(file_path)
    for root in allowed_roots:
        if candidate == root or candidate.startswith(f"{root}{os.sep}"):
            return True
    return False


def _normalize(vector: np.ndarray) -> np.ndarray:
    norm = np.linalg.norm(vector)
    if not np.isfinite(norm) or norm <= 0:
        raise HTTPException(status_code=500, detail="Invalid embedding norm")
    return vector / norm


def _extract_texts(messages: list[dict[str, Any]]) -> list[str]:
    texts: list[str] = []
    for message in messages:
        content = message.get("content")
        if isinstance(content, list):
            for part in content:
                if isinstance(part, dict) and part.get("type") == "text":
                    text = str(part.get("text", "")).strip()
                    if text:
                        texts.append(text)
    return texts


def _extract_image_url(messages: list[dict[str, Any]]) -> str:
    for message in reversed(messages):
        content = message.get("content")
        if not isinstance(content, list):
            continue
        for part in content:
            if not isinstance(part, dict):
                continue
            if part.get("type") != "image_url":
                continue
            image_url = part.get("image_url")
            if isinstance(image_url, dict):
                url = str(image_url.get("url", "")).strip()
                if url:
                    return url
    return ""


def _decode_data_uri(uri: str) -> bytes:
    comma = uri.find(",")
    if comma < 0:
        raise HTTPException(status_code=400, detail="Invalid data URI")
    metadata = uri[:comma]
    payload = uri[comma + 1 :]
    if ";base64" not in metadata:
        raise HTTPException(status_code=400, detail="Only base64 data URI is supported")
    try:
        return base64.b64decode(payload, validate=True)
    except Exception as error:
        raise HTTPException(status_code=400, detail=f"Invalid base64 image: {error}") from error


def _load_image(image_ref: str) -> Image.Image:
    if image_ref.startswith("data:"):
        data = _decode_data_uri(image_ref)
        return Image.open(io.BytesIO(data)).convert("RGB")

    parsed = urlparse(image_ref)
    if parsed.scheme in ("http", "https"):
        response = requests.get(image_ref, timeout=HTTP_TIMEOUT_SECONDS)
        if response.status_code != 200:
            raise HTTPException(status_code=400, detail=f"Failed to fetch image URL: {response.status_code}")
        return Image.open(io.BytesIO(response.content)).convert("RGB")
    if parsed.scheme in ("", "file"):
        allowed_roots = _parse_allowed_roots(LOCAL_IMAGE_ROOTS)
        if not allowed_roots:
            raise HTTPException(status_code=400, detail="Local file path is disabled: LOCAL_IMAGE_ROOTS is empty")
        raw_path = unquote(parsed.path) if parsed.scheme == "file" else image_ref
        local_path = os.path.realpath(os.path.expanduser(raw_path))
        if not _is_allowed_local_path(local_path, allowed_roots):
            raise HTTPException(
                status_code=403,
                detail=f"Local file path is outside allowed roots: {allowed_roots}",
            )
        if not os.path.isfile(local_path):
            raise HTTPException(status_code=400, detail=f"Local image file not found: {local_path}")
        return Image.open(local_path).convert("RGB")

    raise HTTPException(
        status_code=400,
        detail="Unsupported image_url. Use http(s), file path, or data URI base64.",
    )


def _embed_text(text: str) -> np.ndarray:
    with torch.no_grad():
        tokenized = tokenizer([text]).to(device)
        vector = model.encode_text(tokenized)[0].detach().cpu().numpy().astype(np.float32)
    return _normalize(vector)


def _embed_image(image: Image.Image) -> np.ndarray:
    with torch.no_grad():
        tensor = preprocess(image).unsqueeze(0).to(device)
        vector = model.encode_image(tensor)[0].detach().cpu().numpy().astype(np.float32)
    return _normalize(vector)


def _resolve_fusion_weights(text: str) -> tuple[float, float]:
    if FUSION_MODE == "fixed":
        image_weight = max(0.0, FIXED_IMAGE_WEIGHT)
        text_weight = max(0.0, FIXED_TEXT_WEIGHT)
        total = image_weight + text_weight
        if total <= 0:
            raise HTTPException(status_code=500, detail="Invalid fixed fusion weights")
        return image_weight / total, text_weight / total

    token_count = len([token for token in text.split() if token.strip()])
    text_weight = ADAPTIVE_TEXT_WEIGHT_MIN + max(token_count - 3, 0) * ADAPTIVE_TEXT_WEIGHT_SLOPE
    text_weight = min(ADAPTIVE_TEXT_WEIGHT_MAX, max(ADAPTIVE_TEXT_WEIGHT_MIN, text_weight))
    image_weight = max(0.0, 1.0 - text_weight)
    return image_weight, text_weight


def _blend_embeddings(image_vec: np.ndarray, text_vec: np.ndarray, text: str) -> np.ndarray:
    image_weight, text_weight = _resolve_fusion_weights(text)
    merged = image_weight * image_vec + text_weight * text_vec
    return _normalize(merged.astype(np.float32))


@app.get("/health")
def health() -> dict[str, Any]:
    return {
        "ok": True,
        "model": SERVED_MODEL_ID,
        "device": device,
        "fusionMode": FUSION_MODE,
        "localImageRoots": _parse_allowed_roots(LOCAL_IMAGE_ROOTS),
    }


@app.get("/v1/models")
def list_models() -> dict[str, Any]:
    return {
        "object": "list",
        "data": [{"id": SERVED_MODEL_ID, "object": "model"}],
    }


@app.post("/v1/embeddings")
def embeddings(request: EmbeddingRequest) -> dict[str, Any]:
    if request.model != SERVED_MODEL_ID:
        raise HTTPException(status_code=400, detail=f"Unknown model: {request.model}")
    if not isinstance(request.messages, list) or not request.messages:
        raise HTTPException(status_code=400, detail="messages must be a non-empty array")

    texts = _extract_texts(request.messages)
    image_url = _extract_image_url(request.messages)

    if image_url:
        image = _load_image(image_url)
        image_vec = _embed_image(image)
        if texts:
            merged_text = "\n".join(texts)
            text_vec = _embed_text(merged_text)
            vector = _blend_embeddings(image_vec, text_vec, merged_text)
        else:
            vector = image_vec
    else:
        if not texts:
            raise HTTPException(status_code=400, detail="No text or image found in messages")
        vector = _embed_text("\n".join(texts))

    return {
        "object": "list",
        "data": [{"object": "embedding", "index": 0, "embedding": vector.tolist()}],
        "model": SERVED_MODEL_ID,
    }
