"""Place names come from the footprint centre, not from the STAC item."""

from __future__ import annotations

import unittest

from scene.places import OPEN_SEA, place_name


class PlaceNameTest(unittest.TestCase):
    def test_lisbon_centre_is_lisbon(self) -> None:
        self.assertEqual(place_name(38.689, -9.177), "Lisbon")

    def test_tenerife_centre_is_the_town_on_that_island(self) -> None:
        self.assertEqual(place_name(28.23, -16.71), "Santa Cruz de Tenerife")

    def test_mid_ocean_is_open_sea(self) -> None:
        self.assertEqual(place_name(0.0, -30.0), OPEN_SEA)


if __name__ == "__main__":
    unittest.main()
