//+------------------------------------------------------------------+
//| RC_HistoryDump_MultiPeriod.mq4                                   |
//|                                                                  |
//| Same one-time SCRIPT pattern as Jerk_HistoryDump_MultiPeriod.mq4, |
//| but for the Range Cycle Indicator, which has TWO buffers (blue   |
//| and maroon) instead of Jerk's one -- pulls both at SEVERAL        |
//| RC_Period values in a single pass, so the period sweep doesn't   |
//| need a separate dump run per candidate period.                   |
//|                                                                  |
//| Output: timestamp;blue_p<N>;maroon_p<N> for each period, one pair |
//| of columns per period tested.                                    |
//|                                                                  |
//| MUST be run on the SAME chart (symbol+timeframe) the live EA and |
//| the real Range Cycle Indicator use -- the offline Renko chart.   |
//|                                                                  |
//| Defaults cover the requested sweep: 96 (the indicator's own      |
//| default setting) down to 6 in steps of 10. Set any Period input  |
//| to 0 to skip it. Period8 (8) is the CURRENT live setting (changed |
//| from 7 recently) -- keep it in so the sweep includes the live    |
//| baseline for comparison.                                         |
//+------------------------------------------------------------------+
#property strict
#property show_inputs

input int    RC_Period1 = 96;
input int    RC_Period2 = 86;
input int    RC_Period3 = 76;
input int    RC_Period4 = 66;
input int    RC_Period5 = 56;
input int    RC_Period6 = 46;
input int    RC_Period7 = 36;
input int    RC_Period8 = 26;
input int    RC_Period9 = 16;
input int    RC_Period10 = 6;

input string OutputFileName = "rc_history_multiperiod.csv";

void OnStart()
{
   int periods[10];
   periods[0] = RC_Period1; periods[1] = RC_Period2; periods[2] = RC_Period3;
   periods[3] = RC_Period4; periods[4] = RC_Period5; periods[5] = RC_Period6;
   periods[6] = RC_Period7; periods[7] = RC_Period8; periods[8] = RC_Period9;
   periods[9] = RC_Period10;

   int activePeriods[10];
   int nPeriods = 0;
   for(int p = 0; p < 10; p++)
      if(periods[p] > 0)
         activePeriods[nPeriods++] = periods[p];

   if(nPeriods == 0)
   {
      Alert("RC multi-period dump: all periods are 0 -- nothing to do.");
      return;
   }

   int total = Bars;
   if(total < 2)
   {
      Alert("RC multi-period dump: this chart has almost no bars loaded. Run on the full Renko history chart.");
      return;
   }

   int h = FileOpen(OutputFileName, FILE_WRITE | FILE_CSV | FILE_COMMON, ';');
   if(h == INVALID_HANDLE)
   {
      Alert("RC multi-period dump: could not open output file, err=", GetLastError());
      return;
   }

   // Header: timestamp;blue_p96;maroon_p96;blue_p86;maroon_p86;...
   string header = "timestamp";
   for(int p = 0; p < nPeriods; p++)
      header += ";blue_p" + IntegerToString(activePeriods[p]) + ";maroon_p" + IntegerToString(activePeriods[p]);
   FileWrite(h, header);

   int written = 0;
   int skippedAll = 0; // rows where EVERY period came back EMPTY_VALUE on BOTH buffers

   for(int i = total - 1; i >= 0; i--)
   {
      double blueVals[10];
      double maroonVals[10];
      bool anyValid = false;
      for(int p = 0; p < nPeriods; p++)
      {
         blueVals[p]   = iCustom(NULL, 0, "Range Cycle Indicator", 0, 0, activePeriods[p], 1, i);
         maroonVals[p] = iCustom(NULL, 0, "Range Cycle Indicator", 0, 0, activePeriods[p], 2, i);
         if(blueVals[p] != EMPTY_VALUE || maroonVals[p] != EMPTY_VALUE) anyValid = true;
      }
      if(!anyValid)
      {
         skippedAll++;
         continue;
      }

      string line = TimeToStr(Time[i], TIME_DATE | TIME_MINUTES);
      for(int p = 0; p < nPeriods; p++)
      {
         line += ";" + (blueVals[p]   == EMPTY_VALUE ? "" : DoubleToStr(blueVals[p], 6));
         line += ";" + (maroonVals[p] == EMPTY_VALUE ? "" : DoubleToStr(maroonVals[p], 6));
      }
      FileWrite(h, line);
      written++;

      if(written % 500 == 0)
         Comment("RC multi-period dump running... ", written, " written, ",
                 skippedAll, " skipped, ", (total - i), "/", total, " bars scanned, ",
                 nPeriods, " periods per bar.");
   }

   FileClose(h);
   Comment("");

   string fullPath = TerminalInfoString(TERMINAL_COMMONDATA_PATH) + "\\Files\\" + OutputFileName;
   string periodList = "";
   for(int p = 0; p < nPeriods; p++)
      periodList += (p > 0 ? ", " : "") + IntegerToString(activePeriods[p]);
   string msg = StringFormat("RC multi-period dump complete: %d rows written across %d periods (%s), %d bars fully skipped.\n\nFull file path (copy this):\n%s",
                              written, nPeriods, periodList, skippedAll, fullPath);
   Alert(msg);
   Print("EA: ", msg);
}
//+------------------------------------------------------------------+
