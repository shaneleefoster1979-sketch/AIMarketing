//+------------------------------------------------------------------+
//| Supertrend_x4_CloudFill.mq4                                      |
//|                                                                  |
//| MQL4 port of "Supertrend x4 w/ Cloud Fill" (Pine Script v5).     |
//| Original Supertrend code credit: KivancOzbilgic                  |
//| https://www.tradingview.com/script/r6dAP7yi/                     |
//|                                                                  |
//| Differences from the original, both deliberate:                  |
//|  1. The shaded "cloud" region fills (fill() between two plots)   |
//|     have NO equivalent in MQL4 indicator buffers -- there is no  |
//|     DRAW_FILLING style here (that's MQL5-only). The 4 trend      |
//|     lines and buy/sell signals are ported faithfully; the clouds |
//|     are left out rather than faked with slow per-bar rectangle   |
//|     objects. Say the word if you want that added anyway.         |
//|  2. "Change ATR Calculation Method = true" uses MT4's built-in   |
//|     iATR(), which already matches Pine's ta.atr() (same Wilder   |
//|     smoothing). "= false" is a manual SMA of True Range, same as |
//|     the original's ta.sma(ta.tr, Periods).                       |
//+------------------------------------------------------------------+
#property strict
#property indicator_chart_window
#property indicator_buffers 16
#property indicator_plots   16

#property indicator_label1  "Set1 Up"
#property indicator_type1   DRAW_LINE
#property indicator_color1  clrLimeGreen
#property indicator_width1  2
#property indicator_label2  "Set1 Down"
#property indicator_type2   DRAW_LINE
#property indicator_color2  clrBlack
#property indicator_width2  2
#property indicator_label3  "Set1 Buy"
#property indicator_type3   DRAW_ARROW
#property indicator_color3  clrLimeGreen
#property indicator_width3  2
#property indicator_label4  "Set1 Sell"
#property indicator_type4   DRAW_ARROW
#property indicator_color4  clrBlack
#property indicator_width4  2

#property indicator_label5  "Set2 Up"
#property indicator_type5   DRAW_LINE
#property indicator_color5  clrLimeGreen
#property indicator_width5  3
#property indicator_label6  "Set2 Down"
#property indicator_type6   DRAW_LINE
#property indicator_color6  clrBlack
#property indicator_width6  3
#property indicator_label7  "Set2 Buy"
#property indicator_type7   DRAW_ARROW
#property indicator_color7  clrLimeGreen
#property indicator_width7  2
#property indicator_label8  "Set2 Sell"
#property indicator_type8   DRAW_ARROW
#property indicator_color8  clrBlack
#property indicator_width8  2

#property indicator_label9  "Set3 Up"
#property indicator_type9   DRAW_LINE
#property indicator_color9  clrLimeGreen
#property indicator_width9  3
#property indicator_label10 "Set3 Down"
#property indicator_type10  DRAW_LINE
#property indicator_color10 clrBlack
#property indicator_width10 3
#property indicator_label11 "Set3 Buy"
#property indicator_type11  DRAW_ARROW
#property indicator_color11 clrLimeGreen
#property indicator_width11 2
#property indicator_label12 "Set3 Sell"
#property indicator_type12  DRAW_ARROW
#property indicator_color12 clrBlack
#property indicator_width12 2

#property indicator_label13 "Set4 Up"
#property indicator_type13  DRAW_LINE
#property indicator_color13 clrLimeGreen
#property indicator_width13 3
#property indicator_label14 "Set4 Down"
#property indicator_type14  DRAW_LINE
#property indicator_color14 clrBlack
#property indicator_width14 3
#property indicator_label15 "Set4 Buy"
#property indicator_type15  DRAW_ARROW
#property indicator_color15 clrLimeGreen
#property indicator_width15 2
#property indicator_label16 "Set4 Sell"
#property indicator_type16  DRAW_ARROW
#property indicator_color16 clrBlack
#property indicator_width16 2

input int    Set1_Period      = 10;
input double Set1_Multiplier  = 3.336;
input bool   Set1_ChangeATR   = true;

input int    Set2_Period      = 10;
input double Set2_Multiplier  = 2.636;
input bool   Set2_ChangeATR   = true;

input int    Set3_Period      = 10;
input double Set3_Multiplier  = 9.736;
input bool   Set3_ChangeATR   = true;

input int    Set4_Period      = 10;
input double Set4_Multiplier  = 8.536;
input bool   Set4_ChangeATR   = true;

input bool   EnableAlerts     = false;
input bool   EnablePush       = false;

double Buf1Up[], Buf1Dn[], Buf1Buy[], Buf1Sell[];
double Buf2Up[], Buf2Dn[], Buf2Buy[], Buf2Sell[];
double Buf3Up[], Buf3Dn[], Buf3Buy[], Buf3Sell[];
double Buf4Up[], Buf4Dn[], Buf4Buy[], Buf4Sell[];

double g_rawUp1[], g_rawDn1[], g_trend1[];
double g_rawUp2[], g_rawDn2[], g_trend2[];
double g_rawUp3[], g_rawDn3[], g_trend3[];
double g_rawUp4[], g_rawDn4[], g_trend4[];

int OnInit()
{
   SetIndexBuffer(0,  Buf1Up);   SetIndexBuffer(1,  Buf1Dn);
   SetIndexBuffer(2,  Buf1Buy);  SetIndexBuffer(3,  Buf1Sell);
   SetIndexBuffer(4,  Buf2Up);   SetIndexBuffer(5,  Buf2Dn);
   SetIndexBuffer(6,  Buf2Buy);  SetIndexBuffer(7,  Buf2Sell);
   SetIndexBuffer(8,  Buf3Up);   SetIndexBuffer(9,  Buf3Dn);
   SetIndexBuffer(10, Buf3Buy);  SetIndexBuffer(11, Buf3Sell);
   SetIndexBuffer(12, Buf4Up);   SetIndexBuffer(13, Buf4Dn);
   SetIndexBuffer(14, Buf4Buy);  SetIndexBuffer(15, Buf4Sell);
   for(int b = 0; b < 16; b++) SetIndexEmptyValue(b, EMPTY_VALUE);

   SetIndexArrow(2,  233); SetIndexArrow(3,  234); // Set1 buy/sell
   SetIndexArrow(6,  233); SetIndexArrow(7,  234); // Set2 buy/sell
   SetIndexArrow(10, 233); SetIndexArrow(11, 234); // Set3 buy/sell
   SetIndexArrow(14, 233); SetIndexArrow(15, 234); // Set4 buy/sell

   IndicatorShortName("Supertrend x4 [port]");
   return(INIT_SUCCEEDED);
}

double TrueRange(int k, int total)
{
   if(k + 1 >= total) return High[k] - Low[k];
   double prevClose = Close[k + 1];
   return MathMax(High[k] - Low[k], MathMax(MathAbs(High[k] - prevClose), MathAbs(Low[k] - prevClose)));
}

double GetATR(int i, int period, bool changeATR, int total)
{
   if(changeATR) return iATR(NULL, 0, period, i);
   if(i + period > total) return EMPTY_VALUE;
   double sum = 0;
   for(int k = i; k < i + period; k++) sum += TrueRange(k, total);
   return sum / period;
}

// Faithful port of the Pine recursive Supertrend block (up/up1/dn/dn1/trend),
// walking oldest -> newest since each bar's ratcheted stop depends on the
// previous bar's final (not raw) value -- same as every other recursive
// calculation in this project's indicators.
void ComputeSupertrend(int period, double multiplier, bool changeATR, int total, int start,
                        double &rawUp[], double &rawDn[], double &trendArr[],
                        double &bufUp[], double &bufDn[], double &bufBuy[], double &bufSell[])
{
   for(int i = start; i >= 0; i--)
   {
      double atr = GetATR(i, period, changeATR, total);
      if(atr == EMPTY_VALUE)
      {
         rawUp[i] = EMPTY_VALUE; rawDn[i] = EMPTY_VALUE; trendArr[i] = EMPTY_VALUE;
         bufUp[i] = EMPTY_VALUE; bufDn[i] = EMPTY_VALUE; bufBuy[i] = EMPTY_VALUE; bufSell[i] = EMPTY_VALUE;
         continue;
      }
      double src = (High[i] + Low[i]) / 2.0; // hl2

      double rawUpToday = src - multiplier * atr;
      double rawDnToday = src + multiplier * atr;

      bool havePrev = (i + 1 < total && rawUp[i + 1] != EMPTY_VALUE);
      double up1 = havePrev ? rawUp[i + 1] : rawUpToday;         // nz(up[1], up)
      double dn1 = havePrev ? rawDn[i + 1] : rawDnToday;         // nz(dn[1], dn)

      double finalUp = (havePrev && Close[i + 1] > up1) ? MathMax(rawUpToday, up1) : rawUpToday;
      double finalDn = (havePrev && Close[i + 1] < dn1) ? MathMin(rawDnToday, dn1) : rawDnToday;

      rawUp[i] = finalUp;
      rawDn[i] = finalDn;

      double prevTrend = (havePrev && trendArr[i + 1] != EMPTY_VALUE) ? trendArr[i + 1] : 1;
      double curTrend;
      if(prevTrend == -1 && Close[i] > dn1)      curTrend = 1;
      else if(prevTrend == 1 && Close[i] < up1)  curTrend = -1;
      else                                        curTrend = prevTrend;
      trendArr[i] = curTrend;

      bufUp[i] = (curTrend == 1) ? finalUp : EMPTY_VALUE;
      bufDn[i] = (curTrend == 1) ? EMPTY_VALUE : finalDn;

      bufBuy[i]  = (curTrend == 1  && prevTrend == -1) ? finalUp : EMPTY_VALUE;
      bufSell[i] = (curTrend == -1 && prevTrend == 1)  ? finalDn : EMPTY_VALUE;
   }
}

void CheckAlerts(string tag, double &trendArr[], double &bufBuy[], double &bufSell[], datetime &lastAlertTime)
{
   if(!(EnableAlerts || EnablePush)) return;
   if(Time[1] == lastAlertTime) return;
   string msg = "";
   if(bufBuy[1]  != EMPTY_VALUE) msg = tag + " SuperTrend Long | " + Symbol();
   if(bufSell[1] != EMPTY_VALUE) msg = tag + " SuperTrend Short | " + Symbol();
   if(trendArr[1] != EMPTY_VALUE && trendArr[2] != EMPTY_VALUE && trendArr[1] != trendArr[2] && msg == "")
      msg = tag + " SuperTrend direction change | " + Symbol();
   if(msg != "")
   {
      lastAlertTime = Time[1];
      if(EnableAlerts) Alert(msg);
      if(EnablePush)   SendNotification(msg);
   }
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
   int maxPeriod = MathMax(MathMax(Set1_Period, Set2_Period), MathMax(Set3_Period, Set4_Period));
   if(rates_total < maxPeriod * 3 + 10) return(0);
   int total = rates_total;

   ArrayResize(g_rawUp1, total); ArrayResize(g_rawDn1, total); ArrayResize(g_trend1, total);
   ArrayResize(g_rawUp2, total); ArrayResize(g_rawDn2, total); ArrayResize(g_trend2, total);
   ArrayResize(g_rawUp3, total); ArrayResize(g_rawDn3, total); ArrayResize(g_trend3, total);
   ArrayResize(g_rawUp4, total); ArrayResize(g_rawDn4, total); ArrayResize(g_trend4, total);

   int start = total - 1; // full recompute: the ratchet/trend state is cheap per bar and this guarantees correctness

   ComputeSupertrend(Set1_Period, Set1_Multiplier, Set1_ChangeATR, total, start,
                      g_rawUp1, g_rawDn1, g_trend1, Buf1Up, Buf1Dn, Buf1Buy, Buf1Sell);
   ComputeSupertrend(Set2_Period, Set2_Multiplier, Set2_ChangeATR, total, start,
                      g_rawUp2, g_rawDn2, g_trend2, Buf2Up, Buf2Dn, Buf2Buy, Buf2Sell);
   ComputeSupertrend(Set3_Period, Set3_Multiplier, Set3_ChangeATR, total, start,
                      g_rawUp3, g_rawDn3, g_trend3, Buf3Up, Buf3Dn, Buf3Buy, Buf3Sell);
   ComputeSupertrend(Set4_Period, Set4_Multiplier, Set4_ChangeATR, total, start,
                      g_rawUp4, g_rawDn4, g_trend4, Buf4Up, Buf4Dn, Buf4Buy, Buf4Sell);

   if(prev_calculated > 0 && total > 2)
   {
      static datetime lastAlert1 = 0, lastAlert2 = 0, lastAlert3 = 0, lastAlert4 = 0;
      CheckAlerts("Set1 (ST)", g_trend1, Buf1Buy, Buf1Sell, lastAlert1);
      CheckAlerts("Set2 (ST)", g_trend2, Buf2Buy, Buf2Sell, lastAlert2);
      CheckAlerts("Set3 (LT)", g_trend3, Buf3Buy, Buf3Sell, lastAlert3);
      CheckAlerts("Set4 (LT)", g_trend4, Buf4Buy, Buf4Sell, lastAlert4);
   }

   return(rates_total);
}
//+------------------------------------------------------------------+
