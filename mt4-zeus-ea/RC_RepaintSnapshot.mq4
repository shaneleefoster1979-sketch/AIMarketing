//+------------------------------------------------------------------+
//| RC_RepaintSnapshot.mq4                                           |
//|                                                                  |
//| One-time SCRIPT, meant to be run REPEATEDLY over time (once now, |
//| then again in a few hours, again tomorrow, again in a few days,  |
//| etc.) to directly test whether -- and how much -- the Range      |
//| Cycle Indicator repaints, at BOTH the current live period (8) and |
//| the hypothesized-less-repainting period (96), side by side.      |
//|                                                                  |
//| Each run dumps the last RecentBars closed bricks' blue/maroon     |
//| readings at both periods to a NEW, timestamped file -- it never  |
//| overwrites a previous run, so you build up a time series of      |
//| snapshots just by re-running this periodically. A companion      |
//| Python script (rc_repaint_diff.py) then compares every pair of    |
//| snapshots and reports exactly which bars' readings changed       |
//| between runs, for each period separately.                        |
//|                                                                  |
//| Only the last RecentBars bars are dumped (default 2000) -- this   |
//| tool is about catching repaints on RECENT bars that could still   |
//| plausibly be revised, not re-dumping the whole multi-year history |
//| every single run.                                                 |
//|                                                                  |
//| MUST be run on the SAME offline Renko chart the live EA uses.    |
//+------------------------------------------------------------------+
#property strict
#property show_inputs

input int RecentBars    = 2000;
input int PeriodA       = 8;   // current live RC_Period
input int PeriodB       = 96;  // the hypothesized-less-repainting secondary period

void OnStart()
{
   int total = Bars;
   if(total < 3)
   {
      Alert("RC repaint snapshot: this chart has almost no bars loaded. Run on the full offline Renko history chart.");
      return;
   }

   int n = MathMin(RecentBars, total - 1);

   datetime now = TimeCurrent();
   string fileName = StringFormat("rc_repaint_snapshot_%s.csv", TimeToStr(now, TIME_DATE | TIME_SECONDS));
   // Replace characters FileOpen won't accept in a filename.
   StringReplace(fileName, ".", "");
   StringReplace(fileName, ":", "");
   StringReplace(fileName, " ", "_");

   int h = FileOpen(fileName, FILE_WRITE | FILE_CSV | FILE_COMMON, ';');
   if(h == INVALID_HANDLE)
   {
      Alert("RC repaint snapshot: could not open output file, err=", GetLastError());
      return;
   }

   FileWrite(h, StringFormat("snapshot_taken_at;%s", TimeToStr(now, TIME_DATE | TIME_SECONDS)));
   FileWrite(h, StringFormat("bar_timestamp;blue_p%d;maroon_p%d;blue_p%d;maroon_p%d", PeriodA, PeriodA, PeriodB, PeriodB));

   for(int i = n; i >= 1; i--)
   {
      double blueA   = iCustom(NULL, 0, "Range Cycle Indicator", 0, 0, PeriodA, 1, i);
      double maroonA = iCustom(NULL, 0, "Range Cycle Indicator", 0, 0, PeriodA, 2, i);
      double blueB   = iCustom(NULL, 0, "Range Cycle Indicator", 0, 0, PeriodB, 1, i);
      double maroonB = iCustom(NULL, 0, "Range Cycle Indicator", 0, 0, PeriodB, 2, i);

      string line = TimeToStr(Time[i], TIME_DATE | TIME_MINUTES) + ";" +
                    (blueA   == EMPTY_VALUE ? "" : DoubleToStr(blueA,   6)) + ";" +
                    (maroonA == EMPTY_VALUE ? "" : DoubleToStr(maroonA, 6)) + ";" +
                    (blueB   == EMPTY_VALUE ? "" : DoubleToStr(blueB,   6)) + ";" +
                    (maroonB == EMPTY_VALUE ? "" : DoubleToStr(maroonB, 6));
      FileWrite(h, line);
   }

   FileClose(h);

   string fullPath = TerminalInfoString(TERMINAL_COMMONDATA_PATH) + "\\Files\\" + fileName;
   string msg = StringFormat("RC repaint snapshot complete: %d bars written (periods %d and %d).\n\nFull file path (copy this):\n%s\n\nRun this script again later (in a few hours, tomorrow, etc.) to build a second snapshot -- each run makes a new, uniquely-named file.",
                              n, PeriodA, PeriodB, fullPath);
   Alert(msg);
   Print("EA: ", msg);
}
//+------------------------------------------------------------------+
