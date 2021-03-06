from sent_orders_type import SentOrdersType
import sqlite3
import logging
import re
import datetime

class TradeDB:
    def __init__(self, db_file):
        self._db_file = db_file
        self.log = logging.getLogger('smart-trader')

    def create_db_connection(self, db_file):
        """ create a database connection to a SQLite database """
        try:
            conn = sqlite3.connect(db_file)
        except sqlite3.Error as e:
            self.log.error("db connection error",e)
            conn = None

        return conn

    def write_order_to_db(self, order_info):
        return_order_id = -1
        conn = self.create_db_connection(self._db_file)
        if conn is None:
            self.log.error("Can't connect to DB")
        else:
            try:
                if 'ask' not in order_info or 'bid' not in order_info:
                    order_info['ask'] = 0
                    order_info['bid'] = 0
                if 'balance' not in order_info or 'balances' not in order_info['balance']:
                    order_info['balance'] = {'balances': {order_info['currency_from']: {'available': 0},
                                                          order_info['currency_to']: {'available': 0}}}
                trade_order_id = -1
                if 'trade_order_id' in order_info:
                    trade_order_id = order_info['trade_order_id']
                exchange_id = ''
                if 'exchange_id' in order_info and order_info['exchange_id'] is not None:
                    exchange_id = order_info['exchange_id']
                price = 'NULL'
                if 'price' in order_info and order_info['price'] is not None:
                    price = order_info['price']
                parent_trade_order_id = -1
                if 'parent_trade_order_id' in order_info:
                    parent_trade_order_id = order_info['parent_trade_order_id']
                insert_str = "INSERT INTO sent_orders VALUES('{}', '{}', {}, {}, '{}', '{}', '{}', {}, '{}', {}, {}" \
                             ", {}, {}, {}, {}, '{}', '{}', {}, '{}')".format(
                    order_info['exchange'], order_info['action_type'], order_info['size'],
                    price, exchange_id, order_info['status'], order_info['order_time'],
                    order_info['timed_order'], order_info['currency_to'],
                    order_info['balance']['balances'][order_info['currency_from']]['available'],
                    order_info['balance']['balances'][order_info['currency_to']]['available'],
                    order_info['ask'], order_info['bid'], parent_trade_order_id, trade_order_id, order_info['user_id'],
                    order_info['external_order_id'], order_info['user_quote_price'], order_info['currency_from'])
                self.log.debug("Insert command: <%s>", insert_str)
                cur = conn.cursor()
                cur.execute(insert_str)
                conn.commit()
                return_order_id = cur.lastrowid
                self.log.debug('Inserted order <%s> with id <%s>', str(order_info), return_order_id)
            except Exception as e:
                self.log.error("DB error: <%s>", str(e))
            finally:
                conn.close()

            return return_order_id

    def get_sent_orders(self, type, orders_limit, filter):
        conn = self.create_db_connection(self._db_file)
        limit_clause = ''
        if orders_limit > 0:
            limit_clause = " LIMIT " + str(orders_limit)
        where_clause = ""

        if filter:
            if 'exchanges' in filter:
                where_clause = 'exchange in ('
                first_exchange = True
                exchange_re = re.compile('^[a-zA-Z]+$')
                for exchange in filter['exchanges']:
                    if exchange_re.match(exchange):
                        if first_exchange:
                            first_exchange = False
                        else:
                            where_clause += ', '

                        where_clause += '\'{}\''.format(exchange)
                where_clause += ') '
            if 'start_date' in filter:
                try:
                    start_date = datetime.datetime.strptime(filter['start_date'], '%Y-%m-%d %H:%M')
                    if where_clause != "":
                        where_clause += " AND "
                    where_clause += 'datetime(order_time) >= datetime(\'{}\')'.format(start_date)
                except Exception as e:
                    pass

            if 'end_date' in filter:
                try:
                    end_date = datetime.datetime.strptime(filter['end_date'], '%Y-%m-%d %H:%M')
                    if where_clause != "":
                        where_clause += " AND "
                    where_clause += 'datetime(order_time) <= datetime(\'{}\')'.format(end_date)
                except Exception as e:
                    pass

            if 'statuses' in filter:
                if where_clause != "":
                    where_clause += " AND "
                where_clause += 'status in ('
                first_status = True
                status_re = re.compile('^[a-zA-Z ]+$')
                for status in filter['statuses']:
                    if status_re.match(status):
                        if first_status:
                            first_status = False
                        else:
                            where_clause += ', '
                        where_clause += '\'{}\''.format(status)
                where_clause += ') '

            if 'types' in filter:
                if where_clause != "":
                    where_clause += " AND "
                where_clause += 'action_type in ('
                first_type = True
                type_re = re.compile('^[a-zA-Z _]+$')
                for action_type in filter['types']:
                    if type_re.match(action_type):
                        if first_type:
                            first_type = False
                        else:
                            where_clause += ', '
                        where_clause += '\'{}\''.format(action_type)
                where_clause += ') '
            
            if 'userId' in filter:
                if where_clause != "":
                    where_clause += " AND "
                where_clause += 'user_id = \'{}\''.format(filter['userId'])
            
            if 'externalOrderId' in filter:
                if where_clause != "":
                    where_clause += " AND "
                where_clause += 'external_order_id = \'{}\''.format(filter['externalOrderId'])

        if where_clause != "":
            where_clause = "WHERE {}".format(where_clause)
        query = "SELECT * FROM (SELECT rowid, * FROM sent_orders ORDER BY datetime(order_time) DESC) " + where_clause + \
                limit_clause
        sent_orders = conn.execute(query)
        data = sent_orders.fetchall()
        result = []
        conn.close()
        # add child orders to parents orders
        if type == SentOrdersType.FLAT:
            for curr_order in data:
                trade_order_id = self.get_trade_order_id(curr_order)
                order_dict = self.get_curr_order(curr_order, trade_order_id, type)
                result.append(order_dict)

        elif type == SentOrdersType.HIERARCHICAL:
            # collect all parents orders
            all_orders = {}
            for curr_order in data:
                if (curr_order[14] == -1 and type == SentOrdersType.HIERARCHICAL) or (type == SentOrdersType.FLAT):
                    trade_order_id = self.get_trade_order_id(curr_order)
                    order_dict = self.get_curr_order(curr_order, trade_order_id, type)
                    all_orders[trade_order_id] = order_dict
            for curr_order in data:
                if curr_order[14] != -1 and curr_order[14] in all_orders:
                    trade_order_id = self.get_trade_order_id(curr_order)
                    order_dict = self.get_curr_order(curr_order, trade_order_id, type)
                    all_orders.get(curr_order[14]).get('childOrders').append(order_dict)
            result = list(all_orders.values())

        return result

    def get_trade_order_id(self, curr_order):
        trade_order_id = curr_order[0]
        if curr_order[15] != -1:
            trade_order_id = curr_order[15]
        return trade_order_id

    def get_curr_order(self, curr_order, trade_order_id, type):
        exchange_id = curr_order[5]
        if exchange_id is None:
            exchange_id = ""
        if type == SentOrdersType.FLAT:
            order_dict = {'exchange': curr_order[1],
                            'action_type': curr_order[2],
                            'crypto_size': curr_order[3],
                            'price_fiat': curr_order[4],
                            'exchange_id': exchange_id,
                            'status': curr_order[6],
                            'order_time': curr_order[7],
                            'timed_order': curr_order[8],
                            'crypto_type': curr_order[9],
                            'usd_balance': curr_order[10],
                            'crypto_available': curr_order[11],
                            'ask': curr_order[12],
                            'bid': curr_order[13],
                            'parent_trade_order_id': curr_order[14],
                            'trade_order_id': trade_order_id}
        else: 
            order_dict = {'userId': curr_order[16],
                        'exchange': curr_order[1],
                        'exchangeOrderId': exchange_id,
                        'externalOrderId': curr_order[17],
                        'tradeOrderId': trade_order_id,
                        'parentOrderId': curr_order[14],
                        'actionType': curr_order[2],
                        'assetPair': curr_order[9] + "-" + curr_order[19],
                        'currencyFromAvailable': curr_order[10],
                        'currencyToAvailable': curr_order[11],
                        'size': curr_order[3],
                        'price': curr_order[4],
                        'status': curr_order[6],
                        'orderTime': curr_order[7],
                        'timedOrder': curr_order[8],
                        'ask': curr_order[12],
                        'bid': curr_order[13],
                        'userQuotePrice': curr_order[18],
                        'childOrders': []}
        return order_dict