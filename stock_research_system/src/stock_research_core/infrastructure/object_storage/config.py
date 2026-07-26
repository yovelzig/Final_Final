"""Production S3 object-storage configuration (Phase F1b).

Reads S3 connection settings from the environment (and an optional
`.env` file), matching `infrastructure.database.config`'s pattern.
Importing this module never creates a boto3 client - it only describes
how one *would* be configured.

Production credentials come exclusively from boto3's default credential
chain (environment, shared config/credentials files, or - on the
production EC2 host - the Instance Profile). No AWS access-key setting
exists here on purpose; see `docs/aws-s3-f1-setup.md`.
"""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class ObjectStorageSettings(BaseSettings):
    """S3 connection settings backing `S3ObjectStorageAdapter`.

    Defaults match the Phase F1a CloudFormation stack
    (`infrastructure/aws/finquest-storage.yaml`) and
    `docs/aws-s3-f1-setup.md`.
    """

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    object_storage_provider: str = "s3"
    aws_region: str = "us-east-2"
    s3_bucket_name: str = "finquest-knowledge-prod-881490130721-us-east-2"
    s3_knowledge_prefix: str = "knowledge/"
    s3_extracted_text_prefix: str = "knowledge-extracted/"
    s3_research_artifact_prefix: str = "research-artifacts/"
    s3_force_path_style: bool = False

    @property
    def allowed_key_prefixes(self) -> tuple[str, ...]:
        """The three configured prefixes, in the shape `validate_object_key` expects."""
        return (
            self.s3_knowledge_prefix,
            self.s3_extracted_text_prefix,
            self.s3_research_artifact_prefix,
        )
