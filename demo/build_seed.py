"""Write demo/seed. The container runs this while the image is built."""

from __future__ import annotations

from scene.demo import write_seed
from scene.paths import project_root


def main() -> None:
    dest = write_seed(project_root() / "demo" / "seed")
    print(dest)


if __name__ == "__main__":
    main()
