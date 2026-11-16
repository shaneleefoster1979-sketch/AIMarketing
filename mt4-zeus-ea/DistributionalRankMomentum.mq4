//+------------------------------------------------------------------+
//| DistributionalRankMomentum.mq4                                   |
//|                                                                  |
//| MQL4 port of "Distributional Rank Momentum | NAL" (c) NordicAlphaLab,
//| Pine Script v6, licensed under Mozilla Public License 2.0:
//| https://mozilla.org/MPL/2.0/ -- ported logic only, this header and
//| attribution kept intact per the license.
//|
//| Differences from the original Pine Script, all deliberate:
//|  1. The gradient fills between the Score line and its active
//|     threshold have no MQL4 equivalent (no fill-between-two-plots
//|     outside MQL5's DRAW_FILLING) -- left out rather than faked.
//|  2. Pine's plotcandle(..., force_overlay=true) recolors the MAIN
//|     price chart's candles by regime. Classic MQL4 has no DRAW_CANDLES
//|     style and a separate-window indicator cannot draw on the main
//|     chart pane -- left out. The Score line itself is still colored
//|     by regime (3-way split: bull/bear/neutral buffers), so the
//|     regime is still visible, just not painted onto the candles.
//|  3. Pine's Buy/Sell triangle shapes use force_overlay=true to sit on
//|     the price chart (below/above the candles). Here they're plotted
//|     in this indicator's own subwindow instead, at the Score's value
//|     -- same transition events, different pane.
//|  4. Score/EMA/NAL compute and plot live at shift 0 (matching Pine's
//|     own live-updating behavviour) -- only the ALERT firing is gated
//|     to confirmed, just-closed bars (shift 1, new-bar detected),
//|     matching Pine's barstate.isconfirmed exactly (Pine applies that
//|     guard only to the alert flips, not to the plotted values).
//|
//| Formula ported faithfully: percentile-linear-interpolation (same
//| method as numpy's default "linear" and Excel's PERCENTILE.INC),
//| the momentum-vs-own-percentile source, the 99-level percentile rank
//| scoring, the EMA confluence gate, and the sticky NAL state machine.
//+------------------------------------------------------------------+
#property strict
#property indicator_separate_window
#property indicator_buffers 8
#property indicator_plots   8
#property indicator_minimum -5
#property indicator_maximum 105

#property indicator_label1  "Score (Bull)"
#property indicator_type1   DRAW_LINE
#property indicator_color1  C'0,255,200'
#property indicator_width1  2

#property indicator_label2  "Score (Bear)"
#property indicator_type2   DRAW_LINE
#property indicator_color2  C'32,94,144'
#property indicator_width2  2

#property indicator_label3  "Score (Neutral)"
#property indicator_type3   DRAW_LINE
#property indicator_color3  clrGray
#property indicator_width3  2

#property indicator_label4  "Rank EMA"
#property indicator_type4   DRAW_LINE
#property indicator_color4  clrSilver
#property indicator_style4  STYLE_DOT
#property indicator_width4  1

#property indicator_label5  "Bullish Transition"
#property indicator_type5   DRAW_ARROW
#property indicator_color5  C'0,255,200'
#property indicator_width5  2

#property indicator_label6  "Bearish Transition"
#property indicator_type6   DRAW_ARROW
#property indicator_color6  C'32,94,144'
#property indicator_width6  2

#property indicator_label7  "Bullish Threshold"
#property indicator_type7   DRAW_LINE
#property indicator_color7  C'0,255,200'
#property indicator_style7  STYLE_DOT
#property indicator_width7  1

#property indicator_label8  "Bearish Threshold"
#property indicator_type8   DRAW_LINE
#property indicator_color8  C'32,94,144'
#property indicator_style8  STYLE_DOT
#property indicator_width8  1

input int    momLen        = 60;    // Momentum Length
input int    Lookback      = 60;    // Distributional Rank Lookback
input double uThreshold    = 90.0;  // Bullish Threshold
input double lThreshold    = 40.0;  // Bearish Threshold
input bool   UseEMAConfluence = true;
input int    EMALength     = 30;
input bool   EnableAlerts  = false;
input bool   EnablePush    = false;
input int    MaxBarsToProcess = 3000; // caps how far back this indicator ever computes -- this is a full-history recompute every tick (see OnCalculate), and a chart with a very deep history (hundreds of thousands of bars) will freeze MT4 on attach without this cap. A rank/momentum oscillator doesn't need 25 years of history anyway; raise this only if your hardware handles it and you actually need the extra lookback.

double BufBull[], BufBear[], BufNeutral[], BufEMA[], BufBuyArrow[], BufSellArrow[], BufUpperLine[], BufLowerLine[];

int OnInit()
{
   SetIndexBuffer(0, BufBull);
   SetIndexBuffer(1, BufBear);
   SetIndexBuffer(2, BufNeutral);
   SetIndexBuffer(3, BufEMA);
   SetIndexBuffer(4, BufBuyArrow);
   SetIndexBuffer(5, BufSellArrow);
   SetIndexBuffer(6, BufUpperLine);
   SetIndexBuffer(7, BufLowerLine);
   for(int b = 0; b < 8; b++) SetIndexEmptyValue(b, EMPTY_VALUE);

   SetIndexArrow(4, 233); // up triangle-ish (Wingdings up arrow) -- Buy
   SetIndexArrow(5, 234); // down arrow -- Sell

   IndicatorShortName("Distributional Rank Momentum [NAL port]");
   IndicatorDigits(2);
   return(INIT_SUCCEEDED);
}

// Same method as Pine's ta.percentile_linear_interpolation / array.percentile_linear_interpolation
// (numpy's default "linear" method, Excel PERCENTILE.INC): sorts ascending,
// interpolates linearly between the two bracketing ranks.
double PercentileLinearInterp(double &sortedAsc[], int n, double pct)
{
   if(n <= 0) return EMPTY_VALUE;
   if(n == 1) return sortedAsc[0];
   double rank = pct / 100.0 * (n - 1);
   int lo = (int)MathFloor(rank);
   int hi = (int)MathCeil(rank);
   if(lo < 0) lo = 0;
   if(hi > n - 1) hi = n - 1;
   double frac = rank - lo;
   return sortedAsc[lo] + frac * (sortedAsc[hi] - sortedAsc[lo]);
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
   int minBars = momLen + Lookback + EMALength + 10;
   if(rates_total < minBars) return(0);
   // Hard cap on how far back this ever computes -- see MaxBarsToProcess
   // comment. Close[]/Open[] indexing (0 = newest) means this naturally
   // covers "the newest `total` bars" with nothing further back touched.
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
         BufEMA[j] = EMPTY_VALUE; BufBuyArrow[j] = EMPTY_VALUE; BufSellArrow[j] = EMPTY_VALUE;
         BufUpperLine[j] = EMPTY_VALUE; BufLowerLine[j] = EMPTY_VALUE;
      }
      blankedBeyondCutoff = true;
   }

   double pct = (uThreshold + lThreshold) / 2.0;

   // Pass 1: Momentum[i] = Close[i] - percentile_linear_interp(Close[i..i+momLen-1], pct)
   // Needs momLen closes ending at (and including) bar i.
   // closeWindow is allocated ONCE outside the loop and reused (just
   // overwritten) each iteration -- repeatedly calling ArrayResize() inside
   // a per-bar loop was the other big cost that made attaching this freeze
   // the terminal.
   double momentum[];
   ArrayResize(momentum, total);
   double closeWindow[];
   ArrayResize(closeWindow, momLen);
   for(int i = 0; i < total; i++)
   {
      if(i + momLen > total) { momentum[i] = EMPTY_VALUE; continue; }
      for(int k = 0; k < momLen; k++) closeWindow[k] = Close[i + k];
      ArraySort(closeWindow); // ascending
      momentum[i] = Close[i] - PercentileLinearInterp(closeWindow, momLen, pct);
   }

   // Pass 2: Score[i] -- rank of momentum[i] against the trailing Lookback-sized
   // window of momentum[i..i+Lookback-1], via 99 interpolated percentile levels
   // (1..99) checked against the current momentum value. Needs the full window
   // of Lookback valid momentum values. windowAsc reused the same way as
   // closeWindow above.
   double score[];
   ArrayResize(score, total);
   double windowAsc[];
   ArrayResize(windowAsc, Lookback);
   for(int i = 0; i < total; i++)
   {
      if(i + Lookback > total || momentum[i] == EMPTY_VALUE) { score[i] = EMPTY_VALUE; continue; }
      bool windowValid = true;
      for(int k = 0; k < Lookback; k++)
      {
         if(momentum[i + k] == EMPTY_VALUE) { windowValid = false; break; }
         windowAsc[k] = momentum[i + k];
      }
      if(!windowValid) { score[i] = EMPTY_VALUE; continue; }
      ArraySort(windowAsc); // ascending

      int aboveCount = 0;
      for(int p = 1; p <= 99; p++)
      {
         double level = PercentileLinearInterp(windowAsc, Lookback, (double)p);
         if(level != EMPTY_VALUE && level < momentum[i]) aboveCount++;
      }
      score[i] = aboveCount / 99.0 * 100.0;
   }

   // Pass 3: EMA of Score -- recursive, oldest -> newest. Seeds at the first
   // valid Score with EMA = Score itself, matching Pine's ta.ema seeding.
   double emaArr[];
   ArrayResize(emaArr, total);
   double alpha = 2.0 / (EMALength + 1.0);
   double runningEma = EMPTY_VALUE;
   for(int i = total - 1; i >= 0; i--)
   {
      if(score[i] == EMPTY_VALUE) { emaArr[i] = EMPTY_VALUE; continue; }
      runningEma = (runningEma == EMPTY_VALUE) ? score[i] : (alpha * score[i] + (1.0 - alpha) * runningEma);
      emaArr[i] = runningEma;
   }

   // Pass 4: NAL sticky state machine + buffers -- recursive, oldest -> newest.
   int nalPrev = 0;
   for(int i = total - 1; i >= 0; i--)
   {
      BufBull[i] = EMPTY_VALUE; BufBear[i] = EMPTY_VALUE; BufNeutral[i] = EMPTY_VALUE;
      BufEMA[i] = EMPTY_VALUE; BufBuyArrow[i] = EMPTY_VALUE; BufSellArrow[i] = EMPTY_VALUE;
      BufUpperLine[i] = uThreshold; BufLowerLine[i] = lThreshold;

      if(score[i] == EMPTY_VALUE) { nalPrev = 0; continue; }

      bool haveEma = (UseEMAConfluence && emaArr[i] != EMPTY_VALUE);
      bool emaBullish = (!UseEMAConfluence) || (haveEma && score[i] > emaArr[i]);
      bool emaBearish = (!UseEMAConfluence) || (haveEma && score[i] < emaArr[i]);

      bool bullish = (score[i] >= uThreshold) && emaBullish;
      bool bearish = (score[i] <  lThreshold) && emaBearish;

      int nal = bullish ? 1 : (bearish ? -1 : nalPrev);

      if(nal == 1)       BufBull[i]    = score[i];
      else if(nal == -1) BufBear[i]    = score[i];
      else                BufNeutral[i] = score[i];

      if(UseEMAConfluence && emaArr[i] != EMPTY_VALUE) BufEMA[i] = emaArr[i];

      if(nal == 1  && nalPrev == -1) BufBuyArrow[i]  = score[i];
      if(nal == -1 && nalPrev ==  1) BufSellArrow[i] = score[i];

      nalPrev = nal;
   }

   // Alerts: gated to a confirmed, just-closed bar (shift 1), matching Pine's
   // barstate.isconfirmed -- the plotted values above already updated live at
   // shift 0, same as the real indicator does; only the alert fire is held
   // back to the bar that has actually finished.
   if((EnableAlerts || EnablePush) && prev_calculated > 0 && total > 2)
   {
      static datetime lastAlertTime = 0;
      if(Time[1] != lastAlertTime)
      {
         lastAlertTime = Time[1];
         if(BufBuyArrow[1]  != EMPTY_VALUE)
         {
            string msg = "Distributional Rank Momentum changed to bullish on " + Symbol();
            if(EnableAlerts) Alert(msg);
            if(EnablePush)   SendNotification(msg);
         }
         if(BufSellArrow[1] != EMPTY_VALUE)
         {
            string msg2 = "Distributional Rank Momentum changed to bearish on " + Symbol();
            if(EnableAlerts) Alert(msg2);
            if(EnablePush)   SendNotification(msg2);
         }
      }
   }

   return(rates_total);
}
//+------------------------------------------------------------------+
