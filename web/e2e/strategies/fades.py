
import numpy as np
from datamodel import Order

class Trader:
    def run(self, state):
        depth = state.order_depths["TELLURIUM"]
        if not depth.buy_orders or not depth.sell_orders:
            return {}, 0, state.traderData
        mid = (max(depth.buy_orders) + min(depth.sell_orders)) / 2
        history = [float(x) for x in state.traderData.split(",") if x][-20:] + [mid]
        position = state.position.get("TELLURIUM", 0)
        orders = []
        if mid > np.mean(history) + 3 and position > -10:
            orders.append(Order("TELLURIUM", max(depth.buy_orders), -1))
        elif mid < np.mean(history) - 3 and position < 10:
            orders.append(Order("TELLURIUM", min(depth.sell_orders), 1))
        return {"TELLURIUM": orders}, 0, ",".join(map(str, history))
