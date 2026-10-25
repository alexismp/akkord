# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""Configuration and default settings for Akkord."""

import os
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_MODEL = "gemini-4-argon"
DEFAULT_GCP_PROJECT = "alexismp-runner"
DEFAULT_VERTEXAI = True
DEFAULT_API_KEY = os.environ.get("AKKORD_GEMINI_API_KEY", "")
SUPPORTED_LANGUAGES = ("fr", "en")
DEFAULT_LANGUAGE = "fr"

AVAILABLE_MODELS = (
    "gemini-4-argon",
    "gemini-3.8-flash",
    "gemini-3.5-flash-lite",
    "gemini-2.5-pro",
    "gemini-2.5-flash",
)


@dataclass
class AkkordConfig:
    """Runtime configuration for processing music sheets."""

    model: str = field(
        default_factory=lambda: os.environ.get("AKKORD_MODEL", DEFAULT_MODEL)
    )
    vertexai: bool = field(
        default_factory=lambda: os.environ.get("AKKORD_VERTEXAI", "true").lower()
        in ("1", "true", "yes")
    )
    project: str = field(
        default_factory=lambda: os.environ.get(
            "AKKORD_GCP_PROJECT",
            os.environ.get("GOOGLE_CLOUD_PROJECT", DEFAULT_GCP_PROJECT),
        )
    )
    api_key: str | None = field(
        default_factory=lambda: os.environ.get(
            "AKKORD_GEMINI_API_KEY",
            os.environ.get("GEMINI_API_KEY", DEFAULT_API_KEY),
        )
    )
    language: str = field(
        default_factory=lambda: os.environ.get("AKKORD_LANG", DEFAULT_LANGUAGE)
    )
    output_dir: Path = field(
        default_factory=lambda: Path(os.environ.get("AKKORD_OUTPUT_DIR", "outputs"))
    )
    upload_to_drive: bool = False
    google_credentials_path: str | None = field(
        default_factory=lambda: os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
    )

    def __post_init__(self) -> None:
        self.language = self.language.lower().strip()
        if self.language not in SUPPORTED_LANGUAGES:
            raise ValueError(
                f"Unsupported language '{self.language}'. Choose from: {SUPPORTED_LANGUAGES}"
            )
        self.output_dir = Path(self.output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
