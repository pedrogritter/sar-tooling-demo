"""The GRD affine round-trips a pixel through longitude and latitude."""

from __future__ import annotations

import unittest

from scene.grid import Grid

# proj:transform of the Lisbon GRD sidecar.
GRD = (
    -9.139894173828166,
    -0.0000010168661664162748,
    -0.0000026882390056062633,
    38.70191466774008,
    -0.0000021062189607544467,
    7.96655191910034e-7,
)


class GridTest(unittest.TestCase):
    def test_origin_and_round_trip(self) -> None:
        grid = Grid.from_transform(GRD)
        lon, lat = grid.to_lonlat(0, 0)
        self.assertAlmostEqual(lon, GRD[0], places=8)
        self.assertAlmostEqual(lat, GRD[3], places=8)
        col, row = grid.to_colrow(lon, lat)
        self.assertAlmostEqual(col, 0, places=4)
        self.assertAlmostEqual(row, 0, places=4)

    def test_coarse_scale_uses_full_pixels(self) -> None:
        grid = Grid.from_transform(GRD)
        lon, lat = grid.to_lonlat(2, 3, scale=5)
        direct = grid.to_lonlat(10, 15)
        self.assertAlmostEqual(lon, direct[0], places=8)
        self.assertAlmostEqual(lat, direct[1], places=8)


if __name__ == "__main__":
    unittest.main()
