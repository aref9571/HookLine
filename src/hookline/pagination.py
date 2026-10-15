from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Query
from pydantic import BaseModel


@dataclass
class PageParams:
    limit: int
    offset: int


def get_page_params(
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> PageParams:
    return PageParams(limit=limit, offset=offset)


PageQuery = Annotated[PageParams, Depends(get_page_params)]


class Page[T](BaseModel):
    items: list[T]
    total: int
    limit: int
    offset: int
