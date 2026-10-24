# Attribution

OffBall's football world is synthetic. Two open datasets were used to calibrate it: the generator's targets are fitted from them, and the quality gates compare generated matches against those fits (PRD 12.2). No rows from either dataset are in this repository, the app or the demo. The repository keeps only fitted numbers (`calibration/targets.json`, `calibration/params.json`), reports (`calibration/reports/`) and salted hashes of real names for the blocklist (`calibration/blocklist.sha256.txt`). The raw files are downloaded into `calibration/raw/`, which git ignores.

## Calibration data

### Wyscout soccer match event data set

Used for event rates per match (passes, shots, possessions, fouls, set pieces, conversion), pass lengths and shot distances, fitted from the 380 matches of the English first division, 2017/18.

Pappalardo, L., Cintia, P., Rossi, A., Massucco, E., Ferragina, P., Pedreschi, D. and Giannotti, F. (2019). A public data set of spatio-temporal match events in soccer competitions. *Scientific Data* 6, 236. https://doi.org/10.1038/s41597-019-0247-7

Data: https://doi.org/10.6084/m9.figshare.c.4415000.v2, downloaded from the figshare original. Licensed under [Creative Commons Attribution 4.0 International](https://creativecommons.org/licenses/by/4.0/). OffBall uses fitted statistics derived from the data; the data itself is not redistributed.

### SkillCorner open data

Used for physical output (distance, speed bands, peak speed, time with the ball in play), off-ball run rates by type, and the names behind the blocklist, fitted from the A-League 2024/25 season aggregates.

Data courtesy of [SkillCorner](https://skillcorner.com), from https://github.com/SkillCorner/opendata, under the MIT License:

> Copyright (c) 2020 SkillCorner. https://skillcorner.com
>
> Permission is hereby granted, free of charge, to any person obtaining a copy of this software and associated documentation files (the "Software"), to deal in the Software without restriction, including without limitation the rights to use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of the Software, and to permit persons to whom the Software is furnished to do so, subject to the following conditions:
>
> The above copyright notice and this permission notice shall be included in all copies or substantial portions of the Software.
>
> THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.

### Not used

StatsBomb open data is excluded, because its user agreement may not allow the commercial licence the hackathon rules require (PRD 12.2). Metrica Sports sample data, if used for laptop sanity checks, stays local and nothing derived from it is shipped.
