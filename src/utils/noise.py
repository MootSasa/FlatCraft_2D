"""Генератор шума Перлина для создания карт мира.

Библиотека perlin-noise даёт градиенты (через hasher + sample_vector),
а интерполяция делается на NumPy для скорости.
Мультипроцессинг ускоряет предвычисление градиентов в 2-4x.
"""

from __future__ import annotations

import logging
import os
from concurrent.futures import (
    ProcessPoolExecutor,
    Future,
)
from dataclasses import dataclass

import numpy as np
from perlin_noise.tools import hasher, sample_vector

logger = logging.getLogger(__name__)

# Количество воркеров для мультипроцессинга
_MP_WORKERS: int = max(2, min(128, (os.cpu_count() or 2)))


class NoiseGenerationError(Exception):
    """Ошибка при генерации шума."""


@dataclass(frozen=True)
class NoiseParams:
    """Параметры шума.

    Attributes:
        octaves: Количество слоёв шума (больше - детальнее).
        frequency: Базовая частота (ниже - крупнее структуры).
        persistence: Влияние каждого следующего слоя (0..1).
        lacunarity: Множитель частоты между слоями (обычно 2.0).
    """

    octaves: int = 6
    frequency: float = 0.01
    persistence: float = 0.5
    lacunarity: float = 2.0

    def __post_init__(self) -> None:
        """Проверка параметров."""
        if self.octaves < 1:
            raise NoiseGenerationError(
                f"Количество октав должно быть >= 1, получено: {self.octaves}"
            )
        if self.frequency <= 0:
            raise NoiseGenerationError(
                f"Частота должна быть > 0, получено: {self.frequency}"
            )
        if not (0 < self.persistence <= 1):
            raise NoiseGenerationError(
                f"Persistence должен быть в (0, 1],"
                f" получено: {self.persistence}"
            )
        if self.lacunarity <= 1:
            raise NoiseGenerationError(
                f"Lacunarity должен быть > 1, получено: {self.lacunarity}"
            )


def _compute_gradient_row(
    octave_seed: int, iy: int, max_ix: int
) -> tuple[int, np.ndarray, np.ndarray]:
    """Вычисляет градиенты для одной строки сетки.

    Args:
        octave_seed: Сид октавы.
        iy: Номер строки.
        max_ix: Максимальная X-координата.

    Returns:
        Кортеж (iy, row_x, row_y).
    """
    row_x = np.empty(max_ix + 1, dtype=np.float64)
    row_y = np.empty(max_ix + 1, dtype=np.float64)
    for ix in range(max_ix + 1):
        h = hasher((ix, iy))
        vec_seed = octave_seed * h
        vec = sample_vector(dimensions=2, seed=vec_seed)
        row_x[ix] = vec[0]
        row_y[ix] = vec[1]
    return iy, row_x, row_y


def _precompute_gradients(
    octave_seed: int,
    max_ix: int,
    max_iy: int,
    executor: ProcessPoolExecutor | None = None,
) -> tuple[np.ndarray, np.ndarray]:
    """Предвычисляет градиентные векторы для сетки.

    Использует perlin-noise (hasher + sample_vector), повторяя
    логику RandVec: seed = octave_seed * hasher((ix, iy)),
    vec = sample_vector(2, seed).

    Если передан executor - использует его для распределения
    строк по воркерам. Иначе - однопоточный режим.

    Args:
        octave_seed: Сид октавы (seed + octave_idx * 1000).
        max_ix: Максимальная X-координата сетки.
        max_iy: Максимальная Y-координата сетки.
        executor: Существующий пул процессов
            (переиспользуется между октавами).

    Returns:
        Кортеж (grad_x, grad_y) - массивы формы
        (max_iy+1, max_ix+1).
    """
    grad_x = np.empty((max_iy + 1, max_ix + 1), dtype=np.float64)
    grad_y = np.empty((max_iy + 1, max_ix + 1), dtype=np.float64)

    # Маленькие сетки - нет смысла в мультипроцессинге
    total_cells = (max_ix + 1) * (max_iy + 1)
    if total_cells < 500 or executor is None:
        for iy in range(max_iy + 1):
            for ix in range(max_ix + 1):
                h = hasher((ix, iy))
                vec_seed = octave_seed * h
                vec = sample_vector(
                    dimensions=2, seed=vec_seed
                )
                grad_x[iy, ix] = vec[0]
                grad_y[iy, ix] = vec[1]
        return grad_x, grad_y

    # Мультипроцессинг: строки по воркерам
    try:
        futures: list[Future] = [
            executor.submit(
                _compute_gradient_row,
                octave_seed,
                iy,
                max_ix,
            )
            for iy in range(max_iy + 1)
        ]
        for future in futures:
            iy, row_x, row_y = future.result()
            grad_x[iy] = row_x
            grad_y[iy] = row_y
    except Exception as exc:
        # Fallback: однопоточный режим при ошибке
        logger.warning(
            "Мультипроцессинг недоступен (%s), "
            "переключаюсь на однопоточный режим",
            exc,
        )
        for iy in range(max_iy + 1):
            for ix in range(max_ix + 1):
                h = hasher((ix, iy))
                vec_seed = octave_seed * h
                vec = sample_vector(
                    dimensions=2, seed=vec_seed
                )
                grad_x[iy, ix] = vec[0]
                grad_y[iy, ix] = vec[1]

    return grad_x, grad_y


def _fade(t: np.ndarray) -> np.ndarray:
    """Smoothstep Перлина: 6t^5 - 15t^4 + 10t^3.

    Args:
        t: Массив значений [0, 1].

    Returns:
        Сглаженные значения [0, 1].
    """
    return 6.0 * t**5 - 15.0 * t**4 + 10.0 * t**3


class FractalNoiseGenerator:
    """Генератор фрактального шума Перлина.

    perlin-noise даёт градиенты, NumPy делает интерполяцию.
    Совместимость по сидам + высокая скорость.

    Пример::

        params = NoiseParams(octaves=6, frequency=0.01)
        gen = FractalNoiseGenerator(seed=42, params=params)
        height_map = gen.generate_map(width=1000, height=1000)
    """

    def __init__(self, seed: int, params: NoiseParams | None = None) -> None:
        """Инициализация генератора.

        Args:
            seed: Сид для воспроизводимости.
            params: Параметры шума. Если None - по умолчанию.

        Raises:
            NoiseGenerationError: При неверных параметрах.
        """
        self._seed = seed
        self._params = params if params is not None else NoiseParams()

    @property
    def seed(self) -> int:
        """Сид генерации."""
        return self._seed

    @property
    def params(self) -> NoiseParams:
        """Параметры шума."""
        return self._params

    def generate_map(self, width: int, height: int) -> np.ndarray:
        """Генерирует 2D-карту шума.

        Значения нормализованы в [0, 1]. Каждый слой генерируется
        с увеличивающейся частотой и уменьшающейся амплитудой,
        потом все слои складываются.

        Создаёт один ProcessPoolExecutor на все октавы,
        вместо создания/уничтожения пула для каждой октавы.

        Args:
            width: Ширина карты.
            height: Высота карты.

        Returns:
            Массив NumPy формы (height, width) со
            значениями [0, 1].

        Raises:
            NoiseGenerationError: Если размеры некорректны.
        """
        if width <= 0 or height <= 0:
            raise NoiseGenerationError(
                f"Размеры должны быть > 0,"
                f" получено: {width}x{height}"
            )

        # Координатная сетка
        x_coords = np.arange(width, dtype=np.float64)
        y_coords = np.arange(height, dtype=np.float64)
        x_grid, y_grid = np.meshgrid(x_coords, y_coords)

        # Нормализация к базовой частоте
        x_norm = x_grid * self._params.frequency
        y_norm = y_grid * self._params.frequency

        # Один пул процессов на все октавы
        executor: ProcessPoolExecutor | None = None
        try:
            executor = ProcessPoolExecutor(
                max_workers=_MP_WORKERS,
            )
        except Exception as exc:
            logger.warning(
                "Не удалось создать пул процессов (%s),"
                " переключаюсь на однопоточный режим",
                exc,
            )
            executor = None

        # Суммируем октавы
        result = np.zeros((height, width), dtype=np.float64)
        total_amplitude = 0.0

        try:
            for octave_idx in range(self._params.octaves):
                freq_multiplier = (
                    self._params.lacunarity**octave_idx
                )
                amp_multiplier = (
                    self._params.persistence**octave_idx
                )

                octave_map = self._generate_octave(
                    x_norm * freq_multiplier,
                    y_norm * freq_multiplier,
                    octave_idx,
                    executor=executor,
                )

                result += octave_map * amp_multiplier
                total_amplitude += amp_multiplier
        finally:
            # Освобождаем пул
            if executor is not None:
                executor.shutdown(wait=True)

        # Нормализация в [0, 1]
        if total_amplitude > 0:
            result /= total_amplitude

        result = self._normalize_to_01(result)

        return result

    def _generate_octave(
        self,
        x_norm: np.ndarray,
        y_norm: np.ndarray,
        octave_idx: int,
        executor: ProcessPoolExecutor | None = None,
    ) -> np.ndarray:
        """Генерирует одну октаву шума (векторизованно).

        Градиенты берём из perlin-noise, скалярные произведения
        и интерполяцию делаем на NumPy.

        Алгоритм:
        1. Находим целочисленные углы ячеек
        2. Предвычисляем градиенты через perlin-noise
        3. Скалярное произведение градиента на смещение
        4. Билинейная интерполяция через smoothstep

        Args:
            x_norm: Нормализованные X-координаты (2D-массив).
            y_norm: Нормализованные Y-координаты (2D-массив).
            octave_idx: Номер октавы (для вычисления сида).
            executor: Пул процессов для мультипроцессинга.

        Returns:
            2D-массив значений шума для этой октавы.
        """
        octave_seed = self._seed + octave_idx * 1000

        # Целочисленные координаты углов ячеек
        ix = np.floor(x_norm).astype(int)
        iy = np.floor(y_norm).astype(int)

        # Дробные части (смещение внутри ячейки)
        fx = x_norm - ix
        fy = y_norm - iy

        # Предвычисляем градиенты
        max_ix = int(ix.max()) + 1
        max_iy = int(iy.max()) + 1
        grad_x, grad_y = _precompute_gradients(
            octave_seed, max_ix, max_iy,
            executor=executor,
        )

        # Градиенты для 4 углов каждой ячейки
        g00_x = grad_x[iy, ix]
        g00_y = grad_y[iy, ix]
        g10_x = grad_x[iy, ix + 1]
        g10_y = grad_y[iy, ix + 1]
        g01_x = grad_x[iy + 1, ix]
        g01_y = grad_y[iy + 1, ix]
        g11_x = grad_x[iy + 1, ix + 1]
        g11_y = grad_y[iy + 1, ix + 1]

        # Скалярные произведения: gradient . offset
        d00 = g00_x * fx + g00_y * fy
        d10 = g10_x * (fx - 1) + g10_y * fy
        d01 = g01_x * fx + g01_y * (fy - 1)
        d11 = g11_x * (fx - 1) + g11_y * (fy - 1)

        # Smoothstep-интерполяция
        u = _fade(fx)
        v = _fade(fy)

        # Билинейная интерполяция
        return (  # type: ignore[no-any-return]
            d00 * (1 - u) * (1 - v)
            + d10 * u * (1 - v)
            + d01 * (1 - u) * v
            + d11 * u * v
        )

    @staticmethod
    def _normalize_to_01(array: np.ndarray) -> np.ndarray:
        """Нормализует массив в [0, 1].

        Args:
            array: Входной массив.

        Returns:
            Массив с тем же shape, значения в [0, 1].
        """
        min_val = array.min()
        max_val = array.max()
        if max_val - min_val < 1e-12:
            return np.zeros_like(array)
        result = (array - min_val) / (max_val - min_val)
        return result  # type: ignore[no-any-return]
