"""Elder triple-screen paper-portfolio strategy.

Runs the locked config validated in candidate 16 (slow_ema=15,
fast_ema=5, RSI ≥ 93.7 on 4h within a 1d trend) across the vol_q4
cohort of Hyperliquid perps. Paper-only execution: positions are
recorded at the printing bar's close, marked to bar close on every
tick, and exited on stop/target.
"""
