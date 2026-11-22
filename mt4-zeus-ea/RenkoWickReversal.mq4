//+------------------------------------------------------------------+
//| RenkoWickReversal.mq4                                            |
//|                                                                  |
//| Marks Renko reversal bricks whose wick dipped back past the close
//| of the opposite-direction brick immediately before them:
//|
//|  Buy signal  : brick is a buy brick (Close > Open), the PREVIOUS
//|                brick was a sell brick (Close < Open), AND this
//|                brick's Low dipped below that previous sell brick's
//|                Close. Arrow plotted BELOW the brick.
//|
//|  Sell signal : brick is a sell brick (Close < Open), the PREVIOUS
//|                brick was a buy brick (Close > Open), AND this
//|                brick's High poked above that previous buy brick's
//|                Close. Arrow plotted ABOVE the brick.
//|
//| In other words: this only ever fires on the first brick of a new
//| direction (a reversal brick), when its wick overshoots back past
//| where the prior, opposite-direction brick had closed.
//|
//| "Previous brick" = the immediately preceding bar (shift+1), whatever
//| direction it closed. Meant for the same offline Renko chart this
//| project's other tools use, where each bar is one brick and shift 0
//| is the still-forming/live brick.
//|
//| Evaluated only on confirmed, already-closed bricks (shift >= 1) --
//| a still-forming brick's Low/High/Close aren't final yet, so shift 0
//| is left unevaluated until it closes, same convention used throughout
//| this project's other indicators and the EA's own decision logic.
//|
//| No MaxBarsToProcess cap here: unlike this project's other ported
//| indicators, this is a plain O(1)-per-bar comparison (no per-bar
//| window scan, sort, or recursive smoothing), so even a very deep
//| history computes in well under a second -- the freeze risk that cap
//| guards against doesn't apply.
//+------------------------------------------------------------------+
#property strict
#property indicator_chart_window
#property indicator_buffers 2
#property indicator_plots   2

#property indicator_label1  "Buy Wick Reversal"
#property indicator_type1   DRAW_ARROW
#property indicator_color1  clrLime
#property indicator_width1  2

#property indicator_label2  "Sell Wick Reversal"
#property indicator_type2   DRAW_ARROW
#property indicator_color2  clrRed
#property indicator_width2  2

input int    BrickSizePoints   = 200;  // Renko brick size in points (20 pips on a 5-digit USDJPY feed) -- used only to scale the arrow offset
input double ArrowOffsetFraction = 1.0; // Arrow distance from the brick's Low/High, as a fraction of one brick
input bool   EnableAlerts      = false;
input bool   EnablePush        = false;

double BufBuyArrow[], BufSellArrow[];

int OnInit()
{
   SetIndexBuffer(0, BufBuyArrow);
   SetIndexBuffer(1, BufSellArrow);
   SetIndexEmptyValue(0, EMPTY_VALUE);
   SetIndexEmptyValue(1, EMPTY_VALUE);

   SetIndexArrow(0, 233); // Wingdings up arrow -- buy
   SetIndexArrow(1, 234); // Wingdings down arrow -- sell

   IndicatorShortName("Renko Wick Reversal");
   return(INIT_SUCCEEDED);
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
   if(rates_total < 3) return(0);

   double offset = BrickSizePoints * Point * ArrowOffsetFraction;

   int start = (prev_calculated > 1) ? rates_total - prev_calculated : rates_total - 2;
   if(start > rates_total - 2) start = rates_total - 2;

   for(int i = start; i >= 1; i--)
   {
      BufBuyArrow[i]  = EMPTY_VALUE;
      BufSellArrow[i] = EMPTY_VALUE;

      bool isBuyBrick      = close[i] > open[i];
      bool isSellBrick     = close[i] < open[i];
      bool prevWasBuyBrick  = close[i + 1] > open[i + 1];
      bool prevWasSellBrick = close[i + 1] < open[i + 1];
      double prevClose = close[i + 1];

      if(isBuyBrick && prevWasSellBrick && low[i] < prevClose)
         BufBuyArrow[i] = low[i] - offset;

      if(isSellBrick && prevWasBuyBrick && high[i] > prevClose)
         BufSellArrow[i] = high[i] + offset;
   }
   BufBuyArrow[0]  = EMPTY_VALUE; // shift 0 is still forming -- not evaluated, see header
   BufSellArrow[0] = EMPTY_VALUE;

   if((EnableAlerts || EnablePush) && prev_calculated > 0)
   {
      static datetime lastAlertTime = 0;
      if(time[1] != lastAlertTime)
      {
         lastAlertTime = time[1];
         if(BufBuyArrow[1] != EMPTY_VALUE)
         {
            string m = "Renko buy wick-reversal brick closed on " + Symbol();
            if(EnableAlerts) Alert(m);
            if(EnablePush)   SendNotification(m);
         }
         if(BufSellArrow[1] != EMPTY_VALUE)
         {
            string m2 = "Renko sell wick-reversal brick closed on " + Symbol();
            if(EnableAlerts) Alert(m2);
            if(EnablePush)   SendNotification(m2);
         }
      }
   }

   return(rates_total);
}
//+------------------------------------------------------------------+
