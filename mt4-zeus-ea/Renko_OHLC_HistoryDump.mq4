//+------------------------------------------------------------------+
//| Renko_OHLC_HistoryDump.mq4                                       |
//|                                                                  |
//| One-time SCRIPT: dumps the REAL offline Renko chart's own Open/  |
//| High/Low/Close history directly from its bar arrays -- NOT         |
//| reconstructed from M1 closes the way every Python backtest in    |
//| this project has used so far (renko_generator.py's bricks are    |
//| wickless by construction: Open always equals the prior brick's   |
//| Close exactly, with no reversal-brick doubling).                 |
//|                                                                  |
//| This dump captures the chart's TRUE wicks and true reversal-     |
//| brick doubling (the first brick in a new direction after a run   |
//| genuinely covers 2x the normal distance), since it reads directly |
//| from the real tick-built offline chart MT4 maintains -- exactly  |
//| what a wick-dependent strategy (e.g. RenkoWickReversal.mq4) needs |
//| to be backtested honestly.                                       |
//|                                                                  |
//| MUST be run on the SAME offline Renko chart the live EA and all  |
//| the other indicators in this project use.                        |
//|                                                                  |
//| Only confirmed/closed bricks are dumped (shift 1 through Bars-1) |
//| -- shift 0 is the live/still-forming brick on this chart and is  |
//| deliberately excluded, same convention used everywhere else in   |
//| this project (its Open/High/Low/Close are still changing).       |
//+------------------------------------------------------------------+
#property strict
#property show_inputs

input string OutputFileName = "renko_ohlc_history.csv";

void OnStart()
{
   int total = Bars;
   if(total < 3)
   {
      Alert("Renko OHLC dump: this chart has almost no bars loaded. Run on the full offline Renko history chart.");
      return;
   }

   int h = FileOpen(OutputFileName, FILE_WRITE | FILE_CSV | FILE_COMMON, ';');
   if(h == INVALID_HANDLE)
   {
      Alert("Renko OHLC dump: could not open output file, err=", GetLastError());
      return;
   }

   FileWrite(h, "timestamp;open;high;low;close");

   int written = 0;
   // shift 0 excluded -- still forming/live on this chart, not a closed brick
   for(int i = total - 1; i >= 1; i--)
   {
      string line = TimeToStr(Time[i], TIME_DATE | TIME_MINUTES) + ";" +
                    DoubleToStr(Open[i],  Digits) + ";" +
                    DoubleToStr(High[i],  Digits) + ";" +
                    DoubleToStr(Low[i],   Digits) + ";" +
                    DoubleToStr(Close[i], Digits);
      FileWrite(h, line);
      written++;

      if(written % 500 == 0)
         Comment("Renko OHLC dump running... ", written, " written, ", (total - i), "/", total, " bars scanned.");
   }

   FileClose(h);
   Comment("");

   string fullPath = TerminalInfoString(TERMINAL_COMMONDATA_PATH) + "\\Files\\" + OutputFileName;
   string msg = StringFormat("Renko OHLC dump complete: %d confirmed bricks written (shift 0, the live/forming brick, excluded).\n\nFull file path (copy this):\n%s",
                              written, fullPath);
   Alert(msg);
   Print("EA: ", msg);
}
//+------------------------------------------------------------------+
