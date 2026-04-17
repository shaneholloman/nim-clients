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

"""Constants and default values for the AI for Media Relighting client.

All defaults match the server-side RelightingEffectApp implementation.
"""

import sys
from pathlib import Path

SCRIPT_PATH = Path(__file__).parent.resolve()
PROJECT_ROOT = Path(__file__).parent.parent.resolve()
REPO_ROOT = PROJECT_ROOT.parent

# Add repo root to sys.path so shared utils/utils.py is importable.
sys.path.append(str(REPO_ROOT))

# Add proto stubs to sys.path.
_interfaces_path = SCRIPT_PATH / "../interfaces"
_grpc_stubs_path = SCRIPT_PATH / "../grpc/src/auto_generated_stubs"
if _interfaces_path.exists():
    sys.path.append(str(_interfaces_path))
elif _grpc_stubs_path.exists():
    sys.path.append(str(_grpc_stubs_path))

# Data handling
DATA_CHUNK_SIZE = 64 * 1024  # 64 KiB per gRPC message
DEFAULT_BITRATE_BPS = 10_000_000  # 10 Mbps; keep in sync with grpc DEFAULT_OUTPUT_VIDEO_BITRATE_BPS
DEFAULT_IDR_INTERVAL = 8

# Default input video — first existing path wins, else a relative fallback.
_default_video_candidates = [
    PROJECT_ROOT / "assets/sample_video.mp4",
    PROJECT_ROOT / "assets/test/relighting_video.mp4",
]
DEFAULT_VIDEO_PATH = next(
    (str(p) for p in _default_video_candidates if p.exists()),
    "./assets/sample_video.mp4",
)

# Relighting effect defaults (matching RelightingEffectApp)
DEFAULT_PAN_DEGREES = -90.0
DEFAULT_VFOV_DEGREES = 60.0
DEFAULT_ROTATION_RATE_DEGREES = 20.0
DEFAULT_FOREGROUND_GAIN = 1.0
DEFAULT_BACKGROUND_GAIN = 1.0
DEFAULT_BLUR_STRENGTH = 0.0
DEFAULT_SPECULAR = 0.0

# BackgroundSource enum values (aligned with proto BackgroundSource).
BACKGROUND_SOURCE_UNSPECIFIED = 0
BACKGROUND_SOURCE_FROM_IMAGE = 1
BACKGROUND_SOURCE_FROM_HDR = 2

BACKGROUND_SOURCE_NAMES = {
    BACKGROUND_SOURCE_UNSPECIFIED: "UNSPECIFIED (source video)",
    BACKGROUND_SOURCE_FROM_IMAGE: "FROM_IMAGE (custom image)",
    BACKGROUND_SOURCE_FROM_HDR: "FROM_HDR (HDR projection)",
}
