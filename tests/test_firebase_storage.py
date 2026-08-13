"""
tests/test_firebase_storage.py
================================
Pruebas puras (sin DB, sin HTTP) del helper que borra archivos de Firebase
Storage a partir de la public_url guardada en BD (usado al eliminar
pacientes y evaluaciones socioeconómicas para no dejar archivos huérfanos).
"""
import pytest

from app.core import firebase as firebase_module


def _url(path: str) -> str:
    return f"https://storage.googleapis.com/{firebase_module.BUCKET_NAME}/{path}"


def test_storage_path_from_public_url_extracts_path():
    path = "pacientes/42/legal/identidad/ci_paciente.pdf"
    assert firebase_module.storage_path_from_public_url(_url(path)) == path


def test_storage_path_from_public_url_decodes_percent_encoding():
    url = f"https://storage.googleapis.com/{firebase_module.BUCKET_NAME}/pacientes/1/evaluaciones/foto%20fachada.jpg"
    assert firebase_module.storage_path_from_public_url(url) == "pacientes/1/evaluaciones/foto fachada.jpg"


def test_storage_path_from_public_url_returns_none_for_foreign_url():
    assert firebase_module.storage_path_from_public_url("https://example.com/foo/bar.jpg") is None


def test_storage_path_from_public_url_returns_none_for_empty_or_none():
    assert firebase_module.storage_path_from_public_url("") is None
    assert firebase_module.storage_path_from_public_url(None) is None


def test_storage_path_from_public_url_returns_none_for_malformed_url():
    assert firebase_module.storage_path_from_public_url("not-a-url::::") is None


def test_delete_file_from_firebase_by_url_raises_for_unmappable_url():
    with pytest.raises(ValueError):
        firebase_module.delete_file_from_firebase_by_url("https://example.com/not-our-bucket/file.jpg")


def test_delete_file_from_firebase_by_url_delegates_with_extracted_path(monkeypatch):
    calls = []
    monkeypatch.setattr(firebase_module, "delete_file_from_firebase", lambda path: calls.append(path))

    firebase_module.delete_file_from_firebase_by_url(_url("pacientes/9/foto.jpg"))

    assert calls == ["pacientes/9/foto.jpg"]
