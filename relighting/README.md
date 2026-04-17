# NVIDIA Relighting NIM Client

This package includes a sample Python client that demonstrates interaction with the NVIDIA Relighting NIM over gRPC. The client sends an MP4 (and optional custom HDRI or background images inline in the stream), applies HDR lighting and background compositing options, and writes the relit MP4 to disk.

The API is defined under the `nvidia.ai4m.relighting.v1` protobuf package (`VideoRelightingService.Relight` bidirectional stream).

## Getting Started

NVIDIA NIM client packages use gRPC. The following steps use the Python client shipped in this folder.

## Prerequisites

Access to a NVIDIA Relighting NIM container or hosted endpoint.

### Python

Ensure that you have **Python 3.12 or later** installed. For download and installation instructions, see [Download Python](https://www.python.org/downloads/).

## Usage Guide

### 1. Clone the Repository

```bash
git clone https://github.com/nvidia-maxine/nim-clients.git

# Go to the 'relighting' folder
cd nim-clients/relighting/
```

### 2. Install Dependencies

#### Python

```bash
pip install -r requirements.txt
```

### 3. Compile the Protos

If you use the pre-generated stubs under `relighting/interfaces/`, you can skip this step.

The proto files live under `relighting/protos/proto`, including:

- `nvidia/ai4m/relighting/v1/relighting.proto`: NVIDIA Relighting service (`Relight` RPC, `RelightConfig`, image upload protocol)
- `nvidia/ai4m/video/v1/video.proto`: Video encoding options (`VideoEncoding`, lossy / lossless / custom)

You can compile them for your preferred language; see [Supported languages](https://grpc.io/docs/languages/) in the gRPC documentation.

The `grpcio-tools` version used for compilation should match the `grpcio` / `grpcio-tools` versions in `requirements.txt`.

#### Python

**Linux:**

```bash
cd relighting/protos/linux/
chmod +x compile_protos.sh
./compile_protos.sh
```

**Windows:**

```bash
cd relighting/protos/windows/
compile_protos.bat
```

Generated Python modules are written under `nim-clients/relighting/interfaces/` (package layout under `nvidia/`).

### 4. Host the NIM Server

Before running the client, deploy or start an NVIDIA Relighting NIM instance. The simplest path is the public documentation: [Getting Started](https://docs.nvidia.com/nim/maxine/relighting/latest/getting-started.html).

The gRPC service is exposed on port **8001** in the default container layout (HTTP/NIM endpoints may use other ports; see the deployment guide you are following).

### 5. Run the Python Client

Go to the `scripts` directory (from the repository root, `nim-clients/relighting/scripts`).

```bash
cd scripts
```

#### Usage for a Hosted NIM Request

```bash
python3 relighting.py \
  --target <server_ip:port> \
  --video-input <input_video_file_path> \
  --output <output_file_path> \
  --ssl-mode <ssl_mode_value> \
  --ssl-key <ssl_key_file_path> \
  --ssl-cert <ssl_cert_filepath> \
  --ssl-root-cert <ssl_root_cert_filepath>
```

Running the script with no arguments uses the defaults documented below.

To view details of all command-line arguments, run:

```bash
python3 relighting.py -h
```

#### Usage for Preview API Request

To use the [Try API](https://build.nvidia.com/nvidia/maxine-relighting/api) preview on NVIDIA Cloud Functions, pass `--preview-mode` with your NGC API key and function ID:

```bash
python3 relighting.py --preview-mode \
  --target grpc.nvcf.nvidia.com:443 \
  --function-id <FUNCTION_ID> \
  --api-key $NGC_API_KEY \
  --video-input <input_file_path> \
  --output <output_file_path>
```

Replace `<FUNCTION_ID>` with your assigned function ID from [build.nvidia.com](https://build.nvidia.com/nvidia/maxine-relighting/api). This step does not require hosting a NIM server yourself.

#### Example Command Using the Packaged Sample Input

From `relighting/scripts`, with a local insecure endpoint:

```bash
python3 relighting.py --target 127.0.0.1:8001 --video-input ../assets/sample_video.mp4 --output out.mp4
```

If you omit `--output`, the client writes `<input_basename>-relighting_output.mp4` in the current working directory (basename taken from `--video-input`).

#### Command-Line Arguments

| Argument                       | Default Value                                                                                                           | Required? | Description                                                                                                                                           |
| ------------------------------ | ----------------------------------------------------------------------------------------------------------------------- | --------- | ----------------------------------------------------------------------------------------------------------------------------------------------------- |
| `-h`, `--help`                 | n/a                                                                                                                     | Optional  | Show help and exit.                                                                                                                                   |
| `--ssl-mode`                   | `DISABLED`                                                                                                              | Optional  | SSL mode: `DISABLED`, `MTLS`, or `TLS`.                                                                                                               |
| `--ssl-key`                    | `../ssl_key/ssl_key_client.pem`                                                                                         | Optional  | Path to TLS private key. Required for `MTLS`.                                                                                                         |
| `--ssl-cert`                   | `../ssl_key/ssl_cert_client.pem`                                                                                        | Optional  | Path to TLS certificate chain. Required for `MTLS`.                                                                                                   |
| `--ssl-root-cert`              | `../ssl_key/ssl_ca_cert.pem`                                                                                            | Optional  | Path to root CA. Required for `MTLS` or `TLS`.                                                                                                        |
| `--target`                     | `127.0.0.1:8001`                                                                                                        | Optional  | `host:port` of the gRPC service. For NVIDIA Cloud Functions (NVCF), use `grpc.nvcf.nvidia.com:443` with `--preview-mode` or TLS (see below).          |
| `--preview-mode`               | `False`                                                                                                                 | Optional  | Send request to NVCF preview server. Requires `--api-key` and `--function-id`.                                                                        |
| `--api-key`                    | None                                                                                                                    | Optional  | NGC API key for authentication. Required when `--preview-mode` is set.                                                                                |
| `--function-id`                | None                                                                                                                    | Optional  | NVCF function ID for the service. Required when `--preview-mode` is set.                                                                              |
| `--video-input`                | First existing of `../assets/sample_video.mp4`, `../assets/test/relighting_video.mp4`, else `./assets/sample_video.mp4` | Optional  | Path to input MP4.                                                                                                                                    |
| `--output`                     | None (derived name)                                                                                                     | Optional  | Output MP4 path. If omitted: `<video_input_stem>-relighting_output.mp4`.                                                                              |
| `--video-bitrate`, `--bitrate` | `10000000`                                                                                                              | Optional  | Output bitrate in **bits per second**. `0` lets the encoder use automatic bitrate selection in the lossy path.                                        |
| `--idr-interval`               | `8`                                                                                                                     | Optional  | IDR interval in frames for lossy encoding.                                                                                                            |
| `--lossless`                   | `False`                                                                                                                 | Optional  | Enable lossless video encoding (overrides lossy bitrate / IDR for the `VideoEncoding` message).                                                       |
| `--custom-encoding-params`     | None                                                                                                                    | Optional  | Custom encoder settings as a JSON object (mapped into `VideoEncoding.custom_encoding`).                                                               |
| `--hdr`                        | None                                                                                                                    | Optional  | Path to a custom Radiance `.hdr` environment map (sent as inline HDRI; overrides preset).                                                             |
| `--hdri-id`                    | `0`                                                                                                                     | Optional  | Built-in preset when no `--hdr`: `0` Lounge, `1` Cobblestone Street Night, `2` Glasshouse Interior, `3` Little Paris Eiffel Tower, `4` Wooden Studio. |
| `--pan`                        | `-90`                                                                                                                   | Optional  | Pan angle in degrees.                                                                                                                                 |
| `--vertical-fov`, `--vfov`     | `60`                                                                                                                    | Optional  | Vertical field of view in degrees.                                                                                                                    |
| `--autorotate`                 | `False`                                                                                                                 | Optional  | Rotate the HDR environment over time.                                                                                                                 |
| `--rotation-rate`              | `20`                                                                                                                    | Optional  | Autorotate speed in degrees per second.                                                                                                               |
| `--background-source`          | `0`                                                                                                                     | Optional  | `0` = source video background, `1` = custom image (`--background-image`), `2` = HDR projection. Works with `--blur`.                                  |
| `--background-image`           | None                                                                                                                    | Optional  | Custom background image path (PNG, JPEG, or HDR) when using source `1`.                                                                               |
| `--background-image-type`      | None                                                                                                                    | Optional  | Hint when source is `1`: `0` auto, `1` HDRI, `2` standard (PNG/JPEG).                                                                                 |
| `--background-color`           | None                                                                                                                    | Optional  | Solid background color as hex integer, e.g. `0x808080`.                                                                                               |
| `--foreground-gain`            | `1.0`                                                                                                                   | Optional  | Foreground relighting strength (0.0–2.0).                                                                                                             |
| `--background-gain`            | `1.0`                                                                                                                   | Optional  | Background relighting strength (0.0–2.0).                                                                                                             |
| `--blur`                       | `0.0`                                                                                                                   | Optional  | Background blur strength (0.0–1.0).                                                                                                                   |
| `--specular`                   | `0.0`                                                                                                                   | Optional  | Specular highlight intensity (0.0–2.0).                                                                                                               |

#### Examples

- Show all options:

```bash
python3 relighting.py -h
```

- Local server, defaults for video path and encoding:

```bash
python3 relighting.py --target 127.0.0.1:8001
```

- Custom HDRI file and preset-style pan / FOV:

```bash
python3 relighting.py --target 127.0.0.1:8001 --hdr /path/to/scene.hdr --pan 0 --vfov 55 --output relit_hdr.mp4
```

- HDR projection background with blur:

```bash
python3 relighting.py --target 127.0.0.1:8001 --background-source 2 --blur 0.5 --output relit_bg_hdr.mp4
```

- Lossless output:

```bash
python3 relighting.py --target 127.0.0.1:8001 --lossless --output relit_lossless.mp4
```

- TLS to NVCF (use your CA bundle as required by your environment):

```bash
python3 relighting.py \
  --target grpc.nvcf.nvidia.com:443 \
  --ssl-mode TLS \
  --ssl-root-cert /path/to/ca-bundle.pem \
  --video-input ../assets/sample_video.mp4 \
  --output out.mp4
```

- mTLS (client certificate authentication):

```bash
python3 relighting.py --target 127.0.0.1:8001 \
  --ssl-mode MTLS \
  --ssl-key ../ssl_key/ssl_key_client.pem \
  --ssl-cert ../ssl_key/ssl_cert_client.pem \
  --ssl-root-cert ../ssl_key/ssl_ca_cert.pem
```

### 6. Important Usage Notes

#### NVIDIA Cloud Functions (NVCF)

The simplest way to reach an NVCF endpoint is **preview mode** — pass `--preview-mode` with `--api-key` and `--function-id`. The client handles TLS and attaches authorization metadata automatically:

```bash
python3 relighting.py --preview-mode \
  --target grpc.nvcf.nvidia.com:443 \
  --function-id <FUNCTION_ID> \
  --api-key $NGC_API_KEY \
  --video-input ../assets/sample_video.mp4 \
  --output out.mp4
```

Alternatively, for managed deployments that require custom certificates, point `--target` at `grpc.nvcf.nvidia.com:443`, enable `--ssl-mode TLS` (or `MTLS` if your deployment requires client certificates), and supply `--ssl-root-cert` (and key/cert for mTLS) as required by your organization. See the [NVIDIA NIM documentation](https://docs.nvidia.com/nim/maxine/relighting/latest/index.html) for details.

#### Supported Formats

| Format type          | Supported formats | Notes                                                                              |
| -------------------- | ----------------- | ---------------------------------------------------------------------------------- |
| **Video input**      | MP4 (H.264)       | The client validates `.mp4` extension; use CFR inputs for predictable results.     |
| **Custom HDRI**      | Radiance `.hdr`   | Loaded and streamed as `IMAGE_TYPE_HDRI`.                                          |
| **Background image** | HDR, PNG, JPEG    | Used when `--background-source` is `1`.                                            |
| **Video output**     | MP4               | Encoding follows `VideoEncoding`: lossless, lossy (bitrate + IDR), or custom JSON. |

#### Input Modes (Server-Side)

The NIM chooses **transactional** vs **streaming** processing from the input MP4 layout (for example, streamable files with `moov` early enable incremental processing). You do not set a separate client flag for this; use streamable MP4s when you want lower latency on large files. See [Input modes](https://docs.nvidia.com/nim/maxine/relighting/latest/overview.html#input-modes) in the overview and [Basic Inference](https://docs.nvidia.com/nim/maxine/relighting/latest/basic-inference.html#input-modes) for details.

#### HDR Presets

When you do not pass `--hdr`, `--hdri-id` selects a packaged environment map:

| ID  | Preset                    |
| --- | ------------------------- |
| 0   | Lounge                    |
| 1   | Cobblestone Street Night  |
| 2   | Glasshouse Interior       |
| 3   | Little Paris Eiffel Tower |
| 4   | Wooden Studio             |

#### Background Source and Blur

`--background-source` selects how the background is composited (`0` source video, `1` custom image, `2` HDR projection). `--blur` applies background blur in combination with these modes per server behavior.

#### Custom Encoding Parameters

`--custom-encoding-params` accepts JSON for advanced encoder tuning (passed through to `VideoEncoding`). Incorrect values can cause encoding failures; align with the encoder capabilities described in the NIM and GStreamer/NVENC documentation linked from the product docs.

#### Jupyter Notebook

For an interactive walkthrough of options, use [`notebook/relighting_notebook.ipynb`](notebook/relighting_notebook.ipynb) in VS Code or any Jupyter environment.

---

For more information, see the [NVIDIA Relighting NIM](https://docs.nvidia.com/nim/maxine/relighting/latest/index.html) documentation.
