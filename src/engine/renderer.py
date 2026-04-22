"""Рендер мира: два слоя (поверхность + объекты).

Слой поверхности - цветные квадратики по биомам.
Слой объектов - декоративные объекты (деревья, камни, трава),
включая многотайловые (1x2 деревья, 2x1 трава).

Оптимизация:
- Спрайты создаются лениво при первом попадании чанка в область
  видимости и кэшируются.
- Отрисовываются только SpriteList видимых чанков.
"""

from __future__ import annotations

import math
import random

import arcade

from src.engine.camera import GameCamera
from src.engine.layers import BIOME_COLORS, FALLBACK_MAP, PLACEMENT_RULES, ObjectType
from src.world.models import Biome, Chunk, World


class Renderer:
    """Рендер мира с двумя слоями: поверхность и объекты.

    Attributes:
        tile_size: Размер тайла в пикселях.
    """

    def __init__(self, world: World, tile_size: int = 32) -> None:
        """Инициализация рендера.

        Args:
            world: Сгенерированный мир.
            tile_size: Размер тайла в пикселях.
        """
        self._world = world
        self.tile_size = tile_size
        self._rng = random.Random(world.seed + 100)

        # Тайлы, занятые объектами (для проверки наложений)
        self._occupied: set[tuple[int, int]] = set()

        # Кэш текстур объектов
        self._obj_textures: dict[ObjectType, arcade.Texture] = {}
        self._build_object_textures()

    # ================================================================
    # API
    # ================================================================

    def draw(self, camera: GameCamera) -> None:
        """Отрисовывает видимые чанки.

        Создаёт SpriteList для чанков, которые ещё не были
        отрисованы, и рисует только видимые.

        Args:
            camera: Активная камера.
        """
        visible = camera.visible_chunks(self._world.chunk_size)

        for cx, cy in visible:
            chunk = self._world.get_chunk(cx, cy)
            if chunk is None:
                continue

            # Ленивое создание спрайтов
            if chunk.surface_sprite_list is None:
                chunk.surface_sprite_list = self._build_surface_sprites(
                    chunk
                )
            if chunk.object_sprite_list is None:
                chunk.object_sprite_list = self._build_object_sprites(
                    chunk
                )

        # Сначала поверхность, потом объекты
        for cx, cy in visible:
            chunk = self._world.get_chunk(cx, cy)
            if chunk is None:
                continue
            if chunk.surface_sprite_list is not None:
                chunk.surface_sprite_list.draw()
        for cx, cy in visible:
            chunk = self._world.get_chunk(cx, cy)
            if chunk is None:
                continue
            if chunk.object_sprite_list is not None:
                chunk.object_sprite_list.draw()

    # ================================================================
    # Спрайты поверхности
    # ================================================================

    def _build_surface_sprites(self, chunk: Chunk) -> arcade.SpriteList:
        """Создаёт цветные квадратики для чанка.

        Каждый тайл - один SpriteSolidColor.

        Args:
            chunk: Чанк для отрисовки.

        Returns:
            SpriteList с цветными спрайтами.
        """
        cs = self._world.chunk_size
        sprite_list = arcade.SpriteList()

        for ly in range(chunk.tiles.shape[0]):
            for lx in range(chunk.tiles.shape[1]):
                tile = chunk.tiles[ly, lx]
                color = BIOME_COLORS.get(tile.biome, (255, 0, 255))

                # Мировые координаты центра тайла
                tx = chunk.x * cs + lx
                ty = chunk.y * cs + ly
                cx_px = tx * self.tile_size + self.tile_size / 2.0
                cy_px = (
                    (self._world.height - 1 - ty)
                    * self.tile_size
                    + self.tile_size / 2.0
                )

                sprite = arcade.SpriteSolidColor(
                    width=self.tile_size,
                    height=self.tile_size,
                    color=color,
                    center_x=cx_px,
                    center_y=cy_px,
                )
                sprite_list.append(sprite)

        return sprite_list

    # ================================================================
    # Спрайты объектов
    # ================================================================

    def _build_object_sprites(self, chunk: Chunk) -> arcade.SpriteList:
        """Создаёт декоративные объекты для чанка.

        Размещает объекты по правилам PLACEMENT_RULES.
        Многотайловые объекты проверяют, что все занимаемые
        тайлы принадлежат нужному биому и не заняты другими
        объектами. При наложении широкий объект заменяется
        на узкий с помощью fallback (из FALLBACK_MAP).

        Цветы генерируются полянами - зоны определяются
        детерминированным хешем по координатам зоны.

        Args:
            chunk: Чанк для отрисовки.

        Returns:
            SpriteList со спрайтами объектов.
        """
        cs = self._world.chunk_size
        sprite_list = arcade.SpriteList()
        height = self._world.height

        # Группируем правила по биому
        rules_by_biome: dict[Biome, list] = {}
        for rule in PLACEMENT_RULES:
            rules_by_biome.setdefault(rule.biome, []).append(rule)

        for ly in range(chunk.tiles.shape[0]):
            for lx in range(chunk.tiles.shape[1]):
                tile = chunk.tiles[ly, lx]
                biome = tile.biome

                # Вода - без объектов
                if biome.is_water:
                    continue

                # Глобальные координаты тайла
                tx = chunk.x * cs + lx
                ty = chunk.y * cs + ly

                # Тайл уже занят другим объектом
                if (tx, ty) in self._occupied:
                    continue

                rules = rules_by_biome.get(biome)
                if not rules:
                    continue

                for rule in rules:
                    # Проверяем, что якорный тайл подходит
                    if not self._can_place_anchor(
                        tx, ty, rule, rules_by_biome
                    ):
                        continue

                    # Береговые объекты - только рядом с водой
                    if rule.shore_only and not self._is_adjacent_to_water(
                        tx, ty
                    ):
                        continue

                    # Цветы: зонная генерация (поляны)
                    density = rule.density
                    if rule.object_type == ObjectType.FLOWER:
                        if not self._is_flower_zone(tx, ty):
                            continue
                        density = 0.35  # плотность внутри поляны

                    # Вероятностный отбор
                    if self._rng.random() >= density:
                        continue

                    # Проверяем наложение на занятые тайлы
                    obj = rule.object_type
                    obj_tiles = self._get_obj_tiles(tx, ty, obj)

                    if any(t in self._occupied for t in obj_tiles):
                        # Пробуем fallback (заменяем на узкий объект)
                        fallback = FALLBACK_MAP.get(obj)
                        if fallback is None:
                            continue
                        obj = fallback
                        obj_tiles = [(tx, ty)]
                        if (tx, ty) in self._occupied:
                            continue

                    # Размещаем объект
                    tex = self._obj_textures[obj]
                    px_w = obj.tile_width * self.tile_size
                    px_h = obj.tile_height * self.tile_size

                    cx_px, cy_px = self._object_position(
                        tx, ty, obj, height
                    )

                    sprite = arcade.Sprite(
                        tex,
                        center_x=cx_px,
                        center_y=cy_px,
                    )
                    sprite.width = px_w
                    sprite.height = px_h
                    sprite_list.append(sprite)

                    # Помечаем все тайлы объекта как занятые
                    for ot in obj_tiles:
                        self._occupied.add(ot)

                    # Только один объект на тайл
                    break

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
        """Простой детерминированный хеш.

        Args:
            *args: Числа для хеширования.

        Returns:
            Целочисленный хеш.
        """
        h = 0
        for a in args:
            h = (h * 31 + a) & 0xFFFFFFFF
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
        zone_rng = random.Random(zone_seed)
        return zone_rng.random() < 0.4  # 40% зон - цветочные

    def _can_place_anchor(
        self,
        tx: int,
        ty: int,
        rule: "ObjectPlacementRule",  # noqa: F821
        rules_by_biome: dict[Biome, list],
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

        # Высокие объекты идут ВВЕРХ по экрану
        # (ty - dy = ниже индекс массива = выше на экране)
        for dy in range(oh):
            for dx in range(ow):
                ntx = tx + dx
                nty = ty - dy
                tile = self._world.get_tile(ntx, nty)
                if tile is None:
                    return False
                if obj not in {
                    r.object_type for r in rules_by_biome.get(
                        tile.biome, []
                    )
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
        obj: ObjectType,
        world_height: int,
    ) -> tuple[float, float]:
        """Пиксельная позиция центра объекта.

        Основание высоких объектов привязано к ЦЕНТРУ якорного
        тайла, а не к его нижней границе.

        Args:
            tx: X-координата якорного тайла.
            ty: Y-координата якорного тайла.
            obj: Тип объекта.
            world_height: Высота мира в тайлах.

        Returns:
            Кортеж (center_x, center_y) в пикселях.
        """
        ts = self.tile_size
        px_h = obj.tile_height * ts

        # Центр якорного тайла
        base_x = tx * ts + ts / 2.0
        base_y = (world_height - 1 - ty) * ts + ts / 2.0

        # Широкие объекты: центр между двумя тайлами по X
        if obj.tile_width > 1:
            base_x += (obj.tile_width - 1) * ts / 2.0

        # Высокие объекты: основание в центре тайла
        # Нижний край спрайта = base_y, центр = base_y + px_h/2
        if obj.tile_height > 1:
            base_y += px_h / 2.0

        return base_x, base_y

    # ================================================================
    # Генерация текстур объектов
    # ================================================================

    def _build_object_textures(self) -> None:
        """Создаёт текстуры для всех типов объектов.

        Использует PIL для простых фигур (будут заменены
        на реальные текстуры в итерации 2).
        """
        from PIL import Image, ImageDraw

        ts = self.tile_size

        for obj_type in ObjectType:
            w = obj_type.tile_width * ts
            h = obj_type.tile_height * ts
            color = obj_type.color + (255,)  # RGBA

            img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
            draw = ImageDraw.Draw(img)

            label = obj_type.label

            if label.startswith("tree_"):
                # Дерево: ствол + крона
                trunk_w = max(ts // 6, 2)
                trunk_h = ts // 2
                trunk_x = w // 2 - trunk_w // 2
                draw.rectangle(
                    [trunk_x, h - trunk_h, trunk_x + trunk_w, h],
                    fill=(100, 70, 40, 255),
                )
                crown_r = int(ts * 0.45)
                crown_cx = w // 2
                crown_cy = h // 2 - ts // 6
                draw.ellipse(
                    [
                        crown_cx - crown_r,
                        crown_cy - crown_r,
                        crown_cx + crown_r,
                        crown_cy + crown_r,
                    ],
                    fill=color,
                )
            elif label == "palm":
                # Пальма
                trunk_w = max(ts // 5, 2)
                # Ствол
                for seg_y in range(h):
                    bend = int(ts * 0.15 * math.sin(seg_y / h * math.pi))
                    tx_start = w // 2 - trunk_w // 2 + bend
                    draw.rectangle(
                        [tx_start, seg_y, tx_start + trunk_w, seg_y + 1],
                        fill=(140, 110, 60, 255),
                    )
                # Листья
                leaf_cy = ts // 4
                leaf_rx = int(ts * 0.5)
                leaf_ry = int(ts * 0.2)
                for angle_deg in (-60, -30, 0, 30, 60):
                    rad = math.radians(angle_deg)
                    leaf_cx = w // 2 + int(leaf_rx * 0.4 * math.sin(rad))
                    ly = leaf_cy - int(leaf_ry * 0.3 * math.cos(rad))
                    draw.ellipse(
                        [
                            leaf_cx - leaf_rx,
                            ly - leaf_ry,
                            leaf_cx + leaf_rx,
                            ly + leaf_ry,
                        ],
                        fill=color,
                    )
            elif label == "cactus":
                # Кактус
                trunk_w = max(ts // 5, 2)
                trunk_x = w // 2 - trunk_w // 2
                draw.rectangle(
                    [trunk_x, 0, trunk_x + trunk_w, h],
                    fill=color,
                )
                branch_y1 = h // 3
                branch_y2 = 2 * h // 3
                draw.rectangle(
                    [0, branch_y1, trunk_x, branch_y1 + trunk_w],
                    fill=color,
                )
                draw.rectangle(
                    [trunk_x + trunk_w, branch_y2, w, branch_y2 + trunk_w],
                    fill=color,
                )
            elif label.startswith("rock_"):
                # Камень
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
            elif label == "reed":
                # Тростник
                blade_w = max(ts // 6, 2)
                for i in range(3):
                    bx = w // 4 + i * w // 4 - blade_w // 2
                    draw.rectangle(
                        [bx, h // 3, bx + blade_w, h],
                        fill=(80, 130, 50, 255),
                    )
                    top_w = blade_w * 2
                    draw.ellipse(
                        [
                            bx + blade_w // 2 - top_w // 2,
                            h // 6,
                            bx + blade_w // 2 + top_w // 2,
                            h // 3 + top_w // 2,
                        ],
                        fill=(160, 140, 60, 255),
                    )
            elif label == "tumbleweed":
                # Перекати-поле
                r = int(ts * 0.4)
                cx, cy = w // 2, h // 2
                draw.ellipse(
                    [cx - r, cy - r, cx + r, cy + r], fill=color
                )
                for angle_deg in range(0, 360, 45):
                    rad = math.radians(angle_deg)
                    sx = cx + int(r * math.cos(rad))
                    sy = cy + int(r * math.sin(rad))
                    ex = cx + int((r + ts // 6) * math.cos(rad))
                    ey = cy + int((r + ts // 6) * math.sin(rad))
                    draw.line(
                        [(sx, sy), (ex, ey)],
                        fill=(120, 100, 60, 255),
                        width=max(1, ts // 16),
                    )
            elif label == "tundra_bush":
                # Тундровый куст
                rx = int(ts * 0.4)
                ry = int(ts * 0.25)
                cx, cy = w // 2, h // 2 + ts // 8
                draw.ellipse(
                    [cx - rx, cy - ry, cx + rx, cy + ry], fill=color
                )
                # Веточки
                for dx_off in (-ts // 5, 0, ts // 5):
                    draw.rectangle(
                        [cx + dx_off - 1, cy - ry - ts // 8,
                         cx + dx_off + 1, cy - ry + 2],
                        fill=(80, 90, 70, 255),
                    )
            elif label == "bush":
                # Куст
                r = int(ts * 0.4)
                cx, cy = w // 2, h // 2
                draw.ellipse(
                    [cx - r, cy - r, cx + r, cy + r], fill=color
                )
            elif label == "grass_tuft":
                # Широкая трава
                blade_w = max(ts // 8, 1)
                for i in range(5):
                    bx = w // 6 + i * w // 5 - blade_w // 2
                    draw.rectangle(
                        [bx, h // 3, bx + blade_w, h],
                        fill=color,
                    )
            elif label == "grass_tuft_small":
                # Узкая трава
                blade_w = max(ts // 8, 1)
                for i in range(3):
                    bx = w // 4 + i * w // 4 - blade_w // 2
                    draw.rectangle(
                        [bx, h // 3, bx + blade_w, h],
                        fill=color,
                    )
            elif label == "flower":
                # Цветок
                stem_w = max(ts // 8, 1)
                draw.rectangle(
                    [w // 2 - stem_w // 2, h // 2,
                     w // 2 + stem_w // 2, h],
                    fill=(40, 130, 40, 255),
                )
                r = int(ts * 0.25)
                draw.ellipse(
                    [w // 2 - r, h // 4 - r, w // 2 + r, h // 4 + r],
                    fill=color,
                )
            else:
                # Запасной вариант: залить цветом
                draw.rectangle([0, 0, w, h], fill=color)

            tex = arcade.Texture(image=img, size=(w, h))
            self._obj_textures[obj_type] = tex
