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

"""Main script for running LipSync inference with video and audio files.

This script provides the following functionality:
- Parse command-line arguments for configuring LipSync.
- Set up gRPC communication with the LipSync service.
- Send video, audio, and speaker data to the service.
- Process responses and write output video files.

The script supports various SSL modes for secure communication and handles
numerous input/output formats and configurations.
"""

import json
import os
import sys
import time
import grpc
from typing import Iterator
import pathlib
from config import LipSyncConfig, parse_args
from constants import (
    AUDIO_CODEC_CONFIGS,
    DATA_CHUNK_SIZE,
    EXTEND_AUDIO_CONFIGS,
    EXTEND_VIDEO_CONFIGS,
    SPEAKER_DATA_BATCH_SIZE,
)
from contextlib import nullcontext
from tqdm import tqdm

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../../")))
from utils.utils import (  # noqa: E402
    create_channel_credentials,
    create_protobuf_any_value,
)

# Importing gRPC compiler auto-generated lipsync library
SCRIPT_PATH = str(pathlib.Path(__file__).parent.resolve())
sys.path.insert(0, os.path.join(SCRIPT_PATH, "../interfaces"))
import nvidia.ai4m.lipsync.v1.lipsync_pb2 as lipsync_pb2  # noqa: E402
import nvidia.ai4m.lipsync.v1.lipsync_pb2_grpc as lipsync_pb2_grpc  # noqa: E402
import nvidia.ai4m.video.v1.video_pb2 as video_pb2  # noqa: E402
import nvidia.ai4m.audio.v1.audio_pb2 as audio_pb2  # noqa: E402
import nvidia.ai4m.common.v1.common_pb2 as common_pb2  # noqa: E402


def create_custom_encoding_params(params: dict) -> video_pb2.CustomEncodingParams:
    """Create CustomEncodingParams from a dictionary.

    This function creates a CustomEncodingParams protobuf message from a dictionary of parameters.
    The CustomEncodingParams message specifies custom encoding parameters for the
    deepstream encoder.

    Example:
        params = {
            "bitrate": 5000000,
            "idrinterval": 30,
            "maxbitrate": 5000000,
            "tuning-info-id": 4
        }
        custom_encoding = create_custom_encoding_params(params)

    Args:
        params: Dictionary with string keys and values of type bool, int, float, or str

    Returns:
        CustomEncodingParams protobuf message
    """
    custom_params = video_pb2.CustomEncodingParams()
    for key, value in params.items():
        custom_params.custom[key].CopyFrom(create_protobuf_any_value(value))
    return custom_params


def batched_json_reader(frames: list, batch_size: int) -> Iterator[list]:
    """Read JSON frame data in batches.

    Args:
        frames: List of frame dictionaries from JSON
        batch_size: Number of frames to include in each batch

    Yields:
        List of frames in batches of the specified size
    """
    for i in range(0, len(frames), batch_size):
        yield frames[i : i + batch_size]


def generate_request_for_inference(
    lipsync_config: LipSyncConfig,
) -> Iterator[lipsync_pb2.LipsyncRequest]:
    """Generate a stream of LipsyncRequest messages for the LipSync service.

    Args:
        lipsync_config: Configuration object containing all LipSync parameters

    Yields:
        LipsyncRequest messages containing either configuration or chunks of input data

    Raises:
        RuntimeError: If there are errors reading input files
    """
    print("Generating request for inference")

    if lipsync_config.lossless:
        output_video_encoding = video_pb2.VideoEncoding(lossless=True)
    elif lipsync_config.custom_encoding_params:
        output_video_encoding = video_pb2.VideoEncoding(
            custom_encoding=create_custom_encoding_params(lipsync_config.custom_encoding_params)
        )
    else:
        output_video_encoding = video_pb2.VideoEncoding(
            lossy=video_pb2.LossyEncoding(
                bitrate_mbps=lipsync_config.bitrate, idr_interval=lipsync_config.idr_interval
            )
        )

    # Build background audio config
    background_audio_config = None
    if lipsync_config.mix_background_audio and lipsync_config.background_audio_filepath:
        bg_ext = os.path.splitext(lipsync_config.background_audio_filepath)[1].lower().lstrip(".")
        background_audio_config = lipsync_pb2.BackgroundAudioConfig(
            is_background_audio_provided=True,
            audio_codec=AUDIO_CODEC_CONFIGS.get(bg_ext, audio_pb2.AudioCodec.AUDIO_CODEC_WAV),
            audio_volume=lipsync_config.background_audio_volume,
        )

    params = {
        "input_audio_codec": AUDIO_CODEC_CONFIGS[lipsync_config.input_audio_codec],
        "extend_audio": EXTEND_AUDIO_CONFIGS[lipsync_config.extend_audio],
        "extend_video": EXTEND_VIDEO_CONFIGS[lipsync_config.extend_video],
        "output_video_encoding": output_video_encoding,
        "is_speaker_info_provided": lipsync_config.is_speaker_info_provided,
        "output_audio_codec": AUDIO_CODEC_CONFIGS[lipsync_config.output_audio_codec],
    }

    if lipsync_config.head_movement_speed is not None:
        params["head_movement_speed"] = lipsync_config.head_movement_speed

    if background_audio_config is not None:
        params["background_audio_config"] = background_audio_config

    print("Sending data for inference")

    # Send config
    yield lipsync_pb2.LipsyncRequest(config=lipsync_pb2.LipsyncConfig(**params))

    # Load JSON speaker data if provided
    json_frames = None
    if lipsync_config.speaker_data_filepath and lipsync_config.is_speaker_info_provided:
        print(f"Loading JSON speaker data from {lipsync_config.speaker_data_filepath}")
        with open(lipsync_config.speaker_data_filepath, "r") as json_fd:
            json_data = json.load(json_fd)
            json_frames = json_data.get("frames", [])
        print(f"Loaded {len(json_frames)} frames from JSON")

    # Send video, audio, speaker data, and background audio in interleaved chunks
    video_done = False
    audio_done = False
    speaker_done = True if not json_frames else False
    bg_audio_done = (
        True
        if not (lipsync_config.mix_background_audio and lipsync_config.background_audio_filepath)
        else False
    )

    with open(lipsync_config.video_filepath, "rb") as video_file, open(
        lipsync_config.audio_filepath, "rb"
    ) as audio_file, (
        open(lipsync_config.background_audio_filepath, "rb")
        if lipsync_config.mix_background_audio and lipsync_config.background_audio_filepath
        else nullcontext()
    ) as bg_audio_file:

        speaker_data_batch_iter = None
        global_frame_index = 0
        if json_frames:
            speaker_data_batch_iter = batched_json_reader(json_frames, SPEAKER_DATA_BATCH_SIZE)

        video_chunk_number = 0
        audio_chunk_number = 0
        speaker_batch_number = 0

        while not (video_done and audio_done and speaker_done and bg_audio_done):
            # Send video chunk
            if not video_done:
                try:
                    video_buffer = video_file.read(DATA_CHUNK_SIZE)
                    if video_buffer == b"":
                        video_done = True
                    else:
                        video_chunk_number += 1
                        yield lipsync_pb2.LipsyncRequest(
                            input=lipsync_pb2.LipsyncInputData(video_file_data=video_buffer)
                        )
                except IOError as e:
                    print(f"Error reading video chunk {video_chunk_number}: {e}")
                    raise RuntimeError(f"Failed to read video file: {e}") from e

            # Send audio chunk
            if not audio_done:
                try:
                    audio_buffer = audio_file.read(DATA_CHUNK_SIZE)
                    if audio_buffer == b"":
                        audio_done = True
                    else:
                        audio_chunk_number += 1
                        yield lipsync_pb2.LipsyncRequest(
                            input=lipsync_pb2.LipsyncInputData(audio_file_data=audio_buffer)
                        )
                except IOError as e:
                    print(f"Error reading audio chunk {audio_chunk_number}: {e}")
                    raise RuntimeError(f"Failed to read audio file: {e}") from e

            # Send speaker data batch
            if not speaker_done and speaker_data_batch_iter:
                try:
                    batch = next(speaker_data_batch_iter)
                    speaker_batch_number += 1

                    speaker_info_per_frame_batch = []
                    for batch_idx, frame_data in enumerate(batch):
                        speaker_data_results = frame_data.get("speakers", [])
                        current_frame_index = global_frame_index + batch_idx

                        bypass_kwargs = {}
                        if "bypass" in frame_data:
                            bypass_kwargs["bypass"] = bool(frame_data["bypass"])

                        if not speaker_data_results:
                            speaker_info = lipsync_pb2.SpeakerInfoPerFrame(
                                frame_id=current_frame_index,
                                speaker_infos=[
                                    lipsync_pb2.SpeakerInfo(
                                        speaker_bbox=common_pb2.BoundingBox(
                                            x=0, y=0, width=0, height=0
                                        ),
                                        speaker_id=0,
                                        is_speaking=True,
                                    )
                                ],
                                **bypass_kwargs,
                            )
                        else:
                            speakers = []
                            for speaker_data in speaker_data_results:
                                bbox = speaker_data.get("bbox", [0, 0, 0, 0])
                                x, y, width, height = bbox

                                speaker_id = speaker_data.get("speaker_id")
                                if speaker_id is None:
                                    speaker_id = speaker_data.get("face_tracker_id", 0)

                                is_speaking = speaker_data.get("is_speaking", False)

                                speakers.append(
                                    lipsync_pb2.SpeakerInfo(
                                        speaker_bbox=common_pb2.BoundingBox(
                                            x=float(x),
                                            y=float(y),
                                            width=float(width),
                                            height=float(height),
                                        ),
                                        speaker_id=int(speaker_id),
                                        is_speaking=bool(is_speaking),
                                    )
                                )

                            speaker_info = lipsync_pb2.SpeakerInfoPerFrame(
                                frame_id=current_frame_index,
                                speaker_infos=speakers,
                                **bypass_kwargs,
                            )

                        speaker_info_per_frame_batch.append(speaker_info)

                    global_frame_index += len(batch)

                    yield lipsync_pb2.LipsyncRequest(
                        input=lipsync_pb2.LipsyncInputData(
                            per_frame_speaker_infos=speaker_info_per_frame_batch
                        )
                    )
                except StopIteration:
                    speaker_done = True
                except Exception as e:
                    print(f"Error processing speaker data batch {speaker_batch_number}: {e}")
                    raise RuntimeError(f"Failed to process speaker data: {e}") from e

            # Send background audio chunk
            if not bg_audio_done:
                try:
                    bg_buffer = bg_audio_file.read(DATA_CHUNK_SIZE)
                    if bg_buffer == b"":
                        bg_audio_done = True
                    else:
                        yield lipsync_pb2.LipsyncRequest(
                            input=lipsync_pb2.LipsyncInputData(background_audio_file_data=bg_buffer)
                        )
                except IOError as e:
                    print(f"Error reading background audio: {e}")
                    raise RuntimeError(f"Failed to read background audio file: {e}") from e

    print("Data sending completed")


def write_output_file_from_response(
    response_iter: Iterator[lipsync_pb2.LipsyncResponse],
    output_filepath: os.PathLike = "output.mp4",
) -> None:
    """Function to write the output file from the incoming gRPC data stream.

    Args:
        response_iter: Responses from the server to write into output file
        output_filepath: Path to output file
    """
    print(f"Writing output in {output_filepath}")
    sys.stdout.flush()

    chunk_count = 0
    total_bytes = 0

    with open(output_filepath, "wb") as fd:
        pbar = tqdm(
            desc="Receiving video chunks",
            unit="chunks",
            unit_scale=False,
            dynamic_ncols=True,
            leave=False,
            bar_format="{desc}: {n} chunks | {rate_fmt} | {postfix}",
        )

        try:
            for response in response_iter:
                if response.HasField("video_file_data"):
                    chunk_data = response.video_file_data
                    fd.write(chunk_data)

                    chunk_count += 1
                    total_bytes += len(chunk_data)

                    pbar.update(1)
                    pbar.set_postfix_str(f"{total_bytes / (1024*1024):.1f} MB received")
        finally:
            pbar.close()

    print(f"Completed: Received {chunk_count} chunks ({total_bytes / (1024*1024):.1f} MB total)")


def process_request(
    channel: grpc.Channel,
    lipsync_config: LipSyncConfig,
) -> None:
    """Process gRPC request and handle responses.

    Args:
        channel: gRPC channel for server client communication
        lipsync_config: Configuration for the LipSync service

    Raises:
        Exception: If any errors occur during processing
    """
    try:
        stub = lipsync_pb2_grpc.LipSyncServiceStub(channel)
        start_time = time.time()

        responses = stub.Lipsync(generate_request_for_inference(lipsync_config=lipsync_config))
        next(responses)
        write_output_file_from_response(
            response_iter=responses, output_filepath=lipsync_config.output_filepath
        )
        end_time = time.time()
        print(f"Function invocation completed in {end_time-start_time:.2f}s")
    except Exception as e:
        print(f"An error occurred: {e}")
        raise e


def main():
    """Main entry point for the LipSync client.

    Handles:
    1. Argument parsing
    2. Configuration validation
    3. Channel setup (secure/insecure)
    4. Request processing
    """
    args = parse_args()
    lipsync_config = LipSyncConfig.from_args(args)

    try:
        lipsync_config.validate_lipsync_config()
    except Exception as e:
        print(f"Invalid configuration: {e}")
        return
    print(lipsync_config)

    if args.ssl_mode != "DISABLED":
        channel_credentials = create_channel_credentials(args)
        with grpc.secure_channel(target=args.target, credentials=channel_credentials) as channel:
            process_request(
                channel=channel,
                lipsync_config=lipsync_config,
            )
    else:
        print(f"Establishing insecure channel to {args.target}")
        with grpc.insecure_channel(target=args.target) as channel:
            process_request(
                channel=channel,
                lipsync_config=lipsync_config,
            )


if __name__ == "__main__":
    main()
