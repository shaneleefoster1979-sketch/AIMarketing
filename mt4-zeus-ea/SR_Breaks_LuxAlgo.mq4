//+------------------------------------------------------------------+
//| SR_Breaks_LuxAlgo.mq4                                            |
//|                                                                  |
//| MQL4 port of "Support and Resistance Levels with Breaks"         |
//| (c) LuxAlgo -- original Pine Script v4, licensed under           |
//| Attribution-NonCommercial-ShareAlike 4.0 International           |
//| (CC BY-NC-SA 4.0): https://creativecommons.org/licenses/by-nc-sa/4.0/
//| Ported logic only, for personal (non-commercial) use. Keep this  |
//| header and attribution intact if you share or modify this file,  |
//| per the ShareAlike term of the original license.                 |
//|                                                                  |
//| Differences from the original Pine Script, both deliberate:      |
//|  1. MQL4 has no built-in pivothigh/pivotlow/fixnan -- the pivot  |
//|     scan and forward-fill are implemented directly below, and    |
//|     each level is drawn starting at its TRUE pivot bar (same     |
//|     visual result as Pine's offset=-(rightBars+1), computed      |
//|     directly instead of via a plot offset).                      |
//|  2. Break/alert conditions evaluate shift 1 (the last FULLY      |
//|     CLOSED bar), never shift 0. On an offline/Renko-style chart  |
//|     the current bar can still be live/forming, so decisions here |
//|     intentionally never touch it -- same convention the rest of  |
//|     this project's indicators and EA use.                        |
//+------------------------------------------------------------------+
#property strict
#property indicator_chart_window
#property indicator_buffers 6
#property indicator_plots   6

#property indicator_label1  "Resistance"
#property indicator_type1   DRAW_LINE
#property indicator_color1  clrRed
#property indicator_style1  STYLE_SOLID
#property indicator_width1  3

#property indicator_label2  "Support"
#property indicator_type2   DRAW_LINE
#property indicator_color2  clrBlue
#property indicator_style2  STYLE_SOLID
#property indicator_width2  3

#property indicator_label3  "Break Down"
#property indicator_type3   DRAW_ARROW
#property indicator_color3  clrRed
#property indicator_width3  2

#property indicator_label4  "Break Up"
#property indicator_type4   DRAW_ARROW
#property indicator_color4  clrLimeGreen
#property indicator_width4  2

#property indicator_label5  "Bull Wick"
#property indicator_type5   DRAW_ARROW
#property indicator_color5  clrLimeGreen
#property indicator_width5  1

#property indicator_label6  "Bear Wick"
#property indicator_type6   DRAW_ARROW
#property indicator_color6  clrRed
#property indicator_width6  1

input bool   ToggleBreaks   = true;
input int    LeftBars       = 15;
input int    RightBars      = 15;
input double VolumeThresh   = 20.0;  // percent, matches the original "Volume Threshold"
input bool   EnableAlerts   = false;
input bool   EnablePush     = false;

double BufResistance[];
double BufSupport[];
double BufBreakDown[];
double BufBreakUp[];
double BufBullWick[];
double BufBearWick[];

int OnInit()
{
   SetIndexBuffer(0, BufResistance);
   SetIndexBuffer(1, BufSupport);
   SetIndexBuffer(2, BufBreakDown);
   SetIndexBuffer(3, BufBreakUp);
   SetIndexBuffer(4, BufBullWick);
   SetIndexBuffer(5, BufBearWick);
   for(int b = 0; b < 6; b++) SetIndexEmptyValue(b, EMPTY_VALUE);

   SetIndexArrow(2, 234); // down label  - "B" breakdown
   SetIndexArrow(3, 233); // up label    - "B" breakout
   SetIndexArrow(4, 217); // small up    - bull wick break
   SetIndexArrow(5, 218); // small down  - bear wick break

   IndicatorShortName("S/R Breaks [LuxAlgo port]");
   return(INIT_SUCCEEDED);
}

// EMA of tick Volume[], computed walking oldest->newest (MQL4 series index 0
// = newest), seeded with a simple average over the first `period` bars.
void ComputeVolumeEMA(int period, int total, double &out[])
{
   ArrayResize(out, total);
   for(int i = 0; i < total; i++) out[i] = EMPTY_VALUE;
   int seedStart = total - 1;
   if(seedStart < period - 1) return;

   double seed = 0;
   for(int k = seedStart; k > seedStart - period; k--) seed += (double)Volume[k];
   seed /= period;
   out[seedStart - period + 1] = seed;

   double alpha = 2.0 / (period + 1.0);
   for(int i = seedStart - period; i >= 0; i--)
      out[i] = out[i + 1] + alpha * ((double)Volume[i] - out[i + 1]);
}

bool IsPivotHigh(int i, int total)
{
   if(i - RightBars < 0 || i + LeftBars >= total) return false;
   double v = High[i];
   for(int k = i - RightBars; k < i; k++) if(High[k] > v) return false;
   for(int k = i + 1; k <= i + LeftBars; k++) if(High[k] > v) return false;
   return true;
}

bool IsPivotLow(int i, int total)
{
   if(i - RightBars < 0 || i + LeftBars >= total) return false;
   double v = Low[i];
   for(int k = i - RightBars; k < i; k++) if(Low[k] < v) return false;
   for(int k = i + 1; k <= i + LeftBars; k++) if(Low[k] < v) return false;
   return true;
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
   int minBars = LeftBars + RightBars + 15;
   if(rates_total < minBars) return(0);
   int total = rates_total;

   double emaShort[]; double emaLong[];
   ComputeVolumeEMA(5, total, emaShort);
   ComputeVolumeEMA(10, total, emaLong);

   int start = total - RightBars - LeftBars - 2;
   if(start < 1) start = 1;

   // Pass 1: pivot scan + forward-fill ("fixnan"), oldest -> newest so each
   // new pivot naturally supersedes the previous one going forward in time.
   double curRes = EMPTY_VALUE;
   double curSup = EMPTY_VALUE;
   for(int i = start; i >= 0; i--)
   {
      if(IsPivotHigh(i, total)) curRes = High[i];
      if(IsPivotLow(i, total))  curSup = Low[i];
      BufResistance[i] = curRes;
      BufSupport[i]    = curSup;
   }

   // Pass 2: breaks, evaluated on shift 1 (last fully closed bar) only.
   // i+1 ("previous" relative to i) must have a valid level and close to
   // test a genuine cross -- never signals off shift 0 (still forming).
   for(int i = start; i >= 1; i--)
   {
      BufBreakDown[i] = EMPTY_VALUE;
      BufBreakUp[i]   = EMPTY_VALUE;
      BufBullWick[i]  = EMPTY_VALUE;
      BufBearWick[i]  = EMPTY_VALUE;
      if(!ToggleBreaks) continue;
      if(BufResistance[i] == EMPTY_VALUE || BufSupport[i] == EMPTY_VALUE) continue;
      if(BufResistance[i+1] == EMPTY_VALUE || BufSupport[i+1] == EMPTY_VALUE) continue;
      if(emaShort[i] == EMPTY_VALUE || emaLong[i] == EMPTY_VALUE || emaLong[i] == 0) continue;

      bool crossUnder = (Close[i] < BufSupport[i]) && (Close[i+1] >= BufSupport[i+1]);
      bool crossOver  = (Close[i] > BufResistance[i]) && (Close[i+1] <= BufResistance[i+1]);
      double osc      = 100.0 * (emaShort[i] - emaLong[i]) / emaLong[i];

      bool bearWickShape = (Open[i] - Close[i]) < (High[i] - Open[i]);
      bool bullWickShape = (Open[i] - Low[i])   > (Close[i] - Open[i]);

      if(crossUnder && !bearWickShape && osc > VolumeThresh) BufBreakDown[i] = High[i];
      if(crossOver  && !bullWickShape && osc > VolumeThresh) BufBreakUp[i]   = Low[i];
      if(crossOver  && bullWickShape)                        BufBullWick[i] = Low[i];
      if(crossUnder && bearWickShape)                        BufBearWick[i] = High[i];
   }

   if((EnableAlerts || EnablePush) && prev_calculated > 0)
   {
      static datetime lastAlertTime = 0;
      if(Time[1] != lastAlertTime)
      {
         string msg = "";
         if(BufBreakDown[1] != EMPTY_VALUE) msg = "Support Broken | " + Symbol();
         if(BufBreakUp[1]   != EMPTY_VALUE) msg = "Resistance Broken | " + Symbol();
         if(msg != "")
         {
            lastAlertTime = Time[1];
            if(EnableAlerts) Alert(msg);
            if(EnablePush)   SendNotification(msg);
         }
      }
   }

   return(rates_total);
}
//+------------------------------------------------------------------+
