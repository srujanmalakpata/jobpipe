"""Schema contracts enforced at extract time, before anything lands in bronze.

Bronze keeps the provider payload *verbatim*; these models only check that the fields the
warehouse depends on are present and well-typed. Unknown extra fields are allowed so that a
provider adding a field never breaks extraction, while a provider removing or retyping one
we rely on is caught here instead of surfacing as NULLs three models downstream.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, ValidationError


class _Contract(BaseModel):
    model_config = ConfigDict(extra="allow", frozen=True)


def _not_blank(value: str) -> str:
    if not value.strip():
        raise ValueError("must not be blank")
    return value


# A job title made only of whitespace would become NULL in staging and fail a dbt not_null
# test three models later; reject it here instead, for every provider.
Title = Annotated[str, Field(min_length=1), AfterValidator(_not_blank)]


# --- Greenhouse: GET boards-api.greenhouse.io/v1/boards/<board>/jobs?content=true -------------


class GreenhouseLocation(_Contract):
    name: str | None = None


class GreenhouseJob(_Contract):
    id: int
    title: Title
    updated_at: datetime
    absolute_url: str = Field(min_length=1)
    location: GreenhouseLocation | None = None
    content: str | None = None
    first_published: datetime | None = None


class GreenhouseEnvelope(_Contract):
    jobs: list[Any]  # items are validated one by one, so one bad item is not fatal


# --- Lever: GET api.lever.co/v0/postings/<company>?mode=json ----------------------------------


class LeverCategories(_Contract):
    location: str | None = None
    commitment: str | None = None
    team: str | None = None
    department: str | None = None


class LeverPosting(_Contract):
    id: str = Field(min_length=1)
    text: Title
    createdAt: int  # epoch milliseconds (field names mirror the provider JSON)
    hostedUrl: str = Field(min_length=1)
    categories: LeverCategories = LeverCategories()
    workplaceType: str | None = None


# --- Ashby: GET api.ashbyhq.com/posting-api/job-board/<board> ---------------------------------


class AshbyJob(_Contract):
    id: str = Field(min_length=1)
    title: Title
    location: str | None = None
    publishedAt: datetime
    jobUrl: str = Field(min_length=1)
    isListed: bool = True
    isRemote: bool | None = None
    workplaceType: str | None = None
    employmentType: str | None = None


class AshbyEnvelope(_Contract):
    jobs: list[Any]  # items are validated one by one, so one bad item is not fatal


class EnvelopeError(ValueError):
    """The whole response is unusable (wrong top-level shape); the board fetch fails."""


def validation_message(exc: ValidationError) -> str:
    """Compact, log-friendly summary of a pydantic error."""
    parts = []
    for err in exc.errors():
        loc = ".".join(str(p) for p in err["loc"]) or "<root>"
        parts.append(f"{loc}: {err['msg']}")
    return "; ".join(parts)
