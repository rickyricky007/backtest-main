import kite_data as kd

kite = kd.kite_client()

margins = kite.margins()
print("Funds:", margins)
holdings = kite.holdings()
print("Holdings:", holdings)
positions = kite.positions()
print("Positions:", positions)
