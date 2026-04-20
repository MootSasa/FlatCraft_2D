#!/usr/bin/env python3
"""Точка входа FlatCraft 2D.

Генерирует мир и запускает игровое окно Arcade.

Использование::
    python -m src.main [--seed SEED] [--width W] [--height H] [--tile-size TS]
"""

from __future__ import annotations

import argparse

import arcade

from src.engine.game_window import FlatCraftWindow
from src.world.generator import GenerationConfig, WorldGenerator


def _parse_args() -> argparse.Namespace:
    """Парсит аргументы командной строки."""
    parser = argparse.ArgumentParser(
        description="FlatCraft 2D - процедурно генерируемый мир"
    )
    parser.add_argument(
        "--seed", type=int, default=42, help="Сид генерации (default: 42)"
    )
    parser.add_argument(
        "--width",
        type=int,
        default=500,
        help="Ширина мира в тайлах (default: 500)",
    )
    parser.add_argument(
        "--height",
        type=int,
        default=500,
        help="Высота мира в тайлах (default: 500)",
    )
    parser.add_argument(
        "--tile-size",
        type=int,
        default=32,
        help="Размер тайла в пикселях (default: 32)",
    )
    return parser.parse_args()


def main() -> None:
    """Генерирует мир и запускает окно."""
    args = _parse_args()

    # Генерация мира
    print(
        f"Генерация мира {args.width}x{args.height}, "
        f"seed={args.seed}..."
    )
    config = GenerationConfig(
        seed=args.seed,
        width=args.width,
        height=args.height,
    )
    generator = WorldGenerator(config)
    world = generator.generate()
    print(
        f"Мир создан: {world.width}x{world.height}, "
        f"{world.chunk_count} чанков"
    )

    # Запуск окна
    window = FlatCraftWindow(
        world=world,
        tile_size=args.tile_size,
    )
    arcade.run()


if __name__ == "__main__":
    main()
