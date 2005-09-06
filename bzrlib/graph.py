# Dijkstra's algorithm for shortest paths
# David Eppstein, UC Irvine, 4 April 2002

# http://aspn.activestate.com/ASPN/Cookbook/Python/Recipe/117228
from priodict import priorityDictionary

def dijkstra(G,start,end=None):
	"""
	Find shortest paths from the start vertex to all
	vertices nearer than or equal to the end.

	The input graph G is assumed to have the following
	representation: A vertex can be any object that can
	be used as an index into a dictionary.  G is a
	dictionary, indexed by vertices.  For any vertex v,
	G[v] is itself a dictionary, indexed by the neighbors
	of v.  For any edge v->w, G[v][w] is the length of
	the edge.  This is related to the representation in
	<http://www.python.org/doc/essays/graphs.html>
	where Guido van Rossum suggests representing graphs
	as dictionaries mapping vertices to lists of neighbors,
	however dictionaries of edges have many advantages
	over lists: they can store extra information (here,
	the lengths), they support fast existence tests,
	and they allow easy modification of the graph by edge
	insertion and removal.  Such modifications are not
	needed here but are important in other graph algorithms.
	Since dictionaries obey iterator protocol, a graph
	represented as described here could be handed without
	modification to an algorithm using Guido's representation.

	Of course, G and G[v] need not be Python dict objects;
	they can be any other object that obeys dict protocol,
	for instance a wrapper in which vertices are URLs
	and a call to G[v] loads the web page and finds its links.
	
	The output is a pair (D,P) where D[v] is the distance
	from start to v and P[v] is the predecessor of v along
	the shortest path from s to v.
	
	Dijkstra's algorithm is only guaranteed to work correctly
	when all edge lengths are positive. This code does not
	verify this property for all edges (only the edges seen
 	before the end vertex is reached), but will correctly
	compute shortest paths even for some graphs with negative
	edges, and will raise an exception if it discovers that
	a negative edge has caused it to make a mistake.
	"""

	D = {}	# dictionary of final distances
	P = {}	# dictionary of predecessors
	Q = priorityDictionary()  # est.dist. of non-final vert.
	Q[start] = 0
	
	for v in Q:
		D[v] = Q[v]
		if v == end: break
		
		for w in G[v]:
			vwLength = D[v] + G[v][w]
			if w in D:
				if vwLength < D[w]:
					raise ValueError, \
  "Dijkstra: found better path to already-final vertex"
			elif w not in Q or vwLength < Q[w]:
				Q[w] = vwLength
				P[w] = v
	
	return (D,P)
			
def shortest_path(G,start, end):
	"""
	Find a single shortest path from the given start vertex
	to the given end vertex.
	The input has the same conventions as Dijkstra().
	The output is a list of the vertices in order along
	the shortest path.
	"""

	D,P = dijkstra(G,start,end)
        print D,P
	Path = []
	while 1:
		Path.append(end)
		if end == start: break
		end = P[end]
	Path.reverse()
	return Path

def closest(distances, pending):
    closest = None
    for node in pending:
        distance = distances[node]
        if distance is None:
            continue
        if closest is None or distance < closest[1]:
            closest = (node, distance)
    return closest[0] 

def relax(node, distances, graph):
    for child in graph[node]:
        new_distance = distances[node] + graph[node][child]
        if distances[child] is None or distances[child] < new_distance:
            print "setting %s to %d, from %s(%d)" % (child, new_distance, node,
            distances[node])
            distances[child] = new_distance

def farthest_node(graph, start):
    done = set()
    distances = {}
    pending = set(graph.keys())
    for node in graph:
        distances[node] = None
    distances[start] = 0
    while len(done) < len(distances):
        node = closest(distances, pending)
        done.add(node)
        pending.remove(node)
        relax(node, distances, graph)
    print distances
    distfirst = [(d, n) for n, d in distances.iteritems()]
    return distfirst[-1][1]

def farthest_nodes_ab(graph, start):
    lines = [start]
    predecessors = {}
    endpoints = {}
    while len(lines) > 0:
        new_lines = set()
        for line in lines:
            for child in graph[line]:
                if child not in predecessors:
                    new_lines.add(child)
                predecessors[child] = line
            else:
                endpoints[line] = None
        lines = new_lines
    distances = []
    for endpoint in endpoints:
        path = []
        node = endpoint
        while node != start:
           path.append(node)
           node = predecessors[node]
        distances.append((len(path), endpoint))
    distances.sort(reverse=True)
    return [d[1] for d in distances]


def max_distance(node, ancestors, distances):
    """Calculate the max distance to an ancestor.  Return None if"""
    best = None
    if node in distances:
        best = distances[node]
    for ancestor in ancestors[node]:
        if ancestor not in distances:
            return None
        if best is None or distances[ancestor] > best:
            best = distances[ancestor] + 1
    return best

    
def farthest_node(graph, ancestors, start):
    distances = {start: 0}
    lines = set(start)
    while len(lines) > 0:
        new_lines = set()
        for line in lines:
            for descendant in graph[line]:
                distance = max_distance(descendant, ancestors, distances)
                if distance is None:
                    continue
                distances[descendant] = distance
                new_lines.add(descendant)
        lines = new_lines

    def by_distance(n):
        return distances[n]
    node_list = distances.keys()
    node_list.sort(key=by_distance, reverse=True)
    return node_list
