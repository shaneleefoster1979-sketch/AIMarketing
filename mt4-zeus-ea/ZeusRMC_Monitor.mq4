//+------------------------------------------------------------------+
//| ZeusRMC_Monitor.mq4                                              |
//|                                                                  |
//| Plots EXACTLY what ZeusAI.mq4's internal RMC port computes --    |
//| same formula (GetBrickRun/EstimateCycleLength/MomentumDecay/     |
//| CalcRMC), same default inputs, same shift-1 ("last fully closed  |
//| brick") read Zeus itself uses for every entry/exit decision.     |
//|                                                                  |
//| Purpose: remove the third-party Renko_Momentum_Cycle.mq4 as a    |
//| middleman entirely. Hover shift 1 on this indicator and you are  |
//| reading precisely the number Zeus used on its last decision --   |
//| no separate program, no possible divergence, no guessing which   |
//| bar is "the one that triggered it."                              |
//|                                                                  |
//| Shift 0 (the current, right-most bar) is intentionally left      |
//| UNPLOTTED -- on this chart it is a live, still-forming brick,    |
//| not a finished one, and Zeus never reads it for a decision.      |
//| A gap at the current bar is correct, not a bug.                  |
//+------------------------------------------------------------------+
#property strict
#property indicator_separate_window
#property indicator_buffers 2
#property indicator_plots   2
#property indicator_minimum -1.1
#property indicator_maximum  1.1

#property indicator_label1  "Zeus RMC Bull"
#property indicator_type1   DRAW_LINE
#property indicator_color1  clrMediumTurquoise
#property indicator_style1  STYLE_SOLID
#property indicator_width1  2

#property indicator_label2  "Zeus RMC Bear"
#property indicator_type2   DRAW_LINE
#property indicator_color2  clrTomato
#property indicator_style2  STYLE_SOLID
#property indicator_width2  2

// Same names/defaults as ZeusAI.mq4's inputs -- keep these in sync if you
// ever change the EA's settings, so this indicator keeps matching it exactly.
input int    RMC_MinRunLength   = 2;
input int    RMC_MaxRunLookback = 10;
input int    RMC_RSI_MinPeriod  = 7;
input int    RMC_RSI_MaxPeriod  = 21;
input int    RMC_CycleMemory    = 5;
input bool   ShowLastDecisionComment = true; // on-chart text of the exact shift-1 reading

double BufBull[];
double BufBear[];

int OnInit()
{
   SetIndexBuffer(0, BufBull);
   SetIndexBuffer(1, BufBear);
   SetIndexEmptyValue(0, EMPTY_VALUE);
   SetIndexEmptyValue(1, EMPTY_VALUE);
   IndicatorShortName("Zeus RMC [matches EA internal read]");
   IndicatorDigits(4);
   return(INIT_SUCCEEDED);
}

void OnDeinit(const datetime &reason[])
{
   if(ShowLastDecisionComment) Comment("");
}

// --- Ported directly from ZeusAI.mq4's RMC_GetBrickRun/RMC_EstimateCycleLength/
// RMC_GetMomentumDecay -- same formula, same variable names minus the prefix.
int GetBrickRun(int i, int total, double &runVol)
{
   if(i >= total) return 0;
   bool isUp = (Close[i] > Open[i]);
   int  count = 0;
   runVol = 0;
   for(int k = i; k < total && count < RMC_MaxRunLookback; k++)
   {
      bool kUp = (Close[k] > Open[k]);
      if(kUp != isUp) break;
      count++;
      runVol += (double)Volume[k];
   }
   return isUp ? count : -count;
}

int EstimateCycleLength(int i, int total)
{
   int  runCount = 0;
   int  totalLen = 0;
   int  k        = i;
   bool lastDir  = (Close[i] > Open[i]);
   int  runLen   = 0;
   while(k < total && runCount < RMC_CycleMemory * 2)
   {
      bool kUp = (Close[k] > Open[k]);
      if(kUp == lastDir) { runLen++; }
      else
      {
         if(runLen >= RMC_MinRunLength) { totalLen += runLen; runCount++; }
         lastDir = kUp; runLen = 1;
      }
      k++;
   }
   if(runCount == 0) return (RMC_RSI_MinPeriod + RMC_RSI_MaxPeriod) / 2;
   double avgRun = (double)totalLen / runCount;
   int    cycle  = (int)MathRound(avgRun * 2);
   if(cycle < RMC_RSI_MinPeriod) cycle = RMC_RSI_MinPeriod;
   if(cycle > RMC_RSI_MaxPeriod) cycle = RMC_RSI_MaxPeriod;
   return cycle;
}

double GetMomentumDecay(int i, int total)
{
   if(i >= total) return 1.0;
   bool   curDir  = (Close[i] > Open[i]);
   double curVol  = 0;
   int    curLen  = 0;
   for(int k = i; k < total; k++)
   {
      if((Close[k] > Open[k]) != curDir) break;
      curLen++; curVol += (double)Volume[k];
   }
   int  k2     = i + curLen;
   bool oppDir = !curDir;
   while(k2 < total && (Close[k2] > Open[k2]) == oppDir) k2++;
   double prevVol = 0;
   int    prevLen = 0;
   for(int k = k2; k < total; k++)
   {
      if((Close[k] > Open[k]) != curDir) break;
      prevLen++; prevVol += (double)Volume[k];
   }
   if(prevLen == 0 || prevVol == 0) return 1.0;
   double lenRatio = (double)curLen / prevLen;
   double volRatio = (curVol / curLen) / (prevVol / prevLen);
   return MathMin(lenRatio * 0.5 + volRatio * 0.5, 1.5);
}

// Returns EMPTY_VALUE, run, rsiPeriod and decay via out-params so the
// on-chart comment can show the same diagnostic fields Zeus's own
// ZEUS-FILTER[PORT] log line prints.
double CalcRMC(int i, int total, int &outRun, int &outRsiPeriod, double &outDecay)
{
   outRun = 0; outRsiPeriod = 0; outDecay = 1.0;
   if(i + RMC_RSI_MaxPeriod * 3 >= total) return(EMPTY_VALUE);
   double runVol = 0;
   int    run    = GetBrickRun(i, total, runVol);
   outRun = run;
   if(MathAbs(run) < RMC_MinRunLength) return(EMPTY_VALUE);
   int    rsiPeriod = EstimateCycleLength(i, total);
   outRsiPeriod = rsiPeriod;
   double rsi       = iRSI(NULL, 0, rsiPeriod, PRICE_CLOSE, i);
   if(rsi == EMPTY_VALUE) return(EMPTY_VALUE);
   double rsiNorm   = (rsi - 50.0) / 50.0;
   double decay     = GetMomentumDecay(i, total);
   outDecay = decay;
   double runStrength = MathMin(MathAbs(run), RMC_MaxRunLookback);
   double runNorm      = runStrength / RMC_MaxRunLookback;
   if(run < 0) runNorm = -runNorm;
   double avgVol = 0; int vCnt = 0;
   for(int k = i; k < i + rsiPeriod && k < total; k++)
      { avgVol += (double)Volume[k]; vCnt++; }
   if(vCnt > 0) avgVol /= vCnt;
   double volNorm = (avgVol > 0 && MathAbs(run) > 0)
                    ? MathMin((runVol / MathAbs(run)) / avgVol, 2.0) : 1.0;
   volNorm = (volNorm - 1.0) * 0.3 + 1.0;
   double rmc = (rsiNorm * 0.5 + runNorm * 0.35 + (volNorm - 1.0) * 0.15)
                * MathMin(decay, 1.0);
   return MathMax(-1.0, MathMin(1.0, rmc));
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
   int minBars = RMC_RSI_MaxPeriod * 4 + RMC_CycleMemory * RMC_MaxRunLookback * 2 + 10;
   if(rates_total < minBars) return(0);

   int total = rates_total;

   int start;
   if(prev_calculated <= 0) start = total - RMC_RSI_MaxPeriod * 3 - 2;
   else start = prev_calculated - 1;
   if(start >= total) start = total - 1;
   if(start < 0) start = 0;

   // Shift 0 (the live, still-forming brick on this chart) is deliberately
   // left EMPTY_VALUE / unplotted -- Zeus never reads it for a decision, and
   // plotting a value there would misleadingly suggest it's a finished read.
   BufBull[0] = EMPTY_VALUE;
   BufBear[0] = EMPTY_VALUE;

   int dummyRun; int dummyRsi; double dummyDecay;
   for(int i = MathMax(start, 1); i >= 1; i--)
   {
      BufBull[i] = EMPTY_VALUE;
      BufBear[i] = EMPTY_VALUE;
      double rmc = CalcRMC(i, total, dummyRun, dummyRsi, dummyDecay);
      if(rmc == EMPTY_VALUE) continue;
      if(rmc >= 0) BufBull[i] = rmc;
      else         BufBear[i] = rmc;
   }

   if(ShowLastDecisionComment)
   {
      int    run; int rsiPeriod; double decay;
      double rmc1 = CalcRMC(1, total, run, rsiPeriod, decay);
      string txt = "ZEUS RMC [shift 1 -- last closed brick, matches EA's last decision]\n"
                 + "time=" + TimeToStr(Time[1], TIME_DATE|TIME_MINUTES)
                 + "  O=" + DoubleToStr(Open[1], Digits) + "  C=" + DoubleToStr(Close[1], Digits) + "\n"
                 + "rmc=" + (rmc1 == EMPTY_VALUE ? "EMPTY (no qualifying run yet)" : DoubleToStr(rmc1, 4))
                 + "  run=" + IntegerToString(run)
                 + "  rsiPeriod=" + IntegerToString(rsiPeriod)
                 + "  decay=" + DoubleToStr(decay, 4) + "\n"
                 + "shift 0 (current brick, O=" + DoubleToStr(Open[0], Digits)
                 + ") is still forming -- not evaluated, not plotted.";
      Comment(txt);
   }

   return(rates_total);
}
//+------------------------------------------------------------------+
