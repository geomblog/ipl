# IPL 2026 Playoff Scenarios

A single-page web app that estimates each IPL 2026 team's probability of qualifying for the playoffs (top 4) and the direct top-2 slot, plus a max-flow check for mathematical lock-in / elimination.

Everything lives in two files:

- [`ipl_scenarios.html`](ipl_scenarios.html) — HTML + CSS + vanilla JS. Embeds the latest results in a `<script id="ipl-data">` JSON block, runs the Monte Carlo simulation in the browser, and renders the table.
- [`refresh.py`](refresh.py) — Python 3 stdlib script that scrapes cricbuzz and rewrites the embedded JSON block.

## Quick start

```bash
# 1. Pull the latest results from cricbuzz and rewrite the JSON block in the HTML.
python3 refresh.py

# 2. Open the file in any browser. No server needed.
open ipl_scenarios.html
```

That's it. The page reads the embedded data, runs the simulation, and caches the result in `localStorage`. Reload-after-refresh shows updated numbers; reload-without-refresh is a cache hit.

`refresh.py` prints how many completed matches it found and the delta versus the previous run — so it's easy to tell when new results have landed.

## What the page shows

Per team, sorted by qualify probability:

| Column | Meaning |
|---|---|
| **P / W / L / Pts / NRR** | Current standings (mirrored from cricbuzz) |
| **Top 2** | Probability of finishing 1st or 2nd. A small **Out** badge appears here when a team is mathematically eliminated from top-2 |
| **Qualify** | Probability of finishing top-4. The bar color is on a red→yellow→green scale (red = 0%, yellow = 30%, green = 100%). **Locked** / **Eliminated** badges are driven by a certified max-flow proof, not the Monte Carlo |
| **Trend** | ↑ / ↓ / ↔ comparing this run's qualify% to the previous saved snapshot (threshold 2 percentage points) |

Below the table: collapsible cards for recent results, upcoming fixtures, and a graph of remaining games (one node per team, one edge per remaining match; parallel edges when a pair meets more than once).

## The two simulation modes

Both modes run 50,000 Monte Carlo trials, sorting the final table by (points desc, current NRR desc) and counting how often each team lands in the top 4 / top 2.

### Fair coin

Every remaining match is a 50/50 coin flip. The simplest possible model and the natural baseline. Sum of qualify probabilities across all 10 teams is exactly 4.0; sum of top-2 probabilities is exactly 2.0.

### Recent form

For each remaining match A vs B, the probability that A wins is

```
P(A) = r_A / (r_A + r_B)
```

where `r_T` is team T's Laplace-smoothed win ratio over its last `k` decided games:

```
r_T = (wins + 1) / (games + 2)
```

`k` is a UI control (default 5, clamped to 1–20). The window is a rolling buffer of each team's *decided* games — ties and no-results are excluded. As the simulation steps through the remaining schedule, each simulated outcome is pushed into the buffer, evicting the oldest entry once the window is full. So a hot team gets hotter (in the model) the longer their winning run continues within a trial.

Laplace smoothing handles two edge cases gracefully:

- A team with **no recent decided games** has `r = 1/2` — i.e. a fair coin against any opponent.
- A team with **zero wins** still has `r = 1/(games+2) > 0`, avoiding the divide-by-zero that a raw win ratio would hit when paired against another zero-win team.

Switching modes (or changing `k`) re-runs the sim and caches the result independently per mode/k, so toggling back is instant.

## Calculating team strength

The "strength" of team T at any point in the recent-form simulation is its Laplace-smoothed win ratio `r_T = (wins+1)/(games+2)` over the most recent `k` decided games.

A few properties that make this number well-behaved as a strength estimate:

- **Bounded in (0, 1)** for any input. Never exactly 0 or 1, so head-to-head P(A) = r_A / (r_A + r_B) is always defined.
- **Symmetric prior**. The +1 / +2 is equivalent to a Beta(1,1) (uniform) prior on the team's true win rate, updated by `k` observed games.
- **Recency-weighted, hard cutoff**. Older games drop out of the window entirely once `k` new ones arrive. Shorter `k` makes the model more reactive (form swings move it); longer `k` makes it more stable (regression to the team's whole-season record).
- **Updates inside a trial**. During a single Monte Carlo trial the simulated outcomes feed back into each team's window. So a simulated 3-game losing run actually lowers that team's strength for their next match within the same trial — modeling momentum effects without any extra parameters.

The fair-coin mode is the degenerate case `r_A = r_B = 1/2` for every team and every match.

## Mathematical lock / elimination (max-flow)

The **Locked** and **Eliminated** badges aren't probability-derived — they're a certified yes/no from a small max-flow check, the classical "baseball elimination" reduction generalized to top-`N`.

For each team z and each candidate set `R` of `N-1` opponents allowed to outrank z:

1. Build a flow network: source → game node (cap 2) → both teams playing the game, and team → sink (cap = points slack for that team, or ∞ for R-teams).
2. If max flow saturates the source, the candidate `R` is feasible and z is not eliminated. Try the next `R`.
3. If every `R` fails, z is mathematically eliminated.

The symmetric test (assume z loses all remaining; check whether 4 opponents can still pass z) decides lock-in. With 10 teams and a handful of remaining games the whole sweep runs in single-digit milliseconds.

## Data and caching

The scraper extracts two cricbuzz pages — matches and points table — by walking `self.__next_f.push([1,"..."])` streaming payloads and parsing the embedded JSON blobs. It writes the result back into the `<script id="ipl-data">` tag of the HTML. Stdlib only; no `pip install` needed. Tested against Python 3.9.

Three `localStorage` keys are used by the page:

- `ipl2026_scenarios_v3` — most-recent sim result (keyed by completed-results hash + mode + k).
- `ipl2026_trend_v1` — previous qualify% per team per mode, for the trend arrows.

Clear them in DevTools if the page ever gets into a weird state.

## Caveats

- **No-result / tied games** are folded into the points table by cricbuzz and excluded from the recent-form window. They contribute to the completed-results hash so cached probabilities invalidate correctly.
- **NRR is frozen** at its current value and used only as a tiebreaker. The simulator does not try to predict run rates.
- **Playoff fixtures** (Qualifier 1, Eliminator, Qualifier 2, Final) are excluded from the simulation and from the games graph — those slots don't exist until the league stage finishes.
- **All times are IST** on the page (cricbuzz's source timezone). The browser locale is used for the "fetched at" string.
