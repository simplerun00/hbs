# Terrain Analyzer Notes

## Runtime dependencies

Install the Python packages below before running `terrain_analyzer.py`.

- `numpy`
- `pyshp`
- `scipy`
- `matplotlib`
- `ezdxf`
- `pyproj`

## Configurable paths

The script now supports overriding its default working directory with the `TERRAIN_ANALYZER_HOME` environment variable.

- Default app home: `%USERPROFILE%\\Documents\\terrain-analyzer`
- Default output folder: `%USERPROFILE%\\Documents\\terrain-analyzer\\분석결과`
- Default crash log: `%USERPROFILE%\\Documents\\terrain-analyzer\\분석기_오류로그.txt`

This keeps the code portable across PCs without relying on a fixed drive path.
