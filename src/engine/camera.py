"""2D-камера: перемещение и масштабирование.

Оборачивает arcade.camera.Camera2D, добавляя:
- Управление WASD / стрелки
- Масштабирование колесом мыши и клавишами +/-
- Ограничение позиции границами мира
"""

from __future__ import annotations

import arcade
from arcade.camera import Camera2D

# Скорость камеры (пикселей/сек)
_CAMERA_SPEED: float = 600.0
# Сглаживание (0..1); больше - плавнее
_LERP_SMOOTHING: float = 0.85
# Пределы масштаба
_MIN_ZOOM: float = 0.15
_MAX_ZOOM: float = 5.0
# Шаг масштабирования
_ZOOM_STEP: float = 0.12


class GameCamera:
    """2D-камера с управлением и ограничениями.

    Attributes:
        tile_size: Размер тайла в пикселях.
    """

    def __init__(
        self,
        window: arcade.Window,
        world_width: int,
        world_height: int,
        tile_size: int = 32,
    ) -> None:
        """Инициализация камеры.

        Args:
            window: Игровое окно Arcade.
            world_width: Ширина мира в тайлах.
            world_height: Высота мира в тайлах.
            tile_size: Размер тайла в пикселях.
        """
        self._cam = Camera2D()
        self._cam.match_window()
        self._window = window
        self.tile_size = tile_size

        # Размеры мира в пикселях
        self._world_px_w = world_width * tile_size
        self._world_px_h = world_height * tile_size
        self._world_w = world_width
        self._world_h = world_height

        # Целевая позиция (центр мира)
        self._target_x = self._world_px_w / 2.0
        self._target_y = self._world_px_h / 2.0
        self._cam.position = (self._target_x, self._target_y)

        # Зажатые клавиши
        self._keys: set[int] = set()

    # ================================================================
    # Ввод
    # ================================================================

    def handle_key_press(self, key: int) -> None:
        """Обрабатывает нажатие клавиши."""
        self._keys.add(key)

    def handle_key_release(self, key: int) -> None:
        """Обрабатывает отпускание клавиши."""
        self._keys.discard(key)

    def handle_mouse_scroll(self, scroll_y: int) -> None:
        """Обрабатывает прокрутку колеса мыши.

        Args:
            scroll_y: Направление (>0 - вверх, <0 - вниз).
        """
        zoom = self._cam.zoom
        if scroll_y > 0:
            zoom *= 1.0 + _ZOOM_STEP
        elif scroll_y < 0:
            zoom /= 1.0 + _ZOOM_STEP
        self._cam.zoom = max(_MIN_ZOOM, min(_MAX_ZOOM, zoom))

    # ================================================================
    # Обновление
    # ================================================================

    def update(self, delta_time: float) -> None:
        """Обновляет позицию камеры.

        Args:
            delta_time: Время с прошлого кадра (сек).
        """
        # Скорость
        speed = _CAMERA_SPEED / self._cam.zoom * delta_time

        dx, dy = 0.0, 0.0
        if arcade.key.W in self._keys or arcade.key.UP in self._keys:
            dy += speed
        if arcade.key.S in self._keys or arcade.key.DOWN in self._keys:
            dy -= speed
        if arcade.key.A in self._keys or arcade.key.LEFT in self._keys:
            dx -= speed
        if arcade.key.D in self._keys or arcade.key.RIGHT in self._keys:
            dx += speed

        # Зум клавишами +/-
        if arcade.key.EQUAL in self._keys or arcade.key.PLUS in self._keys:
            new_zoom = self._cam.zoom * (1.0 + _ZOOM_STEP * delta_time * 5)
            self._cam.zoom = min(_MAX_ZOOM, new_zoom)
        if arcade.key.MINUS in self._keys:
            new_zoom = self._cam.zoom / (1.0 + _ZOOM_STEP * delta_time * 5)
            self._cam.zoom = max(_MIN_ZOOM, new_zoom)

        # Сдвиг цели
        self._target_x += dx
        self._target_y += dy

        # Не выходим за границы мира
        half_w = self._view_width / 2.0
        half_h = self._view_height / 2.0
        self._target_x = max(
            half_w, min(self._world_px_w - half_w, self._target_x)
        )
        self._target_y = max(
            half_h, min(self._world_px_h - half_h, self._target_y)
        )

        # Плавное перемещение
        lerp = 1.0 - pow(_LERP_SMOOTHING, delta_time * 60.0)
        pos = self._cam.position
        cam_x = float(pos[0]) + (self._target_x - float(pos[0])) * lerp
        cam_y = float(pos[1]) + (self._target_y - float(pos[1])) * lerp
        self._cam.position = (cam_x, cam_y)

    # ================================================================
    # Рендер
    # ================================================================

    def use(self) -> None:
        """Активирует камеру для отрисовки."""
        self._cam.use()

    def resize(self, width: int, height: int) -> None:
        """Обновляет камеру при изменении размера окна.

        Args:
            width: Новая ширина окна.
            height: Новая высота окна.
        """
        self._cam.match_window()

    # ================================================================
    # Видимая область
    # ================================================================

    @property
    def _view_width(self) -> float:
        """Ширина видимой области в пикселях."""
        result = self._window.width / self._cam.zoom
        return result  # type: ignore[no-any-return]

    @property
    def _view_height(self) -> float:
        """Высота видимой области в пикселях."""
        result = self._window.height / self._cam.zoom
        return result  # type: ignore[no-any-return]

    def visible_tile_bounds(
        self,
    ) -> tuple[int, int, int, int]:
        """Границы видимой области в координатах тайлов.

        Returns:
            Кортеж (left, top, right, bottom) в тайлах.
            top/bottom - индексы строк массива (0 = верх).
        """
        pos = self._cam.position
        cam_x = float(pos[0])
        cam_y = float(pos[1])

        left_px = cam_x - self._view_width / 2.0
        right_px = cam_x + self._view_width / 2.0
        bottom_px = cam_y - self._view_height / 2.0
        top_px = cam_y + self._view_height / 2.0

        # Столбцы (x) - прямое отображение
        left = max(0, int(left_px / self.tile_size))
        right = min(self._world_w - 1, int(right_px / self.tile_size))

        # Строки (y) - переворот: пиксель y=0 внизу,
        # а строка ty=0 - верхняя в массиве
        ty_top = max(0, self._world_h - 1 - int(top_px / self.tile_size))
        ty_bottom = min(
            self._world_h - 1,
            self._world_h - 1 - int(bottom_px / self.tile_size),
        )

        return left, ty_top, right, ty_bottom

    def visible_chunks(self, chunk_size: int) -> set[tuple[int, int]]:
        """Координаты видимых чанков.

        Args:
            chunk_size: Размер чанка в тайлах.

        Returns:
            Множество кортежей (cx, cy).
        """
        left, ty_top, right, ty_bottom = self.visible_tile_bounds()
        cx_min = left // chunk_size
        cx_max = right // chunk_size
        cy_min = ty_top // chunk_size
        cy_max = ty_bottom // chunk_size

        return {
            (cx, cy)
            for cy in range(cy_min, cy_max + 1)
            for cx in range(cx_min, cx_max + 1)
        }
