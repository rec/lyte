from __future__ import annotations

import math

from pydantic import BaseModel, model_validator


class Layout(BaseModel, frozen=True):
    name: str = 'layout'
    coords: list[list[float]] | None = None
    dims: list[int] | None = None
    spacing: float | list[float] = 1.0

    @model_validator(mode='after')
    def validate_layout(self) -> Layout:
        if (self.coords is None) == (self.dims is None):
            raise ValueError('Exactly one of coords and dims must be set')
        if self.coords is not None:
            if not self.coords:
                raise ValueError('coords must not be empty')
            for coord in self.coords:
                validate_coord(coord)
        if self.dims is not None:
            if len(self.dims) != 2:
                raise ValueError('dims must contain rows and columns')
            rows, columns = self.dims
            if rows <= 0 or columns <= 0:
                raise ValueError('dims rows and columns must be greater than zero')
        spacing = self.resolved_spacing
        if spacing[0] <= 0 or spacing[1] <= 0:
            raise ValueError('spacing must be greater than zero')
        return self

    @property
    def resolved_spacing(self) -> tuple[float, float]:
        if isinstance(self.spacing, int | float):
            return float(self.spacing), float(self.spacing)
        if len(self.spacing) != 2:
            raise ValueError('spacing must be a float or x, y pair')
        return float(self.spacing[0]), float(self.spacing[1])

    def points(self) -> list[list[float]]:
        if self.coords is not None:
            return self.coords
        if self.dims is None:
            raise ValueError('Exactly one of coords and dims must be set')
        rows, columns = self.dims
        x_spacing, y_spacing = self.resolved_spacing
        return [
            [column * x_spacing, row * y_spacing]
            for row in range(rows)
            for column in range(columns)
        ]


def validate_coord(coord: list[float]) -> None:
    if len(coord) != 2:
        raise ValueError('coords must contain x, y pairs')
    for value in coord:
        if not math.isfinite(value):
            raise ValueError('coords must contain finite values')
