"""Multi-depot capacitated VRP with time deadlines and priority-based drop penalties (OR-Tools)."""
import math
from ortools.constraint_solver import pywrapcp, routing_enums_pb2
from .risk import SPEED

BIG = 10 ** 6

def haversine(a, b):
    (la1, lo1), (la2, lo2) = a, b
    p = math.pi / 180
    x = math.sin((la2 - la1) * p / 2) ** 2 + math.cos(la1 * p) * math.cos(la2 * p) * math.sin((lo2 - lo1) * p / 2) ** 2
    return 12742 * math.asin(math.sqrt(x))

def solve(depots, vehicles, drops, edge, coords, limit_s=5):
    """depots: [codes]; vehicles: [{code, depot, cap}]; drops: [{post, kg, deadline_min, penalty}];
    edge: {(depot, post): evaluated segment}; coords: {code: (lat, lon)}"""
    nd = len(depots); names = depots + [d["post"] for d in drops]; N = len(names)
    cost = [[0] * N for _ in range(N)]; km = [[0.0] * N for _ in range(N)]; tm = [[0] * N for _ in range(N)]
    for i in range(N):
        for j in range(N):
            a, b = names[i], names[j]
            if i == j or a == b:
                c = k = t = 0
            elif i < nd and j < nd:
                c, k, t = BIG, 0, BIG
            elif i < nd or j < nd:
                e = edge.get((a, b) if i < nd else (b, a))
                c, k, t = (e["cost"], e["km"], e["eta"] * 60) if e else (BIG, 0, BIG)
            else:
                k = haversine(coords[a], coords[b]) * 1.4
                c, t = k * 1.6, k / (SPEED * 0.8) * 60
            cost[i][j] = int(round(c)); km[i][j] = k; tm[i][j] = int(round(t))
    starts = [depots.index(v["depot"]) for v in vehicles]
    mgr = pywrapcp.RoutingIndexManager(N, len(vehicles), starts, starts)
    rt = pywrapcp.RoutingModel(mgr)
    cb = rt.RegisterTransitCallback(lambda i, j: cost[mgr.IndexToNode(i)][mgr.IndexToNode(j)])
    rt.SetArcCostEvaluatorOfAllVehicles(cb)
    rt.SetFixedCostOfAllVehicles(300)
    dem = rt.RegisterUnaryTransitCallback(lambda i: int(drops[mgr.IndexToNode(i) - nd]["kg"]) if mgr.IndexToNode(i) >= nd else 0)
    rt.AddDimensionWithVehicleCapacity(dem, 0, [int(v["cap"]) for v in vehicles], True, "Cap")
    tcb = rt.RegisterTransitCallback(lambda i, j: tm[mgr.IndexToNode(i)][mgr.IndexToNode(j)] + (30 if mgr.IndexToNode(i) >= nd else 0))
    rt.AddDimension(tcb, 0, 14 * 24 * 60, True, "Time")
    td = rt.GetDimensionOrDie("Time")
    for k, d in enumerate(drops):
        idx = mgr.NodeToIndex(nd + k)
        td.CumulVar(idx).SetRange(0, int(d["deadline_min"]))
        rt.AddDisjunction([idx], int(d["penalty"]))
    p = pywrapcp.DefaultRoutingSearchParameters()
    p.first_solution_strategy = routing_enums_pb2.FirstSolutionStrategy.PATH_CHEAPEST_ARC
    p.local_search_metaheuristic = routing_enums_pb2.LocalSearchMetaheuristic.GUIDED_LOCAL_SEARCH
    p.time_limit.seconds = limit_s
    sol = rt.SolveWithParameters(p)
    if not sol:
        return [], list(range(len(drops)))
    routes, served = [], set()
    for v, veh in enumerate(vehicles):
        idx = rt.Start(v); stops, dist, prev = [], 0.0, mgr.IndexToNode(idx)
        while not rt.IsEnd(idx):
            node = mgr.IndexToNode(idx)
            if node >= nd:
                stops.append({"drop": node - nd, "arrive_min": sol.Value(td.CumulVar(idx))}); served.add(node - nd)
            idx = sol.Value(rt.NextVar(idx)); nxt = mgr.IndexToNode(idx)
            dist += km[node][nxt]
        if stops:
            routes.append({"vehicle": veh, "stops": stops, "km": round(dist, 1)})
    return routes, [k for k in range(len(drops)) if k not in served]
