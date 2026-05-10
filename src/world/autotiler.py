"""Автотайлинг: определение варианта текстуры по соседним тайлам.

Правила для песка (BEACH):
- Рядом с водой (по стороне) -> SAND_DARK
- Рядом с тёмным песком (по стороне) -> SAND_MEDIUM
- Остальной песок -> SAND_LIGHT

Векторизованная обработка через NumPy + SciPy.
"""

from __future__ import annotations

import numpy as np
from scipy.ndimage import binary_dilation

from src.world.models import Biome

# Варианты автотайлинга песка
SAND_DARK = 1  # Песок рядом с водой
SAND_MEDIUM = 2  # Песок рядом с тёмным песком
SAND_LIGHT = 3  # Остальной песок

_CROSS4 = np.array([[0, 1, 0], [1, 1, 1], [0, 1, 0]], dtype=bool)


def compute_autotile_map(biome_map: np.ndarray) -> np.ndarray:
    """Вычисляет карту автотайлинга для всего мира.

    Правила для песка (BEACH):
    - Рядом с водой (по стороне) -> SAND_DARK
    - Рядом с тёмным песком (по стороне) -> SAND_MEDIUM
    - Остальной песок -> SAND_LIGHT

    Args:
        biome_map: 2D-массив биомов.

    Returns:
        2D-массив целых чисел (0 = нет автотайла).
    """
    h, w = biome_map.shape
    autotile_map = np.zeros((h, w), dtype=np.int32)

    # Маски биомов
    water_mask = (
        (biome_map == Biome.OCEAN)
        | (biome_map == Biome.DEEP_OCEAN)
        | (biome_map == Biome.FROZEN_OCEAN)
    )
    sand_mask = biome_map == Biome.BEACH

    if not sand_mask.any():
        return autotile_map

    # Тёмный песок: песок, соседствующий с водой
    water_adjacent = binary_dilation(water_mask, structure=_CROSS4)
    dark_sand = sand_mask & water_adjacent
    autotile_map[dark_sand] = SAND_DARK

    # Средний песок: песок рядом с тёмным песком, но не рядом с водой
    dark_adjacent = binary_dilation(dark_sand, structure=_CROSS4)
    medium_sand = sand_mask & dark_adjacent & ~dark_sand & ~water_mask
    autotile_map[medium_sand] = SAND_MEDIUM

    # Светлый песок: весь остальной песок
    light_sand = sand_mask & ~dark_sand & ~medium_sand
    autotile_map[light_sand] = SAND_LIGHT

    return autotile_map
