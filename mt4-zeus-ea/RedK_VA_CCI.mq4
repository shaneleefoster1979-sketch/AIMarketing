//+------------------------------------------------------------------+
//| RedK_VA_CCI.mq4                                                  |
//|                                                                  |
//| MQL4 port of "RedK DualTF Volume-Accelerated CCI" (c) RedKTrader,
//| Pine Script v6, licensed under Mozilla Public License 2.0:
//| https://mozilla.org/MPL/2.0/ -- ported logic only, this header and
//| attribution kept intact per the license.
//|
//| Formula ported faithfully: the volume-weighted mean/mean-deviation
//| CCI (f_CalcVA_CCI/f_wdev), the optional stochastic rescale to a fixed
//| +-100 range, the soft-cap easing curve beyond +-200, the selectable
//| smoothing (SMA/EMA/HMA/RMA/WMA, HMA built manually -- MQL4's iMA has
//| no Hull mode), the signal line, and the Current-vs-Context TF
//| alignment logic.
//|
//| Differences from the original Pine Script, all deliberate:
//|  1. Volume: this project's symbol (and forex generally) has no real
//|     traded volume, so "Volume Weighted" uses MT4's tick volume as the
//|     practical proxy, same as every other volume reference in this
//|     project. With Volume Weighted off, this has no effect either way
//|     (matches the original's own stated behavior for no-volume symbols).
//|  2. Context (higher) timeframe resolution: Pine's timeframe.from_seconds
//|     can produce an arbitrary custom resolution (chart TF x multiplier,
//|     exactly). MQL4 only has the fixed standard periods (M1/M5/M15/M30/
//|     H1/H4/D1/W1/MN1) -- ResolveHTFPeriod() below snaps UP to the
//|     nearest one that is >= chart TF x multiplier, which will often NOT
//|     equal that product exactly (e.g. H1 x 5 = 300min snaps to D1, since
//|     MQL4 has nothing between H4 and D1). There is also no resolution
//|     above Monthly, so a multiplier that would exceed MN1 is clamped
//|     there instead. This is a genuine MQL4 platform limitation, not an
//|     approximation choice -- turn on DebugComment to see the resolved
//|     period and sanity-check it against what you expected.
//|  3. Live Update vs. Last Closed Bar: MT4 keeps the CURRENTLY FORMING
//|     higher-TF bar live (iHigh/iLow/iClose/iVolume(..., shift 0) update
//|     continuously, same as the chart's own current bar) but, once a
//|     higher-TF bar actually closes, MT4 only ever remembers its final
//|     OHLCV -- not how it looked tick-by-tick while it was still forming.
//|     So the two modes can only ever differ for the SINGLE currently-
//|     forming higher-TF bar (and whichever chart bars fall within it):
//|     Live Update reads it directly (shift 0, live); Last Closed Bar
//|     holds the previous, already-closed higher-TF bar's value (shift 1)
//|     instead, until the current one closes. Every older bar is
//|     identical under both modes -- there is nothing left to "hold back"
//|     further back than that, on either platform.
//|  4. Gradient area fills (Context sentiment fill, Control Level fill)
//|     have no classic-MQL4 equivalent (no fill-between-two-plots outside
//|     MQL5's DRAW_FILLING) -- left out rather than faked. Direction/
//|     regime is still fully conveyed through the bull/bear color split
//|     on each line, same as every other multi-color line in this project.
//|  5. TF Alignment markers: Pine's location.top/location.bottom pins a
//|     shape to the pane's edge regardless of value, which classic MQL4
//|     has no direct equivalent for. Plotted here instead at a fixed
//|     offset beyond the Control Levels (an approximation of "near the
//|     top/bottom"), not a literal pane-edge pixel position.
//|  6. Pine's "Debug: show Context TF" plots are replaced with a single
//|     Comment() diagnostic (DebugComment input), since MQL4's Data
//|     Window doesn't support conditional per-input plot visibility the
//|     way Pine's `display` parameter does.
//+------------------------------------------------------------------+
#property strict
#property indicator_separate_window
#property indicator_buffers 9
#property indicator_plots   9
#property indicator_level1  0.0

#property indicator_label1  "CCI (Bull)"
#property indicator_type1   DRAW_LINE
#property indicator_color1  C'102,255,0'
#property indicator_width1  3

#property indicator_label2  "CCI (Bear)"
#property indicator_type2   DRAW_LINE
#property indicator_color2  C'255,26,26'
#property indicator_width2  3

#property indicator_label3  "CCI Signal"
#property indicator_type3   DRAW_LINE
#property indicator_color3  clrGray
#property indicator_width3  1

#property indicator_label4  "Context CCI (Bull)"
#property indicator_type4   DRAW_LINE
#property indicator_color4  C'219,219,219'
#property indicator_width4  1

#property indicator_label5  "Context CCI (Bear)"
#property indicator_type5   DRAW_LINE
#property indicator_color5  C'99,99,99'
#property indicator_width5  1

#property indicator_label6  "Bull Alignment"
#property indicator_type6   DRAW_ARROW
#property indicator_color6  C'219,219,219'
#property indicator_width6  2

#property indicator_label7  "Bear Alignment"
#property indicator_type7   DRAW_ARROW
#property indicator_color7  C'99,99,99'
#property indicator_width7  2

#property indicator_label8  "Upper Control Level"
#property indicator_type8   DRAW_LINE
#property indicator_color8  C'0,153,0'
#property indicator_style8  STYLE_DASH
#property indicator_width8  1

#property indicator_label9  "Lower Control Level"
#property indicator_type9   DRAW_LINE
#property indicator_color9  C'153,0,0'
#property indicator_style9  STYLE_DASH
#property indicator_width9  1

enum ENUM_PRICE_SOURCE
{
   SRC_HLC3  = 0, // (High+Low+Close)/3 -- Pine default
   SRC_CLOSE = 1,
   SRC_OPEN  = 2,
   SRC_HIGH  = 3,
   SRC_LOW   = 4,
   SRC_HL2   = 5,
   SRC_OHLC4 = 6
};

enum ENUM_MA_TYPE
{
   MA_SMA = 0,
   MA_EMA = 1,
   MA_HMA = 2,
   MA_RMA = 3,
   MA_WMA = 4
};

enum ENUM_CTX_UPDATE
{
   CTX_LIVE_UPDATE  = 0, // matches Pine's "Live Update"
   CTX_LAST_CLOSED  = 1  // matches Pine's "Last Closed Bar"
};

input int    cciLen           = 10;        // CCI Length
input ENUM_PRICE_SOURCE cciSrc = SRC_HLC3;  // Source
input double LamC             = 0.015;     // Lambert's Constant
input bool   VolWeighted      = true;      // Volume Weighted (uses tick volume -- see header)
input bool   stoch_in         = false;     // Stochastic Mode
input int    stoch_len        = 10;        // Stochastic Length
input int    smooth           = 3;         // Smoothing (bars)
input ENUM_MA_TYPE smth_type  = MA_WMA;    // Smoothing Averaging
input color  col_cci_long     = C'102,255,0';
input color  col_cci_short    = C'255,26,26';

input int    signal_len       = 5;         // Signal Line Length
input ENUM_MA_TYPE sig_avg_type = MA_EMA;  // Signal Line Averaging
input color  col_signal       = clrGray;

input bool   show_htf         = false;     // Show Context (Higher) TF CCI
input int    htf_mult         = 5;         // Context TF Multiplier (chart TF x this, snapped to nearest MQL4 period -- see header)
input ENUM_CTX_UPDATE htf_update = CTX_LIVE_UPDATE;
input color  col_cciH_long    = C'219,219,219';
input color  col_cciH_short   = C'99,99,99';

input bool   soft_cap         = false;     // Soft Cap Beyond +-200 (ignored in Stochastic mode)
input double ctrl_up          = 70.0;      // Upper Control Level
input double ctrl_dn          = -70.0;     // Lower Control Level
input bool   show_align       = true;      // TF Alignment Markers

input bool   EnableAlerts     = false;
input bool   EnablePush       = false;
input bool   DebugComment     = false;     // Shows the resolved Context period on-chart
input int    MaxBarsToProcess = 3000;      // caps how far back this full-history recompute ever goes -- same lesson as DistributionalRankMomentum.mq4's freeze: this indicator does several windowed scans (CCI mean/deviation, stochastic rescale, HMA) per bar, and an uncapped recompute on a very deep chart can freeze MT4 on attach. Raise only if your hardware handles it.

double BufCciBull[], BufCciBear[], BufSignal[], BufCtxBull[], BufCtxBear[], BufAlignUp[], BufAlignDn[], BufCtrlUp[], BufCtrlDn[];

int OnInit()
{
   SetIndexBuffer(0, BufCciBull);
   SetIndexBuffer(1, BufCciBear);
   SetIndexBuffer(2, BufSignal);
   SetIndexBuffer(3, BufCtxBull);
   SetIndexBuffer(4, BufCtxBear);
   SetIndexBuffer(5, BufAlignUp);
   SetIndexBuffer(6, BufAlignDn);
   SetIndexBuffer(7, BufCtrlUp);
   SetIndexBuffer(8, BufCtrlDn);
   for(int b = 0; b < 9; b++) SetIndexEmptyValue(b, EMPTY_VALUE);

   SetIndexArrow(5, 233); // Wingdings up triangle -- bull alignment
   SetIndexArrow(6, 234); // Wingdings down triangle -- bear alignment

   SetIndexLabel(0, "CCI (Bull)");
   SetIndexLabel(1, "CCI (Bear)");
   SetIndexLabel(2, "CCI Signal");
   SetIndexLabel(3, "Context CCI (Bull)");
   SetIndexLabel(4, "Context CCI (Bear)");

   IndicatorShortName("RedK VA-CCI port");
   return(INIT_SUCCEEDED);
}

//--- Price source helper, generic over any OHLC set (chart or HTF arrays)
double PriceOf(const double &o[], const double &h[], const double &l[], const double &c[], int i)
{
   switch(cciSrc)
   {
      case SRC_CLOSE: return c[i];
      case SRC_OPEN:  return o[i];
      case SRC_HIGH:  return h[i];
      case SRC_LOW:   return l[i];
      case SRC_HL2:   return (h[i] + l[i]) / 2.0;
      case SRC_OHLC4: return (o[i] + h[i] + l[i] + c[i]) / 4.0;
      default:        return (h[i] + l[i] + c[i]) / 3.0; // SRC_HLC3
   }
}

//--- Snaps chart TF x multiplier up to the nearest available MQL4 period -- see header point 2
int ResolveHTFPeriod(int basePeriod, int mult)
{
   int target = basePeriod * mult;
   int periods[9] = {1, 5, 15, 30, 60, 240, 1440, 10080, 43200};
   for(int k = 0; k < 9; k++) if(periods[k] >= target) return periods[k];
   return 43200; // clamp at Monthly -- MQL4 has nothing above MN1
}

double WmaWindow(const double &arr[], int start, int len)
{
   double num = 0, den = 0;
   for(int k = 0; k < len; k++) { double w = len - k; num += arr[start + k] * w; den += w; }
   return (den != 0) ? num / den : EMPTY_VALUE;
}

double SmaWindow(const double &arr[], int start, int len)
{
   double s = 0;
   for(int k = 0; k < len; k++) s += arr[start + k];
   return s / len;
}

//--- Full MA array over src[] (0=newest), oldest->newest for recursive types,
//    windowed per-bar for SMA/WMA/HMA. HMA = WMA(2*WMA(n/2)-WMA(n), round(sqrt(n))).
void ComputeMAArray(const double &src[], int total, int len, ENUM_MA_TYPE maType, double &dst[])
{
   ArrayResize(dst, total);
   if(maType == MA_EMA || maType == MA_RMA)
   {
      double alpha = (maType == MA_EMA) ? 2.0 / (len + 1.0) : 1.0 / len;
      double running = EMPTY_VALUE;
      for(int i = total - 1; i >= 0; i--)
      {
         if(src[i] == EMPTY_VALUE) { dst[i] = EMPTY_VALUE; running = EMPTY_VALUE; continue; }
         running = (running == EMPTY_VALUE) ? src[i] : alpha * src[i] + (1.0 - alpha) * running;
         dst[i] = running;
      }
      return;
   }

   int halfLen = (int)MathMax(1, MathRound(len / 2.0));
   int sqrtLen = (int)MathMax(1, MathRound(MathSqrt(len)));
   double diff[];
   if(maType == MA_HMA) ArrayResize(diff, sqrtLen); // allocated once, reused per bar -- see MaxBarsToProcess comment re: the NAL freeze lesson

   for(int i = 0; i < total; i++)
   {
      if(i + len > total) { dst[i] = EMPTY_VALUE; continue; }
      if(maType == MA_SMA) { dst[i] = SmaWindow(src, i, len); continue; }
      if(maType == MA_WMA) { dst[i] = WmaWindow(src, i, len); continue; }

      // HMA
      if(i + sqrtLen - 1 + len > total) { dst[i] = EMPTY_VALUE; continue; }
      bool ok = true;
      for(int k = 0; k < sqrtLen; k++)
      {
         double wHalf = WmaWindow(src, i + k, halfLen);
         double wFull = WmaWindow(src, i + k, len);
         if(wHalf == EMPTY_VALUE || wFull == EMPTY_VALUE) { ok = false; break; }
         diff[k] = 2.0 * wHalf - wFull;
      }
      dst[i] = ok ? WmaWindow(diff, 0, sqrtLen) : EMPTY_VALUE;
   }
}

//--- Volume-weighted CCI (+ optional stochastic rescale), reused for both
//    the chart-TF and Context-TF series.
void ComputeVACCI(const double &src[], const double &vol[], int total, int len, double lamC,
                   bool stochOn, int stochLen, double &outCCI[])
{
   double rawCci[];
   ArrayResize(rawCci, total);
   for(int i = 0; i < total; i++)
   {
      if(i + len > total) { rawCci[i] = EMPTY_VALUE; continue; }
      double sumSV = 0, sumV = 0;
      for(int k = 0; k < len; k++) { sumSV += src[i + k] * vol[i + k]; sumV += vol[i + k]; }
      double avg = (sumV != 0) ? sumSV / sumV : src[i];
      double sumDev = 0;
      for(int k = 0; k < len; k++) sumDev += vol[i + k] * MathAbs(src[i + k] - avg);
      double mdev = (sumV != 0) ? sumDev / sumV : 0;
      rawCci[i] = (mdev != 0) ? (src[i] - avg) / (lamC * mdev) : 0.0;
   }

   ArrayResize(outCCI, total);
   if(!stochOn) { for(int i = 0; i < total; i++) outCCI[i] = rawCci[i]; return; }

   for(int i = 0; i < total; i++)
   {
      if(rawCci[i] == EMPTY_VALUE || i + stochLen > total) { outCCI[i] = EMPTY_VALUE; continue; }
      double hh = rawCci[i], ll = rawCci[i];
      bool validWin = true;
      for(int k = 0; k < stochLen; k++)
      {
         if(rawCci[i + k] == EMPTY_VALUE) { validWin = false; break; }
         if(rawCci[i + k] > hh) hh = rawCci[i + k];
         if(rawCci[i + k] < ll) ll = rawCci[i + k];
      }
      if(!validWin) { outCCI[i] = EMPTY_VALUE; continue; }
      double rangeHL = hh - ll;
      double stochVal = (rangeHL != 0) ? 100.0 * (rawCci[i] - ll) / rangeHL : 50.0;
      outCCI[i] = 2.0 * stochVal - 100.0;
   }
}

double SoftCap(double x)
{
   if(x == EMPTY_VALUE) return x;
   if(!soft_cap || MathAbs(x) <= 200.0) return x;
   double sign = (x > 0) ? 1.0 : -1.0;
   return sign * (200.0 + 50.0 * (1.0 - MathExp(-(MathAbs(x) - 200.0) / 50.0)));
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
   int minBars = cciLen + MathMax(smooth, signal_len) + stoch_len + 20;
   if(rates_total < minBars) return(0);

   int total = MathMin(rates_total, MaxBarsToProcess);

   static bool blankedBeyondCutoff = false;
   if(!blankedBeyondCutoff && rates_total > total)
   {
      for(int j = total; j < rates_total; j++)
      {
         BufCciBull[j] = EMPTY_VALUE; BufCciBear[j] = EMPTY_VALUE; BufSignal[j] = EMPTY_VALUE;
         BufCtxBull[j] = EMPTY_VALUE; BufCtxBear[j] = EMPTY_VALUE;
         BufAlignUp[j] = EMPTY_VALUE; BufAlignDn[j] = EMPTY_VALUE;
         BufCtrlUp[j] = EMPTY_VALUE;  BufCtrlDn[j] = EMPTY_VALUE;
      }
      blankedBeyondCutoff = true;
   }

   // --- Current TF source/volume + VA-CCI ---
   double src[], vol[];
   ArrayResize(src, total);
   ArrayResize(vol, total);
   for(int i = 0; i < total; i++)
   {
      src[i] = PriceOf(open, high, low, close, i);
      vol[i] = VolWeighted ? (double)tick_volume[i] : 1.0;
   }

   double cciCTF_raw[];
   ComputeVACCI(src, vol, total, cciLen, LamC, stoch_in, stoch_len, cciCTF_raw);

   double cciCTF[];
   if(smooth > 1) ComputeMAArray(cciCTF_raw, total, smooth, smth_type, cciCTF);
   else           { ArrayResize(cciCTF, total); for(int i = 0; i < total; i++) cciCTF[i] = cciCTF_raw[i]; }

   double cciSig[];
   if(signal_len > 1) ComputeMAArray(cciCTF, total, signal_len, sig_avg_type, cciSig);
   else                { ArrayResize(cciSig, total); for(int i = 0; i < total; i++) cciSig[i] = cciCTF[i]; }

   // --- Context (higher) TF ---
   int htfPeriod = ResolveHTFPeriod(Period(), MathMax(2, htf_mult));
   bool htfInvalid = (htfPeriod <= Period());
   bool ctxActive = show_htf && !htfInvalid;

   double cciHi[];
   ArrayResize(cciHi, total);
   for(int i = 0; i < total; i++) cciHi[i] = EMPTY_VALUE;

   int htfTotal = 0;
   double htfCci[];
   if(ctxActive)
   {
      htfTotal = MathMin(iBars(NULL, htfPeriod), MaxBarsToProcess);
      if(htfTotal >= cciLen + 5)
      {
         double htfSrc[], htfVol[];
         ArrayResize(htfSrc, htfTotal);
         ArrayResize(htfVol, htfTotal);
         for(int s = 0; s < htfTotal; s++)
         {
            double o = iOpen(NULL, htfPeriod, s), h = iHigh(NULL, htfPeriod, s);
            double l = iLow(NULL, htfPeriod, s),  c = iClose(NULL, htfPeriod, s);
            switch(cciSrc)
            {
               case SRC_CLOSE: htfSrc[s] = c; break;
               case SRC_OPEN:  htfSrc[s] = o; break;
               case SRC_HIGH:  htfSrc[s] = h; break;
               case SRC_LOW:   htfSrc[s] = l; break;
               case SRC_HL2:   htfSrc[s] = (h + l) / 2.0; break;
               case SRC_OHLC4: htfSrc[s] = (o + h + l + c) / 4.0; break;
               default:        htfSrc[s] = (h + l + c) / 3.0; break;
            }
            htfVol[s] = VolWeighted ? (double)iVolume(NULL, htfPeriod, s) : 1.0;
         }
         ComputeVACCI(htfSrc, htfVol, htfTotal, cciLen, LamC, stoch_in, stoch_len, htfCci);

         for(int i = 0; i < total; i++)
         {
            int htfShift = iBarShift(NULL, htfPeriod, time[i], false);
            if(htfShift < 0) continue;
            int effShift = (htfShift == 0 && htf_update == CTX_LAST_CLOSED) ? 1 : htfShift;
            if(effShift >= 0 && effShift < htfTotal) cciHi[i] = htfCci[effShift];
         }
      }
      else ctxActive = false;
   }

   // --- Soft cap for display, direction flags on UNCAPPED values, buffers ---
   for(int i = 0; i < total; i++)
   {
      bool ctfUp = cciCTF[i] != EMPTY_VALUE && cciCTF[i] > 0;
      bool haveCtx = ctxActive && cciHi[i] != EMPTY_VALUE;
      bool htfUp = haveCtx && cciHi[i] > 0;

      double cciCTF_dsp = SoftCap(cciCTF[i]);
      double cciSig_dsp = SoftCap(cciSig[i]);
      double cciHi_dsp  = haveCtx ? SoftCap(cciHi[i]) : EMPTY_VALUE;

      BufCciBull[i] = (cciCTF[i] != EMPTY_VALUE && ctfUp)  ? cciCTF_dsp : EMPTY_VALUE;
      BufCciBear[i] = (cciCTF[i] != EMPTY_VALUE && !ctfUp) ? cciCTF_dsp : EMPTY_VALUE;
      BufSignal[i]  = (cciSig[i] != EMPTY_VALUE) ? cciSig_dsp : EMPTY_VALUE;

      BufCtxBull[i] = (haveCtx && htfUp)  ? cciHi_dsp : EMPTY_VALUE;
      BufCtxBear[i] = (haveCtx && !htfUp) ? cciHi_dsp : EMPTY_VALUE;

      bool alignedUp   = haveCtx && ctfUp && htfUp;
      bool alignedDown = haveCtx && !ctfUp && !htfUp;
      BufAlignUp[i] = (show_align && alignedUp)   ? (ctrl_up * 1.3) : EMPTY_VALUE;
      BufAlignDn[i] = (show_align && alignedDown) ? (ctrl_dn * 1.3) : EMPTY_VALUE;

      BufCtrlUp[i] = ctrl_up;
      BufCtrlDn[i] = ctrl_dn;
   }

   // --- Alerts: based on the uncapped Current-TF CCI, gated to a confirmed, just-closed bar (shift 1) ---
   if((EnableAlerts || EnablePush) && prev_calculated > 0 && total > 3)
   {
      static datetime lastAlertTime = 0;
      if(time[1] != lastAlertTime && cciCTF[1] != EMPTY_VALUE && cciCTF[2] != EMPTY_VALUE)
      {
         lastAlertTime = time[1];
         bool crossUp0  = cciCTF[2] <= 0 && cciCTF[1] > 0;
         bool crossDn0  = cciCTF[2] >= 0 && cciCTF[1] < 0;
         bool crossUpCL = cciCTF[2] <= ctrl_up && cciCTF[1] > ctrl_up;
         bool crossDnCL = cciCTF[2] >= ctrl_dn && cciCTF[1] < ctrl_dn;

         if(crossUp0)
         {
            string m = "RedK VA-CCI crossed ABOVE the zero line (bullish) on " + Symbol();
            if(EnableAlerts) Alert(m);
            if(EnablePush)   SendNotification(m);
         }
         if(crossDn0)
         {
            string m2 = "RedK VA-CCI crossed BELOW the zero line (bearish) on " + Symbol();
            if(EnableAlerts) Alert(m2);
            if(EnablePush)   SendNotification(m2);
         }
         if(crossUpCL)
         {
            string m3 = "RedK VA-CCI crossed ABOVE the Upper Control Level on " + Symbol();
            if(EnableAlerts) Alert(m3);
            if(EnablePush)   SendNotification(m3);
         }
         if(crossDnCL)
         {
            string m4 = "RedK VA-CCI crossed BELOW the Lower Control Level on " + Symbol();
            if(EnableAlerts) Alert(m4);
            if(EnablePush)   SendNotification(m4);
         }
      }
   }

   if(DebugComment)
   {
      string status = ctxActive ? "resolved to period " + IntegerToString(htfPeriod) + " (target was " +
                       IntegerToString(Period() * MathMax(2, htf_mult)) + " min)" : "inactive/invalid";
      Comment("RedK VA-CCI -- Context TF: ", status);
   }
   else Comment("");

   return(rates_total);
}
//+------------------------------------------------------------------+
