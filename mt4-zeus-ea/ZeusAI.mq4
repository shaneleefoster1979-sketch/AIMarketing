// +------------------------------------------------------------------+
// TRADE LOGGER
// Writes all open and closed trade data to a JSON file
// The MT4 Trade Tracker desktop app reads this file in real time
// +------------------------------------------------------------------+
void LogTrades()
{
   if(!EnableTradeLog) return;

   int fh = FileOpen(LogFileName, FILE_WRITE|FILE_TXT|FILE_COMMON);
   if(fh == INVALID_HANDLE) return;

   string json = "{\n";
   json += "  \"timestamp\": \"" +
           TimeToStr(TimeCurrent(), TIME_DATE|TIME_SECONDS) + "\",\n";
   json += "  \"account_balance\": " +
           DoubleToStr(AccountBalance(), 2) + ",\n";
   json += "  \"account_equity\": "  +
           DoubleToStr(AccountEquity(),  2) + ",\n";

   // --- OPEN TRADES ---
   json += "  \"open_trades\": [\n";
   bool firstOpen = true;
   for(int i = 0; i < OrdersTotal(); i++)
   {
      if(!OrderSelect(i, SELECT_BY_POS, MODE_TRADES)) continue;
      if(OrderMagicNumber() != MagicNumber || OrderSymbol() != Symbol()) continue;

      if(!firstOpen) json += ",\n";
      firstOpen = false;

      // Get virtual SL and TP from arrays
      double vsl = 0, vtp = 0;
      for(int v = 0; v < vCount; v++)
      {
         if(vTicket[v] == OrderTicket())
         { vsl = vSL[v]; vtp = vTP[v]; break; }
      }

      double curPrice = (OrderType() == OP_BUY) ? Bid : Ask;
      json += "    {\n";
      json += "      \"ticket\": "        + IntegerToString(OrderTicket())                       + ",\n";
      json += "      \"type\": \""       + (OrderType()==OP_BUY ? "BUY" : "SELL")              + "\",\n";
      json += "      \"lots\": "          + DoubleToStr(OrderLots(), 2)                          + ",\n";
      json += "      \"entry\": "         + DoubleToStr(OrderOpenPrice(), 3)                     + ",\n";
      json += "      \"open_time\": \""  + TimeToStr(OrderOpenTime(), TIME_DATE|TIME_SECONDS)   + "\",\n";
      json += "      \"virtual_sl\": "    + DoubleToStr(vsl, 3)                                  + ",\n";
      json += "      \"virtual_tp\": "    + DoubleToStr(vtp, 3)                                  + ",\n";
      json += "      \"current_price\": " + DoubleToStr(curPrice, 3)                             + ",\n";
      json += "      \"profit\": "        + DoubleToStr(OrderProfit(), 2)                        + ",\n";
      json += "      \"swap\": "          + DoubleToStr(OrderSwap(), 2)                          + "\n";
      json += "    }";
   }
   json += "\n  ],\n";

   // --- CLOSED TRADES ---
   // Force MT4 to load full account history into memory
   // Without this, OrdersHistoryTotal() may only return recent orders
   RefreshRates();

   json += "  \"closed_trades\": [\n";
   bool firstClosed = true;
   int histTotal = OrdersHistoryTotal();
   for(int i = histTotal - 1; i >= 0; i--)
   {
      if(!OrderSelect(i, SELECT_BY_POS, MODE_HISTORY)) continue;
      if(OrderMagicNumber() != MagicNumber || OrderSymbol() != Symbol()) continue;

      if(!firstClosed) json += ",\n";
      firstClosed = false;

      json += "    {\n";
      json += "      \"ticket\": "        + IntegerToString(OrderTicket())                         + ",\n";
      json += "      \"type\": \""       + (OrderType()==OP_BUY ? "BUY" : "SELL")                + "\",\n";
      json += "      \"lots\": "          + DoubleToStr(OrderLots(), 2)                            + ",\n";
      json += "      \"entry\": "         + DoubleToStr(OrderOpenPrice(), 3)                       + ",\n";
      json += "      \"exit\": "          + DoubleToStr(OrderClosePrice(), 3)                      + ",\n";
      json += "      \"open_time\": \""  + TimeToStr(OrderOpenTime(),  TIME_DATE|TIME_SECONDS)    + "\",\n";
      json += "      \"close_time\": \"" + TimeToStr(OrderCloseTime(), TIME_DATE|TIME_SECONDS)    + "\",\n";
      json += "      \"profit\": "        + DoubleToStr(OrderProfit(), 2)                          + ",\n";
      json += "      \"swap\": "          + DoubleToStr(OrderSwap(), 2)                            + ",\n";
      json += "      \"comment\": \""    + OrderComment()                                         + "\"\n";
      json += "    }";
   }
   json += "\n  ]\n";
   json += "}\n";

   FileWriteString(fh, json);
   FileClose(fh);
}
// +------------------------------------------------------------------+
// |   Zeus EA                                                         |
// |   VIRTUAL SL/TP + PERSISTENT STATE (survives MT4 restart)        |
// |                                                                  |
// |   Entry: RC AND Renko Momentum Cycle (RMC) must AGREE in sign,   |
// |   confirmed by brick direction, on candle close.                 |
// |                                                                  |
// |   All SL, BE, and TP checks fire at candle close only.          |
// |   RC exit signal fires every tick (direction change).            |
// |                                                                  |
// |   Money management:                                              |
// |   3% total risk per signal split across 4 trades:               |
// |   T1=20%  T2=25%  T3=25%  T4=30%                               |
// |   Larger size on T4 (the runner) for maximum trend capture.      |
// |                                                                  |
// |   Break-even moves SL to entry candle close price.              |
// |   No buffer needed - all checks are at candle close.            |
// |                                                                  |
// |   Gap handling: if price gaps over SL the trade closes on        |
// |   that same candle close - no separate gap logic needed.         |
// |                                                                  |
// |   ReadyToTrade: waits for RC to cycle through opposite           |
// |   direction before allowing first entry on attach.               |
// +------------------------------------------------------------------+
#property strict
#include "zeus_ai_weights.mqh"

// +------------------------------------------------------------------+
// ZEUS AI: trained DQN that picks WHICH stop-loss/take-profit profile
// to use per trade (9 choices) or skips the signal entirely, instead of
// the fixed StopLossPoints/TP1-4 below. TotalRiskPercent stays the one
// untouchable constraint -- GetLotSize always recomputes lot size so the
// dollar risk per leg is exactly TotalRiskPercent * weight%, whichever
// stop distance is chosen. The forward pass (zeus_ai_weights.mqh) is a
// direct, numerically-verified port of the trained PyTorch weights -- see
// export_dqn_to_mql4.py in the backtest repo for the verification.
// +------------------------------------------------------------------+
input bool   UseZeusAI            = true;   // Off = fall back to fixed StopLossPoints/TP1-4 exactly as before
input double AI_QuotaTargetPct    = 10.0;   // Trailing-window equity growth target %, matches training
input int    AI_QuotaWindowDays   = 30;     // Trailing window length in days, matches training

double   AI_RefBalance     = 0;
string   AI_RefBalanceFile = "";  // built in OnInit(), once MagicNumber (declared below) is in scope
datetime aiEquityTime[];
double   aiEquityValue[];
int      aiEquityCount = 0;
#define  AI_MAX_EQUITY_HISTORY 5000
string   AI_EquityFile = "";      // built in OnInit(), same reason

input double TotalRiskPercent      = 3.0;   // Total risk % per signal
input int    StopLossPoints        = 600;   // SL in points (600 = 60 pips on 3-digit)
input int    TP1                   = 600;   // T1 TP in points
input int    TP2                   = 1200;  // T2 TP in points
input int    TP3                   = 1800;  // T3 TP in points
input int    TP4                   = 0;     // T4 TP (0 = no TP, runner)
input bool   Trade1Enabled         = true;
input bool   Trade2Enabled         = true;
input bool   Trade3Enabled         = true;
input bool   Trade4Enabled         = true;
input int    RC_Period             = 7;     // Range Cycle period
input bool   UseRMCFilter          = true;  // Require Renko Momentum Cycle to AGREE with RC (both blue = buy, both red/maroon = sell)
input int    RMC_MinRunLength      = 2;     // Must match Renko Momentum Cycle MinRunLength input
input int    RMC_MaxRunLookback    = 10;    // Must match Renko Momentum Cycle MaxRunLookback input
input int    RMC_RSI_MinPeriod     = 7;     // Must match Renko Momentum Cycle RSI_MinPeriod input
input int    RMC_RSI_MaxPeriod     = 21;    // Must match Renko Momentum Cycle RSI_MaxPeriod input
input int    RMC_CycleMemory       = 5;     // Must match Renko Momentum Cycle CycleMemory input
input double RMC_MinConfirmMagnitude = 0.03; // RMC must be at least this far from zero (of its -1..+1 range) to count as a real red/blue reading, not noise sitting on the zero line -- raised from 0.02 to 0.03 live after a trade still entered on a signal so weak the RMC line remained invisible on the chart
input bool   AllowNewEntries       = true;  // Uncheck to pause entries after manual close
input bool   BypassRenkoResetGate   = false; // TESTER ONLY: skip the Renko-reset unlock handshake (leave false for live)
input int    RenkoResetTimeoutSeconds = 60; // Auto-unlock entries if Renko Reset script hasn't run within this many seconds
input double MaxLotsPerTrade       = 50.0;  // Broker max lot size per trade
input bool   KeepTradesOverWeekend = true;
input int    MarketCloseHour       = 21;
input int    MarketCloseMinute     = 55;
input int    MagicNumber           = 112233;
input int    Slippage              = 3;
// Risk weight per trade leg - must sum to 100
// T4 is the runner (no TP) so gets the largest allocation
input int    T1_Weight             = 20;   // T1 risk weight % (hits TP1 then closes)
input int    T2_Weight             = 25;   // T2 risk weight % (hits TP2 then closes)
input int    T3_Weight             = 25;   // T3 risk weight % (hits TP3 then closes)
input int    T4_Weight             = 30;   // T4 risk weight % (runner - no TP)
// Trade Logger
input bool   EnableTradeLog        = true;  // Write trade log for desktop tracker
input string LogFileName           = "MT4_TradeLog.json"; // Log file name

datetime lastBarTime    = 0;
bool BreakEvenTriggered = false;
bool T1_WasOpen         = false;
// knownTickets array tracks open trades for manual close detection

// ReadyToTrade: prevents mid-cycle entry on attach.
// Records RC AND RMC direction at load. Arms (OR logic) as soon as
// EITHER RC or RMC has moved to the OPPOSITE direction from its own
// load-time reading at least once since load.
bool ReadyToTrade         = false;
int  InitialRC_Direction  = 0;
int  InitialRMC_Direction = 0;

// Entry and exit are gated by the just-closed brick direction (matching the
// trade) and the RMC filter. No multi-brick confirmation state is needed.

// Startup lockout - prevents acting on corrupted Renko after restart
bool     StartupLockout    = false;
datetime StartupTime       = 0;   // wall-clock, for the human-readable log line only
int      StartupTickCount  = 0;   // GetTickCount() snapshot - what elapsed is actually measured against
bool     ManualUnlocked    = false;
string   UNLOCK_FLAG       = "renko_ready.txt";
int      LOCKOUT_MINUTES   = 2;

// Renko-reset manual-unlock gate (no open trades on attach): tracks when the
// gate started waiting so it can auto-release after RenkoResetTimeoutSeconds
// if the Renko Reset script isn't run in time -- see Gate 3 in OnTick().
datetime NoTradesGateStartTime = 0;

// Manual close detection
// Tracks open tickets - if one disappears without EA closing it = manual close
bool     WaitingForNewCycle    = false;
int      CycleWaitDirection    = 0;
int      RMCCycleWaitDirection = 0;
bool     CycleSawOpposite      = false;
int      knownTickets[];
int      knownTicketCount      = 0;

// +------------------------------------------------------------------+
// VIRTUAL SL/TP STORAGE
// +------------------------------------------------------------------+
#define MAX_TRADES 10
int    vTicket[MAX_TRADES];
double vSL[MAX_TRADES];
double vTP[MAX_TRADES];
double vBEPrice[MAX_TRADES];
int    vCount = 0;

// +------------------------------------------------------------------+
// GlobalVariable name helpers
// +------------------------------------------------------------------+
string GV_SL(int ticket)  { return "EA_VSL_"  + IntegerToString(MagicNumber) + "_" + IntegerToString(ticket); }
string GV_TP(int ticket)  { return "EA_VTP_"  + IntegerToString(MagicNumber) + "_" + IntegerToString(ticket); }
string GV_BE(int ticket)  { return "EA_VBE_"  + IntegerToString(MagicNumber) + "_" + IntegerToString(ticket); }
string GV_BEF()           { return "EA_BEF_"  + IntegerToString(MagicNumber); }
string GV_T1()            { return "EA_T1_"   + IntegerToString(MagicNumber); }

// +------------------------------------------------------------------+
// STATE FILE PERSISTENCE
// GlobalVariables are wiped by the Renko-reset procedure run after
// restarts, which destroys virtual SL/TP and orphans open trades.
// We mirror all virtual state to a file (FILE_COMMON) so it survives
// both MT4 restarts AND the reset script. The file is the source of
// truth on restore; GlobalVariables and comment-based recalculation
// remain only as last-resort fallbacks.
// +------------------------------------------------------------------+
string StateFileName()
{
   return "Zeus_state_" + IntegerToString(MagicNumber) + ".csv";
}

// Write every tracked ticket's virtual state to the state file.
void SaveStateToFile()
{
   int h = FileOpen(StateFileName(), FILE_WRITE|FILE_CSV|FILE_COMMON, ',');
   if(h == INVALID_HANDLE)
   {
      Print("EA: WARNING - could not write state file err=", GetLastError());
      return;
   }
   // header
   FileWrite(h, "ticket", "vsl", "vtp", "vbe");
   for(int i = 0; i < vCount; i++)
      FileWrite(h, vTicket[i],
                   DoubleToStr(vSL[i], Digits),
                   DoubleToStr(vTP[i], Digits),
                   DoubleToStr(vBEPrice[i], Digits));
   FileClose(h);
}

// Look up a ticket's saved TP/SL/BE from the state file.
// Returns true and fills out-params if found.
bool LoadTicketFromFile(int ticket, double &outSL, double &outTP, double &outBE)
{
   int h = FileOpen(StateFileName(), FILE_READ|FILE_CSV|FILE_COMMON, ',');
   if(h == INVALID_HANDLE) return false;
   bool found = false;
   // skip header (4 fields)
   for(int skip = 0; skip < 4 && !FileIsEnding(h); skip++) FileReadString(h);
   while(!FileIsEnding(h))
   {
      int    tk = (int)StringToInteger(FileReadString(h));
      if(FileIsEnding(h)) break;
      double sl = StringToDouble(FileReadString(h));
      double tp = StringToDouble(FileReadString(h));
      double be = StringToDouble(FileReadString(h));
      if(tk == ticket)
      {
         outSL = sl; outTP = tp; outBE = be;
         found = true;
         break;
      }
   }
   FileClose(h);
   return found;
}

// +------------------------------------------------------------------+
void VirtualStore(int ticket, double sl, double tp, double bePrice)
{
   for(int i = 0; i < vCount; i++)
   {
      if(vTicket[i] == ticket)
      {
         vSL[i]      = sl;
         vTP[i]      = tp;
         vBEPrice[i] = bePrice;
         GlobalVariableSet(GV_SL(ticket), sl);
         GlobalVariableSet(GV_TP(ticket), tp);
         GlobalVariableSet(GV_BE(ticket), bePrice);
         SaveStateToFile();
         return;
      }
   }
   if(vCount < MAX_TRADES)
   {
      vTicket[vCount]  = ticket;
      vSL[vCount]      = sl;
      vTP[vCount]      = tp;
      vBEPrice[vCount] = bePrice;
      vCount++;
      GlobalVariableSet(GV_SL(ticket), sl);
      GlobalVariableSet(GV_TP(ticket), tp);
      GlobalVariableSet(GV_BE(ticket), bePrice);
      SaveStateToFile();
   }
}

// +------------------------------------------------------------------+
void RemoveKnownTicket(int ticket)
{
   // Remove ticket from known set so manual close detector
   // does not flag EA-closed tickets as manual closes
   for(int i = 0; i < knownTicketCount; i++)
   {
      if(knownTickets[i] == ticket)
      {
         for(int j = i; j < knownTicketCount - 1; j++)
            knownTickets[j] = knownTickets[j+1];
         knownTicketCount--;
         ArrayResize(knownTickets, knownTicketCount);
         return;
      }
   }
}

void VirtualRemove(int ticket)
{
   GlobalVariableDel(GV_SL(ticket));
   GlobalVariableDel(GV_TP(ticket));
   GlobalVariableDel(GV_BE(ticket));
   for(int i = 0; i < vCount; i++)
   {
      if(vTicket[i] == ticket)
      {
         for(int j = i; j < vCount - 1; j++)
         {
            vTicket[j]  = vTicket[j+1];
            vSL[j]      = vSL[j+1];
            vTP[j]      = vTP[j+1];
            vBEPrice[j] = vBEPrice[j+1];
         }
         vCount--;
         SaveStateToFile();
         return;
      }
   }
}

// +------------------------------------------------------------------+
double VirtualGetSL(int ticket)
{
   for(int i = 0; i < vCount; i++)
      if(vTicket[i] == ticket) return vSL[i];
   return 0;
}

double VirtualGetTP(int ticket)
{
   for(int i = 0; i < vCount; i++)
      if(vTicket[i] == ticket) return vTP[i];
   return 0;
}

double VirtualGetBEPrice(int ticket)
{
   for(int i = 0; i < vCount; i++)
      if(vTicket[i] == ticket) return vBEPrice[i];
   return 0;
}

void VirtualUpdateSL(int ticket, double newSL)
{
   for(int i = 0; i < vCount; i++)
   {
      if(vTicket[i] == ticket)
      {
         vSL[i] = newSL;
         GlobalVariableSet(GV_SL(ticket), newSL);
         return;
      }
   }
}

// +------------------------------------------------------------------+
// RestoreStateFromGlobalVariables
// +------------------------------------------------------------------+
void RestoreStateFromGlobalVariables()
{
   vCount = 0;
   bool tradesFound = false;

   for(int i = 0; i < OrdersTotal(); i++)
   {
      if(!OrderSelect(i, SELECT_BY_POS, MODE_TRADES)) continue;
      if(OrderMagicNumber() != MagicNumber || OrderSymbol() != Symbol()) continue;

      int ticket = OrderTicket();
      tradesFound = true;

      double savedSL = 0, savedTP = 0, savedBE = 0;

      // Source 1 (most reliable): state file. Survives MT4 restart AND
      // the Renko-reset script that wipes GlobalVariables.
      bool fromFile = LoadTicketFromFile(ticket, savedSL, savedTP, savedBE);
      if(fromFile)
         Print("EA: ticket ", ticket, " state restored from file.");

      // Source 2: GlobalVariables (if file missing/incomplete)
      if(savedSL == 0 && GlobalVariableCheck(GV_SL(ticket)))
         savedSL = GlobalVariableGet(GV_SL(ticket));
      if(savedTP == 0 && GlobalVariableCheck(GV_TP(ticket)))
         savedTP = GlobalVariableGet(GV_TP(ticket));
      if(savedBE == 0 && GlobalVariableCheck(GV_BE(ticket)))
         savedBE = GlobalVariableGet(GV_BE(ticket));

      // Fallback: recalculate SL from open price if still unknown
      if(savedSL == 0)
      {
         if(OrderType() == OP_BUY)
            savedSL = NormalizeDouble(OrderOpenPrice() - StopLossPoints * Point, Digits);
         else
            savedSL = NormalizeDouble(OrderOpenPrice() + StopLossPoints * Point, Digits);
         Print("EA: VSL for ticket ", ticket, " recalculated from open price.");
      }

      // Fallback: recalculate TP from leg label if still unknown.
      // NOTE: this is a LAST resort - it uses OrderOpenPrice (broker fill)
      // which differs slightly from the original candleClose reference,
      // and depends on the broker preserving the T1/T2/T3/T4 comment.
      // The state file above is the reliable path; this only fires if
      // both the file and GlobalVariables are gone.
      if(savedTP == 0)
      {
         string lbl   = OrderComment();
         int    tpPts = 0;
         if(lbl == "T1")      tpPts = TP1;
         else if(lbl == "T2") tpPts = TP2;
         else if(lbl == "T3") tpPts = TP3;
         else if(lbl == "T4") tpPts = TP4; // TP4=0 means runner, no TP
         if(tpPts > 0)
         {
            if(OrderType() == OP_BUY)
               savedTP = NormalizeDouble(OrderOpenPrice() + tpPts * Point, Digits);
            else
               savedTP = NormalizeDouble(OrderOpenPrice() - tpPts * Point, Digits);
            Print("EA: VTP for ticket ", ticket, " [", lbl,
                  "] recalculated from open price = ",
                  DoubleToStr(savedTP, Digits));
         }
         else if(lbl != "T4")
         {
            // Comment was lost/mangled and this is not the runner.
            // Leaving TP at 0 would mean the leg NEVER takes profit.
            // Warn loudly so it is visible in the Experts tab.
            Print("EA: *** WARNING ticket ", ticket,
                  " has no recoverable TP (comment='", lbl,
                  "'). Leg will not auto-TP. Manage manually. ***");
         }
      }

      // Fallback: BE from open price if unknown
      if(savedBE == 0) savedBE = OrderOpenPrice();

      if(vCount < MAX_TRADES)
      {
         vTicket[vCount]  = ticket;
         vSL[vCount]      = savedSL;
         vTP[vCount]      = savedTP;
         vBEPrice[vCount] = savedBE;
         vCount++;
      }

      if(OrderComment() == "T1") T1_WasOpen = true;

      Print("EA: Restored ticket=", ticket,
            " VSL=", savedSL,
            " VTP=", (savedTP > 0 ? DoubleToStr(savedTP, Digits) : "none"),
            " BEPrice=", savedBE);
   }

   if(GlobalVariableCheck(GV_BEF()))
      BreakEvenTriggered = (GlobalVariableGet(GV_BEF()) > 0);
   if(GlobalVariableCheck(GV_T1()))
      T1_WasOpen = (GlobalVariableGet(GV_T1()) > 0);

   if(tradesFound)
      Print("EA: Restart detected with open trades - state restored.");
   else
      Print("EA: No open trades found on restart.");
}

// +------------------------------------------------------------------+
int OnInit()
{
   Print("=== ZEUS AI BUILD 2026-08-26 | RC + RMC dual-agreement direction | Trained DQN picks per-trade SL/TP profile ===");
   lastBarTime          = 0;
   ReadyToTrade         = false;
   InitialRC_Direction  = 0;
   InitialRMC_Direction = 0;
   RestoreStateFromGlobalVariables();
   AI_RefBalanceFile = "ZeusAI_refbalance_" + IntegerToString(MagicNumber) + ".txt";
   AI_EquityFile     = "ZeusAI_equity_"     + IntegerToString(MagicNumber) + ".csv";
   AI_LoadOrInitRefBalance();
   AI_LoadEquityHistory();

   // Wait for indicator buffers to initialize (up to 20 retries)
   // Prevents EMPTY_VALUE reads immediately after attach/recompile
   double rc = 0;
   for(int attempt = 0; attempt < 20; attempt++)
   {
      rc = GetRC_Value();
      if(rc != 0 && rc != EMPTY_VALUE) break;
      Sleep(100);
   }

   // If restoring existing open trades after restart:
   // Engage lockout - wait 2 minutes before resuming management
   // This gives time to fix Renko chart via reset script
   if(CountTrades() > 0)
   {
      StartupLockout   = true;
      StartupTime      = TimeCurrent();
      StartupTickCount = GetTickCount();
      ReadyToTrade     = false;
      Print("EA: Restart detected with open trades.",
            " New-entry lockout active for ", LOCKOUT_MINUTES,
            " real minutes (existing trades' SL/TP still checked every tick"
            " throughout). Fix Renko chart now if needed.");
      Print("EA: New-entry lockout should clear at approximately: ",
            TimeToStr(StartupTime + LOCKOUT_MINUTES*60,
                      TIME_DATE|TIME_SECONDS),
            " (measured off real elapsed time, not broker quote time -",
            " so it will not stall over a weekend market close)");

      // Populate known tickets from restored open trades
      knownTicketCount = 0;
      ArrayResize(knownTickets, 0);
      for(int rt = 0; rt < OrdersTotal(); rt++)
      {
         if(!OrderSelect(rt, SELECT_BY_POS, MODE_TRADES)) continue;
         if(OrderMagicNumber() != MagicNumber || OrderSymbol() != Symbol()) continue;
         ArrayResize(knownTickets, knownTicketCount + 1);
         knownTickets[knownTicketCount++] = OrderTicket();
      }
      return(INIT_SUCCEEDED);
   }

   // No open trades - require manual unlock via Renko Reset script
   // Delete any stale unlock flag first
   if(FileIsExist(UNLOCK_FLAG, FILE_COMMON))
      FileDelete(UNLOCK_FLAG, FILE_COMMON);

   ManualUnlocked = false;
   ReadyToTrade   = false;
   NoTradesGateStartTime = TimeCurrent();
   Print("EA: No open trades on restart.",
         " Waiting for Renko Reset script to run before allowing entries.");
   Print("EA: Run Renko_Reset script then entries will unlock automatically.");
   Print("EA: If the script isn't run within ", RenkoResetTimeoutSeconds,
         "s, entries will auto-unlock anyway.");

   // Record the current RC direction at load time
   if(rc > 0)       InitialRC_Direction =  1;
   else if(rc < 0)  InitialRC_Direction = -1;
   else             InitialRC_Direction =  0;

   // Record the current RMC direction at load time too (OR logic with RC
   // below -- either one flipping is enough to arm). GetRMC_Value() reads
   // directly off Close[]/Open[]/Volume[] (no iCustom buffer warmup
   // involved), so no retry loop is needed here the way there is for RC
   // above; EMPTY_VALUE (insufficient bar history) is treated the same as
   // a neutral reading.
   double rmcAtLoad = GetRMC_Value();
   InitialRMC_Direction = RMC_Dir(rmcAtLoad);

   // Arm immediately if EITHER side was neutral at load -- nothing to wait
   // for on that side, mirrors RC's own original immediate-arm behavior,
   // now applied per-indicator under the OR rule.
   if(InitialRC_Direction == 0 || InitialRMC_Direction == 0)
   {
      ReadyToTrade = true;
      Print("EA: ReadyToTrade immediately - RC dir=", InitialRC_Direction,
            " RMC dir=", InitialRMC_Direction, " (one or both neutral on load).");
   }
   else
   {
      Print("EA: RC direction on load = ", InitialRC_Direction,
            ", RMC direction on load = ", InitialRMC_Direction,
            " - waiting for EITHER to flip before entering.");
   }

   return(INIT_SUCCEEDED);
}

// +------------------------------------------------------------------+
void OnDeinit(const int reason)
{
   // Save all virtual state to GlobalVariables before EA shuts down
   // This ensures RestoreStateFromGlobalVariables() can recover everything
   GlobalVariableSet(GV_BEF(), BreakEvenTriggered ? 1.0 : 0.0);
   GlobalVariableSet(GV_T1(),  T1_WasOpen         ? 1.0 : 0.0);

   // Re-save all ticket SL/TP/BE values as a safety net
   // VirtualStore already saves these on open and update,
   // but re-saving here guarantees they survive MT4 restart
   for(int i = 0; i < vCount; i++)
   {
      GlobalVariableSet(GV_SL(vTicket[i]), vSL[i]);
      GlobalVariableSet(GV_TP(vTicket[i]), vTP[i]);
      GlobalVariableSet(GV_BE(vTicket[i]), vBEPrice[i]);
   }
   SaveStateToFile();
   Print("EA: OnDeinit - saved state for ", vCount, " tickets.");
}

// +------------------------------------------------------------------+
bool IsNewBar()
{
   if(Time[0] != lastBarTime)
   {
      lastBarTime = Time[0];
      return true;
   }
   return false;
}

// +------------------------------------------------------------------+
// RC indicator readers
// Buffer 1 = Blue line (bullish cycle)
// Buffer 2 = Maroon line (bearish cycle)
// +------------------------------------------------------------------+
double GetRC_Value()
{
   // Direction is encoded by WHICH coloured line is active on the just-closed
   // bar (shift 0), NOT by the raw value's sign or magnitude:
   //   blue line active   = bullish  -> return a POSITIVE value
   //   maroon line active = bearish  -> return a NEGATIVE value
   // Magnitude is the active line's absolute value so magnitude-based callers
   // keep working. Only shift 0 is read - the old version scanned shift 0 AND
   // shift 1 and returned the largest-magnitude of all four reads, which could
   // hand back the PREVIOUS bar's opposite direction (buys at bottoms / the
   // impossible sell in an uptrend). That cross-bar, sign-of-value logic was
   // the bug.
   // Read the just-closed bar (shift 1) so RC direction is evaluated on the
   // SAME bar as the RMC filter, the brick direction, and candleClose.
   // (Reading shift 0 - the forming bar - misaligns RC from whatever else
   // was evaluated on the already-closed bar, which historically made
   // trades land on the wrong side of the filter's actual test bar.)
   double blue   = GetRC_BlueLine(1);
   double maroon = GetRC_MaroonLine(1);
   bool   blueOn   = (blue   != EMPTY_VALUE && blue   != 0.0);
   bool   maroonOn = (maroon != EMPTY_VALUE && maroon != 0.0);

   if(blueOn && !maroonOn) return  MathAbs(blue);     // bullish
   if(maroonOn && !blueOn) return -MathAbs(maroon);   // bearish
   if(blueOn && maroonOn)
   {
      // Transition bar with both plotted: the larger-magnitude line is the
      // one that just became the active signal.
      if(MathAbs(blue) >= MathAbs(maroon)) return  MathAbs(blue);
      return -MathAbs(maroon);
   }
   return 0;
}

double GetRC_BlueLine(int shift)
{
   return iCustom(NULL, 0, "Range Cycle Indicator", 0, 0, RC_Period, 1, shift);
}

double GetRC_MaroonLine(int shift)
{
   return iCustom(NULL, 0, "Range Cycle Indicator", 0, 0, RC_Period, 2, shift);
}

// Direction of the just-closed brick (shift 1).
// Returns +1 for a bull brick (Close>Open), -1 for bear (Close<Open), 0 flat.
// On Renko this is the brick colour: the confirmation the trade direction
// actually printed one more brick our way after the RC crossover.
int ClosedBrickDir()
{
   double o = Open[1];
   double c = Close[1];
   if(c > o) return  1;
   if(c < o) return -1;
   return 0;
}

// Internal port of Renko Momentum Cycle (RMC) -- ported directly from
// RMC.mq4's GetBrickRun/EstimateCycleLength/GetMomentumDecay/CalcRMC,
// renamed RMC_* to avoid symbol collisions with anything else in this file.
// Same rationale as the old Synth port: computing this internally off the
// SAME Close[]/Open[]/Volume[] series Zeus itself reads means no iCustom
// divergence between this EA's evaluation and whatever RMC.mq4 plots if
// you also run it as a visible indicator -- and it behaves identically in
// the Strategy Tester and live. RMC.mq4's own math is itself non-repainting
// (verified by code review: every helper only ever looks at bar i and bars
// OLDER than i, never anything newer) -- ported faithfully, not approximated.
datetime g_rmcCacheTime = 0;
double   g_rmcCacheVal  = 0.0;
int      g_rmcCacheRun  = 0;       // diagnostics: brick run length at cache time
int      g_rmcCacheRsiPeriod = 0;  // diagnostics: adaptive RSI period used
double   g_rmcCacheDecay = 0.0;    // diagnostics: momentum decay factor used

int RMC_GetBrickRun(int i, int total, double &runVol)
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

int RMC_EstimateCycleLength(int i, int total)
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

double RMC_GetMomentumDecay(int i, int total)
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

// GetRMC_Value(): returns RMC's raw oscillator value (-1..+1) for the
// just-closed bar (shift 1), matching how GetRC_Value() always evaluates
// shift 1. Sign is what Zeus's entry/exit rules act on: >=0 is RMC's
// "Bull" (blue) line, <0 is its "Bear" (red/tomato) line -- exactly the
// two colored buffers RMC.mq4 itself plots.
double GetRMC_Value()
{
   // Cache: compute once per bar; entry and exit both call this on the same bar
   if(g_rmcCacheTime == Time[1] && g_rmcCacheTime != 0)
      return g_rmcCacheVal;

   int total = Bars;
   int i = 1; // just-closed bar

   if(i + RMC_RSI_MaxPeriod * 3 >= total) return EMPTY_VALUE; // insufficient history yet

   double runVol = 0;
   int    run    = RMC_GetBrickRun(i, total, runVol);
   if(MathAbs(run) < RMC_MinRunLength) return EMPTY_VALUE; // no qualifying run at this bar

   int    rsiPeriod = RMC_EstimateCycleLength(i, total);
   double rsi       = iRSI(NULL, 0, rsiPeriod, PRICE_CLOSE, i);
   if(rsi == EMPTY_VALUE) return EMPTY_VALUE;
   double rsiNorm   = (rsi - 50.0) / 50.0;
   double decay     = RMC_GetMomentumDecay(i, total);

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
   rmc = MathMax(-1.0, MathMin(1.0, rmc));

   g_rmcCacheTime       = Time[1];
   g_rmcCacheVal        = rmc;
   g_rmcCacheRun        = run;
   g_rmcCacheRsiPeriod  = rsiPeriod;
   g_rmcCacheDecay      = decay;
   return rmc;
}

// RMC_Dir(): the ONE place that turns a raw GetRMC_Value() reading into a
// +1/-1/0 direction, everywhere in this file. A bare sign check treats
// anything nonzero as a confirmed reading -- including values sitting a
// hair off the zero line (e.g. rmc=-0.0414, the exact value that let a set
// of sell entries through on a reading barely distinguishable from flat).
// This requires the value to actually clear RMC_MinConfirmMagnitude before
// it counts as clearly red or clearly blue; anything closer to zero than
// that, plus EMPTY_VALUE, comes back 0 (no reading) same as before.
int RMC_Dir(double rmc)
{
   if(rmc == EMPTY_VALUE) return 0;
   if(rmc >=  RMC_MinConfirmMagnitude) return  1;
   if(rmc <= -RMC_MinConfirmMagnitude) return -1;
   return 0;
}

// +------------------------------------------------------------------+
// ZEUS AI -- forward pass, feature build, action decode, equity history
// +------------------------------------------------------------------+

// Exact port of the trained network's forward pass: Linear(5,64) -> ReLU
// -> Linear(64,64) -> ReLU -> Linear(64,10). Weight arrays come from
// zeus_ai_weights.mqh (auto-generated, verified bit-for-bit against the
// PyTorch model by export_dqn_to_mql4.py before ever being committed).
void ZAI_Forward(double &x[], double &qOut[])
{
   double h1[ZAI_H1];
   ArrayInitialize(h1, 0.0);
   for(int o = 0; o < ZAI_H1; o++)
   {
      double s = ZAI_B1[o];
      for(int i = 0; i < ZAI_IN; i++) s += ZAI_W1[o*ZAI_IN+i] * x[i];
      h1[o] = MathMax(0.0, s);
   }
   double h2[ZAI_H2];
   ArrayInitialize(h2, 0.0);
   for(int o = 0; o < ZAI_H2; o++)
   {
      double s = ZAI_B2[o];
      for(int i = 0; i < ZAI_H1; i++) s += ZAI_W2[o*ZAI_H1+i] * h1[i];
      h2[o] = MathMax(0.0, s);
   }
   for(int o = 0; o < ZAI_OUT; o++)
   {
      double s = ZAI_B3[o];
      for(int i = 0; i < ZAI_H2; i++) s += ZAI_W3[o*ZAI_H2+i] * h2[i];
      qOut[o] = s;
   }
}

// Reference account balance the log-equity feature is measured against --
// set ONCE, the first time Zeus AI ever runs on this account, then
// persisted forever (matches training's fixed starting_balance reference).
void AI_LoadOrInitRefBalance()
{
   if(FileIsExist(AI_RefBalanceFile, FILE_COMMON))
   {
      int handle = FileOpen(AI_RefBalanceFile, FILE_READ|FILE_CSV|FILE_COMMON);
      if(handle != INVALID_HANDLE)
      {
         string s = FileReadString(handle);
         FileClose(handle);
         double val = StrToDouble(s);
         if(val > 0) { AI_RefBalance = val; return; }
      }
   }
   AI_RefBalance = AccountBalance();
   int wh = FileOpen(AI_RefBalanceFile, FILE_WRITE|FILE_CSV|FILE_COMMON);
   if(wh != INVALID_HANDLE)
   {
      FileWrite(wh, DoubleToStr(AI_RefBalance, 2));
      FileClose(wh);
   }
   Print("EA: Zeus AI reference balance set to ", DoubleToStr(AI_RefBalance, 2));
}

// Loads the persisted (timestamp, equity) log from FILE_COMMON so the
// trailing-window return survives a restart -- same "must survive the
// weekly reboot" requirement as everything else in this EA's state.
void AI_LoadEquityHistory()
{
   aiEquityCount = 0;
   ArrayResize(aiEquityTime, 0);
   ArrayResize(aiEquityValue, 0);
   if(!FileIsExist(AI_EquityFile, FILE_COMMON)) return;

   int handle = FileOpen(AI_EquityFile, FILE_READ|FILE_CSV|FILE_COMMON);
   if(handle == INVALID_HANDLE) return;

   while(!FileIsEnding(handle))
   {
      string tStr = FileReadString(handle);
      if(tStr == "") break;
      string eStr = FileReadString(handle);
      datetime t = StrToTime(tStr);
      double   e = StrToDouble(eStr);
      if(t > 0 && e > 0)
      {
         ArrayResize(aiEquityTime,  aiEquityCount + 1);
         ArrayResize(aiEquityValue, aiEquityCount + 1);
         aiEquityTime[aiEquityCount]  = t;
         aiEquityValue[aiEquityCount] = e;
         aiEquityCount++;
      }
   }
   FileClose(handle);

   if(aiEquityCount > AI_MAX_EQUITY_HISTORY)
   {
      int trimCount = aiEquityCount - AI_MAX_EQUITY_HISTORY;
      for(int i = 0; i < AI_MAX_EQUITY_HISTORY; i++)
      {
         aiEquityTime[i]  = aiEquityTime[i + trimCount];
         aiEquityValue[i] = aiEquityValue[i + trimCount];
      }
      ArrayResize(aiEquityTime,  AI_MAX_EQUITY_HISTORY);
      ArrayResize(aiEquityValue, AI_MAX_EQUITY_HISTORY);
      aiEquityCount = AI_MAX_EQUITY_HISTORY;
   }
   Print("EA: Zeus AI loaded ", aiEquityCount, " equity history snapshots.");
}

// Appends one (time, equity) snapshot -- called once per closed brick,
// same cadence the training data used. Appends to the file (not a full
// rewrite) since this log only ever grows-then-trims.
void AI_SaveEquitySnapshot(datetime t, double eq)
{
   ArrayResize(aiEquityTime,  aiEquityCount + 1);
   ArrayResize(aiEquityValue, aiEquityCount + 1);
   aiEquityTime[aiEquityCount]  = t;
   aiEquityValue[aiEquityCount] = eq;
   aiEquityCount++;

   if(aiEquityCount > AI_MAX_EQUITY_HISTORY)
   {
      int trimCount = aiEquityCount - AI_MAX_EQUITY_HISTORY;
      for(int i = 0; i < AI_MAX_EQUITY_HISTORY; i++)
      {
         aiEquityTime[i]  = aiEquityTime[i + trimCount];
         aiEquityValue[i] = aiEquityValue[i + trimCount];
      }
      ArrayResize(aiEquityTime,  AI_MAX_EQUITY_HISTORY);
      ArrayResize(aiEquityValue, AI_MAX_EQUITY_HISTORY);
      aiEquityCount = AI_MAX_EQUITY_HISTORY;
   }

   int handle = FileOpen(AI_EquityFile, FILE_READ|FILE_WRITE|FILE_CSV|FILE_COMMON);
   if(handle != INVALID_HANDLE)
   {
      FileSeek(handle, 0, SEEK_END);
      FileWrite(handle, TimeToStr(t, TIME_DATE|TIME_SECONDS), DoubleToStr(eq, 2));
      FileClose(handle);
   }
}

// Trailing AI_QuotaWindowDays-day return: current equity vs. the most
// recent snapshot at or before (now - window). Falls back to the oldest
// snapshot available if history doesn't reach back that far yet -- same
// convention as the Python training environment.
double AI_TrailingReturn(datetime now, double currentEquity)
{
   datetime cutoff = now - AI_QuotaWindowDays * 86400;
   double pastEquity = AI_RefBalance;
   bool found = false;
   for(int i = aiEquityCount - 1; i >= 0; i--)
   {
      if(aiEquityTime[i] <= cutoff)
      {
         pastEquity = aiEquityValue[i];
         found = true;
         break;
      }
   }
   if(!found && aiEquityCount > 0)
      pastEquity = aiEquityValue[0];
   if(pastEquity <= 0) return 0.0;
   return (currentEquity / pastEquity) - 1.0;
}

// Mirrors decode_action() in quota_environment.py exactly: action 0 =
// skip; actions 1-9 = (stop-distance x take-profit-profile) combination.
// SL choices: 400/600/800 points = 40/60/80 pips. TP profiles (points):
// tight=[400,800,1200,0] standard=[600,1200,1800,0] wide=[800,1600,2400,0].
bool AI_DecodeAction(int action, int &slPoints, int &tp0, int &tp1, int &tp2, int &tp3)
{
   if(action == 0) return false;

   int idx   = action - 1;
   int slIdx = idx / 3;
   int tpIdx = idx % 3;

   int slChoices[3] = {400, 600, 800};
   slPoints = slChoices[slIdx];

   if(tpIdx == 0)      { tp0 = 400; tp1 = 800;  tp2 = 1200; tp3 = 0; } // tight
   else if(tpIdx == 1) { tp0 = 600; tp1 = 1200; tp2 = 1800; tp3 = 0; } // standard
   else                { tp0 = 800; tp1 = 1600; tp2 = 2400; tp3 = 0; } // wide

   return true;
}

// Builds the same 5 features training used (rc_value, rmc_value,
// trailing-pace-vs-target, log-equity-ratio, in-position flag -- always
// 0 here since this is only ever called when CountTrades()==0, exactly
// as in training) and returns the greedy (argmax) action.
int AI_Decide()
{
   // rmc_value feature is the raw reading unconditionally -- training never
   // gated this on UseRMCFilter, only the entry GATE (already evaluated
   // before AI_Decide() is ever called) depends on that setting.
   double rc     = GetRC_Value();
   double rmcRaw = GetRMC_Value();
   double rmc    = (rmcRaw == EMPTY_VALUE) ? 0.0 : rmcRaw;

   double equity      = AccountEquity();
   double trailingRet  = AI_TrailingReturn(TimeCurrent(), equity);
   double pace         = trailingRet - (AI_QuotaTargetPct / 100.0);
   double logEq        = MathLog(MathMax(equity, 1.0) / MathMax(AI_RefBalance, 1.0));
   double inPos         = (CountTrades() > 0) ? 1.0 : 0.0;

   double x[5];
   x[0] = rc;
   x[1] = rmc;
   x[2] = pace;
   x[3] = logEq;
   x[4] = inPos;

   double q[10];
   ZAI_Forward(x, q);

   int    bestAction = 0;
   double bestQ      = q[0];
   for(int a = 1; a < ZAI_OUT; a++)
   {
      if(q[a] > bestQ) { bestQ = q[a]; bestAction = a; }
   }

   Print("EA: Zeus AI decide -- rc=", DoubleToStr(rc,4), " rmc=", DoubleToStr(rmc,4),
         " pace=", DoubleToStr(pace,4), " logEq=", DoubleToStr(logEq,4),
         " -> action=", bestAction);
   return bestAction;
}

// Draw the standard MT4 entry flag at the fill: blue up-arrow (Wingdings 241)
// for a buy, red down-arrow (242) for a sell. Entry markers only - no exit
// arrows, no connecting lines.
void DrawEntryFlag(datetime dt, double price, bool isBuy)
{
   static int flagSeq = 0;
   flagSeq++;
   string name = "ZeusFlag_" + IntegerToString(flagSeq);
   ObjectCreate(0, name, OBJ_ARROW, 0, dt, price);
   ObjectSetInteger(0, name, OBJPROP_ARROWCODE, isBuy ? 241 : 242);
   ObjectSetInteger(0, name, OBJPROP_COLOR,     isBuy ? clrBlue : clrRed);
   ObjectSetInteger(0, name, OBJPROP_WIDTH,     2);
   ObjectSetInteger(0, name, OBJPROP_SELECTABLE, false);
}

int GetRC_CrossoverSignal()
{
   // Read shift 0 (just closed) vs shift 1 (previous) to detect
   // crossover on the exact brick it occurred
   double blue1   = GetRC_BlueLine(0);
   double maroon1 = GetRC_MaroonLine(0);
   double blue2   = GetRC_BlueLine(1);
   double maroon2 = GetRC_MaroonLine(1);

   bool blueNow    = (blue1   != EMPTY_VALUE && blue1   != 0);
   bool maroonNow  = (maroon1 != EMPTY_VALUE && maroon1 != 0);
   bool bluePrev   = (blue2   != EMPTY_VALUE && blue2   != 0);
   bool maroonPrev = (maroon2 != EMPTY_VALUE && maroon2 != 0);

   if(blueNow && maroonNow && !bluePrev && maroonPrev)   return  1;
   if(maroonNow && blueNow && !maroonPrev && bluePrev)   return -1;

   if(blueNow && maroonNow)
   {
      if(MathAbs(blue1) > MathAbs(maroon1)) return  1;
      if(MathAbs(maroon1) > MathAbs(blue1)) return -1;
   }
   return 0;
}

// +------------------------------------------------------------------+
// GetLotSize
// +------------------------------------------------------------------+
double GetLotSize(int weightPct, int slPoints)
{
   double minLot  = MarketInfo(Symbol(), MODE_MINLOT);
   double maxLot  = MarketInfo(Symbol(), MODE_MAXLOT);
   double lotStep = MarketInfo(Symbol(), MODE_LOTSTEP);
   if(minLot  <= 0) minLot  = 0.01;
   if(maxLot  <= 0) maxLot  = 100.0;
   if(lotStep <= 0) lotStep = 0.01;

   // Hard cap at broker maximum and user-defined maximum
   double hardMax = MathMin(maxLot, MaxLotsPerTrade);

   double totalRiskMoney = AccountBalance() * TotalRiskPercent / 100.0;
   double tradeMoney     = totalRiskMoney * weightPct / 100.0;

   double tickValue = MarketInfo(Symbol(), MODE_TICKVALUE);
   double tickSize  = MarketInfo(Symbol(), MODE_TICKSIZE);
   if(tickValue <= 0 || tickSize <= 0) return(minLot);

   // slPoints is whichever stop distance was used for THIS trade (fixed
   // StopLossPoints, or the AI's chosen distance) -- dollar risk per leg
   // is always TotalRiskPercent * weight%, no matter which one that is.
   double slTicks     = (slPoints * Point) / tickSize;
   double moneyPerLot = slTicks * tickValue;
   if(moneyPerLot <= 0) return(minLot);

   double lots = tradeMoney / moneyPerLot;
   lots = MathFloor(lots / lotStep) * lotStep;
   lots = MathMax(lots, minLot);
   lots = MathMin(lots, hardMax);
   lots = NormalizeDouble(lots, 2);

   // Log only when lot is capped at maximum
   if(lots >= hardMax)
      Print("EA: LotSize [CAPPED AT MAX] weight=", weightPct,
            "% lots=", DoubleToStr(lots,2));

   return(lots);
}

// +------------------------------------------------------------------+
// OpenTrade
// +------------------------------------------------------------------+
void OpenTrade(int type, double entry, double candleClose,
               int tpPoints, string label, int weightPct, int slPoints)
{
   double vsl = (type == OP_BUY)
                ? NormalizeDouble(candleClose - slPoints * Point, Digits)
                : NormalizeDouble(candleClose + slPoints * Point, Digits);

   double vtp = 0;
   if(tpPoints > 0)
      vtp = (type == OP_BUY)
            ? NormalizeDouble(candleClose + tpPoints * Point, Digits)
            : NormalizeDouble(candleClose - tpPoints * Point, Digits);

   double lots   = GetLotSize(weightPct, slPoints);
   int    ticket = OrderSend(Symbol(), type, lots, entry, Slippage,
                              0, 0, label, MagicNumber, 0);
   if(ticket < 0)
   {
      Print("OrderSend FAILED [", label, "] err=", GetLastError());
      return;
   }

   VirtualStore(ticket, vsl, vtp, candleClose);

   // Entry flag on the SIGNAL bar (shift 1) - the bar RC/RMC/brick were
   // evaluated on - not the forming bar. Drawing at TimeCurrent put the flag
   // one bar ahead of the bar the filter tested, making every trade look like
   // it sat on the wrong side of the filter's zero line.
   DrawEntryFlag(Time[1], candleClose, type == OP_BUY);

   Print("EA: Opened [", label, "] ticket=", ticket,
         " Lots=", DoubleToStr(lots, 2),
         " Weight=", weightPct, "%",
         " CandleClose=", candleClose,
         " SLPoints=", slPoints,
         " VSL=", vsl,
         " VTP=", (vtp > 0 ? DoubleToStr(vtp, Digits) : "none"));
}

// +------------------------------------------------------------------+
void OpenAll(int type, int slPoints, int &tpPoints[])
{
   // Entry price: live Ask for buys, live Bid for sells
   // This is the actual fill price the broker uses
   double entry = NormalizeDouble((type == OP_BUY) ? Ask : Bid, Digits);

   // CandleClose: the CLOSING PRICE of the signal brick (Close[1] at candle close)
   // ALL SL, TP and BE levels are calculated from this price - not the fill price
   // This is the price the arrow appeared on and the decision was made
   double candleClose = NormalizeDouble(Close[1], Digits);

   if(Trade1Enabled) OpenTrade(type, entry, candleClose, tpPoints[0], "T1", T1_Weight, slPoints);
   if(Trade2Enabled) OpenTrade(type, entry, candleClose, tpPoints[1], "T2", T2_Weight, slPoints);
   if(Trade3Enabled) OpenTrade(type, entry, candleClose, tpPoints[2], "T3", T3_Weight, slPoints);
   if(Trade4Enabled) OpenTrade(type, entry, candleClose, tpPoints[3], "T4", T4_Weight, slPoints);

   T1_WasOpen         = true;
   BreakEvenTriggered = false;
   GlobalVariableSet(GV_T1(),  1.0);
   GlobalVariableSet(GV_BEF(), 0.0);

   Print("EA: Opened ", (type == OP_BUY) ? "BUY" : "SELL",
         " x4 | Entry=", entry, " | CandleClose=", candleClose,
         " | TotalRisk=", TotalRiskPercent, "% | SLPoints=", slPoints);

   // Update known tickets so manual close detector tracks these new trades
   knownTicketCount = 0;
   ArrayResize(knownTickets, 0);
   for(int nt = 0; nt < OrdersTotal(); nt++)
   {
      if(!OrderSelect(nt, SELECT_BY_POS, MODE_TRADES)) continue;
      if(OrderMagicNumber() != MagicNumber || OrderSymbol() != Symbol()) continue;
      ArrayResize(knownTickets, knownTicketCount + 1);
      knownTickets[knownTicketCount++] = OrderTicket();
   }
}

// +------------------------------------------------------------------+
int CountTrades()
{
   int n = 0;
   for(int i = 0; i < OrdersTotal(); i++)
      if(OrderSelect(i, SELECT_BY_POS, MODE_TRADES))
         if(OrderMagicNumber() == MagicNumber && OrderSymbol() == Symbol())
            n++;
   return n;
}

bool ExistsT1()
{
   for(int i = 0; i < OrdersTotal(); i++)
      if(OrderSelect(i, SELECT_BY_POS, MODE_TRADES))
         if(OrderMagicNumber() == MagicNumber && OrderSymbol() == Symbol())
            if(OrderComment() == "T1") return true;
   return false;
}

// +------------------------------------------------------------------+
// CheckVirtualSL - candle close only
// +------------------------------------------------------------------+
void CheckVirtualSL()
{
   double candleClose = Close[1];

   for(int i = OrdersTotal() - 1; i >= 0; i--)
   {
      if(!OrderSelect(i, SELECT_BY_POS, MODE_TRADES)) continue;
      if(OrderMagicNumber() != MagicNumber || OrderSymbol() != Symbol()) continue;

      int    ticket = OrderTicket();
      double vsl    = VirtualGetSL(ticket);
      if(vsl == 0) continue;

      bool hit = false;
      if(OrderType() == OP_BUY  && candleClose <= vsl) hit = true;
      if(OrderType() == OP_SELL && candleClose >= vsl) hit = true;

      if(hit)
      {
         double cp = (OrderType() == OP_BUY) ? Bid : Ask;
         if(OrderClose(ticket, OrderLots(), cp, Slippage))
         {
            Print("EA: VSL hit - closed ticket=", ticket,
                  " CandleClose=", candleClose, " VSL=", vsl);
            VirtualRemove(ticket);
            RemoveKnownTicket(ticket);
         }
         else
            Print("EA: VSL close FAILED ticket=", ticket, " err=", GetLastError());
      }
   }
}

// +------------------------------------------------------------------+
// CheckVirtualTP - candle close only
// +------------------------------------------------------------------+
void CheckVirtualTP()
{
   double candleClose = Close[1];

   for(int i = OrdersTotal() - 1; i >= 0; i--)
   {
      if(!OrderSelect(i, SELECT_BY_POS, MODE_TRADES)) continue;
      if(OrderMagicNumber() != MagicNumber || OrderSymbol() != Symbol()) continue;

      int    ticket = OrderTicket();
      double vtp    = VirtualGetTP(ticket);
      if(vtp == 0) continue;

      bool hit = false;
      if(OrderType() == OP_BUY  && candleClose >= vtp) hit = true;
      if(OrderType() == OP_SELL && candleClose <= vtp) hit = true;

      if(hit)
      {
         double cp = (OrderType() == OP_BUY) ? Bid : Ask;
         if(OrderClose(ticket, OrderLots(), cp, Slippage))
         {
            Print("EA: VTP hit - closed ticket=", ticket,
                  " CandleClose=", candleClose, " VTP=", vtp);
            VirtualRemove(ticket);
            RemoveKnownTicket(ticket);
         }
         else
            Print("EA: VTP close FAILED ticket=", ticket, " err=", GetLastError());
      }
   }
}

// +------------------------------------------------------------------+
// MoveAllToBE
// Moves virtual SL to the entry candle close price.
// +------------------------------------------------------------------+
void MoveAllToBE()
{
   for(int i = 0; i < OrdersTotal(); i++)
   {
      if(!OrderSelect(i, SELECT_BY_POS, MODE_TRADES)) continue;
      if(OrderMagicNumber() != MagicNumber || OrderSymbol() != Symbol()) continue;

      int    ticket  = OrderTicket();
      double bePrice = VirtualGetBEPrice(ticket);
      double curSL   = VirtualGetSL(ticket);

      if(OrderType() == OP_BUY  && curSL < bePrice)
      {
         VirtualUpdateSL(ticket, bePrice);
         Print("EA: BE - ticket=", ticket, " VSL moved to ", bePrice);
      }
      if(OrderType() == OP_SELL && (curSL > bePrice || curSL == 0))
      {
         VirtualUpdateSL(ticket, bePrice);
         Print("EA: BE - ticket=", ticket, " VSL moved to ", bePrice);
      }
   }
}

// +------------------------------------------------------------------+
// CheckBreakEven - fires when T1 closes at TP
// +------------------------------------------------------------------+
void CheckBreakEven()
{
   if(BreakEvenTriggered || !T1_WasOpen) return;
   if(!ExistsT1())
   {
      MoveAllToBE();
      BreakEvenTriggered = true;
      T1_WasOpen         = false;
      GlobalVariableSet(GV_BEF(), 1.0);
      GlobalVariableSet(GV_T1(),  0.0);
   }
}

// +------------------------------------------------------------------+
void CloseAll()
{
   bool closedOne = true;
   while(closedOne)
   {
      closedOne = false;
      for(int i = OrdersTotal() - 1; i >= 0; i--)
      {
         if(!OrderSelect(i, SELECT_BY_POS, MODE_TRADES)) continue;
         if(OrderMagicNumber() != MagicNumber || OrderSymbol() != Symbol()) continue;
         int    t      = OrderTicket();
         bool   wasBuy = (OrderType() == OP_BUY);
         double cp = wasBuy ? Bid : Ask;
         if(OrderClose(t, OrderLots(), cp, Slippage))
         {
            VirtualRemove(t);
            RemoveKnownTicket(t);
            closedOne = true;
            break;
         }
      }
   }
   // Clear known tickets so manual close detector ignores these closes
   knownTicketCount = 0;
   ArrayResize(knownTickets, 0);
}

// +------------------------------------------------------------------+
bool IsNearWeekendClose()
{
   if(KeepTradesOverWeekend) return false;
   MqlDateTime dt;
   TimeToStruct(TimeCurrent(), dt);
   if(dt.day_of_week != 5) return false;
   if(dt.hour > MarketCloseHour) return true;
   if(dt.hour == MarketCloseHour && dt.min >= MarketCloseMinute) return true;
   return false;
}

// +------------------------------------------------------------------+
void OnTick()
{
   // ================================================================
   // GATE 1: Respect AutoTrading button - absolute first check
   // ================================================================
   if(!IsTradeAllowed()) return;

   // Weekend close
   if(IsNearWeekendClose()) { CloseAll(); return; }

   // ================================================================
   // VIRTUAL SL/TP: checked every tick, ALWAYS, before any lockout gate.
   // Deliberately placed here (not after GATE 2) so a restart -- including
   // one that happens to land while the market is closed, when the startup
   // lockout below can take much longer than its nominal 2 minutes to
   // clear -- can never suspend an already-open trade's SL/TP protection.
   // vSL/vTP were already restored (from file, GlobalVariables, or the
   // OrderOpenPrice fallback) by RestoreStateFromGlobalVariables() in
   // OnInit() before OnTick() ever runs, and this only ever compares them
   // against Close[1] (the last FULLY CLOSED brick), never live Bid/Ask -
   // so there is no "chart might still be rebuilding" risk here the way
   // there is for new entries and the discretionary RC-flip exit below.
   // ================================================================
   CheckVirtualSL();
   CheckVirtualTP();

   // ================================================================
   // GATE 2: Startup lockout (2 real minutes after restart with open
   // trades) - blocks NEW ENTRIES and the discretionary RC-flip exit
   // only, since those trust freshly-(re)computed RC/RMC indicator
   // direction, which can't yet be trusted if the Renko chart is still
   // being rebuilt. Existing trades' virtual SL/TP were already checked
   // above, unconditionally, before this gate runs.
   //
   // Elapsed time is measured with GetTickCount() (real wall-clock
   // milliseconds since terminal start), NOT TimeCurrent(). TimeCurrent()
   // is the broker's last-known-quote time, which freezes while the
   // market is closed (e.g. a Sunday reboot before the session reopens)
   // and can jump forward by an hour or more the instant a new quote
   // arrives -- that stale-clock behavior was letting this "2 minute"
   // lockout silently stretch for 90+ minutes, during which the old code
   // also blocked SL/TP checks on already-open trades (fixed above).
   // ================================================================
   if(StartupLockout)
   {
      int elapsedMs = (int)(GetTickCount() - StartupTickCount);
      int elapsed   = elapsedMs / 1000;
      if(elapsed >= LOCKOUT_MINUTES * 60)
      {
         StartupLockout = false;
         ReadyToTrade   = true;
         Print("EA: Startup lockout expired. Resuming full management (new entries + RC-flip exits).");
      }
      else
      {
         static int lastLockLogTick = 0;
         if((int)(GetTickCount() - lastLockLogTick) >= 30000)
         {
            Print("EA: New-entry lockout. ", (LOCKOUT_MINUTES*60 - elapsed),
                  "s remaining. Existing trades' SL/TP still being checked. Fix Renko chart now.");
            lastLockLogTick = GetTickCount();
         }
         return; // Block new entries + RC-flip exits only during lockout
      }
   }

   // ================================================================
   // GATE 3: Manual unlock required after restart with no open trades
   // Blocks entries until Renko Reset script runs, OR auto-releases
   // after RenkoResetTimeoutSeconds if the script isn't run in time.
   // ================================================================
   if(!ManualUnlocked && !ReadyToTrade && CountTrades() == 0)
   {
      if(BypassRenkoResetGate)
      {
         ManualUnlocked = true;
         Print("EA: Renko-reset gate BYPASSED (tester flag on).");
      }
      else if(FileIsExist(UNLOCK_FLAG, FILE_COMMON))
      {
         ManualUnlocked = true;
         FileDelete(UNLOCK_FLAG, FILE_COMMON);
         Print("EA: Renko Reset detected. Entries unlocked.");
      }
      else if(RenkoResetTimeoutSeconds > 0 && NoTradesGateStartTime > 0 &&
              (TimeCurrent() - NoTradesGateStartTime) >= RenkoResetTimeoutSeconds)
      {
         ManualUnlocked = true;
         Print("EA: Renko Reset script not run within ", RenkoResetTimeoutSeconds,
               "s of attach - auto-releasing entries.");
      }
      else return;
   }

   // ================================================================
   // MANUAL CLOSE DETECTION: runs every tick
   // Compares live tickets against known tickets.
   // Any missing ticket not removed by EA = manual close detected.
   // Save ticket BEFORE OrderSelect context is lost.
   // ================================================================
   if(!WaitingForNewCycle && ReadyToTrade && knownTicketCount > 0)
   {
      for(int ki = 0; ki < knownTicketCount; ki++)
      {
         bool stillOpen = false;
         for(int oi = 0; oi < OrdersTotal(); oi++)
         {
            if(!OrderSelect(oi, SELECT_BY_POS, MODE_TRADES)) continue;
            if(OrderMagicNumber() != MagicNumber || OrderSymbol() != Symbol()) continue;
            if(OrderTicket() == knownTickets[ki]) { stillOpen = true; break; }
         }
         if(!stillOpen)
         {
            // This ticket disappeared without EA removing it = manual close
            double rcAtClose  = GetRC_Value();
            double rmcAtClose = GetRMC_Value();
            WaitingForNewCycle    = true;
            CycleWaitDirection    = (rcAtClose > 0) ? 1 : -1;
            RMCCycleWaitDirection = RMC_Dir(rmcAtClose);
            ReadyToTrade       = false;
            knownTicketCount   = 0;
            ArrayResize(knownTickets, 0);
            Print("EA: Manual close detected (ticket ", knownTickets[ki],
                  " missing). RC dir=", CycleWaitDirection,
                  " RMC dir=", RMCCycleWaitDirection,
                  ". Waiting for EITHER to flip before re-entry.");
            break;
         }
      }
   }

   // ================================================================
   // NEW CYCLE WAIT: blocks entries until EITHER RC or RMC flips direction
   // once (OR logic, same rule as ReadyToTrade on attach) -- either one
   // flipping is enough, they no longer both have to.
   // ================================================================
   if(WaitingForNewCycle)
   {
      double rcCycle       = GetRC_Value();
      int    rcDirNow       = (rcCycle > 0) ? 1 : (rcCycle < 0) ? -1 : 0;
      bool   rcCycleFlipped = (rcDirNow != 0 && rcDirNow != CycleWaitDirection);

      double rmcCycle       = GetRMC_Value();
      int    rmcDirNow       = RMC_Dir(rmcCycle);
      bool   rmcCycleFlipped = (rmcDirNow != 0) && (rmcDirNow != RMCCycleWaitDirection);

      if(rcCycleFlipped || rmcCycleFlipped)
      {
         WaitingForNewCycle = false;
         ReadyToTrade       = true;
         string cycleReason = "";
         if(rcCycleFlipped)  cycleReason += "RC flipped to " + IntegerToString(rcDirNow) + ". ";
         if(rmcCycleFlipped) cycleReason += "RMC flipped to " + IntegerToString(rmcDirNow) + ".";
         Print("EA: ", cycleReason, " Manual close cycle reset complete. Re-entry allowed.");
      }
      // Always return while waiting - no SL/TP/entry while waiting for cycle
      // Exception: existing open trades still get managed at candle close below
      if(WaitingForNewCycle && CountTrades() == 0) return;
   }

   // ================================================================
   // READY TO TRADE: arms (OR logic) as soon as EITHER RC or RMC changes
   // from its own initial-load direction -- either one flipping is
   // enough, they no longer both have to.
   // ================================================================
   if(!ReadyToTrade)
   {
      double rcNow    = GetRC_Value();
      int    rcDirNow = (rcNow > 0) ? 1 : (rcNow < 0) ? -1 : 0;
      bool   rcFlipped = (rcDirNow != 0 && rcDirNow != InitialRC_Direction);

      double rmcNow    = GetRMC_Value();
      int    rmcDirNow = RMC_Dir(rmcNow);
      bool   rmcFlipped = (rmcDirNow != 0) && (rmcDirNow != InitialRMC_Direction);

      if(rcFlipped || rmcFlipped)
      {
         ReadyToTrade = true;
         string reason = "";
         if(rcFlipped)
            reason += "RC flipped to " + IntegerToString(rcDirNow) + " from initial " + IntegerToString(InitialRC_Direction) + ". ";
         if(rmcFlipped)
            reason += "RMC flipped to " + IntegerToString(rmcDirNow) + " from initial " + IntegerToString(InitialRMC_Direction) + ".";
         Print("EA: ReadyToTrade armed. ", reason);
      }
   }

   // ================================================================
   // CANDLE CLOSE LOGIC
   // Entries and break-even management still fire at candle close only
   // ================================================================
   bool newBar = IsNewBar();
   if(!newBar) return;

   // --- Zeus AI: one equity snapshot per closed brick, same cadence training used ---
   AI_SaveEquitySnapshot(Time[1], AccountEquity());

   // --- Break-even ---
   CheckBreakEven();

   // --- Clean up flags when flat ---
   if(CountTrades() == 0)
   {
      BreakEvenTriggered = false;
      T1_WasOpen         = false;
      GlobalVariableSet(GV_BEF(), 0.0);
      GlobalVariableSet(GV_T1(),  0.0);
   }

   // --- RC EXIT ---
   // Close trades when RC flips against the open direction, gated by the
   // reversal-brick and RMC checks below so exit conditions mirror entry.
   // The virtual SL remains the independent backstop for genuine reversals.
   if(CountTrades() > 0)
   {
      double rcExit = GetRC_Value();

      // RMC exit gate: block the RC reversal exit until RMC agrees with the
      // reversal direction. A buy may only be RC-closed when RMC < 0 (red);
      // a sell only when RMC > 0 (blue) -- matches the entry rule exactly
      // (both must agree). SL and TP are unaffected and still fire above -
      // this only holds back the discretionary RC exit.
      double rmcExit    = UseRMCFilter ? GetRMC_Value() : 0.0;
      int    rmcExitDir = UseRMCFilter ? RMC_Dir(rmcExit) : 0;

      // Reversal-brick gate: the just-closed brick must print in the reversal
      // direction (bear brick to close a buy, bull brick to close a sell).
      // This mirrors the entry brick gate so exit and entry conditions line up
      // - the moment a buy qualifies to close, the reverse sell also qualifies
      // to open, giving a clean same-bar reversal instead of going flat.
      int brickDir = ClosedBrickDir();

      bool   moreToClose = true;
      while(moreToClose)
      {
         moreToClose = false;
         for(int i = OrdersTotal() - 1; i >= 0; i--)
         {
            if(!OrderSelect(i, SELECT_BY_POS, MODE_TRADES)) continue;
            if(OrderMagicNumber() != MagicNumber || OrderSymbol() != Symbol()) continue;

            bool flip = (OrderType()==OP_BUY  && rcExit < 0) ||
                        (OrderType()==OP_SELL && rcExit > 0);
            if(!flip) continue;

            // Reversal-brick gate: close a buy only on a bear brick, a sell
            // only on a bull brick (matches the entry brick-direction rule).
            if(OrderType()==OP_BUY  && brickDir != -1) continue;
            if(OrderType()==OP_SELL && brickDir !=  1) continue;

            // RMC agreement gate: hold the exit until RMC confirms. Matches
            // the entry rule exactly so entry and exit stay symmetric -- a
            // buy closes exactly when the sell entry condition (RC<0 AND
            // RMC<0) would fire, and vice versa, so the reversal happens
            // cleanly on the same bar instead of going flat first. Buy
            // exits need RMC < 0 (red), sell exits need RMC > 0 (blue).
            if(UseRMCFilter)
            {
               if(rmcExitDir == 0) continue;                    // no clear red/blue reading - do not exit
               if(OrderType()==OP_BUY  && rmcExitDir != -1) continue; // buy exit needs RMC clearly red
               if(OrderType()==OP_SELL && rmcExitDir !=  1) continue; // sell exit needs RMC clearly blue
            }

            int    t      = OrderTicket();
            bool   wasBuy = (OrderType() == OP_BUY);
            double cp     = wasBuy ? Bid : Ask;
            if(OrderClose(t, OrderLots(), cp, Slippage))
            {
               Print("EA: RC exit closed ticket=", t,
                     " rc=", DoubleToStr(rcExit, 3));
               VirtualRemove(t);
               RemoveKnownTicket(t);
               moreToClose = true;
               break;
            }
            else
               Print("EA: RC exit FAILED ticket=", t, " err=", GetLastError());
         }
      }
      if(CountTrades() == 0)
      {
         knownTicketCount = 0;
         ArrayResize(knownTickets, 0);
         BreakEvenTriggered = false;
         T1_WasOpen         = false;
         GlobalVariableSet(GV_BEF(), 0.0);
         GlobalVariableSet(GV_T1(),  0.0);
      }
   }

   // --- ENTRY-STATE DIAGNOSTIC (fires every closed brick, before any gate) ---
   {
      double dRc   = GetRC_Value();
      int    dRcD  = (dRc > 0) ? 1 : (dRc < 0) ? -1 : 0;
      int    dBr   = ClosedBrickDir();
      double dRmc  = UseRMCFilter ? GetRMC_Value() : 0.0;
      int    dRmcD = UseRMCFilter ? RMC_Dir(dRmc) : 0;
      int    dDir  = 0;
      if(UseRMCFilter)
      {
         if(dRcD < 0 && dRmcD < 0)      dDir = -1;
         else if(dRcD > 0 && dRmcD > 0) dDir =  1;
      }
      else dDir = dRcD;
      Print("ZEUS-ENTRY-STATE bar=", TimeToStr(Time[1], TIME_DATE|TIME_MINUTES),
            " rcDir=", dRcD, " brickDir=", dBr,
            " rmc=", (dRmc==EMPTY_VALUE?"EMPTY":DoubleToStr(dRmc,4)),
            " rmcDir=", dRmcD,
            " combinedDir=", dDir, " brickOK=", (dBr==dDir),
            " ready=", ReadyToTrade, " waitCycle=", WaitingForNewCycle,
            " trades=", CountTrades(), " allowNew=", AllowNewEntries);
   }

   // --- ENTRY CHECK ---
   // Direction requires RC and Renko Momentum Cycle (RMC) to AGREE in sign:
   //   RC < 0 (maroon) AND RMC < 0 (red)   -> SELL
   //   RC > 0 (blue)   AND RMC > 0 (blue)  -> BUY
   //   anything else (disagreement, either exactly zero, or no valid RMC
   //   read) -> no entry
   // If UseRMCFilter is off, RMC is ignored entirely and RC alone sets
   // direction.
   // Still required either way: the just-closed brick must print IN the
   // trade direction (bull brick for a buy, bear brick for a sell) - never
   // enter against the active brick.
   if(ReadyToTrade && !WaitingForNewCycle &&
      CountTrades() == 0 && AllowNewEntries)
   {
      double rcEntry  = GetRC_Value();
      int    rcDir    = (rcEntry > 0) ? 1 : (rcEntry < 0) ? -1 : 0;
      int    brickDir = ClosedBrickDir();

      int    entryDir = 0;
      if(UseRMCFilter)
      {
         double rmc    = GetRMC_Value();
         int    rmcDir = RMC_Dir(rmc);
         if(rcDir < 0 && rmcDir < 0)      entryDir = -1; // both clearly below zero -> sell
         else if(rcDir > 0 && rmcDir > 0) entryDir =  1; // both clearly above zero -> buy
         // DIAGNOSTIC - port's RMC read vs. what RMC.mq4 itself would plot.
         Print("ZEUS-FILTER[PORT] bar=", TimeToStr(Time[1], TIME_DATE|TIME_MINUTES),
               " c1=", DoubleToStr(Close[1],Digits),
               " c2=", DoubleToStr(Close[2],Digits),
               " c10=", DoubleToStr(Close[10],Digits),
               " bars=", Bars,
               " rcDir=", rcDir, " rmcDir=", rmcDir, " entryDir=", entryDir,
               " rmc=", (rmc==EMPTY_VALUE?"EMPTY":DoubleToStr(rmc,4)),
               " run=", g_rmcCacheRun, " rsiPeriod=", g_rmcCacheRsiPeriod,
               " decay=", DoubleToStr(g_rmcCacheDecay,4));
      }
      else
         entryDir = rcDir;

      bool dirOK   = (entryDir != 0);
      bool brickOK = (brickDir == entryDir);

      if(dirOK && brickOK)
      {
         if(UseZeusAI)
         {
            int action = AI_Decide();
            int slPts, tp0, tp1, tp2, tp3;
            if(AI_DecodeAction(action, slPts, tp0, tp1, tp2, tp3))
            {
               int tpArr[4];
               tpArr[0] = tp0; tpArr[1] = tp1; tpArr[2] = tp2; tpArr[3] = tp3;
               if(entryDir > 0) OpenAll(OP_BUY,  slPts, tpArr);
               else              OpenAll(OP_SELL, slPts, tpArr);
            }
            else
               Print("EA: Zeus AI chose to SKIP this signal (action=0).");
         }
         else
         {
            int tpArrFixed[4];
            tpArrFixed[0] = TP1; tpArrFixed[1] = TP2; tpArrFixed[2] = TP3; tpArrFixed[3] = TP4;
            if(entryDir > 0) OpenAll(OP_BUY,  StopLossPoints, tpArrFixed);
            else              OpenAll(OP_SELL, StopLossPoints, tpArrFixed);
         }
      }
   }

   // NOTE: the old immediate "OPPOSITE SIGNAL / CloseAll" block was removed.
   // Closing on an RC reversal is handled by the magnitude-gated RC EXIT block
   // above. A second immediate closer here would bypass the magnitude floor.

   // Log trades for desktop tracker
   LogTrades();
}
// +------------------------------------------------------------------+
