"""Объекты мира и правила их размещения.

Содержит:
- ObjectType - типы объектов (деревья, камни, трава)
- BIOME_COLORS - цвета биомов для рендера
- PLACEMENT_RULES - правила размещения объектов по биомам
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from src.world.models import Biome


# =====================================================================
# Цвета биомов для рендера
# =====================================================================

BIOME_COLORS: dict[Biome, tuple[int, int, int]] = {
    Biome.DEEP_OCEAN: (15, 40, 120),
    Biome.OCEAN: (30, 70, 160),
    Biome.FROZEN_OCEAN: (140, 190, 220),
    Biome.BEACH: (230, 210, 140),
    Biome.DESERT: (210, 180, 100),
    Biome.SAVANNA: (180, 190, 80),
    Biome.GRASSLAND: (80, 170, 60),
    Biome.FOREST: (30, 120, 40),
    Biome.TAIGA: (60, 110, 70),
    Biome.TUNDRA: (150, 155, 150),
    Biome.SNOW: (230, 235, 240),
}


# =====================================================================
# Типы объектов
# =====================================================================


class ObjectType(Enum):
    """Тип объекта на карте.

    Каждый объект имеет размер в тайлах (width x height) и цвет.
    """

    # Деревья - 1x2 тайла
    TREE_OAK = ("tree_oak", 1, 2, (20, 100, 30))
    TREE_PINE = ("tree_pine", 1, 2, (10, 80, 30))
    TREE_BIRCH = ("tree_birch", 1, 2, (100, 140, 60))

    # Кусты - 1x1 тайл
    BUSH = ("bush", 1, 1, (40, 130, 40))

    # Трава - 1x1 или 2x1
    GRASS_TUFT_SMALL = ("grass_tuft_small", 1, 1, (60, 180, 50))
    GRASS_TUFT = ("grass_tuft", 2, 1, (60, 180, 50))

    # Камни - 1x1 или 2x1
    ROCK_SMALL = ("rock_small", 1, 1, (130, 130, 130))
    ROCK_LARGE = ("rock_large", 2, 1, (110, 110, 115))

    # Цветы - 1x1
    FLOWER = ("flower", 1, 1, (220, 180, 50))

    # Кактус - 1x2
    CACTUS = ("cactus", 1, 2, (50, 140, 40))

    # Перекати-поле - 1x1
    TUMBLEWEED = ("tumbleweed", 1, 1, (160, 140, 80))

    # Тундровый куст - 1x1
    TUNDRA_BUSH = ("tundra_bush", 1, 1, (100, 110, 90))

    # Тростник - 1x2 (только вдоль берега)
    REED = ("reed", 1, 2, (100, 150, 50))

    # Пальма - 1x2
    PALM = ("palm", 1, 2, (30, 130, 50))

    def __init__(
        self,
        label: str,
        tile_width: int,
        tile_height: int,
        color: tuple[int, int, int],
    ) -> None:
        self._label = label
        self._tile_width = tile_width
        self._tile_height = tile_height
        self._color = color

    @property
    def label(self) -> str:
        """Название объекта."""
        return self._label

    @property
    def tile_width(self) -> int:
        """Ширина в тайлах."""
        return self._tile_width

    @property
    def tile_height(self) -> int:
        """Высота в тайлах."""
        return self._tile_height

    @property
    def color(self) -> tuple[int, int, int]:
        """Цвет объекта."""
        return self._color


# =====================================================================
# Правила размещения объектов
# =====================================================================


@dataclass(frozen=True)
class ObjectPlacementRule:
    """Правила размещения объектов в биоме.

    Attributes:
        biome: Биом, где размещается объект.
        object_type: Тип объекта.
        density: Вероятность размещения на тайле (0..1).
        anchor: Якорь объекта: 'bottom' - нижний тайл,
            'left' - левый тайл.
        shore_only: Если True - только рядом с водой.
    """

    biome: Biome
    object_type: ObjectType
    density: float
    anchor: str = "bottom"
    shore_only: bool = False


# Правила размещения по биомам
PLACEMENT_RULES: list[ObjectPlacementRule] = [
    # Лес
    ObjectPlacementRule(Biome.FOREST, ObjectType.TREE_OAK, 0.25),
    ObjectPlacementRule(Biome.FOREST, ObjectType.TREE_BIRCH, 0.08),
    ObjectPlacementRule(Biome.FOREST, ObjectType.BUSH, 0.10),
    ObjectPlacementRule(Biome.FOREST, ObjectType.GRASS_TUFT, 0.05),
    # Луга
    ObjectPlacementRule(Biome.GRASSLAND, ObjectType.GRASS_TUFT, 0.15),
    ObjectPlacementRule(Biome.GRASSLAND, ObjectType.TREE_OAK, 0.03),
    ObjectPlacementRule(Biome.GRASSLAND, ObjectType.FLOWER, 0.05),
    ObjectPlacementRule(Biome.GRASSLAND, ObjectType.BUSH, 0.04),
    # Тайга
    ObjectPlacementRule(Biome.TAIGA, ObjectType.TREE_PINE, 0.20),
    ObjectPlacementRule(Biome.TAIGA, ObjectType.BUSH, 0.05),
    # Саванна
    ObjectPlacementRule(Biome.SAVANNA, ObjectType.GRASS_TUFT, 0.08),
    ObjectPlacementRule(Biome.SAVANNA, ObjectType.TREE_OAK, 0.01),
    # Пустыня
    ObjectPlacementRule(Biome.DESERT, ObjectType.CACTUS, 0.02),
    ObjectPlacementRule(Biome.DESERT, ObjectType.TUMBLEWEED, 0.03),
    # Тундра
    ObjectPlacementRule(Biome.TUNDRA, ObjectType.ROCK_SMALL, 0.04),
    ObjectPlacementRule(Biome.TUNDRA, ObjectType.ROCK_LARGE, 0.01),
    ObjectPlacementRule(Biome.TUNDRA, ObjectType.TUNDRA_BUSH, 0.02),
    # Пляж
    ObjectPlacementRule(
        Biome.BEACH, ObjectType.REED, 0.15, shore_only=True
    ),
    ObjectPlacementRule(Biome.BEACH, ObjectType.PALM, 0.01),
]

# Fallback: широкий объект -> узкий объект при наложении
FALLBACK_MAP: dict[ObjectType, ObjectType] = {
    ObjectType.GRASS_TUFT: ObjectType.GRASS_TUFT_SMALL,
    ObjectType.ROCK_LARGE: ObjectType.ROCK_SMALL,
}
