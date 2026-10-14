from typing import Literal

from pydantic import BaseModel, Field


class BoardListing(BaseModel):
    length: str = Field(description='Length exactly as written, e.g. "5\'8" or "8ft"')
    width: str = Field(description='Width exactly as written, e.g. "21" or "19 3/4"')
    thickness: str = Field(description='Thickness exactly as written, e.g. "2 5/8"')
    volume_l: float | None = Field(
        None, description="Volume in litres. Null if not stated"
    )
    tail: Literal["squash", "round", "pin", "swallow", "square", "other"] | None = None
    fins: Literal["single", "twin", "thruster", "quad", "2+1", "other"] | None = None
    board_type: (
        Literal["shortboard", "fish", "mid-length", "longboard", "foamie", "other"]
        | None
    ) = None


class BoardSpec(BaseModel):
    length_in: float = Field(
        ge=36, le=144, description="Total length in inches. 6'0\" = 72"
    )
    width_in: float = Field(ge=14, le=30, description="Width in inches. 19 3/4 = 19.75")
    thickness_in: float = Field(
        ge=1.5, le=5, description="Thickness in inches. 2 1/2 = 2.5"
    )
    volume_l: float | None = Field(
        None, description="Volume in litres. Null if not stated"
    )
    tail: Literal["squash", "round", "pin", "swallow", "square", "other"] | None = None
    fins: Literal["single", "twin", "thruster", "quad", "2+1", "other"] | None = None
    board_type: (
        Literal["shortboard", "fish", "mid-length", "longboard", "foamie", "other"]
        | None
    ) = None
