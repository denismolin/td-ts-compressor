# Manim Algorithm Animation

This folder contains a Manim scene that explains how `ts_compress_to` selects
important points in a time series.

Render the README video:

```powershell
.\.venv\Scripts\python.exe -m manim -ql --media_dir docs/assets/manim_render docs/manim/ts_compress_algorithm.py TsCompressAlgorithm
```

Copy the final render to the stable README asset path:

```powershell
Copy-Item docs/assets/manim_render/videos/ts_compress_algorithm/480p15/TsCompressAlgorithm.mp4 docs/assets/ts_compress_algorithm.mp4 -Force
```

For a slower 1080p export, use `-qh` instead of `-ql` and copy from the `1080p60` folder.

The animation demonstrates:

- partition-local compression with endpoints retained
- tolerance scaling with `tol_x` and `tol_y`
- global farthest-point selection
- perpendicular residual distance to the active compressed segment
- `distance_max` as a stretched-space tolerance ball and segment tube
- returned metadata columns: `compression_importance` and `compression_distance`
- plateau detection from low-slope compressed segments

Manim writes generated videos and frames under `docs/assets/manim_render/`.
That render cache is ignored by git; only `docs/assets/ts_compress_algorithm.mp4`
is intended for the README.

