# Third-party licences

Clip Anything is MIT licensed (see `LICENSE`). It bundles no third-party code. The packages
below are pulled in from PyPI when you install it; each keeps its own licence. The table was
produced with `pip-licenses` on a fresh install of the 0.1.0 wheel with the `captions` extra
on 2026-11-12. Versions move with your resolver; the licences do not change often.

All of them are permissive. The only weak-copyleft components are the LGPL FFmpeg build that
ships inside the `opencv-python-headless` and `av` wheels and the MPL-2.0 part of `tqdm`;
they are used unmodified as separate libraries, which their licences allow.

## Always installed

| Package | Licence | Project |
|---|---|---|
| numpy | BSD-3-Clause (plus 0BSD, MIT, Zlib, CC0 pieces) | https://numpy.org |
| scipy | BSD-3-Clause | https://scipy.org |
| opencv-python-headless | Apache-2.0; the wheel bundles OpenCV (Apache-2.0) and an FFmpeg build (LGPL-2.1+) | https://github.com/opencv/opencv-python |
| rich | MIT | https://github.com/Textualize/rich |
| markdown-it-py, mdurl | MIT | https://github.com/executablebooks |
| Pygments | BSD-2-Clause | https://pygments.org |
| typer | MIT | https://github.com/fastapi/typer |
| click | BSD-3-Clause | https://github.com/pallets/click |
| shellingham | ISC | https://github.com/sarugaku/shellingham |
| typing_extensions | PSF-2.0 | https://github.com/python/typing_extensions |
| annotated-doc | MIT | https://github.com/fastapi/annotated-doc |

## Optional extra `captions`

| Package | Licence | Project |
|---|---|---|
| faster-whisper | MIT | https://github.com/SYSTRAN/faster-whisper |
| ctranslate2 | MIT | https://github.com/OpenNMT/CTranslate2 |
| onnxruntime | MIT | https://onnxruntime.ai |
| av (PyAV) | BSD-3-Clause; the wheel bundles an FFmpeg build (LGPL-2.1+) | https://pyav.basswood.io |
| huggingface_hub, hf-xet, tokenizers | Apache-2.0 | https://github.com/huggingface |
| tqdm | MPL-2.0 AND MIT | https://tqdm.github.io |
| filelock | MIT | https://github.com/tox-dev/filelock |
| fsspec | BSD-3-Clause | https://github.com/fsspec/filesystem_spec |
| PyYAML | MIT | https://pyyaml.org |
| packaging | Apache-2.0 OR BSD-2-Clause | https://github.com/pypa/packaging |
| protobuf | BSD-3-Clause | https://protobuf.dev |
| flatbuffers | Apache-2.0 | https://flatbuffers.dev |
| httpx2, httpcore2, anyio, h11, idna, truststore, pydantic, pydantic_core, annotated-types, typing-inspection | MIT / BSD-3-Clause | transitive, via huggingface_hub |
| Whisper model weights (`Systran/faster-whisper-*`) | MIT (OpenAI Whisper) | downloaded once from Hugging Face, only after you agree (`--yes`) |

## Desktop app builds only (GitHub Releases)

| Component | Licence | Build |
|---|---|---|
| ffmpeg / ffprobe, Windows | GPL-3.0 (`--enable-gpl --enable-version3`; libx264, libx265) | BtbN FFmpeg-Builds `autobuild-2026-11-12-15-40`, `ffmpeg-n9.0.2-…-win64-gpl-shared-9.0.zip`, https://github.com/BtbN/FFmpeg-Builds |
| ffmpeg / ffprobe, macOS | GPL-3.0 (`--enable-gpl --enable-version3`; libx264, libx265) | eugeneware/ffmpeg-static `b6.1.1` (ffmpeg 6.0): arm64 from https://osxexperts.net, x86_64 from https://evermeet.cx/ffmpeg/ |
| Python runtime, pywebview, PyInstaller bootloader | PSF-2.0, BSD-3-Clause, GPL-2.0-with-bootloader-exception | bundled by PyInstaller |

ffmpeg runs as a separate process and is not linked into Clip Anything. The GPL and LGPL
texts and each build's own licence file are in the `ffmpeg` folder of the app
(`packaging/licences` in this repository); `ffmpeg -version` prints the exact configuration.
Pinned URLs and SHA-256 sums: `packaging/fetch_ffmpeg.py`.

## External programs (never bundled by the PyPI package, found on your PATH)

| Program | Licence | Project |
|---|---|---|
| FFmpeg / ffprobe | LGPL-2.1+ or GPL-2.0+ depending on how your copy was built | https://ffmpeg.org |
| Ollama (optional, `--ai`, `--vision`) | MIT; the vision models you pull carry their own licences (Qwen: Apache-2.0; Gemma: Gemma Terms of Use; others vary) | https://ollama.com |

## Optional cloud services (only with your own key)

| Service | Terms | Used by |
|---|---|---|
| OpenAI API | https://openai.com/policies | `--ai-provider openai` / `OPENAI_API_KEY` |
| Anthropic API | https://www.anthropic.com/legal | `--ai-provider anthropic` / `ANTHROPIC_API_KEY` |
| Hugging Face Hub | https://huggingface.co/terms-of-service | one-time Whisper model download |

What each receives is in `docs/privacy.md`.

To regenerate: `uv venv /tmp/v && uv pip install -p /tmp/v/bin/python 'dist/*.whl[captions]' pip-licenses && /tmp/v/bin/pip-licenses --from=mixed --with-urls --format=markdown`.
