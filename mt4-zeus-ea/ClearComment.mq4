//+------------------------------------------------------------------+
//| ClearComment.mq4                                                 |
//| One-time script: clears any stuck Comment() text off the chart.  |
//+------------------------------------------------------------------+
#property strict

void OnStart()
{
   Comment("");
}
