//+------------------------------------------------------------------+
//| Jerk_Probe.mq4                                                   |
//|                                                                  |
//| Diagnostic only -- NOT part of the live strategy. Finds the      |
//| correct integer values for Jerk Indicator's two enum inputs      |
//| (Signal Polarity Criterion, Select Price Data) by calling        |
//| iCustom() with adjustable guesses and printing the result, so it |
//| can be compared against the real Jerk Indicator's own displayed  |
//| value at the same bar -- no recompiling needed to try a new      |
//| guess, just change the inputs and hit OK.                        |
//|                                                                  |
//| How to use:                                                      |
//|  1. Attach the real "Jerk Indicator" to this chart (as you       |
//|     already have) so you can read its live corner value.         |
//|  2. Attach this probe to the SAME chart.                         |
//|  3. Compare the "iCustom result" line in the comment box against |
//|     the real indicator's own displayed value.                    |
//|  4. If they don't match, open this probe's Inputs and try        |
//|     PolarityGuess / PriceGuess = 0, 1, 2, 3... until they do.    |
//|  5. Report back the winning combination.                         |
//+------------------------------------------------------------------+
#property strict
#property indicator_chart_window
#property indicator_buffers 1

input int PolarityGuess = 0;   // guess for "Signal Polarity Criterion" (currently set to Jerk_Acceleration on the real indicator)
input int PriceGuess    = 0;   // guess for "Select Price Data" (currently set to Bar_Close on the real indicator)
input int LPD_Period    = 32;  // matches the real indicator's LPD Period input exactly
input int BufferIndex   = 5;   // the only colored buffer (DeepSkyBlue) -- best guess for "the one line"
input int ShiftToRead   = 0;   // 0 = compare against the indicator's own live corner value; switch to 1 once confirmed, to match this project's "last closed bar" convention

double DummyBuf[];

int OnInit()
{
   SetIndexBuffer(0, DummyBuf);
   SetIndexStyle(0, DRAW_NONE);
   return(INIT_SUCCEEDED);
}

void OnDeinit(const datetime &reason[])
{
   Comment("");
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
   double val = iCustom(NULL, 0, "Jerk Indicator", PolarityGuess, PriceGuess, LPD_Period, BufferIndex, ShiftToRead);

   string txt = "JERK PROBE (diagnostic only)\n"
              + "polarity=" + IntegerToString(PolarityGuess)
              + "  price=" + IntegerToString(PriceGuess)
              + "  period=" + IntegerToString(LPD_Period)
              + "  buffer=" + IntegerToString(BufferIndex)
              + "  shift=" + IntegerToString(ShiftToRead) + "\n"
              + "iCustom result = "
              + (val == EMPTY_VALUE ? "EMPTY_VALUE (wrong buffer or inputs)" : DoubleToStr(val, 4)) + "\n"
              + "Compare this number to the real 'Jerk Indicator' window's own\n"
              + "corner value at the SAME moment. If they don't match, change\n"
              + "PolarityGuess / PriceGuess in this indicator's Inputs tab (try\n"
              + "0, 1, 2, 3...) and hit OK -- no recompile needed.";
   Comment(txt);

   return(rates_total);
}
//+------------------------------------------------------------------+
