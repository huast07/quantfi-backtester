# QuantiFi Backtester

Backtest QuantiFi competition strategies on synthetic **day 1** markets before day 1 exists.

**Live site:** [https://quantfi-backtester.vercel.app/]

Upload one or more `trader.py` files, and each one runs through the unmodified [`prosperity3bt`](https://pypi.org/project/prosperity3bt/) 0.12.0 engine on a catalogue of 42 synthetic day-1 markets.
Each market is a named **case**: a regular day, a volatility crush, a TELLURIUM storm, a black swan crash, and so on.
The results show, for each strategy, the cases it handles well, the cases it handles badly, and why, from its per-product PnL.

Everything runs in your browser (Python via Pyodide in web workers).
Your files and results never leave your machine.

## Why synthetic days

The competition scores strategies on several day-1 datasets that do not exist yet.
Each is generated differently but follows the same underlying patterns, and the other traders do not react to our orders.
So the honest question is not "how much would this make on day 1" but "on which kinds of day does this strategy make or lose money".

We do not know the true price processes or how many bots trade.
Everything below is inferred from the real days -2, -1 and 0 and from the two EDA reports (`Prices_Report.pdf`, `Trades_Report.pdf`).
The generator encodes those inferences, and the case catalogue then deliberately varies them.

## Assumed trader behaviours

The Trades report infers four kinds of participant, and the generator implements each one as its own layer.
These are assumptions fitted to three days of data, not known facts.
Every parameter is fitted from the CSVs by `quantgen calibrate`, with nothing tuned by hand.

| Participant | Assumed behaviour | Calibrated from the real days |
|---|---|---|
| **Market-maker bot** | Quotes a 3-level book around each product's hidden fair value, regenerated every tick. It does not hold inventory or react to us. | Spread sets per product (for example 3 for AMETHYST, 14 values for TELLURIUM), level volumes (5-30, LYCHEE 10-40, TELLURIUM 2-24), L2 missing about 9% of the time. On TELLURIUM it widens both sides and thins the chased side for about 400 ticks after a jump. |
| **Noise takers** (15 non-voucher products) | Poisson arrivals that hit the touch with a random side and a size uniform on 1..N (N = 3, 4 or 6). TOFFEE_CAKE arrivals cluster. | Arrival rate and size cap per product; over-dispersion for TOFFEE_CAKE. |
| **Voucher IV-rule takers** (about 90% of voucher flow) | Buy strikes priced below the smile and sell strikes priced above it, 93-100% consistently. They wait for large mispricings: arrival rates scale with \|mispricing\|^s, so they trade at about 1.4x the average mispricing, as real ones do. | Rule consistency and selectivity exponent s (about 0.4-1.0) per strike. |
| **TELLURIUM chasers** | A burst of buying or selling in the jump's direction after each jump, sweeping L2 and deeper on 23-34% of prints. Unexpected chase volume moves the quotes about 0.5 per lot from the next tick (Kyle 1985; Bouchaud et al. 2004 on propagators). | Burst size and timing, sweep share, impact per lot from a joint least-squares fit. |

What the reports found **absent**, and the generator therefore leaves out: cross-product traders, and a bot that buys the lows.
Other traders never respond to our orders, which is exactly the model `prosperity3bt` implements: the book and the trade tape are fixed inputs, and our orders fill against them.

### Assumed price processes

Each product has a hidden fair value, which the market maker quotes around.
Day 1 opens where day 0 closed.

| Product(s) | Assumed process |
|---|---|
| AMETHYST | Constant 10,000. |
| GOLDEN_PEARLS | Plateaus with occasional downward steps of about 100 (0, 1 and 2 steps on days -2, -1, 0), absorbed by WHITE (about 45%) and BLACK (about 46%) so the pearl sum holds. |
| PINK_PEARLS | Plateaus plus jumps that restore the five-pearl sum to 50,000 (jump probability 5-11% when the sum is more than 10 away, 0.4% otherwise). |
| WHITE / BLACK / BLUE_PEARLS | Correlated random walks (WHITE-BLACK -0.60, BLACK-BLUE -0.40); BLUE adds drift and short-horizon momentum. |
| PAPER_LANTERNS | Slowly drifting level plus independent quote noise (lag-1 autocorrelation -0.50). |
| TOFFEE_CAKE | Mean reversion (Ornstein-Uhlenbeck) around about 5,000. |
| JELLY, PEANUT_BUTTER, LYCHEE, DRAGONFRUIT, GRANADILLA, MANGOSTEEN | Random walks with a per-day drift drawn from the observed range. |
| FRUIT_BASKET | 2 DRAGONFRUIT + 3 GRANADILLA + 1 MANGOSTEEN, plus a random-walk premium and its own noise. |
| TELLURIUM | Jump-diffusion with 8-13 jumps a day (mean size about 170, max 300). After a jump, price drifts about 24 further its way over 200 ticks and fades by 600; jumps larger than typical give back about 1.2x their excess. |
| VOUCHER_6800 to VOUCHER_8100 | Black-Scholes on LYCHEE's fair value with a quadratic smile, implied volatility 20-30% above realised, a shared IV factor, and a persistent per-strike mispricing (AR(1), phi about 0.993). Five days to expiry at the day-1 open. |

### How realistic the synthetic days are

`quantgen fidelity` regenerates the EDA's headline statistics on the observed-tier cases and checks them against the real days: 294 checks covering tick volatility, autocorrelation, spreads, prints per day, trade sizes, pearl-sum behaviour, the IV smile, and taker markouts at 1, 10 and 50 ticks.
It passes on every seed set tried.
As a strategy-level check, simple TELLURIUM and AMETHYST strategies earn on the real days amounts that fall inside the 10-90% band of their results on 12 synthetic regular days.

## Test cases from the literature

Every case starts from the calibrated regular day and changes one thing, using one of 25 typed modifiers (shocks, regime switches, parameter overrides, flow changes).
Cases are YAML files in `quantgen/cases/catalog/`, validated strictly on load.
They come in three tiers, weighted by default 60% observed, 30% plausible, 10% stress (adjustable on the results page).
Each tier's weight is split equally among its cases, so adding a case never changes a tier's total.

### Observed tier (5 cases): what the real days look like

| Case | What changes | Source |
|---|---|---|
| Regular day | Every product follows its calibrated behaviour. | EDA reports |
| Regular day, varied | Volatility, flow and TELLURIUM jump rate vary across their observed day-to-day range. | EDA reports (day-to-day variation) |
| Quiet day | Volatility and taker flow at the low end of the observed range. | EDA reports (day-level ranges) |
| Busy day | Volatility and taker flow at the high end of the observed range. | EDA reports (day-level ranges) |
| Trends continue | The multi-day drifts persist: DRAGONFRUIT up, PAPER_LANTERNS down, GOLDEN_PEARLS stepping down. | Prices report, days -2 to 0 |

### Plausible tier (28 cases): what the data leaves room for

**Price dynamics**

| Case | What changes | Literature |
|---|---|---|
| Fat tails | Price moves are Student-t (3.5 degrees of freedom): rare large moves, same variance. | Mandelbrot (1963); Cont (2001) |
| Volatility clustering | Calm and turbulent stretches alternate (GARCH), with the same average volatility. | Engle (1982); Bollerslev (1986); Cont (2001) |
| Volatility regime switch | A hidden Markov chain switches the market between calm and 3x turbulent volatility. | Hamilton (1989) |
| Trend regime flip | Random-walk products trend one way, then reverse at a random time mid-day. | Hamilton (1989) |
| Intraday seasonality | U-shaped day: more volatility and flow near the open and close, quieter mid-day. | Admati & Pfleiderer (1988); Andersen & Bollerslev (1997) |
| Mean reversion decays | TOFFEE_CAKE reverts 3-5x more slowly and its anchor drifts. | Avellaneda & Lee (2010) |
| Momentum crash | BLUE_PEARLS' uptrend reverses sharply instead of fading. | Daniel & Moskowitz (2016) |
| TELLURIUM jumps stick | Jumps are simply permanent, with no follow-through and no give-back. | De Bondt & Thaler (1985); Jegadeesh & Titman (1993) |
| TELLURIUM whipsaw | Jumps go both ways within the day instead of mostly one way. | Merton (1976) |

**Cross-product structure**

| Case | What changes | Literature |
|---|---|---|
| Basket dislocation | The FRUIT_BASKET premium trends far from normal for a few thousand ticks, then snaps back. | Gatev, Goetzmann & Rouwenhorst (2006); Mitchell & Pulvino (2001) |
| Correlation breakdown | The WHITE/BLACK/BLUE pearl correlations flip sign. | Longin & Solnik (2001); Khandani & Lo (2007) |
| Pearl plug weakens | PINK_PEARLS restores the pearl sum less often and only partly, so deviations last longer. | Shleifer & Vishny (1997) |
| Pearl total shifts | The five-pearl total moves to a new constant (50,000 +/- 100-200) part-way through the day. | Perron (1989) |
| GOLDEN_PEARLS keeps falling | Steps down two or three times. | Prices report, open question |
| GOLDEN_PEARLS holds | Stays on one plateau all day. | Prices report, open question |
| GOLDEN_PEARLS reverses | Steps up instead of down. | Prices report, open question |

**Options (LYCHEE vouchers)**

| Case | What changes | Literature |
|---|---|---|
| Volatility crush | Voucher implied volatility falls to LYCHEE's realised volatility. | Carr & Wu (2009) |
| Volatility spike and skew | Implied volatility rises 30-60% and the smile's skew steepens. | Gatheral (2006); Derman (1999) |
| Smile flattens | The smile's curvature falls by half or more, so wing vouchers cheapen. | Gatheral (2006) |
| Sticky-strike smile | The smile stays fixed in strike as LYCHEE moves. | Derman (1999) |
| LYCHEE trends | LYCHEE trends 250-450 in one direction all day, so voucher deltas swing. | Hull (2018), ch. 19 |

**Microstructure and liquidity**

| Case | What changes | Literature |
|---|---|---|
| Toxic flow | 30-50% of takers know where the price is going over the next 50 ticks. | Kyle (1985); Glosten & Milgrom (1985); Easley, López de Prado & O'Hara (2012) |
| TELLURIUM informed flow | Jump chasers start 100 ticks before each jump instead of after it. | Easley, Kiefer, O'Hara & Paperman (1996); Trades report, open question |
| Heavy flow | Taker arrival rates double on every product. | Glosten & Milgrom (1985) |
| Liquidity drought | Book volumes and taker arrivals halve on every product. | Brunnermeier & Pedersen (2009) |
| Wide spreads | The market maker quotes one or two ticks wider per side on every product. | Ho & Stoll (1981) |
| One-sided flow | Noise takers lean 70-80% to one side on five products. | Cont, Kukanov & Stoikov (2014) |
| Clustered arrivals | Takers arrive in bursts on every product, not just TOFFEE_CAKE and TELLURIUM. | Bacry, Mastromatteo & Muzy (2015) |

### Stress tier (9 cases): rare, extreme events

| Case | What changes | Literature |
|---|---|---|
| Black swan crash | A market-wide crash of 5-15% in seconds, with spreads blowing out and IV spiking, then a partial recovery. | Taleb (2007); Longin & Solnik (2001); Roll (1988) |
| Black swan squeeze | The mirror image: a market-wide spike up of 5-15%. | Taleb (2007) |
| Flash crash | One random product collapses 4-10% and fully recovers within about 100 ticks while books thin. | Kirilenko, Kyle, Samadi & Tuzun (2017); CFTC-SEC (2010) |
| Liquidity spiral | A slow market-wide decline during which the market maker withdraws. | Brunnermeier & Pedersen (2009); Kirilenko et al. (2017) |
| Quant quake | Every relative-value relationship breaks at once. | Khandani & Lo (2007) |
| TELLURIUM storm | TELLURIUM jumps 2.5x as often and twice as far as ever observed. | Merton (1976); Bates (1996) |
| Volatility explosion | Volatility triples on every diffusive product for 500-2,000 ticks. | Schwert (1989) |
| Opening gap | Day 1 opens 2-6% away from the day-0 close on every diffusive product. | Lou, Polk & Skouras (2019) |
| AMETHYST anchor break | AMETHYST's 10,000 anchor moves permanently by 15-40. | Perron (1989) |

Each case runs on several seeds (independent random days), because one synthetic path can flatter or punish a strategy by luck.
Every strategy sees exactly the same days, so differences between strategies are paired and far less noisy.

## Scoring and verdicts

- **Suites:**
  - Quick: 8 representative cases x 1 seed, for iterating.
    Its verdicts are marked indicative.
  - Standard: all 42 cases x 2 seeds, the default.
  - Full: all 42 cases x 5 seeds, for use before submitting.
  - Custom: any set of cases and seed count.
- **Per case:** mean and worst PnL across seeds, PnL per product, drawdown, limit breaches and crashes.
- **Overall:** the tier-weighted mean PnL plus the worst case, so one number never hides a blow-up.
- **Verdicts:** every case is rated Strong, Neutral or Weak for each strategy, with a one-line reason.
  - Absolute part: a case where the strategy loses money, or is more than one standard deviation below its own average, is Weak; more than one above is Strong.
  - Relative part, with several uploads: its edge over the other uploads in that case compared with its usual edge.
  - The reason line comes from the per-product breakdown, for example "-28,928 mean; of which TELLURIUM -28,928; loses money".
- **Reference strategy:** a built-in market maker on the 15 delta-one products other than TELLURIUM, roughly break-even on the real days.
  It is a gate, not a score: a case cannot be Strong for a strategy that trails the reference on every seed.

## Using the website

1. Drop one or more `trader.py` files (up to 6) on the Backtest page.
   Each must define a `Trader` class as submitted to the competition; `from datamodel import ...` works as usual, and numpy is available.
2. Pick a suite and the passive-fill rule (the wiki's rule is "all").
3. Run.
   The first run downloads the Python runtime (about 40 MB); later runs start at once.
   Two strategies on the Quick suite take about 30 seconds.
4. Read the results:
   - profile cards listing the cases each strategy performs well and poorly in;
   - a strategy-by-case table;
   - head to head between two uploads, per seed;
   - a per-product breakdown;
   - a replay of any case and seed, with price and fills, position, PnL and trader logs.

From the replay you can download the full `prosperity3bt` log (for the open-source Prosperity visualizer), the day's CSVs, or any chart as a PNG.
Runs are saved in your browser under History, with JSON export and import.
The Cases page lists every case with its parameters and literature, and downloads any case's day for any seed as competition-format CSVs.

## Running locally

Requirements: Python 3.12+ with [uv](https://docs.astral.sh/uv/), and Node 20+.

### Command line

```bash
uv sync
uv run quantgen cases                                   # list the 42 cases
uv run quantgen run a.py b.py --suite standard          # compare strategies case by case
uv run quantgen run a.py --cases tellurium-storm black-swan-crash --seeds 5
uv run quantgen run a.py --real                         # replay the real days -2, -1, 0
uv run quantgen gen --case vol-crush --seed 3 --out data  # write a case as competition CSVs
uv run quantgen calibrate                               # refit params/params.json from the real CSVs
uv run quantgen fidelity                                # check synthetic days against the real ones
uv run pytest
```

### Web app

```bash
cd web
npm ci
npm run dev        # http://localhost:3000; builds the Python bundle first (needs uv)
npm test           # unit and component tests
npm run test:parity  # browser (Pyodide) output equals CPython output, byte for byte
npm run build && npm run e2e                                  # Playwright, desktop and phone
E2E_BASE_URL=https://web-khaki-chi-52.vercel.app npm run e2e  # against a deployment
```

### Deploying

The site is a static export, so any static host works.
On Vercel, import this repository and set **Root Directory** to `web`.
`web/vercel.json` installs uv for the Python bundle step and serves `web/out` as plain files.

## Repository layout

```
quantgen/            Python package: generator, calibration, cases, scoring, prosperity3bt adapter, CLI
  generator/         fair value processes, market-maker book, takers
  calibration/       fits params.json from the real CSVs; the fidelity gate
  cases/catalog/     the 42 case YAML files
  scoring/           metrics, verdicts, reference strategy
params/params.json   calibrated generator parameters
tests/               Python tests
web/                 Next.js static site; Pyodide workers run quantgen in the browser
QuantFi Price Data/  real days -2, -1, 0 (order books)
QuantFi Trades Data/ real days -2, -1, 0 (trade tape)
```

## Caveats

- The participant model and price processes are inferences from three days.
  If day 1 is generated differently, the observed tier is wrong in ways the other tiers may or may not cover.
- A strategy tuned until it wins every case is probably fitted to this generator.
  Prefer strategies that are rarely Weak over ones that win big on a few cases (Bailey, Borwein, López de Prado & Zhu 2014; López de Prado 2018).
- Synthetic PnL is a comparison tool, not a forecast of competition PnL.

## References

- Admati, A. & Pfleiderer, P. (1988). A theory of intraday patterns. *Review of Financial Studies* 1(1).
- Andersen, T. & Bollerslev, T. (1997). Intraday periodicity and volatility persistence in financial markets. *Journal of Empirical Finance* 4.
- Avellaneda, M. & Lee, J.-H. (2010). Statistical arbitrage in the US equities market. *Quantitative Finance* 10(7).
- Bacry, E., Mastromatteo, I. & Muzy, J.-F. (2015). Hawkes processes in finance. *Market Microstructure and Liquidity* 1(1).
- Bailey, D., Borwein, J., López de Prado, M. & Zhu, Q. (2014). Pseudo-mathematics and financial charlatanism. *Notices of the AMS* 61(5).
- Bates, D. (1996). Jumps and stochastic volatility. *Review of Financial Studies* 9(1).
- Bollerslev, T. (1986). Generalized autoregressive conditional heteroskedasticity. *Journal of Econometrics* 31.
- Bouchaud, J.-P., Gefen, Y., Potters, M. & Wyart, M. (2004). Fluctuations and response in financial markets. *Quantitative Finance* 4(2).
- Brunnermeier, M. & Pedersen, L. (2009). Market liquidity and funding liquidity. *Review of Financial Studies* 22(6).
- Carr, P. & Wu, L. (2009). Variance risk premiums. *Review of Financial Studies* 22(3).
- CFTC-SEC (2010). Findings regarding the market events of May 6, 2010.
- Cont, R. (2001). Empirical properties of asset returns: stylized facts and statistical issues. *Quantitative Finance* 1.
- Cont, R., Kukanov, A. & Stoikov, S. (2014). The price impact of order book events. *Journal of Financial Econometrics* 12(1).
- Daniel, K. & Moskowitz, T. (2016). Momentum crashes. *Journal of Financial Economics* 122(2).
- De Bondt, W. & Thaler, R. (1985). Does the stock market overreact? *Journal of Finance* 40(3).
- Derman, E. (1999). Regimes of volatility. *Risk* 12(4).
- Easley, D., Kiefer, N., O'Hara, M. & Paperman, J. (1996). Liquidity, information, and infrequently traded stocks. *Journal of Finance* 51(4).
- Easley, D., López de Prado, M. & O'Hara, M. (2012). Flow toxicity and liquidity in a high-frequency world. *Review of Financial Studies* 25(5).
- Engle, R. (1982). Autoregressive conditional heteroscedasticity. *Econometrica* 50(4).
- Gatev, E., Goetzmann, W. & Rouwenhorst, K. G. (2006). Pairs trading. *Review of Financial Studies* 19(3).
- Gatheral, J. (2006). *The Volatility Surface*. Wiley.
- Glosten, L. & Milgrom, P. (1985). Bid, ask and transaction prices. *Journal of Financial Economics* 14(1).
- Hamilton, J. (1989). A new approach to the economic analysis of nonstationary time series. *Econometrica* 57(2).
- Ho, T. & Stoll, H. (1981). Optimal dealer pricing. *Journal of Financial Economics* 9(1).
- Hull, J. (2018). *Options, Futures, and Other Derivatives*, 10th ed. Pearson.
- Jegadeesh, N. & Titman, S. (1993). Returns to buying winners and selling losers. *Journal of Finance* 48(1).
- Khandani, A. & Lo, A. (2007). What happened to the quants in August 2007? *Journal of Investment Management* 5(4).
- Kirilenko, A., Kyle, A., Samadi, M. & Tuzun, T. (2017). The Flash Crash. *Journal of Finance* 72(3).
- Kyle, A. (1985). Continuous auctions and insider trading. *Econometrica* 53(6).
- Longin, F. & Solnik, B. (2001). Extreme correlation of international equity markets. *Journal of Finance* 56(2).
- López de Prado, M. (2018). *Advances in Financial Machine Learning*. Wiley.
- Lou, D., Polk, C. & Skouras, S. (2019). A tug of war: overnight versus intraday expected returns. *Journal of Financial Economics* 134(1).
- Mandelbrot, B. (1963). The variation of certain speculative prices. *Journal of Business* 36(4).
- Merton, R. (1976). Option pricing when underlying stock returns are discontinuous. *Journal of Financial Economics* 3.
- Mitchell, M. & Pulvino, T. (2001). Characteristics of risk and return in risk arbitrage. *Journal of Finance* 56(6).
- Perron, P. (1989). The great crash, the oil price shock, and the unit root hypothesis. *Econometrica* 57(6).
- Roll, R. (1988). The international crash of October 1987. *Financial Analysts Journal* 44(5).
- Schwert, G. W. (1989). Why does stock market volatility change over time? *Journal of Finance* 44(5).
- Shleifer, A. & Vishny, R. (1997). The limits of arbitrage. *Journal of Finance* 52(1).
- Taleb, N. N. (2007). *The Black Swan*. Random House.
