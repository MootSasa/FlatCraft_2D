"""Биомы, тайлы, чанки и мир - основные данные проекта."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Optional

import numpy as np

if TYPE_CHECKING:
    import arcade


class WorldGenerationError(Exception):
    """Ошибка при создании мира."""


class Biome(Enum):
    """Биом - тип местности. У каждого есть название и цвет."""

    DEEP_OCEAN = ("deep_ocean", (15, 40, 120))
    OCEAN = ("ocean", (30, 70, 160))
    FROZEN_OCEAN = ("frozen_ocean", (140, 190, 220))
    BEACH = ("beach", (230, 210, 140))
    DESERT = ("desert", (210, 180, 100))
    SAVANNA = ("savanna", (180, 190, 80))
    GRASSLAND = ("grassland", (80, 170, 60))
    FOREST = ("forest", (30, 120, 40))
    TAIGA = ("taiga", (60, 110, 70))
    TUNDRA = ("tundra", (150, 155, 150))
    SNOW = ("snow", (230, 235, 240))

    def __init__(self, label: str, color: tuple[int, int, int]) -> None:
        self._label = label
        self._color = color

    @property
    def label(self) -> str:
        """Название биома."""
        return self._label

    @property
    def color(self) -> tuple[int, int, int]:
        "Цвет биома." ""
        return self._color

    @classmethod
    def from_index(cls, index: int) -> Biome:
        """Биом по номеру (0, 1, 2, ...).

        Args:
            index: Номер биома в списке.

        Returns:
            Объект Biome.

        Raises:
            WorldGenerationError: Если номер за пределами списка.
        """
        members = list(cls)
        if 0 <= index < len(members):
            return members[index]
        raise WorldGenerationError(
            f"Номер биома {index} вне диапазона [0, {len(members) - 1}]"
        )

    @property
    def is_water(self) -> bool:
        """Это вода (любой океан)?"""
        return self in (
            Biome.DEEP_OCEAN,
            Biome.OCEAN,
            Biome.FROZEN_OCEAN,
        )

    @property
    def is_frozen(self) -> bool:
        """Это лёд или снег?"""
        return self in (Biome.FROZEN_OCEAN, Biome.SNOW)


@dataclass(frozen=True)
class Tile:
    """Один квадратик мира.

    Attributes:
        biome: Тип местности.
        temperature: Температура 0..1.
        moisture: Влажность 0..1.
        elevation: Высота 0..1.
        autotile_mask: Маска для автотайлинга (TODO).
    """

    biome: Biome
    temperature: float
    moisture: float
    elevation: float
    autotile_mask: int = 0


@dataclass
class Chunk:
    """Кусок мира размером chunk_size x chunk_size тайлов.

    Attributes:
        x, y: Координаты чанка.
        tiles: Массив тайлов.
        surface_sprite_list: Спрайты земли (заполняет рендер).
        object_sprite_list: Спрайты объектов (заполняет рендер).
    """

    x: int
    y: int
    tiles: np.ndarray
    surface_sprite_list: Optional[arcade.SpriteList[arcade.Sprite]] = field(
        default=None, repr=False
    )
    object_sprite_list: Optional[arcade.SpriteList[arcade.Sprite]] = field(
        default=None, repr=False
    )

    @property
    def tile_count(self) -> int:
        """Сколько тайлов в чанке."""
        return self.tiles.size


@dataclass
class World:
    """Сгенерированный мир.

    Attributes:
        seed: Сид для воспроизводимости.
        width, height: Размер в тайлах.
        chunk_size: Размер одного чанка.
        chunks: Словарь чанков по ключу (x, y).
        biome_map: Карта биомов (NumPy).
        elevation_map: Карта высот (NumPy).
        temperature_map: Карта температур (NumPy).
        moisture_map: Карта влажности (NumPy).
    """

    seed: int
    width: int
    height: int
    chunk_size: int
    chunks: dict[tuple[int, int], Chunk] = field(default_factory=dict)
    biome_map: Optional[np.ndarray] = None
    elevation_map: Optional[np.ndarray] = None
    temperature_map: Optional[np.ndarray] = None
    moisture_map: Optional[np.ndarray] = None

    @property
    def chunk_count(self) -> int:
        """Сколько чанков в мире."""
        return len(self.chunks)

    @property
    def chunks_x(self) -> int:
        """Чанков по горизонтали."""
        return (self.width + self.chunk_size - 1) // self.chunk_size

    @property
    def chunks_y(self) -> int:
        """Чанков по вертикали."""
        return (self.height + self.chunk_size - 1) // self.chunk_size

    def get_chunk(self, cx: int, cy: int) -> Optional[Chunk]:
        """Чанк по координатам или None."""
        return self.chunks.get((cx, cy))

    def get_tile(self, tx: int, ty: int) -> Optional[Tile]:
        """Тайл по глобальным координатам или None (если вне мира).

        Args:
            tx: X-координата тайла.
            ty: Y-координата тайла.

        Returns:
            Объект Tile или None.
        """
        if not (0 <= tx < self.width and 0 <= ty < self.height):
            return None
        cx, cy = tx // self.chunk_size, ty // self.chunk_size
        chunk = self.get_chunk(cx, cy)
        if chunk is None:
            return None
        local_x = tx % self.chunk_size
        local_y = ty % self.chunk_size
        return chunk.tiles[local_y, local_x]  # type: ignore[no-any-return]
