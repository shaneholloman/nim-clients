# NVIDIA Active Speaker Detection NIM Client

This package has a sample client which demonstrates interaction with an Active Speaker Detection NIM.

The client sends video, audio, and diarization data to the service and produces an output video with speaker bounding boxes overlaid on the original frames.

## Pre-requisites

- Python 3.10 or above. Refer to the [Python documentation](https://www.python.org/downloads/) for installation instructions.
- Access to NVIDIA Active Speaker Detection NIM Container / Service.

## Usage guide

### 1. Clone the repository

```bash
git clone https://github.com/nvidia-maxine/nim-clients.git
cd nim-clients/active-speaker-detection
```

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

### 3. Host the NIM Server

Set up the Active Speaker Detection NIM server by following the [quick start guide](https://docs.nvidia.com/nim/maxine/active-speaker-detection/latest/index.html).

### 4. Compile the Protos

If you want to use the client code provided in the GitHub client repository, you can skip this step.

The proto files are available in the `active-speaker-detection/protos` folder. You can compile them to generate client interfaces in your preferred programming language. For more details, refer to [Supported languages](https://grpc.io/docs/languages/) in the gRPC documentation.

The following example shows how to compile the protos for Python on Linux and Windows.

#### Python

The `grpcio` version needed for compilation can be referred at `requirements.txt`

**To compile protos on Linux:**
```bash
# Go to active-speaker-detection/protos/linux/ folder
cd active-speaker-detection/protos/linux/

chmod +x compile_protos.sh
./compile_protos.sh
```

**To compile protos on Windows:**
```bash
# Go to active-speaker-detection/protos/windows/ folder
cd active-speaker-detection/protos/windows/

./compile_protos.bat
```

The compiled proto files appear in the `nim-clients/active-speaker-detection/interfaces` directory.

### Supported Formats

#### Video

| Format | Codec | Container |
|--------|-------|-----------|
| H.264  | H.264 | MP4 (.mp4) |

The input video must be a streamable MP4 file (moov atom at the start of the file). Non-streamable MP4 files will fail to process correctly.

#### Audio

| Format | Extension |
|--------|-----------|
| WAV    | `.wav`    |
| MP3    | `.mp3`    |
| Opus   | `.opus`   |

When using `--skip-audio`, the audio embedded in the MP4 video file is used. The embedded audio must be encoded in one of the above supported formats.

#### Converting MP4 Files to Streamable Format

Standard MP4 files may not be streamable (the moov atom is at the end of the file). Use the following `ffmpeg` command to make the file streamable:

```bash
ffmpeg -i input.mp4 -movflags +faststart output_streamable.mp4
```

### 5. Run the Python Client

```bash
cd scripts

python active_speaker_detection.py \
    --target 127.0.0.1:8001 \
    --video-input ../assets/sample_video_streamable.mp4 \
    --audio-input ../assets/sample_audio.wav \
    --diarization-input ../assets/sample_diarization.json \
    --output speaker_detection_output.mp4
```

The output video will have green bounding boxes on speaking faces and red on non-speaking faces.

To skip sending a separate audio stream (use audio embedded in the video):

```bash
python active_speaker_detection.py \
    --target 127.0.0.1:8001 \
    --video-input ../assets/sample_video_streamable.mp4 \
    --diarization-input ../assets/sample_diarization.json \
    --skip-audio
```

#### Invoking via NVCF API (Preview Mode)

To run inference against the NVIDIA Cloud Functions (NVCF) hosted service, use preview mode:

```bash
cd scripts

python active_speaker_detection.py --preview-mode \
    --target grpc.nvcf.nvidia.com:443 \
    --function-id <FUNCTION_ID> \
    --api-key <NVCF_API_KEY> \
    --video-input ../assets/sample_video_streamable.mp4 \
    --output out.mp4
```

Replace `<FUNCTION_ID>` and `<NVCF_API_KEY>` with your assigned function ID and API key. In preview mode, the client connects over a secure gRPC channel to the NVCF endpoint. Audio and diarization can be omitted for a quick test -- the service will use the audio embedded in the video.


### 6. Important Usage Notes

#### Input Modes

The Active Speaker Detection NIM provides two modes for processing input files: streaming and transactional.

| Aspect                | Transactional Mode                                                                   | Streaming Mode                                                       |
| --------------------- | ------------------------------------------------------------------------------------ | -------------------------------------------------------------------- |
| **Data Storage**      | Entire video and audio files are temporarily copied on disk.                         | Only frames being processed are temporarily copied in memory.        |
| **Processing Start**  | NIM waits to receive entire files before starting.                                   | NIM starts processing as soon as data chunk for first frame arrives. |
| **Processing Timing** | Processing begins after all data is received.                                        | Continuous processing without waiting for complete input.            |
| **Diarization Data**  | Complete diarization input is received with video and audio before processing begins. | Diarization must be available at the time of the first inference request. If diarization is not supplied for that request, the session is treated as having no diarization, which can result in incorrect outputs. Provide diarization by interleaving it with stream data or by sending the diarization payload before the first inference call. |
| **Output Delivery**   | Complete results are returned to client after inference is finished for whole video. | Results are generated and returned immediately per frame.            |

#### Streaming Mode

Streaming mode is the recommended way to use Active Speaker Detection NIM.  It allows inference to begin without receiving the whole video from the client. It processes video frames incrementally, and inference begins as soon as the first frame of information is available. The output frames are then streamed back to the client immediately after inference.

The NIM automatically detects streamable videos and enables streaming mode. This mode delivers the lowest latency and best resource efficiency, and it scales well to large files.

Use streaming mode for these use cases:
- Best overall performance—the NIM is optimized for this path.
- Streamable video inputs.
- Applications that benefit from receiving output as it is generated, without waiting for the entire file to be uploaded.
- Large video files that benefit from incremental processing and reduced disk I/O.

Streaming mode works with streamable videos in which metadata is positioned at the beginning of the file. The NIM automatically detects streamable videos and enables streaming mode. Videos that are not streamable can be easily converted to a streamable format.

To make any video streamable, use FFmpeg with the following command:

```bash
ffmpeg -i sample_video.mp4 -movflags +faststart sample_video_streamable.mp4
```

##### Streaming Mode and Diarization

In streaming mode, diarization must be available at the time of the first inference request. If diarization is not supplied for that request, the session is treated as having no diarization, which can result in incorrect outputs.

```{note}
We recommend that you provide diarization data by interleaving it with stream data or by sending the diarization payload before the first inference call.
```

#### Transactional Mode

In transactional mode, the video and audio files must be completely received by the NIM before processing can begin. This is the default mode; no flag must be set.

Transactional mode is suitable for the following use cases:

- Processing of small video and audio files.
- Applications that can wait for complete processing before receiving output.
- Videos that are not optimized for streaming (such as non-streamable MP4 files in which metadata is located at the end of the file, requiring the entire file to be downloaded before playback can begin).

#### Command Line Arguments

| Argument              | Description                                                                 | Default                              |
|-----------------------|-----------------------------------------------------------------------------|--------------------------------------|
| `--target`            | IP:port of gRPC service.                                                    | `127.0.0.1:8001`                     |
| `--video-input`       | Path to input video file (MP4 format).                                      | `../assets/sample_video_streamable.mp4`    |
| `--audio-input`       | Path to input audio file (WAV/MP3/OPUS format).                             | `../assets/sample_audio.wav`         |
| `--diarization-input` | Path to diarization JSON file with word-level speaker info.                 | `../assets/sample_diarization.json`  |
| `--output`            | Path for the output video file with speaker bounding boxes.                 | `speaker_detection_output.mp4`       |
| `--skip-audio`        | Skip sending separate audio; use audio embedded in the video stream.        | `False`                              |
| `--preview-mode`      | Send request to the preview NVCF NIM server.                                | `False`                              |
| `--api-key`           | NGC API key for authentication. Required in preview mode.                   | `None`                               |
| `--function-id`       | NVCF function ID for the service. Required in preview mode.                 | `None`                               |
| `--ssl-mode`          | SSL mode: `DISABLED`, `TLS`, or `MTLS`.                                    | `DISABLED`                           |
| `--ssl-key`           | Path to SSL private key (required for MTLS).                                | `../ssl_key/ssl_key_client.pem`      |
| `--ssl-cert`          | Path to SSL certificate chain (required for MTLS).                          | `../ssl_key/ssl_cert_client.pem`     |
| `--ssl-root-cert`     | Path to SSL root certificate (required for TLS/MTLS).                       | `../ssl_key/ssl_ca_cert.pem`         |


#### Output Format

The sample client produces an output video with speaker bounding boxes overlaid on the original frames. A three-color scheme is used to indicate speaker state:

| Color   | State                                                        |
| ------- | ------------------------------------------------------------ |
| Green   | Face is actively speaking.                                   |
| Blue    | Face has an assigned audio track (diarized) but is not speaking. |
| Red     | Face is tracked but has no audio track assigned.             |


#### Diarization Input Format

The client package ships with two JSON parsers in `scripts/diarization.py`:

- **`RIVADiarizationParser`** — NVIDIA RIVA ASR diarized output.
- **`SampleDiarizationParser`** — Sample JSON with a top-level `words` array (see below).

The helper **`load_diarization`** tries registered parsers in order (`RIVADiarizationParser` first, then `SampleDiarizationParser`) and uses the first parser whose `can_parse` accepts the file content. If you pass diarization through code paths that call `load_diarization`, RIVA exports and the sample format are both recognized automatically.

To add support for additional diarization formats (other JSON layouts, CSV, plain text, etc.), subclass the `DiarizationParser` base class in `diarization.py`, implement `can_parse` and `parse`, and register your parser in `_PARSERS` if you want it picked up by `load_diarization`.

##### Sample JSON format

The sample diarization JSON format uses a top-level object with a `words` array. Each entry contains `text`, `start` (seconds), `end` (seconds), and `speaker_id`. Optional top-level fields include `text` (full transcript) and `language_code`.

```json
{
  "language_code": "eng",
  "text": "Perfect. Hey, welcome to the show.",
  "words": [
    {
      "text": "Perfect.",
      "start": 0.219,
      "end": 0.62,
      "speaker_id": "speaker_0"
    },
    {
      "text": "Hey,",
      "start": 0.62,
      "end": 1.019,
      "speaker_id": "speaker_0"
    }
  ]
}
```

##### RIVA JSON shape (illustrative)

RIVA responses use nested `results` / `alternatives` / `words` with millisecond times and `speakerTag`:

```json
{
  "results": [
    {
      "alternatives": [
        {
          "transcript": "hello world",
          "words": [
            {
              "word": "hello",
              "startTime": 120,
              "endTime": 380,
              "speakerTag": 1,
              "languageCode": "en-US",
              "confidence": 0.95
            }
          ]
        }
      ]
    }
  ]
}
```

For generating diarization data from an audio stream, refer to the following services:

- [NVIDIA Riva ASR Overview](https://docs.nvidia.com/deeplearning/riva/user-guide/docs/asr/asr-overview.html)

Refer to the [docs](https://docs.nvidia.com/nim/maxine/active-speaker-detection/latest/index.html) for more information.
