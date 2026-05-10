"""Рендер мира: два слоя (поверхность + объекты).

Слой поверхности - цветные квадратики по биомам.
Слой объектов - декоративные объекты (деревья, камни, трава).

Оптимизация:
- Спрайты создаются прогрессивно (build_pending_chunks),
  не более N чанков за кадр.
- Отрисовываются только SpriteList видимых чанков.
"""

from __future__ import annotations

import glob
from dataclasses import dataclass
from typing import TYPE_CHECKING, Optional

import arcade

from src.engine.camera import GameCamera
from src.engine.layers import (
    BIOME_COLORS,
    FALLBACK_MAP,
    PLACEMENT_RULES,
    ObjectPlacementRule,
    ObjectType,
)
from src.world.autotiler import SAND_DARK, SAND_LIGHT, SAND_MEDIUM
from src.world.models import Biome, Chunk, World

if TYPE_CHECKING:
    from src.engine.player import Player


@dataclass(frozen=True)
class _Placement:
    """Предвычисленное размещение объекта на карте."""

    obj_type: ObjectType
    variant_idx: int
    is_flipped: bool


class Renderer:
    """Рендер мира с двумя слоями: поверхность и объекты.

    Attributes:
        tile_size: Размер тайла в пикселях.
    """

    def __init__(self, world: World, tile_size: int = 32) -> None:
        """Инициализация рендера.

        Спрайты создаются прогрессивно через
        build_pending_chunks(). Размещения объектов
        предвычисляются лениво при первом вызове
        build_pending_chunks().

        Args:
            world: Сгенерированный мир.
            tile_size: Размер тайла в пикселях.
        """
        self._world = world
        self.tile_size = tile_size

        # NEAREST-фильтр для пиксель-арта (без размытия при зуме)
        arcade.SpriteList.DEFAULT_TEXTURE_FILTER = (
            arcade.gl.NEAREST,
            arcade.gl.NEAREST,
        )

        # Кэш текстур поверхности (биомы + автотайлинг)
        self._biome_textures: dict[Biome, arcade.Texture] = {}
        self._sand_textures: dict[int, arcade.Texture] = {}
        self._build_surface_textures()

        # Кэш текстур объектов (списки вариантов)
        self._obj_textures: dict[ObjectType, list[arcade.Texture]] = {}
        self._build_object_textures()

        # Предвычисленные размещения объектов
        # Вычисляются лениво при первом вызове
        # build_pending_chunks()
        self._placements: dict[tuple[int, int], _Placement] = {}
        self._placements_computed: bool = False

    # ================================================================
    # Очистка ресурсов
    # ================================================================

    def cleanup(self) -> None:
        """Освобождает спрайты, текстуры и размещения.

        Вызывается при возврате в меню для уменьшения RSS
        процесса, что ускоряет fork() при следующей
        генерации мира.
        """
        # Очищаем спрайт-листы чанков
        for chunk in self._world.chunks.values():
            if chunk.surface_sprite_list is not None:
                chunk.surface_sprite_list.clear()
                chunk.surface_sprite_list = None
            if chunk.object_sprite_list is not None:
                chunk.object_sprite_list.clear()
                chunk.object_sprite_list = None

        # Очищаем кэши текстур
        self._biome_textures.clear()
        self._sand_textures.clear()
        self._obj_textures.clear()

        # Очищаем размещения
        self._placements.clear()
        self._placements_computed = False

    # ================================================================
    # API
    # ================================================================

    def draw(
        self,
        camera: GameCamera,
        player: Optional["Player"] = None,
    ) -> None:
        """Отрисовывает видимые чанки и игрока.

        Рисует только чанки, спрайты которых уже созданы
        через build_pending_chunks(). Алгоритм художника:
        дальние объекты рисуются раньше ближних.
        Игрок рисуется в слое объектов с учётом Z-порядка
        - внутри чанка игрока объекты разбиваются на
        "далёкие" (выше игрока) и "ближние" (ниже).

        Args:
            camera: Активная камера.
            player: Игровой персонаж (опционально).
        """
        visible = camera.visible_chunks(self._world.chunk_size)

        # Сортируем чанки: дальние (малый cy = верх мира) первыми
        sorted_chunks = sorted(visible, key=lambda c: c[1])

        # Поверхность: дальние чанки рисуются первыми
        for cx, cy in sorted_chunks:
            chunk = self._world.get_chunk(cx, cy)
            if chunk is None:
                continue
            if chunk.surface_sprite_list is not None:
                chunk.surface_sprite_list.draw()

        # Объекты + игрок: Z-порядок с учётом позиции
        # внутри чанка игрока
        player_drawn = False
        player_sprite = player.get_sprite() if player else None

        # Определяем чанк игрока по Y-позиции
        player_cx: int = -1
        player_cy: int = -1
        player_pixel_y: float = 0.0
        if player is not None and player_sprite is not None:
            cs = self._world.chunk_size
            # Переводим пиксельную Y в индекс чанка
            # (переворот: пиксель y=0 внизу, ty=0 верх)
            ty = self._world.height - 1 - int(
                player.world_y / self.tile_size
            )
            player_cx = max(0, tx // cs) if (tx := int(player.world_x / self.tile_size)) >= 0 else -1  # noqa: E501
            player_cy = max(0, ty // cs)
            player_pixel_y = player_sprite.center_y

        for cx, cy in sorted_chunks:
            # Перед чанком, который ближе чем игрок -
            # рисуем игрока
            if (
                not player_drawn
                and player_sprite is not None
                and cy > player_cy
            ):
                self._draw_player_sprite(player_sprite)
                player_drawn = True

            chunk = self._world.get_chunk(cx, cy)
            if chunk is None:
                continue

            obj_list = chunk.object_sprite_list
            if obj_list is None:
                continue

            # Чанк игрока: разбиваем объекты на
            # "далёкие" (выше) и "ближние" (ниже)
            # Сравниваем по основанию спрайта (нижний край),
            # а не по центру - чтобы высокие деревья
            # с кроной наверху не считались "далёкими"
            is_player_chunk = (
                cx == player_cx and cy == player_cy
            )
            if (
                is_player_chunk
                and not player_drawn
                and player_sprite is not None
            ):
                player_base = player_pixel_y - player_sprite.height / 2.0
                self._draw_chunk_split(
                    obj_list, player_base, player_sprite
                )
                player_drawn = True
            else:
                obj_list.draw()

        # Если игрок ещё не нарисован - он самый ближний
        if not player_drawn and player_sprite is not None:
            self._draw_player_sprite(player_sprite)

    def _draw_chunk_split(
        self,
        obj_list: arcade.SpriteList[arcade.Sprite],
        player_y: float,
        player_sprite: arcade.Sprite,
    ) -> None:
        """Рисует чанк с вставкой игрока по Z-порядку.

        Сравнение идёт по **основанию** спрайта (нижний край),
        а не по центру - чтобы высокие деревья с кроной
        наверху не считались "далёкими" когда их ствол
        находится рядом с игроком.

        Args:
            obj_list: SpriteList объектов чанка (отсортирован
                по убыванию основания - дальние первыми).
            player_y: Y-позиция основания игрока в пикселях.
            player_sprite: Спрайт игрока.
        """
        if not hasattr(self, "_split_far"):
            self._split_far: arcade.SpriteList[
                arcade.Sprite
            ] = arcade.SpriteList()
            self._split_near: arcade.SpriteList[
                arcade.Sprite
            ] = arcade.SpriteList()

        self._split_far.clear()
        self._split_near.clear()

        for sprite in obj_list:
            # Основание спрайта = нижний край
            sprite_base = sprite.center_y - sprite.height / 2.0
            if sprite_base > player_y:
                self._split_far.append(sprite)
            else:
                self._split_near.append(sprite)

        # Далёкие -> игрок -> ближние
        self._split_far.draw()
        self._draw_player_sprite(player_sprite)
        self._split_near.draw()

    def _draw_player_sprite(self, sprite: arcade.Sprite) -> None:
        """Рисует спрайт игрока через маленький SpriteList.

        Args:
            sprite: Спрайт игрока.
        """
        if not hasattr(self, "_player_spritelist"):
            self._player_spritelist: arcade.SpriteList[
                arcade.Sprite
            ] = arcade.SpriteList()
        # Очищаем и добавляем текущий спрайт
        self._player_spritelist.clear()
        self._player_spritelist.append(sprite)
        self._player_spritelist.draw()

    # ================================================================
    # Прогрессивная загрузка
    # ================================================================

    def build_pending_chunks(
        self,
        camera: GameCamera,
        max_per_frame: int = 2,
        time_budget: float = 0.008,
    ) -> int:
        """Прогрессивно создаёт спрайты для видимых чанков.

        Args:
            camera: Активная камера.
            max_per_frame: Макс. количество новых чанков за кадр.
            time_budget: Макс. время на построение (сек).

        Returns:
            Количество построенных чанков.
        """
        import time as _time

        # Ленивое предвычисление размещений объектов
        if not self._placements_computed:
            self._precompute_placements()
            self._placements_computed = True

        visible = camera.visible_chunks(self._world.chunk_size)

        # Находим чанки без спрайтов
        pending: list[tuple[int, int, Chunk]] = []
        for cx, cy in visible:
            chunk = self._world.get_chunk(cx, cy)
            if chunk is None:
                continue
            if chunk.surface_sprite_list is None:
                pending.append((cx, cy, chunk))

        if not pending:
            return 0

        # Сортируем по расстоянию до камеры (ближние первыми)
        cam_pos = camera.position
        cs = self._world.chunk_size
        cam_cx = cam_pos[0] / (cs * self.tile_size)
        cam_cy = cam_pos[1] / (cs * self.tile_size)
        pending.sort(
            key=lambda p: (p[0] - cam_cx) ** 2
            + (p[1] - cam_cy) ** 2
        )

        # Создаём спрайты с ограничением по кол-ву и времени
        built = 0
        t0 = _time.perf_counter()
        for cx, cy, chunk in pending[:max_per_frame]:
            chunk.surface_sprite_list = (
                self._build_surface_sprites(chunk)
            )
            chunk.object_sprite_list = (
                self._build_object_sprites(chunk)
            )
            built += 1
            # Проверяем бюджет времени после каждого чанка
            if _time.perf_counter() - t0 >= time_budget:
                break
        return built

    # ================================================================
    # Текстуры поверхности
    # ================================================================

    # Маппинг биом -> путь к текстуре
    _BIOME_TEXTURE_PATHS: dict[Biome, str] = {
        Biome.DEEP_OCEAN: "assets/textures/ocean/deep_ocean.png",
        Biome.OCEAN: "assets/textures/ocean/ocean.png",
        Biome.FROZEN_OCEAN: "assets/textures/ocean/ice.png",
        Biome.DESERT: "assets/textures/sand/sand_light.png",
        Biome.SAVANNA: "assets/textures/savanna/savanna.png",
        Biome.GRASSLAND: "assets/textures/grass/grassland.png",
        Biome.FOREST: "assets/textures/grass/forest.png",
        Biome.TAIGA: "assets/textures/grass/taiga.png",
        Biome.TUNDRA: "assets/textures/grass/tundra.png",
        Biome.SNOW: "assets/textures/snow/snow.png",
    }

    # Маппинг autotile_mask -> путь к текстуре песка
    _SAND_TEXTURE_PATHS: dict[int, str] = {
        SAND_DARK: "assets/textures/sand/sand_dark.png",
        SAND_MEDIUM: "assets/textures/sand/sand_medium.png",
        SAND_LIGHT: "assets/textures/sand/sand_light.png",
    }

    def _build_surface_textures(self) -> None:
        """Загружает текстуры для всех биомов и автотайлинга."""
        from PIL import Image

        ts = self.tile_size

        # Текстуры биомов
        for biome, path in self._BIOME_TEXTURE_PATHS.items():
            img = Image.open(path).convert("RGBA")
            if img.size != (ts, ts):
                img = img.resize((ts, ts), Image.Resampling.NEAREST)
            tex = arcade.Texture(image=img, size=(ts, ts))
            self._biome_textures[biome] = tex

        # Текстуры автотайлинга песка
        for mask_val, path in self._SAND_TEXTURE_PATHS.items():
            img = Image.open(path).convert("RGBA")
            if img.size != (ts, ts):
                img = img.resize((ts, ts), Image.Resampling.NEAREST)
            tex = arcade.Texture(image=img, size=(ts, ts))
            self._sand_textures[mask_val] = tex

    # ================================================================
    # Спрайты поверхности
    # ================================================================

    def _build_surface_sprites(
        self, chunk: Chunk
    ) -> arcade.SpriteList[arcade.Sprite]:
        """Создаёт спрайты поверхности для чанка.

        Все биомы используют текстуры. Песок (BEACH) -
        автотайлинг, пустыня (DESERT) - светлый песок.
        Текстуры поворачиваются на 0/90/180/270°
        детерминированно по координатам тайла и сиду.

        Args:
            chunk: Чанк для отрисовки.

        Returns:
            SpriteList со спрайтами поверхности.
        """
        cs = self._world.chunk_size
        sprite_list: arcade.SpriteList[arcade.Sprite] = arcade.SpriteList()

        for ly in range(chunk.tiles.shape[0]):
            for lx in range(chunk.tiles.shape[1]):
                tile = chunk.tiles[ly, lx]

                # Мировые координаты центра тайла
                tx = chunk.x * cs + lx
                ty = chunk.y * cs + ly
                cx_px = tx * self.tile_size + self.tile_size / 2.0
                cy_px = (
                    self._world.height - 1 - ty
                ) * self.tile_size + self.tile_size / 2.0

                # Выбираем текстуру
                tex: arcade.Texture | None = None
                if (
                    tile.biome == Biome.BEACH
                    and tile.autotile_mask in self._sand_textures
                ):
                    tex = self._sand_textures[tile.autotile_mask]
                elif tile.biome in self._biome_textures:
                    tex = self._biome_textures[tile.biome]

                if tex is not None:
                    sprite = arcade.Sprite(
                        tex,
                        center_x=cx_px,
                        center_y=cy_px,
                    )
                    sprite.width = self.tile_size
                    sprite.height = self.tile_size
                    # Детерминированный поворот
                    angle_hash = self._deterministic_hash(
                        tx, ty, self._world.seed + 99
                    )
                    sprite.angle = (angle_hash % 4) * 90.0
                else:
                    # Запасной вариант: цветной квадратик
                    color = BIOME_COLORS.get(tile.biome, (255, 0, 255))
                    sprite = arcade.SpriteSolidColor(
                        width=self.tile_size,
                        height=self.tile_size,
                        color=(*color, 255),
                        center_x=cx_px,
                        center_y=cy_px,
                    )

                sprite_list.append(sprite)

        return sprite_list

    # ================================================================
    # Спрайты объектов
    # ================================================================

    def _precompute_placements(self) -> None:
        """Предвычисляет размещения объектов для всего мира.

        Итерирует по всем чанкам в детерминированном порядке
        (сортировка по cy, cx). Размещения не зависят от того,
        в каком порядке чанки попадают в видимую область.
        """
        occupied: set[tuple[int, int]] = set()
        cs = self._world.chunk_size

        # Группируем правила по биому
        rules_by_biome: dict[Biome, list[ObjectPlacementRule]] = {}
        for rule in PLACEMENT_RULES:
            rules_by_biome.setdefault(rule.biome, []).append(rule)

        # Детерминированный порядок: сортируем по (cy, cx)
        sorted_chunks = sorted(
            self._world.chunks.values(), key=lambda c: (c.y, c.x)
        )

        for chunk in sorted_chunks:
            for ly in range(chunk.tiles.shape[0]):
                for lx in range(chunk.tiles.shape[1]):
                    tile = chunk.tiles[ly, lx]
                    biome = tile.biome

                    if biome.is_water:
                        continue

                    tx = chunk.x * cs + lx
                    ty = chunk.y * cs + ly

                    if (tx, ty) in occupied:
                        continue

                    rules = rules_by_biome.get(biome)
                    if not rules:
                        continue

                    for rule in rules:
                        if not self._can_place_anchor(
                            tx, ty, rule, rules_by_biome
                        ):
                            continue

                        if rule.shore_only and not self._is_adjacent_to_water(
                            tx, ty
                        ):
                            continue

                        # Цветы: зонная генерация (поляны)
                        density = rule.density
                        if rule.object_type == ObjectType.FLOWER:
                            if not self._is_flower_zone(tx, ty):
                                continue
                            density = 0.35

                        obj_id = sum(
                            ord(c) * (i + 1)
                            for i, c in enumerate(
                                rule.object_type.label
                            )
                        )
                        prob = (self._deterministic_hash(
                            tx, ty, self._world.seed + 66, obj_id,
                        ) % 10000) / 10000.0
                        if prob >= density:
                            continue

                        # Проверяем наложение на занятые тайлы
                        obj = rule.object_type
                        obj_tiles = self._get_obj_tiles(tx, ty, obj)

                        if any(t in occupied for t in obj_tiles):
                            fallback = FALLBACK_MAP.get(obj)
                            if fallback is None:
                                continue
                            obj = fallback
                            obj_tiles = [(tx, ty)]
                            if (tx, ty) in occupied:
                                continue

                        # Детерминированный выбор варианта
                        variants = self._obj_textures.get(obj, [])
                        if not variants:
                            continue
                        idx = self._deterministic_hash(
                            tx, ty, self._world.seed + 77
                        ) % len(variants)

                        # Детерминированное отражение
                        flip_hash = self._deterministic_hash(
                            tx, ty, self._world.seed + 88
                        )
                        is_flipped = flip_hash % 2 == 0

                        # Сохраняем размещение
                        self._placements[(tx, ty)] = _Placement(
                            obj_type=obj,
                            variant_idx=idx,
                            is_flipped=is_flipped,
                        )

                        for ot in obj_tiles:
                            occupied.add(ot)

                        break

    def _build_object_sprites(
        self, chunk: Chunk
    ) -> arcade.SpriteList[arcade.Sprite]:
        """Создаёт спрайты объектов для чанка из предвычисленных
        размещений.

        Args:
            chunk: Чанк для отрисовки.

        Returns:
            SpriteList со спрайтами объектов.
        """
        cs = self._world.chunk_size
        sprite_list: arcade.SpriteList[arcade.Sprite] = arcade.SpriteList()
        height = self._world.height

        for ly in range(chunk.tiles.shape[0]):
            for lx in range(chunk.tiles.shape[1]):
                tx = chunk.x * cs + lx
                ty = chunk.y * cs + ly

                placement = self._placements.get((tx, ty))
                if placement is None:
                    continue

                obj = placement.obj_type
                variants = self._obj_textures.get(obj, [])
                if not variants:
                    continue

                tex = variants[placement.variant_idx % len(variants)]
                px_w = tex.width
                px_h = tex.height

                cx_px, cy_px = self._object_position(tx, ty, height)

                sprite = arcade.Sprite(
                    tex,
                    center_x=cx_px,
                    center_y=cy_px + px_h / 2.0,
                )
                sprite.width = px_w
                sprite.height = px_h

                if placement.is_flipped:
                    sprite.scale_x = -sprite.scale_x

                sprite_list.append(sprite)

        # Z-сортировка
        # Сортируем по нижнему краю спрайта (основанию)
        sprite_list.sort(
            key=lambda s: -(s.center_y - s.height / 2.0)
        )
        return sprite_list

    def _get_obj_tiles(
        self, tx: int, ty: int, obj: ObjectType
    ) -> list[tuple[int, int]]:
        """Возвращает список тайлов, занимаемых объектом.

        Args:
            tx: X-координата якоря.
            ty: Y-координата якоря.
            obj: Тип объекта.

        Returns:
            Список координат (x, y) всех занимаемых тайлов.
        """
        tiles = []
        for dy in range(obj.tile_height):
            for dx in range(obj.tile_width):
                tiles.append((tx + dx, ty - dy))
        return tiles

    @staticmethod
    def _deterministic_hash(*args: int) -> int:
        """Детерминированный хеш с хорошим перемешиванием битов.

        FNV-1a + MurmurHash3: даёт визуально
        случайное распределение.

        Args:
            *args: Числа для хеширования.

        Returns:
            Целочисленный хеш (32 бита).
        """
        # FNV-1a
        h = 0x811C9DC5
        for a in args:
            h ^= a & 0xFFFFFFFF
            h = (h * 0x01000193) & 0xFFFFFFFF
        # MurmurHash3
        h ^= h >> 16
        h = (h * 0x85EBCA6B) & 0xFFFFFFFF
        h ^= h >> 13
        h = (h * 0xC2B2AE35) & 0xFFFFFFFF
        h ^= h >> 16
        return h

    def _is_flower_zone(self, tx: int, ty: int) -> bool:
        """Определяет, находится ли тайл в зоне цветочной поляны.

        Мир разбит на зоны 8x8 тайлов. Каждая зона детерминированно
        (по хешу) является или не является цветочной поляной.

        Args:
            tx: X-координата тайла.
            ty: Y-координата тайла.

        Returns:
            True, если зона - цветочная поляна.
        """
        zone_size = 8
        zone_x = tx // zone_size
        zone_y = ty // zone_size
        zone_seed = self._deterministic_hash(
            zone_x, zone_y, self._world.seed + 50
        )
        return (zone_seed % 10000) / 10000.0 < 0.4

    def _can_place_anchor(
        self,
        tx: int,
        ty: int,
        rule: ObjectPlacementRule,
        rules_by_biome: dict[Biome, list[ObjectPlacementRule]],
    ) -> bool:
        """Можно ли разместить объект якорём в (tx, ty)?

        Для многотайловых объектов проверяет, что все занимаемые
        тайлы допускают данный тип объекта.

        Args:
            tx: X-координата якоря.
            ty: Y-координата якоря.
            rule: Правило размещения.
            rules_by_biome: Маппинг биом -> правила.

        Returns:
            True, если объект можно разместить.
        """
        obj = rule.object_type
        ow = obj.tile_width
        oh = obj.tile_height

        for dy in range(oh):
            for dx in range(ow):
                ntx = tx + dx
                nty = ty - dy
                tile = self._world.get_tile(ntx, nty)
                if tile is None:
                    return False
                if obj not in {
                    r.object_type for r in rules_by_biome.get(tile.biome, [])
                }:
                    return False

        return True

    def _is_adjacent_to_water(self, tx: int, ty: int) -> bool:
        """Проверяет 4 соседей, рядом с водой ли тайл.

        Args:
            tx: X-координата тайла.
            ty: Y-координата тайла.

        Returns:
            True, если хотя бы один сосед - вода.
        """
        for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
            tile = self._world.get_tile(tx + dx, ty + dy)
            if tile is not None and tile.biome.is_water:
                return True
        return False

    def _object_position(
        self,
        tx: int,
        ty: int,
        world_height: int,
    ) -> tuple[float, float]:
        """Пиксельная позиция центра объекта.

        Объект крепится к центру якорного тайла -
        спрайт центрируется на тайле независимо от
        собственных размеров.

        Args:
            tx: X-координата якорного тайла.
            ty: Y-координата якорного тайла.
            world_height: Высота мира в тайлах.

        Returns:
            Кортеж (center_x, center_y) в пикселях.
        """
        ts = self.tile_size

        # Центр якорного тайла
        center_x = tx * ts + ts / 2.0
        center_y = (world_height - 1 - ty) * ts + ts / 2.0

        return center_x, center_y

    # ================================================================
    # Генерация текстур объектов
    # ================================================================

    # Маппинг ObjectType.label -> (папка, префикс файла)
    #   Пустая строка "" - загрузить все файлы из папки.
    _PLANT_FOLDERS: dict[str, tuple[str, str]] = {
        # Лиственные деревья (assets/plants/tree/)
        "tree_oak": ("assets/plants/tree", "oak"),
        "tree_birch": ("assets/plants/tree", "birch"),
        "tree_baobab": ("assets/plants/tree", "baobab"),
        "tree_poplar": ("assets/plants/tree", "poplar"),
        "tree_ash": ("assets/plants/tree", "ash"),
        "tree_chestnut": ("assets/plants/tree", "chestnut"),
        "tree_willow": ("assets/plants/tree", "willow"),
        # Хвойные деревья (assets/plants/pine_tree/)
        "tree_pine": ("assets/plants/pine_tree", ""),
        # Кусты (assets/plants/bush/)
        "bush": ("assets/plants/bush", ""),
        # Трава (assets/plants/grass/)
        "grass_tuft_small": ("assets/plants/grass", ""),
        "grass_tuft": ("assets/plants/grass", ""),
        # Цветы (assets/plants/flower/)
        "flower": ("assets/plants/flower", ""),
        # Кактус (assets/plants/cactus/)
        "cactus": ("assets/plants/cactus", ""),
        # Перекати-поле (assets/plants/tumbleweed/)
        "tumbleweed": ("assets/plants/tumbleweed", ""),
        # Тростник (assets/plants/reed/)
        "reed": ("assets/plants/reed", ""),
        # Пальма (assets/plants/palm/)
        "palm": ("assets/plants/palm", ""),
        # Камни (assets/stones/)
        "rock_small": ("assets/stones", "small_stone"),
        "rock_large": ("assets/stones", "large_stone"),
        # Тундровые кусты (assets/plants/tundra_bush/)
        "tundra_bush": ("assets/plants/tundra_bush", ""),
    }

    def _build_object_textures(self) -> None:
        """Загружает текстуры объектов из PNG или генерирует PIL."""
        ts = self.tile_size

        for obj_type in ObjectType:
            label = obj_type.label
            entry = self._PLANT_FOLDERS.get(label)

            if entry is not None:
                folder, prefix = entry
                # Загружаем PNG-варианты с префиксной фильтрацией
                variants = self._load_plant_variants(folder, prefix)
                if variants:
                    self._obj_textures[obj_type] = variants
                    continue

            # Fallback: генерируем PIL-фигуру
            tex = self._generate_pil_texture(obj_type, ts)
            self._obj_textures[obj_type] = [tex]

    def _load_plant_variants(
        self, folder: str, prefix: str = ""
    ) -> list[arcade.Texture]:
        """Загружает PNG-варианты из папки с опциональной
        фильтрацией по префиксу имени файла.

        Args:
            folder: Путь к папке с PNG-файлами.
            prefix: Префикс имени файла (без расширения).
                Пустая строка - загрузить все файлы.

        Returns:
            Список текстур Arcade.
        """
        from PIL import Image

        # Ищем PNG-файлы в папке
        paths = sorted(glob.glob(f"{folder}/*.png"))

        if not paths:
            return []

        # Фильтрация по префиксу
        if prefix:
            import os

            paths = [
                p
                for p in paths
                if os.path.basename(p).startswith(prefix)
            ]

        if not paths:
            return []

        variants: list[arcade.Texture] = []
        for path in paths:
            img = Image.open(path).convert("RGBA")
            tex = arcade.Texture(image=img, size=img.size)
            variants.append(tex)
        return variants

    @staticmethod
    def _generate_pil_texture(obj_type: ObjectType, ts: int) -> arcade.Texture:
        """Генерирует текстуру объекта через PIL (fallback)."""
        from PIL import Image, ImageDraw

        w = obj_type.tile_width * ts
        h = obj_type.tile_height * ts
        color = obj_type.color + (255,)

        img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        label = obj_type.label

        if label.startswith("tree_"):
            trunk_w = max(ts // 6, 2)
            trunk_h = ts // 2
            trunk_x = w // 2 - trunk_w // 2
            draw.rectangle(
                [trunk_x, h - trunk_h, trunk_x + trunk_w, h],
                fill=(100, 70, 40, 255),
            )
            crown_r = int(ts * 0.45)
            draw.ellipse(
                [
                    w // 2 - crown_r,
                    h // 2 - ts // 6 - crown_r,
                    w // 2 + crown_r,
                    h // 2 - ts // 6 + crown_r,
                ],
                fill=color,
            )
        elif label.startswith("rock_"):
            margin = max(ts // 8, 1)
            draw.polygon(
                [
                    (margin, h - margin),
                    (margin + ts // 6, margin),
                    (w - margin - ts // 6, margin + ts // 8),
                    (w - margin, h - margin - ts // 6),
                    (w - margin - ts // 4, h - margin),
                ],
                fill=color,
            )
        elif label == "tundra_bush":
            rx = int(ts * 0.4)
            ry = int(ts * 0.25)
            cx, cy = w // 2, h // 2 + ts // 8
            draw.ellipse([cx - rx, cy - ry, cx + rx, cy + ry], fill=color)
        elif label == "grass_tuft":
            blade_w = max(ts // 8, 1)
            for i in range(5):
                bx = w // 6 + i * w // 5 - blade_w // 2
                draw.rectangle([bx, h // 3, bx + blade_w, h], fill=color)
        elif label == "grass_tuft_small":
            blade_w = max(ts // 8, 1)
            for i in range(3):
                bx = w // 4 + i * w // 4 - blade_w // 2
                draw.rectangle([bx, h // 3, bx + blade_w, h], fill=color)
        elif label == "flower":
            stem_w = max(ts // 8, 1)
            draw.rectangle(
                [w // 2 - stem_w // 2, h // 2, w // 2 + stem_w // 2, h],
                fill=(40, 130, 40, 255),
            )
            r = int(ts * 0.25)
            draw.ellipse(
                [w // 2 - r, h // 4 - r, w // 2 + r, h // 4 + r],
                fill=color,
            )
        else:
            draw.rectangle([0, 0, w, h], fill=color)

        return arcade.Texture(image=img, size=(w, h))
