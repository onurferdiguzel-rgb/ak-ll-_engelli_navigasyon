import geopandas as gpd
import networkx as nx
import math
from flask import Flask, request, jsonify, render_template_string
from shapely.geometry import Point, LineString
from shapely.ops import unary_union
from itertools import islice

# =========================
# SHAPEFILE
# =========================
gdf = gpd.read_file("engelli.shp")

try:
    gdf = gdf.to_crs(epsg=4326)
except:
    pass

network_geom = unary_union(gdf.geometry)

# =========================
# MESAFE (METRE)
# =========================
def haversine(a, b):
    lon1, lat1 = a
    lon2, lat2 = b

    R = 6371000
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)

    x = math.sin(dlat/2)**2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon/2)**2
    return 2 * R * math.asin(math.sqrt(x))

# =========================
# GRAPH
# =========================
G = nx.Graph()
edges_list = []

def add_line(line):
    coords = list(line.coords)
    for i in range(len(coords)-1):
        a = coords[i]
        b = coords[i+1]

        G.add_edge(a, b, weight=haversine(a, b))
        edges_list.append((a, b))

for geom in gdf.geometry:
    if geom is None:
        continue

    if geom.geom_type == "LineString":
        add_line(geom)

    elif geom.geom_type == "MultiLineString":
        for line in geom:
            add_line(line)

print("Graph hazır:", len(G.nodes), "node,", len(G.edges), "edge")

# =========================
# PROJE DIŞI (10m)
# =========================
MAX_DIST = 10

def is_valid(p):
    return network_geom.distance(Point(p)) * 111000 < MAX_DIST

# =========================
# SNAP + EDGE SPLIT
# =========================
def snap_and_insert(graph, p):

    point = Point(p)
    nearest_line = None
    min_dist = float("inf")

    for (a, b) in edges_list:
        line = LineString([a, b])
        d = line.distance(point)

        if d < min_dist:
            min_dist = d
            nearest_line = (a, b)

    a, b = nearest_line
    line = LineString([a, b])

    proj_point = line.interpolate(line.project(point))
    snapped = (proj_point.x, proj_point.y)

    if graph.has_edge(a, b):
        graph.remove_edge(a, b)

    graph.add_node(snapped)
    graph.add_edge(a, snapped, weight=haversine(a, snapped))
    graph.add_edge(snapped, b, weight=haversine(snapped, b))

    return snapped

def path_distance(path):
    dist = 0
    for i in range(1, len(path)):
        dist += haversine(path[i-1], path[i])
    return dist

# =========================
# ROUTE
# =========================
def shortest_routes(start, end):

    if not is_valid(start):
        return "outside", None, None, None, None

    if not is_valid(end):
        return "outside", None, None, None, None

    temp_G = G.copy()

    s_snap = snap_and_insert(temp_G, start)
    e_snap = snap_and_insert(temp_G, end)

    try:
        paths = list(islice(nx.shortest_simple_paths(temp_G, s_snap, e_snap, weight="weight"), 2))

        path1 = paths[0]
        dist1 = path_distance(path1)

        path2 = None
        dist2 = None

        if len(paths) > 1:
            path2 = paths[1]
            dist2 = path_distance(path2)

        return "ok", path1, dist1, path2, dist2

    except:
        return "fail", None, None, None, None

# =========================
# FLASK
# =========================
app = Flask(__name__)

HTML = """
<!DOCTYPE html>
<html>
<head>
<link rel="stylesheet" href="https://unpkg.com/leaflet/dist/leaflet.css"/>
<style>#map{height:600px}</style>
</head>
<body>

<h3>Engelli Navigasyon Sistemi</h3>
<div id="map"></div>

<script src="https://unpkg.com/leaflet/dist/leaflet.js"></script>

<script>

var map = L.map('map').setView([39.75,37.01],13);

L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png').addTo(map);

let pts = [];
let markers = [];
let line1 = null;
let line2 = null;
let popup = null;

fetch("/geojson")
.then(r=>r.json())
.then(d=>{
    L.geoJSON(d,{color:"red"}).addTo(map);
});

function clearAll(){

    markers.forEach(m => map.removeLayer(m));
    markers = [];

    if(line1){
        map.removeLayer(line1);
        line1 = null;
    }

    if(line2){
        map.removeLayer(line2);
        line2 = null;
    }

    if(popup){
        map.closePopup();
        popup = null;
    }

    pts = [];
}

map.on('click', function(e){

    let p = [e.latlng.lng, e.latlng.lat];

    markers.push(L.marker(e.latlng).addTo(map));
    pts.push(p);

    if(pts.length == 2){

        fetch(`/route?sx=${pts[0][0]}&sy=${pts[0][1]}&ex=${pts[1][0]}&ey=${pts[1][1]}`)
        .then(r=>r.json())
        .then(d=>{

            if(d.status=="outside"){
                alert("🚫 Proje dışı (10 metre)");
                clearAll();
                return;
            }

            if(d.status!="ok"){
                alert("Rota bulunamadı");
                clearAll();
                return;
            }

            let l1 = d.path.map(p=>[p[1],p[0]]);

            clearAll();

            line1 = L.polyline(l1,{
                color:"blue",
                weight:4
            }).addTo(map);

            let popupText = "1. rota: " + Math.round(d.distance) + " metre";

            if(d.path2){
                let l2 = d.path2.map(p=>[p[1],p[0]]);

                line2 = L.polyline(l2,{
                    color:"green",
                    weight:4,
                    dashArray:"8,8"
                }).addTo(map);

                popupText += "<br>2. rota: " + Math.round(d.distance2) + " metre";
            } else {
                popupText += "<br>2. rota bulunamadı";
            }

            popup = L.popup()
                .setLatLng(l1[Math.floor(l1.length/2)])
                .setContent(popupText)
                .openOn(map);

        });

    }

});

</script>

</body>
</html>
"""

@app.route("/")
def home():
    return render_template_string(HTML)

@app.route("/route")
def route():
    sx = float(request.args.get("sx"))
    sy = float(request.args.get("sy"))
    ex = float(request.args.get("ex"))
    ey = float(request.args.get("ey"))

    status, path1, dist1, path2, dist2 = shortest_routes((sx,sy),(ex,ey))

    return jsonify({
        "status": status,
        "path": path1,
        "distance": dist1,
        "path2": path2,
        "distance2": dist2
    })

@app.route("/geojson")
def geojson():
    return gdf.to_json()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)