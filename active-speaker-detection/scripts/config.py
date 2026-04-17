#
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
#
"""Configuration and argument parsing for Active Speaker Detection NIM client."""

import argparse
import os
import sys
from dataclasses import dataclass

from constants import (
    AUDIO_ENCODING_CONFIGS,
    DEFAULT_AUDIO_PATH,
    DEFAULT_DIARIZATION_PATH,
    DEFAULT_VIDEO_PATH,
)

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../../")))
from utils.utils import (  # noqa: E402
    add_preview_arguments,
    add_ssl_arguments,
    is_file_available,
)


def create_argument_parser() -> argparse.ArgumentParser:
    """Create and configure the argument parser for Active Speaker Detection.

    Returns:
        argparse.ArgumentParser: Configured argument parser with all options
    """
    parser = argparse.ArgumentParser(
        description=(
            "Run Active Speaker Detection inference with video," " audio, and diarization files"
        ),
    )

    add_ssl_arguments(parser)
    add_preview_arguments(parser)

    parser.add_argument(
        "--video-input",
        type=str,
        default=DEFAULT_VIDEO_PATH,
        help="The path to the input video file (MP4 format).",
    )
    parser.add_argument(
        "--audio-input",
        type=str,
        default=DEFAULT_AUDIO_PATH,
        help="The path to the input audio file (WAV/MP3 format).",
    )
    parser.add_argument(
        "--diarization-input",
        type=str,
        default=DEFAULT_DIARIZATION_PATH,
        help="The path to the diarization file (JSON format with word-level speaker info).",
    )
    parser.add_argument(
        "--skip-audio",
        action="store_true",
        help="Skip sending separate audio data. "
        "Audio will be extracted from embedded video stream.",
    )
    parser.add_argument(
        "--output",
        type=str,
        default="speaker_detection_output.mp4",
        help="The path for the output video file with speaker bounding boxes.",
    )

    return parser


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments using the configured argument parser.

    Returns:
        Namespace containing all parsed arguments
    """
    parser = create_argument_parser()
    return parser.parse_args()


@dataclass
class ActiveSpeakerDetectionConfig:
    """Configuration class for Active Speaker Detection parameters."""

    video_filepath: os.PathLike
    audio_filepath: os.PathLike
    diarization_filepath: os.PathLike
    output_filepath: os.PathLike
    skip_audio: bool = False
    embedded_audio_codec: str = "opus"
    input_audio_format: str | None = None
    input_video_format: str | None = None

    @classmethod
    def from_args(cls, args):
        """Create config from command line arguments."""
        return cls(
            video_filepath=args.video_input,
            audio_filepath=args.audio_input,
            diarization_filepath=args.diarization_input,
            output_filepath=args.output,
            skip_audio=args.skip_audio,
        )

    def __str__(self) -> str:
        """Return string representation of config."""
        sep = "=" * 60
        audio_display = (
            "(skipped - using embedded)" if self.skip_audio else str(self.audio_filepath)
        )
        diarization_display = str(self.diarization_filepath)
        lines = [
            sep,
            "Active Speaker Detection Configuration",
            sep,
            f"Video input       : {self.video_filepath}",
            f"Audio input       : {audio_display}",
            f"Diarization input : {diarization_display}",
            f"Output file       : {self.output_filepath}",
            f"Skip audio        : {self.skip_audio}",
            sep,
        ]
        return "\n".join(lines)

    def validate_config(self) -> bool:
        """Validate the active speaker detection configuration.

        Raises:
            FileNotFoundError: If input files don't exist.
            RuntimeError: If file formats are invalid.
        """
        # Validate video file
        is_file_available(self.video_filepath, ["mp4"])
        self.input_video_format = "h264"

        # Validate diarization file
        is_file_available(self.diarization_filepath, ["json"])

        # Validate audio file
        if not self.skip_audio:
            is_file_available(self.audio_filepath, ["wav", "mp3"])
            audio_ext = os.path.splitext(self.audio_filepath)[1].lower().lstrip(".")
            if audio_ext not in AUDIO_ENCODING_CONFIGS:
                raise RuntimeError(
                    f"Unsupported audio format: {audio_ext}. "
                    f"Supported formats: {list(AUDIO_ENCODING_CONFIGS.keys())}"
                )
            self.input_audio_format = audio_ext
        else:
            self.input_audio_format = None
        return True
