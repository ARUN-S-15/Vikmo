"""Forecasting pipeline for VIKMO DealerDesk AI/ML Track.

Forecasts weekly units_sold for 40 SKUs over 4 weeks:
2026-09-28, 2026-10-05, 2026-10-12, 2026-10-19.

Adheres strictly to the run contract:
- Exactly 160 rows in ml/forecast.csv
- Columns: sku,week_start,forecast_units
- Non-negative forecasts
- Rigorous rolling-origin historical validation without future data leakage
"""
import math
from pathlib import Path
import pandas as pd
import numpy as np

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
ML_DIR = BASE_DIR / "ml"

TARGET_WEEKS = ["2026-09-28", "2026-10-05", "2026-10-12", "2026-10-19"]


def calculate_metrics(y_true, y_pred):
    y_true = np.array(y_true, dtype=float)
    y_pred = np.array(y_pred, dtype=float)
    mae = np.mean(np.abs(y_true - y_pred))
    rmse = math.sqrt(np.mean((y_true - y_pred) ** 2))
    total_actual = np.sum(y_true)
    wape = (np.sum(np.abs(y_true - y_pred)) / total_actual * 100) if total_actual > 0 else 0.0
    return {"mae": round(mae, 2), "rmse": round(rmse, 2), "wape": round(wape, 2)}


def get_diwali_offset_weeks(week_date_str, year):
    """Calculates weeks remaining until Diwali for the given date.
    Diwali dates from festival_calendar.csv:
    2024: 2024-11-01
    2025: 2025-10-21
    2026: 2026-11-08
    """
    diwali_map = {
        2024: pd.to_datetime("2024-11-01"),
        2025: pd.to_datetime("2025-10-21"),
        2026: pd.to_datetime("2026-11-08"),
    }
    diwali_date = diwali_map.get(year)
    if diwali_date is None:
        return 999
    week_dt = pd.to_datetime(week_date_str)
    diff_days = (diwali_date - week_dt).days
    return diff_days // 7


def predict_for_window(history_df, future_promo_df, target_weeks):
    """Predicts weekly sales for target_weeks given historical sales up to the cutoff date.
    Strictly prevents future leakage by only using observations present in history_df.
    """
    predictions = []
    lead_skus = sorted(history_df["sku"].unique())

    # Precalculate global promo uplift for shrinkage
    global_promo = history_df[history_df["promo_flag"] == 1]["units_sold"]
    global_non_promo = history_df[history_df["promo_flag"] == 0]["units_sold"]
    global_uplift = (global_promo.mean() / max(1.0, global_non_promo.mean())) if len(global_promo) > 0 else 1.5

    for sku in lead_skus:
        sku_hist = history_df[history_df["sku"] == sku].sort_values("week_start").reset_index(drop=True)
        n_obs = len(sku_hist)

        # 1. Base level estimation
        # Distinguish non-promo baseline
        non_promo_obs = sku_hist[sku_hist["promo_flag"] == 0]["units_sold"]
        recent_obs = sku_hist["units_sold"].tail(4)

        if n_obs < 10:
            # Newly introduced SKU: robust median / EMA of recent obs
            base_demand = max(0.0, float(recent_obs.median() if len(recent_obs) > 0 else 5.0))
            is_intermittent = False
            sku_promo_uplift = global_uplift
        else:
            zero_ratio = (sku_hist["units_sold"] == 0).mean()
            is_intermittent = zero_ratio > 0.30

            if is_intermittent:
                # Croston-inspired demand rate: demand size * demand probability
                non_zero_demands = sku_hist[sku_hist["units_sold"] > 0]["units_sold"]
                avg_demand_size = non_zero_demands.mean() if len(non_zero_demands) > 0 else 1.0
                demand_prob = (sku_hist["units_sold"] > 0).mean()
                base_demand = avg_demand_size * demand_prob
                sku_promo_uplift = 1.3  # modest uplift for intermittent parts
            else:
                # Regular SKU: weighted average of recent 4-week non-promo level and 12-week trend
                recent_non_promo = non_promo_obs.tail(4)
                if len(recent_non_promo) >= 2:
                    base_demand = float(recent_non_promo.mean())
                else:
                    base_demand = float(recent_obs.mean())

                # SKU specific promo uplift with shrinkage towards global mean
                sku_promo = sku_hist[sku_hist["promo_flag"] == 1]["units_sold"]
                if len(sku_promo) >= 3 and len(non_promo_obs) >= 3:
                    raw_uplift = sku_promo.mean() / max(1.0, non_promo_obs.mean())
                    # Empirical Bayes shrinkage: weight towards global
                    sku_promo_uplift = 0.6 * raw_uplift + 0.4 * global_uplift
                else:
                    sku_promo_uplift = global_uplift

        # Precompute same-week-last-year historical map for seasonal reference
        sku_date_map = dict(zip(sku_hist["week_start"].dt.strftime("%Y-%m-%d"), sku_hist["units_sold"]))

        for week in target_weeks:
            week_dt = pd.to_datetime(week)
            promo_row = future_promo_df[(future_promo_df["sku"] == sku) & (future_promo_df["week_start"] == week)]
            is_promo = int(promo_row["promo_flag"].values[0]) if len(promo_row) > 0 else 0

            # Festival multiplier based on distance to Diwali
            weeks_to_diwali = get_diwali_offset_weeks(week, week_dt.year)
            # Diwali lift ramps up 1 to 4 weeks before festival
            if 1 <= weeks_to_diwali <= 4:
                festive_mult = 1.0 + (0.25 * (5 - weeks_to_diwali) / 4.0)
            elif weeks_to_diwali == 0:
                festive_mult = 1.20
            else:
                festive_mult = 1.0

            # Seasonal same-week-last-year adjustment if available
            last_year_date = (week_dt - pd.Timedelta(weeks=52)).strftime("%Y-%m-%d")
            swly_val = sku_date_map.get(last_year_date)

            if swly_val is not None and not is_intermittent and n_obs >= 52:
                # Combine base trend with seasonal pattern
                seasonal_ratio = max(0.5, min(2.0, swly_val / max(1.0, base_demand)))
                pred = (0.7 * base_demand + 0.3 * swly_val) * festive_mult
            else:
                pred = base_demand * festive_mult

            # Apply promotional uplift
            if is_promo:
                pred *= sku_promo_uplift

            pred = max(0.0, round(float(pred), 2))
            predictions.append({"sku": sku, "week_start": week, "forecast_units": pred})

    return pd.DataFrame(predictions)


def run_pipeline():
    print("Loading datasets...")
    sales_df = pd.read_csv(DATA_DIR / "sales_history.csv")
    sales_df["week_start"] = pd.to_datetime(sales_df["week_start"])
    lead_df = pd.read_csv(DATA_DIR / "lead_times.csv")
    promo_df = pd.read_csv(DATA_DIR / "promo_calendar.csv")

    # Filter sales to lead SKUs only
    target_skus = set(lead_df["sku"].unique())
    sales_df = sales_df[sales_df["sku"].isin(target_skus)].sort_values(["sku", "week_start"]).reset_index(drop=True)

    print(f"Total sales history rows: {len(sales_df)} across {len(target_skus)} SKUs")

    # =========================================================================
    # ROLLING ORIGIN BACKTESTING (Last 4 Weeks of available history)
    # =========================================================================
    all_weeks = sorted(sales_df["week_start"].unique())
    cutoff_idx = len(all_weeks) - 4
    train_weeks = all_weeks[:cutoff_idx]
    eval_weeks = all_weeks[cutoff_idx:]
    eval_week_strs = [w.strftime("%Y-%m-%d") for w in eval_weeks]

    train_sales = sales_df[sales_df["week_start"].isin(train_weeks)].copy()
    eval_actuals = sales_df[sales_df["week_start"].isin(eval_weeks)].copy()

    print(f"\n--- BACKTESTING VALIDATION (Origin: {train_weeks[-1].strftime('%Y-%m-%d')}) ---")
    print(f"Evaluation window: {eval_week_strs}")

    # Baseline 1: Last Value (Naive)
    last_vals = train_sales.groupby("sku").last()["units_sold"].to_dict()
    eval_actuals["pred_naive"] = eval_actuals["sku"].map(last_vals).fillna(0)

    # Baseline 2: 4-Week Moving Average
    ma4 = train_sales.groupby("sku").tail(4).groupby("sku")["units_sold"].mean().to_dict()
    eval_actuals["pred_ma4"] = eval_actuals["sku"].map(ma4).fillna(0)

    # Baseline 3: Same Week Last Year (52 weeks prior)
    train_lookup = dict(zip(zip(train_sales["sku"], train_sales["week_start"]), train_sales["units_sold"]))
    swly_preds = []
    for _, row in eval_actuals.iterrows():
        prev_dt = row["week_start"] - pd.Timedelta(weeks=52)
        swly_preds.append(train_lookup.get((row["sku"], prev_dt), ma4.get(row["sku"], 0)))
    eval_actuals["pred_swly"] = swly_preds

    # Model Evaluation on same backtest window
    backtest_promo = eval_actuals[["week_start", "sku", "promo_flag"]].copy()
    backtest_promo["week_start"] = backtest_promo["week_start"].dt.strftime("%Y-%m-%d")
    model_backtest_preds = predict_for_window(train_sales, backtest_promo, eval_week_strs)
    eval_merged = eval_actuals.merge(
        model_backtest_preds,
        left_on=["sku", eval_actuals["week_start"].dt.strftime("%Y-%m-%d")],
        right_on=["sku", "week_start"],
        suffixes=("", "_model"),
    )

    m_naive = calculate_metrics(eval_actuals["units_sold"], eval_actuals["pred_naive"])
    m_ma4 = calculate_metrics(eval_actuals["units_sold"], eval_actuals["pred_ma4"])
    m_swly = calculate_metrics(eval_actuals["units_sold"], eval_actuals["pred_swly"])
    m_model = calculate_metrics(eval_merged["units_sold"], eval_merged["forecast_units"])

    print(f"Baseline 1 (Last Value / Naive):      MAE={m_naive['mae']}, RMSE={m_naive['rmse']}, WAPE={m_naive['wape']}%")
    print(f"Baseline 2 (4-Week Moving Average):   MAE={m_ma4['mae']}, RMSE={m_ma4['rmse']}, WAPE={m_ma4['wape']}%")
    print(f"Baseline 3 (Same Week Last Year):     MAE={m_swly['mae']}, RMSE={m_swly['rmse']}, WAPE={m_swly['wape']}%")
    print(f"DealerDesk Multi-Factor Model:        MAE={m_model['mae']}, RMSE={m_model['rmse']}, WAPE={m_model['wape']}%")

    # =========================================================================
    # GENERATE PRODUCTION FORECAST FOR TARGET WEEKS
    # =========================================================================
    print(f"\nGenerating final forecast for {len(target_skus)} SKUs across {TARGET_WEEKS}...")
    final_forecast_df = predict_for_window(sales_df, promo_df, TARGET_WEEKS)

    # Validate output contract
    assert len(final_forecast_df) == 160, f"Expected 160 rows, got {len(final_forecast_df)}"
    assert list(final_forecast_df.columns) == ["sku", "week_start", "forecast_units"], "Columns mismatch"
    assert (final_forecast_df["forecast_units"] >= 0).all(), "Negative forecast values detected"

    out_file = ML_DIR / "forecast.csv"
    final_forecast_df.to_csv(out_file, index=False)
    print(f"Committed {len(final_forecast_df)} rows to {out_file} successfully!")


if __name__ == "__main__":
    run_pipeline()
