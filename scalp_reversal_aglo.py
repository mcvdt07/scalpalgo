"""
    Title: Short Term Reversal (Forex)
    Description: This is a long short strategy based on moving
        average signals. We also square off all positions at the end
        of the trading day to avoid any roll-over costs. The trade 
        size is fixed - mini lotsize (1000) multiplied by a leverage. 
        The leverage is a parameter, defaults to 1. Minimum capital 1000.
    Style tags: Momentum, Mean Reversion
    Asset class: Equities, Futures, ETFs and Currencies
    Dataset: FX Minute
"""
from blueshift_library.technicals.indicators import ema
from blueshift_library.utils.utils import square_off
##################################################################
#    Take profit / Stop loss
##################################################################
from functools import partial
##################################################################


# Zipline
from zipline.finance import commission, slippage
from zipline.api import(    symbol,
                            order_target,
                            set_commission,
                            set_slippage,
                            schedule_function,
                            date_rules,
                            time_rules,
                            set_account_currency
                       )
##################################################################
#    Take profit / Stop loss
##################################################################
from blueshift.api import (symbol, order_target, get_datetime, terminate,
                           on_data, on_trade, off_data, off_trade)
##################################################################


# for live

# accountCode = '8000131387'
# access_token = '5d215cc7c1fc34f7da95766c8d3c44f956e5fd4e'
# server='real'

# For demo
accountCode = '701522959'
access_token = '216883126b65a7bed7295c074144ee641f3c3621'
server='demo'


def initialize(context):
    """
        A function to define things to do at the start of the strategy
    """
    # set the account currency, only valid for backtests
    set_account_currency("USD")

    # lot-size (mini-lot for most brokers)
    context.lot_size = 200

    # universe selection
    context.securities = [
                               symbol('FXCM:AUD/USD'),
                               symbol('FXCM:EUR/CHF'),
                               symbol('FXCM:EUR/JPY'),
                               symbol('FXCM:EUR/USD'),
                               symbol('FXCM:GBP/USD'),
                               symbol('FXCM:NZD/USD'),
                               symbol('FXCM:USD/CAD'),
                               symbol('FXCM:USD/CHF'),
                               symbol('FXCM:USD/JPY'),
                             ]

    # define strategy parameters
    context.params = {'indicator_lookback':375,
                      'indicator_freq':'1m',
                      'buy_signal_threshold':0.5,
                      'sell_signal_threshold':-0.5,
                      'SMA_period_short':15,
                      'SMA_period_long':60,
                      'RSI_period':60,
                      'trade_freq':30,
                      'leverage':10,
                      'pip_cost':0.00003}
##################################################################
#    Take profit / Stop loss
##################################################################
    context.take_profit = 0.1
    # context.stop_loss = 0.0005
    context.traded = False
    context.entry_price = {}
    context.order_monitors = {}
    context.data_monitors = {}
    on_data(check_exit)
##################################################################    

    # variable to control trading frequency
    context.bar_count = 0
    context.trading_hours = False

    # variables to track signals and target portfolio
    context.signals = dict((security,0) for security in context.securities)
    context.target_position = dict((security,0) for security in context.securities)

    # set trading cost and slippage to zero
    set_commission(fx=commission.PipsCost(cost=context.params['pip_cost']))
    set_slippage(fx=slippage.FixedSlippage(0.00))

    # set a timeout for trading
    schedule_function(stop_trading,
                    date_rules.every_day(),
                    time_rules.market_close(hours=0, minutes=31))
    # call square off to zero out positions 30 minutes before close.
    schedule_function(daily_square_off,
                    date_rules.every_day(),
                    time_rules.market_close(hours=0, minutes=30))


def before_trading_start(context, data):
    """ set flag to true for trading. """
    context.trading_hours = True

def stop_trading(context, data):
    """ stop trading and prepare to square off."""
    context.trading_hours = False

def daily_square_off(context, data):
    """ square off all positions at the end of day."""
    context.trading_hours = False
    square_off(context)

def handle_data(context, data):
    """
        A function to define things to do at every bar
    """
    if context.trading_hours == False:
        return

    context.bar_count = context.bar_count + 1
    if context.bar_count < context.params['trade_freq']:
        return
        
    # time to trade, call the strategy function
    context.bar_count = 0
    run_strategy(context, data)
    

def run_strategy(context, data):
    """
        A function to define core strategy steps
    """
    generate_signals(context, data)
    generate_target_position(context, data)
    rebalance(context, data)

def rebalance(context,data):
    """
        A function to rebalance - all execution logic goes here
    """
    for security in context.securities:
        order_target(security, context.target_position[security])

def generate_target_position(context, data):
    """
        A function to define target portfolio
    """
    weight = context.lot_size*context.params['leverage']
    
    for security in context.securities:
        if context.signals[security] > context.params['buy_signal_threshold']:
            context.target_position[security] = weight
        elif context.signals[security] < context.params['sell_signal_threshold']:
            context.target_position[security] = -weight
        else:
            context.target_position[security] = 0
            


def generate_signals(context, data):
    """
        A function to define define the signal generation
    """
    try:
        price_data = data.history(context.securities, 'close',
            context.params['indicator_lookback'], context.params['indicator_freq'])
    except:
        return

    for security in context.securities:
        px = price_data.loc[:,security].values
        context.signals[security] = signal_function(px, context.params)

def signal_function(px, params):
    """
        The main trading logic goes here, called by generate_signals above
    """
    ind2 = ema(px, params['SMA_period_short'])
    ind3 = ema(px, params['SMA_period_long'])

    if ind2-ind3 > 0:
        return -1
    elif ind2-ind3 < 0:
        return 1
    else:
        return 0
##################################################################
#    Take profit / Stop loss
##################################################################
def check_exit(asset, context, data):
    """ this function is called on every data update. """
    px = data.current(asset, 'close')
    move = (px-context.entry_price[asset])/context.entry_price[asset]
    # print_msg(f'the move for {asset} is {move}')
    if move > context.take_profit:
        # we hit the take profit target, book profit and terminate
        order_target(asset, 0)
        # off_data()
        off_trade(callback)
        off_data(callback)
        # print_msg(f'booking profit for {asset} at {px} and turn off data monitor.')
        terminate()
    # elif move < -context.stop_loss:
    #     # we hit the stoploss, sqaure off and terminate
    #     order_target(asset, 0)
    #     off_data()
    #     print_msg(f'booking loss for {asset} at {px} and turn off data monitor.')
    #     terminate()

##################################################################




##################################################################
#    Take profit / Stop loss
##################################################################
# def print_msg(msg):
#     msg = f'{get_datetime()}:' + msg
#     print(msg)

# def check_order(order_id, asset, context, data):
#     """ this function is called on every trade update. """
#     orders = context.orders
#     if order_id in orders:
#         order = orders[order_id]
#         if order.pending > 0:
#             print_msg(f'order {order_id} is pending')
#             return
#         context.entry_price[asset] = order.average_price
#         on_data(partial(check_exit, asset))
#         off_trade(context.order_monitors[asset])
#         msg = f'traded order {order_id} for {asset} at '
#         msg = msg + f'{context.entry_price[asset]},'
#         msg = msg + ' set up exit monitor.'
#         print_msg(msg)

# def enter_trade(context, data):
#     """ this function is called only once at the beginning. """
#     if not context.traded:
#         px = data.current(context.assets, 'close')
#         # for more than one asset, set up a loop and create 
#         # the monitoring function using partial from functools
#         for asset in context.assets:
#             # place a limit order at the last price
#             order_id = order_target(asset, 1, px[asset])
#             f = partial(check_order, order_id, asset)
#             context.order_monitors[asset]=f
#             on_trade(f)
#             msg = f'placed a new trade {order_id} for {asset},'
#             msg = msg + ' and set up order monitor.'
#             print_msg(msg)
#         context.traded = True



# def initialize(context):
#     """ this function is called once at the start of the execution. """
#     context.assets = [
#                         symbol('FXCM:AUD/USD'),
#                         symbol('FXCM:EUR/CHF'), 
#                         symbol('FXCM:EUR/JPY'),
#                         symbol('FXCM:EUR/USD'),
#                         symbol('FXCM:GBP/USD'),
#                         symbol('FXCM:NZD/USD'),
#                         symbol('FXCM:USD/CAD'),
#                         symbol('FXCM:USD/CHF'),
#                         symbol('FXCM:USD/JPY'),
#                         ]
    
# def handle_data(context, data):
#     """ this function is called every minute. """
#     enter_trade(context, data)
##################################################################

