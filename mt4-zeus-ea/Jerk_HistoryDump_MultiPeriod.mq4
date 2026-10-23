//+------------------------------------------------------------------+
//| Jerk_HistoryDump_MultiPeriod.mq4                                 |
//|                                                                  |
//| Same one-time SCRIPT as Jerk_HistoryDump.mq4, but pulls Jerk at  |
//| SEVERAL LPD_Period values in a single pass instead of one --     |
//| lets the LPD_Period backtest sweep run without you having to     |
//| re-run the dump separately for each candidate period.            |
//|                                                                  |
//| Output: timestamp;jerk_p<N> for each period, one column per      |
//| period tested, same semicolon-delimited shape as the single-     |
//| period version.                                                  |
//|                                                                  |
//| MUST be run on the SAME chart (symbol+timeframe) the live EA and |
//| the real Jerk Indicator use -- the offline Renko chart.          |
//|                                                                  |
//| Set any Period input to 0 to skip it. Period5 (32) is the        |
//| current live setting -- keep it in so the sweep includes the     |
//| baseline for comparison.                                         |
//+------------------------------------------------------------------+
#property strict
#property show_inputs

input string Jerk_IndicatorName     = "Jerk Indicator";
input int    Jerk_PolarityCriterion = 0;
input int    Jerk_PriceData         = 1;
input int    Jerk_Buffer            = 5;

input int    Period1 = 10;
input int    Period2 = 16;
input int    Period3 = 20;
input int    Period4 = 25;
input int    Period5 = 32;  // current live setting -- keep this one in the sweep
input int    Period6 = 45;

input string OutputFileName = "jerk_history_multiperiod.csv";

void OnStart()
{
   int periods[6];
   periods[0] = Period1; periods[1] = Period2; periods[2] = Period3;
   periods[3] = Period4; periods[4] = Period5; periods[5] = Period6;

   int activePeriods[6];
   int nPeriods = 0;
   for(int p = 0; p < 6; p++)
      if(periods[p] > 0)
         activePeriods[nPeriods++] = periods[p];

   if(nPeriods == 0)
   {
      Alert("Jerk multi-period dump: all periods are 0 -- nothing to do.");
      return;
   }

   int total = Bars;
   if(total < 2)
   {
      Alert("Jerk multi-period dump: this chart has almost no bars loaded. Run on the full Renko history chart.");
      return;
   }

   int h = FileOpen(OutputFileName, FILE_WRITE | FILE_CSV | FILE_COMMON, ';');
   if(h == INVALID_HANDLE)
   {
      Alert("Jerk multi-period dump: could not open output file, err=", GetLastError());
      return;
   }

   // Header: timestamp;jerk_p10;jerk_p16;...
   string header = "timestamp";
   for(int p = 0; p < nPeriods; p++)
      header += ";jerk_p" + IntegerToString(activePeriods[p]);
   FileWrite(h, header);

   int written = 0;
   int skippedAll = 0; // rows where EVERY period came back EMPTY_VALUE

   for(int i = total - 1; i >= 0; i--)
   {
      double vals[6];
      bool anyValid = false;
      for(int p = 0; p < nPeriods; p++)
      {
         vals[p] = iCustom(NULL, 0, Jerk_IndicatorName,
                            Jerk_PolarityCriterion, Jerk_PriceData, activePeriods[p],
                            Jerk_Buffer, i);
         if(vals[p] != EMPTY_VALUE) anyValid = true;
      }
      if(!anyValid)
      {
         skippedAll++;
         continue;
      }

      string line = TimeToStr(Time[i], TIME_DATE | TIME_MINUTES);
      for(int p = 0; p < nPeriods; p++)
         line += ";" + (vals[p] == EMPTY_VALUE ? "" : DoubleToStr(vals[p], 6));
      FileWrite(h, line);
      written++;

      if(written % 500 == 0)
         Comment("Jerk multi-period dump running... ", written, " written, ",
                 skippedAll, " skipped, ", (total - i), "/", total, " bars scanned, ",
                 nPeriods, " periods per bar.");
   }

   FileClose(h);
   Comment("");

   string fullPath = TerminalInfoString(TERMINAL_COMMONDATA_PATH) + "\\Files\\" + OutputFileName;
   string periodList = "";
   for(int p = 0; p < nPeriods; p++)
      periodList += (p > 0 ? ", " : "") + IntegerToString(activePeriods[p]);
   string msg = StringFormat("Jerk multi-period dump complete: %d rows written across %d periods (%s), %d bars fully skipped.\n\nFull file path (copy this):\n%s",
                              written, nPeriods, periodList, skippedAll, fullPath);
   Alert(msg);
   Print("EA: ", msg);
}
//+------------------------------------------------------------------+
