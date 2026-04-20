"""Генератор мира.

Этап 1 - Форма мира (континенты и океан):
- Многоуровневый континентальный шум -> карта высот
- Гауссово сглаживание -> чёткие границы материков
- Порог sea_level -> маска суши/океана

Этап 2 - Биомы суши:
- Низкочастотные карты температуры и влажности
- Domain warping - искажение координат для извилистых границ
- Корректировка влажности по расстоянию до океана
- Пересечение карт, биомы только на суше

Этап 3 - Водные детали:
- Глубокий океан / мелководье через distance_transform
- Замёрзший океан по температуре
- Пляж как тонкая прибрежная полоса

Этап 4 - Очистка и сборка:
- Удаление мелких изолированных компонентов
- Разбиение на чанки
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.ndimage import (
    binary_dilation,
    binary_erosion,
    distance_transform_edt,
    gaussian_filter,
    label,
)

from src.utils.noise import FractalNoiseGenerator, NoiseParams
from src.world.models import Biome, Chunk, Tile, World, WorldGenerationError


@dataclass(frozen=True)
class GenerationConfig:
    """Настройки генерации мира.

    Attributes:
        seed: Зерно генерации для воспроизводимости.
        width: Ширина мира в тайлах.
        height: Высота мира в тайлах.
        chunk_size: Размер чанка в тайлах.
        sea_level: Уровень моря (0..1). Тайлы ниже - океан.
        deep_ocean_distance: Минимальное расстояние до суши
            (в тайлах) для глубокого океана.
        gaussian_sigma: Сигма сглаживания Гауссом (0 - отключено).
            Применяется только к карте высот (форма материков).
        min_biome_size: Минимальный размер связного компонента биома
            (в тайлах). Компоненты меньше удаляются.
        ocean_moisture_weight: Вес влияния океана на влажность (0..1).
        warp_strength: Сила domain warping (в тайлах) - искажение
            координат выборки температуры/влажности для извилистых
            границ биомов. 0 - отключено.
        continental_params: Параметры шума для макро-рельефа (континенты).
        regional_params: Параметры шума для регионального рельефа.
        local_params: Параметры шума для локального микрорельефа.
        temperature_params: Параметры шума для карты температур.
        moisture_params: Параметры шума для карты влажности.
        warp_params: Параметры шума для domain warping (искажение границ).
    """

    seed: int = 42
    width: int = 1000
    height: int = 1000
    chunk_size: int = 64
    sea_level: float = 0.4
    deep_ocean_distance: float = 20.0
    gaussian_sigma: float = 0.8
    min_biome_size: int = 8
    ocean_moisture_weight: float = 0.15
    warp_strength: float = 80.0

    # Многоуровневый рельеф
    continental_params: NoiseParams = NoiseParams(
        octaves=2, frequency=0.002, persistence=0.5, lacunarity=2.0
    )
    regional_params: NoiseParams = NoiseParams(
        octaves=4, frequency=0.008, persistence=0.5, lacunarity=2.0
    )
    local_params: NoiseParams = NoiseParams(
        octaves=6, frequency=0.03, persistence=0.5, lacunarity=2.0
    )

    # Низкочастотные карты для крупных биомов
    temperature_params: NoiseParams = NoiseParams(
        octaves=2, frequency=0.002, persistence=0.5, lacunarity=2.0
    )
    moisture_params: NoiseParams = NoiseParams(
        octaves=2, frequency=0.003, persistence=0.5, lacunarity=2.0
    )

    # Domain warping - извилистые границы биомов
    warp_params: NoiseParams = NoiseParams(
        octaves=4, frequency=0.008, persistence=0.5, lacunarity=2.0
    )

    # Веса наложения уровней рельефа
    continental_weight: float = 0.7
    regional_weight: float = 0.2
    local_weight: float = 0.1

    def __post_init__(self) -> None:
        """Проверка настроек генерации."""
        if self.width <= 0 or self.height <= 0:
            raise WorldGenerationError(
                f"Размеры мира должны быть > 0, получено: "
                f"{self.width}x{self.height}"
            )
        if self.chunk_size <= 0:
            raise WorldGenerationError(
                f"Размер чанка должен быть > 0, получено: {self.chunk_size}"
            )
        if not (0 < self.sea_level < 1):
            raise WorldGenerationError(
                f"Уровень моря должен быть в (0, 1), получено: {self.sea_level}"
            )
        if self.gaussian_sigma < 0:
            raise WorldGenerationError(
                f"Сигма Гаусса должна быть >= 0, получено: "
                f"{self.gaussian_sigma}"
            )
        if self.min_biome_size < 1:
            raise WorldGenerationError(
                f"Мин. размер биома должен быть >= 1, получено: "
                f"{self.min_biome_size}"
            )
        if not (0 <= self.ocean_moisture_weight <= 1):
            raise WorldGenerationError(
                f"Вес океанной влажности должен быть в [0, 1], "
                f"получено: {self.ocean_moisture_weight}"
            )
        if self.deep_ocean_distance < 0:
            raise WorldGenerationError(
                f"Дистанция глубокого океана должна быть >= 0, получено: "
                f"{self.deep_ocean_distance}"
            )
        if self.warp_strength < 0:
            raise WorldGenerationError(
                f"Сила domain warping должна быть >= 0, получено: "
                f"{self.warp_strength}"
            )
        total_weight = (
            self.continental_weight
            + self.regional_weight
            + self.local_weight
        )
        if abs(total_weight - 1.0) > 0.01:
            raise WorldGenerationError(
                f"Веса рельефа должны давать в сумме 1.0, получено: "
                f"{total_weight}"
            )


class WorldGenerator:
    """Генератор мира на базе фрактального шума.

    Четыре этапа:
    1. Форма мира - континенты, океан, маска суши.
    2. Биомы суши - температура + влажность -> биомы на суше.
    3. Водные детали - глубокий океан, замёрзший океан, пляж.
    4. Очистка - удаление мелких компонентов, сборка чанков.

    Пример использования::

        config = GenerationConfig(seed=42, width=500, height=500)
        generator = WorldGenerator(config)
        world = generator.generate()
    """

    def __init__(self, config: GenerationConfig | None = None) -> None:
        """Инициализация генератора.

        Args:
            config: Настройки генерации. Если None, используются
                    значения по умолчанию.
        """
        self._config = config if config is not None else GenerationConfig()

    @property
    def config(self) -> GenerationConfig:
        """Текущие настройки генератора."""
        return self._config

    def generate(self) -> World:
        """Генерирует мир по текущим настройкам.

        Returns:
            Объект World со сгенерированными чанками и картами.

        Raises:
            WorldGenerationError: При ошибке генерации.
        """
        cfg = self._config

        # ЭТАП 1: Форма мира (континенты и океаны)
        elevation_map, land_mask = self._generate_land_shape(cfg)

        # ЭТАП 2: Биомы суши
        temperature_map, moisture_map = self._generate_climate_maps(
            cfg, elevation_map, land_mask
        )
        biome_map = self._generate_land_biomes(
            land_mask, elevation_map, temperature_map, moisture_map, cfg
        )

        # ЭТАП 3: Водные детали
        biome_map = self._generate_water_features(
            biome_map, land_mask, elevation_map, temperature_map, cfg
        )

        # ЭТАП 4: Очистка и сборка
        if cfg.min_biome_size > 1:
            biome_map = self._remove_small_biome_patches(
                biome_map, cfg.min_biome_size
            )

        world = World(
            seed=cfg.seed,
            width=cfg.width,
            height=cfg.height,
            chunk_size=cfg.chunk_size,
            biome_map=biome_map,
            elevation_map=elevation_map,
            temperature_map=temperature_map,
            moisture_map=moisture_map,
        )

        self._build_chunks(
            world, biome_map, elevation_map, temperature_map, moisture_map
        )

        return world

    # =================================================================
    # ЭТАП 1: Форма мира (континенты и океан)
    # =================================================================

    @staticmethod
    def _generate_land_shape(
        cfg: GenerationConfig,
    ) -> tuple[np.ndarray, np.ndarray]:
        """Генерирует карту высот и маску суши.

        Многоуровневый шум (континентальный + региональный + локальный)
        создаёт крупные массы суши и океана. Гауссово сглаживание
        убирает шумные края. Порог sea_level разделяет сушу и океан.

        Args:
            cfg: Настройки генерации.

        Returns:
            Кортеж (elevation_map, land_mask):
            - elevation_map: 2D-массив высот [0, 1]
            - land_mask: булев 2D-массив (True = суша)
        """
        # Многоуровневая карта высот
        continental_gen = FractalNoiseGenerator(
            seed=cfg.seed, params=cfg.continental_params
        )
        regional_gen = FractalNoiseGenerator(
            seed=cfg.seed + 100, params=cfg.regional_params
        )
        local_gen = FractalNoiseGenerator(
            seed=cfg.seed + 200, params=cfg.local_params
        )

        continental = continental_gen.generate_map(cfg.width, cfg.height)
        regional = regional_gen.generate_map(cfg.width, cfg.height)
        local = local_gen.generate_map(cfg.width, cfg.height)

        elevation = (
            continental * cfg.continental_weight
            + regional * cfg.regional_weight
            + local * cfg.local_weight
        )
        elevation = _normalize_to_01(elevation)

        # Гауссово сглаживание - убирает шумные края биомов
        if cfg.gaussian_sigma > 0:
            elevation = gaussian_filter(elevation, sigma=cfg.gaussian_sigma)
            elevation = _normalize_to_01(elevation)

        # Маска суши: всё выше уровня моря
        land_mask = elevation >= cfg.sea_level

        return elevation, land_mask

    # =================================================================
    # ЭТАП 2: Биомы суши
    # =================================================================

    @staticmethod
    def _generate_climate_maps(
        cfg: GenerationConfig,
        elevation: np.ndarray,
        land_mask: np.ndarray,
    ) -> tuple[np.ndarray, np.ndarray]:
        """Генерирует карты температуры и влажности с пост-обработкой.

        Включает domain warping (искажение координат для извилистых
        границ биомов) и корректировку влажности по расстоянию
        до океана. Гауссово сглаживание не применяется к климатическим
        картам - только к карте высот (на этапе 1).

        Args:
            cfg: Настройки генерации.
            elevation: 2D-массив высот [0, 1].
            land_mask: Булева маска суши.

        Returns:
            Кортеж (temperature_map, moisture_map).
        """
        # Генерация сырых карт
        temp_gen = FractalNoiseGenerator(
            seed=cfg.seed + 1, params=cfg.temperature_params
        )
        moist_gen = FractalNoiseGenerator(
            seed=cfg.seed + 2, params=cfg.moisture_params
        )

        temperature = temp_gen.generate_map(cfg.width, cfg.height)
        moisture = moist_gen.generate_map(cfg.width, cfg.height)

        # Domain warping - извилистые границы биомов
        if cfg.warp_strength > 0:
            warp_x_gen = FractalNoiseGenerator(
                seed=cfg.seed + 10, params=cfg.warp_params
            )
            warp_y_gen = FractalNoiseGenerator(
                seed=cfg.seed + 11, params=cfg.warp_params
            )

            warp_x = warp_x_gen.generate_map(cfg.width, cfg.height)
            warp_y = warp_y_gen.generate_map(cfg.width, cfg.height)

            # Смещённые координаты
            y_coords = np.arange(cfg.height, dtype=np.float64)
            x_coords = np.arange(cfg.width, dtype=np.float64)
            x_grid, y_grid = np.meshgrid(x_coords, y_coords)

            shifted_x = x_grid + (warp_x - 0.5) * cfg.warp_strength
            shifted_y = y_grid + (warp_y - 0.5) * cfg.warp_strength

            # Билинейная интерполяция для плавного результата
            temperature = _bilinear_sample(temperature, shifted_y, shifted_x)
            moisture = _bilinear_sample(moisture, shifted_y, shifted_x)

        # Корректировка влажности по расстоянию до океана
        if cfg.ocean_moisture_weight > 0:
            ocean_mask = ~land_mask
            dist_to_ocean = distance_transform_edt(ocean_mask).astype(
                np.float64
            )

            max_dist = dist_to_ocean.max()
            if max_dist > 0:
                ocean_proximity = 1.0 - dist_to_ocean / max_dist
            else:
                ocean_proximity = np.ones_like(dist_to_ocean)

            ocean_proximity[ocean_mask] = 1.0

            weight = cfg.ocean_moisture_weight
            moisture = moisture * (1.0 - weight) + ocean_proximity * weight
            moisture = _normalize_to_01(moisture)

        return temperature, moisture

    @staticmethod
    def _generate_land_biomes(
        land_mask: np.ndarray,
        elevation: np.ndarray,
        temperature: np.ndarray,
        moisture: np.ndarray,
        cfg: GenerationConfig,
    ) -> np.ndarray:
        """Назначает биомы на суше по температуре и влажности.

        Океанские тайлы получают заглушку OCEAN (будет заменена
        на этапе водных деталей). Снежные биомы SNOW не назначаются
        на суше - они генерируются как ледяные острова в океане
        на этапе водных деталей.

        Правила распределения биомов суши:
        - Пляж: высота чуть выше моря + температура выше средней
        - Тундра: низкая температура + низкая влажность
        - Тайга: низкая температура + высокая влажность
        - Пустыня: высокая температура + низкая влажность
        - Саванна: высокая температура + средняя влажность
        - Лес: средняя температура + высокая влажность
        - Луга: всё остальное

        Args:
            land_mask: Булева маска суши.
            elevation: 2D-массив высот [0, 1].
            temperature: 2D-массив температур [0, 1].
            moisture: 2D-массив влажности [0, 1].
            cfg: Настройки генерации.

        Returns:
            2D-массив биомов (океан = OCEAN заглушка).
        """
        height, width = land_mask.shape
        biome_map = np.empty((height, width), dtype=object)

        # Пороговые значения
        beach_threshold = cfg.sea_level + 0.05
        temp_high = 0.65
        temp_mid = 0.3
        temp_low = 0.15
        temp_beach = 0.4
        moist_high = 0.6
        moist_mid = 0.35

        # Океан - заглушка (будет детализирована на этапе 3)
        ocean_mask = ~land_mask
        biome_map[ocean_mask] = Biome.OCEAN

        # Пляж: высота чуть выше моря + температура выше средней
        mask_beach = (
            land_mask
            & (elevation < beach_threshold)
            & (temperature >= temp_beach)
        )

        # Суша без пляжа
        mask_inland = land_mask & (~mask_beach)

        # Тундра: низкая температура + низкая влажность
        mask_tundra = (
            mask_inland
            & (temperature < temp_mid)
            & (moisture < moist_mid)
        )

        # Тайга: низкая температура + высокая влажность
        mask_taiga = (
            mask_inland
            & (~mask_tundra)
            & (temperature < temp_mid)
            & (moisture >= moist_mid)
        )

        # Пустыня: высокая температура + низкая влажность
        mask_desert = (
            mask_inland
            & (~mask_tundra)
            & (~mask_taiga)
            & (temperature >= temp_high)
            & (moisture < moist_mid)
        )

        # Саванна: высокая температура + средняя влажность
        mask_savanna = (
            mask_inland
            & (~mask_tundra)
            & (~mask_taiga)
            & (~mask_desert)
            & (temperature >= temp_high)
            & (moisture < moist_high)
        )

        # Лес: средняя температура + высокая влажность
        mask_forest = (
            mask_inland
            & (~mask_tundra)
            & (~mask_taiga)
            & (~mask_desert)
            & (~mask_savanna)
            & (temperature >= temp_mid)
            & (moisture >= moist_high)
        )

        # Луга: всё остальное
        mask_grassland = (
            mask_inland
            & (~mask_tundra)
            & (~mask_taiga)
            & (~mask_desert)
            & (~mask_savanna)
            & (~mask_forest)
        )

        # Заполнение биомов суши
        biome_map[mask_beach] = Biome.BEACH
        biome_map[mask_tundra] = Biome.TUNDRA
        biome_map[mask_taiga] = Biome.TAIGA
        biome_map[mask_desert] = Biome.DESERT
        biome_map[mask_savanna] = Biome.SAVANNA
        biome_map[mask_forest] = Biome.FOREST
        biome_map[mask_grassland] = Biome.GRASSLAND

        return biome_map

    # =================================================================
    # ЭТАП 3: Водные детали
    # =================================================================

    @staticmethod
    def _generate_water_features(
        biome_map: np.ndarray,
        land_mask: np.ndarray,
        elevation: np.ndarray, #TODO
        temperature: np.ndarray,
        cfg: GenerationConfig,
    ) -> np.ndarray:
        """Добавляет водные детали: глубокий океан, замёрзший океан, ледяные острова.

        Заменяет заглушку OCEAN на конкретные водные биомы:
        - DEEP_OCEAN - далеко от суши
        - FROZEN_OCEAN - океан в холодных зонах
        - OCEAN - обычный мелкий океан

        Затем в замёрзшем океане генерирует ледяные острова (SNOW) -
        аналоги айсбергов, окружённые замёрзшим океаном.

        Args:
            biome_map: 2D-массив биомов (с заглушкой OCEAN).
            land_mask: Булева маска суши.
            elevation: 2D-массив высот [0, 1].
            temperature: 2D-массив температур [0, 1].
            cfg: Настройки генерации.

        Returns:
            Матрица биомов с водными деталями.
        """
        result = biome_map.copy()
        ocean_mask = ~land_mask
        temp_freeze = 0.3

        # --- Глубокий океан ---
        dist_to_land = distance_transform_edt(ocean_mask).astype(np.float64)

        # Шумим границу глубокого океана для неровного мелководья
        deep_noise_gen = FractalNoiseGenerator(
            seed=cfg.seed + 30,
            params=NoiseParams(
                octaves=3, frequency=0.01, persistence=0.5, lacunarity=2.0
            ),
        )
        deep_noise = deep_noise_gen.generate_map(cfg.width, cfg.height)
        # Асимметричный шум с затуханием:
        # Ближе к берегу - мелководье может отходить далеко,
        # дальше от берега - вероятность уменьшается (затухание).
        # Это создаёт изрезанную береговую линию и плавный
        # переход к ровной границе глубокого океана вдали от суши.
        max_offset = cfg.deep_ocean_distance * 2.5  # до 50 тайлов
        decay_scale = cfg.deep_ocean_distance * 2  # медленное затухание
        amplitude = max_offset * decay_scale / (decay_scale + dist_to_land)
        noisy_dist = (
            dist_to_land
            + deep_noise * amplitude * 1.2
            - amplitude * 1.5  # сильнее смещает к мелководью
        )

        mask_deep_ocean = noisy_dist >= cfg.deep_ocean_distance

        # Замёрзший глубокий океан
        mask_frozen_deep = ocean_mask & mask_deep_ocean & (
            temperature < temp_freeze
        )
        # Обычный глубокий океан
        mask_deep_unfrozen = ocean_mask & mask_deep_ocean & (
            temperature >= temp_freeze
        )

        # Замёрзший мелкий океан
        mask_frozen_shallow = ocean_mask & (~mask_deep_ocean) & (
            temperature < temp_freeze
        )
        # Обычный мелкий океан
        mask_ocean_shallow = ocean_mask & (~mask_deep_ocean) & (
            temperature >= temp_freeze
        )

        result[mask_frozen_deep] = Biome.FROZEN_OCEAN
        result[mask_deep_unfrozen] = Biome.DEEP_OCEAN
        result[mask_frozen_shallow] = Biome.FROZEN_OCEAN
        result[mask_ocean_shallow] = Biome.OCEAN

        # --- Постобработка глубокого океана ---
        # 1. Сглаживаем острые выступы глубокого океана через
        #    морфологическое открытие (эрозия + дилатация).
        # 2. Удаляем мелкие изолированные участки глубокого океана,
        #    окружённые мелководьем (заменяем на мелководье).
        deep_ocean_mask = (result == Biome.DEEP_OCEAN) | (
            result == Biome.FROZEN_OCEAN
        )

        # Морфологическое открытие: эрозия срезает выступы,
        # дилатация восстанавливает основное тело.
        # 4 итерации для агрессивного сглаживания выступов до 4 тайлов.
        structure = np.ones((3, 3), dtype=int)
        eroded = deep_ocean_mask.copy()
        for _ in range(4):
            eroded = binary_erosion(eroded, structure=structure)
        smoothed_deep = eroded
        for _ in range(4):
            smoothed_deep = binary_dilation(smoothed_deep, structure=structure)

        # Заменяем сглаженные выступы на мелководье
        protrusions = deep_ocean_mask & (~smoothed_deep)
        if protrusions.any():
            # В холодных зонах - замёрзшее мелководье, в тёплых - обычное
            cold_protrusions = protrusions & (temperature < temp_freeze)
            warm_protrusions = protrusions & (temperature >= temp_freeze)
            result[cold_protrusions] = Biome.FROZEN_OCEAN
            result[warm_protrusions] = Biome.OCEAN

        # Удаляем мелкие изолированные участки глубокого океана
        current_deep = (result == Biome.DEEP_OCEAN) | (
            result == Biome.FROZEN_OCEAN
        )
        if current_deep.any():
            labeled_deep, num_deep = label(
                current_deep, structure=np.ones((3, 3), dtype=int)
            )
            min_deep_size = cfg.min_biome_size * 32
            for comp_id in range(1, num_deep + 1):
                comp = labeled_deep == comp_id
                if comp.sum() < min_deep_size:
                    # Заменяем на мелководье в зависимости от температуры
                    cold_comp = comp & (temperature < temp_freeze)
                    warm_comp = comp & (temperature >= temp_freeze)
                    result[cold_comp] = Biome.FROZEN_OCEAN
                    result[warm_comp] = Biome.OCEAN

        # Ледяные острова
        # В глубоком замёрзшем океане (вдали от суши) генерируем
        # острова льда (SNOW), используя отдельный шум.
        # Только глубокий океан - острова не касаются материков.
        ice_island_gen = FractalNoiseGenerator(
            seed=cfg.seed + 20,
            params=NoiseParams(
                octaves=2, frequency=0.006, persistence=0.5, lacunarity=2.0
            ),
        )
        ice_noise = ice_island_gen.generate_map(cfg.width, cfg.height)

        # Ледяные острова: только глубокий замёрзший океан + шум выше порога
        deep_frozen_mask = (
            (result == Biome.FROZEN_OCEAN) & mask_deep_ocean
        )
        ice_island_mask = deep_frozen_mask & (ice_noise > 0.55)

        # Удаляем слишком мелкие ледяные острова
        if ice_island_mask.any():
            labeled_ice, num_ice = label(
                ice_island_mask, structure=np.ones((3, 3), dtype=int)
            )
            for comp_id in range(1, num_ice + 1):
                comp = labeled_ice == comp_id
                if comp.sum() < cfg.min_biome_size * 6:
                    ice_island_mask[comp] = False

        result[ice_island_mask] = Biome.SNOW

        return result

    # =================================================================
    # ЭТАП 4: Очистка и сборка
    # =================================================================

    @staticmethod
    def _remove_small_biome_patches(
        biome_map: np.ndarray, min_size: int
    ) -> np.ndarray:
        """Удаляет мелкие изолированные компоненты биомов.

        Для каждого биома находит связные компоненты и заменяет
        компоненты размером < min_size на биом ближайшего крупного
        соседа.

        Args:
            biome_map: 2D-массив объектов Biome.
            min_size: Минимальный размер компонента в тайлах.

        Returns:
            Очищенная матрица биомов.
        """
        result = biome_map.copy()

        for biome in Biome:
            mask = biome_map == biome
            if not mask.any():
                continue

            labeled_arr, num_features = label(
                mask, structure=np.ones((3, 3), dtype=int)
            )

            for component_id in range(1, num_features + 1):
                component_mask = labeled_arr == component_id
                component_size = int(component_mask.sum())

                if component_size < min_size:
                    replacement = _find_neighbor_biome(result, component_mask)
                    result[component_mask] = replacement

        return result

    @staticmethod
    def _build_chunks(
        world: World,
        biome_map: np.ndarray,
        elevation: np.ndarray,
        temperature: np.ndarray,
        moisture: np.ndarray,
    ) -> None:
        """Разбивает матрицу биомов на чанки и заполняет world.chunks.

        Args:
            world: Объект World для заполнения чанками.
            biome_map: 2D-массив биомов.
            elevation: 2D-массив высот.
            temperature: 2D-массив температур.
            moisture: 2D-массив влажности.
        """
        cs = world.chunk_size
        chunks_x = world.chunks_x
        chunks_y = world.chunks_y

        for cy in range(chunks_y):
            for cx in range(chunks_x):
                x_start = cx * cs
                y_start = cy * cs
                x_end = min(x_start + cs, world.width)
                y_end = min(y_start + cs, world.height)

                biome_slice = biome_map[y_start:y_end, x_start:x_end]
                elev_slice = elevation[y_start:y_end, x_start:x_end]
                temp_slice = temperature[y_start:y_end, x_start:x_end]
                moist_slice = moisture[y_start:y_end, x_start:x_end]

                chunk_height, chunk_width = biome_slice.shape
                tiles = np.empty((chunk_height, chunk_width), dtype=object)

                for ly in range(chunk_height):
                    for lx in range(chunk_width):
                        tiles[ly, lx] = Tile(
                            biome=biome_slice[ly, lx],
                            temperature=float(temp_slice[ly, lx]),
                            moisture=float(moist_slice[ly, lx]),
                            elevation=float(elev_slice[ly, lx]),
                        )

                chunk = Chunk(x=cx, y=cy, tiles=tiles)
                world.chunks[(cx, cy)] = chunk


# =====================================================================
# Вспомогательные функции (не зависят от WorldGenerator)
# =====================================================================


def _normalize_to_01(array: np.ndarray) -> np.ndarray:
    """Нормализует массив значений в диапазон [0, 1].

    Args:
        array: Входной массив произвольных значений.

    Returns:
        Массив с тем же shape, значения в [0, 1].
    """
    min_val = array.min()
    max_val = array.max()
    if max_val - min_val < 1e-12:
        return np.zeros_like(array)
    return (array - min_val) / (max_val - min_val)


def _find_neighbor_biome(
    biome_map: np.ndarray,
    component_mask: np.ndarray,
) -> Biome:
    """Определяет биом-заместитель для мелкого компонента.

    Ищет ближайший соседний тайл, не принадлежащий данному
    компоненту, и возвращает его биом.

    Args:
        biome_map: Полная матрица биомов.
        component_mask: Бинарная маска удаляемого компонента.

    Returns:
        Биом ближайшего соседа (по умолчанию OCEAN).
    """
    dilated = binary_dilation(component_mask, structure=np.ones((3, 3)))
    border = dilated & (~component_mask)

    border_biomes = biome_map[border]
    if border_biomes.size == 0:
        return Biome.OCEAN

    freq: dict[Biome, int] = {}
    for b in border_biomes.flat:
        freq[b] = freq.get(b, 0) + 1
    return max(freq, key=freq.get)  # type: ignore[arg-type]


def _bilinear_sample(
    array: np.ndarray,
    y_coords: np.ndarray,
    x_coords: np.ndarray,
) -> np.ndarray:
    """Билинейная интерполяция 2D-массива по вещественным координатам.

    Координаты за пределами массива ограничиваются до
    допустимого диапазона. Это гарантирует отсутствие артефактов
    на границах карты.

    Args:
        array: Исходный 2D-массив значений.
        y_coords: 2D-массив вещественных Y-координат.
        x_coords: 2D-массив вещественных X-координат.

    Returns:
        2D-массив интерполированных значений того же shape.
    """
    height, width = array.shape

    # Ограничение координат в допустимый диапазон
    y_clamped = np.clip(y_coords, 0, height - 1.001)
    x_clamped = np.clip(x_coords, 0, width - 1.001)

    y0 = np.floor(y_clamped).astype(int)
    x0 = np.floor(x_clamped).astype(int)
    y1 = np.minimum(y0 + 1, height - 1)
    x1 = np.minimum(x0 + 1, width - 1)

    fy = y_clamped - y0
    fx = x_clamped - x0

    # Билинейная интерполяция
    result = (
        array[y0, x0] * (1 - fy) * (1 - fx)
        + array[y0, x1] * (1 - fy) * fx
        + array[y1, x0] * fy * (1 - fx)
        + array[y1, x1] * fy * fx
    )

    return result
