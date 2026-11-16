"""Usage guide text for the Documentation section.

Paragraphs quote the toolkit limits, the glossary, and the scene note.
This module does not call a model and does not read a raster.
"""

from __future__ import annotations

from dataclasses import dataclass

from scene.toolkit.catalog import TOOLS
from scene.toolkit.run import LIMITS

READ_GRD = (
    "It reads grd-cog.tif. The calibration factor and the ground size of "
    "an overview pixel come from grd-json.json."
)
READ_MOTION = (
    "It reads grd-cog.tif and vid-cog.tif. vid-cog.tif is the georeferenced "
    "dwell stack. The stage video is vid-mp4, and this tool does not read "
    "that file."
)
READ_PAIR = (
    "It reads grd-cog.tif on the open scene and grd-cog.tif on the partner "
    "scene. The partner is resampled onto the open scene's overview grid."
)
READ_STACK = (
    "It reads grd-cog.tif on the open scene and grd-cog.tif on every matched "
    "scene. A stack compares every matched scene, not only one partner."
)
STACK_MEAN_LOCK = (
    "It stays locked until five matched scenes, including the open one, "
    "are on disk."
)
FILES: dict[str, tuple[str, ...]] = {
    "single": (READ_GRD,),
    "motion": (READ_MOTION,),
    "pair": (READ_PAIR,),
    "stack": (READ_STACK,),
    "stack-mean": (READ_STACK, STACK_MEAN_LOCK),
}
DESCRIPTIONS: dict[str, str] = {
    "open-water": (
        "Dark smooth water, from the darkest histogram mode. It reports "
        "the area, the fraction of the scene, and the median sigma-nought."
    ),
    "sea-roughness": (
        "Calm water against wind-roughened water, inside the water mask. "
        "A sea that spans less than 1.5 dB stays one class."
    ),
    "built-up": (
        "Bright clusters on land. It reports the fraction of land and a "
        "cluster count."
    ),
    "returns-on-water": (
        "Compact bright returns that touch the water. The label stays "
        "bright return."
    ),
    "long-structure": "A long bright return along the waterline.",
    "dwell-motion": (
        "Tracks of bright returns during this collect. Cyan held still. "
        "Red moved. It reports displacement and speed over those seconds."
    ),
    "amplitude-change": (
        "Earlier date in red, later date in cyan. The darker, brighter, "
        "and unchanged areas count a difference of at least 3 dB in a "
        "patch of at least 8 pixels."
    ),
    "water-persistence": "How many dates each pixel is water.",
    "sea-state": "The median sigma-nought of the water on each date.",
    "dark-sea-anomaly": (
        "Water at least 2 dB darker than the stack median, in a patch of "
        "at least 8 pixels, whose surrounding ring is at least 1 dB "
        "brighter. It reports extent only."
    ),
    "shoreline-series": "The waterline once per date.",
    "date-of-change": (
        "The date a pixel left the stack median, when the departure is "
        "at least 3 dB and the patch is at least 8 pixels."
    ),
    "repeat-returns": (
        "A bright return seen on many dates against one seen once."
    ),
    "site-activity": (
        "A bright cluster that appears or leaves relative to the stack "
        "median."
    ),
    "stack-mean": "The mean of at least five matched dates.",
}


@dataclass(frozen=True)
class GuideSection:
    """One block the Documentation page can render."""

    id: str
    title: str
    paragraphs: tuple[str, ...]

    def to_public(self) -> dict[str, object]:
        return {
            "id": self.id,
            "title": self.title,
            "paragraphs": list(self.paragraphs),
        }


def guide_payload() -> dict[str, object]:
    """The JSON body of GET /api/guide."""

    return {"sections": [section.to_public() for section in _sections()]}


def _sections() -> tuple[GuideSection, ...]:
    return _intro() + _science() + _tools() + _sketches()


def _intro() -> tuple[GuideSection, ...]:
    return (
        GuideSection(
            "what-this-is",
            "What this application does",
            (
                "This page shows ICEYE synthetic-aperture radar scenes from "
                "the public open-data collection. You can search that "
                "collection, download a scene onto this machine, and run "
                "measurements that stay inside what the rasters support.",
                "A bright mark is a bright radar return. The page does not "
                "name a ship, match AIS, or claim that a model read the radar.",
                "The first public collect on this page is "
                "ICEYE_EYCKP5_20251024T135309Z_6724574_X52_SLF. It is "
                "ICEYE-X52, spotlight, X-band, VV, collected on 24 October "
                "2025 at 13:53 UTC. Its footprint covers the 25 de Abril "
                "bridge.",
                "The person-written scene note says: "
                '"A bright return on the water is not a vessel '
                'identification." If those texts do not contain the answer, '
                "the answer is that the texts do not say.",
            ),
        ),
        GuideSection(
            "search",
            "Search the catalogue",
            (
                "Catalog searches the public ICEYE open-data collection. "
                "There is no account and no STAC API.",
                "The text box is a case-insensitive substring of the scene "
                "id. It does not search place, mode, or satellite. The other "
                "filters are a start date, an end date, a satellite, a "
                "product code, and a west, south, east, north box.",
                "A cached row is labeled with the nearest place within 150 "
                "km of the footprint centre, or Open sea when the place is "
                "farther. Clicking a row opens its file list. It does not "
                "open the scene.",
            ),
        ),
        GuideSection(
            "download",
            "Download a scene",
            (
                "Download starts the one download onto this machine. The "
                "dock shows each file and its byte count.",
                "The default selection is the preview pack: graphic, "
                "qlk-cog, qlk-json, and vid-mp4 when the item has it. The "
                "STAC item is always written as stac.json. Large products "
                "stay unchecked until you select them.",
                "One download runs at a time. A scene that is only in the "
                "catalogue is not downloaded by a report.",
            ),
        ),
        GuideSection(
            "open-a-scene",
            "Open a scene",
            (
                "Open is shown when that scene is already on disk. It opens "
                "the scene on the stage and closes the pane.",
                "Library lists the scenes on this machine. Choosing a row "
                "opens that scene on the stage. The test scene is the 25 de "
                "Abril collect.",
            ),
        ),
        GuideSection(
            "run-a-tool",
            "Run a measurement",
            (
                "The tool column groups the measurements as Surface, "
                "Objects, Motion, Change, and Stack. A locked tool stays in "
                "the list and names the missing file or the missing second "
                "look.",
                "Running a tool draws a picture with a legend, then writes "
                "a measurement and a briefing. The briefing carries that "
                "tool's limit sentence. The toolkit does not call a model.",
                "Single-scene tools run on spotlight and stripmap. Scan and "
                "Scan Wide stay locked because those GRDs are not treated "
                "as radiometrically calibrated. Change and stack tools need "
                "a second scene with the same orbit direction, the same "
                "look side, an incidence within 1 degree, and footprints "
                "that overlap.",
            ),
        ),
        GuideSection(
            "run-a-report",
            "Run a report",
            (
                "Report writes one report for the open scene. The page does "
                "not ask a question. Start measures the tools this scene "
                "can support.",
                "A bright return stays a bright radar return. The prose may "
                "not name a ship, a spill, a tide height, or a building "
                "height.",
                "You can leave the second scene as this scene only, or pick "
                "one partner that shares the same look. Download PDF saves "
                "the report that was written. The report does not download "
                "a scene that is only in the catalogue.",
            ),
        ),
    )


def _science() -> tuple[GuideSection, ...]:
    return (
        GuideSection(
            "sigma-nought",
            "Sigma-nought",
            (
                "Sigma-nought is the brightness a calibrated tool reports, "
                "in decibels. Open water reports a median sigma-nought. Sea "
                "state reports the median sigma-nought of the water on each "
                "date. A lower bar is a darker sea, not a Beaufort number. "
                "Scan and Scan Wide GRDs are not radiometrically calibrated, "
                "so those tools do not report sigma-nought.",
            ),
        ),
        GuideSection(
            "incidence",
            "Incidence",
            (
                "Incidence is the scene incidence angle in degrees. Change "
                "and stack tools compare scenes with an incidence within 1 "
                "degree. X-band VV sea sigma-nought can fall by about a "
                "decibel per degree of incidence between 26° and 34°.",
            ),
        ),
        GuideSection(
            "look-side",
            "Look side",
            (
                "Look side is left or right. Change and stack tools need "
                "the same look side and the same orbit direction.",
            ),
        ),
        GuideSection(
            "speckle",
            "Speckle",
            (
                "Speckle is grain in the picture. Speckle and a residual "
                "shift can still fall in an amplitude-change area. The "
                "stack mean cuts speckle where the surface was stable. A "
                "surface that changed is blurred, not removed.",
            ),
        ),
        GuideSection(
            "layover",
            "Layover",
            (
                "Layover is part of a long bright return. The length is the "
                "bright return, layover included. An empty class is a valid "
                "result.",
            ),
        ),
        GuideSection(
            "bright-return",
            "A bright return",
            (
                "A bright return stays a bright radar return. The label "
                "stays bright return. A hull, a pier, and a platform all "
                "qualify.",
            ),
        ),
    )


def _tools() -> tuple[GuideSection, ...]:
    sections: list[GuideSection] = []
    for spec in TOOLS:
        sections.append(
            GuideSection(
                f"tool-{spec.id}",
                spec.label,
                (DESCRIPTIONS[spec.id], *FILES[spec.kind], LIMITS[spec.id]),
            )
        )
    return tuple(sections)


def _sketches() -> tuple[GuideSection, ...]:
    return (
        GuideSection(
            "retrieval",
            "Retrieval",
            (
                "Retrieval is not running.",
                "If a later change adds it, the documents would be texts "
                "this page may already quote: the scene note, each tool's "
                "limit sentence, each briefing, the summary rows, and the "
                "STAC fields for scenes on disk. Rasters, quicklooks, and "
                "overview pictures are not documents.",
                "A passage that does not contain the answer means the texts "
                "do not say. The measurements still run when retrieval is "
                "off.",
            ),
        ),
        GuideSection(
            "kubernetes",
            "Kubernetes",
            (
                "This checkout does not run in Kubernetes. The sketch below "
                "is not running.",
                "The running process is one program. It keeps one "
                "measurement and one download in memory, and it keeps "
                "scenes on a local disk. A first pod would be that same "
                "process, one replica, with the scene folders on one "
                "volume.",
                "Two pods with the current code would each keep their own "
                "measurement and would disagree about the scene folders "
                "unless they share a volume.",
            ),
        ),
    )