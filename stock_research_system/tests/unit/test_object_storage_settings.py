"""Unit tests for `ObjectStorageSettings` (Phase F1b).

Pure settings/validation checks - no boto3, no network, no AWS.
"""

from __future__ import annotations

import pytest

from stock_research_core.infrastructure.object_storage.config import ObjectStorageSettings

_ENV_VARS = (
    "OBJECT_STORAGE_PROVIDER",
    "AWS_REGION",
    "S3_BUCKET_NAME",
    "S3_KNOWLEDGE_PREFIX",
    "S3_EXTRACTED_TEXT_PREFIX",
    "S3_RESEARCH_ARTIFACT_PREFIX",
    "S3_FORCE_PATH_STYLE",
)


@pytest.fixture(autouse=True)
def _clean_object_storage_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Isolate every test from the real shell environment / any `.env` file."""
    for name in _ENV_VARS:
        monkeypatch.delenv(name, raising=False)


def test_defaults_match_f1a_cloudformation_contract() -> None:
    settings = ObjectStorageSettings()

    assert settings.object_storage_provider == "s3"
    assert settings.aws_region == "us-east-2"
    assert settings.s3_bucket_name == "finquest-knowledge-prod-881490130721-us-east-2"
    assert settings.s3_knowledge_prefix == "knowledge/"
    assert settings.s3_extracted_text_prefix == "knowledge-extracted/"
    assert settings.s3_research_artifact_prefix == "research-artifacts/"
    assert settings.s3_force_path_style is False


def test_allowed_key_prefixes_matches_the_shared_key_contract_defaults() -> None:
    from stock_research_core.application.object_storage.keys import DEFAULT_ALLOWED_KEY_PREFIXES

    settings = ObjectStorageSettings()
    assert settings.allowed_key_prefixes == DEFAULT_ALLOWED_KEY_PREFIXES


def test_settings_read_every_required_field_from_the_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OBJECT_STORAGE_PROVIDER", "s3")
    monkeypatch.setenv("AWS_REGION", "us-west-2")
    monkeypatch.setenv("S3_BUCKET_NAME", "custom-bucket")
    monkeypatch.setenv("S3_KNOWLEDGE_PREFIX", "custom-knowledge/")
    monkeypatch.setenv("S3_EXTRACTED_TEXT_PREFIX", "custom-extracted/")
    monkeypatch.setenv("S3_RESEARCH_ARTIFACT_PREFIX", "custom-artifacts/")
    monkeypatch.setenv("S3_FORCE_PATH_STYLE", "true")

    settings = ObjectStorageSettings()

    assert settings.aws_region == "us-west-2"
    assert settings.s3_bucket_name == "custom-bucket"
    assert settings.s3_knowledge_prefix == "custom-knowledge/"
    assert settings.s3_extracted_text_prefix == "custom-extracted/"
    assert settings.s3_research_artifact_prefix == "custom-artifacts/"
    assert settings.s3_force_path_style is True
    assert settings.allowed_key_prefixes == (
        "custom-knowledge/",
        "custom-extracted/",
        "custom-artifacts/",
    )


def test_settings_never_declare_static_credential_fields() -> None:
    forbidden = {
        "aws_access_key_id",
        "aws_secret_access_key",
        "aws_session_token",
    }
    declared = set(ObjectStorageSettings.model_fields)
    assert not (forbidden & declared)


def test_settings_never_declare_presigned_url_or_fake_provider_fields() -> None:
    declared = set(ObjectStorageSettings.model_fields)
    assert not any("presigned" in field for field in declared)
    assert not any("fake" in field for field in declared)


def test_settings_ignore_unrelated_environment_variables(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SOME_UNRELATED_SETTING", "irrelevant")
    settings = ObjectStorageSettings()
    assert settings.s3_bucket_name == "finquest-knowledge-prod-881490130721-us-east-2"
