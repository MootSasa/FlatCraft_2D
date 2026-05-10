"""Миникарта."""

from __future__ import annotations

from typing import Optional

import arcade
import numpy as np
from PIL import Image

from src.world.models import Biome, World


class Minimap:
    """Миникарта мира с рамкой камеры и кликом для перемещения.

    Привязана к правому нижнему углу окна.
    Клик по миникарте перемещает камеру в соответствующую точку мира.

    Attributes:
        size: Размер миникарты в пикселях (квадрат).
    """

    def __init__(self, world: World, size: int = 180) -> None:
        """Инициализация миникарты.

        Args:
            world: Сгенерированный мир (нужен biome_map).
            size: Размер миникарты в пикселях (квадрат).
        """
        self._world = world
        self.size = size
        self._margin = 10

        # Текстура и спрайт
        self._tex: Optional[arcade.Texture] = None
        self._sprite: Optional[arcade.Sprite] = None
        self._spritelist: Optional[arcade.SpriteList[arcade.Sprite]] = None

        # Позиция на экране
        self._screen_left: float = 0.0
        self._screen_bottom: float = 0.0

        self._build_texture()

    def cleanup(self) -> None:
        """Освобождает текстуру и спрайты миникарты."""
        if self._spritelist is not None:
            self._spritelist.clear()
            self._spritelist = None
        self._sprite = None
        self._tex = None

    # ================================================================
    # Генерация текстуры
    # ================================================================

    def _build_texture(self) -> None:
        """Генерирует текстуру миникарты из biome_map."""
        biome_map = self._world.biome_map
        if biome_map is None:
            return

        h, w = biome_map.shape
        size = self.size

        # Векторизованная конвертация biome_map -> RGB
        rgb = np.zeros((h, w, 3), dtype=np.uint8)
        for biome in Biome:
            mask = biome_map == biome
            rgb[mask] = biome.color

        img = Image.fromarray(rgb, "RGB").convert("RGBA")
        img = img.resize((size, size), Image.Resampling.NEAREST)
        self._tex = arcade.Texture(image=img, size=(size, size))

    # ================================================================
    # Позиционирование
    # ================================================================

    def _update_position(self, screen_w: int, screen_h: int) -> None:
        """Обновляет позицию миникарты."""
        if self._tex is None:
            return

        size = self.size
        margin = self._margin

        self._screen_left = screen_w - margin - size
        self._screen_bottom = margin

        cx = self._screen_left + size / 2.0
        cy = self._screen_bottom + size / 2.0

        if self._sprite is None:
            self._sprite = arcade.Sprite(
                self._tex, center_x=cx, center_y=cy
            )
            self._sprite.width = size
            self._sprite.height = size
            self._spritelist = arcade.SpriteList()
            self._spritelist.append(self._sprite)
        else:
            self._sprite.center_x = cx
            self._sprite.center_y = cy

    # ================================================================
    # Клик для перемещения камеры
    # ================================================================

    def hit_test(self, screen_x: float, screen_y: float) -> bool:
        """Проверяет, попадает ли клик в область миникарты.

        Args:
            screen_x: X-координата клика (пиксели экрана).
            screen_y: Y-координата клика (пиксели экрана).

        Returns:
            True, если клик внутри миникарты.
        """
        return (
            self._screen_left <= screen_x <= self._screen_left + self.size
            and self._screen_bottom
            <= screen_y
            <= self._screen_bottom + self.size
        )

    def click_to_world(
        self, screen_x: float, screen_y: float, tile_size: int = 32
    ) -> tuple[float, float]:
        """Преобразует клик по миникарте в мировые координаты.

        Args:
            screen_x: X-координата клика (пиксели экрана).
            screen_y: Y-координата клика (пиксели экрана).
            tile_size: Размер тайла в пикселях.

        Returns:
            Кортеж (world_x, world_y) в пикселях мира.
        """
        # Относительная позиция внутри миникарты [0..1]
        rel_x = (screen_x - self._screen_left) / self.size
        rel_y = (screen_y - self._screen_bottom) / self.size

        # Ограничиваем [0..1]
        rel_x = max(0.0, min(1.0, rel_x))
        rel_y = max(0.0, min(1.0, rel_y))

        # Мировые координаты в пикселях
        world_px_w = self._world.width * tile_size
        world_px_h = self._world.height * tile_size

        world_x = rel_x * world_px_w
        world_y = rel_y * world_px_h

        return world_x, world_y

    # ================================================================
    # Отрисовка
    # ================================================================

    def draw(
        self,
        screen_w: int,
        screen_h: int,
        cam_x: float,
        cam_y: float,
        zoom: float,
        tile_size: int = 32,
    ) -> None:
        """Отрисовывает миникарту с рамкой камеры.

        Args:
            screen_w: Ширина окна.
            screen_h: Высота окна.
            cam_x: X камеры в пикселях мира.
            cam_y: Y камеры в пикселях мира.
            zoom: Текущий зум.
            tile_size: Размер тайла.
        """
        self._update_position(screen_w, screen_h)

        # Рисуем миникарту
        if self._spritelist is not None:
            self._spritelist.draw()

        # Рамка вокруг миникарты
        size = self.size
        arcade.draw_lrbt_rectangle_outline(
            self._screen_left,
            self._screen_left + size,
            self._screen_bottom,
            self._screen_bottom + size,
            (255, 255, 255, 200),
            border_width=2,
        )

        # Рамка камеры
        self._draw_camera_rect(
            screen_w, screen_h, cam_x, cam_y, zoom, tile_size
        )

    def _draw_camera_rect(
        self,
        screen_w: int,
        screen_h: int,
        cam_x: float,
        cam_y: float,
        zoom: float,
        tile_size: int,
    ) -> None:
        """Рисует прямоугольник видимой области на миникарте."""
        world_w = self._world.width
        world_h = self._world.height
        size = self.size

        # Центр камеры на миникарте
        mm_cx = cam_x / (world_w * tile_size) * size
        mm_cy = cam_y / (world_h * tile_size) * size

        # Размер видимой области на миникарте
        if zoom > 0:
            rect_w = (screen_w / zoom) / (world_w * tile_size) * size
            rect_h = (screen_h / zoom) / (world_h * tile_size) * size
        else:
            rect_w = size
            rect_h = size

        rect_w = min(rect_w, size)
        rect_h = min(rect_h, size)

        # Координаты на экране
        rect_left = self._screen_left + mm_cx - rect_w / 2.0
        rect_right = rect_left + rect_w
        rect_bottom = self._screen_bottom + mm_cy - rect_h / 2.0
        rect_top = rect_bottom + rect_h

        # Ограничиваем рамку пределами миникарты
        rect_left = max(rect_left, self._screen_left)
        rect_right = min(rect_right, self._screen_left + size)
        rect_bottom = max(rect_bottom, self._screen_bottom)
        rect_top = min(rect_top, self._screen_bottom + size)

        arcade.draw_lrbt_rectangle_outline(
            rect_left,
            rect_right,
            rect_bottom,
            rect_top,
            (255, 255, 255, 180),
            border_width=2,
        )

    def on_resize(self, screen_w: int, screen_h: int) -> None:
        """Обновляет позицию при изменении размера окна."""
        self._update_position(screen_w, screen_h)
