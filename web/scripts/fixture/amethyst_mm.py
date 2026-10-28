from datamodel import Order


class Trader:
    def run(self, state):
        depth = state.order_depths.get("AMETHYST")
        if depth is None:
            return {}, 0, ""
        position = state.position.get("AMETHYST", 0)
        orders = []
        if position < 50:
            orders.append(Order("AMETHYST", 9999, min(10, 50 - position)))
        if position > -50:
            orders.append(Order("AMETHYST", 10001, -min(10, 50 + position)))
        return {"AMETHYST": orders}, 0, ""
