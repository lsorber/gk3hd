# SeedVR2 third-party notice

The model-definition files under this directory are derived from:

- ByteDance Seed, [SeedVR](https://github.com/ByteDance-Seed/SeedVR), copyright
  2025 ByteDance Ltd. and/or its affiliates.
- numz, [ComfyUI-SeedVR2_VideoUpscaler](https://github.com/numz/ComfyUI-SeedVR2_VideoUpscaler),
  release 2.5.24, commit `4490bd1f482e026674543386bb2a4d176da245b9`.
- Hugging Face Diffusers, where noted in individual VAE source headers,
  copyright 2023 Hugging Face Team.

Those sources are licensed under Apache License 2.0; the complete text is in
`LICENSE` beside this notice.

Changes made for gk3hd: retained the 3B DiT and VAE definitions, removed
training, distributed execution, ComfyUI integration, alternate attention,
quantization, and process-monitoring paths, and added small single-device SDPA
and OOM-retry compatibility modules. LAB correction is a focused adaptation of
numz's recommended implementation.
