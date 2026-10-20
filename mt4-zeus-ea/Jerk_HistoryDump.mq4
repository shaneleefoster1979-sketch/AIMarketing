//+------------------------------------------------------------------+
//| Jerk_HistoryDump.mq4                                             |
//|                                                                  |
//| One-time SCRIPT (not an indicator/EA -- drag onto the chart,     |
//| it runs once and finishes). Walks the ENTIRE bar history         |
//| currently loaded on this chart and dumps iCustom()-read Jerk     |
//| values to a CSV, same semicolon-delimited timestamp;value shape  |
//| rc_history.csv already uses, so it can be loaded by the same     |
//| kind of pandas pipeline (merge_asof backward onto the Renko      |
//| brick series).                                                   |
//|                                                                  |
//| MUST be run on the SAME chart (symbol+timeframe) the live EA and |
//| the real Jerk Indicator use -- the offline Renko chart, not the  |
//| underlying M1 chart. iCustom(NULL, 0, ...) means "this chart."   |
//|                                                                  |
//| Parameters below default to the values already confirmed via     |
//| Jerk_Probe.mq4 against the live indicator's own displayed value. |
//+------------------------------------------------------------------+
#property strict
#property show_inputs

input string Jerk_IndicatorName     = "Jerk Indicator"; // include a subfolder prefix here if the .ex4 is not directly in MQL4/Indicators
input int    Jerk_PolarityCriterion = 0;
input int    Jerk_PriceData         = 1;
input int    Jerk_LPD_Period        = 32;
input int    Jerk_Buffer            = 5;
input string OutputFileName         = "jerk_history.csv"; // written to the Common Files folder -- the completion alert prints the exact full path

void OnStart()
{
   int total = Bars;
   if(total < 2)
   {
      Alert("Jerk history dump: this chart has almost no bars loaded. Run on the full Renko history chart.");
      return;
   }

   int h = FileOpen(OutputFileName, FILE_WRITE | FILE_CSV | FILE_COMMON, ';');
   if(h == INVALID_HANDLE)
   {
      Alert("Jerk history dump: could not open output file, err=", GetLastError());
      return;
   }
   FileWrite(h, "timestamp", "jerk");

   int written = 0;
   int skipped = 0;

   // Oldest -> newest, so the CSV reads chronologically like rc_history.csv.
   for(int i = total - 1; i >= 0; i--)
   {
      double val = iCustom(NULL, 0, Jerk_IndicatorName,
                            Jerk_PolarityCriterion, Jerk_PriceData, Jerk_LPD_Period,
                            Jerk_Buffer, i);
      if(val == EMPTY_VALUE)
      {
         skipped++;
         continue;
      }
      FileWrite(h, TimeToStr(Time[i], TIME_DATE | TIME_MINUTES), DoubleToStr(val, 6));
      written++;

      if(written % 1000 == 0)
         Comment("Jerk history dump running... ", written, " written, ", skipped,
                 " skipped, ", (total - i), "/", total, " bars scanned.");
   }

   FileClose(h);
   Comment("");

   // MQL4 scripts can't write outside the terminal's own Files/ or the
   // shared Common\Files\ sandbox -- there's no direct-to-Desktop option
   // without raw WinAPI/DLL calls. TerminalInfoString() gives the real,
   // full OS path instead, so there's nothing to hunt for: copy it,
   // Windows+R, paste, Enter, Explorer opens straight to the file.
   string fullPath = TerminalInfoString(TERMINAL_COMMONDATA_PATH) + "\\Files\\" + OutputFileName;
   string msg = StringFormat("Jerk history dump complete: %d rows written, %d bars skipped (no Jerk value yet).\n\nFull file path (copy this):\n%s",
                              written, skipped, fullPath);
   Alert(msg);
   Print("EA: ", msg);
}
//+------------------------------------------------------------------+
