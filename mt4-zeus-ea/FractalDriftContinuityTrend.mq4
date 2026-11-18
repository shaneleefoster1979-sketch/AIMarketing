//+------------------------------------------------------------------+
//| FractalDriftContinuityTrend.mq4                                  |
//|                                                                  |
//| MQL4 port of "Fractal Drift Continuity Trend" (c) SchizoQuant,
//| Pine Script v6, licensed under Mozilla Public License 2.0:
//| https://mozilla.org/MPL/2.0/ -- ported logic only, this header and
//| attribution kept intact per the license.
//|
//| Repaint check (done the same way as for DistributionalRankMomentum.mq4
//| before porting it): every quantity below -- recentRange/previousRange/
//| completeRange (ta.highest/ta.lowest, no forward offset), the recursive
//| fractalDimension carry-forward, the recursive fractalTrend adaptive
//| EMA, directionalDrift (reads fractalTrend shifted BACK by driftLength),
//| priceDisplacement, the recursive directionalPressure/stableDimension
//| EMAs, and bullishImpulse/bearishImpulse (read high[1]/low[1], a PAST
//| bar) -- only ever reads the current bar or bars strictly older. It
//| cannot repaint on an already-closed bar.
//|
//| One thing is MORE conservative here than in the NAL port: the original
//| script wraps the entire SQ regime-flip state machine in
//| `if barstate.isconfirmed`, so the TRANSITION ITSELF (not just an alert)
//| only ever commits on a fully-closed bar -- on the live/forming bar Pine
//| just holds the prior confirmed state. Replicated below: the trendline
//| value computes and plots live at shift 0 (matching Pine's own live
//| plot), but the SQ regime/signal only ever evaluates and flips for
//| shift >= 1 (confirmed bars); shift 0 simply inherits shift 1's SQ.
//|
//| Differences from the original Pine Script, all deliberate:
//|  1. Pine's `barcolor`/`plotcandle(..., force_overlay=true)` recolor
//|     the MAIN chart's candles by regime. Classic MQL4 has no such
//|     main-chart recoloring from a separate indicator -- left out. The
//|     trendline itself is still colored by regime (3-way buffer split:
//|     bull/bear/neutral), so the regime is still visible on the chart.
//|  2. Pine's input.source lets the source be picked from an open-ended
//|     dropdown (close/open/hl2/hlc3/...). MQL4 has no equivalent input
//|     type, so PriceSourceMode below picks from the common choices,
//|     defaulting to hl2 to match this script's own default.
//|  3. Buy/Sell triangle markers are plotted as arrows offset from
//|     price (Low-/High-side) rather than Pine's exact plotshape
//|     placement, which isn't recoverable 1:1 in MQL4 -- same signal
//|     events, cosmetic placement only.
//|
//| Formula ported faithfully: the two-window fractal-dimension estimate
//| ((ln(n1+n2)-ln(n3))/ln(2), clamped [1,2]), the exp(-4.6*(D-1)) adaptive
//| alpha, the recursive FRAMA-style fractalTrend, directional drift vs. a
//| driftLength-bars-back trend read, ATR-normalized price displacement,
//| the pressure/dimension EMAs, the congestion-scaled adaptive threshold,
//| and the sticky, confirmed-bar-gated SQ regime state machine.
//+------------------------------------------------------------------+
#property strict
#property indicator_chart_window
#property indicator_buffers 5
#property indicator_plots   5

#property indicator_label1  "Fractal Trend (Bull)"
#property indicator_type1   DRAW_LINE
#property indicator_color1  C'57,255,20'
#property indicator_width1  2

#property indicator_label2  "Fractal Trend (Bear)"
#property indicator_type2   DRAW_LINE
#property indicator_color2  C'138,43,226'
#property indicator_width2  2

#property indicator_label3  "Fractal Trend (Neutral)"
#property indicator_type3   DRAW_LINE
#property indicator_color3  clrGray
#property indicator_width3  2

#property indicator_label4  "Bullish Transition"
#property indicator_type4   DRAW_ARROW
#property indicator_color4  C'57,255,20'
#property indicator_width4  2

#property indicator_label5  "Bearish Transition"
#property indicator_type5   DRAW_ARROW
#property indicator_color5  C'138,43,226'
#property indicator_width5  2

enum ENUM_PRICE_SOURCE
{
   SRC_HL2   = 0, // (High+Low)/2 -- Pine default
   SRC_CLOSE = 1,
   SRC_OPEN  = 2,
   SRC_HIGH  = 3,
   SRC_LOW   = 4,
   SRC_HLC3  = 5,
   SRC_OHLC4 = 6
};

input ENUM_PRICE_SOURCE PriceSourceMode   = SRC_HL2; // matches Pine's hl2 default
input int    fractalLength       = 24;   // Fractal Length (forced even, as in Pine)
input int    dimensionSmoothing  = 3;    // Dimension Smoothing
input int    atrLength           = 14;   // ATR Length
input int    driftLength         = 3;    // Drift Lookback (bars)
input double driftInfluence      = 1.50; // Drift Influence
input double displacementInfluence = 0.30; // Price Displacement Influence
input int    pressureSmoothing   = 3;    // Pressure Smoothing
input double reversalThreshold   = 0.18; // Base Reversal Threshold
input double fractalProtection   = 0.25; // Fractal Congestion Protection
input bool   useImpulseOverride  = true; // Allow Impulse Override
input double impulseThreshold    = 1.20; // Impulse Threshold (x ATR)
input bool   EnableAlerts        = false;
input bool   EnablePush          = false;
input int    MaxBarsToProcess    = 5000; // caps how far back this full-history recompute ever goes -- same lesson as DistributionalRankMomentum.mq4's freeze: a rolling-window trend estimator doesn't need 25 years of history, and an uncapped recompute on a very deep chart can freeze MT4 on attach. Raise only if your hardware handles it.

double BufBull[], BufBear[], BufNeutral[], BufBuyArrow[], BufSellArrow[];

int OnInit()
{
   SetIndexBuffer(0, BufBull);
   SetIndexBuffer(1, BufBear);
   SetIndexBuffer(2, BufNeutral);
   SetIndexBuffer(3, BufBuyArrow);
   SetIndexBuffer(4, BufSellArrow);
   for(int b = 0; b < 5; b++) SetIndexEmptyValue(b, EMPTY_VALUE);

   SetIndexArrow(3, 233); // Wingdings up triangle -- bullish transition
   SetIndexArrow(4, 234); // Wingdings down triangle -- bearish transition

   IndicatorShortName("Fractal Drift Continuity Trend [SQ port]");
   return(INIT_SUCCEEDED);
}

double GetSource(const double &o[], const double &h[], const double &l[], const double &c[], int i)
{
   switch(PriceSourceMode)
   {
      case SRC_CLOSE: return c[i];
      case SRC_OPEN:  return o[i];
      case SRC_HIGH:  return h[i];
      case SRC_LOW:   return l[i];
      case SRC_HLC3:  return (h[i] + l[i] + c[i]) / 3.0;
      case SRC_OHLC4: return (o[i] + h[i] + l[i] + c[i]) / 4.0;
      default:        return (h[i] + l[i]) / 2.0; // SRC_HL2
   }
}

double HighestInRange(const double &arr[], int start, int len)
{
   double m = arr[start];
   for(int k = 1; k < len; k++) if(arr[start + k] > m) m = arr[start + k];
   return m;
}

double LowestInRange(const double &arr[], int start, int len)
{
   double m = arr[start];
   for(int k = 1; k < len; k++) if(arr[start + k] < m) m = arr[start + k];
   return m;
}

int OnCalculate(const int rates_total,
                const int prev_calculated,
                const datetime &time[],
                const double &open[],
                const double &high[],
                const double &low[],
                const double &close[],
                const long &tick_volume[],
                const long &volume[],
                const int &spread[])
{
   int fullLength = fractalLength - (fractalLength % 2); // force even, matching Pine
   if(fullLength < 2) fullLength = 2;
   int halfLength = fullLength / 2;

   int minBars = fullLength + driftLength + MathMax(atrLength, MathMax(dimensionSmoothing, pressureSmoothing)) + 20;
   if(rates_total < minBars) return(0);

   // Hard cap on how far back this full-history recompute ever processes --
   // see MaxBarsToProcess comment above. Close[]/High[]/Low[] indexing
   // (0 = newest) means this naturally covers "the newest `total` bars"
   // with nothing further back touched.
   int total = MathMin(rates_total, MaxBarsToProcess);

   // Buffers bound via SetIndexBuffer are zero-initialized by the platform,
   // not EMPTY_VALUE-initialized -- without this, bars beyond the cutoff
   // would show a stray flat line at 0 instead of simply not being drawn.
   // Only needs doing once ever: bars beyond `total` never change which
   // bars they are from one tick to the next.
   static bool blankedBeyondCutoff = false;
   if(!blankedBeyondCutoff && rates_total > total)
   {
      for(int j = total; j < rates_total; j++)
      {
         BufBull[j] = EMPTY_VALUE; BufBear[j] = EMPTY_VALUE; BufNeutral[j] = EMPTY_VALUE;
         BufBuyArrow[j] = EMPTY_VALUE; BufSellArrow[j] = EMPTY_VALUE;
      }
      blankedBeyondCutoff = true;
   }

   double fractalDimension[], fractalTrend[], directionalPressure[], stableDimension[], safeATR[];
   ArrayResize(fractalDimension, total);
   ArrayResize(fractalTrend, total);
   ArrayResize(directionalPressure, total);
   ArrayResize(stableDimension, total);
   ArrayResize(safeATR, total);

   double alphaP = 2.0 / (pressureSmoothing + 1.0);
   double alphaD = 2.0 / (dimensionSmoothing + 1.0);

   // Single oldest -> newest pass: fractalDimension, fractalTrend,
   // directionalPressure and stableDimension are all recursive (each bar
   // depends on the previous bar's already-computed value, i.e. the OLDER
   // neighbor at index i+1 in this 0=newest array convention), so they must
   // all be computed in this order.
   for(int i = total - 1; i >= 0; i--)
   {
      // --- fractal dimension (two-window range-scaling estimate) ---
      bool computable = (i + fullLength <= total);
      double dimVal;
      if(computable)
      {
         double recentRange   = HighestInRange(high, i, halfLength)              - LowestInRange(low, i, halfLength);
         double previousRange = HighestInRange(high, i + halfLength, halfLength) - LowestInRange(low, i + halfLength, halfLength);
         double completeRange = HighestInRange(high, i, fullLength)              - LowestInRange(low, i, fullLength);
         double n1 = recentRange / halfLength;
         double n2 = previousRange / halfLength;
         double n3 = completeRange / fullLength;
         if(n1 > 0 && n2 > 0 && n3 > 0)
         {
            dimVal = (MathLog(n1 + n2) - MathLog(n3)) / MathLog(2.0);
            if(dimVal < 1.0) dimVal = 1.0;
            if(dimVal > 2.0) dimVal = 2.0;
         }
         else
         {
            dimVal = (i + 1 < total) ? fractalDimension[i + 1] : 1.5; // carry forward, seed 1.5
         }
      }
      else
      {
         dimVal = (i + 1 < total) ? fractalDimension[i + 1] : 1.5;
      }
      fractalDimension[i] = dimVal;

      double adaptiveAlpha = MathExp(-4.6 * (dimVal - 1.0));
      if(adaptiveAlpha < 0.01) adaptiveAlpha = 0.01;
      if(adaptiveAlpha > 1.0)  adaptiveAlpha = 1.0;

      // --- ATR, floored like Pine's nz(atrValue, high-low) then a mintick floor ---
      double atrVal = iATR(NULL, 0, atrLength, i);
      if(atrVal <= 0 || atrVal == EMPTY_VALUE) atrVal = high[i] - low[i];
      if(atrVal < Point) atrVal = Point;
      safeATR[i] = atrVal;

      // --- fractal trend: recursive adaptive EMA (FRAMA-style) ---
      double src = GetSource(open, high, low, close, i);
      if(i + 1 >= total) fractalTrend[i] = src; // seed at the oldest processed bar
      else                 fractalTrend[i] = fractalTrend[i + 1] + adaptiveAlpha * (src - fractalTrend[i + 1]);

      // --- directional drift vs. a driftLength-bars-back trend read ---
      int histIdx = i + driftLength;
      double historicalTrend = (histIdx < total) ? fractalTrend[histIdx] : fractalTrend[i];
      double directionalDrift = (fractalTrend[i] - historicalTrend) / (safeATR[i] * driftLength);

      // --- ATR-normalized price displacement, clamped ---
      double priceDisplacement = (close[i] - fractalTrend[i]) / safeATR[i];
      if(priceDisplacement < -2.5) priceDisplacement = -2.5;
      if(priceDisplacement >  2.5) priceDisplacement =  2.5;

      double rawPressure = directionalDrift * driftInfluence + priceDisplacement * displacementInfluence;
      if(i + 1 >= total) directionalPressure[i] = rawPressure;
      else                 directionalPressure[i] = alphaP * rawPressure + (1.0 - alphaP) * directionalPressure[i + 1];

      if(i + 1 >= total) stableDimension[i] = dimVal;
      else                 stableDimension[i] = alphaD * dimVal + (1.0 - alphaD) * stableDimension[i + 1];
   }

   // SQ regime state machine -- evaluated oldest -> newest, but ONLY for
   // confirmed bars (i >= 1). Shift 0 (the live/forming bar) never
   // evaluates a new transition; it simply inherits shift 1's SQ, matching
   // Pine's `if barstate.isconfirmed` gate on the state transition itself.
   int SQ[];
   bool longSignal[], shortSignal[];
   ArrayResize(SQ, total);
   ArrayResize(longSignal, total);
   ArrayResize(shortSignal, total);

   int sqCarry = 0;
   for(int i = total - 1; i >= 1; i--)
   {
      longSignal[i] = false;
      shortSignal[i] = false;

      double fractalCongestion = stableDimension[i] - 1.0;
      if(fractalCongestion < 0) fractalCongestion = 0;
      if(fractalCongestion > 1) fractalCongestion = 1;
      double adaptiveThreshold = reversalThreshold + fractalProtection * fractalCongestion;

      bool bullishEvidence = (directionalPressure[i] >  adaptiveThreshold) && (close[i] > fractalTrend[i]);
      bool bearishEvidence = (directionalPressure[i] < -adaptiveThreshold) && (close[i] < fractalTrend[i]);

      bool bullishImpulse = false, bearishImpulse = false;
      if(useImpulseOverride && i + 1 < total)
      {
         bullishImpulse = (close[i] > fractalTrend[i] + impulseThreshold * safeATR[i]) && (close[i] > high[i + 1]);
         bearishImpulse = (close[i] < fractalTrend[i] - impulseThreshold * safeATR[i]) && (close[i] < low[i + 1]);
      }

      bool ready = (i + fullLength <= total) && (i + driftLength < total);
      if(ready)
      {
         if(sqCarry == 0)
         {
            sqCarry = (directionalPressure[i] >= 0) ? 1 : -1;
         }
         else if(sqCarry == -1 && (bullishEvidence || bullishImpulse))
         {
            sqCarry = 1;
            longSignal[i] = true;
         }
         else if(sqCarry == 1 && (bearishEvidence || bearishImpulse))
         {
            sqCarry = -1;
            shortSignal[i] = true;
         }
      }
      SQ[i] = sqCarry;
   }
   SQ[0] = SQ[1]; // unconfirmed live bar inherits the last confirmed regime
   longSignal[0] = false;
   shortSignal[0] = false;

   // Buffer fill
   for(int i = total - 1; i >= 0; i--)
   {
      BufBull[i] = EMPTY_VALUE; BufBear[i] = EMPTY_VALUE; BufNeutral[i] = EMPTY_VALUE;
      BufBuyArrow[i] = EMPTY_VALUE; BufSellArrow[i] = EMPTY_VALUE;

      if(SQ[i] == 1)       BufBull[i]    = fractalTrend[i];
      else if(SQ[i] == -1) BufBear[i]    = fractalTrend[i];
      else                  BufNeutral[i] = fractalTrend[i];

      if(longSignal[i])  BufBuyArrow[i]  = low[i]  - 0.5 * safeATR[i];
      if(shortSignal[i]) BufSellArrow[i] = high[i] + 0.5 * safeATR[i];
   }

   // Alerts: gated to a confirmed, just-closed bar (shift 1) -- the SQ
   // transition itself is already confirmed-bar-only above, so this just
   // fires once per new transition rather than re-checking live.
   if((EnableAlerts || EnablePush) && prev_calculated > 0 && total > 2)
   {
      static datetime lastAlertTime = 0;
      if(time[1] != lastAlertTime)
      {
         lastAlertTime = time[1];
         if(BufBuyArrow[1] != EMPTY_VALUE)
         {
            string msg = "Fractal Drift Continuity Trend flipped bullish on " + Symbol();
            if(EnableAlerts) Alert(msg);
            if(EnablePush)   SendNotification(msg);
         }
         if(BufSellArrow[1] != EMPTY_VALUE)
         {
            string msg2 = "Fractal Drift Continuity Trend flipped bearish on " + Symbol();
            if(EnableAlerts) Alert(msg2);
            if(EnablePush)   SendNotification(msg2);
         }
      }
   }

   return(rates_total);
}
//+------------------------------------------------------------------+
