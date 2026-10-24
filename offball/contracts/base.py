from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

from offball.core import SCHEMA_VERSION

XY = Annotated[tuple[float, float], Field(description="Pitch position in metres: [x, y]")]
XYZ = Annotated[tuple[float, float, float], Field(description="Ball position in metres: [x, y, z]")]
Locale = Annotated[str, Field(pattern=r"^[a-z]{2}$", description="ISO 639-1 language code")]


class Contract(BaseModel):
    """Base for every published format. Unknown fields are rejected so drift is caught early."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class Versioned(Contract):
    schema_version: str = Field(default=SCHEMA_VERSION, description="Contract version, e.g. 2.0")
