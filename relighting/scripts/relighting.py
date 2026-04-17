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

"""AI for Media Relighting gRPC client.

Sends an MP4 video (and optional HDRI / background images) to the
VideoRelightingService, receives the relit video, and writes it to disk.
"""

import sys
import time
from collections.abc import Iterator
from pathlib import Path

# Constants must be imported before proto stubs (it sets up sys.path).
try:  # when used as a package
    from .config import VideoRelightingConfig, parse_args
    from .constants import DATA_CHUNK_SIZE, DEFAULT_BITRATE_BPS
except ImportError:  # when run as a standalone script
    from config import VideoRelightingConfig, parse_args
    from constants import DATA_CHUNK_SIZE, DEFAULT_BITRATE_BPS

import grpc
from nvidia.ai4m.relighting.v1 import relighting_pb2, relighting_pb2_grpc
from nvidia.ai4m.video.v1 import video_pb2

from utils.utils import (
    create_channel_credentials,
    create_protobuf_any_value,
    create_request_metadata,
    validate_preview_args,
)

# ---------------------------------------------------------------------------
# Request generation
# ---------------------------------------------------------------------------


def _iter_image_chunks(
    image_bytes: bytes,
    image_type: int,
) -> Iterator[relighting_pb2.RelightRequest]:
    """Yield ``RelightRequest(image_data=…)`` messages in ``DATA_CHUNK_SIZE`` pieces."""
    for offset in range(0, len(image_bytes), DATA_CHUNK_SIZE):
        yield relighting_pb2.RelightRequest(
            image_data=relighting_pb2.ImageData(
                image_type=image_type,
                data=image_bytes[offset : offset + DATA_CHUNK_SIZE],
            )
        )


def _iter_video_chunks(
    source: bytes | Path | str,
) -> Iterator[relighting_pb2.RelightRequest]:
    """Yield ``RelightRequest(video_data=…)`` messages from a buffer or file path."""
    if isinstance(source, bytes):
        for offset in range(0, len(source), DATA_CHUNK_SIZE):
            yield relighting_pb2.RelightRequest(
                video_data=source[offset : offset + DATA_CHUNK_SIZE]
            )
    else:
        with open(source, "rb") as f:
            while chunk := f.read(DATA_CHUNK_SIZE):
                yield relighting_pb2.RelightRequest(video_data=chunk)


def _build_video_encoding(cfg: VideoRelightingConfig) -> video_pb2.VideoEncoding:
    """Translate CLI encoding options into a ``VideoEncoding`` proto."""
    enc = video_pb2.VideoEncoding()
    if cfg.lossless:
        enc.lossless = True
    elif cfg.custom_encoding_params:
        for key, value in cfg.custom_encoding_params.items():
            enc.custom_encoding.custom[key].CopyFrom(create_protobuf_any_value(value))
    else:
        bitrate_mbps = max(1, round(cfg.bitrate / 1_000_000)) if cfg.bitrate > 0 else 0
        enc.lossy.CopyFrom(
            video_pb2.LossyEncoding(bitrate_mbps=bitrate_mbps, idr_interval=cfg.idr_interval)
        )
    return enc


def _build_relight_config(
    cfg: VideoRelightingConfig,
    has_hdri_image: bool,
) -> relighting_pb2.RelightConfig:
    """Populate a ``RelightConfig`` proto from the client config."""
    rc = relighting_pb2.RelightConfig()

    # HDRI source
    if has_hdri_image:
        rc.hdri_image_provided = True
    else:
        rc.hdri_preset_id = cfg.hdri_id

    rc.angle_pan_radians = cfg.get_pan_radians()
    rc.angle_v_fov_radians = cfg.get_vfov_radians()

    # Background
    rc.background_source = cfg.background_source
    if cfg.background_image_type is not None:
        rc.background_image_type = cfg.background_image_type
    bg_color = cfg.get_background_color_int()
    if bg_color is not None:
        rc.background_color = bg_color

    # Effects
    rc.foreground_gain = cfg.foreground_gain
    rc.background_gain = cfg.background_gain
    rc.blur_strength = cfg.blur
    rc.specular = cfg.specular

    # Autorotate
    rc.autorotate = cfg.autorotate
    rc.rotation_rate = cfg.get_rotation_rate_radians()

    rc.output_video_encoding.CopyFrom(_build_video_encoding(cfg))
    return rc


def generate_requests(
    cfg: VideoRelightingConfig,
) -> Iterator[relighting_pb2.RelightRequest]:
    """Stream ``RelightRequest`` messages: config, images, then video chunks."""
    print("Generating request for inference...")

    hdri_bytes = cfg.get_hdri_image_bytes()
    bg_bytes = cfg.get_background_image_bytes()

    # 1. Config
    yield relighting_pb2.RelightRequest(
        config=_build_relight_config(cfg, has_hdri_image=hdri_bytes is not None)
    )

    if cfg.bitrate != DEFAULT_BITRATE_BPS:
        print(f"Using output bitrate override: {cfg.bitrate:,} bps")

    # 2. Inline images (before video)
    if hdri_bytes is not None:
        print(f"Sending HDR image ({len(hdri_bytes):,} bytes)...")
        yield from _iter_image_chunks(hdri_bytes, relighting_pb2.IMAGE_TYPE_HDRI)
    if bg_bytes is not None:
        print(f"Sending background image ({len(bg_bytes):,} bytes)...")
        yield from _iter_image_chunks(bg_bytes, relighting_pb2.IMAGE_TYPE_BACKGROUND)

    # 3. Video
    print("Sending video data to server...")
    source = cfg.video_filepath
    chunk_count = 0
    for req in _iter_video_chunks(source):
        chunk_count += 1
        yield req

    print(f"Video chunks sent: {chunk_count}")


# ---------------------------------------------------------------------------
# Response handling
# ---------------------------------------------------------------------------


def _print_progress(response: relighting_pb2.RelightResponse) -> None:
    """Print inline progress for *image_upload_ack*, *progress*, and *keep_alive*."""
    if response.HasField("image_upload_ack"):
        ack = response.image_upload_ack
        label = "HDRI" if ack.image_type == 1 else "Background"
        print(f"{label} image accepted ({ack.size_bytes / 1024:.1f} KB)")

    elif response.HasField("progress"):
        prog = response.progress
        if prog.HasField("total_frames") and prog.total_frames > 0:
            pct = 100 * prog.frames_processed // prog.total_frames
            print(
                f"\r\033[KProcessing: {pct}% (frame {prog.frames_processed} / {prog.total_frames})",
                end="",
                flush=True,
            )
        else:
            print(f"\r\033[KProcessing: frame {prog.frames_processed}", end="", flush=True)

    elif response.HasField("keep_alive"):
        print("\r\033[KProcessing...", end="", flush=True)


def write_response_to_file(
    responses: Iterator[relighting_pb2.RelightResponse],
    output_filepath: Path | str,
) -> None:
    """Consume *responses*, write video data to *output_filepath*, and show progress."""
    print(f"Writing output to: {output_filepath}")
    sys.stdout.flush()

    chunk_count = 0
    total_bytes = 0
    start_time = time.time()
    first_chunk_time: float | None = None
    last_update_time = 0.0

    with open(output_filepath, "wb") as fd:
        for response in responses:
            if not response.HasField("video_data"):
                _print_progress(response)
                continue

            fd.write(response.video_data)
            chunk_count += 1
            total_bytes += len(response.video_data)
            now = time.time()

            if chunk_count == 1:
                first_chunk_time = now
                print(f"\rServer ready in {first_chunk_time - start_time:.1f}s" + " " * 20)

            if now - last_update_time >= 0.5 or chunk_count % 50 == 0:
                elapsed = now - first_chunk_time if first_chunk_time else 0
                mb = total_bytes / (1024 * 1024)
                rate = mb / elapsed if elapsed > 0 else 0
                print(
                    f"\rReceiving: {chunk_count} chunks | {mb:.2f} MB | "
                    f"{rate:.2f} MB/s | {elapsed:.1f}s",
                    end="",
                    flush=True,
                )
                last_update_time = now

    # Final summary
    mb_total = total_bytes / (1024 * 1024)
    if first_chunk_time:
        transfer = time.time() - first_chunk_time
        rate = mb_total / transfer if transfer > 0 else 0
        print(
            f"\rCompleted: {chunk_count} chunks"
            f" | {mb_total:.2f} MB"
            f" | {rate:.2f} MB/s"
            f" | {transfer:.1f}s"
        )
    else:
        elapsed = time.time() - start_time
        print(f"\nCompleted: {chunk_count} chunks | {mb_total:.2f} MB | {elapsed:.1f}s")


def _run_normal(
    stub: relighting_pb2_grpc.VideoRelightingServiceStub,
    cfg: VideoRelightingConfig,
    request_metadata: tuple | None = None,
) -> None:
    """Normal (non-benchmark) relighting run."""
    start = time.time()
    responses = stub.Relight(generate_requests(cfg), metadata=request_metadata)
    write_response_to_file(responses, cfg.output_filepath)
    print(f"\nRelighting completed in {time.time() - start:.2f}s")
    print(f"   Output saved to: {cfg.output_filepath}")


def process_request(
    channel: grpc.Channel,
    cfg: VideoRelightingConfig,
    request_metadata: tuple | None = None,
) -> None:
    """Send a relighting request over *channel* and handle the response."""
    try:
        stub = relighting_pb2_grpc.VideoRelightingServiceStub(channel)
        _run_normal(stub, cfg, request_metadata=request_metadata)
    except grpc.RpcError as e:
        details = e.details() or ""
        print(f"\nERROR: gRPC error: {e.code()} - {details}")
        if "Exception iterating requests" in details or "Server Error:" in details:
            print("   Check server logs: docker compose logs relighting-server")
        sys.exit(1)
    except OSError as e:
        print(f"\nERROR: I/O failure: {e}")
        sys.exit(1)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def _open_channel(args: object, options: list[tuple]) -> grpc.Channel:
    """Create a secure or insecure gRPC channel based on ``args.ssl_mode`` and preview mode."""
    if args.ssl_mode != "DISABLED":
        credentials = create_channel_credentials(args)
        print(f"Establishing secure channel to {args.target}")
        return grpc.secure_channel(target=args.target, credentials=credentials, options=options)
    if args.preview_mode:
        print(f"Establishing secure channel to {args.target} (preview mode)")
        return grpc.secure_channel(
            target=args.target, credentials=grpc.ssl_channel_credentials(), options=options
        )
    print(f"Establishing insecure channel to {args.target}")
    return grpc.insecure_channel(target=args.target, options=options)


def main() -> None:
    args = parse_args()
    cfg = VideoRelightingConfig.from_args(args)
    cfg.validate()
    validate_preview_args(args)

    print(cfg)
    print(f"Target server:     {args.target}")
    print("=" * 70)

    request_metadata = create_request_metadata(args)

    channel_options = [
        ("grpc.max_send_message_length", 100 * 1024 * 1024),
        ("grpc.max_receive_message_length", 100 * 1024 * 1024),
        ("grpc.keepalive_time_ms", 10_000),
        ("grpc.keepalive_timeout_ms", 60_000),
        ("grpc.keepalive_permit_without_calls", True),
        ("grpc.http2.max_pings_without_data", 0),
    ]

    with _open_channel(args, channel_options) as channel:
        process_request(channel, cfg, request_metadata=request_metadata)


if __name__ == "__main__":
    main()
