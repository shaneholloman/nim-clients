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

"""Diarization parsers for Active Speaker Detection NIM client.

Provides an abstract ``DiarizationParser`` base class that users can subclass
to support custom diarization data formats (JSON, CSV, plain text, etc.).

Ships with built-in parsers:

- ``SampleDiarizationParser``: for the sample diarization JSON format with
  top-level ``words`` array containing ``text``, ``start``, ``end``, and
  ``speaker_id`` fields.
- ``RIVADiarizationParser``: for NVIDIA RIVA ASR diarized output with
  ``results[].alternatives[].words[]`` containing ``startTime``, ``endTime``,
  ``word``, ``speakerTag``, and ``languageCode`` fields.
"""

import json
import os
import re
from abc import ABC, abstractmethod

import pathlib
import sys

SCRIPT_PATH = str(pathlib.Path(__file__).parent.resolve())
sys.path.append(os.path.join(SCRIPT_PATH, "../interfaces"))
from nvidia.ai4m.activespeakerdetection.v1 import activespeakerdetection_pb2  # noqa: E402

AudioSegmentInfo = activespeakerdetection_pb2.AudioSegmentInfo
AudioDiarizationInfo = activespeakerdetection_pb2.AudioDiarizationInfo


# ---------------------------------------------------------------------------
# Abstract base class
# ---------------------------------------------------------------------------


class DiarizationParser(ABC):
    """Abstract base class for diarization data parsers.

    Subclass this to add support for your own diarization format (JSON,
    CSV, plain text, etc.).  Implement :meth:`can_parse` to declare what
    content you handle, and :meth:`parse` to convert raw file content
    into ``AudioSegmentInfo`` protos.
    """

    @abstractmethod
    def can_parse(self, raw_content: str) -> bool:
        """Check whether this parser understands the given file content.

        Args:
            raw_content: Raw text content of the diarization file.

        Returns:
            True if this parser can handle the content.
        """

    @abstractmethod
    def parse(
        self,
        raw_content: str,
    ) -> tuple[list[AudioSegmentInfo], str | None]:
        """Parse raw diarization file content into ``AudioSegmentInfo`` protos.

        Args:
            raw_content: Raw text content of the diarization file.

        Returns:
            Tuple of (list of AudioSegmentInfo protos, optional transcript).

        Raises:
            ValueError: If the content is malformed.
        """

    def load(self, filepath: str | os.PathLike) -> AudioDiarizationInfo:
        """Read a diarization file and parse it into an ``AudioDiarizationInfo``.

        Reads the file as text, calls :meth:`parse`, and assembles the
        protobuf message. Subclasses that need binary reads can override
        this method.

        Args:
            filepath: Path to the diarization file.

        Returns:
            Populated ``AudioDiarizationInfo`` protobuf message.

        Raises:
            ValueError: If the data cannot be parsed.
            FileNotFoundError: If *filepath* does not exist.
        """
        with open(filepath, encoding="utf-8") as f:
            raw_content = f.read()

        segments, transcript = self.parse(raw_content)
        kwargs: dict = {"segments": segments}
        if transcript:
            kwargs["transcript"] = transcript
        return AudioDiarizationInfo(**kwargs)


# ---------------------------------------------------------------------------
# Sample diarization JSON format
# ---------------------------------------------------------------------------

_SPEAKER_ID_RE = re.compile(r"\d+")


class SampleDiarizationParser(DiarizationParser):
    """Parser for the sample diarization JSON format.

    Expects a top-level JSON object with a ``words`` array where each entry
    has ``text`` (str), ``start``/``end`` (float seconds), and ``speaker_id``
    (e.g. ``"speaker_0"``).  An optional top-level ``text`` field is used as
    the transcript, and ``language_code`` is applied to every segment.
    """

    def can_parse(self, raw_content: str) -> bool:
        try:
            data = json.loads(raw_content)
            return isinstance(data, dict) and "words" in data
        except (json.JSONDecodeError, ValueError):
            return False

    @staticmethod
    def _parse_speaker_id(speaker_id: str | int) -> int:
        """Extract the integer speaker id from a value like ``"speaker_0"``."""
        if isinstance(speaker_id, int):
            return speaker_id
        m = _SPEAKER_ID_RE.search(str(speaker_id))
        if m:
            return int(m.group())
        raise ValueError(f"Cannot extract speaker id from {speaker_id!r}")

    def parse(
        self,
        raw_content: str,
    ) -> tuple[list[AudioSegmentInfo], str | None]:
        data = json.loads(raw_content)
        if not isinstance(data, dict):
            raise ValueError("SampleDiarizationParser expects a JSON object with a 'words' key.")

        words = data.get("words")
        if not isinstance(words, list):
            raise ValueError("'words' field must be a list.")

        transcript: str | None = data.get("text")
        language_code: str | None = data.get("language_code")

        segments: list[AudioSegmentInfo] = []
        for word in words:
            if "speaker_id" not in word:
                raise ValueError("Missing speaker_id in word entry.")
            kwargs: dict = {
                "start_time": int(round(float(word.get("start", 0)) * 1000)),
                "end_time": int(round(float(word.get("end", 0)) * 1000)),
                "speaker_id": self._parse_speaker_id(word.get("speaker_id", 0)),
            }
            if word.get("text") is not None:
                kwargs["word"] = str(word["text"])
            if language_code:
                kwargs["language_code"] = language_code

            segments.append(AudioSegmentInfo(**kwargs))

        return segments, transcript


# ---------------------------------------------------------------------------
# RIVA ASR diarized JSON format
# ---------------------------------------------------------------------------


class RIVADiarizationParser(DiarizationParser):
    """Parser for NVIDIA RIVA ASR diarized output.

    Expects a JSON object with a ``results`` array.  Each result contains
    an ``alternatives`` array whose first element holds ``transcript`` (str)
    and ``words`` (list).  Each word entry has:

    - ``startTime`` / ``endTime``: int milliseconds
    - ``word``: str
    - ``speakerTag``: int speaker identifier
    - ``languageCode``: str (e.g. ``"en-US"``)
    - ``confidence``: float (unused, kept for reference)

    Multiple results are concatenated into a single flat segment list.
    """

    def can_parse(self, raw_content: str) -> bool:
        try:
            data = json.loads(raw_content)
            if not isinstance(data, dict) or "results" not in data:
                return False
            results = data["results"]
            if not isinstance(results, list) or len(results) == 0:
                return False
            first = results[0]
            return isinstance(first.get("alternatives"), list)
        except (json.JSONDecodeError, ValueError):
            return False

    def parse(
        self,
        raw_content: str,
    ) -> tuple[list[AudioSegmentInfo], str | None]:
        data = json.loads(raw_content)
        results = data.get("results")
        if not isinstance(results, list):
            raise ValueError("RIVADiarizationParser expects a JSON object with a 'results' key.")

        segments: list[AudioSegmentInfo] = []
        transcripts: list[str] = []

        for result in results:
            alternatives = result.get("alternatives")
            if not isinstance(alternatives, list) or len(alternatives) == 0:
                continue

            alt = alternatives[0]
            transcript = alt.get("transcript")
            if transcript:
                transcripts.append(transcript)

            words = alt.get("words", [])
            for word in words:
                kwargs: dict = {
                    "start_time": int(word.get("startTime", 0)),
                    "end_time": int(word.get("endTime", 0)),
                    "speaker_id": int(word.get("speakerTag", 0)),
                }
                if word.get("word") is not None:
                    kwargs["word"] = str(word["word"])
                lang = word.get("languageCode")
                if lang:
                    kwargs["language_code"] = lang

                segments.append(AudioSegmentInfo(**kwargs))

        combined_transcript = " ".join(transcripts) if transcripts else None
        return segments, combined_transcript


# ---------------------------------------------------------------------------
# Auto-detection registry
# ---------------------------------------------------------------------------

_PARSERS: list[DiarizationParser] = [
    RIVADiarizationParser(),
    SampleDiarizationParser(),
]


def load_diarization(filepath: str | os.PathLike) -> AudioDiarizationInfo:
    """Auto-detect the diarization format and load it.

    Tries each registered parser's ``can_parse`` in order and uses the
    first match.

    Args:
        filepath: Path to the diarization JSON file.

    Returns:
        Populated ``AudioDiarizationInfo`` protobuf message.

    Raises:
        ValueError: If no parser recognises the format.
    """
    with open(filepath, encoding="utf-8") as f:
        raw_content = f.read()

    for parser in _PARSERS:
        if parser.can_parse(raw_content):
            segments, transcript = parser.parse(raw_content)
            kwargs: dict = {"segments": segments}
            if transcript:
                kwargs["transcript"] = transcript
            return AudioDiarizationInfo(**kwargs)

    raise ValueError(
        f"No parser recognised the diarization format in {filepath}. "
        f"Expected either RIVA (results[].alternatives[].words[]) "
        f"or sample (top-level 'words' array) format."
    )
