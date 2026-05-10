"""Игровое окно: ввод, связь мира/камеры/рендера."""

from __future__ import annotations

import arcade

from src.engine.camera import GameCamera
from src.engine.renderer import Renderer
from src.world.models import World

# Размер окна по умолчанию
_DEFAULT_WIDTH: int = 1280
_DEFAULT_HEIGHT: int = 720
_DEFAULT_TITLE: str = "FlatCraft 2D"
# Размер тайла в пикселях
_DEFAULT_TILE_SIZE: int = 32


class FlatCraftWindow(arcade.Window):
    """Главное окно FlatCraft 2D.

    Связывает мир, камеру и рендер в один игровой цикл.

    Attributes:
        world: Сгенерированный мир.
        camera: Игровая камера.
        renderer: Рендер мира.
        tile_size: Размер тайла в пикселях.
    """

    def __init__(
        self,
        world: World,
        tile_size: int = _DEFAULT_TILE_SIZE,
        width: int = _DEFAULT_WIDTH,
        height: int = _DEFAULT_HEIGHT,
        title: str = _DEFAULT_TITLE,
    ) -> None:
        """Инициализация окна.

        Args:
            world: Сгенерированный мир.
            tile_size: Размер тайла в пикселях.
            width: Ширина окна.
            height: Высота окна.
            title: Заголовок окна.
        """
        super().__init__(
            width=width,
            height=height,
            title=title,
            resizable=True,
        )
        self.world = world
        self.tile_size = tile_size

        # Подсистемы
        self.camera = GameCamera(
            window=self,
            world_width=world.width,
            world_height=world.height,
            tile_size=tile_size,
        )
        self.renderer = Renderer(world=world, tile_size=tile_size)

        # Фон - цвет глубокого океана
        self.background_color = (10, 25, 80)

        # Частота обновления логики (240 раз/сек)
        self.set_update_rate(1.0 / 240)

        # FPS: среднее (EMA)
        self._fps_ema: float = 0.0
        self._fps_alpha: float = 0.1  # вес нового значения

        # FPS-текст
        self._fps_text = arcade.Text(
            "FPS: --",
            x=10,
            y=height - 25,
            color=(255, 255, 255),
            font_size=14,
        )

    # ================================================================
    # Игровой цикл
    # ================================================================

    def on_draw(self) -> None:
        """Отрисовка кадра."""
        self.clear()

        # Мир
        self.camera.use()
        self.renderer.draw(self.camera)

        # HUD: FPS
        self.default_camera.use()
        self._fps_text.text = f"FPS: {self._fps_ema:.0f}"
        self._fps_text.draw()

    def on_update(self, delta_time: float) -> None:
        """Обновление логики каждый кадр.

        Args:
            delta_time: Время с прошлого кадра (сек).
        """
        self.camera.update(delta_time)

        # Обновляем FPS
        if delta_time > 0:
            instant_fps = 1.0 / delta_time
            if self._fps_ema <= 0:
                self._fps_ema = instant_fps
            else:
                self._fps_ema = (
                    self._fps_alpha * instant_fps
                    + (1.0 - self._fps_alpha) * self._fps_ema
                )

    # ================================================================
    # Ввод: клавиатура
    # ================================================================

    def on_key_press(self, key: int, modifiers: int) -> None:
        """Нажатие клавиши."""
        self.camera.handle_key_press(key)

        # Escape - закрыть окно
        if key == arcade.key.ESCAPE:
            self.close()

    def on_key_release(self, key: int, modifiers: int) -> None:
        """Отпускание клавиши."""
        self.camera.handle_key_release(key)

    # ================================================================
    # Ввод: мышь
    # ================================================================

    def on_mouse_scroll(
        self, x: int, y: int, scroll_x: float, scroll_y: float
    ) -> None:
        """Прокрутка колеса мыши (масштабирование)."""
        self.camera.handle_mouse_scroll(int(scroll_y))

    # ================================================================
    # События окна
    # ================================================================

    def on_resize(self, width: int, height: int) -> None:
        """Изменение размера окна."""
        super().on_resize(width, height)
        self.camera.resize(width, height)
