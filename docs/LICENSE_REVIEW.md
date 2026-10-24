# License and data review

Code/documentation: MIT. Original generated fixture frames and clips: CC0-1.0
under FIXTURE_LICENSE.md. DATA_CARD.md now summarizes the existing scope.
`fixtures.py` renders geometry, texture and controlled motion locally. Sampled
video first frames were those program materials, not user avatars or personal
footage. No pretrained model is required by these demonstration clips.

Existing `docs/upstream_sources.json` separates conceptual upstream references
from original implementation. It also records that the installed FFmpeg binary
had GPL-2.0-or-later output, rather than treating every FFmpeg build as LGPL. No
FFmpeg executable was identified in this repository; this review did not alter
that prior runtime evidence or recertify every dependency/build.

Machine-specific absolute paths were observed in `verification_v2.json` and an
ignored run record. The publishing role was informed; generated execution evidence
was not modified by this reviewer.

## Inspection scope

The 2026-10-23 review inspected the repository file tree, software LICENSE,
example manifests/provenance, relevant fixture or adapter code, source links and
license declarations. It searched common pretrained-weight extensions
(`.safetensors`, `.ckpt`, `.pth`, `.pt`, `.bin`, `.onnx`, `.h5`, `.gguf`), files over
20 MB, symlinks, obvious private-key/token filenames and text patterns, personal
home paths and email-like strings. No model-weight files, large unexplained
single files or symlinks were found in the inspected five-repository snapshot.
Installed environments and the external model cache are outside these repositories
and outside the publication target.

This is a snapshot review during concurrent work. It does not establish the
contents of a later Git commit/archive or prove that every upstream author owns
every right. The public file list must still be checked after packaging. No
source-code similarity audit or copyright clearance of training data was performed.
