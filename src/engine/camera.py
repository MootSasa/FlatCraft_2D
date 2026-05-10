"""2D-камера: перемещение и масштабирование.

Камера следует за игроком, плавно перемещаясь к его позиции.
Зум управляется колёсиком мыши и клавишами +/-.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import arcade
from arcade.camera import Camera2D

if TYPE_CHECKING:
    from src.engine.input_manager import InputManager

# Ограничения зума
_MIN_ZOOM: float = 0.25
_MAX_ZOOM: float = 4.0
_ZOOM_STEP: float = 0.1

# Плавность следования (0 = мгновенно, 1 = нет движения)
_LERP_SMOOTHING: float = 0.01


class GameCamera:
    """2D-камера с управлением и ограничениями.

    Камера следует за позициёй игрока, плавно перемещаясь.
    Зум управляется колёсиком мыши и клавишами +/-.

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

    # ================================================================
    # Ввод
    # ================================================================

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
    # Управление
    # ================================================================

    def move_to(self, world_x: float, world_y: float) -> None:
        """Мгновенно перемещает камеру в указанную точку мира.

        Args:
            world_x: X-координата в пикселях мира.
            world_y: Y-координата в пикселях мира.
        """
        half_w = self._view_width / 2.0
        half_h = self._view_height / 2.0
        self._target_x = max(
            half_w, min(self._world_px_w - half_w, world_x)
        )
        self._target_y = max(
            half_h, min(self._world_px_h - half_h, world_y)
        )
        self._cam.position = (self._target_x, self._target_y)

    def follow(self, world_x: float, world_y: float) -> None:
        """Устанавливает цель следования за объектом.

        Камера плавно перемещается к указанной позиции,
        но не выходит за границы мира.

        Args:
            world_x: X-координата цели в пикселях мира.
            world_y: Y-координата цели в пикселях мира.
        """
        half_w = self._view_width / 2.0
        half_h = self._view_height / 2.0
        self._target_x = max(
            half_w, min(self._world_px_w - half_w, world_x)
        )
        self._target_y = max(
            half_h, min(self._world_px_h - half_h, world_y)
        )

    # ================================================================
    # Обновление
    # ================================================================

    def update(self, delta_time: float, input_mgr: InputManager) -> None:
        """Обновляет позицию камеры.

        Плавно перемещает камеру к целевой позиции.
        Зум через InputManager (клавиши +/-, триггеры геймпада).

        Args:
            delta_time: Время с прошлого кадра (сек).
            input_mgr: Менеджер ввода (клавиатура + геймпад).
        """
        from src.engine.input_manager import Action

        # Зум через InputManager
        if input_mgr.is_pressed(Action.ZOOM_IN):
            new_zoom = self._cam.zoom * (
                1.0 + _ZOOM_STEP * delta_time * 5
            )
            self._cam.zoom = min(_MAX_ZOOM, new_zoom)
        if input_mgr.is_pressed(Action.ZOOM_OUT):
            new_zoom = self._cam.zoom / (
                1.0 + _ZOOM_STEP * delta_time * 5
            )
            self._cam.zoom = max(_MIN_ZOOM, new_zoom)

        # Плавное перемещение к цели
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

    @property
    def zoom(self) -> float:
        """Текущий зум камеры."""
        return float(self._cam.zoom)

    @property
    def position(self) -> tuple[float, float]:
        """Текущая позиция камеры (center_x, center_y)."""
        pos = self._cam.position
        return (float(pos[0]), float(pos[1]))

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

    def visible_chunks(
        self, chunk_size: int, margin: int = 5
    ) -> set[tuple[int, int]]:
        """Координаты видимых чанков с буфером.

        Args:
            chunk_size: Размер чанка в тайлах.
            margin: Кол-во дополнительных чанков за краем видимой
                области (предзагрузка, чтобы избежать провалов FPS
                при прокрутке).

        Returns:
            Множество кортежей (cx, cy).
        """
        left, ty_top, right, ty_bottom = self.visible_tile_bounds()
        cx_min = left // chunk_size
        cx_max = right // chunk_size
        cy_min = ty_top // chunk_size
        cy_max = ty_bottom // chunk_size

        # Расширяем на margin чанков в каждую сторону
        cx_min = max(0, cx_min - margin)
        cx_max = cx_max + margin
        cy_min = max(0, cy_min - margin)
        cy_max = cy_max + margin

        return {
            (cx, cy)
            for cy in range(cy_min, cy_max + 1)
            for cx in range(cx_min, cx_max + 1)
        }
