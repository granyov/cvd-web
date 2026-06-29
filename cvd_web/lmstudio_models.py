from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any
from urllib.parse import urlsplit


class LMStudioManagementError(RuntimeError):
    pass


def management_base_url(api_url: str) -> str:
    parsed = urlsplit(api_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise LMStudioManagementError("Некорректный LM Studio API URL")
    return f"{parsed.scheme}://{parsed.netloc}"


def _request_json(
    url: str,
    *,
    method: str = "GET",
    payload: dict[str, Any] | None = None,
    timeout_seconds: int = 10,
) -> dict[str, Any]:
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(
        url,
        data=body,
        method=method,
        headers={"Accept": "application/json", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            decoded = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError:
        raise
    except (urllib.error.URLError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise LMStudioManagementError(str(exc)) from exc
    if not isinstance(decoded, dict):
        raise LMStudioManagementError("LM Studio вернула некорректный ответ")
    return decoded


def _normalize_v1_model(item: dict[str, Any]) -> dict[str, Any]:
    instances = item.get("loaded_instances") if isinstance(item.get("loaded_instances"), list) else []
    normalized_instances = []
    for instance in instances:
        if not isinstance(instance, dict):
            continue
        raw_config = instance.get("load_config") or instance.get("config")
        load_config = raw_config if isinstance(raw_config, dict) else {}
        normalized_instances.append({
            "id": str(instance.get("id") or ""),
            "context_length": load_config.get("context_length"),
        })
    model_id = str(item.get("key") or item.get("id") or "").strip()
    raw_quantization = item.get("quantization")
    quantization = (
        str(raw_quantization.get("name") or "")
        if isinstance(raw_quantization, dict)
        else str(raw_quantization or "")
    )
    return {
        "id": model_id,
        "display_name": str(item.get("display_name") or model_id),
        "type": str(item.get("type") or "unknown"),
        "publisher": str(item.get("publisher") or ""),
        "architecture": str(item.get("architecture") or ""),
        "format": str(item.get("format") or ""),
        "quantization": quantization,
        "params": str(item.get("params_string") or item.get("params") or ""),
        "size_bytes": int(item.get("size_bytes") or 0),
        "max_context_length": item.get("max_context_length"),
        "loaded_context_length": normalized_instances[0].get("context_length") if normalized_instances else None,
        "state": "loaded" if normalized_instances else "not-loaded",
        "loaded_instances": normalized_instances,
    }


def _normalize_v0_model(item: dict[str, Any]) -> dict[str, Any]:
    model_id = str(item.get("id") or "").strip()
    state = str(item.get("state") or "unknown")
    instance_id = model_id if state == "loaded" else ""
    return {
        "id": model_id,
        "display_name": str(item.get("display_name") or model_id),
        "type": str(item.get("type") or "unknown"),
        "publisher": str(item.get("publisher") or ""),
        "architecture": str(item.get("arch") or item.get("architecture") or ""),
        "format": str(item.get("compatibility_type") or item.get("format") or ""),
        "quantization": str(item.get("quantization") or ""),
        "params": str(item.get("params_string") or ""),
        "size_bytes": int(item.get("size_bytes") or 0),
        "max_context_length": item.get("max_context_length"),
        "loaded_context_length": item.get("loaded_context_length"),
        "state": state,
        "loaded_instances": [{"id": instance_id, "context_length": item.get("loaded_context_length")}] if instance_id else [],
    }


def list_lm_models(api_url: str, *, timeout_seconds: int = 10) -> dict[str, Any]:
    base_url = management_base_url(api_url)
    try:
        payload = _request_json(f"{base_url}/api/v1/models", timeout_seconds=timeout_seconds)
        raw_models = payload.get("models") if isinstance(payload.get("models"), list) else []
        models = [_normalize_v1_model(item) for item in raw_models if isinstance(item, dict)]
        return {"api_version": "v1", "models": [item for item in models if item["id"]]}
    except urllib.error.HTTPError as exc:
        if exc.code != 404:
            raise LMStudioManagementError(f"LM Studio HTTP {exc.code}") from exc

    try:
        payload = _request_json(f"{base_url}/api/v0/models", timeout_seconds=timeout_seconds)
    except urllib.error.HTTPError as exc:
        raise LMStudioManagementError(f"LM Studio HTTP {exc.code}") from exc
    raw_models = payload.get("data") if isinstance(payload.get("data"), list) else []
    models = [_normalize_v0_model(item) for item in raw_models if isinstance(item, dict)]
    return {"api_version": "v0", "models": [item for item in models if item["id"]]}


def activate_lm_model(
    api_url: str,
    model_id: str,
    *,
    previous_model_id: str = "",
    unload_previous: bool = True,
    timeout_seconds: int = 300,
) -> dict[str, Any]:
    selected_id = str(model_id or "").strip()
    if not selected_id:
        raise LMStudioManagementError("Не выбрана модель")

    catalog = list_lm_models(api_url, timeout_seconds=min(timeout_seconds, 30))
    models = catalog["models"]
    selected = next((item for item in models if item["id"] == selected_id), None)
    if not selected:
        raise LMStudioManagementError("Выбранная модель не найдена в LM Studio")
    if selected["type"] not in {"llm", "vlm"}:
        raise LMStudioManagementError("Для клинического анализа нужна LLM/VLM-модель")

    if catalog["api_version"] == "v0":
        if selected["state"] != "loaded":
            raise LMStudioManagementError("Эта версия LM Studio не поддерживает загрузку модели через API v1")
        return {**catalog, "selected": selected, "warning": "Использован совместимый API v0"}

    base_url = management_base_url(api_url)
    if selected["state"] != "loaded":
        try:
            _request_json(
                f"{base_url}/api/v1/models/load",
                method="POST",
                payload={"model": selected_id, "echo_load_config": True},
                timeout_seconds=timeout_seconds,
            )
        except urllib.error.HTTPError as exc:
            raise LMStudioManagementError(f"Не удалось загрузить модель: LM Studio HTTP {exc.code}") from exc

    previous_id = str(previous_model_id or "").strip()
    unloaded_instances: list[str] = []
    if unload_previous and previous_id and previous_id != selected_id:
        previous = next((item for item in models if item["id"] == previous_id), None)
        for instance in (previous or {}).get("loaded_instances", []):
            instance_id = str(instance.get("id") or "").strip()
            if not instance_id:
                continue
            try:
                _request_json(
                    f"{base_url}/api/v1/models/unload",
                    method="POST",
                    payload={"instance_id": instance_id},
                    timeout_seconds=min(timeout_seconds, 60),
                )
                unloaded_instances.append(instance_id)
            except urllib.error.HTTPError as exc:
                raise LMStudioManagementError(f"Модель выбрана, но предыдущая не выгружена: LM Studio HTTP {exc.code}") from exc

    refreshed = list_lm_models(api_url, timeout_seconds=min(timeout_seconds, 30))
    active = next((item for item in refreshed["models"] if item["id"] == selected_id), None)
    if not active or active["state"] != "loaded":
        raise LMStudioManagementError("LM Studio не подтвердила загрузку выбранной модели")
    return {**refreshed, "selected": active, "unloaded_instances": unloaded_instances}
