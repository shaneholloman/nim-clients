# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: MIT
#
# Permission is hereby granted, free of charge, to any person obtaining a
# copy of this software and associated documentation files (the "Software"),
# to deal in the Software without restriction, including without limitation
# the rights to use, copy, modify, merge, publish, distribute, sublicense,
# and/or sell copies of the Software, and to permit persons to whom the
# Software is furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in
# all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL
# THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING
# FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER
# DEALINGS IN THE SOFTWARE.

"""CLI configuration for the AI for Media Relighting client.

Provides :class:`VideoRelightingConfig` (a frozen snapshot of all relighting
parameters) and argument-parsing helpers used by ``relighting.py``.
"""

import argparse
import json
import logging
import math
import os
from dataclasses import dataclass
from pathlib import Path

try:  # when used as a package
    from . import constants
except ImportError:  # when run as a standalone script
    import constants

from utils.utils import add_preview_arguments, add_ssl_arguments, read_file_content

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------


class _SmartFormatter(argparse.RawDescriptionHelpFormatter, argparse.ArgumentDefaultsHelpFormatter):
    pass


def create_argument_parser() -> argparse.ArgumentParser:
    """Build the full argparse parser for the relighting CLI."""
    parser = argparse.ArgumentParser(
        description="Run AI for Media Relighting with all available features",
        formatter_class=lambda prog: _SmartFormatter(prog, max_help_position=60),
    )
    add_ssl_arguments(parser)
    add_preview_arguments(parser)

    # -- Input / Output ----------------------------------------------------
    io = parser.add_argument_group("Input/Output")
    io.add_argument(
        "--video-input",
        type=str,
        default=constants.DEFAULT_VIDEO_PATH,
        help="Path to the input video file.",
    )
    io.add_argument("--output", type=str, default=None, help="Path for the output video file.")
    io.add_argument(
        "--video-bitrate",
        "--bitrate",
        type=int,
        default=constants.DEFAULT_BITRATE_BPS,
        help=f"Output video bitrate in bps (default: {constants.DEFAULT_BITRATE_BPS}).",
    )
    io.add_argument(
        "--idr-interval",
        type=int,
        default=constants.DEFAULT_IDR_INTERVAL,
        help="IDR interval in frames (server auto ~2 s GOP if omitted in API).",
    )
    io.add_argument("--lossless", action="store_true", help="Enable lossless video encoding.")
    io.add_argument(
        "--custom-encoding-params",
        type=str,
        default=None,
        help="Custom encoding parameters as JSON.",
    )

    # -- HDR / Illumination ------------------------------------------------
    hdr = parser.add_argument_group("HDR/Illumination")
    hdr.add_argument("--hdr", type=str, dest="hdr_file", default=None, help="Custom .hdr file.")
    hdr.add_argument(
        "--hdri-id",
        type=int,
        default=0,
        choices=[0, 1, 2, 3, 4],
        help=(
            "HDR preset: 0=Lounge, 1=Cobblestone Street Night, "
            "2=Glasshouse Interior, 3=Little Paris Eiffel Tower, "
            "4=Wooden Studio."
        ),
    )
    hdr.add_argument(
        "--pan", type=float, default=constants.DEFAULT_PAN_DEGREES, help="Pan angle (degrees)."
    )
    hdr.add_argument(
        "--vertical-fov",
        "--vfov",
        type=float,
        default=constants.DEFAULT_VFOV_DEGREES,
        help="Vertical FOV (degrees).",
    )

    # -- Autorotate --------------------------------------------------------
    rot = parser.add_argument_group("Autorotate")
    rot.add_argument("--autorotate", action="store_true", help="Auto-rotate the HDR environment.")
    rot.add_argument(
        "--rotation-rate",
        type=float,
        default=constants.DEFAULT_ROTATION_RATE_DEGREES,
        help="Rotation speed (degrees/s).",
    )

    # -- Background --------------------------------------------------------
    bg = parser.add_argument_group("Background")
    bg.add_argument(
        "--background-source",
        type=int,
        dest="background_source",
        default=constants.BACKGROUND_SOURCE_UNSPECIFIED,
        choices=[0, 1, 2],
        help="0=source video, 1=custom image, 2=HDR projection.",
    )
    bg.add_argument(
        "--background-image",
        type=str,
        dest="background_image",
        default=None,
        help="Custom background image (PNG, JPG, or HDR).",
    )
    bg.add_argument(
        "--background-image-type",
        type=int,
        dest="background_image_type",
        default=None,
        choices=[0, 1, 2],
        help="Format hint: 0=auto-detect, 1=HDRI, 2=standard (PNG/JPG). "
        "Only relevant with --background-source=1.",
    )
    bg.add_argument(
        "--background-color",
        type=lambda s: int(s, 0),
        default=None,
        help="Solid color as hex integer, e.g. 0x808080.",
    )

    # -- Effect parameters -------------------------------------------------
    fx = parser.add_argument_group("Effect Parameters")
    fx.add_argument(
        "--foreground-gain",
        type=float,
        dest="foreground_gain",
        default=constants.DEFAULT_FOREGROUND_GAIN,
        help="Foreground relighting strength (0.0-2.0).",
    )
    fx.add_argument(
        "--background-gain",
        type=float,
        dest="background_gain",
        default=constants.DEFAULT_BACKGROUND_GAIN,
        help="Background relighting strength (0.0-2.0).",
    )
    fx.add_argument(
        "--blur",
        type=float,
        default=constants.DEFAULT_BLUR_STRENGTH,
        help="Background blur (0.0-1.0).",
    )
    fx.add_argument(
        "--specular",
        type=float,
        default=constants.DEFAULT_SPECULAR,
        help="Specular highlight intensity (0.0-2.0).",
    )
    return parser


def parse_args() -> argparse.Namespace:
    """Parse CLI arguments using :func:`create_argument_parser`."""
    return create_argument_parser().parse_args()


# ---------------------------------------------------------------------------
# Configuration dataclass
# ---------------------------------------------------------------------------

_HDR_PRESET_NAMES = [
    "Lounge",
    "Cobblestone Street Night",
    "Glasshouse Interior",
    "Little Paris Eiffel Tower",
    "Wooden Studio",
]
_IMAGE_TYPE_NAMES = {0: "auto-detect", 1: "HDRI", 2: "standard (PNG/JPG)"}


@dataclass(frozen=True)
class VideoRelightingConfig:
    """Immutable snapshot of every relighting parameter.

    Constructed from CLI args via :meth:`from_args`.  All angle fields are
    stored in **degrees**; use the ``get_*_radians()`` helpers when building
    proto messages.
    """

    # Input / Output
    video_filepath: Path
    output_filepath: Path
    bitrate: int
    idr_interval: int
    lossless: bool
    custom_encoding_params: dict | None

    # HDR / Illumination
    hdr_filepath: Path | None
    hdri_id: int
    pan: float
    vfov: float

    # Autorotate
    autorotate: bool
    rotation_rate: float

    # Background
    background_source: int
    background_image: str | None
    background_image_type: int | None
    background_color: int | None

    # Effect parameters
    foreground_gain: float
    background_gain: float
    blur: float
    specular: float

    # -- Construction ------------------------------------------------------

    @classmethod
    def from_args(cls, args: argparse.Namespace) -> "VideoRelightingConfig":
        """Create a config from parsed CLI arguments."""
        custom_params = None
        if args.custom_encoding_params:
            try:
                custom_params = json.loads(args.custom_encoding_params)
            except json.JSONDecodeError as e:
                raise ValueError(f"Invalid JSON for --custom-encoding-params: {e}") from e

        if args.output is not None:
            output_path = Path(args.output)
        else:
            output_path = Path(f"{Path(args.video_input).stem}-relighting_output.mp4")

        return cls(
            video_filepath=Path(args.video_input),
            output_filepath=output_path,
            bitrate=args.video_bitrate,
            idr_interval=args.idr_interval,
            lossless=args.lossless,
            custom_encoding_params=custom_params,
            hdr_filepath=Path(args.hdr_file) if args.hdr_file else None,
            hdri_id=args.hdri_id,
            pan=args.pan,
            vfov=args.vertical_fov,
            autorotate=args.autorotate,
            rotation_rate=args.rotation_rate,
            background_source=args.background_source,
            background_image=args.background_image,
            background_image_type=args.background_image_type,
            background_color=args.background_color,
            foreground_gain=args.foreground_gain,
            background_gain=args.background_gain,
            blur=args.blur,
            specular=args.specular,
        )

    # -- Display -----------------------------------------------------------

    def __str__(self) -> str:
        lines: list[str] = []
        sep = "=" * 70
        thin = "-" * 70

        lines.append(sep)
        lines.append("AI for Media Relighting Configuration")
        lines.append(sep)

        # Input / Output
        lines.append(f"Video input:       {self.video_filepath}")
        lines.append(f"Output file:       {self.output_filepath}")

        if self.lossless:
            lines.append("Encoding:          Lossless")
        elif self.custom_encoding_params:
            lines.append(f"Encoding:          Custom: {self.custom_encoding_params}")
        else:
            lines.append(
                f"Bitrate:           {self.bitrate:,} bps"
                if self.bitrate > 0
                else "Bitrate:           auto"
            )
            lines.append(f"IDR interval:      {self.idr_interval}")

        # HDR / Illumination
        lines.append(thin)
        lines.append("HDR/Illumination:")
        if self.hdr_filepath:
            lines.append(f"  HDR file:        {self.hdr_filepath}")
        else:
            label = (
                _HDR_PRESET_NAMES[self.hdri_id]
                if 0 <= self.hdri_id < len(_HDR_PRESET_NAMES)
                else f"Unknown ({self.hdri_id})"
            )
            lines.append(f"  HDR preset:      {self.hdri_id} ({label})")
        lines.append(f"  Pan angle:       {self.pan}\u00b0 ({math.radians(self.pan):.4f} rad)")
        lines.append(f"  Vertical FOV:    {self.vfov}\u00b0 ({math.radians(self.vfov):.4f} rad)")
        if self.autorotate:
            lines.append(f"  Autorotate:      ON at {self.rotation_rate}\u00b0/s")

        # Background
        lines.append(thin)
        lines.append("Background:")
        source = constants.BACKGROUND_SOURCE_NAMES.get(
            self.background_source, f"UNKNOWN_{self.background_source}"
        )
        lines.append(f"  Source:          {self.background_source} ({source})")
        if self.background_image:
            lines.append(f"  Image:           {self.background_image}")
        if self.background_image_type is not None:
            img_type = _IMAGE_TYPE_NAMES.get(self.background_image_type, self.background_image_type)
            lines.append(f"  Image type:      {img_type}")
        if self.background_color is not None:
            lines.append(f"  Color:           0x{self.background_color:06X}")

        # Effect parameters
        lines.append(thin)
        lines.append("Effect Parameters:")
        lines.append(f"  Foreground gain: {self.foreground_gain}")
        lines.append(f"  Background gain: {self.background_gain}")
        lines.append(f"  Blur strength:   {self.blur}")
        lines.append(f"  Specular:        {self.specular}")
        lines.append(sep)

        return "\n".join(lines)

    # -- Validation --------------------------------------------------------

    def validate(self) -> None:
        """Validate paths and formats.

        Raises:
            RuntimeError: If the video file is missing, unreadable, or not MP4.
        """
        if not self.video_filepath.is_file():
            raise RuntimeError(f"Video file '{self.video_filepath}' not found")
        if not os.access(self.video_filepath, os.R_OK):
            raise RuntimeError(f"Video file '{self.video_filepath}' is not readable")
        if self.video_filepath.suffix.lower() != ".mp4":
            raise RuntimeError("Only MP4 video format is supported")

        if self.hdr_filepath and not self.hdr_filepath.is_file():
            logger.warning("HDR file '%s' not found, using preset", self.hdr_filepath)
        if self.background_image and not Path(self.background_image).is_file():
            logger.warning("Background image '%s' not found", self.background_image)

    # -- Proto helpers -----------------------------------------------------

    def get_hdri_image_bytes(self) -> bytes | None:
        """Load the custom HDR file, or ``None`` if unset."""
        if not self.hdr_filepath or not self.hdr_filepath.is_file():
            return None
        try:
            return read_file_content(self.hdr_filepath)
        except OSError as exc:
            logger.warning("Could not read %s: %s", self.hdr_filepath, exc)
            return None

    def get_background_image_bytes(self) -> bytes | None:
        """Load the custom background image, or ``None`` if unset."""
        if not self.background_image or not Path(self.background_image).is_file():
            return None
        try:
            return read_file_content(self.background_image)
        except OSError as exc:
            logger.warning("Could not read %s: %s", self.background_image, exc)
            return None

    def get_background_color_int(self) -> int | None:
        """Return ``--background-color`` as an int, or ``None`` if unset."""
        return self.background_color

    def get_pan_radians(self) -> float:
        return math.radians(self.pan)

    def get_vfov_radians(self) -> float:
        return math.radians(self.vfov)

    def get_rotation_rate_radians(self) -> float:
        return math.radians(self.rotation_rate)
